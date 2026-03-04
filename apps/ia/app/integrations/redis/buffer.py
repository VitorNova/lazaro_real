# ==============================================================================
# REDIS BUFFER
# Servico de buffer de mensagens
# ==============================================================================

"""
Buffer de mensagens com Redis.

Funcionalidades:
- Adicionar mensagens ao buffer (RPUSH)
- Obter mensagens do buffer (LRANGE)
- Limpar buffer (DEL)
- Obter e limpar atomicamente (pipeline)
- Listar buffers orfaos (para recovery)

Uso:
    from app.integrations.redis import get_buffer_service

    buffer = await get_buffer_service()

    # Adicionar mensagem
    count = await buffer.add_message("agent123", "5511999999999", "Ola!")

    # Obter mensagens
    messages = await buffer.get_messages("agent123", "5511999999999")

    # Obter e limpar atomicamente
    messages = await buffer.get_and_clear("agent123", "5511999999999")
"""

from __future__ import annotations

import logging
from typing import List, Optional, Any

from .types import (
    BUFFER_TTL_SECONDS,
    OrphanBuffer,
    buffer_key,
    lock_key,
    parse_buffer_key,
)
from .client import RedisClient, get_redis_client

logger = logging.getLogger(__name__)


# ==============================================================================
# BUFFER SERVICE
# ==============================================================================

class BufferService:
    """
    Servico de buffer de mensagens usando Redis.

    Armazena mensagens temporariamente antes do processamento.
    """

    def __init__(self, client: RedisClient):
        """
        Inicializa servico de buffer.

        Args:
            client: Cliente Redis conectado
        """
        self._client = client

    async def add_message(
        self,
        agent_id: str,
        phone: str,
        message: str,
        ttl: int = BUFFER_TTL_SECONDS,
    ) -> int:
        """
        Adiciona uma mensagem ao buffer.

        Args:
            agent_id: ID do agente
            phone: Telefone do lead
            message: Conteudo da mensagem
            ttl: Tempo de vida em segundos

        Returns:
            Numero de mensagens no buffer apos adicao
        """
        key = buffer_key(agent_id, phone)

        count = await self._client.rpush(key, message)
        await self._client.expire(key, ttl)

        logger.debug(f"Buffer {key}: +1 mensagem (total: {count})")
        return count

    async def get_messages(
        self,
        agent_id: str,
        phone: str,
    ) -> List[str]:
        """
        Obtem todas as mensagens do buffer.

        Args:
            agent_id: ID do agente
            phone: Telefone do lead

        Returns:
            Lista de mensagens
        """
        key = buffer_key(agent_id, phone)
        messages = await self._client.lrange(key, 0, -1)
        logger.debug(f"Buffer {key}: {len(messages)} mensagens")
        return messages

    async def clear(self, agent_id: str, phone: str) -> bool:
        """
        Limpa o buffer.

        Args:
            agent_id: ID do agente
            phone: Telefone do lead

        Returns:
            True se buffer foi limpo
        """
        key = buffer_key(agent_id, phone)
        deleted = await self._client.delete(key)
        logger.debug(f"Buffer {key} limpo: {deleted > 0}")
        return deleted > 0

    async def get_and_clear(
        self,
        agent_id: str,
        phone: str,
    ) -> List[str]:
        """
        Obtem todas as mensagens e limpa o buffer atomicamente.

        Usa pipeline para garantir atomicidade.

        Args:
            agent_id: ID do agente
            phone: Telefone do lead

        Returns:
            Lista de mensagens que estavam no buffer
        """
        key = buffer_key(agent_id, phone)

        # Pipeline para operacao atomica
        async with self._client.pipeline(transaction=True) as pipe:
            pipe.lrange(key, 0, -1)
            pipe.delete(key)
            results = await pipe.execute()

        messages = results[0] if results else []
        logger.debug(f"Buffer {key} consumido: {len(messages)} mensagens")
        return messages

    async def length(self, agent_id: str, phone: str) -> int:
        """
        Retorna numero de mensagens no buffer.

        Args:
            agent_id: ID do agente
            phone: Telefone do lead

        Returns:
            Numero de mensagens
        """
        key = buffer_key(agent_id, phone)
        return await self._client.llen(key)

    async def exists(self, agent_id: str, phone: str) -> bool:
        """
        Verifica se buffer existe.

        Args:
            agent_id: ID do agente
            phone: Telefone do lead

        Returns:
            True se buffer existe
        """
        key = buffer_key(agent_id, phone)
        return await self._client.exists(key) > 0

    async def get_ttl(self, agent_id: str, phone: str) -> int:
        """
        Retorna TTL do buffer.

        Args:
            agent_id: ID do agente
            phone: Telefone do lead

        Returns:
            Segundos restantes (-1 se sem TTL, -2 se nao existe)
        """
        key = buffer_key(agent_id, phone)
        return await self._client.ttl(key)

    async def list_orphan_buffers(self) -> List[OrphanBuffer]:
        """
        Lista todos os buffers pendentes SEM lock associado.

        Buffers sem lock sao orfaos - a task que os processaria
        foi perdida (ex: restart do servico).

        Usado para recovery no startup.

        Returns:
            Lista de buffers orfaos
        """
        orphan_buffers: List[OrphanBuffer] = []

        # Busca todas as chaves de buffer
        buffer_keys: List[str] = []
        async for key in self._client.scan_iter(match="buffer:msg:*", count=100):
            buffer_keys.append(key)

        for key in buffer_keys:
            # Extrai agent_id e phone da chave
            agent_id, phone = parse_buffer_key(key)
            if not agent_id or not phone:
                logger.warning(f"[ORPHAN SCAN] Chave com formato inesperado: {key}")
                continue

            # Verifica se existe lock ativo para este buffer
            lk = lock_key(agent_id, phone)
            lock_exists = await self._client.exists(lk) > 0

            if not lock_exists:
                # Buffer orfao - sem lock, ninguem esta processando
                message_count = await self._client.llen(key)
                ttl = await self._client.ttl(key)

                orphan_buffers.append({
                    "agent_id": agent_id,
                    "phone": phone,
                    "message_count": message_count,
                    "ttl_seconds": ttl if ttl > 0 else None,
                    "key": key,
                })

        if orphan_buffers:
            logger.info(f"[ORPHAN SCAN] Encontrados {len(orphan_buffers)} buffers orfaos")

        return orphan_buffers


# ==============================================================================
# SINGLETON
# ==============================================================================

_buffer_service: Optional[BufferService] = None


async def get_buffer_service() -> BufferService:
    """
    Obtem instancia singleton do BufferService.

    Returns:
        BufferService conectado
    """
    global _buffer_service

    if _buffer_service is None:
        client = await get_redis_client()
        _buffer_service = BufferService(client)

    return _buffer_service
