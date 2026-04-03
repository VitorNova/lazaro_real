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

    # Dashboard API (split into dashboard/stats.py, dashboard/categories.py)
    from app.api.routes.dashboard import router as dashboard_router
    app.include_router(dashboard_router, tags=["dashboard"])

    # Google OAuth
    from app.api.routes.google_oauth import router as google_oauth_router
    app.include_router(google_oauth_router, prefix="/api/google/oauth", tags=["google-oauth"])

    # Auth
    from app.api.routes.auth import router as auth_router
    app.include_router(auth_router, prefix="/api/auth", tags=["auth"])

    # Agents CRUD (split into agents/crud.py, agents/connection.py, agents/metrics.py)
    from app.api.routes.agents import agents_router
    app.include_router(agents_router, prefix="/api", tags=["agents"])

    # Dynamic webhook
    app.include_router(webhooks_router)

    # Asaas payment webhook
    from app.webhooks.pagamentos import router as asaas_webhook_router
    app.include_router(asaas_webhook_router, prefix="/webhooks", tags=["webhooks"])

    # Leadbox webhook
    app.include_router(leadbox_router)

    # Diana v2 - Prospecao ativa
    from app.api.routes.diana import router as diana_router
    app.include_router(diana_router, prefix="/api/diana", tags=["diana"])

    # REMOVIDO: Athena Oraculo - Analytics (desativado na refatoração)
    # from app.api.routes.athena import router as athena_router
    # app.include_router(athena_router, prefix="/api/athena", tags=["athena"])

    # ERP API (split into erp/customers.py, erp/products.py, erp/orders.py, etc.)
    from app.api.routes.erp import router as erp_router
    app.include_router(erp_router, prefix="/api/erp", tags=["erp"])

    # ERP Users/SaaS API
    from app.api.routes.erp_users import router as erp_users_router
    app.include_router(erp_users_router, prefix="/api/erp", tags=["erp-users"])

    # Asaas Dashboard (proxy para agnes-agent por enquanto)
    from app.api.routes.asaas_dashboard import router as asaas_dashboard_router
    app.include_router(asaas_dashboard_router, tags=["asaas-dashboard"])

    # Manutenções Dashboard (proxy para agnes-agent por enquanto)
    from app.api.routes.manutencoes_dashboard import router as manutencoes_dashboard_router
    app.include_router(manutencoes_dashboard_router, tags=["manutencoes-dashboard"])

    # Athena Oráculo (proxy para agnes-agent por enquanto)
    from app.api.routes.athena import router as athena_router
    app.include_router(athena_router, tags=["athena"])

    # Agents-leads (migrado de proxy_agnes, agora implementacao nativa)
    from app.api.routes.agents_leads import router as agents_leads_router
    app.include_router(agents_leads_router, tags=["agents-leads"])

    # Extracted routes
    app.include_router(uploads_router)
    app.include_router(jobs_control_router)
    app.include_router(maintenance_slots_router)
    app.include_router(leads_analysis_router)
    app.include_router(health_router)
