"""API routes module."""

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
]
