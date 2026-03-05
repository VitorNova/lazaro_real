"""
Follow-Up Job - Envio automatico de follow-ups inteligentes (Salvador).

THIN DISPATCHER - Refatorado na Fase 3.
A logica de negocio foi movida para domain/leads/services/.

Fluxo:
1. Verifica se job ja esta rodando (estado local)
2. Busca agentes com follow-up habilitado
3. Processa follow-ups via follow_up_orchestrator
4. Retorna estatisticas
"""

import logging
import traceback
from typing import Any, Dict

# Imports do domain/leads/services
from app.domain.leads.services import (
    get_agents_with_follow_up,
    resolve_shared_whatsapp,
    process_agent_follow_up,
    reset_follow_up_on_lead_response,
)
from app.services.supabase import get_supabase_service

logger = logging.getLogger(__name__)

# Estado do job (evita execucao concorrente)
_is_running = False

LOG_PREFIX = "[Salvador]"


def _log(msg: str, data: Any = None) -> None:
    extra = f" | {data}" if data else ""
    logger.info(f"{LOG_PREFIX} {msg}{extra}")




async def run_follow_up_job() -> Dict[str, Any]:
    """
    Job principal de follow-up (Salvador).
    Roda a cada 5 minutos via APScheduler.
    Respeita horario comercial e dias uteis via config do agente.
    """
    global _is_running

    if _is_running:
        logger.warning("[REENGAJAR LEADS] Job ja esta em execucao, pulando...")
        return {"status": "skipped", "reason": "already_running"}

    _is_running = True
    logger.info("[REENGAJAR LEADS] Iniciando job de follow-up...")

    total_stats = {
        "sent": 0, "skipped": 0, "errors": 0,
        "agents_processed": 0
    }

    try:
        agents = await get_agents_with_follow_up()
        logger.info(f"[REENGAJAR LEADS] Encontrados {len(agents)} agentes com follow-up habilitado")

        if not agents:
            logger.info("[REENGAJAR LEADS] Nenhum agente com follow-up habilitado encontrado")
            return {"status": "completed", "stats": total_stats, "message": "no_agents"}

        for agent in agents:
            agent_name = agent.get("name", "Unknown")
            agent_id = agent.get("id", "")
            logger.info(f"[REENGAJAR LEADS] Processando agente: {agent_name} ({agent_id[:8]}...)")

            try:
                agent_stats = await process_agent_follow_up(agent)
                total_stats["sent"] += agent_stats.get("sent", 0)
                total_stats["skipped"] += agent_stats.get("skipped", 0)
                total_stats["errors"] += agent_stats.get("errors", 0)
                total_stats["agents_processed"] += 1
                logger.info(f"[REENGAJAR LEADS] Agente {agent_name}: {agent_stats}")
            except Exception as e:
                logger.error(f"[REENGAJAR LEADS] Erro ao processar agente {agent_name}: {e}")
                logger.error(traceback.format_exc())
                total_stats["errors"] += 1

        _log(
            f"Job finalizado: {total_stats['sent']} follow-ups enviados, "
            f"{total_stats['skipped']} pulados, {total_stats['errors']} erros"
        )

        return {"status": "completed", "stats": total_stats}

    except Exception as e:
        logger.error(f"[REENGAJAR LEADS] Erro no processamento: {e}")
        logger.error(traceback.format_exc())
        return {"status": "error", "error": str(e)}

    finally:
        _is_running = False


def is_follow_up_running() -> bool:
    """Verifica se o job esta em execucao."""
    return _is_running


async def _force_run_follow_up() -> Dict[str, Any]:
    """
    Versao forcada do job - ignora verificacoes de horario/dia util.
    APENAS PARA DEBUG/TESTES.
    """
    global _is_running

    if _is_running:
        logger.warning("[REENGAJAR LEADS] Job ja esta em execucao, pulando...")
        return {"status": "skipped", "reason": "already_running"}

    _is_running = True
    logger.info("[REENGAJAR LEADS] === EXECUCAO FORCADA (ignorando horario/dia util) ===")

    total_stats = {
        "sent": 0, "skipped": 0, "errors": 0,
        "agents_processed": 0
    }

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
        agents = [
            a for a in agents
            if a.get("uazapi_base_url") and a.get("uazapi_token")
        ]

        logger.info(f"[REENGAJAR LEADS] Encontrados {len(agents)} agentes com follow-up habilitado")

        if not agents:
            logger.info("[REENGAJAR LEADS] Nenhum agente com follow-up habilitado encontrado")
            return {"status": "completed", "stats": total_stats, "message": "no_agents"}

        for agent in agents:
            agent_name = agent.get("name", "Unknown")
            agent_id = agent.get("id", "")
            logger.info(f"[REENGAJAR LEADS] Processando agente: {agent_name} ({agent_id})")

            try:
                # force_mode=True ignora schedule (horario/dia)
                agent_stats = await process_agent_follow_up(agent, force_mode=True)
                total_stats["sent"] += agent_stats.get("sent", 0)
                total_stats["skipped"] += agent_stats.get("skipped", 0)
                total_stats["errors"] += agent_stats.get("errors", 0)
                total_stats["agents_processed"] += 1
                logger.info(f"[REENGAJAR LEADS] Agente {agent_name}: {agent_stats}")
            except Exception as e:
                logger.error(f"[REENGAJAR LEADS] Erro ao processar agente {agent_name}: {e}")
                logger.error(traceback.format_exc())
                total_stats["errors"] += 1

        _log(
            f"=== Job finalizado: {total_stats['sent']} follow-ups enviados, "
            f"{total_stats['skipped']} pulados, {total_stats['errors']} erros ==="
        )

        return {"status": "completed", "stats": total_stats}

    except Exception as e:
        logger.error(f"[REENGAJAR LEADS] Erro no processamento: {e}")
        logger.error(traceback.format_exc())
        return {"status": "error", "error": str(e)}

    finally:
        _is_running = False


# Re-exportar para compatibilidade com imports existentes
# (mensagens.py importa esta funcao diretamente)
__all__ = [
    "run_follow_up_job",
    "is_follow_up_running",
    "_force_run_follow_up",
    "reset_follow_up_on_lead_response",
]
