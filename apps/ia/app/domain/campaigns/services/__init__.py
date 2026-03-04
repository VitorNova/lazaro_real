"""
Domain Campaigns Services - Diana Prospecção Ativa.

Módulos:
- types: DTOs e enums (DianaStatus, DianaProspect, DianaCampanha)
- phone_formatter: Formatação de telefones brasileiros
- message_service: Integração UAZAPI + Gemini
- campaign_service: Serviço principal de campanhas
"""

from .types import (
    DianaStatus,
    DianaProspect,
    DianaCampanha,
    DianaConversationMessage,
    DianaConversationHistory,
)
from .phone_formatter import (
    format_phone,
    format_to_remotejid,
    extract_phone_from_remotejid,
    is_valid_brazilian_phone,
)
from .message_service import DianaMessageService
from .campaign_service import DianaCampaignService, get_diana_campaign_service

__all__ = [
    # Types
    "DianaStatus",
    "DianaProspect",
    "DianaCampanha",
    "DianaConversationMessage",
    "DianaConversationHistory",
    # Phone formatter
    "format_phone",
    "format_to_remotejid",
    "extract_phone_from_remotejid",
    "is_valid_brazilian_phone",
    # Services
    "DianaMessageService",
    "DianaCampaignService",
    "get_diana_campaign_service",
]
