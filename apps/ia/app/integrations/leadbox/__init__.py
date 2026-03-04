# ==============================================================================
# LEADBOX INTEGRATION
# Integracao completa com Leadbox (Cliente HTTP + Dispatcher + Types)
# ==============================================================================

"""
Leadbox Integration para Lazaro-v2.

Este modulo fornece:
- LeadboxClient: Cliente HTTP para API do Leadbox
- LeadboxDispatcher: Dispatch inteligente (criar/mover ticket)
- Types: Tipos, enums e helpers para tipagem forte

Exemplo de uso basico:
    from app.integrations.leadbox import (
        create_leadbox_client,
        create_dispatcher,
        LeadboxCredentials,
        DispatchResult,
        QUEUE_BILLING,
        QUEUE_MAINTENANCE,
    )

    # Criar cliente a partir de config
    client = create_leadbox_client(handoff_config)
    if client:
        # Transferir para departamento
        result = await client.transfer_to_department(
            ticket_id=12345,
            queue_id=QUEUE_BILLING,
            user_id=10,
        )

        # Verificar fila atual
        queue_info = await client.get_current_queue(phone="5511999999999")

    # Dispatch inteligente (cria ou move ticket)
    credentials = LeadboxCredentials.from_config(handoff_config)
    dispatcher = create_dispatcher(credentials)

    result = await dispatcher.dispatch(
        phone="5511999999999",
        queue_id=QUEUE_BILLING,
        message="Mensagem inicial",
    )

    if result["success"]:
        if result["ticket_existed"]:
            # Ticket movido - enviar mensagem via UAZAPI
            pass
        else:
            # Ticket criado - PUSH ja enviou a mensagem
            pass

Arquitetura:
- types.py: Tipos, enums, constantes, helpers
- client.py: LeadboxClient (HTTP client)
- dispatch.py: LeadboxDispatcher (dispatch inteligente)
"""

# ==============================================================================
# TYPES
# ==============================================================================

from .types import (
    # Constantes - Filas
    QUEUE_BILLING,
    QUEUE_MAINTENANCE,
    QUEUE_GENERIC,
    # Enums
    TicketStatus,
    WebhookEvent,
    SendType,
    MediaType,
    # Config Types
    LeadboxConfig,
    DepartmentConfig,
    DispatchDepartment,
    ContextInjection,
    HandoffTriggers,
    # Result Types
    TransferResult,
    DispatchResult,
    QueueInfo,
    SendMessageResult,
    # Webhook Types
    Contact,
    Ticket,
    Message,
    WebhookPayload,
    # Lead State
    LeadboxLeadState,
    # Dataclasses
    LeadboxCredentials,
    # Helpers
    format_phone,
    is_ia_queue,
    extract_webhook_data,
)

# ==============================================================================
# CLIENT
# ==============================================================================

from .client import (
    LeadboxClient,
    create_leadbox_client,
    create_leadbox_client_from_credentials,
)

# ==============================================================================
# DISPATCHER
# ==============================================================================

from .dispatch import (
    LeadboxDispatcher,
    create_dispatcher,
    create_dispatcher_from_config,
    leadbox_push_silent,
)

# ==============================================================================
# EXPORTS
# ==============================================================================

__all__ = [
    # Constantes - Filas
    "QUEUE_BILLING",
    "QUEUE_MAINTENANCE",
    "QUEUE_GENERIC",
    # Enums
    "TicketStatus",
    "WebhookEvent",
    "SendType",
    "MediaType",
    # Config Types
    "LeadboxConfig",
    "DepartmentConfig",
    "DispatchDepartment",
    "ContextInjection",
    "HandoffTriggers",
    # Result Types
    "TransferResult",
    "DispatchResult",
    "QueueInfo",
    "SendMessageResult",
    # Webhook Types
    "Contact",
    "Ticket",
    "Message",
    "WebhookPayload",
    # Lead State
    "LeadboxLeadState",
    # Dataclasses
    "LeadboxCredentials",
    # Helpers
    "format_phone",
    "is_ia_queue",
    "extract_webhook_data",
    # Client
    "LeadboxClient",
    "create_leadbox_client",
    "create_leadbox_client_from_credentials",
    # Dispatcher
    "LeadboxDispatcher",
    "create_dispatcher",
    "create_dispatcher_from_config",
    "leadbox_push_silent",
]
