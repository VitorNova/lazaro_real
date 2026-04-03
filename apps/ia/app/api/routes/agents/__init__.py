# ╔══════════════════════════════════════════════════════════════╗
# ║  AGENTS — Unified router combining CRUD, connection, metrics║
# ╚══════════════════════════════════════════════════════════════╝
"""
Agents API package.

Combines sub-routers into a single ``agents_router`` that is registered
with ``app.include_router(agents_router, prefix="/api", tags=["agents"])``.
"""

from fastapi import APIRouter

from app.api.routes.agents.connection import connection_router
from app.api.routes.agents.crud import crud_router
from app.api.routes.agents.metrics import metrics_router

agents_router = APIRouter(prefix="/agents", tags=["agents"])

agents_router.include_router(crud_router)
agents_router.include_router(connection_router)
agents_router.include_router(metrics_router)

__all__ = ["agents_router"]
