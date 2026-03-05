"""
Maintenance Notifier Job - Entry point para notificacao de manutencao preventiva.

THIN JOB: Logica de negocio delegada para domain/maintenance/services/notification_service.py
Template de mensagem em: prompts/maintenance/reminder_7d.txt

Executa 09:00 dias uteis (seg-sex), timezone America/Cuiaba
"""

import logging
import traceback
from typing import Any, Dict

from app.core.utils.dias_uteis import get_today_brasilia, is_business_day, is_business_hours
from app.domain.maintenance.services import (
    get_maintenance_agent,
    process_maintenance_notifications,
    test_maintenance_notification,
    AGENT_ID_LAZARO,
)

logger = logging.getLogger(__name__)

# Estado do job (evita execucao concorrente)
_is_running = False


async def run_maintenance_notifier_job() -> Dict[str, Any]:
    """Entry point principal do job de notificacao de manutencao."""
    global _is_running

    if _is_running:
        logger.warning("[MAINTENANCE JOB] Job ja esta em execucao, pulando...")
        return {"status": "skipped", "reason": "already_running"}

    hoje = get_today_brasilia()

    if not is_business_day(hoje):
        logger.info("[MAINTENANCE JOB] Hoje nao e dia util, pulando")
        return {"status": "skipped", "reason": "not_business_day"}

    if not is_business_hours(8, 18):
        logger.info("[MAINTENANCE JOB] Fora do horario comercial, pulando")
        return {"status": "skipped", "reason": "outside_business_hours"}

    _is_running = True
    logger.info(f"[MAINTENANCE JOB] Iniciando (hoje={hoje})")

    try:
        agent = await get_maintenance_agent()

        if not agent:
            logger.warning(f"[MAINTENANCE JOB] Agente {AGENT_ID_LAZARO[:8]}... nao encontrado")
            return {"status": "skipped", "reason": "agent_not_found"}

        logger.info(f"[MAINTENANCE JOB] Agente: {agent.get('name')}")

        stats = await process_maintenance_notifications(agent["id"], agent, hoje)

        logger.info(
            f"[MAINTENANCE JOB] Finalizado: {stats['sent']} enviadas, "
            f"{stats['skipped']} puladas, {stats['errors']} erros"
        )

        return {"status": "completed", "stats": stats}

    except Exception as e:
        logger.error(f"[MAINTENANCE JOB] Erro: {e}")
        logger.error(traceback.format_exc())
        return {"status": "error", "error": str(e)}

    finally:
        _is_running = False


async def _force_run_maintenance_notifier() -> Dict[str, Any]:
    """Versao forcada - ignora verificacoes de horario. APENAS PARA DEBUG."""
    global _is_running

    if _is_running:
        return {"status": "skipped", "reason": "already_running"}

    _is_running = True
    hoje = get_today_brasilia()
    logger.info(f"[MAINTENANCE JOB] === EXECUCAO FORCADA (hoje={hoje}) ===")

    try:
        agent = await get_maintenance_agent()
        if not agent:
            return {"status": "skipped", "reason": "agent_not_found"}

        stats = await process_maintenance_notifications(agent["id"], agent, hoje)
        logger.info(f"[MAINTENANCE JOB] Forcado finalizado: {stats}")
        return {"status": "completed", "stats": stats}

    except Exception as e:
        logger.error(f"[MAINTENANCE JOB] Erro forcado: {e}")
        return {"status": "error", "error": str(e)}

    finally:
        _is_running = False


def is_maintenance_notifier_running() -> bool:
    """Verifica se o job esta rodando."""
    return _is_running


# Re-export test function from service for backward compatibility
__all__ = [
    "run_maintenance_notifier_job",
    "_force_run_maintenance_notifier",
    "is_maintenance_notifier_running",
    "test_maintenance_notification",
]
