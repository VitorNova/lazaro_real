"""
Billing Orchestrator Service - Logica principal de cobranca automatica.

Extraido de: app/jobs/cobrar_clientes.py (Fase 3)

Funcionalidades:
- Processamento de cobrancas por agente
- Envio de lembretes (D-2, D-1)
- Envio no dia do vencimento (D0)
- Envio apos vencimento (D+1 a D+15)
- Agrupamento por cliente (mensagens consolidadas)
"""

import asyncio
import logging
from datetime import date
from typing import Any, Dict, List, Tuple

from app.services.dispatch_logger import get_dispatch_logger
from app.services.leadbox_push import QUEUE_BILLING, leadbox_push_silent
from app.services.supabase import get_supabase_service
from app.services.whatsapp_api import UazapiService, sign_message
from app.core.utils.dias_uteis import (
    add_business_days,
    anticipate_to_friday,
    format_date,
    get_today_brasilia,
    parse_date,
    subtract_business_days,
)
from datetime import datetime

from app.domain.billing.models.billing_config import DEFAULT_MESSAGES
from app.domain.billing.services.billing_formatter import (
    format_brl,
    format_message,
    format_consolidated_message,
    get_overdue_template,
    get_consolidated_overdue_template,
)
from app.domain.billing.services.billing_rules import should_skip_payment
from app.domain.billing.services.billing_notifier import (
    claim_notification,
    update_notification_status,
    get_sent_count,
    mask_customer_name,
    mask_phone,
)
from app.domain.billing.services.lead_ensurer import save_message_to_conversation_history
from app.domain.billing.services.payment_fetcher import (
    fetch_payments_with_fallback,
    sync_payments_to_cache,
    enrich_payments_from_api,
)
from app.domain.billing.services.customer_phone import get_customer_phone

logger = logging.getLogger(__name__)


def _log(msg: str) -> None:
    """Log com prefixo do job."""
    logger.info(f"[BILLING JOB] {msg}")


def _log_warn(msg: str) -> None:
    logger.warning(f"[BILLING JOB] {msg}")


def _log_error(msg: str) -> None:
    logger.error(f"[BILLING JOB] {msg}")


async def process_agent_billing(agent: Dict[str, Any]) -> Dict[str, int]:
    """
    Processa notificacoes de cobranca para um agente especifico.

    Fluxo:
    1. Lembretes antes do vencimento (D-2, D-1)
    2. Notificacao no dia do vencimento (D0)
    3. Cobrancas apos vencimento (D+1 a D+15, agrupadas por cliente)

    Args:
        agent: Dados do agente com asaas_api_key, uazapi_*, etc

    Returns:
        Dict com contadores: sent, skipped, errors, api_success, api_failures, fallback_used
    """
    stats = {
        "sent": 0,
        "skipped": 0,
        "errors": 0,
        "api_success": 0,
        "api_failures": 0,
        "fallback_used": 0,
    }

    asaas_config = agent.get("asaas_config") or {}
    auto_collection = asaas_config.get("autoCollection") or {}

    if auto_collection.get("enabled") is False:
        _log(f"Cobranca automatica desabilitada para: {agent.get('name')}")
        return stats

    # Configuracoes da regua
    reminder_days = auto_collection.get("reminderDays") or [2, 1]
    on_due_date = auto_collection.get("onDueDate", True)
    after_due = auto_collection.get("afterDue") or {
        "enabled": True,
        "overdueDays": list(range(1, 16)),
        "maxAttempts": 15,
    }
    messages = auto_collection.get("messages") or {}

    _log(f"Processando cobranca para agente: {agent.get('name')} ({agent['id'][:8]}...)")

    today = get_today_brasilia()
    today_str = format_date(today)

    async def send_notification(
        phone: str,
        message: str,
        payment: Dict[str, Any],
        notification_type: str,
        days_from_due: int,
    ) -> bool:
        """Envia notificacao via WhatsApp e registra."""
        # Tenta clamar a notificacao atomicamente (previne duplicatas)
        claimed = await claim_notification(
            agent_id=agent["id"],
            payment_id=payment["id"],
            notification_type=notification_type,
            scheduled_date=today_str,
            customer_id=payment.get("customer_id"),
            phone=phone,
            days_from_due=days_from_due,
        )

        if not claimed:
            _log(f"Notificacao ja enviada para {payment['id']} ({notification_type})")
            stats["skipped"] += 1
            return False

        try:
            # Verifica configuracao do WhatsApp
            if not agent.get("uazapi_base_url") or not agent.get("uazapi_token"):
                raise ValueError("Configuracao UAZAPI incompleta")

            signed = sign_message(message, agent.get("name", "Ana"))

            # Dispatch via Leadbox PUSH ou UAZAPI
            push_result = await leadbox_push_silent(
                phone, QUEUE_BILLING, agent["id"], message=signed
            )

            if push_result.get("ticket_check_failed") or not push_result.get("message_sent_via_push"):
                uazapi_client = UazapiService(
                    base_url=agent["uazapi_base_url"],
                    api_key=agent["uazapi_token"],
                )
                result = await uazapi_client.send_text_message(phone, signed)
                if not result.get("success"):
                    raise ValueError(result.get("error", "Erro desconhecido ao enviar"))

            # Salvar no conversation_history
            await save_message_to_conversation_history(agent, phone, message, notification_type, payment)

            # Log em dispatch_log
            dispatch_logger = get_dispatch_logger()
            await dispatch_logger.log_dispatch(
                job_type="billing",
                agent_id=agent["id"],
                reference_id=payment["id"],
                phone=phone,
                notification_type=notification_type,
                message_text=message,
                status="sent",
                reference_table="asaas_cobrancas",
                customer_id=payment.get("customer_id") or payment.get("customer"),
                customer_name=payment.get("customer_name", "Desconhecido"),
                days_from_due=days_from_due,
                metadata={
                    "valor": payment.get("value"),
                    "due_date": str(payment.get("due_date") or payment.get("dueDate", "")),
                    "billing_type": payment.get("billing_type") or payment.get("billingType"),
                    "subscription_id": payment.get("subscription_id") or payment.get("subscription"),
                    "payment_link": payment.get("invoice_url") or payment.get("bank_slip_url"),
                },
            )

            # Marcar ia_cobrou
            supabase = get_supabase_service()
            try:
                count_result = supabase.client.table("billing_notifications") \
                    .select("id", count="exact") \
                    .eq("payment_id", payment["id"]) \
                    .eq("status", "sent") \
                    .execute()

                total_notifs = count_result.count if count_result.count else 1

                supabase.client.table("asaas_cobrancas").update({
                    "ia_cobrou": True,
                    "ia_cobrou_at": datetime.utcnow().isoformat(),
                    "ia_total_notificacoes": total_notifs,
                    "ia_ultimo_step": notification_type,
                    "ia_ultimo_days_from_due": days_from_due,
                    "ia_ultima_notificacao_at": datetime.utcnow().isoformat(),
                }).eq("id", payment["id"]).eq("agent_id", agent["id"]).execute()
            except Exception as e:
                _log_warn(f"Erro ao marcar ia_cobrou em asaas_cobrancas: {e}")

            await update_notification_status(
                agent["id"], payment["id"], notification_type, today_str, "sent"
            )
            _log(f"Notificacao enviada: {payment['id']} ({notification_type}) -> {mask_phone(phone)}")
            stats["sent"] += 1
            return True

        except Exception as e:
            error_msg = str(e)
            await update_notification_status(
                agent["id"], payment["id"], notification_type, today_str, "failed", error_msg
            )
            _log_error(f"Erro ao enviar notificacao {payment['id']}: {error_msg}")

            dispatch_logger = get_dispatch_logger()
            await dispatch_logger.log_failure(
                job_type="billing",
                agent_id=agent["id"],
                reference_id=payment["id"],
                phone=phone,
                notification_type=notification_type,
                error_message=error_msg,
                message_text=message,
                reference_table="asaas_cobrancas",
                customer_id=payment.get("customer_id") or payment.get("customer"),
                customer_name=payment.get("customer_name"),
                days_from_due=days_from_due,
                metadata={
                    "valor": payment.get("value"),
                    "due_date": str(payment.get("due_date") or payment.get("dueDate", "")),
                    "billing_type": payment.get("billing_type") or payment.get("billingType"),
                },
            )

            stats["errors"] += 1
            return False

    # ========================================================================
    # 1. LEMBRETES ANTES DO VENCIMENTO
    # ========================================================================
    for days_ahead in reminder_days:
        target_due_date = add_business_days(today, days_ahead)
        anticipated_date = anticipate_to_friday(target_due_date)

        if format_date(anticipated_date) != today_str and format_date(target_due_date) != today_str:
            continue

        _log(f"Buscando pagamentos com vencimento em {format_date(target_due_date)} ({days_ahead} dias uteis)")

        payments, source = await fetch_payments_with_fallback(
            agent=agent,
            status="PENDING",
            due_date_start=target_due_date,
            due_date_end=target_due_date,
        )

        if source == "api":
            stats["api_success"] += 1
            asyncio.create_task(sync_payments_to_cache(agent["id"], payments, agent.get("asaas_api_key")))
            payments = await enrich_payments_from_api(agent["id"], payments)
        else:
            stats["fallback_used"] += 1

        for payment in payments:
            if should_skip_payment(payment, is_overdue=False):
                continue

            phone = get_customer_phone(payment)
            if not phone:
                _log_warn(f"Cliente {mask_customer_name(payment.get('customer_name', 'Desconhecido'))} sem telefone valido")
                continue

            template = messages.get("reminderTemplate") or DEFAULT_MESSAGES["reminder"]
            due_date_str = str(payment.get("due_date") or payment.get("dueDate", ""))
            msg = format_message(
                template,
                payment["customer_name"],
                float(payment["value"]),
                due_date_str,
                days_until_due=days_ahead,
                payment_link=payment.get("invoice_url") or payment.get("bank_slip_url"),
            )
            await send_notification(phone, msg, payment, "reminder", days_ahead)

    # ========================================================================
    # 2. NOTIFICACAO NO DIA DO VENCIMENTO
    # ========================================================================
    if on_due_date:
        _log(f"Buscando pagamentos com vencimento hoje ({today_str})")

        payments, source = await fetch_payments_with_fallback(
            agent=agent,
            status="PENDING",
            due_date_start=today,
            due_date_end=today,
        )

        if source == "api":
            stats["api_success"] += 1
            asyncio.create_task(sync_payments_to_cache(agent["id"], payments, agent.get("asaas_api_key")))
            payments = await enrich_payments_from_api(agent["id"], payments)
        else:
            stats["fallback_used"] += 1

        for payment in payments:
            if should_skip_payment(payment, is_overdue=False):
                continue

            phone = get_customer_phone(payment)
            if not phone:
                _log_warn(f"Cliente {mask_customer_name(payment.get('customer_name', 'Desconhecido'))} sem telefone valido")
                continue

            template = messages.get("dueDateTemplate") or DEFAULT_MESSAGES["dueDate"]
            due_date_str = str(payment.get("due_date") or payment.get("dueDate", ""))
            msg = format_message(
                template,
                payment["customer_name"],
                float(payment["value"]),
                due_date_str,
                payment_link=payment.get("invoice_url") or payment.get("bank_slip_url"),
            )
            await send_notification(phone, msg, payment, "due_date", 0)

    # ========================================================================
    # 3. COBRANCAS APOS VENCIMENTO (D+1 a D+15)
    # ========================================================================
    if after_due.get("enabled", True):
        max_attempts = after_due.get("maxAttempts", 15)
        overdue_days_list = after_due.get("overdueDays") or list(range(1, 16))

        _log(f"Buscando pagamentos vencidos (max: {max_attempts} tentativas, agrupado por cliente)")

        thirty_days_ago = subtract_business_days(today, 30)
        yesterday = subtract_business_days(today, 1)

        payments, source = await fetch_payments_with_fallback(
            agent=agent,
            status="OVERDUE",
            due_date_start=thirty_days_ago,
            due_date_end=yesterday,
        )

        if source == "api":
            stats["api_success"] += 1
            asyncio.create_task(sync_payments_to_cache(agent["id"], payments, agent.get("asaas_api_key")))
            payments = await enrich_payments_from_api(agent["id"], payments)
        else:
            stats["fallback_used"] += 1

        # Fase 3a: Filtrar pagamentos elegiveis
        eligible: List[Tuple[Dict[str, Any], int]] = []

        for payment in payments:
            if should_skip_payment(payment, is_overdue=True):
                continue

            due_date_val = payment.get("due_date")
            if isinstance(due_date_val, str):
                due_date_parsed = parse_date(due_date_val)
            elif isinstance(due_date_val, date):
                due_date_parsed = due_date_val
            else:
                _log_warn(f"Pagamento {payment['id']} sem due_date valido, pulando")
                continue

            days_overdue = (today - due_date_parsed).days

            if days_overdue not in overdue_days_list:
                continue

            sent_count = await get_sent_count(agent["id"], payment["id"])
            if sent_count >= max_attempts:
                _log(f"Pagamento {payment['id']} atingiu maximo de tentativas ({max_attempts})")
                continue

            eligible.append((payment, days_overdue))

        _log(f"{len(eligible)} pagamentos elegiveis para cobranca")

        # Fase 3b: Agrupar por cliente
        grouped: Dict[str, List[Tuple[Dict[str, Any], int]]] = {}
        for payment, days_ov in eligible:
            customer_id = payment.get("customer_id", payment.get("customer", ""))
            if customer_id not in grouped:
                grouped[customer_id] = []
            grouped[customer_id].append((payment, days_ov))

        _log(f"{len(grouped)} clientes para cobrar ({len(eligible)} faturas)")

        # Fase 3c: Enviar 1 mensagem por cliente
        for customer_id, customer_payments in grouped.items():
            first_payment_data = customer_payments[0][0]
            phone = get_customer_phone(first_payment_data)
            if not phone:
                _log_warn(f"Cliente {mask_customer_name(first_payment_data.get('customer_name', 'Desconhecido'))} sem telefone valido")
                continue

            customer_name = first_payment_data.get("customer_name", "Cliente")
            max_days = max(dov for _, dov in customer_payments)

            if len(customer_payments) == 1:
                # Fatura unica
                payment, days_ov = customer_payments[0]
                template = get_overdue_template(days_ov, messages)
                due_date_str = str(payment.get("due_date") or payment.get("dueDate", ""))
                msg = format_message(
                    template,
                    customer_name,
                    float(payment["value"]),
                    due_date_str,
                    days_overdue=days_ov,
                    payment_link=payment.get("invoice_url") or payment.get("bank_slip_url"),
                )
                await send_notification(phone, msg, payment, "overdue", -days_ov)
            else:
                # Multiplas faturas - mensagem consolidada
                total_value = sum(float(p["value"]) for p, _ in customer_payments)
                first_payment, _ = customer_payments[0]

                template = get_consolidated_overdue_template(max_days, messages)
                msg = format_consolidated_message(
                    template,
                    customer_name,
                    total_value,
                    len(customer_payments),
                    max_days,
                    first_payment.get("invoice_url") or first_payment.get("bank_slip_url"),
                )

                _log(
                    f"Enviando cobranca consolidada: {mask_customer_name(customer_name)} - "
                    f"{len(customer_payments)} faturas, total {format_brl(total_value)}"
                )

                sent = await send_notification(
                    phone, msg, first_payment, "overdue", -max_days
                )

                # Registra para os demais payment_ids
                if sent:
                    for i in range(1, len(customer_payments)):
                        pmt, dov = customer_payments[i]
                        claimed = await claim_notification(
                            agent_id=agent["id"],
                            payment_id=pmt["id"],
                            notification_type="overdue",
                            scheduled_date=today_str,
                            customer_id=pmt.get("customer_id"),
                            phone=phone,
                            days_from_due=-dov,
                        )
                        if claimed:
                            await update_notification_status(
                                agent["id"], pmt["id"], "overdue", today_str, "sent"
                            )
                            _log(f"Registro salvo para {pmt['id']} (consolidado com {first_payment['id']})")

    _log(f"Processamento concluido para agente: {agent.get('name')}")
    return stats
