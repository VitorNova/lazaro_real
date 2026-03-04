"""Billing Job V2 - Entry point do cron."""
import logging
from typing import Any, Dict

from app.billing.agent_processor import process_agent
from app.domain.billing.models.billing_config import BILLING_JOB_LOCK_KEY, BILLING_JOB_LOCK_TTL
from app.domain.billing.services.billing_rules import get_agents_with_asaas
from app.services.redis import get_redis_service
from app.utils.dias_uteis import get_today_brasilia, is_business_day, is_business_hours

logger = logging.getLogger(__name__)


async def run_billing_v2() -> Dict[str, Any]:
    """
    Entry point do job de cobranca v2.

    Executa:
    1. Lock distribuido (Redis)
    2. Validacao de dia util e horario
    3. Processamento de cada agente
    4. Estatisticas consolidadas
    """
    redis = await get_redis_service()

    # Lock distribuido para evitar execucao concorrente
    lock = await redis.client.set(
        BILLING_JOB_LOCK_KEY, "v2", nx=True, ex=BILLING_JOB_LOCK_TTL
    )
    if not lock:
        logger.info({"event": "billing_v2_skipped", "reason": "already_running"})
        return {"status": "skipped", "reason": "already_running"}

    try:
        today = get_today_brasilia()

        # Validar dia util
        if not is_business_day(today):
            logger.info({"event": "billing_v2_skipped", "reason": "not_business_day"})
            return {"status": "skipped", "reason": "not_business_day"}

        # Validar horario comercial (8h-20h Brasilia)
        if not is_business_hours(8, 20):
            logger.info({"event": "billing_v2_skipped", "reason": "outside_hours"})
            return {"status": "skipped", "reason": "outside_business_hours"}

        # Buscar agentes com Asaas configurado
        agents = await get_agents_with_asaas()
        logger.info({"event": "billing_v2_start", "agents_count": len(agents)})

        stats = {
            "sent": 0,
            "skipped": 0,
            "errors": 0,
            "degraded": 0,
            "agents": 0,
        }

        # Processar cada agente
        for agent in agents:
            try:
                result = await process_agent(agent, today)
                stats["sent"] += result.get("sent", 0)
                stats["skipped"] += result.get("skipped", 0)
                stats["errors"] += result.get("errors", 0)
                if result.get("degraded"):
                    stats["degraded"] += 1
                stats["agents"] += 1
            except Exception as e:
                logger.error({
                    "event": "agent_processing_error",
                    "agent_id": agent.get("id"),
                    "error": str(e),
                })
                stats["errors"] += 1

        logger.info({"event": "billing_v2_complete", **stats})
        return {"status": "completed", "stats": stats}

    finally:
        await redis.client.delete(BILLING_JOB_LOCK_KEY)
