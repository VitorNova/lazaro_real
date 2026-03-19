"""Dispatcher - envio de notificacoes via WhatsApp."""
import logging
from datetime import datetime
from typing import Any, Dict, Optional

import httpx

from app.billing.models import EligiblePayment, RulerDecision, DispatchResult
from app.billing.templates import get_overdue_template, DEFAULT_MESSAGES
from app.domain.billing.services.billing_formatter import format_message
from app.domain.billing.services.billing_notifier import (
    claim_notification,
    update_notification_status,
)
from app.domain.billing.services.lead_ensurer import save_message_to_conversation_history
from app.domain.leads.services.lead_availability import check_lead_availability
from app.services.dispatch_logger import get_dispatch_logger
from app.services.leadbox_push import leadbox_push_silent, QUEUE_BILLING
from app.services.supabase import get_supabase_service
from app.services.whatsapp_api import UazapiService, sign_message
from app.core.utils.dias_uteis import format_date
from app.core.utils.phone import generate_phone_variants

logger = logging.getLogger(__name__)


async def _search_leadbox_contact(
    api_url: str,
    api_token: str,
    search_phone: str,
    headers: dict,
) -> Optional[str]:
    """
    Busca um contato no Leadbox pelo telefone.

    Returns:
        Telefone normalizado se encontrado, None se não encontrado
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{api_url.rstrip('/')}/contacts",
            params={"searchParam": search_phone, "limit": 1},
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()

    contacts = data.get("contacts", [])
    if contacts:
        leadbox_number = contacts[0].get("number")
        if leadbox_number:
            # Normalizar: remover +, espaços, hífens, parênteses (só dígitos)
            normalized = "".join(filter(str.isdigit, leadbox_number))
            if normalized:
                return normalized

    return None


async def get_leadbox_phone(
    handoff_triggers: Dict[str, Any],
    phone: str,
) -> str:
    """
    Busca o telefone correto no Leadbox via GET /contacts.

    O Asaas pode ter telefone com 9 extra (5566992028039) enquanto o Leadbox
    tem o telefone correto do WhatsApp (556692028039). Essa função busca
    o telefone que o Leadbox conhece para evitar criar registros duplicados.

    Se a busca exata não encontrar, tenta variações do número brasileiro
    (com/sem o 9 após o DDD).

    Args:
        handoff_triggers: Config do Leadbox do agente (api_url, api_token)
        phone: Telefone original (do Asaas)

    Returns:
        Telefone do Leadbox se encontrado, senao telefone original (fail-safe)
    """
    api_url = handoff_triggers.get("api_url")
    api_token = handoff_triggers.get("api_token")

    # Se Leadbox nao configurado, retorna telefone original
    if not api_url or not api_token:
        logger.debug(f"[PHONE NORM] Leadbox nao configurado, usando telefone original")
        return phone

    # Limpar telefone para busca
    clean_phone = phone.replace("@s.whatsapp.net", "").replace("@c.us", "")
    clean_phone = "".join(filter(str.isdigit, clean_phone))

    # Gerar variações do telefone brasileiro (usa função centralizada)
    variations = generate_phone_variants(clean_phone)

    try:
        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }

        # Tentar cada variação até encontrar
        for i, search_phone in enumerate(variations):
            result = await _search_leadbox_contact(api_url, api_token, search_phone, headers)

            if result:
                if i > 0:
                    logger.info(
                        f"[PHONE NORM] Encontrado na variacao {i+1}: "
                        f"{clean_phone} -> {search_phone} -> {result}"
                    )
                else:
                    logger.debug(
                        f"[PHONE NORM] Leadbox retornou number={result} "
                        f"(original={phone[:8]}***)"
                    )
                return result

        # Nenhuma variação encontrou
        logger.debug(
            f"[PHONE NORM] Contato nao encontrado no Leadbox "
            f"(tentou {len(variations)} variacoes), usando original"
        )
        return phone

    except httpx.TimeoutException:
        logger.warning(f"[PHONE NORM] Timeout ao buscar contato no Leadbox, usando original")
        return phone
    except httpx.HTTPStatusError as e:
        logger.warning(f"[PHONE NORM] HTTP {e.response.status_code} do Leadbox, usando original")
        return phone
    except Exception as e:
        logger.warning(f"[PHONE NORM] Erro ao buscar contato no Leadbox: {e}, usando original")
        return phone


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

    # 0. Verificar disponibilidade ANTES de disparar
    available, reason = await check_lead_availability(
        agent=agent,
        phone=eligible.phone,
        agent_id=agent["id"],
    )

    if not available:
        logger.info({
            "event": "dispatch_deferred",
            "payment_id": payment.id,
            "reason": reason,
        })

        # Guardar na "caixa" para retry
        dispatch_logger = get_dispatch_logger()
        await dispatch_logger.log_deferred(
            phone=eligible.phone,
            job_type="billing",
            reason=reason,
            context={
                "payment_id": payment.id,
                "customer_id": payment.customer_id,
                "customer_name": payment.customer_name,
                "value": payment.value,
                "due_date": str(payment.due_date),
                "notification_type": decision.phase,
                "template_key": decision.template_key,
                "offset": decision.offset,
            },
            reference_id=payment.id,
        )

        return DispatchResult(
            status="deferred",
            payment_id=payment.id,
            template_used=decision.template_key,
            offset=decision.offset,
            error=None,
        )

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
        # Normalizar telefone: buscar no Leadbox para evitar duplicatas
        # (Asaas pode ter 5566992028039, Leadbox tem 556692028039)
        normalized_phone = await get_leadbox_phone(
            agent.get("handoff_triggers", {}),
            eligible.phone,
        )

        payment_dict = {
            "id": payment.id,
            "customer_id": payment.customer_id,
            "customer_name": payment.customer_name,
            "value": payment.value,
            "due_date": str(payment.due_date),
            "status": payment.status,
        }
        await save_message_to_conversation_history(
            agent, normalized_phone, message, decision.phase, payment_dict
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

        # 7. Atualizar colunas de billing no lead
        await _update_lead_billing_info(
            table_leads=agent["table_leads"],
            phone=normalized_phone,
            billing_type=decision.phase,
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


async def _update_lead_billing_info(
    table_leads: str,
    phone: str,
    billing_type: str,
) -> None:
    """
    Atualiza last_billing_sent_at e last_billing_type no lead.

    Desnormaliza a data do ultimo disparo de cobranca para evitar
    N queries ao listar leads no dashboard.
    """
    supabase = get_supabase_service()
    try:
        remotejid = f"{phone}@s.whatsapp.net"
        supabase.client.table(table_leads).update({
            "last_billing_sent_at": datetime.utcnow().isoformat(),
            "last_billing_type": billing_type,
        }).eq("remotejid", remotejid).execute()

        logger.debug({
            "event": "lead_billing_info_updated",
            "phone": phone[:8] + "***",
            "billing_type": billing_type,
        })
    except Exception as e:
        logger.warning({
            "event": "update_lead_billing_error",
            "error": str(e),
            "phone": phone[:8] + "***",
        })
