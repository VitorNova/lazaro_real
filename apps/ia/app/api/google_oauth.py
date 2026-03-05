"""
DEPRECATED: Use app.api.routes.google_oauth instead.

Este modulo e uma ponte de compatibilidade.
"""

from app.api.routes.google_oauth import router

__all__ = ["router"]
