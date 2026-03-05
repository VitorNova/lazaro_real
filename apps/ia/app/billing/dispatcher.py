"""Dispatcher - envio de notificacoes via WhatsApp."""
import logging
from datetime import datetime
from typing import Any, Dict

from app.billing.models import EligiblePayment, RulerDecision, DispatchResult
from app.billing.templates import get_overdue_template, DEFAULT_MESSAGES
from app.domain.billing.services.billing_formatter import format_message
from app.domain.billing.services.billing_notifier import (
    claim_notification,
    update_notification_status,
)
from app.domain.billing.services.lead_ensurer import save_message_to_conversation_history
from app.services.dispatch_logger import get_dispatch_logger
from app.services.leadbox_push import leadbox_push_silent, QUEUE_BILLING
from app.services.supabase import get_supabase_service
from app.services.whatsapp_api import UazapiService, sign_message
from app.core.utils.dias_uteis import format_date

logger = logging.getLogger(__name__)


async def dispatch_single(
    agent: Dict[str, Any],
    eligible: EligiblePayment,
    decision: RulerDecision,
    messages_config: Dict[str, Any],
) -> DispatchResult:
    """
    Envia notificacao para um pagamento.

    Pipeline:
    1. Claim atomico (previne duplicatas)
    2. Formatar mensagem com template
    3. Enviar via Leadbox/UAZAPI
    4. Salvar historico
    5. Log dispatch
    6. Atualizar asaas_cobrancas
    """
    today_str = format_date(datetime.utcnow().date())
    payment = eligible.payment

    # 1. Claim atomico
    claimed = await claim_notification(
        agent_id=agent["id"],
        payment_id=payment.id,
        notification_type=decision.phase,
        scheduled_date=today_str,
        customer_id=payment.customer_id,
        phone=eligible.phone,
        days_from_due=decision.offset,
    )

    if not claimed:
        logger.debug({
            "event": "dispatch_duplicate",
            "payment_id": payment.id,
            "phase": decision.phase,
        })
        return DispatchResult(
            status="duplicate",
            payment_id=payment.id,
            template_used=decision.template_key,
            offset=decision.offset,
            error=None,
        )

    # 2. Formatar mensagem
    template = _get_template(decision, messages_config)
    payment_link = payment.invoice_url or payment.bank_slip_url or ""

    message = format_message(
        template,
        eligible.customer_name,
        payment.value,
        str(payment.due_date),
        days_overdue=abs(decision.offset) if decision.offset > 0 else None,
        days_until_due=abs(decision.offset) if decision.offset < 0 else None,
        payment_link=payment_link,
    )

    try:
        # 3. Enviar via Leadbox ou UAZAPI
        signed = sign_message(message, agent.get("name", "Ana"))

        push_result = await leadbox_push_silent(
            eligible.phone, QUEUE_BILLING, agent["id"], message=signed
        )

        # Se Leadbox falhou ou ticket ja existia, enviar via UAZAPI
        if push_result.get("ticket_check_failed") or not push_result.get("message_sent_via_push"):
            uazapi = UazapiService(
                base_url=agent.get("uazapi_base_url"),
                api_key=agent.get("uazapi_token"),
            )
            result = await uazapi.send_text_message(eligible.phone, signed)
            if not result.get("success"):
                raise ValueError(result.get("error", "Erro desconhecido no UAZAPI"))

        # 4. Salvar historico
        payment_dict = {
            "id": payment.id,
            "customer_id": payment.customer_id,
            "customer_name": payment.customer_name,
            "value": payment.value,
            "due_date": str(payment.due_date),
            "status": payment.status,
        }
        await save_message_to_conversation_history(
            agent, eligible.phone, message, decision.phase, payment_dict
        )

        # 5. Log dispatch
        dispatch_logger = get_dispatch_logger()
        await dispatch_logger.log_dispatch(
            job_type="billing_v2",
            agent_id=agent["id"],
            reference_id=payment.id,
            phone=eligible.phone,
            notification_type=decision.phase,
            message_text=message,
            status="sent",
            days_from_due=decision.offset,
        )

        # 6. Atualizar asaas_cobrancas
        await _update_payment_status(agent["id"], payment.id, decision)

        await update_notification_status(
            agent["id"], payment.id, decision.phase, today_str, "sent"
        )

        logger.info({
            "event": "dispatch_sent",
            "payment_id": payment.id,
            "phase": decision.phase,
            "offset": decision.offset,
            "agent_id": agent["id"],
        })

        return DispatchResult(
            status="sent",
            payment_id=payment.id,
            template_used=decision.template_key,
            offset=decision.offset,
            error=None,
        )

    except Exception as e:
        error_msg = str(e)
        await update_notification_status(
            agent["id"], payment.id, decision.phase, today_str, "failed", error_msg
        )

        dispatch_logger = get_dispatch_logger()
        await dispatch_logger.log_failure(
            job_type="billing_v2",
            agent_id=agent["id"],
            reference_id=payment.id,
            phone=eligible.phone,
            notification_type=decision.phase,
            error_message=error_msg,
            message_text=message,
            days_from_due=decision.offset,
        )

        logger.error({
            "event": "dispatch_error",
            "payment_id": payment.id,
            "error": error_msg,
        })

        return DispatchResult(
            status="error",
            payment_id=payment.id,
            template_used=decision.template_key,
            offset=decision.offset,
            error=error_msg,
        )


def _get_template(decision: RulerDecision, messages_config: Dict[str, Any]) -> str:
    """Obtem template baseado na decisao."""
    if decision.phase == "reminder":
        return messages_config.get("reminderTemplate") or DEFAULT_MESSAGES["reminder"]
    elif decision.phase == "due_date":
        return messages_config.get("dueDateTemplate") or DEFAULT_MESSAGES["dueDate"]
    else:
        return get_overdue_template(decision.offset, messages_config)


async def _update_payment_status(
    agent_id: str, payment_id: str, decision: RulerDecision
) -> None:
    """Atualiza campos ia_* na asaas_cobrancas."""
    supabase = get_supabase_service()
    try:
        supabase.client.table("asaas_cobrancas").update({
            "ia_cobrou": True,
            "ia_cobrou_at": datetime.utcnow().isoformat(),
            "ia_ultimo_step": decision.phase,
            "ia_ultimo_days_from_due": decision.offset,
            "ia_total_notificacoes": supabase.client.rpc(
                "increment_field",
                {"row_id": payment_id, "field_name": "ia_total_notificacoes"}
            ).execute().data if False else None,  # Placeholder - increment manual
        }).eq("id", payment_id).eq("agent_id", agent_id).execute()
    except Exception as e:
        logger.warning({"event": "update_payment_status_error", "error": str(e)})

    # Incremento manual do contador
    try:
        result = (
            supabase.client.table("asaas_cobrancas")
            .select("ia_total_notificacoes")
            .eq("id", payment_id)
            .eq("agent_id", agent_id)
            .maybe_single()
            .execute()
        )
        current = (result.data or {}).get("ia_total_notificacoes") or 0
        supabase.client.table("asaas_cobrancas").update({
            "ia_total_notificacoes": current + 1,
        }).eq("id", payment_id).eq("agent_id", agent_id).execute()
    except Exception as e:
        logger.warning({"event": "increment_notifications_error", "error": str(e)})
