# apps/ia/app/integrations/uazapi/types.py
"""
Tipos e constantes para a integração UAZAPI (WhatsApp).

Baseado em apps/api/src/services/uazapi/types.ts para paridade.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ============================================================================
# CONSTANTES
# ============================================================================

# Configuração de retry
MAX_RETRIES = 3
RETRY_DELAY_S = 1.0
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# Timeout padrão em segundos
DEFAULT_TIMEOUT = 30.0

# Tamanho máximo de chunk para envio de mensagens longas
MAX_CHUNK_SIZE = 200


# ============================================================================
# ENUMS
# ============================================================================

class MediaType(str, Enum):
    """Tipos de mídia suportados."""
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"
    STICKER = "sticker"


class PresenceType(str, Enum):
    """Tipos de presença/status."""
    COMPOSING = "composing"
    RECORDING = "recording"
    PAUSED = "paused"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class InstanceState(str, Enum):
    """Estados da instância UAZAPI."""
    OPEN = "open"
    CLOSE = "close"
    CONNECTING = "connecting"


class MessageStatus(str, Enum):
    """Status de mensagem."""
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"


class ParsedMessageType(str, Enum):
    """Tipos de mensagem parseada."""
    TEXT = "text"
    AUDIO = "audio"
    IMAGE = "image"
    VIDEO = "video"
    DOCUMENT = "document"
    STICKER = "sticker"
    LOCATION = "location"
    CONTACT = "contact"
    BUTTON_RESPONSE = "button_response"
    LIST_RESPONSE = "list_response"
    UNKNOWN = "unknown"


class WebhookEventType(str, Enum):
    """Tipos de eventos de webhook."""
    MESSAGES_UPSERT = "messages.upsert"
    MESSAGES_UPDATE = "messages.update"
    MESSAGES_DELETE = "messages.delete"
    SEND_MESSAGE = "send.message"
    CONNECTION_UPDATE = "connection.update"
    QRCODE_UPDATED = "qrcode.updated"
    PRESENCE_UPDATE = "presence.update"
    CHATS_SET = "chats.set"
    CHATS_UPDATE = "chats.update"
    CONTACTS_SET = "contacts.set"
    CONTACTS_UPDATE = "contacts.update"
    GROUPS_UPSERT = "groups.upsert"
    GROUPS_UPDATE = "groups.update"


# ============================================================================
# TYPED DICTS - CONFIGURAÇÃO
# ============================================================================

class UazapiConfig(TypedDict, total=False):
    """Configuração do cliente UAZAPI."""
    base_url: str
    instance: Optional[str]
    api_key: Optional[str]
    instance_token: Optional[str]  # Token específico da instância
    admin_token: Optional[str]  # Token admin para criar instâncias
    timeout: float


# ============================================================================
# TYPED DICTS - PAYLOADS DE ENVIO
# ============================================================================

class SendTextPayload(TypedDict, total=False):
    """Payload para envio de texto."""
    number: str
    text: str
    delay: Optional[int]


class SendMediaPayload(TypedDict, total=False):
    """Payload para envio de mídia."""
    number: str
    media: str  # base64 ou URL
    caption: Optional[str]
    fileName: Optional[str]


class SendAudioPayload(TypedDict, total=False):
    """Payload para envio de áudio."""
    number: str
    audio: str  # base64
    ptt: Optional[bool]  # push to talk (áudio de voz)


class SendDocumentPayload(TypedDict, total=False):
    """Payload para envio de documento."""
    number: str
    document: str  # base64
    fileName: str
    caption: Optional[str]


class ButtonItem(TypedDict):
    """Item de botão."""
    buttonId: str
    buttonText: Dict[str, str]  # {"displayText": "..."}
    type: int


class SendButtonsPayload(TypedDict, total=False):
    """Payload para envio de botões."""
    number: str
    title: str
    description: str
    footer: Optional[str]
    buttons: List[ButtonItem]


class ListRow(TypedDict, total=False):
    """Linha de lista."""
    title: str
    description: Optional[str]
    rowId: str


class ListSection(TypedDict):
    """Seção de lista."""
    title: str
    rows: List[ListRow]


class SendListPayload(TypedDict, total=False):
    """Payload para envio de lista."""
    number: str
    title: str
    description: str
    buttonText: str
    footerText: Optional[str]
    sections: List[ListSection]


class SendContactPayload(TypedDict, total=False):
    """Payload para envio de contato."""
    number: str
    fullName: str
    phoneNumber: str  # Múltiplos números separados por vírgula
    organization: Optional[str]
    email: Optional[str]
    url: Optional[str]
    delay: Optional[int]


# ============================================================================
# TYPED DICTS - RESPOSTAS DA API
# ============================================================================

class MessageKey(TypedDict, total=False):
    """Chave de mensagem."""
    remoteJid: str
    fromMe: bool
    id: str
    participant: Optional[str]


class SendMessageResponse(TypedDict, total=False):
    """Resposta de envio de mensagem."""
    id: Optional[str]
    messageid: Optional[str]
    chatid: Optional[str]
    fromMe: Optional[bool]
    isGroup: Optional[bool]
    messageType: Optional[str]
    messageTimestamp: Optional[int]
    sender: Optional[str]
    senderName: Optional[str]
    status: Optional[str]
    text: Optional[str]
    fileURL: Optional[str]
    # Formato legado (compatibilidade)
    key: Optional[MessageKey]
    message: Optional[Dict[str, Any]]
    response: Optional[Dict[str, str]]


class MessageResponse(TypedDict, total=False):
    """Resposta simplificada de mensagem."""
    success: bool
    message_id: Optional[str]
    error: Optional[str]


class InstanceStatus(TypedDict, total=False):
    """Status da instância UAZAPI."""
    connected: bool
    phone_number: Optional[str]
    instance_id: Optional[str]
    status: Optional[str]
    battery: Optional[int]
    plugged: Optional[bool]


class InstanceStatusResponse(TypedDict):
    """Resposta de status da instância."""
    instance: Dict[str, Any]


class MediaBase64Response(TypedDict):
    """Resposta de mídia em base64."""
    base64: str
    mimetype: str


class ChunkedSendResult(TypedDict):
    """Resultado de envio em chunks."""
    all_success: bool
    success_count: int
    total_chunks: int
    failed_chunks: List[int]
    results: List[MessageResponse]
    first_error: Optional[str]


# ============================================================================
# TYPED DICTS - WEBHOOK
# ============================================================================

class ContextInfo(TypedDict, total=False):
    """Informações de contexto (mensagem citada)."""
    stanzaId: Optional[str]
    participant: Optional[str]
    quotedMessage: Optional[Dict[str, Any]]


class ImageMessage(TypedDict, total=False):
    """Mensagem de imagem."""
    url: Optional[str]
    mimetype: Optional[str]
    caption: Optional[str]
    fileSha256: Optional[str]
    fileLength: Optional[str]
    mediaKey: Optional[str]
    jpegThumbnail: Optional[str]


class AudioMessage(TypedDict, total=False):
    """Mensagem de áudio."""
    url: Optional[str]
    mimetype: Optional[str]
    fileSha256: Optional[str]
    fileLength: Optional[str]
    seconds: Optional[int]
    ptt: Optional[bool]
    mediaKey: Optional[str]


class VideoMessage(TypedDict, total=False):
    """Mensagem de vídeo."""
    url: Optional[str]
    mimetype: Optional[str]
    caption: Optional[str]
    fileSha256: Optional[str]
    fileLength: Optional[str]
    seconds: Optional[int]
    mediaKey: Optional[str]
    jpegThumbnail: Optional[str]


class DocumentMessage(TypedDict, total=False):
    """Mensagem de documento."""
    url: Optional[str]
    mimetype: Optional[str]
    title: Optional[str]
    fileSha256: Optional[str]
    fileLength: Optional[str]
    mediaKey: Optional[str]
    fileName: Optional[str]


class StickerMessage(TypedDict, total=False):
    """Mensagem de sticker."""
    url: Optional[str]
    mimetype: Optional[str]
    fileSha256: Optional[str]
    fileLength: Optional[str]
    mediaKey: Optional[str]


class LocationMessage(TypedDict, total=False):
    """Mensagem de localização."""
    degreesLatitude: Optional[float]
    degreesLongitude: Optional[float]
    name: Optional[str]
    address: Optional[str]


class ContactMessage(TypedDict, total=False):
    """Mensagem de contato."""
    displayName: Optional[str]
    vcard: Optional[str]


class ButtonsResponseMessage(TypedDict, total=False):
    """Resposta de botões."""
    selectedButtonId: Optional[str]
    selectedDisplayText: Optional[str]


class ListResponseMessage(TypedDict, total=False):
    """Resposta de lista."""
    title: Optional[str]
    listType: Optional[int]
    singleSelectReply: Optional[Dict[str, str]]


class WebhookMessage(TypedDict, total=False):
    """Conteúdo de mensagem do webhook."""
    conversation: Optional[str]
    extendedTextMessage: Optional[Dict[str, Any]]
    imageMessage: Optional[ImageMessage]
    audioMessage: Optional[AudioMessage]
    videoMessage: Optional[VideoMessage]
    documentMessage: Optional[DocumentMessage]
    stickerMessage: Optional[StickerMessage]
    locationMessage: Optional[LocationMessage]
    contactMessage: Optional[ContactMessage]
    buttonsResponseMessage: Optional[ButtonsResponseMessage]
    listResponseMessage: Optional[ListResponseMessage]


class WebhookData(TypedDict, total=False):
    """Dados do webhook."""
    key: MessageKey
    pushName: Optional[str]
    message: Optional[WebhookMessage]
    messageType: Optional[str]
    messageTimestamp: Optional[int]
    owner: Optional[str]
    source: Optional[str]


class WebhookPayload(TypedDict, total=False):
    """Payload completo do webhook."""
    event: Optional[str]
    instance: Optional[str]
    data: Optional[WebhookData]
    # Estrutura alternativa (algumas versões)
    key: Optional[MessageKey]
    message: Optional[WebhookMessage]
    messageTimestamp: Optional[int]
    pushName: Optional[str]
    messageType: Optional[str]


# ============================================================================
# TYPED DICTS - MENSAGEM PARSEADA
# ============================================================================

class MessageContent(TypedDict, total=False):
    """Conteúdo de mensagem parseada."""
    text: Optional[str]
    caption: Optional[str]
    url: Optional[str]
    mimetype: Optional[str]
    fileName: Optional[str]
    fileLength: Optional[int]
    seconds: Optional[int]
    latitude: Optional[float]
    longitude: Optional[float]
    locationName: Optional[str]
    address: Optional[str]
    displayName: Optional[str]
    vcard: Optional[str]
    selectedButtonId: Optional[str]
    selectedRowId: Optional[str]
    base64: Optional[str]
    mediaKey: Optional[str]


class QuotedMessage(TypedDict, total=False):
    """Mensagem citada."""
    messageId: str
    participant: Optional[str]
    content: MessageContent


class MessageReceived(TypedDict, total=False):
    """Mensagem recebida (parseada)."""
    remoteJid: str
    fromMe: bool
    messageId: str
    messageType: str
    pushName: Optional[str]
    timestamp: int
    content: MessageContent
    quotedMessage: Optional[QuotedMessage]
    participant: Optional[str]  # Para mensagens de grupo
    isGroup: bool


# ============================================================================
# TYPED DICTS - CAMPANHAS
# ============================================================================

class CampaignMessage(TypedDict, total=False):
    """Mensagem de campanha."""
    number: str  # formato: 5566997194084 (sem @s.whatsapp.net)
    type: str  # tipo da mensagem
    text: str  # mensagem personalizada


class CampaignRequest(TypedDict, total=False):
    """Requisição de campanha."""
    delayMin: int  # delay mínimo em segundos
    delayMax: int  # delay máximo em segundos
    info: str  # nome da campanha
    scheduled_for: int  # minutos para iniciar
    messages: List[CampaignMessage]


class CampaignResponse(TypedDict):
    """Resposta de criação de campanha."""
    folder_id: str
    count: int
    status: str


class CampaignFolder(TypedDict, total=False):
    """Pasta de campanha."""
    id: str
    info: str
    status: str
    count: int
    sent: int
    failed: int
    created_at: str


class SimpleCampaignRequest(TypedDict, total=False):
    """Requisição de campanha simples."""
    numbers: List[str]  # Lista de números
    type: str  # text, image, video, audio, document, contact, location, list, button, poll
    delayMin: int
    delayMax: int
    scheduled_for: int
    folder: Optional[str]
    info: Optional[str]
    # Para type = 'text'
    text: Optional[str]
    linkPreview: Optional[bool]
    # Para mídia
    file: Optional[str]
    docName: Optional[str]
    # Para contato
    fullName: Optional[str]
    phoneNumber: Optional[str]
    organization: Optional[str]
    email: Optional[str]
    url: Optional[str]
    # Para localização
    latitude: Optional[float]
    longitude: Optional[float]
    name: Optional[str]
    address: Optional[str]
