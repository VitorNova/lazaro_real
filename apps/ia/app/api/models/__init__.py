"""
API Models - Pydantic models para validacao de payloads.

Modulos:
- webhook_models: Modelos para validacao de webhooks externos
"""

from .webhook_models import (
    # WhatsApp/UAZAPI
    WhatsAppMessageKey,
    WhatsAppMessageData,
    WhatsAppWebhookPayload,
    WhatsAppTestPayload,
    # Asaas
    AsaasPayment,
    AsaasCustomer,
    AsaasSubscription,
    AsaasWebhookPayload,
    AsaasReprocessContractPayload,
    # Leadbox
    LeadboxContact,
    LeadboxTicket,
    LeadboxMessage,
    LeadboxWebhookPayload,
)

__all__ = [
    # WhatsApp/UAZAPI
    "WhatsAppMessageKey",
    "WhatsAppMessageData",
    "WhatsAppWebhookPayload",
    "WhatsAppTestPayload",
    # Asaas
    "AsaasPayment",
    "AsaasCustomer",
    "AsaasSubscription",
    "AsaasWebhookPayload",
    "AsaasReprocessContractPayload",
    # Leadbox
    "LeadboxContact",
    "LeadboxTicket",
    "LeadboxMessage",
    "LeadboxWebhookPayload",
]
