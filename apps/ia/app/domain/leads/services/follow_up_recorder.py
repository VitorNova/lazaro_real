"""
Follow-Up Recorder - Registro de follow-ups enviados no Supabase.

Registra envios nas tabelas:
- follow_up_notifications
- follow_up_history
- table_leads (atualiza campos)
- table_messages (salva no conversation_history)

Extraido de reengajar_leads.py (Fase 5.7).
"""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from app.services.supabase import get_supabase_service

logger = logging.getLogger(__name__)

LOG_PREFIX = "[Salvador]"


# ============================================================================
# LOG HELPERS
# ============================================================================

def _log_warn(msg: str) -> None:
    logger.warning(f"{LOG_PREFIX} {msg}")


def _log_error(msg: str) -> None:
    logger.error(f"{LOG_PREFIX} {msg}")


# ============================================================================
# RECORDING FUNCTIONS
# ============================================================================

async def record_follow_up_notification(
    agent_id: str,
    lead_phone: str,
    follow_up_number: int,
    message_sent: str,
) -> None:
    """
    Registra follow-up enviado na tabela follow_up_notifications.

    Args:
        agent_id: ID do agente
        lead_phone: Telefone do lead
        follow_up_number: Numero do follow-up (1, 2, 3...)
        message_sent: Mensagem enviada
    """
    supabase = get_supabase_service()
    try:
        supabase.client.table("follow_up_notifications").insert({
            "agent_id": agent_id,
            "lead_phone": lead_phone,
            "follow_up_number": follow_up_number,
            "message_sent": message_sent,
            "sent_at": datetime.utcnow().isoformat(),
            "lead_responded": False,
        }).execute()
    except Exception as e:
        _log_error(f"Erro ao registrar follow-up notification: {e}")


async def log_follow_up_history(
    agent_id: str,
    lead: Dict[str, Any],
    remotejid: str,
    step_number: int,
    message: str,
    table_leads: str,
) -> Optional[str]:
    """
    Registra follow-up na tabela follow_up_history (metricas).

    Args:
        agent_id: ID do agente
        lead: Dados do lead
        remotejid: ID do lead no WhatsApp
        step_number: Numero do follow-up
        message: Mensagem enviada
        table_leads: Nome da tabela de leads

    Returns:
        ID do registro criado ou None
    """
    supabase = get_supabase_service()
    try:
        lead_id = lead.get("id")
        # follow_up_history.lead_id e integer NOT NULL
        if not isinstance(lead_id, int):
            try:
                lead_id = int(lead_id)
            except (ValueError, TypeError):
                return None

        data = {
            "agent_id": agent_id,
            "lead_id": lead_id,
            "table_leads": table_leads,
            "remotejid": remotejid,
            "step_number": step_number,
            "follow_up_type": "inactivity",
            "message_sent": message,
            "lead_name": lead.get("nome") or lead.get("push_name"),
            "pipeline_step": lead.get("pipeline_step"),
        }

        result = (
            supabase.client.table("follow_up_history")
            .insert(data)
            .execute()
        )

        if result.data:
            return result.data[0].get("id")
    except Exception as e:
        _log_warn(f"Erro ao registrar follow_up_history: {e}")

    return None


async def update_lead_follow_up(
    table_leads: str,
    lead_id: int,
    follow_up_count: int,
    follow_up_stage: int,
) -> None:
    """
    Atualiza campos de follow-up no lead apos envio.

    Args:
        table_leads: Nome da tabela de leads
        lead_id: ID do lead
        follow_up_count: Contador de follow-ups
        follow_up_stage: Estagio atual do follow-up
    """
    supabase = get_supabase_service()
    try:
        supabase.client.table(table_leads).update({
            "follow_up_count": follow_up_count,
            "follow_up_stage": follow_up_stage,
            "last_follow_up_at": datetime.utcnow().isoformat(),
            "follow_count": follow_up_count,
            "updated_date": datetime.utcnow().isoformat(),
        }).eq("id", lead_id).execute()
    except Exception as e:
        _log_error(f"Erro ao atualizar lead follow-up: {e}")


async def save_follow_up_to_history(
    table_messages: str,
    remotejid: str,
    message: str,
    follow_up_number: int,
) -> None:
    """
    Salva mensagem de follow-up no conversation_history do lead.

    Adiciona nota de contexto para a IA entender que foi follow-up.

    Args:
        table_messages: Nome da tabela de mensagens
        remotejid: ID do lead no WhatsApp
        message: Mensagem enviada
        follow_up_number: Numero do follow-up
    """
    supabase = get_supabase_service()
    try:
        response = (
            supabase.client.table(table_messages)
            .select("id, conversation_history")
            .eq("remotejid", remotejid)
            .order("creat", desc=True)
            .limit(1)
            .execute()
        )

        if not response.data:
            return

        msg_record = response.data[0]
        history = msg_record.get("conversation_history") or {"messages": []}
        messages = history.get("messages", [])

        now = datetime.utcnow().isoformat()

        # Adicionar nota de contexto para a IA entender que foi follow-up
        context_note = "[CONTEXTO: Esta mensagem foi um follow-up automatico enviado porque o lead nao respondeu. O historico completo da conversa esta acima. Continue a conversa normalmente a partir do contexto anterior.]"
        message_with_context = f"{context_note}\n\n{message}"

        messages.append({
            "role": "model",
            "parts": [{"text": message_with_context}],
            "timestamp": now,
            "sender": "follow_up",
            "sender_name": f"Follow-up #{follow_up_number}",
            "type": "follow_up_notification",
            "follow_up_number": follow_up_number,
        })

        supabase.client.table(table_messages).update({
            "conversation_history": {"messages": messages},
            "Msg_model": now,
            "creat": now,
        }).eq("id", msg_record["id"]).execute()

    except Exception as e:
        _log_warn(f"Erro ao salvar follow-up no historico: {e}")
