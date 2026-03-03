"""
API routes module.

This module exports all routers and provides a function to register
all routes on the FastAPI application.
"""

from fastapi import FastAPI

from app.api.routes.webhooks import router as webhooks_router
from app.api.routes.leadbox import router as leadbox_router
from app.api.routes.uploads import router as uploads_router
from app.api.routes.jobs_control import router as jobs_control_router
from app.api.routes.maintenance_slots import router as maintenance_slots_router
from app.api.routes.leads_analysis import router as leads_analysis_router
from app.api.routes.health import router as health_router

__all__ = [
    "webhooks_router",
    "leadbox_router",
    "uploads_router",
    "jobs_control_router",
    "maintenance_slots_router",
    "leads_analysis_router",
    "health_router",
    "register_routes",
]


def register_routes(app: FastAPI) -> None:
    """
    Register all routes on the FastAPI application.

    This centralizes route registration to keep main.py minimal.
    """
    # Legacy WhatsApp webhook
    from app.webhooks.mensagens import router as whatsapp_router
    app.include_router(whatsapp_router, prefix="/api", tags=["webhooks"])

    # Dashboard API
    from app.api.dashboard import router as dashboard_router
    app.include_router(dashboard_router, tags=["dashboard"])

    # Google OAuth
    from app.api.google_oauth import router as google_oauth_router
    app.include_router(google_oauth_router, prefix="/api/google/oauth", tags=["google-oauth"])

    # Auth
    from app.api.auth import router as auth_router
    app.include_router(auth_router, prefix="/api/auth", tags=["auth"])

    # Agents CRUD
    from app.api.agentes import agents_router
    app.include_router(agents_router, prefix="/api", tags=["agents"])

    # Dynamic webhook
    app.include_router(webhooks_router)

    # Asaas payment webhook
    from app.webhooks.pagamentos import router as asaas_webhook_router
    app.include_router(asaas_webhook_router, prefix="/webhooks", tags=["webhooks"])

    # Leadbox webhook
    app.include_router(leadbox_router)

    # Diana v2 - Prospecao ativa
    from app.api.diana import router as diana_router
    app.include_router(diana_router, prefix="/api/diana", tags=["diana"])

    # Athena Oraculo - Analytics
    from app.api.athena import router as athena_router
    app.include_router(athena_router, prefix="/api/athena", tags=["athena"])

    # Extracted routes
    app.include_router(uploads_router)
    app.include_router(jobs_control_router)
    app.include_router(maintenance_slots_router)
    app.include_router(leads_analysis_router)
    app.include_router(health_router)
