"""
Diana v2 - Agente de prospecao ativa via WhatsApp.

Modulo simplificado para:
1. Importar lista de contatos (CSV)
2. Formatar telefones para UAZAPI
3. Disparar mensagens em massa via UAZAPI /sender/advanced
4. Responder com IA (Gemini) quando prospects respondem
5. Salvar historico de conversas

A inteligencia fica no system_prompt da campanha, nao no codigo.
"""

from app.services.diana.types import DianaStatus, DianaProspect, DianaCampanha
from app.services.diana.phone_formatter import format_phone, format_to_remotejid
from app.services.diana.campaign_service import DianaCampaignService, get_diana_campaign_service
from app.services.diana.message_service import DianaMessageService

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
