"""
Follow-Up Eligibility - Busca de agentes e leads elegiveis para follow-up.

Extraido de reengajar_leads.py (Fase 5.3).
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pytz

from app.services.supabase import get_supabase_service
from .salvador_config import BLOCKED_PIPELINE_STEPS

logger = logging.getLogger(__name__)

# Prefixo para logs
LOG_PREFIX = "[Salvador]"


# ============================================================================
# LOG HELPERS
# ============================================================================

def _log(msg: str, data: Any = None) -> None:
    extra = f" | {data}" if data else ""
    logger.info(f"{LOG_PREFIX} {msg}{extra}")


def _log_warn(msg: str) -> None:
    logger.warning(f"{LOG_PREFIX} {msg}")


def _log_error(msg: str) -> None:
    logger.error(f"{LOG_PREFIX} {msg}")


# ============================================================================
# DATETIME HELPERS
# ============================================================================

def parse_iso_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """Parse de datetime ISO string para datetime aware (UTC se sem timezone)."""
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = pytz.utc.localize(dt)
        return dt
    except (ValueError, TypeError):
        return None


# ============================================================================
# DATABASE FUNCTIONS
# ============================================================================

async def resolve_shared_whatsapp(
    supabase,
    agents: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Para agentes com uses_shared_whatsapp=true, copia uazapi_base_url/token do parent.

    Args:
        supabase: Servico Supabase
        agents: Lista de agentes

    Returns:
        Lista de agentes com credenciais resolvidas
    """
    parent_ids = [
        a["parent_agent_id"] for a in agents
        if a.get("uses_shared_whatsapp") and a.get("parent_agent_id")
    ]
    if not parent_ids:
        return agents

    parent_resp = (
        supabase.client.table("agents")
        .select("id, uazapi_base_url, uazapi_token, uazapi_instance_id")
        .in_("id", parent_ids)
        .execute()
    )
    parents = {p["id"]: p for p in (parent_resp.data or [])}

    for agent in agents:
        if agent.get("uses_shared_whatsapp") and agent.get("parent_agent_id"):
            parent = parents.get(agent["parent_agent_id"])
            if parent:
                agent["uazapi_base_url"] = parent["uazapi_base_url"]
                agent["uazapi_token"] = parent["uazapi_token"]
                agent["uazapi_instance_id"] = parent["uazapi_instance_id"]
                _log(f"Agente {agent.get('name')} usando WhatsApp do parent {agent['parent_agent_id']}")

    return agents


async def get_agents_with_follow_up() -> List[Dict[str, Any]]:
    """
    Busca agentes com follow-up habilitado.

    Returns:
        Lista de agentes ativos com follow_up_enabled=true e UAZAPI configurado
    """
    supabase = get_supabase_service()
    try:
        response = (
            supabase.client.table("agents")
            .select(
                "id, name, follow_up_enabled, follow_up_config, "
                "salvador_config, salvador_prompt, max_follow_ups, "
                "uazapi_base_url, uazapi_token, uazapi_instance_id, "
                "table_leads, table_messages, timezone, "
                "handoff_triggers, system_prompt, "
                "uses_shared_whatsapp, parent_agent_id"
            )
            .eq("status", "active")
            .eq("follow_up_enabled", True)
            .execute()
        )

        agents = response.data or []

        # Resolver credenciais UAZAPI do parent para agentes com WhatsApp compartilhado
        agents = await resolve_shared_whatsapp(supabase, agents)

        result = []
        for agent in agents:
            if agent.get("uazapi_base_url") and agent.get("uazapi_token"):
                result.append(agent)
            else:
                _log_warn(
                    f"Agente {agent.get('name')} sem UAZAPI configurado, pulando"
                )

        return result

    except Exception as e:
        _log_error(f"Erro ao buscar agentes com follow-up: {e}")
        return []


async def get_eligible_leads(
    agent: Dict[str, Any],
    max_follow_ups: int,
) -> List[Dict[str, Any]]:
    """
    Busca leads elegiveis para follow-up.

    Criterios:
    - Atendimento nao finalizado
    - IA nao pausada
    - Na fila da IA (ou sem fila)
    - Ultima mensagem foi da IA (Msg_model > Msg_user)
    - Nao excedeu maxFollowUps
    - Nao optou por sair do follow-up
    - Pipeline step nao bloqueado

    Args:
        agent: Dados do agente
        max_follow_ups: Maximo de follow-ups por lead

    Returns:
        Lista de leads elegiveis com metadados de mensagem
    """
    supabase = get_supabase_service()
    table_leads = agent.get("table_leads")
    table_messages = agent.get("table_messages")

    if not table_leads or not table_messages:
        _log_warn(f"Agente {agent.get('name')} sem tabelas configuradas")
        return []

    try:
        # Filtro de data minima: so leads com atividade nos ultimos 7 dias
        agent_tz_str = agent.get("timezone", "America/Sao_Paulo")
        try:
            agent_tz = pytz.timezone(agent_tz_str)
        except Exception:
            agent_tz = pytz.timezone("America/Sao_Paulo")
        min_date = datetime.now(agent_tz) - timedelta(days=7)
        min_date_str = min_date.isoformat()

        query = (
            supabase.client.table(table_leads)
            .select("*")
            .neq("Atendimento_Finalizado", "true")
            .gte("updated_date", min_date_str)
        )

        response = query.execute()
        all_leads = response.data or []
        _log(f"Filtro de 7 dias: {len(all_leads)} leads com atividade recente")

        eligible = []
        for lead in all_leads:
            # Filtro: IA nao pausada
            if lead.get("pausar_ia") is True:
                continue

            # Filtro: nao optou por sair
            if lead.get("follow_up_opted_out") is True:
                continue

            # Filtro: follow_up_count nao excedeu maximo
            follow_up_count = lead.get("follow_up_count") or 0
            if follow_up_count >= max_follow_ups:
                continue

            # Filtro: pipeline step bloqueado
            pipeline_step = (lead.get("pipeline_step") or "").lower()
            if pipeline_step in BLOCKED_PIPELINE_STEPS:
                continue

            # Filtro: tem agendamento marcado
            if lead.get("next_appointment_at"):
                continue

            # Filtro: verificar fila da IA
            handoff = agent.get("handoff_triggers") or {}
            queue_ia = handoff.get("queue_ia")
            current_queue = lead.get("current_queue_id")

            if current_queue is not None and queue_ia is not None:
                try:
                    if int(current_queue) != int(queue_ia):
                        continue
                except (ValueError, TypeError) as e:
                    _log_warn(
                        f"Erro ao comparar queues para {lead.get('remotejid')}: "
                        f"current={current_queue}, ia={queue_ia}, erro={e}"
                    )

            # Verificar timestamps de mensagem na tabela de mensagens
            remotejid = lead.get("remotejid")
            if not remotejid:
                continue

            try:
                msg_response = (
                    supabase.client.table(table_messages)
                    .select("Msg_model, Msg_user, creat")
                    .eq("remotejid", remotejid)
                    .order("creat", desc=True)
                    .limit(1)
                    .execute()
                )

                if not msg_response.data:
                    continue

                msg_record = msg_response.data[0]
                msg_model = msg_record.get("Msg_model")
                msg_user = msg_record.get("Msg_user")

                if not msg_model:
                    continue

                if msg_user:
                    model_dt = parse_iso_datetime(msg_model)
                    user_dt = parse_iso_datetime(msg_user)

                    if model_dt and user_dt and user_dt > model_dt:
                        continue

                lead["_last_ia_message_at"] = msg_model
                lead["_last_lead_message_at"] = msg_user

            except Exception as e:
                _log_warn(f"Erro ao verificar mensagens de {remotejid}: {e}")
                continue

            eligible.append(lead)

        return eligible

    except Exception as e:
        _log_error(f"Erro ao buscar leads elegiveis: {e}")
        return []
