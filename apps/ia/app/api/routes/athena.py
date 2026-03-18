# apps/ia/app/api/routes/athena.py
"""
Proxy reverso para Athena (Oráculo IA) do agnes-agent.

Endpoints do frontend:
- POST /api/athena/ask -> perguntar ao oráculo
"""

from typing import Any, Dict

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
import httpx
import structlog

from app.middleware.auth import get_current_user

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/athena", tags=["athena"])

AGNES_AGENT_URL = "http://127.0.0.1:3002"


async def proxy_to_agnes(request: Request, path: str = "") -> Response:
    """Proxy genérico para agnes-agent."""
    # agnes-agent usa /api/analytics, frontend usa /api/athena
    target_url = f"{AGNES_AGENT_URL}/api/analytics{path}"

    headers = {}
    if "authorization" in request.headers:
        headers["authorization"] = request.headers["authorization"]
    if "content-type" in request.headers:
        headers["content-type"] = request.headers["content-type"]

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:  # Timeout maior para IA
            body = await request.body()
            response = await client.post(target_url, headers=headers, content=body)

            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.headers.get("content-type", "application/json")
            )

    except httpx.ConnectError:
        logger.error("athena_proxy_connect_error", target=target_url)
        return JSONResponse(status_code=502, content={"error": "Athena unavailable"})
    except Exception as e:
        logger.error("athena_proxy_error", error=str(e))
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/ask")
async def athena_ask(
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """POST /api/athena/ask - Perguntar ao Oráculo (proxied to /api/analytics/ask)"""
    return await proxy_to_agnes(request, "/ask")
