"""
Dynamic webhook routes for WhatsApp messages.

This module provides:
- POST /webhooks/dynamic: Process incoming WhatsApp messages
- GET /webhooks/dynamic: Webhook verification endpoint
"""

from datetime import datetime
from typing import Any, Dict

import structlog
from fastapi import APIRouter, BackgroundTasks, Request

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/dynamic")
async def webhooks_dynamic_post(
    request: Request,
    background_tasks: BackgroundTasks,
) -> Dict[str, Any]:
    """
    Main webhook endpoint for WhatsApp messages (UAZAPI).

    This is the primary endpoint that matches the agnes-agent URL pattern.
    Processes messages and routes them to the appropriate handler.
    """
    from app.webhooks.mensagens import get_webhook_handler

    try:
        body = await request.json()

        # DEBUG: Ver o que está chegando
        event_type = body.get("event") or body.get("type") or body.get("EventType")
        logger.debug("[WEBHOOK DEBUG] Event: %s, Payload preview: %s", event_type, str(body)[:300])

        # Ignore non-message events
        if event_type and event_type not in ["messages.upsert", "message", "messages"]:
            logger.debug("Event ignored", event_type=event_type)
            return {"status": "ignored", "reason": f"event_type_{event_type}"}

        # Process message
        handler = get_webhook_handler()
        result = await handler.handle_message(body, background_tasks)

        return result

    except Exception as e:
        logger.error("Error in /webhooks/dynamic", error=str(e), exc_info=True)
        return {"status": "error", "message": str(e)}


@router.get("/dynamic")
async def webhooks_dynamic_get() -> Dict[str, Any]:
    """
    Webhook verification endpoint.

    Used by UAZAPI to verify the webhook is active.
    """
    return {
        "status": "ok",
        "service": "agente-ia",
        "webhook": "dynamic",
        "timestamp": datetime.utcnow().isoformat(),
    }
