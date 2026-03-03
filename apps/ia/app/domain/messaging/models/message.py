"""
Modelos de dados para mensagens do WhatsApp.

Extraído de: app/webhooks/mensagens.py (Fase 2.1)
"""

from typing import Any, Dict, Optional, TypedDict


class ExtractedMessage(TypedDict, total=False):
    """Dados extraidos da mensagem do webhook."""
    phone: str
    remotejid: str
    text: str
    is_group: bool
    from_me: bool
    message_id: Optional[str]
    timestamp: str
    push_name: Optional[str]
    instance_id: Optional[str]
    token: Optional[str]  # Token da instancia UAZAPI
    media_type: Optional[str]  # audio, ptt, image, video, etc
    media_url: Optional[str]  # URL direta da midia (Leadbox envia diretamente)


class ProcessingContext(TypedDict):
    """Contexto para processamento de mensagens."""
    agent_id: str
    agent_name: str  # Nome do agente para assinatura de mensagens (ex: "Ana")
    remotejid: str
    phone: str
    table_leads: str
    table_messages: str
    system_prompt: str
    uazapi_token: Optional[str]  # Token da instancia UAZAPI do agente
    uazapi_base_url: Optional[str]  # URL base da instancia UAZAPI do agente
    handoff_triggers: Optional[Dict[str, Any]]  # Config do Leadbox para transferencia
    audio_message_id: Optional[str]  # ID da mensagem de audio para download
    image_message_id: Optional[str]  # ID da mensagem de imagem para download
    image_url: Optional[str]  # URL direta da imagem (Leadbox envia diretamente)
    context_prompts: Optional[Dict[str, Any]]  # Prompts dinamicos por contexto (RAG simplificado)
