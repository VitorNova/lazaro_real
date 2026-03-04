"""
SupabaseService - Servico de integracao com Supabase para o agente-ia Python.

Este servico gerencia:
- Conexao com Supabase usando supabase-py
- Tabelas dinamicas: LeadboxCRM_{shortId} e leadbox_messages_{shortId}
- CRUD de leads (get_lead_by_phone, create_lead, update_lead)
- Historico em JSONB formato Gemini (conversation_history)
- Metodos para pausar/ativar bot (set_lead_paused)
- get_agent_config e get_agent_prompt
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, TypedDict

from supabase import create_client, Client

from app.config import settings

# Configurar logging
logger = logging.getLogger(__name__)


# ============================================================================
# TYPE DEFINITIONS
# ============================================================================

class GeminiMessage(TypedDict):
    """Formato de mensagem do Gemini."""
    role: str  # 'user' ou 'model'
    parts: List[Dict[str, str]]
    timestamp: str


class ConversationHistory(TypedDict):
    """Formato do historico de conversa no Gemini."""
    messages: List[GeminiMessage]


class DynamicLead(TypedDict, total=False):
    """Tipo para lead dinamico (tabela LeadboxCRM_*)."""
    id: int
    nome: Optional[str]
    telefone: Optional[str]
    email: Optional[str]
    empresa: Optional[str]
    ad_url: Optional[str]
    pacote: Optional[str]
    resumo: Optional[str]
    pipeline_step: str
    valor: Optional[float]
    status: str
    close_date: Optional[str]
    lead_origin: Optional[str]
    diana_prospect_id: Optional[str]
    responsavel: str
    remotejid: Optional[str]
    follow_count: int
    updated_date: str
    created_date: str
    venda_realizada: Optional[str]
    Atendimento_Finalizado: str
    ultimo_intent: Optional[str]
    crm: Optional[str]
    # Opt-out de follow-up
    follow_up_opted_out: Optional[bool]
    follow_up_opted_out_reason: Optional[str]
    follow_up_opted_out_at: Optional[str]
    # Localizacao
    cidade: Optional[str]
    estado: Optional[str]
    timezone: Optional[str]
    # Follow-up tracking
    follow_up_notes: Optional[str]
    last_follow_up_at: Optional[str]
    # Scheduling
    next_appointment_at: Optional[str]
    next_appointment_link: Optional[str]
    last_scheduled_at: Optional[str]
    # Agent journey
    attended_by: Optional[str]
    journey_stage: Optional[str]
    # Pausa IA
    pausar_ia: Optional[bool]


class LeadMessage(TypedDict, total=False):
    """Tipo para mensagem de lead (tabela leadbox_messages_*)."""
    id: str
    creat: str
    remotejid: str
    conversation_history: Optional[Dict[str, Any]]
    Msg_model: Optional[str]
    Msg_user: Optional[str]


class Agent(TypedDict, total=False):
    """Tipo para agent (tabela agents)."""
    id: str
    user_id: str
    name: str
    status: str
    # WhatsApp
    whatsapp_provider: str
    uazapi_instance_id: Optional[str]
    uazapi_token: Optional[str]
    uazapi_base_url: Optional[str]
    # Dynamic tables
    table_leads: str
    table_messages: str
    # AI Config
    ai_provider: str
    gemini_api_key: Optional[str]
    gemini_model: str
    system_prompt: Optional[str]
    # Business
    business_hours: Optional[Dict[str, str]]
    timezone: str
    pipeline_stages: Optional[List[Dict[str, Any]]]
    # Follow-up
    follow_up_enabled: bool
    follow_up_config: Optional[Dict[str, Any]]


# ============================================================================
# SUPABASE SERVICE
# ============================================================================

class SupabaseService:
    """
    Servico para interacao com Supabase.

    Gerencia conexao e operacoes CRUD para:
    - Tabelas dinamicas de leads (LeadboxCRM_{shortId})
    - Tabelas dinamicas de mensagens (leadbox_messages_{shortId})
    - Tabela de agents
    """

    def __init__(self, url: Optional[str] = None, key: Optional[str] = None):
        """
        Inicializa o cliente Supabase.

        Args:
            url: URL do Supabase (default: from settings)
            key: Service key do Supabase (default: from settings)
        """
        self.url = url or settings.supabase_url
        self.key = key or settings.supabase_service_key

        if not self.url or not self.key:
            raise ValueError(
                "SUPABASE_URL e SUPABASE_SERVICE_KEY sao obrigatorios. "
                "Configure no arquivo .env ou passe como parametros."
            )

        self.client: Client = create_client(self.url, self.key)
        logger.info("SupabaseService inicializado com sucesso")

    # ========================================================================
    # LEADS (tabelas LeadboxCRM_*)
    # ========================================================================

    def get_leads_table(self, short_id: str) -> str:
        """Retorna o nome da tabela de leads para um agent."""
        return f"LeadboxCRM_{short_id}"

    def get_messages_table(self, short_id: str) -> str:
        """Retorna o nome da tabela de mensagens para um agent."""
        return f"leadbox_messages_{short_id}"

    def get_lead_by_phone(
        self,
        table_name: str,
        telefone: str
    ) -> Optional[DynamicLead]:
        """
        Busca lead pelo numero de telefone.

        Args:
            table_name: Nome da tabela de leads (ex: LeadboxCRM_abc123)
            telefone: Numero de telefone do lead

        Returns:
            Lead encontrado ou None
        """
        try:
            logger.debug(f"Buscando lead por telefone {telefone} em {table_name}")

            response = (
                self.client
                .table(table_name)
                .select("*")
                .eq("telefone", telefone)
                .limit(1)
                .execute()
            )

            if response and response.data and len(response.data) > 0:
                logger.debug(f"Lead encontrado: id={response.data[0].get('id')}")
                return response.data[0]

            logger.debug(f"Lead nao encontrado para telefone {telefone}")
            return None

        except Exception as e:
            logger.error(f"Erro ao buscar lead por telefone: {e}")
            raise

    def get_lead_by_remotejid(
        self,
        table_name: str,
        remotejid: str
    ) -> Optional[DynamicLead]:
        """
        Busca lead pelo remotejid (WhatsApp ID).

        Args:
            table_name: Nome da tabela de leads
            remotejid: ID WhatsApp (ex: 5511999999999@s.whatsapp.net)

        Returns:
            Lead encontrado ou None
        """
        try:
            logger.debug(f"Buscando lead por remotejid {remotejid} em {table_name}")

            response = (
                self.client
                .table(table_name)
                .select("*")
                .eq("remotejid", remotejid)
                .limit(1)
                .execute()
            )

            if response and response.data and len(response.data) > 0:
                logger.debug(f"Lead encontrado: id={response.data[0].get('id')}")
                return response.data[0]

            logger.debug(f"Lead nao encontrado para remotejid {remotejid}")
            return None

        except Exception as e:
            logger.error(f"Erro ao buscar lead por remotejid: {e}")
            raise

    def get_lead_by_id(
        self,
        table_name: str,
        lead_id: int
    ) -> Optional[DynamicLead]:
        """
        Busca lead pelo ID.

        Args:
            table_name: Nome da tabela de leads
            lead_id: ID do lead

        Returns:
            Lead encontrado ou None
        """
        try:
            logger.debug(f"Buscando lead por id {lead_id} em {table_name}")

            response = (
                self.client
                .table(table_name)
                .select("*")
                .eq("id", lead_id)
                .limit(1)
                .execute()
            )

            if response and response.data and len(response.data) > 0:
                return response.data[0]
            return None

        except Exception as e:
            logger.error(f"Erro ao buscar lead por id: {e}")
            raise

    def create_lead(
        self,
        table_name: str,
        data: Dict[str, Any]
    ) -> DynamicLead:
        """
        Cria um novo lead.

        Args:
            table_name: Nome da tabela de leads
            data: Dados do lead

        Returns:
            Lead criado
        """
        try:
            now = datetime.utcnow().isoformat()

            lead_data = {
                "pipeline_step": "Leads",
                "status": "open",
                "Atendimento_Finalizado": "false",
                "responsavel": "AI",
                "follow_count": 0,
                "created_date": now,
                "updated_date": now,
                **data,
            }

            logger.info(f"Criando lead em {table_name}")
            logger.debug(f"Dados: {lead_data}")

            response = (
                self.client
                .table(table_name)
                .insert(lead_data)
                .execute()
            )

            if response.data and len(response.data) > 0:
                lead = response.data[0]
                logger.info(f"Lead criado com id: {lead.get('id')}")
                return lead

            raise Exception("Falha ao criar lead - resposta vazia")

        except Exception as e:
            logger.error(f"Erro ao criar lead: {e}")
            raise

    def update_lead(
        self,
        table_name: str,
        lead_id: int,
        data: Dict[str, Any]
    ) -> DynamicLead:
        """
        Atualiza um lead existente.

        Args:
            table_name: Nome da tabela de leads
            lead_id: ID do lead
            data: Dados para atualizar

        Returns:
            Lead atualizado
        """
        try:
            update_data = {
                **data,
                "updated_date": datetime.utcnow().isoformat(),
            }

            logger.debug(f"Atualizando lead {lead_id} em {table_name}")

            response = (
                self.client
                .table(table_name)
                .update(update_data)
                .eq("id", lead_id)
                .execute()
            )

            if response.data and len(response.data) > 0:
                logger.info(f"Lead {lead_id} atualizado")
                return response.data[0]

            raise Exception(f"Lead {lead_id} nao encontrado")

        except Exception as e:
            logger.error(f"Erro ao atualizar lead: {e}")
            raise

    def update_lead_by_remotejid(
        self,
        table_name: str,
        remotejid: str,
        data: Dict[str, Any]
    ) -> Optional[DynamicLead]:
        """
        Atualiza lead pelo remotejid.

        Args:
            table_name: Nome da tabela de leads
            remotejid: ID WhatsApp do lead
            data: Dados para atualizar

        Returns:
            Lead atualizado ou None se nao encontrado
        """
        try:
            update_data = {
                **data,
                "updated_date": datetime.utcnow().isoformat(),
            }

            logger.debug(f"Atualizando lead por remotejid {remotejid} em {table_name}")

            response = (
                self.client
                .table(table_name)
                .update(update_data)
                .eq("remotejid", remotejid)
                .execute()
            )

            if response.data and len(response.data) > 0:
                logger.info(f"Lead atualizado por remotejid {remotejid}")
                return response.data[0]

            logger.debug(f"Lead nao encontrado para remotejid {remotejid}")
            return None

        except Exception as e:
            logger.error(f"Erro ao atualizar lead por remotejid: {e}")
            raise

    def get_or_create_lead(
        self,
        table_name: str,
        remotejid: str,
        default_data: Optional[Dict[str, Any]] = None
    ) -> DynamicLead:
        """
        Busca lead pelo remotejid ou cria um novo se nao existir.

        Implementa unificacao de leads @lid -> @s.whatsapp.net.

        Args:
            table_name: Nome da tabela de leads
            remotejid: ID WhatsApp do lead
            default_data: Dados padrao para criacao

        Returns:
            Lead existente ou recem criado
        """
        try:
            # 1. Buscar pelo remotejid exato
            existing = self.get_lead_by_remotejid(table_name, remotejid)
            if existing:
                return existing

            # 2. Se remotejid e @s.whatsapp.net, buscar pelo telefone
            # para evitar duplicacao de leads que vieram via @lid
            if remotejid.endswith("@s.whatsapp.net"):
                telefone = remotejid.replace("@s.whatsapp.net", "")

                existing_by_phone = self.get_lead_by_phone(table_name, telefone)

                if existing_by_phone:
                    old_remotejid = existing_by_phone.get("remotejid", "")

                    # Se o lead antigo era @lid, atualizar para @s.whatsapp.net
                    if old_remotejid and old_remotejid.endswith("@lid"):
                        logger.info(
                            f"[Lead Unification] Atualizando remotejid de {old_remotejid} "
                            f"para {remotejid}"
                        )

                        updated = self.update_lead(
                            table_name,
                            existing_by_phone["id"],
                            {"remotejid": remotejid}
                        )

                        # Atualizar remotejid nas mensagens tambem
                        agent_suffix = table_name.replace("LeadboxCRM_", "")
                        messages_table = f"leadbox_messages_{agent_suffix}"

                        try:
                            self.client.table(messages_table).update(
                                {"remotejid": remotejid}
                            ).eq("remotejid", old_remotejid).execute()

                            logger.info(
                                f"[Lead Unification] Mensagens atualizadas em {messages_table}"
                            )
                        except Exception as msg_err:
                            logger.error(
                                f"[Lead Unification] Erro ao atualizar mensagens: {msg_err}"
                            )

                        return updated

                    return existing_by_phone

            # 3. Criar novo lead
            create_data = {
                "remotejid": remotejid,
                **(default_data or {}),
            }

            return self.create_lead(table_name, create_data)

        except Exception as e:
            logger.error(f"Erro em get_or_create_lead: {e}")
            raise

    def set_lead_paused(
        self,
        table_name: str,
        remotejid: str,
        paused: bool,
        reason: Optional[str] = None
    ) -> Optional[DynamicLead]:
        """
        Pausa ou ativa o bot para um lead especifico.

        Args:
            table_name: Nome da tabela de leads
            remotejid: ID WhatsApp do lead
            paused: True para pausar, False para ativar
            reason: Motivo da pausa (opcional)

        Returns:
            Lead atualizado ou None se nao encontrado
        """
        try:
            logger.info(
                f"{'Pausando' if paused else 'Ativando'} bot para lead {remotejid}"
            )

            update_data: Dict[str, Any] = {
                "pausar_ia": paused,
            }

            if paused and reason:
                update_data["handoff_reason"] = reason
                update_data["handoff_at"] = datetime.utcnow().isoformat()
            elif not paused:
                # Limpar campos de handoff ao reativar
                update_data["handoff_reason"] = None
                update_data["handoff_at"] = None

            return self.update_lead_by_remotejid(table_name, remotejid, update_data)

        except Exception as e:
            logger.error(f"Erro ao pausar/ativar lead: {e}")
            raise

    def is_lead_paused(
        self,
        table_name: str,
        remotejid: str
    ) -> bool:
        """
        Verifica se o bot esta pausado para um lead.

        Args:
            table_name: Nome da tabela de leads
            remotejid: ID WhatsApp do lead

        Returns:
            True se pausado, False caso contrario
        """
        try:
            lead = self.get_lead_by_remotejid(table_name, remotejid)

            if lead:
                return bool(lead.get("pausar_ia", False))

            return False

        except Exception as e:
            logger.error(f"Erro ao verificar se lead esta pausado: {e}")
            return False

    # ========================================================================
    # LEAD SESSIONS (tabela lead_sessions)
    # ========================================================================

    def ensure_session(
        self,
        agent_id: str,
        remotejid: str,
        inactivity_hours: int = 4
    ) -> int:
        """
        Verifica/cria sessão de atendimento e retorna total de sessões do cliente.

        Uma nova sessão é criada quando:
        - Não existe sessão anterior para este lead
        - A última sessão é mais antiga que inactivity_hours

        Args:
            agent_id: ID do agente
            remotejid: ID WhatsApp do lead
            inactivity_hours: Horas de inatividade para considerar nova sessão (default: 4)

        Returns:
            Total de sessões do cliente com este agente
        """
        try:
            now = datetime.utcnow()
            cutoff = now - timedelta(hours=inactivity_hours)

            # Buscar última sessão
            result = (
                self.client
                .table("lead_sessions")
                .select("id, started_at, ended_at")
                .eq("agent_id", agent_id)
                .eq("remotejid", remotejid)
                .order("started_at", desc=True)
                .limit(1)
                .execute()
            )

            last_session = result.data[0] if result.data else None

            # Verificar se precisa criar nova sessão
            needs_new_session = False
            if not last_session:
                needs_new_session = True
            else:
                last_started = datetime.fromisoformat(
                    last_session["started_at"].replace("Z", "+00:00")
                ).replace(tzinfo=None)
                if last_started < cutoff:
                    needs_new_session = True

            if needs_new_session:
                # Fechar sessão anterior se estiver aberta
                if last_session and not last_session.get("ended_at"):
                    self.client.table("lead_sessions").update({
                        "ended_at": now.isoformat()
                    }).eq("id", last_session["id"]).execute()

                # Criar nova sessão
                self.client.table("lead_sessions").insert({
                    "agent_id": agent_id,
                    "remotejid": remotejid,
                    "started_at": now.isoformat()
                }).execute()

                logger.info(f"[SESSION] Nova sessão criada para {remotejid} com agente {agent_id[:8]}")

            # Contar total de sessões
            count_result = (
                self.client
                .table("lead_sessions")
                .select("id", count="exact")
                .eq("agent_id", agent_id)
                .eq("remotejid", remotejid)
                .execute()
            )

            total = count_result.count if count_result.count else 1
            logger.debug(f"[SESSION] Lead {remotejid} tem {total} sessões com agente {agent_id[:8]}")

            return total

        except Exception as e:
            logger.error(f"Erro ao verificar/criar sessão: {e}")
            # Em caso de erro, retornar 1 para não quebrar o fluxo
            return 1

    # ========================================================================
    # CONVERSATION HISTORY (tabelas leadbox_messages_*)
    # ========================================================================

    def get_conversation_history(
        self,
        table_name: str,
        remotejid: str
    ) -> Optional[ConversationHistory]:
        """
        Busca o historico de conversa de um lead.

        Args:
            table_name: Nome da tabela de mensagens
            remotejid: ID WhatsApp do lead

        Returns:
            Historico de conversa no formato Gemini ou None
        """
        try:
            logger.debug(f"Buscando historico de {remotejid} em {table_name}")

            response = (
                self.client
                .table(table_name)
                .select("conversation_history")
                .eq("remotejid", remotejid)
                .order("creat", desc=True)
                .limit(1)
                .execute()
            )

            if response and response.data and len(response.data) > 0:
                record = response.data[0]
                if record.get("conversation_history"):
                    history = record["conversation_history"]
                    logger.debug(
                        f"Historico encontrado com {len(history.get('messages', []))} mensagens"
                    )
                    return history

            logger.debug(f"Nenhum historico encontrado para {remotejid}")
            return None

        except Exception as e:
            logger.error(f"Erro ao buscar historico de conversa: {e}")
            raise

    def upsert_conversation_history(
        self,
        table_name: str,
        remotejid: str,
        history: ConversationHistory,
        last_message_role: Optional[str] = None,
        set_user_timestamp: bool = False
    ) -> None:
        """
        Insere ou atualiza o historico de conversa.

        Args:
            table_name: Nome da tabela de mensagens
            remotejid: ID WhatsApp do lead
            history: Historico de conversa no formato Gemini
            last_message_role: Role da ultima mensagem ('user' ou 'model')
            set_user_timestamp: Se True, atualiza Msg_user independente do last_message_role.
                                 Util quando a funcao salva tanto mensagem do usuario quanto
                                 do modelo no mesmo upsert.
        """
        try:
            now = datetime.utcnow().isoformat()

            logger.debug(f"Upsert de historico para {remotejid} em {table_name}")

            # Verificar se ja existe registro
            existing_response = (
                self.client
                .table(table_name)
                .select("id, conversation_history")
                .eq("remotejid", remotejid)
                .limit(1)
                .execute()
            )

            existing_record = None
            if existing_response and existing_response.data and len(existing_response.data) > 0:
                existing_record = existing_response.data[0]

            # Preservar dianaContext se existir (para leads transferidos)
            merged_history = dict(history)
            if existing_record:
                existing_history = existing_record.get("conversation_history") or {}
                diana_context = existing_history.get("dianaContext")
                if diana_context:
                    merged_history["dianaContext"] = diana_context
                    logger.debug("Preservando dianaContext para lead transferido")

            # Preparar dados de update
            update_data: Dict[str, Any] = {
                "conversation_history": merged_history,
                "creat": now,
            }

            # Atualizar timestamp baseado no role
            if last_message_role == "model":
                update_data["Msg_model"] = now
            elif last_message_role == "user":
                update_data["Msg_user"] = now

            # Atualizar Msg_user se solicitado explicitamente
            # (usado quando o upsert inclui mensagem do usuario E do modelo)
            if set_user_timestamp and "Msg_user" not in update_data:
                update_data["Msg_user"] = now

            if existing_record:
                # UPDATE
                logger.debug("Registro existente, fazendo UPDATE")
                self.client.table(table_name).update(update_data).eq(
                    "remotejid", remotejid
                ).execute()
            else:
                # INSERT
                logger.debug("Registro nao existe, fazendo INSERT")
                self.client.table(table_name).insert({
                    "remotejid": remotejid,
                    **update_data,
                }).execute()

            logger.info(f"Historico salvo para {remotejid}")

        except Exception as e:
            logger.error(f"Erro ao salvar historico de conversa: {e}")
            raise

    def add_message_to_history(
        self,
        table_name: str,
        remotejid: str,
        role: str,
        text: str
    ) -> ConversationHistory:
        """
        Adiciona uma mensagem ao historico de conversa.

        Args:
            table_name: Nome da tabela de mensagens
            remotejid: ID WhatsApp do lead
            role: Role da mensagem ('user' ou 'model')
            text: Texto da mensagem

        Returns:
            Historico atualizado
        """
        try:
            # Buscar historico existente
            existing_history = self.get_conversation_history(table_name, remotejid)

            if existing_history:
                history = existing_history
            else:
                history = {"messages": []}

            # Criar nova mensagem no formato Gemini
            new_message: GeminiMessage = {
                "role": role,
                "parts": [{"text": text}],
                "timestamp": datetime.utcnow().isoformat(),
            }

            # Adicionar ao historico
            history["messages"].append(new_message)

            # Salvar
            self.upsert_conversation_history(
                table_name,
                remotejid,
                history,
                last_message_role=role
            )

            return history

        except Exception as e:
            logger.error(f"Erro ao adicionar mensagem ao historico: {e}")
            raise

    def clear_conversation_history(
        self,
        table_name: str,
        remotejid: str
    ) -> int:
        """
        Limpa o historico de conversa de um lead (mantendo o registro).

        Args:
            table_name: Nome da tabela de mensagens
            remotejid: ID WhatsApp do lead

        Returns:
            Numero de registros afetados
        """
        try:
            logger.info(f"Limpando historico de {remotejid} em {table_name}")

            response = (
                self.client
                .table(table_name)
                .update({
                    "conversation_history": {"messages": []},
                    "Msg_model": None,
                    "Msg_user": None,
                    "creat": datetime.utcnow().isoformat(),
                })
                .eq("remotejid", remotejid)
                .execute()
            )

            count = len(response.data) if response.data else 0
            logger.info(f"Historico limpo, {count} registro(s) afetado(s)")
            return count

        except Exception as e:
            logger.error(f"Erro ao limpar historico: {e}")
            raise

    def get_message_timestamps(
        self,
        table_name: str,
        remotejid: str
    ) -> Optional[Dict[str, Optional[str]]]:
        """
        Obtem timestamps de mensagem para um lead.

        Args:
            table_name: Nome da tabela de mensagens
            remotejid: ID WhatsApp do lead

        Returns:
            Dict com Msg_model e Msg_user ou None
        """
        try:
            response = (
                self.client
                .table(table_name)
                .select("Msg_model, Msg_user")
                .eq("remotejid", remotejid)
                .maybe_single()
                .execute()
            )

            return response.data

        except Exception as e:
            logger.error(f"Erro ao obter timestamps: {e}")
            raise

    # ========================================================================
    # AGENTS
    # ========================================================================

    def get_agent_by_id(self, agent_id: str) -> Optional[Agent]:
        """
        Busca agent pelo ID.

        Args:
            agent_id: ID do agent

        Returns:
            Agent encontrado ou None
        """
        try:
            logger.debug(f"Buscando agent por id: {agent_id}")

            response = (
                self.client
                .table("agents")
                .select("*")
                .eq("id", agent_id)
                .limit(1)
                .execute()
            )

            if response and response.data and len(response.data) > 0:
                return response.data[0]
            return None

        except Exception as e:
            logger.error(f"Erro ao buscar agent: {e}")
            raise

    def get_agent_by_instance_id(self, instance_id: str) -> Optional[Agent]:
        """
        Busca agent pelo UAZAPI instance ID.
        Retorna None se o agente estiver inativo (active=false ou status=paused).

        Args:
            instance_id: ID da instancia UAZAPI

        Returns:
            Agent encontrado e ativo, ou None
        """
        try:
            logger.debug(f"Buscando agent por instance_id: {instance_id}")

            response = (
                self.client
                .table("agents")
                .select("*")
                .eq("uazapi_instance_id", instance_id)
                .eq("active", True)
                .limit(1)
                .execute()
            )

            if response and response.data and len(response.data) > 0:
                return response.data[0]
            return None

        except Exception as e:
            logger.error(f"Erro ao buscar agent por instance_id: {e}")
            raise

    def get_agent_by_token(self, token: str) -> Optional[Agent]:
        """
        Busca agent pelo UAZAPI token.
        Retorna None se o agente estiver inativo (active=false ou status=paused).

        Args:
            token: Token da instancia UAZAPI

        Returns:
            Agent encontrado e ativo, ou None
        """
        try:
            logger.debug(f"Buscando agent por token: {token[:10]}...")

            response = (
                self.client
                .table("agents")
                .select("*")
                .eq("uazapi_token", token)
                .eq("active", True)
                .limit(1)
                .execute()
            )

            if response and response.data and len(response.data) > 0:
                return response.data[0]
            return None

        except Exception as e:
            logger.error(f"Erro ao buscar agent por token: {e}")
            raise

    def get_agent_config(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        Busca configuracao completa do agent.

        Retorna campos relevantes para processamento de IA:
        - AI provider e credenciais
        - Business config (horarios, timezone)
        - Follow-up config
        - Pipeline stages

        Args:
            agent_id: ID do agent

        Returns:
            Configuracao do agent ou None
        """
        try:
            agent = self.get_agent_by_id(agent_id)

            if not agent:
                return None

            # Extrair config relevante
            config = {
                "id": agent.get("id"),
                "name": agent.get("name"),
                "status": agent.get("status"),
                # AI Config
                "ai_provider": agent.get("ai_provider", "gemini"),
                "gemini_api_key": agent.get("gemini_api_key"),
                "gemini_model": agent.get("gemini_model", "gemini-2.0-flash"),
                "claude_api_key": agent.get("claude_api_key"),
                "claude_model": agent.get("claude_model"),
                "ai_temperature": agent.get("ai_temperature", 0.4),
                "ai_temperature_conversation": agent.get("ai_temperature_conversation"),
                # Response config
                "response_size": agent.get("response_size", "medium"),
                "split_messages": agent.get("split_messages", True),
                "split_mode": agent.get("split_mode", "smart"),
                "max_chars_per_message": agent.get("max_chars_per_message", 500),
                "message_buffer_delay": agent.get("message_buffer_delay", 9000),
                # Business config
                "business_hours": agent.get("business_hours"),
                "work_days": agent.get("work_days"),
                "timezone": agent.get("timezone", "America/Sao_Paulo"),
                # Pipeline
                "pipeline_stages": agent.get("pipeline_stages", []),
                # Follow-up
                "follow_up_enabled": agent.get("follow_up_enabled", False),
                "follow_up_config": agent.get("follow_up_config"),
                # Tabelas dinamicas
                "table_leads": agent.get("table_leads"),
                "table_messages": agent.get("table_messages"),
                # WhatsApp
                "whatsapp_provider": agent.get("whatsapp_provider", "uazapi"),
                "uazapi_base_url": agent.get("uazapi_base_url"),
                "uazapi_token": agent.get("uazapi_token"),
                "uazapi_instance_id": agent.get("uazapi_instance_id"),
                # Handoff
                "handoff_triggers": agent.get("handoff_triggers"),
            }

            return config

        except Exception as e:
            logger.error(f"Erro ao buscar config do agent: {e}")
            raise

    def get_agent_prompt(self, agent_id: str) -> Optional[str]:
        """
        Busca o system prompt do agent.

        Args:
            agent_id: ID do agent

        Returns:
            System prompt ou None
        """
        try:
            response = (
                self.client
                .table("agents")
                .select("system_prompt")
                .eq("id", agent_id)
                .limit(1)
                .execute()
            )

            if response and response.data and len(response.data) > 0:
                return response.data[0].get("system_prompt")

            return None

        except Exception as e:
            logger.error(f"Erro ao buscar prompt do agent: {e}")
            raise

    def get_active_agents(self) -> List[Agent]:
        """
        Lista todos os agents ativos.

        Returns:
            Lista de agents com status 'active'
        """
        try:
            response = (
                self.client
                .table("agents")
                .select("*")
                .eq("status", "active")
                .order("created_at", desc=True)
                .execute()
            )

            return response.data or []

        except Exception as e:
            logger.error(f"Erro ao listar agents ativos: {e}")
            raise

    # ========================================================================
    # UTILITY METHODS
    # ========================================================================

    def reset_lead(
        self,
        table_name: str,
        remotejid: str
    ) -> Optional[DynamicLead]:
        """
        Reseta um lead para valores iniciais (util para comando /reset).

        Args:
            table_name: Nome da tabela de leads
            remotejid: ID WhatsApp do lead

        Returns:
            Lead resetado ou None se nao encontrado
        """
        try:
            logger.info(f"Resetando lead {remotejid} em {table_name}")

            reset_data = {
                "pipeline_step": "Leads",
                "status": "open",
                "Atendimento_Finalizado": "false",
                "responsavel": "AI",
                "follow_count": 0,
                # Limpar handoff
                "pausar_ia": None,
                "handoff_reason": None,
                "handoff_at": None,
            }

            return self.update_lead_by_remotejid(table_name, remotejid, reset_data)

        except Exception as e:
            logger.error(f"Erro ao resetar lead: {e}")
            raise

    def health_check(self) -> bool:
        """
        Verifica se a conexao com Supabase esta funcionando.

        Returns:
            True se conectado, False caso contrario
        """
        try:
            # Tentar buscar um registro qualquer
            response = (
                self.client
                .table("agents")
                .select("id")
                .limit(1)
                .execute()
            )

            return True

        except Exception as e:
            logger.error(f"Health check falhou: {e}")
            return False

    def get_all_leads(
        self,
        table_name: str,
        limit: int = 1000,
        offset: int = 0,
    ) -> List[DynamicLead]:
        """
        Busca todos os leads de uma tabela com paginacao.

        Args:
            table_name: Nome da tabela de leads (ex: LeadboxCRM_abc123)
            limit: Numero maximo de leads por pagina
            offset: Offset para paginacao

        Returns:
            Lista de leads
        """
        try:
            logger.debug(f"Buscando leads em {table_name} (limit={limit}, offset={offset})")

            response = (
                self.client
                .table(table_name)
                .select("*")
                .order("id", desc=False)
                .range(offset, offset + limit - 1)
                .execute()
            )

            leads = response.data or []
            logger.debug(f"Encontrados {len(leads)} leads em {table_name}")
            return leads

        except Exception as e:
            logger.error(f"Erro ao buscar leads: {e}")
            raise

    def count_leads(self, table_name: str) -> int:
        """
        Conta o total de leads em uma tabela.

        Args:
            table_name: Nome da tabela de leads

        Returns:
            Total de leads
        """
        try:
            response = (
                self.client
                .table(table_name)
                .select("id", count="exact")
                .execute()
            )

            return response.count or 0

        except Exception as e:
            logger.error(f"Erro ao contar leads: {e}")
            return 0

    def get_agent_google_credentials(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        Busca as credenciais Google OAuth2 do agente.

        As credenciais estao armazenadas na coluna google_credentials
        da tabela agents no formato:
        {
            "refresh_token": "1//xxx",
            "access_token": "ya29.xxx",
            "calendar_email": "usuario@gmail.com",
            "expiry_date": 1234567890,
            "token_type": "Bearer",
            "scope": "..."
        }

        Args:
            agent_id: ID do agent

        Returns:
            Dict com credenciais Google ou None se nao configurado
        """
        try:
            logger.debug(f"Buscando google_credentials para agent: {agent_id}")

            response = (
                self.client
                .table("agents")
                .select("google_credentials, google_calendar_id, google_calendar_enabled")
                .eq("id", agent_id)
                .limit(1)
                .execute()
            )

            if response and response.data and len(response.data) > 0:
                agent_data = response.data[0]

                # Verificar se Google Calendar esta habilitado
                if not agent_data.get("google_calendar_enabled", False):
                    logger.debug(f"Google Calendar nao habilitado para agent {agent_id}")
                    return None

                credentials = agent_data.get("google_credentials")
                if not credentials:
                    logger.debug(f"google_credentials vazio para agent {agent_id}")
                    return None

                # Adicionar calendar_id ao resultado
                calendar_id = agent_data.get("google_calendar_id", "primary")
                credentials["calendar_id"] = calendar_id

                logger.debug(
                    f"Credenciais Google encontradas para agent {agent_id}, "
                    f"calendar_email={credentials.get('calendar_email', 'N/A')}"
                )

                return credentials

            logger.debug(f"Agent {agent_id} nao encontrado")
            return None

        except Exception as e:
            logger.error(f"Erro ao buscar google_credentials: {e}")
            return None


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_supabase_service: Optional[SupabaseService] = None


def get_supabase_service() -> SupabaseService:
    """
    Retorna instancia singleton do SupabaseService.

    Returns:
        Instancia do SupabaseService
    """
    global _supabase_service

    if _supabase_service is None:
        _supabase_service = SupabaseService()

    return _supabase_service


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def get_lead_by_phone(table_name: str, telefone: str) -> Optional[DynamicLead]:
    """Wrapper para get_lead_by_phone."""
    return get_supabase_service().get_lead_by_phone(table_name, telefone)


def get_lead_by_remotejid(table_name: str, remotejid: str) -> Optional[DynamicLead]:
    """Wrapper para get_lead_by_remotejid."""
    return get_supabase_service().get_lead_by_remotejid(table_name, remotejid)


def create_lead(table_name: str, data: Dict[str, Any]) -> DynamicLead:
    """Wrapper para create_lead."""
    return get_supabase_service().create_lead(table_name, data)


def update_lead(table_name: str, lead_id: int, data: Dict[str, Any]) -> DynamicLead:
    """Wrapper para update_lead."""
    return get_supabase_service().update_lead(table_name, lead_id, data)


def get_or_create_lead(
    table_name: str,
    remotejid: str,
    default_data: Optional[Dict[str, Any]] = None
) -> DynamicLead:
    """Wrapper para get_or_create_lead."""
    return get_supabase_service().get_or_create_lead(table_name, remotejid, default_data)


def get_conversation_history(
    table_name: str,
    remotejid: str
) -> Optional[ConversationHistory]:
    """Wrapper para get_conversation_history."""
    return get_supabase_service().get_conversation_history(table_name, remotejid)


def add_message_to_history(
    table_name: str,
    remotejid: str,
    role: str,
    text: str
) -> ConversationHistory:
    """Wrapper para add_message_to_history."""
    return get_supabase_service().add_message_to_history(table_name, remotejid, role, text)


def get_agent_config(agent_id: str) -> Optional[Dict[str, Any]]:
    """Wrapper para get_agent_config."""
    return get_supabase_service().get_agent_config(agent_id)


def get_agent_prompt(agent_id: str) -> Optional[str]:
    """Wrapper para get_agent_prompt."""
    return get_supabase_service().get_agent_prompt(agent_id)


def set_lead_paused(
    table_name: str,
    remotejid: str,
    paused: bool,
    reason: Optional[str] = None
) -> Optional[DynamicLead]:
    """Wrapper para set_lead_paused."""
    return get_supabase_service().set_lead_paused(table_name, remotejid, paused, reason)


def is_lead_paused(table_name: str, remotejid: str) -> bool:
    """Wrapper para is_lead_paused."""
    return get_supabase_service().is_lead_paused(table_name, remotejid)


def ensure_session(
    agent_id: str,
    remotejid: str,
    inactivity_hours: int = 4
) -> int:
    """Wrapper para ensure_session."""
    return get_supabase_service().ensure_session(agent_id, remotejid, inactivity_hours)


def get_agent_google_credentials(agent_id: str) -> Optional[Dict[str, Any]]:
    """Wrapper para get_agent_google_credentials."""
    return get_supabase_service().get_agent_google_credentials(agent_id)


def get_all_leads(
    table_name: str,
    limit: int = 1000,
    offset: int = 0,
) -> List[DynamicLead]:
    """Wrapper para get_all_leads."""
    return get_supabase_service().get_all_leads(table_name, limit, offset)


def count_leads(table_name: str) -> int:
    """Wrapper para count_leads."""
    return get_supabase_service().count_leads(table_name)
