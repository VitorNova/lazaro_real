# ╔══════════════════════════════════════════════════════════════╗
# ║  AGENTS METRICS — Metrics and dashboard proxy endpoints    ║
# ╚══════════════════════════════════════════════════════════════╝
"""
Agent metrics, dashboard-config, avatar, specs endpoints.

Currently proxies to agnes-agent on port 3002.
"""

import logging
from typing import Any, Dict

import httpx
from fastapi import APIRouter, Depends

from app.middleware.auth import get_current_user

logger = logging.getLogger(__name__)

metrics_router = APIRouter()


# ---------------------------------------------------------------------------
# 9. GET /api/agents/{agent_id}/metrics - Proxy to agnes-agent
# ---------------------------------------------------------------------------

@metrics_router.get("/{agent_id}/metrics")
async def get_agent_metrics(
    agent_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Get agent metrics (proxied to agnes-agent)."""
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(
                f"http://127.0.0.1:3002/api/agents/{agent_id}/metrics",
                headers={"x-user-id": user["id"]},
            )
            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"[Metrics] agnes-agent returned {response.status_code}")
                return {"error": "Backend error", "status": response.status_code}
    except httpx.ConnectError:
        logger.error("[Metrics] agnes-agent unavailable")
        return {"error": "Backend unavailable"}
    except Exception as e:
        logger.error(f"[Metrics] Error: {e}")
        return {"error": str(e)}
