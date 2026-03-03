"""
Follow-Up Reset - Reset de contadores quando lead responde.

Deve ser chamado no webhook do WhatsApp quando uma mensagem
do lead (IsFromMe=false) e recebida.

NOTA: Esta funcao e importada por mensagens.py.

Extraido de reengajar_leads.py (Fase 5.8).
"""

import logging
from datetime import datetime
from typing import Optional

import pytz

from app.services.supabase import get_supabase_service
from .follow_up_throttle import clear_lead_cooldown
from .follow_up_eligibility import parse_iso_datetime

logger = logging.getLogger(__name__)

LOG_PREFIX = "[Salvador]"


# ============================================================================
# RESET FUNCTION
# ============================================================================

async def reset_follow_up_on_lead_response(
    table_leads: str,
    remotejid: str,
    agent_id: Optional[str] = None,
) -> None:
    """
    Reseta contadores de follow-up quando o lead envia uma mensagem.

    Deve ser chamado no webhook do WhatsApp quando uma mensagem
    do lead (IsFromMe=false) e recebida.

    Args:
        table_leads: Nome da tabela de leads
        remotejid: ID do lead no WhatsApp
        agent_id: ID do agente (opcional, para limpar Redis e marcar respondido)
    """
    supabase = get_supabase_service()
    try:
        now = datetime.utcnow().isoformat()

        # Resetar campos de follow-up no lead
        supabase.client.table(table_leads).update({
            "follow_up_count": 0,
            "follow_up_stage": 0,
            "last_lead_message_at": now,
            "updated_date": now,
        }).eq("remotejid", remotejid).execute()

        if agent_id:
            phone = remotejid.replace("@s.whatsapp.net", "").replace("@lid", "")

            # Marcar follow_up_notifications como respondidas
            try:
                supabase.client.table("follow_up_notifications").update({
                    "lead_responded": True,
                    "responded_at": now,
                }).eq("agent_id", agent_id).eq("lead_phone", phone).eq(
                    "lead_responded", False
                ).execute()
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} Erro ao atualizar follow_up_notifications: {e}")

            # Marcar follow_up_history como respondido
            try:
                last_fu = (
                    supabase.client.table("follow_up_history")
                    .select("id, sent_at")
                    .eq("remotejid", remotejid)
                    .eq("agent_id", agent_id)
                    .eq("lead_responded", False)
                    .order("sent_at", desc=True)
                    .limit(1)
                    .execute()
                )

                if last_fu.data:
                    fu_id = last_fu.data[0]["id"]
                    sent_at = parse_iso_datetime(last_fu.data[0].get("sent_at"))
                    now_dt = datetime.utcnow()
                    if sent_at:
                        now_dt_utc = pytz.utc.localize(now_dt) if now_dt.tzinfo is None else now_dt
                        sent_at_utc = sent_at.astimezone(pytz.utc)
                        response_time = int((now_dt_utc - sent_at_utc).total_seconds() / 60)
                    else:
                        response_time = None

                    supabase.client.table("follow_up_history").update({
                        "lead_responded": True,
                        "responded_at": now,
                        "response_time_minutes": response_time,
                    }).eq("id", fu_id).execute()
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} Erro ao atualizar follow_up_history: {e}")

            # Limpar cooldown Redis do lead
            try:
                await clear_lead_cooldown(agent_id, remotejid)
            except Exception:
                pass

    except Exception as e:
        logger.error(f"{LOG_PREFIX} Erro ao resetar follow-up para {remotejid}: {e}")
