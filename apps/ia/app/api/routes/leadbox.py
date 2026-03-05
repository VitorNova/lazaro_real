"""
Leadbox webhook endpoint for CRM integration.

This module provides the FastAPI router for Leadbox webhooks.
All processing logic is delegated to:
- handlers/leadbox_handler.py: Event handlers and orchestration
- services/lead_intake_service.py: Lead processing services

Routes:
- POST /webhooks/leadbox: Process Leadbox events

Validacao Pydantic adicionada na Fase 5.
"""

from typing import Any, Dict
import json as _json

import structlog
from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import ValidationError

from app.api.handlers.leadbox_handler import (
    handle_new_message,
    handle_ticket_closed,
    handle_queue_change,
)
from app.api.models.webhook_models import LeadboxWebhookPayload

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["webhooks"])

# Events that don't need processing
IGNORED_EVENTS = {"AckMessage", "FinishedTicketHistoricMessages"}


@router.post("/webhooks/leadbox")
async def leadbox_webhook(request: Request, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """
    Webhook endpoint para receber eventos do Leadbox.
    Atualiza current_queue_id e pausa/reativa IA baseado na fila.

    REGRA: Se queue != queue_ia do agente, PAUSA imediatamente.

    Events handled:
    - NewMessage: Process incoming messages (human capture or AI processing)
    - QueueChange: Pause/reactivate AI based on queue
    - TicketClosed: Reset lead state when ticket closes

    Events ignored:
    - AckMessage: Message acknowledgment
    - FinishedTicketHistoricMessages: Historical messages loaded

    Validado com Pydantic (warning only, nao rejeita).
    """
    body = await request.json()

    # Validar com Pydantic (warning only)
    validated_payload = None
    try:
        validated_payload = LeadboxWebhookPayload(**body)
    except ValidationError as e:
        logger.warning("[LEADBOX WEBHOOK] Validacao Pydantic falhou: %s", e.errors())

    event_type = body.get("event") or body.get("type") or "unknown"
    logger.info("[LEADBOX WEBHOOK] Evento recebido: %s", event_type)

    # ==========================================================================
    # FILTRAR EVENTOS DESNECESSÁRIOS
    # ==========================================================================
    if event_type in IGNORED_EVENTS:
        logger.debug("[LEADBOX WEBHOOK] Evento ignorado: %s", event_type)
        return {"status": "ignored", "reason": f"event_{event_type}"}

    # Log payload para diagnóstico (primeiros 800 chars)
    logger.info("[LEADBOX WEBHOOK] Payload: %s", _json.dumps(body, default=str)[:800])

    # ==========================================================================
    # PROCESSAR MENSAGEM DO LEAD (substitui webhook UAZAPI)
    # ==========================================================================
    if event_type == "NewMessage":
        await handle_new_message(body, background_tasks)

    # Extrair dados do ticket/mensagem
    message = body.get("message") or body.get("data", {}).get("message") or {}
    ticket = message.get("ticket") or body.get("ticket") or body.get("data", {}).get("ticket") or {}
    contact = ticket.get("contact") or message.get("contact") or body.get("contact") or {}

    queue_id = ticket.get("queueId") or message.get("queueId")
    user_id = ticket.get("userId") or message.get("userId")
    ticket_id = ticket.get("id") or message.get("ticketId")
    phone = contact.get("number", "").replace("+", "").strip()

    # DEBUG: Log raw user_id extraction
    logger.debug(
        "[LEADBOX DEBUG RAW] ticket.userId=%r | message.userId=%r | final user_id=%r (type=%s)",
        ticket.get("userId"), message.get("userId"), user_id, type(user_id).__name__ if user_id else "None"
    )

    # Extrair tenant_id do payload
    payload_tenant_id = body.get("tenantId") or body.get("tenant_id")
    if not payload_tenant_id:
        payload_tenant_id = ticket.get("tenantId") or ticket.get("tenant_id")

    # ==========================================================================
    # VERIFICAR SE TICKET FOI FECHADO
    # ==========================================================================
    ticket_status = ticket.get("status", "")
    closed_at = ticket.get("closedAt")

    if phone and (ticket_status == "closed" or closed_at is not None):
        return await handle_ticket_closed(phone, ticket_id, ticket_status, closed_at, payload_tenant_id)

    # ==========================================================================
    # PROCESSAR MUDANÇA DE FILA
    # ==========================================================================
    if phone and queue_id:
        return await handle_queue_change(
            phone, queue_id, user_id, ticket_id, payload_tenant_id, event_type
        )
    else:
        logger.warning("[LEADBOX WEBHOOK] Payload sem phone ou queueId: phone=%s, queue=%s", phone, queue_id)
        logger.warning("[LEADBOX WEBHOOK] Keys no payload: %s", list(body.keys())[:10])

    return {"status": "ok", "event": event_type}


# =============================================================================
# BACKWARD COMPATIBILITY - Re-export functions from new locations
# =============================================================================
# These re-exports ensure existing code importing from leadbox.py continues to work
from app.api.handlers.leadbox_handler import (
    handle_new_message as _handle_new_message,
    handle_ticket_closed as _handle_ticket_closed,
    handle_queue_change as _handle_queue_change,
)
from app.api.services.lead_intake_service import (
    capture_human_message as _capture_human_message,
    process_lead_message as _process_lead_message,
    create_lead_if_missing as _create_lead_if_missing,
    inject_agnes_message as _inject_agnes_message,
    inject_return_context as _inject_return_context,
)
