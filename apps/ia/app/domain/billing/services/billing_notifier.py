"""
Billing Notifier Service - Controle de notificacoes de cobranca.

Extraido de: app/jobs/cobrar_clientes.py (Fase 4.4)

Funcionalidades:
- Claim atomico de notificacoes (previne duplicatas)
- Salvamento de registros de cobranca enviada
- Atualizacao de status de notificacoes
- Dead Letter Queue para falhas
- Contagem de tentativas de envio
"""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from app.services.supabase import get_supabase_service

logger = logging.getLogger(__name__)


def _log(msg: str) -> None:
    """Log com prefixo do job."""
    logger.info(f"[BILLING JOB] {msg}")


def _log_warn(msg: str) -> None:
    logger.warning(f"[BILLING JOB] {msg}")


def _log_error(msg: str) -> None:
    logger.error(f"[BILLING JOB] {msg}")


def mask_customer_name(name: str) -> str:
    """Mascara nome de cliente para logs (LGPD/GDPR compliance)."""
    if not name or len(name) < 3:
        return "***"
    return name[0] + "*" * (len(name) - 1)


def mask_phone(phone: str) -> str:
    """Mascara telefone para logs (LGPD/GDPR compliance)."""
    if not phone or len(phone) < 8:
        return "****"
    return phone[:4] + "*" * (len(phone) - 8) + phone[-4:]


async def claim_notification(
    agent_id: str,
    payment_id: str,
    notification_type: str,
    scheduled_date: str,
    customer_id: Optional[str] = None,
    phone: Optional[str] = None,
    days_from_due: Optional[int] = None,
) -> bool:
    """
    Tenta registrar notificacao atomicamente usando stored procedure.
    Previne race condition - retorna True se conseguiu clamar, False se ja existia.

    Utiliza RPC 'claim_billing_notification' no Supabase para garantir atomicidade.
    """
    supabase = get_supabase_service()
    try:
        response = supabase.client.rpc(
            "claim_billing_notification",
            {
                "p_agent_id": agent_id,
                "p_payment_id": payment_id,
                "p_notification_type": notification_type,
                "p_scheduled_date": scheduled_date,
                "p_customer_id": customer_id,
                "p_phone": phone,
                "p_days_from_due": days_from_due,
            },
        ).execute()

        if response.data and len(response.data) > 0:
            return response.data[0].get("claimed", False)
        return False
    except Exception as e:
        _log_error(f"Erro ao clamar notificacao: {e}")
        return False


async def save_cobranca_enviada(
    agent_id: str,
    payment: Dict[str, Any],
    customer_name: str,
    phone: str,
    message_text: str,
    notification_type: str,
    days_from_due: int,
    payment_link: Optional[str] = None,
) -> None:
    """
    Salva registro completo da cobranca enviada em billing_notifications (tabela unificada).

    Utiliza UPSERT com on_conflict para atualizar registro ja clamado ou criar novo.
    """
    supabase = get_supabase_service()
    try:
        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        due_date = payment.get("due_date") or payment.get("dueDate")
        if not due_date:
            _log_warn(f"due_date ausente para payment {payment.get('id')} - usando scheduled_date como fallback")
            due_date = today_str

        record = {
            "agent_id": agent_id,
            "payment_id": payment["id"],
            "customer_id": payment.get("customer_id") or payment.get("customer"),
            "phone": phone,
            "customer_name": customer_name,
            "valor": payment.get("value"),
            "due_date": due_date,
            "billing_type": payment.get("billing_type") or payment.get("billingType"),
            "subscription_id": payment.get("subscription_id") or payment.get("subscription"),
            "message_text": message_text,
            "notification_type": notification_type,
            "days_from_due": days_from_due,
            "scheduled_date": today_str,
            "status": "sent",
            "sent_at": datetime.utcnow().isoformat(),
        }

        supabase.client.table("billing_notifications").upsert(
            record,
            on_conflict="agent_id,payment_id,notification_type,scheduled_date"
        ).execute()
        _log(f"Cobranca salva em billing_notifications: {payment['id']} -> {mask_customer_name(customer_name)}")
    except Exception as e:
        _log_error(f"Erro ao salvar em billing_notifications: {e}")


async def update_notification_status(
    agent_id: str,
    payment_id: str,
    notification_type: str,
    scheduled_date: str,
    status: str,
    error_message: Optional[str] = None,
) -> None:
    """
    Atualiza status da notificacao.

    Args:
        agent_id: ID do agente
        payment_id: ID do pagamento
        notification_type: Tipo (reminder, due_date, overdue)
        scheduled_date: Data agendada
        status: Novo status (sent, failed, etc)
        error_message: Mensagem de erro (opcional)
    """
    supabase = get_supabase_service()
    try:
        update_data: Dict[str, Any] = {
            "status": status,
            "sent_at": datetime.utcnow().isoformat() if status == "sent" else None,
        }
        if error_message:
            update_data["error_message"] = error_message

        (
            supabase.client.table("billing_notifications")
            .update(update_data)
            .eq("agent_id", agent_id)
            .eq("payment_id", payment_id)
            .eq("notification_type", notification_type)
            .eq("scheduled_date", scheduled_date)
            .execute()
        )
    except Exception as e:
        _log_error(f"Erro ao atualizar notificacao: {e}")


async def save_to_dead_letter_queue(
    agent_id: str,
    payment: Dict[str, Any],
    phone: str,
    message: str,
    notification_type: str,
    scheduled_date: str,
    days_from_due: int,
    error_message: str,
    dispatch_method: str = "uazapi",
) -> None:
    """
    Salva notificacao falhada no Dead Letter Queue para reprocessamento posterior.
    Classifica o tipo de erro para facilitar analise e retry estrategico.

    Tipos de erro classificados:
    - timeout: Timeout na requisicao
    - rate_limit: 429 / rate limit
    - not_found: 404
    - auth_error: 401/403
    - network_error: Problemas de conexao
    - invalid_data: Dados invalidos
    - api_error: Outros erros de API
    """
    supabase = get_supabase_service()

    # Classificar tipo de erro
    failure_reason = "unknown"
    error_lower = error_message.lower()

    if "timeout" in error_lower or "timed out" in error_lower:
        failure_reason = "timeout"
    elif "429" in error_message or "rate limit" in error_lower:
        failure_reason = "rate_limit"
    elif "404" in error_message or "not found" in error_lower:
        failure_reason = "not_found"
    elif "401" in error_message or "403" in error_message or "unauthorized" in error_lower:
        failure_reason = "auth_error"
    elif "network" in error_lower or "connection" in error_lower:
        failure_reason = "network_error"
    elif "invalid" in error_lower:
        failure_reason = "invalid_data"
    else:
        failure_reason = "api_error"

    try:
        record = {
            "agent_id": agent_id,
            "payment_id": payment["id"],
            "customer_id": payment.get("customer_id"),
            "customer_name": payment.get("customer_name"),
            "phone": phone,
            "message_text": message,
            "notification_type": notification_type,
            "dispatch_method": dispatch_method,
            "error_message": error_message[:1000],  # Limitar tamanho
            "failure_reason": failure_reason,
            "scheduled_date": scheduled_date,
            "days_from_due": days_from_due,
            "payment_value": payment.get("value"),
            "due_date": str(payment.get("due_date") or payment.get("dueDate", "")),
            "status": "pending",
            "attempts_count": 1,
        }
        supabase.client.table("billing_failed_notifications").insert(record).execute()
        _log(f"Falha salva no DLQ: {payment['id']} (motivo: {failure_reason})")
    except Exception as e:
        _log_error(f"Erro ao salvar no DLQ: {e}")


async def get_sent_count(agent_id: str, payment_id: str) -> int:
    """
    Conta quantas notificacoes overdue ja foram enviadas para um pagamento.
    Utilizado para controlar maxAttempts na regua de cobranca.
    """
    supabase = get_supabase_service()
    try:
        response = (
            supabase.client.table("billing_notifications")
            .select("id", count="exact")
            .eq("agent_id", agent_id)
            .eq("payment_id", payment_id)
            .eq("notification_type", "overdue")
            .eq("status", "sent")
            .execute()
        )
        return response.count or 0
    except Exception as e:
        _log_error(f"Erro ao contar notificacoes: {e}")
        return 0
