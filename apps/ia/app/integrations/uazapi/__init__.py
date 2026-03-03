# apps/ia/app/integrations/uazapi/__init__.py
"""
Integração UAZAPI - Cliente HTTP para WhatsApp.

Uso:
    from app.integrations.uazapi import UazapiClient, get_uazapi_client

    # Singleton (usa config do settings)
    client = get_uazapi_client()
    result = await client.send_text_message("5511999999999", "Olá!")

    # Instância customizada
    client = UazapiClient(base_url="https://...", api_key="...")

Features:
- Retry automático para erros transientes
- Formatação automática de telefone
- Chunking de mensagens longas
- Indicadores de digitação
"""

from .client import (
    UazapiClient,
    close_uazapi_client,
    create_uazapi_client,
    get_uazapi_client,
    sign_message,
)
from .types import (
    # Constantes
    DEFAULT_TIMEOUT,
    MAX_CHUNK_SIZE,
    MAX_RETRIES,
    RETRY_DELAY_S,
    RETRYABLE_STATUS_CODES,
    # Enums
    InstanceState,
    MediaType,
    MessageStatus,
    ParsedMessageType,
    PresenceType,
    WebhookEventType,
    # Config
    UazapiConfig,
    # Payloads de Envio
    SendTextPayload,
    SendMediaPayload,
    SendAudioPayload,
    SendDocumentPayload,
    SendButtonsPayload,
    SendListPayload,
    SendContactPayload,
    ButtonItem,
    ListSection,
    ListRow,
    # Respostas
    MessageResponse,
    SendMessageResponse,
    InstanceStatus,
    InstanceStatusResponse,
    MediaBase64Response,
    ChunkedSendResult,
    MessageKey,
    # Webhook
    WebhookPayload,
    WebhookData,
    WebhookMessage,
    ContextInfo,
    ImageMessage,
    AudioMessage,
    VideoMessage,
    DocumentMessage,
    StickerMessage,
    LocationMessage,
    ContactMessage,
    ButtonsResponseMessage,
    ListResponseMessage,
    # Mensagem Parseada
    MessageContent,
    MessageReceived,
    QuotedMessage,
    # Campanhas
    CampaignMessage,
    CampaignRequest,
    CampaignResponse,
    CampaignFolder,
    SimpleCampaignRequest,
)

__all__ = [
    # Client
    "UazapiClient",
    "close_uazapi_client",
    "create_uazapi_client",
    "get_uazapi_client",
    "sign_message",
    # Constantes
    "DEFAULT_TIMEOUT",
    "MAX_CHUNK_SIZE",
    "MAX_RETRIES",
    "RETRY_DELAY_S",
    "RETRYABLE_STATUS_CODES",
    # Enums
    "InstanceState",
    "MediaType",
    "MessageStatus",
    "ParsedMessageType",
    "PresenceType",
    "WebhookEventType",
    # Config
    "UazapiConfig",
    # Payloads de Envio
    "SendTextPayload",
    "SendMediaPayload",
    "SendAudioPayload",
    "SendDocumentPayload",
    "SendButtonsPayload",
    "SendListPayload",
    "SendContactPayload",
    "ButtonItem",
    "ListSection",
    "ListRow",
    # Respostas
    "MessageResponse",
    "SendMessageResponse",
    "InstanceStatus",
    "InstanceStatusResponse",
    "MediaBase64Response",
    "ChunkedSendResult",
    "MessageKey",
    # Webhook
    "WebhookPayload",
    "WebhookData",
    "WebhookMessage",
    "ContextInfo",
    "ImageMessage",
    "AudioMessage",
    "VideoMessage",
    "DocumentMessage",
    "StickerMessage",
    "LocationMessage",
    "ContactMessage",
    "ButtonsResponseMessage",
    "ListResponseMessage",
    # Mensagem Parseada
    "MessageContent",
    "MessageReceived",
    "QuotedMessage",
    # Campanhas
    "CampaignMessage",
    "CampaignRequest",
    "CampaignResponse",
    "CampaignFolder",
    "SimpleCampaignRequest",
]
