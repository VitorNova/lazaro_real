# ==============================================================================
# SUPABASE INTEGRATION
# Integracao completa com Supabase (Cliente + Repositories)
# Baseado na implementacao TypeScript (apps/api/src/services/supabase/)
# ==============================================================================

"""
Supabase Integration para Lazaro-v2.

Este modulo fornece:
- SupabaseClient: Cliente singleton com acesso administrativo
- Repositories: Padrao Repository para acesso ao banco
- Types: Tipos e enums para tipagem forte

Exemplo de uso basico:
    from app.integrations.supabase import (
        get_supabase_client,
        table,
        agents_repository,
        dynamic_repository,
    )

    # Acesso direto a tabela
    result = table("agents").select("*").eq("id", agent_id).execute()

    # Usando repository (recomendado)
    agent = await agents_repository.find_by_id(agent_id)

    # Tabelas dinamicas
    lead = await dynamic_repository.get_or_create_lead(
        table_name="LeadboxCRM_abc123",
        remotejid="5511999999999@s.whatsapp.net",
        default_data={"nome": "Joao", "telefone": "5511999999999"},
    )

    # Historico de conversa
    history = await dynamic_repository.get_conversation_history(
        table_name="leadbox_messages_abc123",
        remotejid="5511999999999@s.whatsapp.net",
    )

Arquitetura:
- client.py: Cliente singleton (SupabaseClient)
- types.py: Tipos, enums, TypedDicts
- repositories/: Padrao Repository
  - base.py: Classe base com CRUD generico
  - agents.py: AgentsRepository (tabela agents)
  - dynamic.py: DynamicRepository (tabelas dinamicas)
"""

# ==============================================================================
# TYPES
# ==============================================================================

from .types import (
    # Enums
    PlanType,
    UserRole,
    AsaasEnvironment,
    LeadStatus,
    PipelineStep,
    MessageRole,
    MessageType,
    ScheduleStatus,
    PaymentStatus,
    WhatsAppProvider,
    AIProvider,
    # Gemini Message
    GeminiMessagePart,
    GeminiMessage,
    DianaContext,
    ConversationHistory,
    # Organization
    Organization,
    OrganizationCreate,
    OrganizationUpdate,
    # Agent
    BusinessHours,
    FollowUpConfig,
    Agent,
    AgentCreate,
    AgentUpdate,
    # Dynamic Lead
    DynamicLead,
    DynamicLeadCreate,
    DynamicLeadUpdate,
    # Lead Message
    LeadMessage,
    LeadMessageCreate,
    LeadMessageUpdate,
    # Lead Session
    LeadSession,
    # Standard Lead
    Lead,
    # Message
    Message,
    # Schedule
    Schedule,
    # Payment
    Payment,
    # Integration
    GoogleCredentials,
    GoogleAccountConfig,
    Integration,
    # Agent Config
    AgentConfig,
    # Controle
    Controle,
    # Query Result
    QueryResult,
    SupabaseErrorCode,
)

# ==============================================================================
# CLIENT
# ==============================================================================

from .client import (
    SupabaseClient,
    get_supabase_client,
    get_supabase_admin,
    table,
    rpc,
    handle_query_result,
    handle_query_list,
    is_not_found_error,
    is_unique_violation,
)

# ==============================================================================
# REPOSITORIES
# ==============================================================================

from .repositories import (
    BaseRepository,
    AgentsRepository,
    agents_repository,
    DynamicRepository,
    dynamic_repository,
)

# ==============================================================================
# EXPORTS
# ==============================================================================

__all__ = [
    # Enums
    "PlanType",
    "UserRole",
    "AsaasEnvironment",
    "LeadStatus",
    "PipelineStep",
    "MessageRole",
    "MessageType",
    "ScheduleStatus",
    "PaymentStatus",
    "WhatsAppProvider",
    "AIProvider",
    # Gemini Message
    "GeminiMessagePart",
    "GeminiMessage",
    "DianaContext",
    "ConversationHistory",
    # Organization
    "Organization",
    "OrganizationCreate",
    "OrganizationUpdate",
    # Agent
    "BusinessHours",
    "FollowUpConfig",
    "Agent",
    "AgentCreate",
    "AgentUpdate",
    # Dynamic Lead
    "DynamicLead",
    "DynamicLeadCreate",
    "DynamicLeadUpdate",
    # Lead Message
    "LeadMessage",
    "LeadMessageCreate",
    "LeadMessageUpdate",
    # Lead Session
    "LeadSession",
    # Standard Lead
    "Lead",
    # Message
    "Message",
    # Schedule
    "Schedule",
    # Payment
    "Payment",
    # Integration
    "GoogleCredentials",
    "GoogleAccountConfig",
    "Integration",
    # Agent Config
    "AgentConfig",
    # Controle
    "Controle",
    # Query helpers
    "QueryResult",
    "SupabaseErrorCode",
    # Client
    "SupabaseClient",
    "get_supabase_client",
    "get_supabase_admin",
    "table",
    "rpc",
    "handle_query_result",
    "handle_query_list",
    "is_not_found_error",
    "is_unique_violation",
    # Repositories
    "BaseRepository",
    "AgentsRepository",
    "agents_repository",
    "DynamicRepository",
    "dynamic_repository",
]
