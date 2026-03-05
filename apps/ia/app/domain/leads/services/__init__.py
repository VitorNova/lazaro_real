"""
Leads Services - Servicos de follow-up automatico (Salvador).

Modulos disponiveis:
- opt_out_detector: Deteccao de pedidos de descadastramento
- salvador_config: Configuracao e normalizacao do agente Salvador
- follow_up_throttle: Rate limiting via Redis
- lead_classifier: Classificacao IA para decidir se envia follow-up
- follow_up_message_generator: Geracao de mensagens via Gemini
- follow_up_eligibility: Busca de agentes e leads elegiveis
- follow_up_recorder: Registro de follow-ups enviados
- follow_up_reset: Reset de contadores quando lead responde
- follow_up_orchestrator: Logica principal de processamento
"""

# Opt-out detector
from .opt_out_detector import (
    detect_opt_out,
    OPT_OUT_PATTERNS,
)

# Salvador config
from .salvador_config import (
    get_salvador_config,
    is_within_schedule,
    FALLBACK_MESSAGES,
    DEFAULT_INACTIVITY_STEPS,
    DEFAULT_LIMITS,
    DEFAULT_SCHEDULE,
    BLOCKED_PIPELINE_STEPS,
    WEEKDAY_NAMES,
)

# Follow-up throttle
from .follow_up_throttle import (
    can_send_follow_up,
    record_follow_up,
    clear_lead_cooldown,
    get_redis_client,
)

# Lead classifier
from .lead_classifier import (
    load_conversation_history,
    build_conversation_summary,
    classify_lead_for_follow_up,
    CLASSIFIER_PROMPT,
)

# Follow-up message generator
from .follow_up_message_generator import (
    generate_follow_up_message,
    get_lead_first_name,
)

# Follow-up eligibility
from .follow_up_eligibility import (
    get_agents_with_follow_up,
    get_eligible_leads,
    resolve_shared_whatsapp,
    parse_iso_datetime,
)

# Follow-up recorder
from .follow_up_recorder import (
    record_follow_up_notification,
    log_follow_up_history,
    update_lead_follow_up,
    save_follow_up_to_history,
)

# Follow-up reset
from .follow_up_reset import (
    reset_follow_up_on_lead_response,
)

# Follow-up orchestrator
from .follow_up_orchestrator import (
    process_agent_follow_up,
)

__all__ = [
    # Opt-out detector
    "detect_opt_out",
    "OPT_OUT_PATTERNS",
    # Salvador config
    "get_salvador_config",
    "is_within_schedule",
    "FALLBACK_MESSAGES",
    "DEFAULT_INACTIVITY_STEPS",
    "DEFAULT_LIMITS",
    "DEFAULT_SCHEDULE",
    "BLOCKED_PIPELINE_STEPS",
    "WEEKDAY_NAMES",
    # Follow-up throttle
    "can_send_follow_up",
    "record_follow_up",
    "clear_lead_cooldown",
    "get_redis_client",
    # Lead classifier
    "load_conversation_history",
    "build_conversation_summary",
    "classify_lead_for_follow_up",
    "CLASSIFIER_PROMPT",
    # Follow-up message generator
    "generate_follow_up_message",
    "get_lead_first_name",
    # Follow-up eligibility
    "get_agents_with_follow_up",
    "get_eligible_leads",
    "resolve_shared_whatsapp",
    "parse_iso_datetime",
    # Follow-up recorder
    "record_follow_up_notification",
    "log_follow_up_history",
    "update_lead_follow_up",
    "save_follow_up_to_history",
    # Follow-up reset
    "reset_follow_up_on_lead_response",
    # Follow-up orchestrator
    "process_agent_follow_up",
]
