"""
Billing Job Lock Service - Lock distribuido para billing job.

Extraido de: app/jobs/cobrar_clientes.py (Fase 3)

Usa Redis SET NX EX para garantir que apenas uma instancia
execute o billing job por vez.
"""

import logging
from typing import Optional

from app.services.redis import get_redis_service
from app.domain.billing.models.billing_config import (
    BILLING_JOB_LOCK_KEY,
    BILLING_JOB_LOCK_TTL,
)

logger = logging.getLogger(__name__)


def _log(msg: str) -> None:
    """Log com prefixo do job."""
    logger.info(f"[BILLING JOB] {msg}")


def _log_warn(msg: str) -> None:
    logger.warning(f"[BILLING JOB] {msg}")


async def acquire_billing_lock() -> bool:
    """
    Tenta adquirir o lock global do billing job.

    Usa SET NX EX para garantir atomicidade.
    TTL padrao: 30 minutos.

    Returns:
        True se lock foi adquirido, False se ja existe (job rodando)
    """
    redis = await get_redis_service()
    lock_acquired = await redis.client.set(
        BILLING_JOB_LOCK_KEY, "1", nx=True, ex=BILLING_JOB_LOCK_TTL
    )

    if not lock_acquired:
        _log_warn("Job ja esta em execucao em outra instancia, pulando...")

    return bool(lock_acquired)


async def release_billing_lock() -> None:
    """
    Libera o lock global do billing job.
    """
    redis = await get_redis_service()
    await redis.client.delete(BILLING_JOB_LOCK_KEY)


async def is_billing_job_running() -> bool:
    """
    Verifica se o billing job esta rodando (lock existe).

    Returns:
        True se job esta rodando
    """
    redis = await get_redis_service()
    return await redis.client.exists(BILLING_JOB_LOCK_KEY) > 0
