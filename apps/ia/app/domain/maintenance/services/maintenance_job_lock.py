"""
Maintenance Job Lock Service - Lock distribuido para job de manutencao.

Usa Redis SET NX EX para garantir que apenas uma instancia
execute o maintenance job por vez em ambientes com multiplas replicas.
"""

import logging
from typing import Optional

from app.services.redis import get_redis_service

logger = logging.getLogger(__name__)

# ============================================================================
# LOCK DISTRIBUIDO (Redis)
# ============================================================================

# Chave do lock no Redis
MAINTENANCE_JOB_LOCK_KEY = "lock:maintenance_job:global"

# TTL: 30 minutos (tempo maximo esperado para o job)
MAINTENANCE_JOB_LOCK_TTL = 1800


def _log(msg: str) -> None:
    """Log com prefixo do job."""
    logger.info(f"[MAINTENANCE JOB] {msg}")


def _log_warn(msg: str) -> None:
    logger.warning(f"[MAINTENANCE JOB] {msg}")


async def acquire_maintenance_lock() -> bool:
    """
    Tenta adquirir o lock global do maintenance job.

    Usa SET NX EX para garantir atomicidade.
    TTL padrao: 30 minutos.

    Returns:
        True se lock foi adquirido, False se ja existe (job rodando)
    """
    redis = await get_redis_service()
    lock_acquired = await redis.client.set(
        MAINTENANCE_JOB_LOCK_KEY, "1", nx=True, ex=MAINTENANCE_JOB_LOCK_TTL
    )

    if not lock_acquired:
        _log_warn("Job ja esta em execucao em outra instancia, pulando...")

    return bool(lock_acquired)


async def release_maintenance_lock() -> None:
    """
    Libera o lock global do maintenance job.
    """
    redis = await get_redis_service()
    await redis.client.delete(MAINTENANCE_JOB_LOCK_KEY)


async def is_maintenance_job_locked() -> bool:
    """
    Verifica se o maintenance job esta rodando (lock existe).

    Returns:
        True se job esta rodando
    """
    redis = await get_redis_service()
    return await redis.client.exists(MAINTENANCE_JOB_LOCK_KEY) > 0
