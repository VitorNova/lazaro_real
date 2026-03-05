"""
Billing Services - Servicos de cobranca automatica.

Modulos disponiveis:
- billing_formatter: Formatacao de mensagens de cobranca
- billing_rules: Regras de negocio (elegibilidade, agentes)
- billing_notifier: Controle de notificacoes (claim, save, DLQ)
- lead_ensurer: Garantia de leads e historico
- payment_fetcher: Busca de pagamentos (API + Supabase)
- customer_phone: Resolucao de telefone
- billing_job_lock: Lock distribuido para job
- billing_orchestrator: Logica principal de processamento
"""

# Formatter
from .billing_formatter import (
    format_brl,
    format_message,
    format_consolidated_message,
    get_overdue_template,
    get_consolidated_overdue_template,
)

# Rules
from .billing_rules import (
    should_skip_payment,
    get_agents_with_asaas,
)

# Notifier
from .billing_notifier import (
    claim_notification,
    save_cobranca_enviada,
    update_notification_status,
    save_to_dead_letter_queue,
    get_sent_count,
    mask_customer_name,
    mask_phone,
)

# Lead ensurer
from .lead_ensurer import (
    ensure_lead_exists,
    ensure_message_record_exists,
    save_message_to_conversation_history,
    phone_to_remotejid,
)

# Payment fetcher
from .payment_fetcher import (
    fetch_payments_from_asaas,
    fetch_payments_with_fallback,
    sync_payments_to_cache,
    enrich_payments_from_api,
    get_pending_payments_by_due_date,
    get_pending_payments_today,
    get_overdue_payments,
)

# Customer phone
from .customer_phone import (
    get_customer_phone,
)

# Job lock
from .billing_job_lock import (
    acquire_billing_lock,
    release_billing_lock,
    is_billing_job_running,
)

# Orchestrator
from .billing_orchestrator import (
    process_agent_billing,
)

__all__ = [
    # Formatter
    "format_brl",
    "format_message",
    "format_consolidated_message",
    "get_overdue_template",
    "get_consolidated_overdue_template",
    # Rules
    "should_skip_payment",
    "get_agents_with_asaas",
    # Notifier
    "claim_notification",
    "save_cobranca_enviada",
    "update_notification_status",
    "save_to_dead_letter_queue",
    "get_sent_count",
    "mask_customer_name",
    "mask_phone",
    # Lead ensurer
    "ensure_lead_exists",
    "ensure_message_record_exists",
    "save_message_to_conversation_history",
    "phone_to_remotejid",
    # Payment fetcher
    "fetch_payments_from_asaas",
    "fetch_payments_with_fallback",
    "sync_payments_to_cache",
    "enrich_payments_from_api",
    "get_pending_payments_by_due_date",
    "get_pending_payments_today",
    "get_overdue_payments",
    # Customer phone
    "get_customer_phone",
    # Job lock
    "acquire_billing_lock",
    "release_billing_lock",
    "is_billing_job_running",
    # Orchestrator
    "process_agent_billing",
]
