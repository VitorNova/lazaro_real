# ==============================================================================
# REDIS CACHE
# Servico de cache generico
# ==============================================================================

"""
Cache generico com Redis.

Funcionalidades:
- GET/SET com serializacao JSON automatica
- TTL configuravel
- DELETE
- EXISTS
- GET TTL

Uso:
    from app.integrations.redis import get_cache_service

    cache = await get_cache_service()

    # Armazenar valor
    await cache.set("minha:chave", {"foo": "bar"}, ttl=3600)

    # Obter valor
    valor = await cache.get("minha:chave")

    # Remover
    await cache.delete("minha:chave")
"""

from __future__ import annotations

import json
import logging
from typing import Optional, Any

from .types import DEFAULT_TTL_SECONDS
from .client import RedisClient, get_redis_client

logger = logging.getLogger(__name__)


# ==============================================================================
# CACHE SERVICE
# ==============================================================================

class CacheService:
    """
    Servico de cache generico usando Redis.

    Suporta serializacao JSON automatica para dicts e listas.
    """

    def __init__(self, client: RedisClient):
        """
        Inicializa servico de cache.

        Args:
            client: Cliente Redis conectado
        """
        self._client = client

    async def get(self, key: str) -> Optional[Any]:
        """
        Obtem valor do cache.

        Args:
            key: Chave do cache

        Returns:
            Valor deserializado ou None se nao existe
        """
        value = await self._client.get(key)
        if value is None:
            return None

        try:
            return json.loads(value)
        except json.JSONDecodeError:
            # Retorna valor bruto se nao for JSON
            return value

    async def set(
        self,
        key: str,
        value: Any,
        ttl: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        """
        Define valor no cache.

        Args:
            key: Chave do cache
            value: Valor a armazenar (sera serializado em JSON se dict/list)
            ttl: Tempo de vida em segundos
        """
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)

        await self._client.set(key, value, ex=ttl)
        logger.debug(f"Cache definido: {key} (TTL: {ttl}s)")

    async def delete(self, key: str) -> bool:
        """
        Remove valor do cache.

        Args:
            key: Chave do cache

        Returns:
            True se foi removido, False se nao existia
        """
        deleted = await self._client.delete(key)
        logger.debug(f"Cache removido: {key} ({deleted > 0})")
        return deleted > 0

    async def exists(self, key: str) -> bool:
        """
        Verifica se chave existe.

        Args:
            key: Chave do cache

        Returns:
            True se existe
        """
        return await self._client.exists(key) > 0

    async def get_ttl(self, key: str) -> int:
        """
        Retorna TTL de uma chave.

        Args:
            key: Chave do cache

        Returns:
            Segundos restantes (-1 se sem TTL, -2 se nao existe)
        """
        return await self._client.ttl(key)

    async def get_or_set(
        self,
        key: str,
        factory: Any,
        ttl: int = DEFAULT_TTL_SECONDS,
    ) -> Any:
        """
        Obtem valor ou cria se nao existir.

        Args:
            key: Chave do cache
            factory: Valor ou funcao async que retorna valor
            ttl: Tempo de vida em segundos

        Returns:
            Valor do cache ou valor criado
        """
        value = await self.get(key)
        if value is not None:
            return value

        # Criar valor
        if callable(factory):
            value = await factory() if hasattr(factory, "__await__") else factory()
        else:
            value = factory

        await self.set(key, value, ttl)
        return value

    async def increment(
        self,
        key: str,
        amount: int = 1,
        ttl: Optional[int] = None,
    ) -> int:
        """
        Incrementa contador.

        Args:
            key: Chave do contador
            amount: Valor a incrementar (pode ser negativo)
            ttl: TTL em segundos (opcional)

        Returns:
            Novo valor do contador
        """
        pipe = self._client.pipeline(transaction=True)
        pipe.incrby(key, amount)
        if ttl is not None:
            pipe.expire(key, ttl)
        results = await pipe.execute()
        return results[0]

    async def delete_pattern(self, pattern: str) -> int:
        """
        Remove todas as chaves que correspondem ao pattern.

        CUIDADO: Pode ser lento em bancos grandes.

        Args:
            pattern: Pattern glob (ex: "cache:user:*")

        Returns:
            Numero de chaves removidas
        """
        keys = []
        async for key in self._client.scan_iter(match=pattern, count=100):
            keys.append(key)

        if not keys:
            return 0

        deleted = await self._client.delete(*keys)
        logger.info(f"Cache pattern removido: {pattern} ({deleted} chaves)")
        return deleted


# ==============================================================================
# SINGLETON
# ==============================================================================

_cache_service: Optional[CacheService] = None


async def get_cache_service() -> CacheService:
    """
    Obtem instancia singleton do CacheService.

    Returns:
        CacheService conectado
    """
    global _cache_service

    if _cache_service is None:
        client = await get_redis_client()
        _cache_service = CacheService(client)

    return _cache_service
