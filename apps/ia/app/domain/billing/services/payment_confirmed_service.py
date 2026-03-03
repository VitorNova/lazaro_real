"""
Servico de processamento de pagamentos confirmados e recebidos.

Responsavel por:
- Processar PAYMENT_CONFIRMED
- Processar PAYMENT_RECEIVED
- Atualizar lead quando pagamento e recebido
- Buscar telefone do cliente para match

Extraido de: app/webhooks/pagamentos.py (Fase 3.8)
"""

import logging
import re
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


async def processar_pagamento_confirmado(
    supabase: Any,
    payment: Dict[str, Any],
    agent_id: Optional[str],
) -> None:
    """
    Processa PAYMENT_CONFIRMED.

    Pagamento confirmado mas saldo ainda nao disponivel.
    Atualiza status para CONFIRMED.
    """
    now = datetime.utcnow().isoformat()
    payment_id = payment.get("id", "")
    value = payment.get("value", 0)

    # Atualizar asaas_cobrancas
    if agent_id:
        try:
            supabase.client.table("asaas_cobrancas").update({
                "status": "CONFIRMED",
                "payment_date": payment.get("paymentDate"),
                "updated_at": now,
            }).eq("id", payment_id).eq("agent_id", agent_id).execute()
        except Exception as e:
            logger.debug("[ASAAS WEBHOOK] Erro ao atualizar asaas_cobrancas: %s", e)

    logger.debug("[ASAAS WEBHOOK] Pagamento confirmado: %s (R$ %.2f)", payment_id, value)


async def buscar_telefone_cliente(
    supabase: Any,
    customer_id: str,
    payment_id: str,
) -> Optional[str]:
    """
    Busca telefone do cliente para encontrar o lead.

    Prioridade:
    1. asaas_clientes.mobile_phone
    2. asaas_clientes.phone
    3. billing_notifications.phone (fallback)

    Returns:
        Telefone normalizado (ultimos 9 digitos) ou None se nao encontrar.
    """
    def normalizar_telefone(phone: str) -> Optional[str]:
        """Remove nao-numericos e retorna ultimos 9 digitos."""
        if not phone:
            return None
        digits = re.sub(r"\D", "", phone)
        if len(digits) >= 9:
            return digits[-9:]  # Ultimos 9 digitos para match flexivel
        return None

    # 1. Tentar asaas_clientes primeiro (cache local)
    try:
        result = (
            supabase.client.table("asaas_clientes")
            .select("mobile_phone, phone")
            .eq("id", customer_id)
            .maybe_single()
            .execute()
        )
        if result.data:
            phone = result.data.get("mobile_phone") or result.data.get("phone")
            normalized = normalizar_telefone(phone)
            if normalized:
                logger.debug("[ASAAS WEBHOOK] Telefone encontrado em asaas_clientes: %s", normalized[-4:])
                return normalized
    except Exception as e:
        logger.warning("[ASAAS WEBHOOK] Erro ao buscar telefone em asaas_clientes: %s", e)

    # 2. Fallback: billing_notifications
    try:
        result = (
            supabase.client.table("billing_notifications")
            .select("phone")
            .eq("payment_id", payment_id)
            .limit(1)
            .execute()
        )
        if result.data and len(result.data) > 0:
            phone = result.data[0].get("phone")
            normalized = normalizar_telefone(phone)
            if normalized:
                logger.debug("[ASAAS WEBHOOK] Telefone encontrado em billing_notifications: %s", normalized[-4:])
                return normalized
    except Exception as e:
        logger.warning("[ASAAS WEBHOOK] Erro ao buscar telefone em billing_notifications: %s", e)

    logger.warning("[ASAAS WEBHOOK] Telefone nao encontrado para customer_id=%s", customer_id)
    return None


async def atualizar_lead_pagamento(
    supabase: Any,
    agent_id: str,
    customer_id: str,
    payment_id: str,
    payment_value: float = 0,
) -> None:
    """
    Atualiza lead quando pagamento e recebido.

    - Vincula asaas_customer_id ao lead (se ainda nao vinculado)
    - Move para pipeline_step = 'cliente'
    - Marca venda_realizada = 'true'
    - Atualiza journey_stage = 'cliente'
    - Registra first_payment_at no primeiro pagamento
    - Registra converted_at se ainda nao definido

    Estrategia de match:
    1. Se lead ja tem asaas_customer_id == customer_id, atualiza direto
    2. Senao, tenta match por CPF/CNPJ do cliente
    3. Senao, tenta match por telefone
    """
    # Validacao inicial
    if not agent_id or not customer_id:
        logger.debug("[ASAAS WEBHOOK] agent_id ou customer_id nao informado, pulando atualizacao de lead")
        return

    now = datetime.utcnow().isoformat()

    # 1. Buscar table_leads do agente
    try:
        agent_result = (
            supabase.client.table("agents")
            .select("table_leads")
            .eq("id", agent_id)
            .maybe_single()
            .execute()
        )
        if not agent_result.data or not agent_result.data.get("table_leads"):
            logger.warning("[ASAAS WEBHOOK] table_leads nao encontrado para agent_id=%s", agent_id[:8])
            return
        table_leads = agent_result.data["table_leads"]
    except Exception as e:
        logger.error("[ASAAS WEBHOOK] Erro ao buscar table_leads: %s", e)
        return

    # 2. Tentar encontrar lead por multiplas estrategias
    lead = None

    # 2.1 - Buscar lead ja vinculado ao customer_id
    try:
        lead_result = (
            supabase.client.table(table_leads)
            .select("id, nome, pipeline_step, asaas_customer_id, converted_at, first_payment_at")
            .eq("asaas_customer_id", customer_id)
            .limit(1)
            .execute()
        )
        if lead_result.data:
            lead = lead_result.data[0]
            logger.debug("[ASAAS WEBHOOK] Lead encontrado por asaas_customer_id: %s", customer_id)
    except Exception as e:
        logger.debug("[ASAAS WEBHOOK] Erro ao buscar lead por asaas_customer_id: %s", e)

    # 2.2 - Se nao encontrou, buscar cliente para pegar CPF e telefone
    if not lead:
        try:
            cliente_result = (
                supabase.client.table("asaas_clientes")
                .select("cpf_cnpj, mobile_phone")
                .eq("id", customer_id)
                .eq("agent_id", agent_id)
                .maybe_single()
                .execute()
            )

            if cliente_result.data:
                cpf_cnpj = cliente_result.data.get("cpf_cnpj")
                mobile_phone = cliente_result.data.get("mobile_phone")

                # 2.2.1 - Tentar match por CPF/CNPJ
                if cpf_cnpj and not lead:
                    cpf_limpo = re.sub(r'\D', '', cpf_cnpj)
                    if len(cpf_limpo) in [11, 14]:
                        lead_result = (
                            supabase.client.table(table_leads)
                            .select("id, nome, pipeline_step, asaas_customer_id, converted_at, first_payment_at")
                            .eq("cpf_cnpj", cpf_limpo)
                            .limit(1)
                            .execute()
                        )
                        if lead_result.data:
                            lead = lead_result.data[0]
                            logger.debug("[ASAAS WEBHOOK] Lead encontrado por CPF: %s", cpf_limpo)

                # 2.2.2 - Tentar match por telefone
                if mobile_phone and not lead:
                    phone_limpo = re.sub(r'\D', '', mobile_phone)
                    if len(phone_limpo) >= 10:
                        phone_suffix = phone_limpo[-11:] if len(phone_limpo) >= 11 else phone_limpo
                        lead_result = (
                            supabase.client.table(table_leads)
                            .select("id, nome, pipeline_step, asaas_customer_id, converted_at, first_payment_at")
                            .ilike("remotejid", f"%{phone_suffix}%")
                            .limit(1)
                            .execute()
                        )
                        if lead_result.data:
                            lead = lead_result.data[0]
                            logger.debug("[ASAAS WEBHOOK] Lead encontrado por telefone: %s", phone_suffix)
        except Exception as e:
            logger.warning("[ASAAS WEBHOOK] Erro ao buscar cliente/lead para match: %s", e)

    # 2.3 - Fallback: buscar telefone via funcao existente
    if not lead:
        telefone = await buscar_telefone_cliente(supabase, customer_id, payment_id)
        if telefone:
            try:
                lead_result = (
                    supabase.client.table(table_leads)
                    .select("id, nome, pipeline_step, asaas_customer_id, converted_at, first_payment_at")
                    .ilike("telefone", f"%{telefone}%")
                    .maybe_single()
                    .execute()
                )
                if lead_result.data:
                    lead = lead_result.data[0]
                    logger.debug("[ASAAS WEBHOOK] Lead encontrado por telefone (fallback): %s", telefone[-4:])
            except Exception as e:
                logger.debug("[ASAAS WEBHOOK] Erro no fallback por telefone: %s", e)

    if not lead:
        logger.warning("[ASAAS WEBHOOK] Nenhum lead encontrado para customer_id=%s", customer_id)
        return

    # 3. Montar dados de atualizacao
    lead_id = lead["id"]
    lead_nome = lead.get("nome", "Desconhecido")
    pipeline_atual = lead.get("pipeline_step", "")

    update_data = {
        "asaas_customer_id": customer_id,
        "pipeline_step": "cliente",
        "venda_realizada": "true",
        "journey_stage": "cliente",
        "updated_date": now,
    }

    # Se ainda nao tem converted_at, definir agora
    if not lead.get("converted_at"):
        update_data["converted_at"] = now

    # Se e o primeiro pagamento, registrar first_payment_at
    if not lead.get("first_payment_at"):
        update_data["first_payment_at"] = now
        logger.info(
            "[CONVERSAO] Primeiro pagamento! Lead %s -> R$ %.2f",
            lead.get("id"), payment_value
        )

    # 4. Atualizar lead
    try:
        supabase.client.table(table_leads).update(update_data).eq("id", lead_id).execute()

        logger.info(
            "[ASAAS WEBHOOK] Lead atualizado apos pagamento: id=%s, nome=%s, pipeline: %s -> cliente",
            lead_id, lead_nome[:20] if lead_nome else "?", pipeline_atual
        )
    except Exception as e:
        logger.error("[ASAAS WEBHOOK] Erro ao atualizar lead id=%s: %s", lead_id, e)


async def processar_pagamento_recebido(
    supabase: Any,
    payment: Dict[str, Any],
    agent_id: Optional[str],
) -> None:
    """
    Processa PAYMENT_RECEIVED.

    Pagamento recebido/pago (saldo disponivel).
    Atualiza status para RECEIVED e marca como pago em billing_notifications.
    Se a IA cobrou este pagamento (ia_cobrou = true), marca ia_recebeu = true.
    """
    now = datetime.utcnow().isoformat()
    payment_id = payment.get("id", "")
    value = payment.get("value", 0)

    # Atualizar asaas_cobrancas
    if agent_id:
        try:
            # Primeiro, buscar se ia_cobrou = true para marcar ia_recebeu
            cobranca_res = (
                supabase.client.table("asaas_cobrancas")
                .select("ia_cobrou")
                .eq("id", payment_id)
                .eq("agent_id", agent_id)
                .limit(1)
                .execute()
            )

            update_data = {
                "status": "RECEIVED",
                "payment_date": payment.get("paymentDate"),
                "updated_at": now,
            }

            # Se IA cobrou, buscar step da ultima notificacao e marcar ia_recebeu
            if cobranca_res.data and cobranca_res.data[0].get("ia_cobrou"):
                try:
                    notif_res = (
                        supabase.client.table("billing_notifications")
                        .select("notification_type, days_from_due")
                        .eq("payment_id", payment_id)
                        .eq("status", "sent")
                        .order("sent_at", desc=True)
                        .limit(1)
                        .execute()
                    )
                    if notif_res.data:
                        update_data["ia_recebeu"] = True
                        update_data["ia_recebeu_at"] = now
                        update_data["ia_recebeu_step"] = notif_res.data[0].get("notification_type")
                        update_data["ia_recebeu_days_from_due"] = notif_res.data[0].get("days_from_due")
                        logger.info(
                            "[ASAAS WEBHOOK] Pagamento %s: IA cobrou e recebeu! Step=%s, Days=%s",
                            payment_id,
                            update_data.get("ia_recebeu_step"),
                            update_data.get("ia_recebeu_days_from_due"),
                        )
                    else:
                        # ia_cobrou mas sem notificacao encontrada (raro)
                        update_data["ia_recebeu"] = True
                        update_data["ia_recebeu_at"] = now
                except Exception as e:
                    logger.warning("[ASAAS WEBHOOK] Erro ao buscar step de notificacao: %s", e)
                    update_data["ia_recebeu"] = True
                    update_data["ia_recebeu_at"] = now

            supabase.client.table("asaas_cobrancas").update(
                update_data
            ).eq("id", payment_id).eq("agent_id", agent_id).execute()
        except Exception as e:
            logger.debug("[ASAAS WEBHOOK] Erro ao atualizar asaas_cobrancas: %s", e)

    # Atualizar billing_notifications (tabela unificada)
    try:
        supabase.client.table("billing_notifications").update({
            "status": "paid",
            "updated_at": now,
        }).eq("payment_id", payment_id).execute()
    except Exception as e:
        logger.debug("[ASAAS WEBHOOK] Erro ao atualizar billing_notifications: %s", e)

    logger.debug("[ASAAS WEBHOOK] Pagamento recebido: %s (R$ %.2f)", payment_id, value)

    # Atualizar lead (pipeline_step, venda_realizada, etc.)
    customer_id = payment.get("customer", "")
    if agent_id and customer_id:
        try:
            await atualizar_lead_pagamento(
                supabase, agent_id, customer_id, payment_id,
                payment_value=value
            )
        except Exception as e:
            logger.error("[ASAAS WEBHOOK] Erro ao atualizar lead apos pagamento: %s", e)
