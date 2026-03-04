"""
Tool consultar_cliente - Consulta unificada de cliente

Substitui:
- buscar_cobrancas (financeiro)
- identificar_equipamento (contratos/equipamentos)

Retorna dados completos do cliente:
- Dados pessoais (nome, cpf, telefone, email)
- Situação financeira (cobranças pendentes e atrasadas)
- Contratos (vigência, valor mensal, prazo)
- Equipamentos alugados e status de manutenção
"""

import logging
import re
from typing import Dict, Any, Optional, List
from datetime import date, datetime

from supabase import create_client
from app.config import settings

logger = logging.getLogger(__name__)


# ============================================================================
# FUNCTION DECLARATION - Formato Gemini (dict puro)
# ============================================================================

CONSULTAR_CLIENTE_DECLARATION = {
    "name": "consultar_cliente",
    "description": (
        "Consulta completa do cliente: dados pessoais, situacao financeira (cobrancas pendentes e atrasadas), "
        "contratos (vigencia, valor mensal, prazo), equipamentos alugados e status de manutencao. "
        "Use quando o cliente perguntar sobre: pagamento, boleto, pix, fatura, segunda via, "
        "valor da parcela, parcelas atrasadas, quanto deve, contrato, quando acaba, vigencia, "
        "equipamentos, qual ar tem, manutencao, ou qualquer informacao sobre sua conta. "
        "Se o cliente NAO recebeu cobranca recente (nao veio por disparo), pergunte o CPF primeiro. "
        "Se o cliente veio por disparo de cobranca, use sem CPF (busca pelo telefone). "
        "IMPORTANTE: Se o cliente AFIRMAR que ja pagou (ex: 'ja paguei', 'paguei ontem', 'acabei de pagar'), "
        "use verificar_pagamento=true para confirmar pagamentos recentes."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "cpf": {
                "type": "string",
                "description": "CPF ou CNPJ do cliente (apenas numeros, 11 ou 14 digitos). Obrigatorio se o cliente nao recebeu cobranca recente."
            },
            "verificar_pagamento": {
                "type": "boolean",
                "description": "Se true, busca faturas recentemente pagas para confirmar pagamento. Use quando o cliente afirmar que ja pagou."
            }
        },
        "required": []
    }
}


# ============================================================================
# HANDLER PRINCIPAL
# ============================================================================

async def consultar_cliente(
    cpf: Optional[str] = None,
    telefone: Optional[str] = None,
    agent_id: Optional[str] = None,
    verificar_pagamento: bool = False
) -> Dict[str, Any]:
    """
    Consulta unificada do cliente.

    Args:
        cpf: CPF do cliente (opcional se veio por disparo)
        telefone: Telefone do cliente (do contexto remotejid)
        agent_id: ID do agente para isolamento
        verificar_pagamento: Se True, busca faturas pagas recentemente para confirmar pagamento

    Returns:
        Dict com dados completos do cliente ou mensagem de erro
    """
    try:
        logger.info(f"[CONSULTAR_CLIENTE] ========== INICIO ==========")
        logger.info(f"[CONSULTAR_CLIENTE] cpf={cpf}, telefone={telefone}, agent_id={agent_id}")

        # Conectar ao Supabase
        supabase = create_client(settings.supabase_url, settings.supabase_service_key)

        # ================================================================
        # PASSO 1: Encontrar customer_id
        # ================================================================
        customer_id = None
        customer_data = None
        cpf_limpo = None

        # 1.1 Se tem CPF, buscar em asaas_clientes
        if cpf:
            cpf_limpo = re.sub(r'\D', '', cpf)
            if len(cpf_limpo) not in [11, 14]:
                return {
                    "sucesso": False,
                    "encontrou": False,
                    "mensagem": "CPF invalido. Informe apenas os numeros (11 digitos)."
                }

            logger.debug(f"[CONSULTAR_CLIENTE] Buscando por CPF: {cpf_limpo}")
            query = supabase.table("asaas_clientes").select(
                "id, name, cpf_cnpj, mobile_phone, email"
            ).eq("cpf_cnpj", cpf_limpo).is_("deleted_at", "null")

            if agent_id:
                query = query.eq("agent_id", agent_id)

            result = query.execute()

            if result.data:
                customer_data = result.data[0]
                customer_id = customer_data["id"]
                logger.info(f"[CONSULTAR_CLIENTE] Cliente encontrado por CPF: {customer_id}")
            else:
                # Fallback: buscar incluindo clientes deletados no Asaas
                query_deleted = supabase.table("asaas_clientes").select(
                    "id, name, cpf_cnpj, mobile_phone, email"
                ).eq("cpf_cnpj", cpf_limpo)
                if agent_id:
                    query_deleted = query_deleted.eq("agent_id", agent_id)
                result_deleted = query_deleted.execute()
                if result_deleted.data:
                    customer_data = result_deleted.data[0]
                    customer_id = customer_data["id"]
                    logger.info(f"[CONSULTAR_CLIENTE] Cliente encontrado por CPF (deletado no Asaas): {customer_id}")

        # 1.2 Se não encontrou por CPF, tentar por telefone (cliente veio por disparo)
        if not customer_id and telefone:
            logger.debug(f"[CONSULTAR_CLIENTE] CPF não encontrado, tentando por telefone: {telefone}")

            # Normalizar telefone (remover 55, pegar últimos 11 dígitos)
            telefone_limpo = re.sub(r'\D', '', telefone)
            if telefone_limpo.startswith("55"):
                telefone_limpo = telefone_limpo[2:]

            # Buscar em billing_notifications pelo telefone
            telefones_busca = [telefone_limpo]
            if not telefone_limpo.startswith("55"):
                telefones_busca.append(f"55{telefone_limpo}")

            for tel in telefones_busca:
                result = supabase.table("billing_notifications").select(
                    "customer_id, customer_name, phone"
                ).eq("phone", tel).order("sent_at", desc=True).limit(1).execute()

                if result.data:
                    notification = result.data[0]
                    customer_id = notification.get("customer_id")

                    # Buscar dados completos do cliente em asaas_clientes
                    if customer_id:
                        cliente_res = supabase.table("asaas_clientes").select(
                            "id, name, cpf_cnpj, mobile_phone, email"
                        ).eq("id", customer_id).execute()

                        if cliente_res.data:
                            customer_data = cliente_res.data[0]
                            logger.info(f"[CONSULTAR_CLIENTE] Cliente encontrado por telefone via billing_notifications: {customer_id}")
                            break
                        else:
                            # Usar dados da notificação se não encontrar em asaas_clientes
                            customer_data = {
                                "id": customer_id,
                                "name": notification.get("customer_name"),
                                "mobile_phone": tel
                            }
                            logger.info(f"[CONSULTAR_CLIENTE] Cliente encontrado parcialmente por telefone: {customer_id}")
                            break

        # 1.3 Se ainda não encontrou cliente
        if not customer_id:
            if cpf:
                return {
                    "sucesso": False,
                    "encontrou": False,
                    "mensagem": "Nao encontrei cadastro com esse CPF/CNPJ. Verifique se digitou corretamente."
                }
            else:
                return {
                    "sucesso": False,
                    "encontrou": False,
                    "mensagem": "Para localizar seu cadastro, por favor informe seu CPF ou CNPJ."
                }

        # ================================================================
        # PASSO 2: Buscar cobranças
        # ================================================================
        logger.debug(f"[CONSULTAR_CLIENTE] Buscando cobrancas para customer_id={customer_id}, verificar_pagamento={verificar_pagamento}")

        # ----------------------------------------------------------------
        # 2.1 Se verificar_pagamento=True, buscar faturas pagas recentemente
        # ----------------------------------------------------------------
        faturas_pagas = []
        payment_ids_encontrados = set()  # Para evitar duplicatas

        if verificar_pagamento:
            logger.debug("[CONSULTAR_CLIENTE] Buscando faturas pagas recentemente...")

            from datetime import timedelta
            data_limite = (date.today() - timedelta(days=30)).isoformat()

            # ---- Estratégia 1: billing_notifications com status "paid" (mais rápido) ----
            # Quando a IA enviou cobrança e o webhook confirmou pagamento
            if telefone:
                telefone_limpo = re.sub(r'\D', '', telefone)
                if telefone_limpo.startswith("55"):
                    telefone_limpo = telefone_limpo[2:]

                notif_result = supabase.table("billing_notifications").select(
                    "payment_id, customer_name, valor, due_date, updated_at"
                ).eq("phone", telefone_limpo).eq("status", "paid").order(
                    "updated_at", desc=True
                ).limit(3).execute()

                for notif in (notif_result.data or []):
                    payment_id = notif.get("payment_id")
                    if payment_id and payment_id not in payment_ids_encontrados:
                        payment_ids_encontrados.add(payment_id)
                        valor = float(notif.get("valor") or 0)
                        faturas_pagas.append({
                            "valor": f"R$ {valor:.2f}",
                            "vencimento": notif.get("due_date"),
                            "status": "Paga",
                            "data_pagamento": str(notif.get("updated_at"))[:10] if notif.get("updated_at") else None,
                            "cobrado_pela_ia": True,  # Veio de billing_notifications
                            "link_comprovante": ""
                        })
                        logger.info(f"[CONSULTAR_CLIENTE] Pagamento encontrado via billing_notifications: {payment_id}")

            # ---- Estratégia 2: asaas_cobrancas com status RECEIVED/CONFIRMED ----
            query_pagas = supabase.table("asaas_cobrancas").select(
                "id, value, due_date, status, payment_date, ia_recebeu, ia_recebeu_at, invoice_url"
            ).eq("customer_id", customer_id).in_(
                "status", ["RECEIVED", "CONFIRMED", "RECEIVED_IN_CASH"]
            ).is_("deleted_at", "null")

            if agent_id:
                query_pagas = query_pagas.eq("agent_id", agent_id)

            # Ordenar por data de pagamento mais recente primeiro
            result_pagas = query_pagas.order("payment_date", desc=True).limit(5).execute()

            for cob in (result_pagas.data or []):
                payment_id = cob.get("id")
                if payment_id in payment_ids_encontrados:
                    continue  # Já adicionado via billing_notifications

                # Filtrar apenas pagamentos dos últimos 30 dias
                payment_date = cob.get("payment_date")
                if payment_date and payment_date < data_limite:
                    continue

                valor = float(cob.get("value") or 0)
                payment_ids_encontrados.add(payment_id)

                faturas_pagas.append({
                    "valor": f"R$ {valor:.2f}",
                    "vencimento": cob.get("due_date"),
                    "status": "Paga",
                    "data_pagamento": payment_date,
                    "cobrado_pela_ia": cob.get("ia_recebeu", False),
                    "link_comprovante": cob.get("invoice_url", "")
                })

            logger.info(f"[CONSULTAR_CLIENTE] Faturas pagas encontradas: {len(faturas_pagas)}")

        # ----------------------------------------------------------------
        # 2.2 Buscar cobranças pendentes/atrasadas
        # ----------------------------------------------------------------
        query = supabase.table("asaas_cobrancas").select(
            "id, value, due_date, status, invoice_url, bank_slip_url, dias_atraso, billing_type"
        ).eq("customer_id", customer_id).in_(
            "status", ["PENDING", "OVERDUE"]
        ).is_("deleted_at", "null")

        if agent_id:
            query = query.eq("agent_id", agent_id)

        result = query.order("due_date", desc=False).limit(10).execute()
        cobrancas_raw = result.data or []

        # Processar cobranças pendentes
        cobrancas_atrasadas = 0
        valor_atrasado = 0.0
        cobrancas_a_vencer = 0
        valor_a_vencer = 0.0
        lista_cobrancas = []

        for cob in cobrancas_raw:
            valor = float(cob.get("value") or 0)

            if cob.get("status") == "OVERDUE":
                cobrancas_atrasadas += 1
                valor_atrasado += valor
            else:
                cobrancas_a_vencer += 1
                valor_a_vencer += valor

            lista_cobrancas.append({
                "valor": f"R$ {valor:.2f}",
                "vencimento": cob.get("due_date"),
                "status": "Vencida" if cob.get("status") == "OVERDUE" else "Pendente",
                "dias_atraso": cob.get("dias_atraso") or 0,
                "link_pagamento": cob.get("invoice_url", "")
            })

        total_devedor = valor_atrasado + valor_a_vencer

        logger.info(f"[CONSULTAR_CLIENTE] Cobrancas pendentes: {len(cobrancas_raw)} (atrasadas={cobrancas_atrasadas}, a_vencer={cobrancas_a_vencer})")

        # ================================================================
        # PASSO 3: Buscar contratos e equipamentos
        # ================================================================
        logger.debug(f"[CONSULTAR_CLIENTE] Buscando contratos para customer_id={customer_id}")

        query = supabase.table("contract_details").select(
            "id, numero_contrato, data_inicio, data_termino, prazo_meses, valor_mensal, "
            "dia_vencimento, renovacao_automatica, endereco_instalacao, "
            "equipamentos, qtd_ars, proxima_manutencao, maintenance_status, maintenance_type, "
            "problema_relatado, observacoes"
        ).eq("customer_id", customer_id)

        if agent_id:
            query = query.eq("agent_id", agent_id)

        result = query.execute()
        contratos_raw = result.data or []

        total_equipamentos = 0
        contratos_formatados = []

        for contrato in contratos_raw:
            # Calcular meses restantes
            meses_restantes = None
            if contrato.get("data_termino"):
                try:
                    data_termino = date.fromisoformat(str(contrato["data_termino"]))
                    dias_restantes = (data_termino - date.today()).days
                    meses_restantes = max(0, dias_restantes // 30)
                except (ValueError, TypeError):
                    pass

            # Extrair equipamentos do JSONB
            equipamentos_raw = contrato.get("equipamentos") or []
            if not isinstance(equipamentos_raw, list):
                equipamentos_raw = []

            equipamentos_formatados = []
            for eq in equipamentos_raw:
                if isinstance(eq, dict):
                    equipamentos_formatados.append({
                        "marca": eq.get("marca", "N/I"),
                        "modelo": eq.get("modelo", "N/I"),
                        "btus": eq.get("btus", 0),
                        "patrimonio": eq.get("patrimonio", ""),
                        "contract_id": contrato["id"]
                    })
                    total_equipamentos += 1

            # Formatar valor mensal
            valor_mensal = contrato.get("valor_mensal")
            if valor_mensal:
                valor_mensal_fmt = f"R$ {float(valor_mensal):.2f}"
            else:
                valor_mensal_fmt = "N/I"

            contratos_formatados.append({
                "numero": contrato.get("numero_contrato"),
                "data_inicio": contrato.get("data_inicio"),
                "data_termino": contrato.get("data_termino"),
                "prazo_meses": contrato.get("prazo_meses"),
                "meses_restantes": meses_restantes,
                "valor_mensal": valor_mensal_fmt,
                "dia_vencimento": contrato.get("dia_vencimento"),
                "renovacao_automatica": contrato.get("renovacao_automatica"),
                "endereco_instalacao": contrato.get("endereco_instalacao"),
                "equipamentos": equipamentos_formatados,
                "manutencao": {
                    "proxima": contrato.get("proxima_manutencao"),
                    "status": contrato.get("maintenance_status", "pending"),
                    "tipo": contrato.get("maintenance_type", "preventiva")
                }
            })

        logger.info(f"[CONSULTAR_CLIENTE] Contratos: {len(contratos_formatados)}, Equipamentos: {total_equipamentos}")

        # ================================================================
        # PASSO 4: Montar retorno unificado
        # ================================================================

        # Montar dados do cliente
        cliente_info = {
            "nome": customer_data.get("name") if customer_data else "Cliente",
            "cpf": customer_data.get("cpf_cnpj") if customer_data else None,
            "telefone": customer_data.get("mobile_phone") if customer_data else telefone,
            "email": customer_data.get("email") if customer_data else None
        }

        # Montar mensagem resumo
        nome = cliente_info["nome"] or "Cliente"
        partes_msg = []

        # Se verificando pagamento e encontrou faturas pagas, priorizar essa info
        if verificar_pagamento and faturas_pagas:
            ultima_paga = faturas_pagas[0]
            msg_financeiro = (
                f"Confirmado! {nome} tem pagamento registrado: "
                f"fatura de {ultima_paga['vencimento']} no valor de {ultima_paga['valor']} foi paga"
            )
            if ultima_paga.get("data_pagamento"):
                msg_financeiro += f" em {ultima_paga['data_pagamento']}"
            msg_financeiro += "."

            # Se ainda tem pendências, mencionar
            if cobrancas_atrasadas > 0 or cobrancas_a_vencer > 0:
                msg_financeiro += f" Obs: ainda restam {cobrancas_atrasadas + cobrancas_a_vencer} fatura(s) em aberto (R$ {total_devedor:.2f})."
        elif verificar_pagamento and not faturas_pagas:
            # Verificando pagamento mas não encontrou nada pago recentemente
            if cobrancas_atrasadas > 0:
                partes_msg.append(f"{cobrancas_atrasadas} fatura(s) vencida(s) (R$ {valor_atrasado:.2f})")
            if cobrancas_a_vencer > 0:
                partes_msg.append(f"{cobrancas_a_vencer} fatura(s) a vencer (R$ {valor_a_vencer:.2f})")

            if partes_msg:
                msg_financeiro = (
                    f"Nao encontrei pagamento recente para {nome}. "
                    f"Situacao atual: " + " e ".join(partes_msg) + f". Total: R$ {total_devedor:.2f}."
                )
            else:
                msg_financeiro = f"{nome} esta em dia! Nao ha faturas pendentes."
        else:
            # Fluxo normal (sem verificar pagamento)
            if cobrancas_atrasadas > 0:
                partes_msg.append(f"{cobrancas_atrasadas} fatura(s) vencida(s) (R$ {valor_atrasado:.2f})")
            if cobrancas_a_vencer > 0:
                partes_msg.append(f"{cobrancas_a_vencer} fatura(s) a vencer (R$ {valor_a_vencer:.2f})")

            if partes_msg:
                msg_financeiro = f"{nome} tem " + " e ".join(partes_msg) + f". Total: R$ {total_devedor:.2f}."
            else:
                msg_financeiro = f"{nome} esta em dia!"

        if contratos_formatados:
            primeiro_contrato = contratos_formatados[0]
            if primeiro_contrato.get("meses_restantes") is not None:
                msg_contrato = f" Contrato {primeiro_contrato['numero']} com {total_equipamentos} equipamento(s), {primeiro_contrato['meses_restantes']} meses restantes."
            else:
                msg_contrato = f" Contrato {primeiro_contrato['numero']} com {total_equipamentos} equipamento(s)."
        else:
            msg_contrato = ""

        mensagem = msg_financeiro + msg_contrato

        # Link de pagamento (se tiver cobranças)
        link_pagamento = lista_cobrancas[0]["link_pagamento"] if lista_cobrancas else None
        if link_pagamento and total_devedor > 0:
            mensagem += f" Link: {link_pagamento}"

        logger.info(f"[CONSULTAR_CLIENTE] customer_id={customer_id}, cobrancas={len(lista_cobrancas)}, contratos={len(contratos_formatados)}")

        return {
            "sucesso": True,
            "encontrou": True,

            "cliente": cliente_info,

            "financeiro": {
                "cobrancas_atrasadas": cobrancas_atrasadas,
                "valor_atrasado": f"R$ {valor_atrasado:.2f}",
                "cobrancas_a_vencer": cobrancas_a_vencer,
                "valor_a_vencer": f"R$ {valor_a_vencer:.2f}",
                "total_devedor": f"R$ {total_devedor:.2f}",
                "cobrancas": lista_cobrancas,
                "faturas_pagas_recentes": faturas_pagas if verificar_pagamento else [],
                "pagamento_confirmado": len(faturas_pagas) > 0 if verificar_pagamento else None
            },

            "contratos": contratos_formatados,

            "total_equipamentos": total_equipamentos,

            "mensagem": mensagem
        }

    except Exception as e:
        logger.error(f"[CONSULTAR_CLIENTE] Erro: {e}", exc_info=True)
        return {
            "sucesso": False,
            "mensagem": "Erro ao consultar dados do cliente. Tente novamente ou entre em contato com o financeiro."
        }
