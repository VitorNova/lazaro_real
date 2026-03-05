"""
DEPRECATED: Use app.domain.campaigns instead.

Este modulo e uma ponte de compatibilidade.
Todos os imports sao redirecionados para domain/campaigns/.
"""

from app.domain.campaigns import (
    # Types
    DianaStatus,
    DianaProspect,
    DianaCampanha,
    # Phone formatter
    format_phone,
    format_to_remotejid,
    # Services
    DianaCampaignService,
    DianaMessageService,
    get_diana_campaign_service,
)

__all__ = [
    # Types
    "DianaStatus",
    "DianaProspect",
    "DianaCampanha",
    # Phone formatter
    "format_phone",
    "format_to_remotejid",
    # Services
    "DianaCampaignService",
    "DianaMessageService",
    "get_diana_campaign_service",
]
