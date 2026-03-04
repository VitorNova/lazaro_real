"""
Observer Service - Agente observador de conversas.

Analisa conversas e extrai insights sem responder ao lead.
"""

from .observer import ObserverService, get_observer_service, analyze_conversation

__all__ = ["ObserverService", "get_observer_service", "analyze_conversation"]
