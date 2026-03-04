# ==============================================================================
# LEADBOX TYPES
# Tipos e constantes para integracao Leadbox
# ==============================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TypedDict, Optional, Any


# ==============================================================================
# CONSTANTES - FILAS PADRÃO
# ==============================================================================

# IDs das filas no Leadbox (Lazaro)
QUEUE_BILLING = 544       # Fila de cobrança
QUEUE_MAINTENANCE = 545   # Fila de manutenção
QUEUE_GENERIC = 537       # Fila genérica (onde tickets caem por padrão)


# ==============================================================================
# ENUMS
# ==============================================================================

class TicketStatus(str, Enum):
    """Status do ticket no Leadbox."""
    OPEN = "open"
    PENDING = "pending"
    CLOSED = "closed"
    GROUP = "group"


class WebhookEvent(str, Enum):
    """Tipos de eventos webhook do Leadbox."""
    NEW_MESSAGE = "NewMessage"
    QUEUE_CHANGE = "QueueChange"
    UPDATE_ON_TICKET = "UpdateOnTicket"
    TRANSFER_OF_TICKET = "TransferOfTicket"
    TICKET_CLOSED = "TicketClosed"
    ACK_MESSAGE = "AckMessage"
    FINISHED_TICKET_HISTORIC_MESSAGES = "FinishedTicketHistoricMessages"


class SendType(str, Enum):
    """Tipo de envio de mensagem."""
    WEBHOOK = "WEBHOOK"
    API = "API"
    MANUAL = "MANUAL"


class MediaType(str, Enum):
    """Tipo de mídia da mensagem."""
    TEXT = "text"
    AUDIO = "audio"
    PTT = "ptt"
    VOICE = "voice"
    IMAGE = "image"
    IMAGE_MESSAGE = "imageMessage"
    DOCUMENT = "document"
    VIDEO = "video"
    STICKER = "sticker"


# ==============================================================================
# CONFIGURATION TYPES
# ==============================================================================

class LeadboxConfig(TypedDict, total=False):
    """Configuracao do Leadbox para um agente."""
    enabled: bool
    type: str  # 'leadbox' ou 'leadbox_api'
    api_url: str
    api_uuid: str
    api_token: str
    ia_queue_id: Optional[int]
    ia_user_id: Optional[int]
    queue_ia_user_id: Optional[int]  # Alias de ia_user_id
    tenant_id: Optional[int]


class DepartmentConfig(TypedDict, total=False):
    """Configuracao de um departamento."""
    id: int
    name: str
    keywords: Optional[list[str]]
    userId: Optional[int]
    queueId: Optional[int]
    context_injection: Optional[dict[str, Any]]


class DispatchDepartment(TypedDict, total=False):
    """Configuracao de dispatch para um departamento."""
    queueId: int
    userId: Optional[int]


class ContextInjection(TypedDict, total=False):
    """Configuracao de injecao de contexto."""
    enabled: bool
    message: str


class HandoffTriggers(TypedDict, total=False):
    """Configuracao completa de handoff triggers."""
    enabled: bool
    type: str
    api_url: str
    api_uuid: str
    api_token: str
    ia_queue_id: Optional[int]
    ia_user_id: Optional[int]
    queue_ia_user_id: Optional[int]
    tenant_id: Optional[int]
    dispatch_departments: Optional[dict[str, DispatchDepartment]]
    departments: Optional[dict[str, DepartmentConfig]]


# ==============================================================================
# RESULT TYPES
# ==============================================================================

class TransferResult(TypedDict):
    """Resultado de uma transferencia."""
    sucesso: bool
    mensagem: str
    ticket_id: Optional[str]
    queue_id: Optional[int]
    user_id: Optional[int]


class DispatchResult(TypedDict):
    """Resultado do dispatch inteligente."""
    success: bool
    ticket_existed: bool
    ticket_id: Optional[int]
    message_sent_via_push: bool
    ticket_check_failed: bool


class QueueInfo(TypedDict, total=False):
    """Informacao da fila atual de um lead."""
    queue_id: Optional[int]
    user_id: Optional[int]
    ticket_id: Optional[int]
    status: Optional[str]
    contact_found: bool


class SendMessageResult(TypedDict):
    """Resultado de envio de mensagem."""
    success: bool
    response: Optional[dict[str, Any]]
    error: Optional[str]


# ==============================================================================
# WEBHOOK PAYLOAD TYPES
# ==============================================================================

class Contact(TypedDict, total=False):
    """Contato do Leadbox."""
    id: int
    number: str
    name: Optional[str]
    email: Optional[str]
    profilePicUrl: Optional[str]


class Ticket(TypedDict, total=False):
    """Ticket do Leadbox."""
    id: int
    status: str
    queueId: Optional[int]
    userId: Optional[int]
    contact: Optional[Contact]
    closedAt: Optional[str]
    closingReasonId: Optional[int]


class Message(TypedDict, total=False):
    """Mensagem do Leadbox."""
    messageId: str
    ticketId: int
    contactId: int
    tenantId: int
    msgCreatedAt: str
    body: str
    fromMe: bool
    sendType: str
    mediaType: str
    mediaUrl: Optional[str]
    ticket: Optional[Ticket]


class WebhookPayload(TypedDict, total=False):
    """Payload completo do webhook Leadbox."""
    event: str
    message: Optional[Message]
    ticket: Optional[Ticket]
    tenantId: Optional[int]
    data: Optional[dict[str, Any]]


# ==============================================================================
# LEAD STATE TYPES
# ==============================================================================

class LeadboxLeadState(TypedDict, total=False):
    """Estado do lead relacionado ao Leadbox."""
    current_queue_id: Optional[int]
    current_user_id: Optional[int]
    ticket_id: Optional[str]
    Atendimento_Finalizado: str  # 'true' ou 'false'
    paused_at: Optional[str]
    paused_by: Optional[str]
    responsavel: str
    current_state: str  # 'ai' ou 'human'


# ==============================================================================
# DATACLASSES
# ==============================================================================

@dataclass
class LeadboxCredentials:
    """Credenciais do Leadbox."""
    base_url: str
    api_uuid: str
    api_token: str
    tenant_id: Optional[int] = None
    ia_queue_id: Optional[int] = None
    ia_user_id: Optional[int] = None

    @classmethod
    def from_config(cls, config: HandoffTriggers) -> Optional["LeadboxCredentials"]:
        """Cria credenciais a partir de config de handoff."""
        if not config.get("enabled"):
            return None

        api_url = config.get("api_url")
        api_uuid = config.get("api_uuid")
        api_token = config.get("api_token")

        if not api_url or not api_uuid or not api_token:
            return None

        return cls(
            base_url=api_url,
            api_uuid=api_uuid,
            api_token=api_token,
            tenant_id=config.get("tenant_id"),
            ia_queue_id=config.get("ia_queue_id"),
            ia_user_id=config.get("ia_user_id") or config.get("queue_ia_user_id"),
        )


# ==============================================================================
# HELPERS
# ==============================================================================

def format_phone(phone: str) -> str:
    """
    Formata telefone para o padrao Leadbox (apenas digitos, com 55).

    Remove sufixos do WhatsApp e caracteres especiais.
    Adiciona codigo do Brasil (55) se necessario.

    Args:
        phone: Numero de telefone (pode conter @s.whatsapp.net, @lid, etc)

    Returns:
        Numero formatado (apenas digitos)
    """
    # Remover sufixos do WhatsApp
    clean = phone.replace("@s.whatsapp.net", "")
    clean = clean.replace("@c.us", "")
    clean = clean.replace("@lid", "")

    # Remover caracteres nao-numericos
    clean = "".join(filter(str.isdigit, clean))

    # Adicionar codigo do Brasil se necessario
    if len(clean) == 10 or len(clean) == 11:
        clean = f"55{clean}"

    return clean


def is_ia_queue(queue_id: Optional[int], config: Optional[HandoffTriggers] = None) -> bool:
    """
    Verifica se uma fila e da IA.

    Args:
        queue_id: ID da fila
        config: Configuracao de handoff (opcional)

    Returns:
        True se for fila da IA
    """
    if queue_id is None:
        return False

    # Filas padrao da IA
    ia_queues = {QUEUE_GENERIC, QUEUE_BILLING, QUEUE_MAINTENANCE}

    # Adicionar fila customizada do config
    if config and config.get("ia_queue_id"):
        ia_queues.add(config["ia_queue_id"])

    return queue_id in ia_queues


def extract_webhook_data(payload: WebhookPayload) -> tuple[Optional[Message], Optional[Ticket], Optional[Contact]]:
    """
    Extrai dados normalizados de um payload de webhook.

    Args:
        payload: Payload do webhook

    Returns:
        Tupla (message, ticket, contact)
    """
    message = payload.get("message") or (payload.get("data") or {}).get("message")
    ticket = None
    contact = None

    if message:
        ticket = message.get("ticket") or payload.get("ticket")
        if ticket:
            contact = ticket.get("contact") or (message.get("contact") if message else None)

    return message, ticket, contact
