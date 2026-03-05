"""
DEPRECATED: Use app.api.routes.dashboard instead.

Este modulo e uma ponte de compatibilidade.
"""

from app.api.routes.dashboard import router

__all__ = ["router"]
