"""
Follow-Up Throttle - Rate limiting via Redis para follow-ups.

Extraido de reengajar_leads.py (Fase 5.4).
"""

import logging
from datetime import datetime
from typing import Tuple

logger = logging.getLogger(__name__)

LOG_PREFIX = "[Salvador]"


# ============================================================================
# REDIS CLIENT
# ============================================================================

async def get_redis_client():
    """
    Obtem cliente Redis (retorna None se indisponivel).

    Returns:
        Cliente Redis ou None
    """
    try:
        from app.services import get_redis_service
        redis_svc = await get_redis_service()
        return redis_svc.client
    except Exception:
        return None


# ============================================================================
# RATE LIMITING
# ============================================================================

async def can_send_follow_up(
    agent_id: str,
    remotejid: str,
    max_per_day: int = 50,
) -> Tuple[bool, str]:
    """
    Verifica rate limiting via Redis.

    Args:
        agent_id: ID do agente
        remotejid: ID do lead no WhatsApp
        max_per_day: Maximo de follow-ups por dia por agente

    Returns:
        Tupla (pode_enviar, motivo)
    """
    redis_client = await get_redis_client()
    if not redis_client:
        return True, "redis_unavailable"

    try:
        # Check daily limit por agente
        date_key = datetime.utcnow().strftime("%Y-%m-%d")
        daily_key = f"salvador:daily:{agent_id}:{date_key}"
        daily_count = await redis_client.get(daily_key)
        if daily_count and int(daily_count) >= max_per_day:
            return False, f"daily_limit ({daily_count}/{max_per_day})"

        # Check per-lead cooldown (evita flood)
        lead_key = f"salvador:lead:{agent_id}:{remotejid}"
        if await redis_client.exists(lead_key):
            return False, "lead_cooldown"

        return True, "ok"
    except Exception as e:
        logger.warning(f"{LOG_PREFIX} Redis rate limit check error: {e}")
        return True, "redis_error"


async def record_follow_up(
    agent_id: str,
    remotejid: str,
    cooldown_seconds: int = 3600,
) -> None:
    """
    Registra envio no Redis para rate limiting.

    Args:
        agent_id: ID do agente
        remotejid: ID do lead no WhatsApp
        cooldown_seconds: Tempo de cooldown entre follow-ups (default 1h)
    """
    redis_client = await get_redis_client()
    if not redis_client:
        return

    try:
        # Incrementa contador diario
        date_key = datetime.utcnow().strftime("%Y-%m-%d")
        daily_key = f"salvador:daily:{agent_id}:{date_key}"
        await redis_client.incr(daily_key)
        await redis_client.expire(daily_key, 86400)

        # Seta cooldown por lead (default 1h entre follow-ups do mesmo lead)
        lead_key = f"salvador:lead:{agent_id}:{remotejid}"
        await redis_client.set(lead_key, "1", ex=cooldown_seconds)
    except Exception as e:
        logger.warning(f"{LOG_PREFIX} Redis record error: {e}")


async def clear_lead_cooldown(agent_id: str, remotejid: str) -> None:
    """
    Remove cooldown de um lead especifico (usado no reset).

    Args:
        agent_id: ID do agente
        remotejid: ID do lead no WhatsApp
    """
    redis_client = await get_redis_client()
    if not redis_client:
        return

    try:
        lead_key = f"salvador:lead:{agent_id}:{remotejid}"
        await redis_client.delete(lead_key)
    except Exception as e:
        logger.warning(f"{LOG_PREFIX} Redis clear cooldown error: {e}")
