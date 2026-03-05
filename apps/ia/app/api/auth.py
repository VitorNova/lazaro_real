"""
DEPRECATED: Use app.api.routes.auth instead.

Este modulo e uma ponte de compatibilidade.
"""

from app.api.routes.auth import router

__all__ = ["router"]
