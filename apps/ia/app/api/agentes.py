"""
DEPRECATED: Use app.api.routes.agentes instead.

Este modulo e uma ponte de compatibilidade.
"""

from app.api.routes.agentes import agents_router

__all__ = ["agents_router"]
