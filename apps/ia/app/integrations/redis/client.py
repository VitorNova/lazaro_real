# ==============================================================================
# REDIS CLIENT
# Cliente de conexao com Redis
# ==============================================================================

"""
Cliente Redis com gerenciamento de conexao.

Uso:
    from app.integrations.redis import get_redis_client

    client = await get_redis_client()
    await client.connect()

    # Usar cliente...
    await client.ping()

    await client.disconnect()
"""

from __future__ import annotations

import time
import logging
from typing import Optional, Any

import redis.asyncio as redis

from .types import RedisConfig, HealthStatus

logger = logging.getLogger(__name__)


# ==============================================================================
# REDIS CLIENT
# ==============================================================================

class RedisClient:
    """
    Cliente Redis com gerenciamento de conexao.

    Fornece conexao assincrona com Redis e metodos utilitarios.
    """

    def __init__(self, config: Optional[RedisConfig] = None):
        """
        Inicializa cliente Redis.

        Args:
            config: Configuracao de conexao (usa padrao se nao informado)
        """
        self._config = config or RedisConfig.from_env()
        self._client: Optional[redis.Redis] = None
        self._connected = False

    @property
    def connected(self) -> bool:
        """Retorna True se conectado."""
        return self._connected and self._client is not None

    @property
    def client(self) -> redis.Redis:
        """
        Retorna cliente Redis.

        Raises:
            RuntimeError: Se nao estiver conectado
        """
        if self._client is None:
            raise RuntimeError("Redis nao conectado. Chame connect() primeiro.")
        return self._client

    async def connect(self) -> None:
        """Estabelece conexao com Redis."""
        if self._connected:
            return

        try:
            self._client = redis.from_url(
                self._config.url,
                encoding=self._config.encoding,
                decode_responses=self._config.decode_responses,
                socket_timeout=self._config.socket_timeout,
                socket_connect_timeout=self._config.socket_connect_timeout,
                retry_on_timeout=self._config.retry_on_timeout,
            )
            # Testa conexao
            await self._client.ping()
            self._connected = True
            logger.info(f"Redis conectado: {self._config.url}")
        except Exception as e:
            logger.error(f"Falha ao conectar Redis: {e}")
            self._connected = False
            raise

    async def disconnect(self) -> None:
        """Encerra conexao com Redis."""
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception as e:
                logger.warning(f"Erro ao desconectar Redis: {e}")
            finally:
                self._client = None
                self._connected = False
                logger.info("Redis desconectado")

    async def ping(self) -> bool:
        """
        Testa conexao com Redis.

        Returns:
            True se conectado
        """
        try:
            if self._client is None:
                return False
            await self._client.ping()
            return True
        except Exception:
            return False

    async def health_check(self) -> HealthStatus:
        """
        Verifica saude da conexao.

        Returns:
            HealthStatus com informacoes de saude
        """
        start = time.time()
        try:
            if self._client is None:
                return {
                    "connected": False,
                    "latency_ms": None,
                    "error": "Client not initialized",
                }

            await self._client.ping()
            latency_ms = (time.time() - start) * 1000

            return {
                "connected": True,
                "latency_ms": round(latency_ms, 2),
                "error": None,
            }
        except Exception as e:
            return {
                "connected": False,
                "latency_ms": None,
                "error": str(e),
            }

    # ========== LOW-LEVEL OPERATIONS ==========

    async def get(self, key: str) -> Optional[str]:
        """GET key."""
        return await self.client.get(key)

    async def set(
        self,
        key: str,
        value: Any,
        ex: Optional[int] = None,
        nx: bool = False,
    ) -> Optional[bool]:
        """SET key value [EX seconds] [NX]."""
        return await self.client.set(key, value, ex=ex, nx=nx)

    async def delete(self, *keys: str) -> int:
        """DEL key [key ...]."""
        return await self.client.delete(*keys)

    async def exists(self, *keys: str) -> int:
        """EXISTS key [key ...]."""
        return await self.client.exists(*keys)

    async def expire(self, key: str, seconds: int) -> bool:
        """EXPIRE key seconds."""
        return await self.client.expire(key, seconds)

    async def ttl(self, key: str) -> int:
        """TTL key."""
        return await self.client.ttl(key)

    async def rpush(self, key: str, *values: Any) -> int:
        """RPUSH key value [value ...]."""
        return await self.client.rpush(key, *values)

    async def lrange(self, key: str, start: int, stop: int) -> list:
        """LRANGE key start stop."""
        return await self.client.lrange(key, start, stop)

    async def llen(self, key: str) -> int:
        """LLEN key."""
        return await self.client.llen(key)

    async def scan_iter(self, match: str, count: int = 100):
        """SCAN com pattern matching."""
        async for key in self.client.scan_iter(match=match, count=count):
            yield key

    def pipeline(self, transaction: bool = True):
        """Cria pipeline para operacoes atomicas."""
        return self.client.pipeline(transaction=transaction)


# ==============================================================================
# SINGLETON
# ==============================================================================

_redis_client: Optional[RedisClient] = None


async def get_redis_client(
    config: Optional[RedisConfig] = None,
    auto_connect: bool = True,
) -> RedisClient:
    """
    Obtem instancia singleton do RedisClient.

    Args:
        config: Configuracao (usa default se nao informado)
        auto_connect: Se True, conecta automaticamente

    Returns:
        RedisClient conectado
    """
    global _redis_client

    if _redis_client is None:
        _redis_client = RedisClient(config)

    if auto_connect and not _redis_client.connected:
        await _redis_client.connect()

    return _redis_client


async def close_redis_client() -> None:
    """Fecha conexao do singleton."""
    global _redis_client

    if _redis_client is not None:
        await _redis_client.disconnect()
        _redis_client = None


def get_redis_client_sync() -> Optional[RedisClient]:
    """
    Obtem cliente Redis de forma sincrona (sem conectar).

    Util para verificar se ja existe conexao.
    """
    return _redis_client
