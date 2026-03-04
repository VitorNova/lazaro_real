# ==============================================================================
# REDIS PAUSE
# Servico de controle de pausa do bot
# ==============================================================================

"""
Controle de pausa do bot com Redis.

Permite pausar o bot para um lead especifico, com TTL opcional.

Funcionalidades:
- Pausar bot (SET com TTL opcional)
- Remover pausa (DEL)
- Verificar se esta pausado
- Obter TTL restante da pausa

Uso:
    from app.integrations.redis import get_pause_service

    pause = await get_pause_service()

    # Pausar por 30 minutos
    await pause.set("agent123", "5511999999999", ttl=1800)

    # Verificar se pausado
    if await pause.is_paused("agent123", "5511999999999"):
        print("Bot pausado para este lead")

    # Remover pausa
    await pause.clear("agent123", "5511999999999")
"""

from __future__ import annotations

import logging
from typing import Optional

from .types import pause_key
from .client import RedisClient, get_redis_client

logger = logging.getLogger(__name__)


# ==============================================================================
# PAUSE SERVICE
# ==============================================================================

class PauseService:
    """
    Servico de controle de pausa do bot.

    Permite pausar o bot para leads especificos.
    """

    def __init__(self, client: RedisClient):
        """
        Inicializa servico de pausa.

        Args:
            client: Cliente Redis conectado
        """
        self._client = client

    async def set(
        self,
        agent_id: str,
        phone: str,
        ttl: Optional[int] = None,
    ) -> None:
        """
        Pausa o bot para um lead especifico.

        Args:
            agent_id: ID do agente
            phone: Telefone do lead
            ttl: Tempo de pausa em segundos (None = indefinido)
        """
        key = pause_key(agent_id, phone)
        await self._client.set(key, "1")
        if ttl is not None:
            await self._client.expire(key, ttl)
        logger.info(f"Bot pausado para {key} (TTL: {ttl}s)")

    async def clear(self, agent_id: str, phone: str) -> bool:
        """
        Remove a pausa do bot.

        Args:
            agent_id: ID do agente
            phone: Telefone do lead

        Returns:
            True se pausa foi removida, False se nao estava pausado
        """
        key = pause_key(agent_id, phone)
        deleted = await self._client.delete(key)
        logger.info(f"Pausa removida para {key}: {deleted > 0}")
        return deleted > 0

    async def is_paused(self, agent_id: str, phone: str) -> bool:
        """
        Verifica se o bot esta pausado.

        Args:
            agent_id: ID do agente
            phone: Telefone do lead

        Returns:
            True se pausado
        """
        key = pause_key(agent_id, phone)
        return await self._client.exists(key) > 0

    async def get_ttl(self, agent_id: str, phone: str) -> int:
        """
        Retorna o tempo restante da pausa.

        Args:
            agent_id: ID do agente
            phone: Telefone do lead

        Returns:
            Segundos restantes (-1 se sem TTL, -2 se nao existe)
        """
        key = pause_key(agent_id, phone)
        return await self._client.ttl(key)

    async def extend(
        self,
        agent_id: str,
        phone: str,
        ttl: int,
    ) -> bool:
        """
        Estende o tempo de pausa.

        Args:
            agent_id: ID do agente
            phone: Telefone do lead
            ttl: Novo tempo de pausa em segundos

        Returns:
            True se pausa foi estendida, False se nao estava pausado
        """
        key = pause_key(agent_id, phone)

        # Verifica se existe
        if not await self._client.exists(key):
            return False

        await self._client.expire(key, ttl)
        logger.info(f"Pausa estendida para {key} (TTL: {ttl}s)")
        return True


# ==============================================================================
# SINGLETON
# ==============================================================================

_pause_service: Optional[PauseService] = None


async def get_pause_service() -> PauseService:
    """
    Obtem instancia singleton do PauseService.

    Returns:
        PauseService conectado
    """
    global _pause_service

    if _pause_service is None:
        client = await get_redis_client()
        _pause_service = PauseService(client)

    return _pause_service
