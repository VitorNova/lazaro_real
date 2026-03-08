"""
Billing context module for customer payment data.

Extracted from mensagens.py (Phase 2.4)
Functions: get_billing_data_for_context, build_billing_context_prompt
"""

import json
import logging
import re
from typing import Any, Dict, Optional

from app.services.redis import get_redis_service
from app.services.supabase import SupabaseService

logger = logging.getLogger(__name__)


async def get_billing_data_for_context(
    supabase: SupabaseService,
    phone: str,
    table_leads: Optional[str] = None,
    remotejid: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Busca dados do cliente para contexto de cobrança.

    Ordem de busca:
    1. Cache Redis (TTL 5 minutos)
    2. Via lead.asaas_customer_id (mais confiável, funciona mesmo se cliente responder de outro telefone)
    3. Via billing_notifications pelo telefone (fallback)

    Args:
        supabase: Instância do SupabaseService
        phone: Telefone do cliente (formato 55XXXXXXXXXXX)
        table_leads: Nome da tabela de leads (opcional, para busca via lead)
        remotejid: RemoteJID do cliente (opcional, para busca via lead)

    Returns:
        Dict com dados do cliente ou None se não encontrar
        {
            "cliente_nome": str,
            "cliente_cpf": str,
            "customer_id": str,
            "cobrancas_pendentes": List[Dict],
            "contratos": List[Dict],
            "equipamentos": List[Dict],
        }
    """
    print(f"[BILLING CONTEXT] Buscando dados do cliente via phone={phone}", flush=True)

    if not phone:
        print(f"[BILLING CONTEXT] phone vazio", flush=True)
        return None

    # ================================================================
    # CACHE: Verificar se já temos dados em cache (TTL 5 min)
    # ================================================================
    cache_key = f"billing_context:{phone}"
    try:
        redis_service = await get_redis_service()
        cached = await redis_service.client.get(cache_key)
        if cached:
            print(f"[BILLING CONTEXT] Cache HIT para {phone}", flush=True)
            return json.loads(cached)
    except Exception as e:
        logger.warning(f"[BILLING CONTEXT] Erro ao buscar cache: {e}")

    try:
        customer_id = None
        customer_name = None
        lead_billing_context = None

        # ================================================================
        # ESTRATÉGIA 1: Buscar via lead (asaas_customer_id + billing_context)
        # Funciona mesmo se cliente responder de telefone diferente
        # ================================================================
        if table_leads and remotejid:
            try:
                lead_result = supabase.client.table(table_leads).select(
                    "id, nome, asaas_customer_id, billing_context"
                ).eq("remotejid", remotejid).limit(1).execute()

                if lead_result.data:
                    lead = lead_result.data[0]
                    customer_id = lead.get("asaas_customer_id")
                    customer_name = lead.get("nome")
                    lead_billing_context = lead.get("billing_context")

                    if customer_id:
                        print(f"[BILLING CONTEXT] Encontrado via lead.asaas_customer_id: {customer_id}", flush=True)
                    if lead_billing_context:
                        print(f"[BILLING CONTEXT] Lead tem billing_context salvo", flush=True)
            except Exception as e:
                logger.warning(f"[BILLING CONTEXT] Erro ao buscar lead: {e}")

        # ================================================================
        # ESTRATÉGIA 2: Usar billing_context do lead (se disponível)
        # ================================================================
        if not customer_id and lead_billing_context:
            customer_id = lead_billing_context.get("customer_id")
            customer_name = lead_billing_context.get("customer_name") or customer_name
            if customer_id:
                print(f"[BILLING CONTEXT] Encontrado via lead.billing_context: {customer_id}", flush=True)

        # ================================================================
        # ESTRATÉGIA 3: Fallback para billing_notifications pelo telefone
        # ================================================================
        if not customer_id:
            # Normalizar telefone (remover 55, pegar últimos 11 dígitos)
            telefone_limpo = re.sub(r'\D', '', phone)
            if telefone_limpo.startswith("55"):
                telefone_limpo = telefone_limpo[2:]

            # Tentar com e sem 55
            telefones_busca = [telefone_limpo]
            if not telefone_limpo.startswith("55"):
                telefones_busca.append(f"55{telefone_limpo}")

            # Buscar em billing_notifications pelo telefone
            for tel in telefones_busca:
                result = supabase.client.table("billing_notifications").select(
                    "customer_id, customer_name, phone"
                ).eq("phone", tel).order("sent_at", desc=True).limit(1).execute()

                if result.data:
                    notification = result.data[0]
                    customer_id = notification.get("customer_id")
                    customer_name = notification.get("customer_name") or customer_name
                    print(f"[BILLING CONTEXT] Encontrado via billing_notifications: customer_id={customer_id}", flush=True)
                    break

        # ================================================================
        # ESTRATÉGIA 4: Fallback para mobile_phone em asaas_clientes
        # ================================================================
        if not customer_id:
            # Reutilizar telefone_limpo e telefones_busca já definidos acima
            for tel in telefones_busca:
                try:
                    result = supabase.client.table("asaas_clientes").select(
                        "id, name, cpf_cnpj, mobile_phone, email"
                    ).eq("mobile_phone", tel).is_("deleted_at", "null").limit(1).execute()

                    if result.data:
                        cliente = result.data[0]
                        customer_id = cliente.get("id")
                        customer_name = cliente.get("name") or customer_name
                        print(f"[BILLING CONTEXT] Encontrado via mobile_phone ({tel}): customer_id={customer_id}", flush=True)
                        break
                except Exception as e:
                    logger.warning(f"[BILLING CONTEXT] Erro ao buscar por mobile_phone: {e}")

        if not customer_id:
            print(f"[BILLING CONTEXT] Cliente não encontrado (nem via lead, nem via billing_context, nem via billing_notifications, nem via mobile_phone)", flush=True)
            return None

        # ================================================================
        # Salvar asaas_customer_id no lead (para próximas interações)
        # ================================================================
        if customer_id and table_leads and remotejid:
            try:
                # Verificar se lead já tem customer_id
                lead_check = supabase.client.table(table_leads).select(
                    "id, asaas_customer_id"
                ).eq("remotejid", remotejid).limit(1).execute()

                if lead_check.data and not lead_check.data[0].get("asaas_customer_id"):
                    supabase.client.table(table_leads).update({
                        "asaas_customer_id": customer_id
                    }).eq("remotejid", remotejid).execute()
                    print(f"[BILLING CONTEXT] asaas_customer_id={customer_id} salvo no lead", flush=True)
            except Exception as e:
                logger.warning(f"[BILLING CONTEXT] Erro ao salvar asaas_customer_id no lead: {e}")

        # Buscar dados completos do cliente em asaas_clientes
        cliente_data = {}
        try:
            cliente_res = supabase.client.table("asaas_clientes").select(
                "id, name, cpf_cnpj, mobile_phone, email"
            ).eq("id", customer_id).maybe_single().execute()

            if cliente_res.data:
                cliente_data = cliente_res.data
                customer_name = cliente_data.get("name") or customer_name
                print(f"[BILLING CONTEXT] Dados do cliente: {customer_name}", flush=True)
        except Exception as e:
            logger.warning(f"[BILLING CONTEXT] Erro ao buscar asaas_clientes: {e}")

        # Buscar cobranças pendentes/atrasadas
        cobrancas = []
        try:
            cob_res = supabase.client.table("asaas_cobrancas").select(
                "id, value, due_date, status, invoice_url, billing_type"
            ).eq("customer_id", customer_id).in_(
                "status", ["PENDING", "OVERDUE"]
            ).is_("deleted_at", "null").order("due_date", desc=False).limit(5).execute()

            for cob in (cob_res.data or []):
                cobrancas.append({
                    "valor": float(cob.get("value") or 0),
                    "vencimento": cob.get("due_date"),
                    "status": "Vencida" if cob.get("status") == "OVERDUE" else "Pendente",
                    "link": cob.get("invoice_url", ""),
                })
            print(f"[BILLING CONTEXT] {len(cobrancas)} cobrança(s) pendente(s)", flush=True)
        except Exception as e:
            logger.warning(f"[BILLING CONTEXT] Erro ao buscar cobranças: {e}")

        # Buscar contratos e equipamentos
        contratos = []
        equipamentos = []
        try:
            contr_res = supabase.client.table("contract_details").select(
                "id, numero_contrato, data_termino, valor_mensal, endereco_instalacao, equipamentos"
            ).eq("customer_id", customer_id).execute()

            for contr in (contr_res.data or []):
                contratos.append({
                    "numero": contr.get("numero_contrato"),
                    "termino": contr.get("data_termino"),
                    "valor_mensal": float(contr.get("valor_mensal") or 0),
                    "endereco": contr.get("endereco_instalacao"),
                })
                # Extrair equipamentos
                eqs = contr.get("equipamentos") or []
                for eq in eqs:
                    if isinstance(eq, dict):
                        equipamentos.append({
                            "marca": eq.get("marca", "N/I"),
                            "modelo": eq.get("modelo", "N/I"),
                            "btus": eq.get("btus", 0),
                            "patrimonio": eq.get("patrimonio", ""),
                        })
            print(f"[BILLING CONTEXT] {len(contratos)} contrato(s), {len(equipamentos)} equipamento(s)", flush=True)
        except Exception as e:
            logger.warning(f"[BILLING CONTEXT] Erro ao buscar contratos: {e}")

        data = {
            "customer_id": customer_id,
            "cliente_nome": customer_name or "Cliente",
            "cliente_cpf": cliente_data.get("cpf_cnpj"),
            "cliente_email": cliente_data.get("email"),
            "cobrancas_pendentes": cobrancas,
            "contratos": contratos,
            "equipamentos": equipamentos,
        }

        logger.info(f"[BILLING CONTEXT] Dados carregados: {customer_name}, {len(cobrancas)} cobrança(s), {len(contratos)} contrato(s)")

        # ================================================================
        # CACHE: Salvar dados no cache (TTL 5 min = 300s)
        # ================================================================
        try:
            await redis_service.client.setex(cache_key, 300, json.dumps(data))
            print(f"[BILLING CONTEXT] Cache salvo para {phone} (TTL 5min)", flush=True)
        except Exception as e:
            logger.warning(f"[BILLING CONTEXT] Erro ao salvar cache: {e}")

        return data

    except Exception as e:
        print(f"[BILLING CONTEXT] Erro ao buscar dados: {e}", flush=True)
        logger.error(f"[BILLING CONTEXT] Erro ao buscar dados para phone={phone}: {e}")
        return None


def build_billing_context_prompt(billing_data: Dict[str, Any]) -> str:
    """
    Constrói o prompt de contexto com os dados do cliente para cobrança.

    Este prompt é injetado ALÉM do prompt de billing do context_prompts,
    adicionando os dados específicos do cliente.

    Args:
        billing_data: Dict retornado por get_billing_data_for_context()

    Returns:
        String com o prompt formatado
    """
    cliente_nome = billing_data.get("cliente_nome", "Cliente")
    cliente_cpf = billing_data.get("cliente_cpf")

    # Formatar cobranças
    cobrancas_str = ""
    total_devido = 0.0
    link_pagamento = ""
    for cob in billing_data.get("cobrancas_pendentes", []):
        valor = cob.get("valor", 0)
        total_devido += valor
        status = cob.get("status", "Pendente")
        vencimento = cob.get("vencimento", "N/I")
        cobrancas_str += f"  - R$ {valor:.2f} ({status}) - vencimento {vencimento}\n"
        if not link_pagamento and cob.get("link"):
            link_pagamento = cob.get("link")

    if not cobrancas_str:
        cobrancas_str = "  (nenhuma cobrança pendente encontrada)\n"

    # Formatar contratos
    contratos_str = ""
    for contr in billing_data.get("contratos", []):
        numero = contr.get("numero", "N/I")
        endereco = contr.get("endereco", "N/I")
        valor_mensal = contr.get("valor_mensal", 0)
        contratos_str += f"  - Contrato {numero}: R$ {valor_mensal:.2f}/mês - {endereco}\n"

    if not contratos_str:
        contratos_str = "  (nenhum contrato encontrado)\n"

    # Formatar equipamentos
    equipamentos_str = ""
    for eq in billing_data.get("equipamentos", []):
        marca = eq.get("marca", "N/I")
        btus = eq.get("btus", "N/I")
        patrimonio = eq.get("patrimonio", "")
        patrimonio_str = f" (patrimônio {patrimonio})" if patrimonio else ""
        equipamentos_str += f"  - {marca} {btus} BTUs{patrimonio_str}\n"

    if not equipamentos_str:
        equipamentos_str = "  (nenhum equipamento registrado)\n"

    prompt = f"""
## DADOS DO CLIENTE (JÁ CARREGADOS - NÃO PERGUNTE CPF OU DADOS PESSOAIS)

**Cliente:** {cliente_nome}
**CPF/CNPJ:** {cliente_cpf or '(não informado)'}
**Customer ID:** {billing_data.get('customer_id', '')}

### SITUAÇÃO FINANCEIRA:
**Total em aberto:** R$ {total_devido:.2f}
**Cobranças:**
{cobrancas_str}
**Link de pagamento:** {link_pagamento or '(use consultar_cliente para buscar)'}

### CONTRATOS:
{contratos_str}
### EQUIPAMENTOS:
{equipamentos_str}
## INSTRUÇÕES IMPORTANTES

VOCÊ JÁ TEM TODAS AS INFORMAÇÕES DO CLIENTE ACIMA.

### O QUE VOCÊ DEVE FAZER:

1. **NUNCA PEÇA CPF, CNPJ ou dados pessoais** - você já os tem acima
2. Se o cliente perguntar sobre pagamento, informe o valor e envie o link
3. Se o cliente pedir segunda via ou link, use `consultar_cliente` para buscar atualizado
4. Se o cliente afirmar que já pagou, use `consultar_cliente` com `verificar_pagamento=true`
5. Se o cliente mudar de assunto (manutenção, defeito), você tem os dados do contrato acima

### O QUE VOCÊ NÃO DEVE FAZER:

**NÃO PEÇA** CPF, CNPJ, telefone ou nome - você já os tem
**NÃO PEÇA** número do contrato ou endereço - você já sabe
**NÃO PEÇA** qual equipamento - você já tem a lista acima

### SE O CLIENTE MUDAR DE ASSUNTO:

Se o cliente perguntar sobre manutenção, defeito ou problema no ar:
1. Você já tem os dados do contrato e equipamentos acima
2. Pergunte qual é o problema (pingando, não gela, barulho, etc)
3. Pergunte dia e período preferido para visita técnica
4. Transfira para o setor técnico usando `transferir_departamento`
"""

    return prompt
