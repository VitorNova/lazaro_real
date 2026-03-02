# webhooks package

from app.webhooks.mensagens import (
    router as whatsapp_router,
    WhatsAppWebhookHandler,
    get_webhook_handler,
)

__all__ = [
    "whatsapp_router",
    "WhatsAppWebhookHandler",
    "get_webhook_handler",
]
