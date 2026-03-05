"""
Follow-Up Job (Salvador) - Orquestrador de follow-ups automaticos.

Job principal que roda via APScheduler para enviar follow-ups
personalizados usando Gemini para leads inativos.

Extraido de reengajar_leads.py (Fase 5.9).
"""

import asyncio
import logging
import traceback
from datetime import datetime
from typing import Any, Dict

from app.services.supabase import get_supabase_service
from app.services.whatsapp_api import UazapiService

# Imports dos modulos extraidos
from app.domain.leads.services.opt_out_detector import detect_opt_out
from app.domain.leads.services.salvador_config import (
    get_salvador_config,
    is_within_schedule,
)
from app.domain.leads.services.follow_up_eligibility import (
    get_agents_with_follow_up,
    get_eligible_leads,
    resolve_shared_whatsapp,
    parse_iso_datetime,
)
from app.domain.leads.services.follow_up_throttle import (
    can_send_follow_up,
    record_follow_up,
)
from app.domain.leads.services.lead_classifier import (
    load_conversation_history,
    classify_lead_for_follow_up,
)
from app.domain.leads.services.follow_up_message_generator import (
    generate_follow_up_message,
    get_lead_first_name,
)
from app.domain.leads.services.follow_up_recorder import (
    record_follow_up_notification,
    log_follow_up_history,
    update_lead_follow_up,
    save_follow_up_to_history,
)

logger = logging.getLogger(__name__)

# Estado do job (evita execucao concorrente)
_is_running = False

# Prefixo para logs
LOG_PREFIX = "[Salvador]"


# ============================================================================
# LOG HELPERS
# ============================================================================

def _log(msg: str, data: Any = None) -> None:
    extra = f" | {data}" if data else ""
    logger.info(f"{LOG_PREFIX} {msg}{extra}")




# ============================================================================
# HELPERS
# ============================================================================

def _hours_since(dt_str: str, tz_str: str = "America/Cuiaba") -> float:
    """Calcula horas desde um datetime ISO string ate agora."""
    import pytz
    dt = parse_iso_datetime(dt_str)
    if not dt:
        return None
    try:
        tz = pytz.timezone(tz_str)
    except Exception:
        tz = pytz.timezone("America/Cuiaba")
    now = datetime.now(tz)
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    now_utc = now.astimezone(pytz.utc)
    dt_utc = dt.astimezone(pytz.utc)
    diff = (now_utc - dt_utc).total_seconds() / 3600
    return diff


# ============================================================================
# MAIN PROCESSING
# ============================================================================

async def _process_agent_follow_up(
    agent: Dict[str, Any],
    force_mode: bool = False,
) -> Dict[str, int]:
    """
    Processa follow-ups para um agente especifico.

    Args:
        agent: Dados do agente
        force_mode: Ignora verificacoes de horario/dia (debug)

    Returns:
        Dict com estatisticas (sent, skipped, errors)
    """
    stats = {"sent": 0, "skipped": 0, "errors": 0}

    agent_id = agent.get("id", "")
    agent_name = agent.get("name", "Unknown")
    agent_tz = agent.get("timezone", "America/Sao_Paulo")

    # Obter configuracao normalizada do Salvador
    salvador_cfg = get_salvador_config(agent)
    steps_minutes = salvador_cfg["steps_minutes"]
    max_follow_ups = salvador_cfg["max_followups"]
    salvador_prompt = salvador_cfg["prompt"]

    _log(
        f"Processando agente: {agent_name} ({agent_id[:8]}...) "
        f"| {len(steps_minutes)} steps | max={max_follow_ups}"
        f"| prompt={'sim' if salvador_prompt else 'nao'}"
    )

    # Verificar schedule (dias e horario)
    if not force_mode:
        can_run, reason = is_within_schedule(salvador_cfg, agent_tz)
        if not can_run:
            logger.info(f"[FOLLOW UP JOB] Agente {agent_name}: fora do schedule ({reason})")
            return stats

    # Rate limit diario
    max_per_day = 50

    # Buscar leads elegiveis
    eligible_leads = await get_eligible_leads(agent, max_follow_ups)
    logger.info(f"[FOLLOW UP JOB] Encontrados {len(eligible_leads)} leads elegiveis para follow-up")

    if not eligible_leads:
        return stats

    # Configurar UAZAPI
    uazapi = UazapiService(
        base_url=agent["uazapi_base_url"],
        api_key=agent["uazapi_token"],
    )

    table_leads = agent.get("table_leads", "")
    table_messages = agent.get("table_messages", "")

    for lead in eligible_leads:
        lead_id = lead.get("id")
        remotejid = lead.get("remotejid", "")
        telefone = lead.get("telefone") or remotejid.replace("@s.whatsapp.net", "").replace("@lid", "")
        first_name = get_lead_first_name(lead)

        current_count = lead.get("follow_up_count") or 0
        next_follow_up_number = current_count + 1

        # Verificar se ainda ha steps a enviar
        if next_follow_up_number > len(steps_minutes):
            stats["skipped"] += 1
            continue

        # Delay do step atual
        delay_minutes = steps_minutes[next_follow_up_number - 1]
        required_delay_hours = delay_minutes / 60.0

        # Calcular horas desde ultima mensagem da IA
        last_ia_msg = lead.get("_last_ia_message_at") or lead.get("last_follow_up_at")
        hours_since_last = _hours_since(last_ia_msg, agent_tz)

        if hours_since_last is None or hours_since_last < required_delay_hours:
            stats["skipped"] += 1
            continue

        # Rate limiting via Redis
        can_send, reason = await can_send_follow_up(agent_id, remotejid, max_per_day)
        if not can_send:
            logger.info(f"[FOLLOW UP JOB] Rate limited {telefone}: {reason}")
            stats["skipped"] += 1
            continue

        # Carregar historico + verificar opt-out
        conversation_history = await load_conversation_history(agent, remotejid)

        opt_out_detected = False
        for msg in reversed(conversation_history[-5:]):
            if msg.get("role") == "user":
                text = msg.get("content", "")
                if not text and msg.get("parts"):
                    parts = msg["parts"]
                    if isinstance(parts, list):
                        text = " ".join(p.get("text", "") for p in parts if isinstance(p, dict))
                if detect_opt_out(text):
                    logger.warning(f"[FOLLOW UP JOB] Opt-out detectado para {telefone}")
                    opt_out_detected = True
                    try:
                        supabase = get_supabase_service()
                        supabase.client.table(table_leads).update({
                            "follow_up_opted_out": True,
                            "follow_up_opted_out_at": datetime.utcnow().isoformat(),
                        }).eq("id", lead_id).execute()
                    except Exception:
                        pass
                    stats["skipped"] += 1
                    break

        if opt_out_detected:
            continue

        # Classificar lead
        deve_enviar, motivo = await classify_lead_for_follow_up(
            conversation_history, first_name or "lead"
        )
        if not deve_enviar:
            logger.info(f"[FOLLOW UP JOB] Lead {telefone} classificado como SKIP: {motivo}")
            stats["skipped"] += 1
            continue

        # Gerar mensagem
        message = await generate_follow_up_message(
            lead, agent, conversation_history, next_follow_up_number,
            custom_prompt=salvador_prompt,
        )

        if message.strip().upper().startswith("SKIP"):
            logger.info(f"[FOLLOW UP JOB] Gemini retornou SKIP para {telefone}")
            stats["skipped"] += 1
            continue

        logger.info(f"[FOLLOW UP JOB] Lead {telefone} - {hours_since_last:.1f}h - enviando follow-up #{next_follow_up_number}")

        try:
            # Enviar mensagem
            result = await uazapi.send_signed_message(telefone, message, agent_name)

            if not result.get("success"):
                raise ValueError(result.get("error", "Erro desconhecido"))

            logger.info(f"[FOLLOW UP JOB] Follow-up #{next_follow_up_number} enviado para {telefone}: {message[:60]}...")

            # Registrar em Redis
            await record_follow_up(agent_id, remotejid)

            # Registrar em tabelas
            await record_follow_up_notification(agent_id, telefone, next_follow_up_number, message)
            await log_follow_up_history(agent_id, lead, remotejid, next_follow_up_number, message, table_leads)
            await update_lead_follow_up(table_leads, lead_id, next_follow_up_number, next_follow_up_number)
            await save_follow_up_to_history(table_messages, remotejid, message, next_follow_up_number)

            stats["sent"] += 1
            await asyncio.sleep(1.5)

        except Exception as e:
            logger.error(f"[FOLLOW UP JOB] Erro ao enviar follow-up para {telefone}: {e}")
            stats["errors"] += 1

    return stats


# ============================================================================
# JOB ENTRY POINTS
# ============================================================================

async def run_follow_up_job() -> Dict[str, Any]:
    """
    Job principal de follow-up (Salvador).
    Roda a cada 5 minutos via APScheduler.
    """
    global _is_running

    if _is_running:
        logger.warning("[FOLLOW UP JOB] Job ja esta em execucao, pulando...")
        return {"status": "skipped", "reason": "already_running"}

    _is_running = True
    logger.info("[FOLLOW UP JOB] Iniciando job de follow-up...")

    total_stats = {"sent": 0, "skipped": 0, "errors": 0, "agents_processed": 0}

    try:
        agents = await get_agents_with_follow_up()
        logger.info(f"[FOLLOW UP JOB] Encontrados {len(agents)} agentes com follow-up habilitado")

        if not agents:
            return {"status": "completed", "stats": total_stats, "message": "no_agents"}

        for agent in agents:
            agent_name = agent.get("name", "Unknown")
            try:
                agent_stats = await _process_agent_follow_up(agent)
                total_stats["sent"] += agent_stats.get("sent", 0)
                total_stats["skipped"] += agent_stats.get("skipped", 0)
                total_stats["errors"] += agent_stats.get("errors", 0)
                total_stats["agents_processed"] += 1
            except Exception as e:
                logger.error(f"[FOLLOW UP JOB] Erro ao processar agente {agent_name}: {e}")
                logger.error(traceback.format_exc())
                total_stats["errors"] += 1

        logger.info(f"[FOLLOW UP JOB] Job finalizado: {total_stats['sent']} enviados, {total_stats['skipped']} pulados")
        return {"status": "completed", "stats": total_stats}

    except Exception as e:
        logger.error(f"[FOLLOW UP JOB] Erro no processamento: {e}")
        return {"status": "error", "error": str(e)}

    finally:
        _is_running = False


def is_follow_up_running() -> bool:
    """Verifica se o job esta em execucao."""
    return _is_running


async def force_run_follow_up() -> Dict[str, Any]:
    """
    Versao forcada do job - ignora verificacoes de horario/dia util.
    APENAS PARA DEBUG/TESTES.
    """
    global _is_running

    if _is_running:
        logger.warning("[FOLLOW UP JOB] Job ja esta em execucao, pulando...")
        return {"status": "skipped", "reason": "already_running"}

    _is_running = True
    logger.info("[FOLLOW UP JOB] === EXECUCAO FORCADA ===")

    total_stats = {"sent": 0, "skipped": 0, "errors": 0, "agents_processed": 0}

    try:
        supabase = get_supabase_service()
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

        agents = await resolve_shared_whatsapp(supabase, response.data or [])
        agents = [a for a in agents if a.get("uazapi_base_url") and a.get("uazapi_token")]

        logger.info(f"[FOLLOW UP JOB] Encontrados {len(agents)} agentes com follow-up habilitado")

        for agent in agents:
            agent_name = agent.get("name", "Unknown")
            try:
                agent_stats = await _process_agent_follow_up(agent, force_mode=True)
                total_stats["sent"] += agent_stats.get("sent", 0)
                total_stats["skipped"] += agent_stats.get("skipped", 0)
                total_stats["errors"] += agent_stats.get("errors", 0)
                total_stats["agents_processed"] += 1
            except Exception as e:
                logger.error(f"[FOLLOW UP JOB] Erro ao processar agente {agent_name}: {e}")
                total_stats["errors"] += 1

        logger.info(f"[FOLLOW UP JOB] === Job finalizado: {total_stats['sent']} enviados ===")
        return {"status": "completed", "stats": total_stats}

    except Exception as e:
        logger.error(f"[FOLLOW UP JOB] Erro no processamento: {e}")
        return {"status": "error", "error": str(e)}

    finally:
        _is_running = False
