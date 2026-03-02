"""
Services - Integrações e serviços externos.
"""

from .redis import (
    RedisService,
    get_redis_service,
    close_redis_service,
    BUFFER_DELAY_SECONDS,
    DEFAULT_TTL_SECONDS,
    LOCK_TTL_SECONDS,
)
from .ia_gemini import (
    GeminiService,
    get_gemini_service,
    reset_gemini_service,
)
from .whatsapp_api import (
    UazapiService,
    get_uazapi_service,
    close_uazapi_service,
    MediaType,
    MessageResponse,
    InstanceStatus,
    send_text_message,
    send_media_message,
    mark_as_read,
    get_instance_status,
    send_typing,
    is_connected,
)
from .agenda import (
    CalendarService,
    CalendarServiceError,
    get_calendar_service,
    reset_calendar_service,
)
from .leadbox import (
    LeadboxService,
    LeadboxConfig,
    TransferResult,
    create_leadbox_service,
    transfer_to_department,
)
from .gateway_pagamento import (
    AsaasService,
    get_asaas_service,
    create_asaas_service,
)

__all__ = [
    # Redis
    "RedisService",
    "get_redis_service",
    "close_redis_service",
    "BUFFER_DELAY_SECONDS",
    "DEFAULT_TTL_SECONDS",
    "LOCK_TTL_SECONDS",
    # Gemini
    "GeminiService",
    "get_gemini_service",
    "reset_gemini_service",
    # UAZAPI
    "UazapiService",
    "get_uazapi_service",
    "close_uazapi_service",
    "MediaType",
    "MessageResponse",
    "InstanceStatus",
    "send_text_message",
    "send_media_message",
    "mark_as_read",
    "get_instance_status",
    "send_typing",
    "is_connected",
    # Calendar
    "CalendarService",
    "CalendarServiceError",
    "get_calendar_service",
    "reset_calendar_service",
    # Leadbox
    "LeadboxService",
    "LeadboxConfig",
    "TransferResult",
    "create_leadbox_service",
    "transfer_to_department",
    # Asaas
    "AsaasService",
    "get_asaas_service",
    "create_asaas_service",
]
