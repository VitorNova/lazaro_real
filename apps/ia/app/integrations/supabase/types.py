# ==============================================================================
# SUPABASE TYPES
# Tipos, enums e TypedDicts para integracao Supabase
# Baseado na implementacao TypeScript (apps/api/src/services/supabase/types.ts)
# ==============================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TypedDict, Optional, Any, Literal


# ==============================================================================
# ENUMS
# ==============================================================================

class PlanType(str, Enum):
    """Tipo de plano da organizacao."""
    BASIC = "basic"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class UserRole(str, Enum):
    """Role do usuario na organizacao."""
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class AsaasEnvironment(str, Enum):
    """Ambiente do Asaas."""
    SANDBOX = "sandbox"
    PRODUCTION = "production"


class LeadStatus(str, Enum):
    """Status do lead."""
    OPEN = "open"
    QUALIFIED = "qualified"
    CONVERTED = "converted"
    LOST = "lost"
    INACTIVE = "inactive"


class PipelineStep(str, Enum):
    """Etapa do pipeline."""
    LEADS = "Leads"
    CONTACTED = "Contacted"
    QUALIFIED = "Qualified"
    PROPOSAL = "Proposal"
    NEGOTIATION = "Negotiation"
    WON = "Won"
    LOST = "Lost"


class MessageRole(str, Enum):
    """Role da mensagem."""
    USER = "user"
    ASSISTANT = "assistant"
    MODEL = "model"  # Alias para assistant (Gemini usa "model")
    FUNCTION = "function"
    SYSTEM = "system"


class MessageType(str, Enum):
    """Tipo de mensagem."""
    TEXT = "text"
    AUDIO = "audio"
    IMAGE = "image"
    DOCUMENT = "document"
    VIDEO = "video"
    STICKER = "sticker"
    LOCATION = "location"


class ScheduleStatus(str, Enum):
    """Status do agendamento."""
    SCHEDULED = "scheduled"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"


class PaymentStatus(str, Enum):
    """Status do pagamento."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    RECEIVED = "received"
    OVERDUE = "overdue"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"


class WhatsAppProvider(str, Enum):
    """Provedor de WhatsApp."""
    UAZAPI = "uazapi"
    EVOLUTION = "evolution"
    BAILEYS = "baileys"


class AIProvider(str, Enum):
    """Provedor de IA."""
    GEMINI = "gemini"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


# ==============================================================================
# GEMINI MESSAGE FORMAT
# ==============================================================================

class GeminiMessagePart(TypedDict):
    """Parte de uma mensagem Gemini."""
    text: str


class GeminiMessage(TypedDict):
    """Formato de mensagem do Gemini."""
    role: str  # 'user' ou 'model'
    parts: list[GeminiMessagePart]
    timestamp: str


class DianaContext(TypedDict, total=False):
    """Contexto preservado de campanhas Diana."""
    campaign_id: Optional[str]
    prospect_id: Optional[str]
    original_message: Optional[str]
    transferred_at: Optional[str]


class ConversationHistory(TypedDict, total=False):
    """Formato do historico de conversa no Gemini."""
    messages: list[GeminiMessage]
    dianaContext: Optional[DianaContext]


# ==============================================================================
# ORGANIZATION
# ==============================================================================

class Organization(TypedDict):
    """Organizacao."""
    id: str
    name: str
    slug: str
    logo_url: Optional[str]
    plan: str
    is_active: bool
    trial_ends_at: Optional[str]
    webhook_secret: Optional[str]
    created_at: str
    updated_at: str


class OrganizationCreate(TypedDict, total=False):
    """Dados para criar organizacao."""
    name: str
    slug: str
    logo_url: Optional[str]
    plan: str
    is_active: bool
    trial_ends_at: Optional[str]
    webhook_secret: Optional[str]


class OrganizationUpdate(TypedDict, total=False):
    """Dados para atualizar organizacao."""
    name: Optional[str]
    slug: Optional[str]
    logo_url: Optional[str]
    plan: Optional[str]
    is_active: Optional[bool]
    trial_ends_at: Optional[str]
    webhook_secret: Optional[str]


# ==============================================================================
# AGENT
# ==============================================================================

class BusinessHours(TypedDict, total=False):
    """Horario comercial."""
    start: str  # HH:MM
    end: str    # HH:MM
    days: list[str]  # ['seg', 'ter', ...]
    timezone: str


class FollowUpConfig(TypedDict, total=False):
    """Configuracao de follow-up."""
    enabled: bool
    max_attempts: int
    interval_hours: int
    messages: list[str]
    schedule_start: str
    schedule_end: str


class Agent(TypedDict, total=False):
    """Agente de atendimento."""
    id: str
    user_id: str
    organization_id: Optional[str]
    name: str
    status: str
    # WhatsApp
    whatsapp_provider: str
    uazapi_instance_id: Optional[str]
    uazapi_token: Optional[str]
    uazapi_base_url: Optional[str]
    evolution_instance_id: Optional[str]
    evolution_token: Optional[str]
    evolution_base_url: Optional[str]
    # Dynamic tables
    table_leads: str
    table_messages: str
    # AI Config
    ai_provider: str
    gemini_api_key: Optional[str]
    gemini_model: str
    openai_api_key: Optional[str]
    openai_model: Optional[str]
    system_prompt: Optional[str]
    # Business
    business_hours: Optional[dict[str, Any]]
    timezone: str
    pipeline_stages: Optional[list[dict[str, Any]]]
    # Follow-up
    follow_up_enabled: bool
    follow_up_config: Optional[dict[str, Any]]
    # Google Calendar
    google_calendar_id: Optional[str]
    google_credentials: Optional[dict[str, Any]]
    google_accounts: Optional[list[dict[str, Any]]]
    # Asaas
    asaas_api_key: Optional[str]
    asaas_environment: Optional[str]
    # Metadata
    active: bool
    created_at: str
    updated_at: str


class AgentCreate(TypedDict, total=False):
    """Dados para criar agente."""
    user_id: str
    organization_id: Optional[str]
    name: str
    status: str
    whatsapp_provider: str
    uazapi_instance_id: Optional[str]
    uazapi_token: Optional[str]
    table_leads: str
    table_messages: str
    ai_provider: str
    gemini_api_key: Optional[str]
    system_prompt: Optional[str]
    timezone: str


class AgentUpdate(TypedDict, total=False):
    """Dados para atualizar agente."""
    name: Optional[str]
    status: Optional[str]
    system_prompt: Optional[str]
    business_hours: Optional[dict[str, Any]]
    follow_up_enabled: Optional[bool]
    follow_up_config: Optional[dict[str, Any]]
    google_calendar_id: Optional[str]
    google_credentials: Optional[dict[str, Any]]
    active: Optional[bool]


# ==============================================================================
# LEAD (DYNAMIC TABLE - LeadboxCRM_*)
# ==============================================================================

class DynamicLead(TypedDict, total=False):
    """Lead dinamico (tabela LeadboxCRM_*)."""
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


class DynamicLeadCreate(TypedDict, total=False):
    """Dados para criar lead dinamico."""
    nome: Optional[str]
    telefone: Optional[str]
    email: Optional[str]
    empresa: Optional[str]
    remotejid: Optional[str]
    pipeline_step: str
    status: str
    lead_origin: Optional[str]
    responsavel: str


class DynamicLeadUpdate(TypedDict, total=False):
    """Dados para atualizar lead dinamico."""
    nome: Optional[str]
    telefone: Optional[str]
    email: Optional[str]
    empresa: Optional[str]
    pipeline_step: Optional[str]
    status: Optional[str]
    resumo: Optional[str]
    valor: Optional[float]
    close_date: Optional[str]
    Atendimento_Finalizado: Optional[str]
    ultimo_intent: Optional[str]
    follow_count: Optional[int]
    follow_up_opted_out: Optional[bool]
    follow_up_opted_out_reason: Optional[str]
    follow_up_opted_out_at: Optional[str]
    cidade: Optional[str]
    estado: Optional[str]
    timezone: Optional[str]
    next_appointment_at: Optional[str]
    next_appointment_link: Optional[str]
    pausar_ia: Optional[bool]
    updated_date: str


# ==============================================================================
# MESSAGE (DYNAMIC TABLE - leadbox_messages_*)
# ==============================================================================

class LeadMessage(TypedDict, total=False):
    """Mensagem de lead (tabela leadbox_messages_*)."""
    id: str
    creat: str
    remotejid: str
    conversation_history: Optional[dict[str, Any]]
    Msg_model: Optional[str]
    Msg_user: Optional[str]


class LeadMessageCreate(TypedDict, total=False):
    """Dados para criar mensagem de lead."""
    remotejid: str
    conversation_history: dict[str, Any]


class LeadMessageUpdate(TypedDict, total=False):
    """Dados para atualizar mensagem de lead."""
    conversation_history: Optional[dict[str, Any]]
    Msg_model: Optional[str]
    Msg_user: Optional[str]


# ==============================================================================
# LEAD SESSION
# ==============================================================================

class LeadSession(TypedDict, total=False):
    """Sessao de lead."""
    id: str
    agent_id: str
    remotejid: str
    started_at: str
    ended_at: Optional[str]
    session_number: int
    created_at: str


# ==============================================================================
# LEAD (STANDARD TABLE)
# ==============================================================================

class Lead(TypedDict, total=False):
    """Lead padrao (tabela leads)."""
    id: str
    organization_id: str
    remote_jid: str
    lead_origin: Optional[str]
    diana_prospect_id: Optional[str]
    status: str
    pipeline_step: str
    atendimento_finalizado: bool
    follow_count: int
    follow_01: Optional[str]
    follow_02: Optional[str]
    follow_03: Optional[str]
    follow_04: Optional[str]
    follow_05: Optional[str]
    follow_06: Optional[str]
    follow_07: Optional[str]
    follow_08: Optional[str]
    follow_09: Optional[str]
    nome: Optional[str]
    empresa: Optional[str]
    telefone: Optional[str]
    email: Optional[str]
    cidade: Optional[str]
    estado: Optional[str]
    timezone: Optional[str]
    created_at: str
    updated_at: str


# ==============================================================================
# MESSAGE (STANDARD TABLE)
# ==============================================================================

class Message(TypedDict, total=False):
    """Mensagem padrao (tabela messages)."""
    id: str
    organization_id: str
    remote_jid: str
    lead_id: Optional[str]
    role: str
    type: str
    content: str
    created_at: str
    updated_at: str


# ==============================================================================
# SCHEDULE
# ==============================================================================

class Schedule(TypedDict, total=False):
    """Agendamento."""
    id: str
    agent_id: str
    remote_jid: str
    lead_id: Optional[str]
    scheduled_at: str
    status: str
    event_id: Optional[str]
    event_link: Optional[str]
    meet_link: Optional[str]
    notes: Optional[str]
    created_at: str
    updated_at: str


# ==============================================================================
# PAYMENT
# ==============================================================================

class Payment(TypedDict, total=False):
    """Pagamento."""
    id: str
    organization_id: str
    lead_id: Optional[str]
    remote_jid: str
    asaas_id: Optional[str]
    status: str
    amount: float
    due_at: str
    paid_at: Optional[str]
    description: Optional[str]
    invoice_url: Optional[str]
    created_at: str
    updated_at: str


# ==============================================================================
# INTEGRATION
# ==============================================================================

class GoogleCredentials(TypedDict, total=False):
    """Credenciais Google OAuth."""
    access_token: str
    refresh_token: str
    token_type: str
    expiry_date: int


class GoogleAccountConfig(TypedDict, total=False):
    """Configuracao de conta Google."""
    email: str
    credentials: dict[str, Any]
    calendar_id: str
    work_days: Optional[dict[str, bool]]
    morning_enabled: Optional[bool]
    morning_start: Optional[str]
    morning_end: Optional[str]
    afternoon_enabled: Optional[bool]
    afternoon_start: Optional[str]
    afternoon_end: Optional[str]
    meeting_duration: Optional[int]


class Integration(TypedDict, total=False):
    """Integracao."""
    id: str
    organization_id: str
    uazapi_base_url: Optional[str]
    uazapi_instance: Optional[str]
    uazapi_api_key: Optional[str]
    evolution_base_url: Optional[str]
    evolution_instance: Optional[str]
    evolution_token: Optional[str]
    asaas_api_key: Optional[str]
    asaas_environment: str
    google_credentials: Optional[dict[str, Any]]
    google_calendar_id: Optional[str]
    google_accounts: Optional[list[dict[str, Any]]]
    created_at: str
    updated_at: str


# ==============================================================================
# AGENT CONFIG
# ==============================================================================

class AgentConfig(TypedDict, total=False):
    """Configuracao detalhada do agente."""
    id: str
    agent_id: str
    ai_temperature: float
    response_size: str
    split_messages: bool
    max_chars_per_message: int
    typing_simulation: bool
    typing_delay_ms: int
    created_at: str
    updated_at: str


# ==============================================================================
# CONTROLE (DYNAMIC TABLE - Controle_*)
# ==============================================================================

class Controle(TypedDict, total=False):
    """Controle dinamico (tabela Controle_*)."""
    id: int
    remotejid: str
    status: str
    last_interaction: Optional[str]
    notes: Optional[str]
    created_at: str
    updated_at: str


# ==============================================================================
# QUERY RESULT TYPES
# ==============================================================================

@dataclass
class QueryResult:
    """Resultado de uma query."""
    data: Optional[list[dict[str, Any]]] = None
    error: Optional[str] = None
    count: Optional[int] = None

    @property
    def success(self) -> bool:
        return self.error is None

    @property
    def first(self) -> Optional[dict[str, Any]]:
        if self.data and len(self.data) > 0:
            return self.data[0]
        return None


# ==============================================================================
# ERROR CODES
# ==============================================================================

class SupabaseErrorCode:
    """Codigos de erro comuns do Supabase/PostgREST."""
    NOT_FOUND = "PGRST116"
    UNIQUE_VIOLATION = "23505"
    FOREIGN_KEY_VIOLATION = "23503"
    CHECK_VIOLATION = "23514"
    NOT_NULL_VIOLATION = "23502"
