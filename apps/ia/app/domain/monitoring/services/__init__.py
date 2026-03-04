"""
Domain Monitoring Services - Observer de Conversas.

Módulos:
- observer: Serviço de análise de conversas sem responder ao lead
"""

from .observer import (
    ObserverService,
    get_observer_service,
    analyze_conversation,
    HIGH_CONFIDENCE_TOOLS,
    CLOSING_KEYWORDS_POSITIVE,
    CLOSING_KEYWORDS_NEGATIVE,
    AD_URL_PATTERNS,
)

__all__ = [
    "ObserverService",
    "get_observer_service",
    "analyze_conversation",
    "HIGH_CONFIDENCE_TOOLS",
    "CLOSING_KEYWORDS_POSITIVE",
    "CLOSING_KEYWORDS_NEGATIVE",
    "AD_URL_PATTERNS",
]
