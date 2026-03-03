"""API routes module."""

from app.api.routes.webhooks import router as webhooks_router

__all__ = ["webhooks_router"]
