# ==============================================================================
# REDIS LOCK
# Servico de lock distribuido
# ==============================================================================

"""
Lock distribuido com Redis.

Usa SET NX EX para garantir atomicidade e evitar race conditions.

Funcionalidades:
- Adquirir lock (SET NX EX)
- Liberar lock (DEL)
- Verificar se lock existe
- Estender TTL do lock
- Wrapper withLock para execucao com lock automatico

Uso:
    from app.integrations.redis import get_lock_service

    lock = await get_lock_service()

    # Adquirir lock
    if await lock.acquire("agent123", "5511999999999"):
        try:
            # Processar...
            pass
        finally:
            await lock.release("agent123", "5511999999999")

    # Ou usar withLock
    async def process():
        return "resultado"

    result = await lock.with_lock("agent123", "5511999999999", process)
"""

from __future__ import annotations

import logging
from typing import Optional, Callable, TypeVar, Awaitable

from .types import LOCK_TTL_SECONDS, LockInfo, lock_key
from .client import RedisClient, get_redis_client

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ==============================================================================
# LOCK SERVICE
# ==============================================================================

class LockService:
    """
    Servico de lock distribuido usando Redis.

    Previne processamento duplicado em ambiente multi-instancia.
    """

    def __init__(self, client: RedisClient):
        """
        Inicializa servico de lock.

        Args:
            client: Cliente Redis conectado
        """
        self._client = client

    async def acquire(
        self,
        agent_id: str,
        phone: str,
        ttl: int = LOCK_TTL_SECONDS,
    ) -> bool:
        """
        Tenta adquirir um lock.

        Usa SET NX EX para garantir atomicidade.

        Args:
            agent_id: ID do agente
            phone: Telefone do lead
            ttl: Tempo de vida do lock em segundos

        Returns:
            True se lock foi adquirido, False se ja existe
        """
        key = lock_key(agent_id, phone)
        acquired = await self._client.set(key, "1", nx=True, ex=ttl)
        logger.debug(f"Lock {key} adquirido: {acquired is not None}")
        return acquired is not None

    async def release(self, agent_id: str, phone: str) -> bool:
        """
        Libera o lock.

        Args:
            agent_id: ID do agente
            phone: Telefone do lead

        Returns:
            True se lock foi liberado, False se nao existia
        """
        key = lock_key(agent_id, phone)
        deleted = await self._client.delete(key)
        logger.debug(f"Lock {key} liberado: {deleted > 0}")
        return deleted > 0

    async def exists(self, agent_id: str, phone: str) -> bool:
        """
        Verifica se lock existe.

        Args:
            agent_id: ID do agente
            phone: Telefone do lead

        Returns:
            True se lock existe
        """
        key = lock_key(agent_id, phone)
        return await self._client.exists(key) > 0

    async def extend(
        self,
        agent_id: str,
        phone: str,
        ttl: int = LOCK_TTL_SECONDS,
    ) -> bool:
        """
        Estende o TTL de um lock existente.

        Args:
            agent_id: ID do agente
            phone: Telefone do lead
            ttl: Novo tempo de vida em segundos

        Returns:
            True se TTL foi estendido, False se lock nao existe
        """
        key = lock_key(agent_id, phone)
        extended = await self._client.expire(key, ttl)
        logger.debug(f"Lock {key} estendido: {extended}")
        return extended

    async def get_info(self, agent_id: str, phone: str) -> Optional[LockInfo]:
        """
        Obtem informacoes sobre um lock.

        Args:
            agent_id: ID do agente
            phone: Telefone do lead

        Returns:
            LockInfo ou None se lock nao existe
        """
        key = lock_key(agent_id, phone)

        value = await self._client.get(key)
        if value is None:
            return None

        ttl = await self._client.ttl(key)

        return {
            "holder": value,
            "ttl": ttl,
            "key": key,
        }

    async def with_lock(
        self,
        agent_id: str,
        phone: str,
        fn: Callable[[], Awaitable[T]],
        ttl: int = LOCK_TTL_SECONDS,
    ) -> Optional[T]:
        """
        Executa funcao com lock automatico.

        Adquire lock, executa funcao, libera lock.
        Se lock nao pode ser adquirido, retorna None.

        Args:
            agent_id: ID do agente
            phone: Telefone do lead
            fn: Funcao async a executar
            ttl: Tempo de vida do lock

        Returns:
            Resultado da funcao ou None se lock nao foi adquirido
        """
        acquired = await self.acquire(agent_id, phone, ttl)

        if not acquired:
            logger.info(f"Lock nao adquirido para {agent_id}:{phone}")
            return None

        try:
            return await fn()
        finally:
            await self.release(agent_id, phone)


# ==============================================================================
# SINGLETON
# ==============================================================================

_lock_service: Optional[LockService] = None


async def get_lock_service() -> LockService:
    """
    Obtem instancia singleton do LockService.

    Returns:
        LockService conectado
    """
    global _lock_service

    if _lock_service is None:
        client = await get_redis_client()
        _lock_service = LockService(client)

    return _lock_service
