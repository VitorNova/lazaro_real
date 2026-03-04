"""
Redis Service - Gerenciamento de buffer, locks e cache para o agente IA.

Funcionalidades:
- Buffer de mensagens com RPUSH/LRANGE
- Lock distribuído com SET NX EX para evitar race conditions
- TTL automático de 300 segundos
- Controle de pausa/ativa do bot
- Cache genérico (get, set, delete)
"""

import json
import logging
from typing import Any, Dict, List, Optional

import redis.asyncio as redis

logger = logging.getLogger(__name__)

# Constantes
BUFFER_DELAY_SECONDS = 14
DEFAULT_TTL_SECONDS = 300
LOCK_TTL_SECONDS = 60  # Aumentado de 30s para suportar retry do Gemini


class RedisService:
    """Serviço de gerenciamento Redis para o agente IA."""

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        """
        Inicializa o serviço Redis.

        Args:
            redis_url: URL de conexão com o Redis (ex: redis://localhost:6379)
        """
        self._redis_url = redis_url
        self._client: Optional[redis.Redis] = None

    async def connect(self) -> None:
        """Estabelece conexão assíncrona com o Redis."""
        if self._client is None:
            self._client = redis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            # Testa a conexão
            await self._client.ping()
            logger.info("Conexão com Redis estabelecida com sucesso")

    async def disconnect(self) -> None:
        """Encerra a conexão com o Redis."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.info("Conexão com Redis encerrada")

    @property
    def client(self) -> redis.Redis:
        """Retorna o cliente Redis, garantindo que está conectado."""
        if self._client is None:
            raise RuntimeError("Redis não conectado. Chame connect() primeiro.")
        return self._client

    # ========== KEYS ==========

    @staticmethod
    def _buffer_key(agent_id: str, phone: str) -> str:
        """Gera a chave do buffer de mensagens."""
        return f"buffer:msg:{agent_id}:{phone}"

    @staticmethod
    def _lock_key(agent_id: str, phone: str) -> str:
        """Gera a chave do lock de processamento."""
        return f"lock:msg:{agent_id}:{phone}"

    @staticmethod
    def _pause_key(agent_id: str, phone: str) -> str:
        """Gera a chave do controle de pausa."""
        return f"pause:{agent_id}:{phone}"

    # ========== BUFFER DE MENSAGENS ==========

    async def buffer_add_message(
        self,
        agent_id: str,
        phone: str,
        message: str,
        ttl: int = DEFAULT_TTL_SECONDS,
    ) -> int:
        """
        Adiciona uma mensagem ao buffer.

        Args:
            agent_id: ID do agente
            phone: Telefone do lead
            message: Conteúdo da mensagem
            ttl: Tempo de vida em segundos (default: 300)

        Returns:
            Número de mensagens no buffer após a adição
        """
        key = self._buffer_key(agent_id, phone)
        count = await self.client.rpush(key, message)
        await self.client.expire(key, ttl)
        logger.debug(f"Mensagem adicionada ao buffer {key}. Total: {count}")
        return count

    async def buffer_get_messages(
        self,
        agent_id: str,
        phone: str,
    ) -> List[str]:
        """
        Obtém todas as mensagens do buffer.

        Args:
            agent_id: ID do agente
            phone: Telefone do lead

        Returns:
            Lista de mensagens no buffer
        """
        key = self._buffer_key(agent_id, phone)
        messages = await self.client.lrange(key, 0, -1)
        logger.debug(f"Buffer {key} contém {len(messages)} mensagens")
        return messages

    async def buffer_clear(self, agent_id: str, phone: str) -> bool:
        """
        Limpa o buffer de mensagens.

        Args:
            agent_id: ID do agente
            phone: Telefone do lead

        Returns:
            True se o buffer foi limpo, False caso contrário
        """
        key = self._buffer_key(agent_id, phone)
        deleted = await self.client.delete(key)
        logger.debug(f"Buffer {key} limpo: {deleted > 0}")
        return deleted > 0

    async def buffer_get_and_clear(
        self,
        agent_id: str,
        phone: str,
    ) -> List[str]:
        """
        Obtém todas as mensagens e limpa o buffer atomicamente.

        Args:
            agent_id: ID do agente
            phone: Telefone do lead

        Returns:
            Lista de mensagens que estavam no buffer
        """
        key = self._buffer_key(agent_id, phone)

        # Usa pipeline para operação atômica
        async with self.client.pipeline(transaction=True) as pipe:
            pipe.lrange(key, 0, -1)
            pipe.delete(key)
            results = await pipe.execute()

        messages = results[0] if results else []
        logger.debug(f"Buffer {key} consumido com {len(messages)} mensagens")
        return messages

    async def buffer_length(self, agent_id: str, phone: str) -> int:
        """
        Retorna o número de mensagens no buffer.

        Args:
            agent_id: ID do agente
            phone: Telefone do lead

        Returns:
            Número de mensagens no buffer
        """
        key = self._buffer_key(agent_id, phone)
        return await self.client.llen(key)

    async def list_orphan_buffers(self) -> List[Dict[str, Any]]:
        """
        Lista todos os buffers pendentes que NÃO têm lock associado.

        Usado para recovery no startup - buffers sem lock são órfãos
        (a task que os processaria foi perdida no restart).

        Returns:
            Lista de dicts com: agent_id, phone, message_count, ttl_seconds
        """
        orphan_buffers = []

        # Busca todas as chaves de buffer (pattern: buffer:msg:{agent_id}:{phone})
        buffer_keys = []
        async for key in self.client.scan_iter(match="buffer:msg:*", count=100):
            buffer_keys.append(key)

        for key in buffer_keys:
            # Extrai agent_id e phone da chave
            # Formato: buffer:msg:{agent_id}:{phone}
            parts = key.split(":")
            if len(parts) != 4:
                logger.warning(f"[ORPHAN SCAN] Chave com formato inesperado: {key}")
                continue

            agent_id = parts[2]
            phone = parts[3]

            # Verifica se existe lock ativo para este buffer
            lock_key = self._lock_key(agent_id, phone)
            lock_exists = await self.client.exists(lock_key)

            if not lock_exists:
                # Buffer órfão - sem lock, ninguém está processando
                message_count = await self.client.llen(key)
                ttl = await self.client.ttl(key)

                orphan_buffers.append({
                    "agent_id": agent_id,
                    "phone": phone,
                    "message_count": message_count,
                    "ttl_seconds": ttl if ttl > 0 else None,
                    "key": key,
                })

        return orphan_buffers

    # ========== LOCK DISTRIBUÍDO ==========

    async def lock_acquire(
        self,
        agent_id: str,
        phone: str,
        ttl: int = LOCK_TTL_SECONDS,
    ) -> bool:
        """
        Tenta adquirir um lock para processamento.

        Usa SET NX EX para garantir atomicidade e evitar race conditions.

        Args:
            agent_id: ID do agente
            phone: Telefone do lead
            ttl: Tempo de vida do lock em segundos (default: 30)

        Returns:
            True se o lock foi adquirido, False se já existe
        """
        key = self._lock_key(agent_id, phone)
        acquired = await self.client.set(key, "1", nx=True, ex=ttl)
        logger.debug(f"Lock {key} adquirido: {acquired is not None}")
        return acquired is not None

    async def lock_release(self, agent_id: str, phone: str) -> bool:
        """
        Libera o lock de processamento.

        Args:
            agent_id: ID do agente
            phone: Telefone do lead

        Returns:
            True se o lock foi liberado, False caso não existisse
        """
        key = self._lock_key(agent_id, phone)
        deleted = await self.client.delete(key)
        logger.debug(f"Lock {key} liberado: {deleted > 0}")
        return deleted > 0

    async def lock_exists(self, agent_id: str, phone: str) -> bool:
        """
        Verifica se existe um lock ativo.

        Args:
            agent_id: ID do agente
            phone: Telefone do lead

        Returns:
            True se o lock existe, False caso contrário
        """
        key = self._lock_key(agent_id, phone)
        return await self.client.exists(key) > 0

    async def lock_extend(
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
            True se o TTL foi estendido, False se o lock não existe
        """
        key = self._lock_key(agent_id, phone)
        extended = await self.client.expire(key, ttl)
        logger.debug(f"Lock {key} estendido: {extended}")
        return extended

    # ========== CONTROLE DE PAUSA ==========

    async def pause_set(
        self,
        agent_id: str,
        phone: str,
        ttl: Optional[int] = None,
    ) -> None:
        """
        Pausa o bot para um lead específico.

        Args:
            agent_id: ID do agente
            phone: Telefone do lead
            ttl: Tempo de pausa em segundos (None = indefinido)
        """
        key = self._pause_key(agent_id, phone)
        await self.client.set(key, "1")
        if ttl is not None:
            await self.client.expire(key, ttl)
        logger.info(f"Bot pausado para {key} (TTL: {ttl}s)")

    async def pause_clear(self, agent_id: str, phone: str) -> bool:
        """
        Remove a pausa do bot para um lead.

        Args:
            agent_id: ID do agente
            phone: Telefone do lead

        Returns:
            True se a pausa foi removida, False se não estava pausado
        """
        key = self._pause_key(agent_id, phone)
        deleted = await self.client.delete(key)
        logger.info(f"Pausa removida para {key}: {deleted > 0}")
        return deleted > 0

    async def pause_is_paused(self, agent_id: str, phone: str) -> bool:
        """
        Verifica se o bot está pausado para um lead.

        Args:
            agent_id: ID do agente
            phone: Telefone do lead

        Returns:
            True se está pausado, False caso contrário
        """
        key = self._pause_key(agent_id, phone)
        return await self.client.exists(key) > 0

    async def pause_get_ttl(self, agent_id: str, phone: str) -> int:
        """
        Retorna o tempo restante da pausa.

        Args:
            agent_id: ID do agente
            phone: Telefone do lead

        Returns:
            Segundos restantes (-1 se não tem TTL, -2 se não existe)
        """
        key = self._pause_key(agent_id, phone)
        return await self.client.ttl(key)

    # ========== CACHE GENÉRICO ==========

    async def cache_get(self, key: str) -> Optional[Any]:
        """
        Obtém um valor do cache.

        Args:
            key: Chave do cache

        Returns:
            Valor deserializado ou None se não existe
        """
        value = await self.client.get(key)
        if value is None:
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    async def cache_set(
        self,
        key: str,
        value: Any,
        ttl: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        """
        Define um valor no cache.

        Args:
            key: Chave do cache
            value: Valor a ser armazenado (será serializado em JSON)
            ttl: Tempo de vida em segundos (default: 300)
        """
        if isinstance(value, (dict, list)):
            value = json.dumps(value)
        await self.client.set(key, value, ex=ttl)
        logger.debug(f"Cache definido: {key} (TTL: {ttl}s)")

    async def cache_delete(self, key: str) -> bool:
        """
        Remove um valor do cache.

        Args:
            key: Chave do cache

        Returns:
            True se foi removido, False se não existia
        """
        deleted = await self.client.delete(key)
        logger.debug(f"Cache removido: {key} ({deleted > 0})")
        return deleted > 0

    async def cache_exists(self, key: str) -> bool:
        """
        Verifica se uma chave existe no cache.

        Args:
            key: Chave do cache

        Returns:
            True se existe, False caso contrário
        """
        return await self.client.exists(key) > 0

    async def cache_get_ttl(self, key: str) -> int:
        """
        Retorna o TTL de uma chave.

        Args:
            key: Chave do cache

        Returns:
            Segundos restantes (-1 se não tem TTL, -2 se não existe)
        """
        return await self.client.ttl(key)

    # ========== UTILITÁRIOS ==========

    async def health_check(self) -> bool:
        """
        Verifica se a conexão com Redis está saudável.

        Returns:
            True se conectado, False caso contrário
        """
        try:
            await self.client.ping()
            return True
        except Exception as e:
            logger.error(f"Redis health check falhou: {e}")
            return False

    async def get_buffer_delay(self) -> int:
        """
        Retorna o delay configurado para o buffer.

        Returns:
            Delay em segundos (14 segundos por padrão)
        """
        return BUFFER_DELAY_SECONDS


# Instância singleton para uso global
_redis_service: Optional[RedisService] = None


async def get_redis_service(redis_url: str = "redis://localhost:6379") -> RedisService:
    """
    Obtém a instância singleton do RedisService.

    Args:
        redis_url: URL de conexão com o Redis

    Returns:
        Instância do RedisService conectada
    """
    global _redis_service
    if _redis_service is None:
        _redis_service = RedisService(redis_url)
        await _redis_service.connect()
    return _redis_service


async def close_redis_service() -> None:
    """Encerra a conexão do singleton do RedisService."""
    global _redis_service
    if _redis_service is not None:
        await _redis_service.disconnect()
        _redis_service = None
