"""
Rotas FastAPI para webhook WhatsApp.

Endpoints:
- POST /webhook/whatsapp - Recebe webhooks UAZAPI
- GET /webhook/whatsapp - Health check
- POST /webhook/whatsapp/test - Teste de webhook

Extraido de: apps/ia/app/webhooks/mensagens.py (Fase 2.16)
"""

from datetime import datetime
from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])


# Referencia ao handler do mensagens.py (sera substituido por orchestrator)
# Por enquanto, importa do modulo original para manter compatibilidade
_webhook_handler = None


def _get_webhook_handler():
    """
    Retorna instancia do handler de webhook.

    Lazy import para evitar circular dependencies.
    """
    global _webhook_handler
    if _webhook_handler is None:
        from app.webhooks.mensagens import get_webhook_handler
        _webhook_handler = get_webhook_handler()
    return _webhook_handler


@router.post("/whatsapp")
async def webhook_whatsapp_post(
    request: Request,
    background_tasks: BackgroundTasks,
) -> Dict[str, Any]:
    """
    Endpoint POST para receber webhooks do WhatsApp (UAZAPI).

    Processa a mensagem em background e retorna imediatamente.

    Args:
        request: Request do FastAPI
        background_tasks: BackgroundTasks para processamento async

    Returns:
        Dict com status do processamento
    """
    try:
        # Parsear body
        body = await request.json()

        logger.debug(
            "webhook_received",
            body_preview=str(body)[:200],
        )

        # Verificar tipo de evento
        event_type = body.get("event") or body.get("type")

        # Ignorar eventos que nao sao mensagens
        if event_type and event_type not in ["messages.upsert", "message", "messages"]:
            logger.debug("event_ignored", event_type=event_type)
            return {"status": "ignored", "reason": f"event_type_{event_type}"}

        # Processar mensagem
        handler = _get_webhook_handler()
        result = await handler.handle_message(body, background_tasks)

        return result

    except Exception as e:
        logger.error("webhook_error", error=str(e), exc_info=True)
        return {"status": "error", "message": str(e)}


@router.get("/whatsapp")
async def webhook_whatsapp_get() -> Dict[str, Any]:
    """
    Endpoint GET para verificacao do webhook.

    Usado pela UAZAPI para verificar se o endpoint esta ativo.

    Returns:
        Dict com status de verificacao
    """
    return {
        "status": "ok",
        "service": "agente-ia",
        "webhook": "whatsapp",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.post("/whatsapp/test")
async def webhook_whatsapp_test(request: Request) -> Dict[str, Any]:
    """
    Endpoint de teste para simular mensagens do webhook.

    Util para desenvolvimento e debugging.

    Args:
        request: Request com payload de teste

    Returns:
        Dict com resultado do processamento
    """
    try:
        body = await request.json()

        # Validar campos minimos
        required = ["phone", "text"]
        for field in required:
            if field not in body:
                raise HTTPException(
                    status_code=400,
                    detail=f"Campo obrigatorio: {field}",
                )

        # Montar payload no formato UAZAPI
        webhook_data = {
            "event": "messages.upsert",
            "instanceId": body.get("instance_id", "test-instance"),
            "data": {
                "key": {
                    "remoteJid": f"{body['phone']}@s.whatsapp.net",
                    "fromMe": False,
                    "id": f"test_{datetime.utcnow().timestamp()}",
                },
                "message": {
                    "conversation": body["text"],
                },
                "pushName": body.get("name", "Teste"),
                "messageTimestamp": datetime.utcnow().isoformat(),
            },
        }

        # Processar
        handler = _get_webhook_handler()
        result = await handler.handle_message(webhook_data)

        return {"test": True, "result": result}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("webhook_test_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
