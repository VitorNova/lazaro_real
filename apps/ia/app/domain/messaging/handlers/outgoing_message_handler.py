"""
Handler para mensagens de saida (envio ao usuario).

Responsavel por:
- Dividir respostas longas em partes menores
- Gerenciar fila de retry para mensagens que falharam

Extraido de: apps/ia/app/webhooks/mensagens.py (Fase 2.8)
"""

from datetime import datetime
from typing import Dict, List, Optional

import structlog

from app.services.redis import RedisService

logger = structlog.get_logger(__name__)


class OutgoingMessageHandler:
    """
    Handler para processamento de mensagens de saida.

    Responsabilidades:
    - Dividir mensagens longas em partes adequadas para WhatsApp
    - Gerenciar fila de retry para mensagens que falharam no envio
    """

    # Tamanho maximo padrao por mensagem WhatsApp
    DEFAULT_MAX_LENGTH = 4000

    # TTL padrao para mensagens na fila de retry (24 horas)
    RETRY_TTL_SECONDS = 86400

    def __init__(self, redis: Optional[RedisService] = None):
        """
        Inicializa o handler de mensagens de saida.

        Args:
            redis: Servico Redis para fila de retry (opcional)
        """
        self.redis = redis
        self.logger = logger.bind(component="OutgoingMessageHandler")

    def split_response(
        self,
        text: str,
        max_length: int = DEFAULT_MAX_LENGTH,
    ) -> List[str]:
        """
        Divide resposta longa em partes menores.

        Tenta dividir em quebras de paragrafo ou sentencas para
        manter a legibilidade.

        Args:
            text: Texto para dividir
            max_length: Tamanho maximo de cada parte

        Returns:
            Lista de partes do texto
        """
        if len(text) <= max_length:
            return [text]

        parts = []
        remaining = text

        while remaining:
            if len(remaining) <= max_length:
                parts.append(remaining)
                break

            # Tentar encontrar ponto de quebra
            chunk = remaining[:max_length]

            # Procurar por quebra de paragrafo
            break_point = chunk.rfind("\n\n")
            if break_point == -1:
                # Procurar por quebra de linha
                break_point = chunk.rfind("\n")
            if break_point == -1:
                # Procurar por ponto final
                break_point = chunk.rfind(". ")
            if break_point == -1:
                # Procurar por espaco
                break_point = chunk.rfind(" ")
            if break_point == -1:
                # Forcar quebra no limite
                break_point = max_length

            parts.append(remaining[:break_point + 1].strip())
            remaining = remaining[break_point + 1:].strip()

        self.logger.debug(
            "response_split",
            original_length=len(text),
            parts_count=len(parts),
        )

        return parts

    async def queue_failed_send(
        self,
        agent_id: str,
        phone: str,
        response_text: str,
        error: Optional[str] = None,
    ) -> None:
        """
        Salva mensagem que falhou ao enviar na fila de retry do Redis.

        A mensagem sera reprocessada no startup ou via task periodica.
        Se ja existir uma mensagem pendente para o mesmo lead, as mensagens
        sao concatenadas para nao perder contexto.

        Args:
            agent_id: ID do agente
            phone: Telefone do destinatario
            response_text: Texto da resposta que nao foi enviada
            error: Erro que ocorreu no envio
        """
        if self.redis is None:
            self.logger.error(
                "redis_not_configured",
                message="Cannot queue failed send without Redis service",
            )
            return

        key = f"failed_send:{agent_id}:{phone}"
        now = datetime.utcnow().isoformat()

        # Verificar se ja existe uma mensagem pendente para este lead
        existing = await self.redis.cache_get(key)

        if existing and isinstance(existing, dict):
            # Ja existe mensagem pendente - concatenar (nao perder contexto)
            attempts = existing.get("attempts", 0) + 1
            response_text = f"{existing.get('text', '')}\n\n---\n\n{response_text}"
            self.logger.info(
                "failed_send_concatenated",
                phone=phone,
                agent_id=agent_id,
                attempts=attempts,
            )
        else:
            attempts = 1

        payload = {
            "text": response_text,
            "timestamp": now,
            "attempts": attempts,
            "last_error": error,
            "agent_id": agent_id,
        }

        # TTL de 24 horas - se nao conseguir reenviar em 24h, desiste
        await self.redis.cache_set(key, payload, ttl=self.RETRY_TTL_SECONDS)

        self.logger.info(
            "failed_send_queued",
            phone=phone,
            agent_id=agent_id,
            attempts=attempts,
            error=error,
        )

    async def get_failed_send(
        self,
        agent_id: str,
        phone: str,
    ) -> Optional[Dict]:
        """
        Recupera mensagem que falhou no envio da fila de retry.

        Args:
            agent_id: ID do agente
            phone: Telefone do destinatario

        Returns:
            Payload da mensagem ou None se nao existir
        """
        if self.redis is None:
            return None

        key = f"failed_send:{agent_id}:{phone}"
        return await self.redis.cache_get(key)

    async def clear_failed_send(
        self,
        agent_id: str,
        phone: str,
    ) -> bool:
        """
        Remove mensagem da fila de retry apos envio bem-sucedido.

        Args:
            agent_id: ID do agente
            phone: Telefone do destinatario

        Returns:
            True se removido, False caso contrario
        """
        if self.redis is None:
            return False

        key = f"failed_send:{agent_id}:{phone}"
        await self.redis.cache_delete(key)

        self.logger.debug(
            "failed_send_cleared",
            phone=phone,
            agent_id=agent_id,
        )

        return True


# Funcoes standalone para compatibilidade com codigo legado


def split_response(
    text: str,
    max_length: int = OutgoingMessageHandler.DEFAULT_MAX_LENGTH,
) -> List[str]:
    """
    Wrapper standalone para dividir resposta em partes.

    Mantido para compatibilidade com codigo existente.
    Prefira usar OutgoingMessageHandler diretamente.
    """
    handler = OutgoingMessageHandler()
    return handler.split_response(text, max_length)


async def queue_failed_send(
    redis: RedisService,
    agent_id: str,
    phone: str,
    response_text: str,
    error: Optional[str] = None,
) -> None:
    """
    Wrapper standalone para enfileirar mensagem que falhou.

    Mantido para compatibilidade com codigo existente.
    Prefira usar OutgoingMessageHandler diretamente.
    """
    handler = OutgoingMessageHandler(redis)
    await handler.queue_failed_send(agent_id, phone, response_text, error)
