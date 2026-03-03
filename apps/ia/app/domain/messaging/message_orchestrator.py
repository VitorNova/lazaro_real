"""
Orquestrador de mensagens WhatsApp.

Coordena o fluxo de processamento de mensagens recebidas:
1. Extrai dados da mensagem
2. Identifica agente
3. Gerencia human takeover
4. Gerencia lead (criar/obter)
5. Valida pre-processamento
6. Adiciona ao buffer
7. Agenda processamento

Extraido de: apps/ia/app/webhooks/mensagens.py (Fase 2.15)
"""

import asyncio
from typing import Any, Dict, Optional

import structlog

from app.domain.messaging.handlers.incoming_message_handler import (
    extract_message_data,
    handle_control_command,
)
from app.domain.messaging.models.message import ExtractedMessage, ProcessingContext
from app.services.redis import RedisService
from app.services.supabase import SupabaseService

logger = structlog.get_logger(__name__)


class MessageOrchestrator:
    """
    Orquestrador principal de mensagens WhatsApp.

    Coordena o fluxo de processamento delegando para
    services especializados.
    """

    def __init__(
        self,
        supabase: SupabaseService,
        redis: RedisService,
    ):
        """
        Inicializa o orquestrador.

        Args:
            supabase: Servico Supabase
            redis: Servico Redis
        """
        self.supabase = supabase
        self.redis = redis
        self.logger = logger.bind(component="MessageOrchestrator")

    async def handle_message(
        self,
        webhook_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Processa mensagem recebida do webhook.

        Fluxo:
        1. Extrai dados da mensagem
        2. Valida (nao grupo)
        3. Se from_me -> human takeover
        4. Identifica agente
        5. Gerencia lead
        6. Verifica comandos de controle
        7. Verifica pause
        8. Adiciona ao buffer
        9. Agenda processamento

        Args:
            webhook_data: Dados brutos do webhook

        Returns:
            Dict com status do processamento
        """
        # 1. EXTRAÇÃO
        extracted = extract_message_data(webhook_data)
        if not extracted:
            return {"status": "ignored", "reason": "invalid_message"}

        if extracted.get("is_group"):
            return {"status": "ignored", "reason": "group_message"}

        phone = extracted["phone"]
        remotejid = extracted["remotejid"]
        from_me = extracted.get("from_me", False)
        instance_id = extracted.get("instance_id")

        self.logger.info(
            "message_received",
            phone=phone,
            from_me=from_me,
            instance_id=instance_id,
        )

        # 2. HUMAN TAKEOVER (se from_me)
        if from_me:
            result = await self._handle_human_takeover(extracted)
            if result.get("status") != "continue":
                return result

        # 3. IDENTIFICAR AGENTE
        agent = await self._identify_agent(extracted)
        if not agent:
            return {"status": "error", "reason": "agent_not_found"}

        agent_id = agent["id"]
        table_leads = agent.get("table_leads", "leads")
        table_messages = agent.get("table_messages", "messages")

        # 4. GERENCIAR LEAD
        lead_result = await self._manage_lead(
            agent=agent,
            extracted=extracted,
        )
        if lead_result.get("should_ignore"):
            return lead_result.get("result", {"status": "ignored"})

        lead = lead_result.get("lead", {})

        # 5. COMANDOS DE CONTROLE
        command_result = await handle_control_command(
            phone=phone,
            remotejid=remotejid,
            text=extracted.get("text", ""),
            agent_id=agent_id,
            table_leads=table_leads,
            table_messages=table_messages,
            supabase=self.supabase,
            redis=self.redis,
        )
        if command_result:
            return {"status": "ok", "action": "control_command", "response": command_result}

        # 6. VERIFICAR PAUSE
        is_paused = await self._check_pause(agent_id, phone, table_leads, remotejid)
        if is_paused:
            return {"status": "ignored", "reason": "paused"}

        # 7. ADICIONAR AO BUFFER
        await self._add_to_buffer(
            agent_id=agent_id,
            phone=phone,
            extracted=extracted,
        )

        # 8. CRIAR CONTEXTO
        context = self._build_context(
            agent=agent,
            lead=lead,
            extracted=extracted,
        )

        # 9. AGENDAR PROCESSAMENTO
        await self._schedule_processing(
            agent_id=agent_id,
            phone=phone,
            remotejid=remotejid,
            context=context,
        )

        return {"status": "ok", "action": "buffered"}

    async def _handle_human_takeover(
        self,
        extracted: ExtractedMessage,
    ) -> Dict[str, Any]:
        """
        Processa mensagem from_me (humano respondendo).

        Detecta comandos de controle (/p, /a, /r) ou pausa IA.

        Returns:
            Dict com status (continue, paused, command)
        """
        # Placeholder - implementacao completa em HumanTakeoverService
        # Por enquanto, apenas loga e continua
        self.logger.debug(
            "human_takeover_check",
            phone=extracted.get("phone"),
        )
        return {"status": "continue"}

    async def _identify_agent(
        self,
        extracted: ExtractedMessage,
    ) -> Optional[Dict[str, Any]]:
        """
        Identifica agente pelo instance_id ou token.

        Returns:
            Dict com dados do agente ou None
        """
        instance_id = extracted.get("instance_id")
        token = extracted.get("token")

        # Tentar por instance_id primeiro
        if instance_id:
            agent = self.supabase.get_agent_by_instance_id(instance_id)
            if agent:
                return agent

        # Fallback: por token
        if token:
            agent = self.supabase.get_agent_by_token(token)
            if agent:
                return agent

        self.logger.warning(
            "agent_not_found",
            instance_id=instance_id,
            token=token,
        )
        return None

    async def _manage_lead(
        self,
        agent: Dict[str, Any],
        extracted: ExtractedMessage,
    ) -> Dict[str, Any]:
        """
        Gerencia lead (criar ou obter).

        Returns:
            Dict com lead e should_ignore flag
        """
        table_leads = agent.get("table_leads", "leads")
        remotejid = extracted["remotejid"]
        push_name = extracted.get("push_name", "")

        # Tentar obter lead existente
        lead = self.supabase.get_lead_by_remotejid(table_leads, remotejid)

        if not lead:
            # Criar novo lead
            lead = self.supabase.get_or_create_lead(
                table_leads=table_leads,
                remotejid=remotejid,
                default_data={
                    "nome": push_name or "Lead",
                    "status": "novo",
                },
            )

        return {
            "lead": lead,
            "should_ignore": False,
        }

    async def _check_pause(
        self,
        agent_id: str,
        phone: str,
        table_leads: str,
        remotejid: str,
    ) -> bool:
        """
        Verifica se IA esta pausada para este lead.

        Verifica Redis (rapido) e Supabase (confiavel).

        Returns:
            True se pausado
        """
        # Verificar Redis primeiro (mais rapido)
        if await self.redis.pause_is_paused(agent_id, phone):
            return True

        # Fallback: verificar Supabase
        if self.supabase.is_lead_paused(table_leads, remotejid):
            return True

        return False

    async def _add_to_buffer(
        self,
        agent_id: str,
        phone: str,
        extracted: ExtractedMessage,
    ) -> None:
        """
        Adiciona mensagem ao buffer Redis.
        """
        text = extracted.get("text", "")
        await self.redis.buffer_add_message(agent_id, phone, text)

        self.logger.debug(
            "message_buffered",
            agent_id=agent_id,
            phone=phone,
        )

    def _build_context(
        self,
        agent: Dict[str, Any],
        lead: Dict[str, Any],
        extracted: ExtractedMessage,
    ) -> ProcessingContext:
        """
        Constroi contexto de processamento.

        Returns:
            ProcessingContext com todos os dados necessarios
        """
        return {
            "agent_id": agent["id"],
            "agent_name": agent.get("name", "Agente"),
            "remotejid": extracted["remotejid"],
            "phone": extracted["phone"],
            "table_leads": agent.get("table_leads", "leads"),
            "table_messages": agent.get("table_messages", "messages"),
            "system_prompt": agent.get("system_prompt", ""),
            "uazapi_token": agent.get("token", ""),
            "uazapi_base_url": agent.get("base_url", ""),
            "handoff_triggers": agent.get("handoff_config", {}),
            "audio_message_id": extracted.get("audio_message_id"),
            "image_message_id": extracted.get("image_message_id"),
            "image_url": extracted.get("image_url"),
            "lead_nome": lead.get("nome", ""),
        }

    async def _schedule_processing(
        self,
        agent_id: str,
        phone: str,
        remotejid: str,
        context: ProcessingContext,
    ) -> None:
        """
        Agenda processamento do buffer apos delay.

        Usa delay de 14 segundos para aguardar mensagens
        adicionais antes de processar.
        """
        # Placeholder - implementacao em MessageScheduler
        # Delega para o sistema de agendamento existente
        self.logger.info(
            "processing_scheduled",
            agent_id=agent_id,
            phone=phone,
        )


def create_message_orchestrator(
    supabase: SupabaseService,
    redis: RedisService,
) -> MessageOrchestrator:
    """
    Factory function para criar MessageOrchestrator.

    Args:
        supabase: Servico Supabase
        redis: Servico Redis

    Returns:
        Instancia configurada de MessageOrchestrator
    """
    return MessageOrchestrator(supabase, redis)
