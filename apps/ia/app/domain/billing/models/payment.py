"""
Modelos e constantes do dominio de billing/pagamentos.

Extraido de: app/webhooks/pagamentos.py (Fase 3.1)
"""

from typing import TypedDict, Optional, List, Any

# Agent ID do Lazaro (fixo para CUSTOMER_CREATED sem agentId identificavel)
LAZARO_AGENT_ID = "14e6e5ce-4627-4e38-aac8-f0191669ff53"

# Extensoes de arquivo suportadas para extracao de contratos
SUPPORTED_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png', '.gif', '.webp'}

# Mapeamento de extensao para MIME type
MIME_TYPES = {
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.gif': 'image/gif',
    '.webp': 'image/webp',
}

# TTL do cache de cliente em minutos
CUSTOMER_CACHE_TTL_MINUTES = 5


class ContractDetails(TypedDict, total=False):
    """Dados extraidos de um contrato via Gemini."""
    nome_cliente: Optional[str]
    telefone: Optional[str]
    endereco: Optional[str]
    equipamentos: Optional[List[str]]
    valor_mensal: Optional[float]
    dia_vencimento: Optional[int]
    data_primeira_cobranca: Optional[str]
    numero_parcelas: Optional[int]
    observacoes: Optional[str]


class WebhookEvent(TypedDict):
    """Evento recebido do webhook Asaas."""
    event: str
    payment: Optional[dict]
    subscription: Optional[dict]
    customer: Optional[dict]


class ProcessedEvent(TypedDict):
    """Resultado do processamento de um evento."""
    event_type: str
    agent_id: Optional[str]
    customer_id: Optional[str]
    subscription_id: Optional[str]
    payment_id: Optional[str]
    status: str
    message: str
