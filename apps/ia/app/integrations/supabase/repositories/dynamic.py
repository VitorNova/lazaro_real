# ==============================================================================
# DYNAMIC REPOSITORY
# Repositorio para tabelas dinamicas (LeadboxCRM_*, leadbox_messages_*, Controle_*)
# Baseado na implementacao TypeScript (apps/api/src/services/supabase/repositories/dynamic.repository.ts)
# ==============================================================================

from __future__ import annotations

import structlog
from datetime import datetime
from typing import Optional, Any

from supabase import Client

from ..client import get_supabase_admin
from ..types import (
    DynamicLead,
    DynamicLeadCreate,
    DynamicLeadUpdate,
    LeadMessage,
    ConversationHistory,
    GeminiMessage,
    Controle,
)

logger = structlog.get_logger(__name__)


class DynamicRepository:
    """
    Repositorio para tabelas dinamicas multi-tenant.

    Gerencia tabelas:
    - LeadboxCRM_{agentShortId}: Leads por agente
    - leadbox_messages_{agentShortId}: Mensagens por agente
    - Controle_{agentShortId}: Controle por agente
    """

    def __init__(self, client: Optional[Client] = None):
        """
        Inicializa o repositorio.

        Args:
            client: Cliente Supabase opcional (default: admin client)
        """
        self._client = client or get_supabase_admin()

    @property
    def client(self) -> Client:
        """Retorna o cliente Supabase."""
        return self._client

    def _table(self, name: str):
        """Retorna uma tabela pelo nome."""
        return self._client.table(name)

    # ==========================================================================
    # LEADS (LeadboxCRM_*)
    # ==========================================================================

    async def find_lead_by_remotejid(
        self, table_name: str, remotejid: str
    ) -> Optional[DynamicLead]:
        """
        Busca lead por remotejid.

        Args:
            table_name: Nome da tabela (LeadboxCRM_xxx)
            remotejid: ID remoto WhatsApp

        Returns:
            Lead ou None
        """
        try:
            response = (
                self._table(table_name)
                .select("*")
                .eq("remotejid", remotejid)
                .single()
                .execute()
            )
            return response.data
        except Exception as e:
            if "PGRST116" in str(e):
                return None
            logger.error(
                "dynamic_find_lead_by_remotejid_error",
                table=table_name,
                remotejid=remotejid,
                error=str(e),
            )
            raise

    async def find_lead_by_phone(
        self, table_name: str, telefone: str
    ) -> Optional[DynamicLead]:
        """
        Busca lead por telefone.

        Args:
            table_name: Nome da tabela (LeadboxCRM_xxx)
            telefone: Numero de telefone

        Returns:
            Lead ou None
        """
        try:
            response = (
                self._table(table_name)
                .select("*")
                .eq("telefone", telefone)
                .single()
                .execute()
            )
            return response.data
        except Exception as e:
            if "PGRST116" in str(e):
                return None
            logger.error(
                "dynamic_find_lead_by_phone_error",
                table=table_name,
                error=str(e),
            )
            raise

    async def find_lead_by_id(
        self, table_name: str, id: int
    ) -> Optional[DynamicLead]:
        """
        Busca lead por ID.

        Args:
            table_name: Nome da tabela (LeadboxCRM_xxx)
            id: ID do lead

        Returns:
            Lead ou None
        """
        try:
            response = (
                self._table(table_name)
                .select("*")
                .eq("id", id)
                .single()
                .execute()
            )
            return response.data
        except Exception as e:
            if "PGRST116" in str(e):
                return None
            logger.error(
                "dynamic_find_lead_by_id_error",
                table=table_name,
                id=id,
                error=str(e),
            )
            raise

    async def create_lead(
        self, table_name: str, data: DynamicLeadCreate
    ) -> DynamicLead:
        """
        Cria novo lead.

        Args:
            table_name: Nome da tabela (LeadboxCRM_xxx)
            data: Dados do lead

        Returns:
            Lead criado
        """
        try:
            now = datetime.now().isoformat()
            lead_data = {
                **data,
                "pipeline_step": data.get("pipeline_step", "Leads"),
                "status": data.get("status", "open"),
                "responsavel": data.get("responsavel", "Agnes IA"),
                "follow_count": 0,
                "Atendimento_Finalizado": "Nao",
                "created_date": now,
                "updated_date": now,
            }

            response = self._table(table_name).insert(lead_data).execute()
            if response.data and len(response.data) > 0:
                return response.data[0]
            raise ValueError("Insert returned no data")
        except Exception as e:
            logger.error(
                "dynamic_create_lead_error",
                table=table_name,
                error=str(e),
            )
            raise

    async def update_lead(
        self, table_name: str, id: int, data: DynamicLeadUpdate
    ) -> Optional[DynamicLead]:
        """
        Atualiza lead por ID.

        Args:
            table_name: Nome da tabela (LeadboxCRM_xxx)
            id: ID do lead
            data: Dados para atualizar

        Returns:
            Lead atualizado ou None
        """
        try:
            update_data = {
                **data,
                "updated_date": datetime.now().isoformat(),
            }
            response = (
                self._table(table_name)
                .update(update_data)
                .eq("id", id)
                .execute()
            )
            if response.data and len(response.data) > 0:
                return response.data[0]
            return None
        except Exception as e:
            logger.error(
                "dynamic_update_lead_error",
                table=table_name,
                id=id,
                error=str(e),
            )
            raise

    async def update_lead_by_remotejid(
        self, table_name: str, remotejid: str, data: DynamicLeadUpdate
    ) -> Optional[DynamicLead]:
        """
        Atualiza lead por remotejid.

        Args:
            table_name: Nome da tabela (LeadboxCRM_xxx)
            remotejid: ID remoto WhatsApp
            data: Dados para atualizar

        Returns:
            Lead atualizado ou None
        """
        try:
            update_data = {
                **data,
                "updated_date": datetime.now().isoformat(),
            }
            response = (
                self._table(table_name)
                .update(update_data)
                .eq("remotejid", remotejid)
                .execute()
            )
            if response.data and len(response.data) > 0:
                return response.data[0]
            return None
        except Exception as e:
            logger.error(
                "dynamic_update_lead_by_remotejid_error",
                table=table_name,
                remotejid=remotejid,
                error=str(e),
            )
            raise

    async def get_or_create_lead(
        self,
        table_name: str,
        remotejid: str,
        default_data: Optional[DynamicLeadCreate] = None,
    ) -> DynamicLead:
        """
        Busca lead por remotejid ou cria se nao existir.

        Implementa logica de unificacao:
        - Se @lid.whatsapp.net, extrai telefone e busca por telefone tambem
        - Se encontrar por telefone, atualiza remotejid

        Args:
            table_name: Nome da tabela (LeadboxCRM_xxx)
            remotejid: ID remoto WhatsApp
            default_data: Dados default para criar se nao existir

        Returns:
            Lead existente ou criado
        """
        # Primeiro tenta por remotejid
        lead = await self.find_lead_by_remotejid(table_name, remotejid)
        if lead:
            return lead

        # Se e @lid, tenta extrair telefone e buscar
        if "@lid" in remotejid:
            # Extrai telefone do remotejid (ex: 5511999999999@lid...)
            phone = remotejid.split("@")[0]
            if phone:
                lead_by_phone = await self.find_lead_by_phone(table_name, phone)
                if lead_by_phone:
                    # Atualiza remotejid do lead existente
                    logger.info(
                        "dynamic_lead_unification",
                        table=table_name,
                        old_jid=lead_by_phone.get("remotejid"),
                        new_jid=remotejid,
                    )
                    await self.update_lead(
                        table_name,
                        lead_by_phone["id"],
                        {"remotejid": remotejid},
                    )
                    lead_by_phone["remotejid"] = remotejid
                    return lead_by_phone

        # Cria novo lead
        create_data: DynamicLeadCreate = default_data or {}
        create_data["remotejid"] = remotejid

        # Extrai telefone do remotejid se nao fornecido
        if not create_data.get("telefone"):
            phone = remotejid.split("@")[0]
            if phone and phone.isdigit():
                create_data["telefone"] = phone

        return await self.create_lead(table_name, create_data)

    async def reset_lead(self, table_name: str, remotejid: str) -> Optional[DynamicLead]:
        """
        Reseta lead para estado inicial (para reprocessamento).

        Args:
            table_name: Nome da tabela (LeadboxCRM_xxx)
            remotejid: ID remoto WhatsApp

        Returns:
            Lead resetado ou None
        """
        return await self.update_lead_by_remotejid(
            table_name,
            remotejid,
            {
                "pipeline_step": "Leads",
                "status": "open",
                "follow_count": 0,
                "Atendimento_Finalizado": "Nao",
                "pausar_ia": False,
            },
        )

    async def set_lead_paused(
        self,
        table_name: str,
        remotejid: str,
        paused: bool,
        reason: Optional[str] = None,
    ) -> Optional[DynamicLead]:
        """
        Pausa ou ativa o bot para um lead especifico.

        Args:
            table_name: Nome da tabela (LeadboxCRM_xxx)
            remotejid: ID remoto WhatsApp
            paused: True para pausar, False para ativar
            reason: Motivo da pausa (opcional)

        Returns:
            Lead atualizado ou None
        """
        update_data: dict[str, Any] = {"pausar_ia": paused}

        if paused and reason:
            update_data["handoff_reason"] = reason
            update_data["handoff_at"] = datetime.now().isoformat()
        elif not paused:
            update_data["handoff_reason"] = None
            update_data["handoff_at"] = None

        return await self.update_lead_by_remotejid(table_name, remotejid, update_data)

    async def is_lead_paused(self, table_name: str, remotejid: str) -> bool:
        """
        Verifica se o bot esta pausado para um lead.

        Verifica múltiplos indicadores em ordem de prioridade:
        1. current_state == 'human' ou 'paused'
        2. Atendimento_Finalizado == 'true'
        3. ticket_id + current_user_id ativos (ticket com humano)
        4. pausar_ia == True (compatibilidade legada)

        Args:
            table_name: Nome da tabela (LeadboxCRM_xxx)
            remotejid: ID remoto WhatsApp

        Returns:
            True se pausado, False caso contrario
        """
        try:
            lead = await self.find_lead_by_remotejid(table_name, remotejid)
            if lead:
                # Check 1: current_state (campo correto do Leadbox)
                current_state = lead.get("current_state", "ai")
                if current_state in ("human", "paused"):
                    logger.debug(f"[IS_PAUSED] Lead {remotejid} pausado: current_state={current_state}")
                    return True

                # Check 2: Atendimento_Finalizado (flag de pausa explícita)
                if lead.get("Atendimento_Finalizado") == "true":
                    logger.debug(f"[IS_PAUSED] Lead {remotejid} pausado: Atendimento_Finalizado=true")
                    return True

                # Check 3: Ticket ativo com atendente humano
                ticket_id = lead.get("ticket_id")
                current_user_id = lead.get("current_user_id")
                if ticket_id and current_user_id:
                    logger.debug(f"[IS_PAUSED] Lead {remotejid} pausado: ticket_id={ticket_id}, user_id={current_user_id}")
                    return True

                # Check 4: Fallback para pausar_ia (compatibilidade legada)
                if bool(lead.get("pausar_ia", False)):
                    logger.debug(f"[IS_PAUSED] Lead {remotejid} pausado: pausar_ia=True")
                    return True

            return False

        except Exception as e:
            logger.error(f"Erro ao verificar se lead esta pausado: {e}")
            # Fail-safe: em caso de erro, assumir que está pausado
            return True

    async def get_all_leads(
        self,
        table_name: str,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[DynamicLead]:
        """
        Busca todos os leads de uma tabela com paginacao.

        Args:
            table_name: Nome da tabela (LeadboxCRM_xxx)
            limit: Numero maximo de leads por pagina
            offset: Offset para paginacao

        Returns:
            Lista de leads
        """
        try:
            response = (
                self._table(table_name)
                .select("*")
                .order("id", desc=False)
                .range(offset, offset + limit - 1)
                .execute()
            )
            return response.data or []
        except Exception as e:
            logger.error(
                "dynamic_get_all_leads_error",
                table=table_name,
                limit=limit,
                offset=offset,
                error=str(e),
            )
            raise

    async def count_leads(self, table_name: str) -> int:
        """
        Conta o total de leads em uma tabela.

        Args:
            table_name: Nome da tabela (LeadboxCRM_xxx)

        Returns:
            Total de leads
        """
        try:
            response = (
                self._table(table_name)
                .select("id", count="exact", head=True)
                .execute()
            )
            return response.count or 0
        except Exception as e:
            logger.error(
                "dynamic_count_leads_error",
                table=table_name,
                error=str(e),
            )
            return 0

    # ==========================================================================
    # MESSAGES (leadbox_messages_*)
    # ==========================================================================

    async def get_conversation_history(
        self, table_name: str, remotejid: str
    ) -> Optional[ConversationHistory]:
        """
        Busca historico de conversa.

        Args:
            table_name: Nome da tabela (leadbox_messages_xxx)
            remotejid: ID remoto WhatsApp

        Returns:
            ConversationHistory ou None
        """
        try:
            response = (
                self._table(table_name)
                .select("conversation_history")
                .eq("remotejid", remotejid)
                .order("creat", desc=True)
                .limit(1)
                .execute()
            )
            if response.data and len(response.data) > 0:
                return response.data[0].get("conversation_history")
            return None
        except Exception as e:
            logger.error(
                "dynamic_get_conversation_history_error",
                table=table_name,
                remotejid=remotejid,
                error=str(e),
            )
            raise

    async def upsert_conversation_history(
        self,
        table_name: str,
        remotejid: str,
        history: ConversationHistory,
        last_message_role: str = "user",
    ) -> LeadMessage:
        """
        Insere ou atualiza historico de conversa.

        Preserva dianaContext se existir no registro atual.

        Args:
            table_name: Nome da tabela (leadbox_messages_xxx)
            remotejid: ID remoto WhatsApp
            history: Historico de conversa
            last_message_role: Role da ultima mensagem ('user' ou 'model')

        Returns:
            Registro atualizado
        """
        try:
            # Busca registro existente para preservar dianaContext
            existing = await self.get_conversation_history(table_name, remotejid)

            # Preserva dianaContext se existir
            if existing and existing.get("dianaContext"):
                if "dianaContext" not in history:
                    history["dianaContext"] = existing["dianaContext"]

            now = datetime.now().isoformat()
            timestamp_field = "Msg_user" if last_message_role == "user" else "Msg_model"

            data = {
                "remotejid": remotejid,
                "conversation_history": history,
                timestamp_field: now,
                "creat": now,
            }

            # Tenta update primeiro
            response = (
                self._table(table_name)
                .update(data)
                .eq("remotejid", remotejid)
                .execute()
            )

            if response.data and len(response.data) > 0:
                return response.data[0]

            # Se nao atualizou, insere
            response = self._table(table_name).insert(data).execute()
            if response.data and len(response.data) > 0:
                return response.data[0]

            raise ValueError("Upsert returned no data")

        except Exception as e:
            logger.error(
                "dynamic_upsert_conversation_history_error",
                table=table_name,
                remotejid=remotejid,
                error=str(e),
            )
            raise

    async def add_message_to_history(
        self,
        table_name: str,
        remotejid: str,
        message: GeminiMessage,
    ) -> ConversationHistory:
        """
        Adiciona mensagem ao historico existente.

        Args:
            table_name: Nome da tabela (leadbox_messages_xxx)
            remotejid: ID remoto WhatsApp
            message: Mensagem para adicionar

        Returns:
            Historico atualizado
        """
        # Busca historico existente
        history = await self.get_conversation_history(table_name, remotejid)
        if not history:
            history = {"messages": []}

        # Adiciona mensagem
        messages = history.get("messages", [])
        messages.append(message)
        history["messages"] = messages

        # Atualiza
        await self.upsert_conversation_history(
            table_name,
            remotejid,
            history,
            last_message_role=message.get("role", "user"),
        )

        return history

    async def clear_conversation_history(
        self, table_name: str, remotejid: str
    ) -> None:
        """
        Limpa historico de conversa (mantendo o registro).

        Args:
            table_name: Nome da tabela (leadbox_messages_xxx)
            remotejid: ID remoto WhatsApp
        """
        try:
            await self.upsert_conversation_history(
                table_name,
                remotejid,
                {"messages": []},
                last_message_role="user",
            )
        except Exception as e:
            logger.error(
                "dynamic_clear_conversation_history_error",
                table=table_name,
                remotejid=remotejid,
                error=str(e),
            )
            raise

    async def delete_conversation_history(
        self, table_name: str, remotejid: str
    ) -> bool:
        """
        Deleta registro de historico de conversa.

        Args:
            table_name: Nome da tabela (leadbox_messages_xxx)
            remotejid: ID remoto WhatsApp

        Returns:
            True se deletado
        """
        try:
            self._table(table_name).delete().eq("remotejid", remotejid).execute()
            return True
        except Exception as e:
            logger.error(
                "dynamic_delete_conversation_history_error",
                table=table_name,
                remotejid=remotejid,
                error=str(e),
            )
            return False

    async def update_message_timestamp(
        self,
        table_name: str,
        remotejid: str,
        role: str,
    ) -> None:
        """
        Atualiza timestamp de mensagem.

        Args:
            table_name: Nome da tabela (leadbox_messages_xxx)
            remotejid: ID remoto WhatsApp
            role: Role da mensagem ('user' ou 'model')
        """
        try:
            now = datetime.now().isoformat()
            timestamp_field = "Msg_user" if role == "user" else "Msg_model"

            # Tenta update
            response = (
                self._table(table_name)
                .update({timestamp_field: now})
                .eq("remotejid", remotejid)
                .execute()
            )

            # Se nao atualizou (registro nao existe), insere
            if not response.data:
                self._table(table_name).insert({
                    "remotejid": remotejid,
                    timestamp_field: now,
                    "creat": now,
                    "conversation_history": {"messages": []},
                }).execute()

        except Exception as e:
            logger.error(
                "dynamic_update_message_timestamp_error",
                table=table_name,
                remotejid=remotejid,
                role=role,
                error=str(e),
            )
            raise

    async def get_message_timestamps(
        self, table_name: str, remotejid: str
    ) -> Optional[dict[str, str]]:
        """
        Retorna timestamps de mensagens.

        Args:
            table_name: Nome da tabela (leadbox_messages_xxx)
            remotejid: ID remoto WhatsApp

        Returns:
            Dict com Msg_user e Msg_model ou None
        """
        try:
            response = (
                self._table(table_name)
                .select("Msg_user,Msg_model")
                .eq("remotejid", remotejid)
                .single()
                .execute()
            )
            return response.data
        except Exception as e:
            if "PGRST116" in str(e):
                return None
            raise

    # ==========================================================================
    # CONTROLE (Controle_*)
    # ==========================================================================

    async def find_controle_by_remotejid(
        self, table_name: str, remotejid: str
    ) -> Optional[Controle]:
        """
        Busca controle por remotejid.

        Args:
            table_name: Nome da tabela (Controle_xxx)
            remotejid: ID remoto WhatsApp

        Returns:
            Controle ou None
        """
        try:
            response = (
                self._table(table_name)
                .select("*")
                .eq("remotejid", remotejid)
                .single()
                .execute()
            )
            return response.data
        except Exception as e:
            if "PGRST116" in str(e):
                return None
            logger.error(
                "dynamic_find_controle_error",
                table=table_name,
                remotejid=remotejid,
                error=str(e),
            )
            raise

    async def create_controle(
        self, table_name: str, data: dict[str, Any]
    ) -> Controle:
        """
        Cria registro de controle.

        Args:
            table_name: Nome da tabela (Controle_xxx)
            data: Dados do controle

        Returns:
            Controle criado
        """
        try:
            now = datetime.now().isoformat()
            controle_data = {
                **data,
                "created_at": now,
                "updated_at": now,
            }
            response = self._table(table_name).insert(controle_data).execute()
            if response.data and len(response.data) > 0:
                return response.data[0]
            raise ValueError("Insert returned no data")
        except Exception as e:
            logger.error(
                "dynamic_create_controle_error",
                table=table_name,
                error=str(e),
            )
            raise

    async def update_controle_by_remotejid(
        self, table_name: str, remotejid: str, data: dict[str, Any]
    ) -> Optional[Controle]:
        """
        Atualiza controle por remotejid.

        Args:
            table_name: Nome da tabela (Controle_xxx)
            remotejid: ID remoto WhatsApp
            data: Dados para atualizar

        Returns:
            Controle atualizado ou None
        """
        try:
            update_data = {
                **data,
                "updated_at": datetime.now().isoformat(),
            }
            response = (
                self._table(table_name)
                .update(update_data)
                .eq("remotejid", remotejid)
                .execute()
            )
            if response.data and len(response.data) > 0:
                return response.data[0]
            return None
        except Exception as e:
            logger.error(
                "dynamic_update_controle_error",
                table=table_name,
                remotejid=remotejid,
                error=str(e),
            )
            raise

    # ==========================================================================
    # LEAD SESSIONS (lead_sessions)
    # ==========================================================================

    async def ensure_session(
        self,
        agent_id: str,
        remotejid: str,
        inactivity_hours: int = 4,
    ) -> int:
        """
        Verifica/cria sessao de atendimento e retorna total de sessoes do cliente.

        Uma nova sessao e criada quando:
        - Nao existe sessao anterior para este lead
        - A ultima sessao e mais antiga que inactivity_hours

        Args:
            agent_id: ID do agente
            remotejid: ID WhatsApp do lead
            inactivity_hours: Horas de inatividade para considerar nova sessao

        Returns:
            Total de sessoes do cliente com este agente
        """
        from datetime import timedelta

        try:
            now = datetime.now()
            cutoff = now - timedelta(hours=inactivity_hours)

            # Buscar ultima sessao
            result = (
                self._client.table("lead_sessions")
                .select("id, started_at, ended_at")
                .eq("agent_id", agent_id)
                .eq("remotejid", remotejid)
                .order("started_at", desc=True)
                .limit(1)
                .execute()
            )

            last_session = result.data[0] if result.data else None

            # Verificar se precisa criar nova sessao
            needs_new_session = False
            if not last_session:
                needs_new_session = True
            else:
                last_started_str = last_session["started_at"]
                # Parse ISO datetime
                last_started = datetime.fromisoformat(
                    last_started_str.replace("Z", "+00:00")
                ).replace(tzinfo=None)
                if last_started < cutoff:
                    needs_new_session = True

            if needs_new_session:
                # Fechar sessao anterior se estiver aberta
                if last_session and not last_session.get("ended_at"):
                    self._client.table("lead_sessions").update({
                        "ended_at": now.isoformat()
                    }).eq("id", last_session["id"]).execute()

                # Criar nova sessao
                self._client.table("lead_sessions").insert({
                    "agent_id": agent_id,
                    "remotejid": remotejid,
                    "started_at": now.isoformat()
                }).execute()

                logger.info(
                    "session_created",
                    agent_id=agent_id[:8],
                    remotejid=remotejid,
                )

            # Contar total de sessoes
            count_result = (
                self._client.table("lead_sessions")
                .select("id", count="exact", head=True)
                .eq("agent_id", agent_id)
                .eq("remotejid", remotejid)
                .execute()
            )

            return count_result.count if count_result.count else 1

        except Exception as e:
            logger.error(
                "session_ensure_error",
                agent_id=agent_id,
                remotejid=remotejid,
                error=str(e),
            )
            # Em caso de erro, retornar 1 para nao quebrar o fluxo
            return 1


# ==============================================================================
# SINGLETON INSTANCE
# ==============================================================================

dynamic_repository = DynamicRepository()
