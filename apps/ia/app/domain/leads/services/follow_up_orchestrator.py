"""
Follow-Up Orchestrator - Logica principal de processamento de follow-ups.

Extraido de reengajar_leads.py (Fase 3).

Funcionalidades:
- Processamento de follow-ups por agente
- Verificacao de schedule (dias/horarios)
- Integracao com classificador IA
- Envio via UAZAPI
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List

import pytz

from app.services.whatsapp_api import UazapiService

from .opt_out_detector import detect_opt_out
from .salvador_config import get_salvador_config, is_within_schedule
from .follow_up_throttle import can_send_follow_up, record_follow_up
from .lead_classifier import (
    load_conversation_history,
    classify_lead_for_follow_up,
)
from .follow_up_message_generator import (
    generate_follow_up_message,
    get_lead_first_name,
)
from .follow_up_eligibility import get_eligible_leads
from .follow_up_recorder import (
    record_follow_up_notification,
    log_follow_up_history,
    update_lead_follow_up,
    save_follow_up_to_history,
)
from app.services.supabase import get_supabase_service

logger = logging.getLogger(__name__)

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
# TIME HELPERS
# ============================================================================

def _get_now_in_timezone(tz_str: str = "America/Cuiaba") -> datetime:
    """Retorna datetime atual no timezone especificado."""
    try:
        tz = pytz.timezone(tz_str)
    except Exception:
        tz = pytz.timezone("America/Cuiaba")
    return datetime.now(tz)


def _hours_since(dt_str: str, tz_str: str = "America/Cuiaba") -> float:
    """Calcula horas desde um datetime ISO string ate agora."""
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = pytz.utc.localize(dt)
    except (ValueError, TypeError):
        return None

    now = _get_now_in_timezone(tz_str)
    now_utc = now.astimezone(pytz.utc)
    dt_utc = dt.astimezone(pytz.utc)
    diff = (now_utc - dt_utc).total_seconds() / 3600
    return diff


# ============================================================================
# MAIN PROCESSING
# ============================================================================

async def process_agent_follow_up(
    agent: Dict[str, Any],
    force_mode: bool = False,
) -> Dict[str, int]:
    """
    Processa follow-ups para um agente especifico.
    Usa Gemini para gerar mensagens personalizadas com base no historico.

    Args:
        agent: Dados do agente
        force_mode: Se True, ignora verificacoes de horario/dia (debug)

    Returns:
        Dict com contadores: sent, skipped, errors
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
            _log(f"Agente {agent_name}: fora do schedule ({reason})")
            return stats

    # Rate limit diario (fixo: 50/dia por agente)
    max_per_day = 50

    # Buscar leads elegiveis
    eligible_leads = await get_eligible_leads(agent, max_follow_ups)
    _log(f"Encontrados {len(eligible_leads)} leads elegiveis para follow-up")

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
        nome = lead.get("nome") or lead.get("push_name") or "Cliente"
        telefone = lead.get("telefone") or remotejid.replace("@s.whatsapp.net", "").replace("@lid", "")
        first_name = get_lead_first_name(lead)

        current_count = lead.get("follow_up_count") or 0
        next_follow_up_number = current_count + 1

        # Verificar se ainda ha steps a enviar
        if next_follow_up_number > len(steps_minutes):
            stats["skipped"] += 1
            continue

        # Delay do step atual em minutos (convertido para horas)
        delay_minutes = steps_minutes[next_follow_up_number - 1]
        required_delay_hours = delay_minutes / 60.0

        # Calcular horas desde ultima mensagem da IA
        last_ia_msg = lead.get("_last_ia_message_at") or lead.get("last_follow_up_at")
        hours_since_last = _hours_since(last_ia_msg, agent_tz)

        if hours_since_last is None:
            stats["skipped"] += 1
            continue

        # Verificar se ja passou tempo suficiente
        if hours_since_last < required_delay_hours:
            continue

        # ================================================================
        # RATE LIMITING via Redis
        # ================================================================
        can_send, reason = await can_send_follow_up(
            agent_id, remotejid, max_per_day
        )
        if not can_send:
            _log(f"Rate limited {telefone}: {reason}")
            stats["skipped"] += 1
            continue

        # ================================================================
        # CARREGAR HISTORICO + OPT-OUT CHECK
        # ================================================================
        conversation_history = await load_conversation_history(agent, remotejid)

        # Verificar opt-out nas ultimas mensagens do usuario
        opt_out_detected = False
        for msg in reversed(conversation_history[-5:]):
            if msg.get("role") == "user":
                text = ""
                if msg.get("content"):
                    text = msg["content"]
                elif msg.get("parts"):
                    parts = msg["parts"]
                    if isinstance(parts, list):
                        text = " ".join(
                            p.get("text", "") for p in parts if isinstance(p, dict)
                        )
                if detect_opt_out(text):
                    _log_warn(f"Opt-out detectado para {telefone}, marcando lead")
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

        # ================================================================
        # CLASSIFICAR LEAD (Gemini Flash - decide se envia ou nao)
        # ================================================================
        deve_enviar, motivo = await classify_lead_for_follow_up(
            conversation_history, first_name or "lead"
        )
        if not deve_enviar:
            _log(f"Lead {telefone} classificado como SKIP: {motivo}")
            stats["skipped"] += 1
            continue

        # ================================================================
        # GERAR MENSAGEM
        # ================================================================
        message = await generate_follow_up_message(
            lead, agent, conversation_history, next_follow_up_number,
            custom_prompt=salvador_prompt,
        )

        # Verificar se Gemini decidiu nao enviar (SKIP)
        if message.strip().upper().startswith("SKIP"):
            _log(f"Gemini retornou SKIP para {telefone} - contexto nao requer follow-up")
            stats["skipped"] += 1
            continue

        _log(
            f"Lead {telefone} - {hours_since_last:.1f}h desde ultimo contato "
            f"- enviando follow-up #{next_follow_up_number} ({len(message)} chars)"
        )

        try:
            # Enviar mensagem via WhatsApp com assinatura do agente
            result = await uazapi.send_signed_message(telefone, message, agent_name)

            if not result.get("success"):
                raise ValueError(result.get("error", "Erro desconhecido ao enviar"))

            _log(f"Follow-up #{next_follow_up_number} enviado para {telefone} ({agent_name}): {message[:80]}...")

            # Registrar em Redis
            await record_follow_up(agent_id, remotejid)

            # Registrar notificacao (tabela legacy)
            await record_follow_up_notification(
                agent_id, telefone, next_follow_up_number, message
            )

            # Registrar no follow_up_history (metricas)
            await log_follow_up_history(
                agent_id, lead, remotejid,
                next_follow_up_number, message, table_leads
            )

            # Atualizar campos de follow-up no lead
            await update_lead_follow_up(
                table_leads, lead_id, next_follow_up_number, next_follow_up_number
            )

            # Salvar no conversation_history
            await save_follow_up_to_history(
                table_messages, remotejid, message, next_follow_up_number
            )

            stats["sent"] += 1

            # Rate limiting: esperar 1.5s entre envios
            await asyncio.sleep(1.5)

        except Exception as e:
            _log_error(f"Erro ao enviar follow-up para {telefone}: {e}")
            stats["errors"] += 1

    return stats
