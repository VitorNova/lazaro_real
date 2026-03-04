# ==============================================================================
# AGENTS REPOSITORY
# Repositorio para tabela agents
# Baseado na implementacao TypeScript (apps/api/src/services/supabase/repositories/agents.repository.ts)
# ==============================================================================

from __future__ import annotations

import structlog
from typing import Optional, Any

from .base import BaseRepository
from ..types import Agent, AgentCreate, AgentUpdate

logger = structlog.get_logger(__name__)


class AgentsRepository(BaseRepository[Agent]):
    """Repositorio para tabela agents."""

    table_name = "agents"

    # ==========================================================================
    # FIND METHODS
    # ==========================================================================

    async def find_by_instance_id(self, instance_id: str) -> Optional[Agent]:
        """
        Busca agente por uazapi_instance_id.

        Args:
            instance_id: ID da instancia UAZAPI

        Returns:
            Agente ou None
        """
        try:
            response = (
                self.table.select("*")
                .eq("uazapi_instance_id", instance_id)
                .eq("active", True)
                .single()
                .execute()
            )
            return response.data
        except Exception as e:
            if self._is_not_found(e):
                return None
            logger.error(
                "agents_find_by_instance_id_error",
                instance_id=instance_id,
                error=str(e),
            )
            raise

    async def find_by_uazapi_token(self, token: str) -> Optional[Agent]:
        """
        Busca agente por uazapi_token.

        Args:
            token: Token UAZAPI

        Returns:
            Agente ou None
        """
        try:
            response = (
                self.table.select("*")
                .eq("uazapi_token", token)
                .eq("active", True)
                .single()
                .execute()
            )
            return response.data
        except Exception as e:
            if self._is_not_found(e):
                return None
            logger.error(
                "agents_find_by_uazapi_token_error",
                error=str(e),
            )
            raise

    async def find_by_evolution_instance(self, instance_id: str) -> Optional[Agent]:
        """
        Busca agente por evolution_instance_id.

        Args:
            instance_id: ID da instancia Evolution

        Returns:
            Agente ou None
        """
        try:
            response = (
                self.table.select("*")
                .eq("evolution_instance_id", instance_id)
                .eq("active", True)
                .single()
                .execute()
            )
            return response.data
        except Exception as e:
            if self._is_not_found(e):
                return None
            logger.error(
                "agents_find_by_evolution_instance_error",
                instance_id=instance_id,
                error=str(e),
            )
            raise

    async def find_active_agents(self) -> list[Agent]:
        """
        Lista todos os agentes ativos.

        Returns:
            Lista de agentes ativos
        """
        try:
            response = (
                self.table.select("*")
                .eq("active", True)
                .order("created_at", desc=True)
                .execute()
            )
            return response.data or []
        except Exception as e:
            logger.error(
                "agents_find_active_error",
                error=str(e),
            )
            raise

    async def find_agents_for_instance(self, instance_id: str) -> list[Agent]:
        """
        Lista agentes para uma instancia (pode ter multiplos agentes por instancia).

        Args:
            instance_id: ID da instancia

        Returns:
            Lista de agentes
        """
        try:
            response = (
                self.table.select("*")
                .eq("uazapi_instance_id", instance_id)
                .eq("active", True)
                .order("created_at", desc=True)
                .execute()
            )
            return response.data or []
        except Exception as e:
            logger.error(
                "agents_find_for_instance_error",
                instance_id=instance_id,
                error=str(e),
            )
            raise

    async def find_agents_with_follow_up(self) -> list[Agent]:
        """
        Lista agentes com follow-up habilitado.

        Returns:
            Lista de agentes com follow-up
        """
        try:
            response = (
                self.table.select("*")
                .eq("active", True)
                .eq("follow_up_enabled", True)
                .execute()
            )
            return response.data or []
        except Exception as e:
            logger.error(
                "agents_find_with_follow_up_error",
                error=str(e),
            )
            raise

    async def find_agents_with_asaas(self) -> list[Agent]:
        """
        Lista agentes com integracao Asaas configurada.

        Returns:
            Lista de agentes com Asaas
        """
        try:
            response = (
                self.table.select("*")
                .eq("active", True)
                .neq("asaas_api_key", None)
                .execute()
            )
            return response.data or []
        except Exception as e:
            logger.error(
                "agents_find_with_asaas_error",
                error=str(e),
            )
            raise

    # ==========================================================================
    # CONFIG & PROMPT
    # ==========================================================================

    async def get_config(self, agent_id: str) -> Optional[dict[str, Any]]:
        """
        Retorna configuracao do agente como dict flat.

        Args:
            agent_id: ID do agente

        Returns:
            Dict com configuracoes ou None
        """
        agent = await self.find_by_id(agent_id)
        if not agent:
            return None

        # Extrair campos de configuracao
        return {
            # Tables
            "table_leads": agent.get("table_leads"),
            "table_messages": agent.get("table_messages"),
            # WhatsApp
            "whatsapp_provider": agent.get("whatsapp_provider", "uazapi"),
            "uazapi_instance_id": agent.get("uazapi_instance_id"),
            "uazapi_token": agent.get("uazapi_token"),
            "uazapi_base_url": agent.get("uazapi_base_url"),
            "evolution_instance_id": agent.get("evolution_instance_id"),
            "evolution_token": agent.get("evolution_token"),
            "evolution_base_url": agent.get("evolution_base_url"),
            # AI
            "ai_provider": agent.get("ai_provider", "gemini"),
            "gemini_api_key": agent.get("gemini_api_key"),
            "gemini_model": agent.get("gemini_model", "gemini-2.0-flash"),
            # Business
            "business_hours": agent.get("business_hours"),
            "timezone": agent.get("timezone", "America/Sao_Paulo"),
            # Follow-up
            "follow_up_enabled": agent.get("follow_up_enabled", False),
            "follow_up_config": agent.get("follow_up_config"),
            # Google
            "google_calendar_id": agent.get("google_calendar_id"),
            "google_credentials": agent.get("google_credentials"),
            "google_accounts": agent.get("google_accounts"),
            # Asaas
            "asaas_api_key": agent.get("asaas_api_key"),
            "asaas_environment": agent.get("asaas_environment", "production"),
        }

    async def get_prompt(self, agent_id: str) -> Optional[str]:
        """
        Retorna system_prompt do agente.

        Args:
            agent_id: ID do agente

        Returns:
            System prompt ou None
        """
        try:
            response = (
                self.table.select("system_prompt")
                .eq("id", agent_id)
                .single()
                .execute()
            )
            if response.data:
                return response.data.get("system_prompt")
            return None
        except Exception as e:
            if self._is_not_found(e):
                return None
            logger.error(
                "agents_get_prompt_error",
                agent_id=agent_id,
                error=str(e),
            )
            raise

    async def get_tables(self, agent_id: str) -> Optional[tuple[str, str]]:
        """
        Retorna nomes das tabelas dinamicas do agente.

        Args:
            agent_id: ID do agente

        Returns:
            Tupla (table_leads, table_messages) ou None
        """
        try:
            response = (
                self.table.select("table_leads,table_messages")
                .eq("id", agent_id)
                .single()
                .execute()
            )
            if response.data:
                return (
                    response.data.get("table_leads"),
                    response.data.get("table_messages"),
                )
            return None
        except Exception as e:
            if self._is_not_found(e):
                return None
            logger.error(
                "agents_get_tables_error",
                agent_id=agent_id,
                error=str(e),
            )
            raise

    # ==========================================================================
    # UPDATE METHODS
    # ==========================================================================

    async def update_follow_up_config(
        self, agent_id: str, config: dict[str, Any]
    ) -> Optional[Agent]:
        """
        Atualiza configuracao de follow-up do agente.

        Args:
            agent_id: ID do agente
            config: Nova configuracao

        Returns:
            Agente atualizado ou None
        """
        return await self.update(
            agent_id,
            {
                "follow_up_config": config,
                "updated_at": "now()",
            },
        )

    async def update_google_credentials(
        self, agent_id: str, credentials: dict[str, Any]
    ) -> Optional[Agent]:
        """
        Atualiza credenciais Google do agente.

        Args:
            agent_id: ID do agente
            credentials: Novas credenciais

        Returns:
            Agente atualizado ou None
        """
        return await self.update(
            agent_id,
            {
                "google_credentials": credentials,
                "updated_at": "now()",
            },
        )

    async def deactivate(self, agent_id: str) -> Optional[Agent]:
        """
        Desativa um agente.

        Args:
            agent_id: ID do agente

        Returns:
            Agente atualizado ou None
        """
        return await self.update(
            agent_id,
            {
                "active": False,
                "updated_at": "now()",
            },
        )


# ==============================================================================
# SINGLETON INSTANCE
# ==============================================================================

agents_repository = AgentsRepository()
