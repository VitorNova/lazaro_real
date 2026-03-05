"""
DEPRECATED: Use app.domain.monitoring instead.

Este modulo e uma ponte de compatibilidade.
Todos os imports sao redirecionados para domain/monitoring/.
"""

from app.domain.monitoring import (
    ObserverService,
    get_observer_service,
    analyze_conversation,
)

__all__ = [
    "ObserverService",
    "get_observer_service",
    "analyze_conversation",
]
