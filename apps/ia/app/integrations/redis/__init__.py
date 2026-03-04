# ==============================================================================
# REDIS INTEGRATION
# Integracao completa com Redis (Buffer + Lock + Pause + Cache)
# ==============================================================================

"""
Redis Integration para Lazaro-v2.

Este modulo fornece:
- RedisClient: Cliente de conexao
- BufferService: Buffer de mensagens
- LockService: Lock distribuido
- PauseService: Controle de pausa
- CacheService: Cache generico
- RedisService: Facade para compatibilidade

Exemplo de uso basico:
    from app.integrations.redis import (
        get_redis_service,
        get_buffer_service,
        get_lock_service,
    )

    # Usando facade (compatibilidade)
    redis = await get_redis_service()
    await redis.buffer_add_message("agent123", "5511999999999", "Ola!")
    messages = await redis.buffer_get_and_clear("agent123", "5511999999999")

    # Usando servicos separados (recomendado)
    buffer = await get_buffer_service()
    lock = await get_lock_service()

    if await lock.acquire("agent123", "5511999999999"):
        try:
            messages = await buffer.get_and_clear("agent123", "5511999999999")
            # Processar...
        finally:
            await lock.release("agent123", "5511999999999")

Arquitetura:
- types.py: Constantes, TypedDicts, helpers
- client.py: RedisClient (conexao)
- buffer.py: BufferService (buffer de mensagens)
- lock.py: LockService (lock distribuido)
- pause.py: PauseService (controle de pausa)
- cache.py: CacheService (cache generico)
"""

from __future__ import annotations

import logging
from typing import List, Optional, Any, Callable, Awaitable, TypeVar

# ==============================================================================
# TYPES
# ==============================================================================

from .types import (
    # Constants
    BUFFER_DELAY_SECONDS,
    DEFAULT_TTL_SECONDS,
    LOCK_TTL_SECONDS,
    BUFFER_TTL_SECONDS,
    # Key Prefixes
    BUFFER_KEY_PREFIX,
    LOCK_KEY_PREFIX,
    PAUSE_KEY_PREFIX,
    CACHE_KEY_PREFIX,
    FAILED_SEND_KEY_PREFIX,
    # TypedDicts
    BufferedMessage,
    OrphanBuffer,
    LockInfo,
    BufferResult,
    HealthStatus,
    # Dataclasses
    RedisConfig,
    # Key Generators
    buffer_key,
    lock_key,
    pause_key,
    failed_send_key,
    parse_buffer_key,
)

# ==============================================================================
# CLIENT
# ==============================================================================

from .client import (
    RedisClient,
    get_redis_client,
    close_redis_client,
    get_redis_client_sync,
)

# ==============================================================================
# SERVICES
# ==============================================================================

from .buffer import BufferService, get_buffer_service
from .lock import LockService, get_lock_service
from .pause import PauseService, get_pause_service
from .cache import CacheService, get_cache_service

logger = logging.getLogger(__name__)
T = TypeVar("T")


# ==============================================================================
# REDIS SERVICE FACADE
# ==============================================================================

class RedisService:
    """
    Facade para todos os servicos Redis.

    Fornece interface unificada compativel com a implementacao original.
    """

    def __init__(
        self,
        client: RedisClient,
        buffer: BufferService,
        lock: LockService,
        pause: PauseService,
        cache: CacheService,
    ):
        """
        Inicializa facade.

        Args:
            client: Cliente Redis
            buffer: Servico de buffer
            lock: Servico de lock
            pause: Servico de pausa
            cache: Servico de cache
        """
        self._client = client
        self._buffer = buffer
        self._lock = lock
        self._pause = pause
        self._cache = cache

    @property
    def client(self):
        """Acesso ao cliente Redis subjacente."""
        return self._client.client

    # ========== CONNECTION ==========

    async def connect(self) -> None:
        """Conecta ao Redis."""
        await self._client.connect()

    async def disconnect(self) -> None:
        """Desconecta do Redis."""
        await self._client.disconnect()

    async def health_check(self) -> bool:
        """Verifica saude da conexao."""
        status = await self._client.health_check()
        return status["connected"]

    # ========== BUFFER ==========

    async def buffer_add_message(
        self,
        agent_id: str,
        phone: str,
        message: str,
        ttl: int = BUFFER_TTL_SECONDS,
    ) -> int:
        """Adiciona mensagem ao buffer."""
        return await self._buffer.add_message(agent_id, phone, message, ttl)

    async def buffer_get_messages(
        self,
        agent_id: str,
        phone: str,
    ) -> List[str]:
        """Obtem mensagens do buffer."""
        return await self._buffer.get_messages(agent_id, phone)

    async def buffer_clear(self, agent_id: str, phone: str) -> bool:
        """Limpa buffer."""
        return await self._buffer.clear(agent_id, phone)

    async def buffer_get_and_clear(
        self,
        agent_id: str,
        phone: str,
    ) -> List[str]:
        """Obtem e limpa buffer atomicamente."""
        return await self._buffer.get_and_clear(agent_id, phone)

    async def buffer_length(self, agent_id: str, phone: str) -> int:
        """Retorna numero de mensagens no buffer."""
        return await self._buffer.length(agent_id, phone)

    async def list_orphan_buffers(self) -> List[OrphanBuffer]:
        """Lista buffers orfaos para recovery."""
        return await self._buffer.list_orphan_buffers()

    # ========== LOCK ==========

    async def lock_acquire(
        self,
        agent_id: str,
        phone: str,
        ttl: int = LOCK_TTL_SECONDS,
    ) -> bool:
        """Adquire lock."""
        return await self._lock.acquire(agent_id, phone, ttl)

    async def lock_release(self, agent_id: str, phone: str) -> bool:
        """Libera lock."""
        return await self._lock.release(agent_id, phone)

    async def lock_exists(self, agent_id: str, phone: str) -> bool:
        """Verifica se lock existe."""
        return await self._lock.exists(agent_id, phone)

    async def lock_extend(
        self,
        agent_id: str,
        phone: str,
        ttl: int = LOCK_TTL_SECONDS,
    ) -> bool:
        """Estende TTL do lock."""
        return await self._lock.extend(agent_id, phone, ttl)

    # ========== PAUSE ==========

    async def pause_set(
        self,
        agent_id: str,
        phone: str,
        ttl: Optional[int] = None,
    ) -> None:
        """Pausa bot para lead."""
        await self._pause.set(agent_id, phone, ttl)

    async def pause_clear(self, agent_id: str, phone: str) -> bool:
        """Remove pausa."""
        return await self._pause.clear(agent_id, phone)

    async def pause_is_paused(self, agent_id: str, phone: str) -> bool:
        """Verifica se pausado."""
        return await self._pause.is_paused(agent_id, phone)

    async def pause_get_ttl(self, agent_id: str, phone: str) -> int:
        """Retorna TTL da pausa."""
        return await self._pause.get_ttl(agent_id, phone)

    # ========== CACHE ==========

    async def cache_get(self, key: str) -> Optional[Any]:
        """Obtem valor do cache."""
        return await self._cache.get(key)

    async def cache_set(
        self,
        key: str,
        value: Any,
        ttl: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        """Define valor no cache."""
        await self._cache.set(key, value, ttl)

    async def cache_delete(self, key: str) -> bool:
        """Remove valor do cache."""
        return await self._cache.delete(key)

    async def cache_exists(self, key: str) -> bool:
        """Verifica se chave existe."""
        return await self._cache.exists(key)

    async def cache_get_ttl(self, key: str) -> int:
        """Retorna TTL da chave."""
        return await self._cache.get_ttl(key)

    # ========== HELPERS ==========

    async def get_buffer_delay(self) -> int:
        """Retorna delay configurado para buffer."""
        return BUFFER_DELAY_SECONDS


# ==============================================================================
# SINGLETON
# ==============================================================================

_redis_service: Optional[RedisService] = None


async def get_redis_service(redis_url: str = "redis://localhost:6379") -> RedisService:
    """
    Obtem instancia singleton do RedisService.

    Args:
        redis_url: URL de conexao com Redis

    Returns:
        RedisService conectado
    """
    global _redis_service

    if _redis_service is None:
        config = RedisConfig(url=redis_url)
        client = await get_redis_client(config)
        buffer = await get_buffer_service()
        lock = await get_lock_service()
        pause = await get_pause_service()
        cache = await get_cache_service()

        _redis_service = RedisService(
            client=client,
            buffer=buffer,
            lock=lock,
            pause=pause,
            cache=cache,
        )

    return _redis_service


async def close_redis_service() -> None:
    """Encerra conexao do singleton."""
    global _redis_service

    if _redis_service is not None:
        await _redis_service.disconnect()
        _redis_service = None

    await close_redis_client()


# ==============================================================================
# EXPORTS
# ==============================================================================

__all__ = [
    # Constants
    "BUFFER_DELAY_SECONDS",
    "DEFAULT_TTL_SECONDS",
    "LOCK_TTL_SECONDS",
    "BUFFER_TTL_SECONDS",
    # Key Prefixes
    "BUFFER_KEY_PREFIX",
    "LOCK_KEY_PREFIX",
    "PAUSE_KEY_PREFIX",
    "CACHE_KEY_PREFIX",
    "FAILED_SEND_KEY_PREFIX",
    # TypedDicts
    "BufferedMessage",
    "OrphanBuffer",
    "LockInfo",
    "BufferResult",
    "HealthStatus",
    # Dataclasses
    "RedisConfig",
    # Key Generators
    "buffer_key",
    "lock_key",
    "pause_key",
    "failed_send_key",
    "parse_buffer_key",
    # Client
    "RedisClient",
    "get_redis_client",
    "close_redis_client",
    "get_redis_client_sync",
    # Services
    "BufferService",
    "get_buffer_service",
    "LockService",
    "get_lock_service",
    "PauseService",
    "get_pause_service",
    "CacheService",
    "get_cache_service",
    # Facade
    "RedisService",
    "get_redis_service",
    "close_redis_service",
]
