"""
Webhook Models - Pydantic models para validacao de payloads de webhooks.

Modelos:
- WhatsApp/UAZAPI: Mensagens do WhatsApp via UAZAPI
- Asaas: Eventos de pagamento, cliente, assinatura
- Leadbox: Eventos de tickets e mensagens do CRM

Uso:
    from app.api.models import WhatsAppWebhookPayload, AsaasWebhookPayload

    @router.post("/webhook/whatsapp")
    async def webhook(payload: WhatsAppWebhookPayload):
        # payload ja validado pelo Pydantic
        ...
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator


# =============================================================================
# WHATSAPP / UAZAPI MODELS
# =============================================================================

class WhatsAppMessageKey(BaseModel):
    """Chave identificadora da mensagem WhatsApp."""
    remoteJid: str = Field(..., description="JID do remetente (phone@s.whatsapp.net)")
    fromMe: bool = Field(False, description="Se a mensagem foi enviada por nos")
    id: str = Field(..., description="ID unico da mensagem")


class WhatsAppMessageContent(BaseModel):
    """Conteudo da mensagem (pode ser texto, imagem, audio, etc)."""
    conversation: Optional[str] = Field(None, description="Texto da mensagem")
    extendedTextMessage: Optional[Dict[str, Any]] = Field(None, description="Texto com preview")
    imageMessage: Optional[Dict[str, Any]] = Field(None, description="Mensagem de imagem")
    audioMessage: Optional[Dict[str, Any]] = Field(None, description="Mensagem de audio")
    documentMessage: Optional[Dict[str, Any]] = Field(None, description="Mensagem de documento")
    videoMessage: Optional[Dict[str, Any]] = Field(None, description="Mensagem de video")
    stickerMessage: Optional[Dict[str, Any]] = Field(None, description="Mensagem de sticker")
    locationMessage: Optional[Dict[str, Any]] = Field(None, description="Mensagem de localizacao")
    contactMessage: Optional[Dict[str, Any]] = Field(None, description="Mensagem de contato")
    reactionMessage: Optional[Dict[str, Any]] = Field(None, description="Reacao a mensagem")


class WhatsAppMessageData(BaseModel):
    """Dados da mensagem WhatsApp."""
    key: WhatsAppMessageKey
    message: Optional[WhatsAppMessageContent] = None
    pushName: Optional[str] = Field(None, description="Nome do contato no WhatsApp")
    messageTimestamp: Optional[Union[str, int]] = Field(None, description="Timestamp da mensagem")


class WhatsAppWebhookPayload(BaseModel):
    """Payload do webhook WhatsApp/UAZAPI."""
    event: Optional[str] = Field(None, description="Tipo de evento (messages.upsert, etc)")
    type: Optional[str] = Field(None, description="Tipo alternativo de evento")
    instanceId: Optional[str] = Field(None, description="ID da instancia UAZAPI")
    data: Optional[WhatsAppMessageData] = Field(None, description="Dados da mensagem")
    
    @field_validator("event", "type", mode="before")
    @classmethod
    def normalize_event_type(cls, v):
        """Normaliza string vazia para None."""
        if v == "":
            return None
        return v
    
    def get_event_type(self) -> Optional[str]:
        """Retorna o tipo de evento (event ou type)."""
        return self.event or self.type


class WhatsAppTestPayload(BaseModel):
    """Payload para teste de webhook WhatsApp."""
    phone: str = Field(..., description="Numero de telefone (sem @s.whatsapp.net)")
    text: str = Field(..., description="Texto da mensagem")
    name: Optional[str] = Field("Teste", description="Nome do contato")
    instance_id: Optional[str] = Field("test-instance", description="ID da instancia")


# =============================================================================
# ASAAS MODELS
# =============================================================================

class AsaasPayment(BaseModel):
    """Dados de pagamento Asaas."""
    id: str = Field(..., description="ID do pagamento (pay_xxx)")
    customer: Optional[str] = Field(None, description="ID do cliente")
    subscription: Optional[str] = Field(None, description="ID da assinatura")
    value: Optional[float] = Field(None, description="Valor do pagamento")
    netValue: Optional[float] = Field(None, description="Valor liquido")
    status: Optional[str] = Field(None, description="Status (PENDING, CONFIRMED, etc)")
    billingType: Optional[str] = Field(None, description="Tipo (BOLETO, PIX, CREDIT_CARD)")
    dueDate: Optional[str] = Field(None, description="Data de vencimento")
    paymentDate: Optional[str] = Field(None, description="Data de pagamento")
    invoiceUrl: Optional[str] = Field(None, alias="invoiceUrl", description="URL do boleto/fatura")
    bankSlipUrl: Optional[str] = Field(None, alias="bankSlipUrl", description="URL do boleto")
    invoiceNumber: Optional[str] = Field(None, description="Numero da fatura")
    externalReference: Optional[str] = Field(None, description="Referencia externa (agent_id:lead_id)")
    description: Optional[str] = Field(None, description="Descricao do pagamento")
    
    class Config:
        populate_by_name = True


class AsaasCustomer(BaseModel):
    """Dados de cliente Asaas."""
    id: str = Field(..., description="ID do cliente (cus_xxx)")
    name: Optional[str] = Field(None, description="Nome do cliente")
    email: Optional[str] = Field(None, description="Email")
    phone: Optional[str] = Field(None, description="Telefone fixo")
    mobilePhone: Optional[str] = Field(None, description="Celular")
    cpfCnpj: Optional[str] = Field(None, description="CPF ou CNPJ")
    address: Optional[str] = Field(None, description="Endereco")
    addressNumber: Optional[str] = Field(None, description="Numero")
    complement: Optional[str] = Field(None, description="Complemento")
    province: Optional[str] = Field(None, description="Bairro")
    city: Optional[str] = Field(None, description="Cidade")
    state: Optional[str] = Field(None, description="Estado (UF)")
    postalCode: Optional[str] = Field(None, description="CEP")
    externalReference: Optional[str] = Field(None, description="Referencia externa")


class AsaasSubscription(BaseModel):
    """Dados de assinatura Asaas."""
    id: str = Field(..., description="ID da assinatura (sub_xxx)")
    customer: Optional[str] = Field(None, description="ID do cliente")
    value: Optional[float] = Field(None, description="Valor da assinatura")
    nextDueDate: Optional[str] = Field(None, description="Proxima data de vencimento")
    cycle: Optional[str] = Field(None, description="Ciclo (MONTHLY, WEEKLY, etc)")
    status: Optional[str] = Field(None, description="Status (ACTIVE, INACTIVE, etc)")
    description: Optional[str] = Field(None, description="Descricao")
    externalReference: Optional[str] = Field(None, description="Referencia externa")


class AsaasWebhookPayload(BaseModel):
    """Payload do webhook Asaas."""
    id: Optional[str] = Field(None, description="ID do evento")
    event: Optional[str] = Field(None, description="Tipo de evento")
    payment: Optional[AsaasPayment] = Field(None, description="Dados do pagamento")
    customer: Optional[AsaasCustomer] = Field(None, description="Dados do cliente")
    subscription: Optional[AsaasSubscription] = Field(None, description="Dados da assinatura")
    
    @field_validator("id", "event", mode="before")
    @classmethod
    def validate_required_fields(cls, v):
        """Valida campos obrigatorios."""
        if v is None or v == "":
            # Permitir None mas logar warning
            return None
        return v


class AsaasReprocessContractPayload(BaseModel):
    """Payload para reprocessamento de contrato."""
    subscription_id: str = Field(..., description="ID da assinatura (sub_xxx)")
    agent_id: str = Field(..., description="UUID do agente")


# =============================================================================
# LEADBOX MODELS
# =============================================================================

class LeadboxContact(BaseModel):
    """Dados do contato Leadbox."""
    id: Optional[str] = Field(None, description="ID do contato")
    name: Optional[str] = Field(None, description="Nome do contato")
    number: Optional[str] = Field(None, description="Numero de telefone")
    email: Optional[str] = Field(None, description="Email")
    profilePicUrl: Optional[str] = Field(None, description="URL da foto de perfil")


class LeadboxTicket(BaseModel):
    """Dados do ticket Leadbox."""
    id: Optional[str] = Field(None, description="ID do ticket")
    status: Optional[str] = Field(None, description="Status (open, closed, pending)")
    queueId: Optional[Union[str, int]] = Field(None, description="ID da fila")
    userId: Optional[Union[str, int]] = Field(None, description="ID do atendente")
    tenantId: Optional[str] = Field(None, description="ID do tenant")
    contact: Optional[LeadboxContact] = Field(None, description="Dados do contato")
    closedAt: Optional[str] = Field(None, description="Data de fechamento")
    
    @field_validator("queueId", "userId", mode="before")
    @classmethod
    def coerce_to_string(cls, v):
        """Converte int para string se necessario."""
        if v is not None:
            return str(v)
        return v


class LeadboxMessage(BaseModel):
    """Dados da mensagem Leadbox."""
    id: Optional[str] = Field(None, description="ID da mensagem")
    body: Optional[str] = Field(None, description="Corpo da mensagem")
    fromMe: Optional[bool] = Field(None, description="Se a mensagem e nossa")
    ticketId: Optional[str] = Field(None, description="ID do ticket")
    queueId: Optional[Union[str, int]] = Field(None, description="ID da fila")
    userId: Optional[Union[str, int]] = Field(None, description="ID do atendente")
    ticket: Optional[LeadboxTicket] = Field(None, description="Dados do ticket")
    contact: Optional[LeadboxContact] = Field(None, description="Dados do contato")
    
    @field_validator("queueId", "userId", mode="before")
    @classmethod
    def coerce_to_string(cls, v):
        """Converte int para string se necessario."""
        if v is not None:
            return str(v)
        return v


class LeadboxWebhookPayload(BaseModel):
    """Payload do webhook Leadbox."""
    event: Optional[str] = Field(None, description="Tipo de evento")
    type: Optional[str] = Field(None, description="Tipo alternativo")
    message: Optional[LeadboxMessage] = Field(None, description="Dados da mensagem")
    ticket: Optional[LeadboxTicket] = Field(None, description="Dados do ticket")
    contact: Optional[LeadboxContact] = Field(None, description="Dados do contato")
    tenantId: Optional[str] = Field(None, description="ID do tenant")
    tenant_id: Optional[str] = Field(None, description="ID do tenant (snake_case)")
    data: Optional[Dict[str, Any]] = Field(None, description="Dados adicionais")
    
    def get_event_type(self) -> str:
        """Retorna o tipo de evento."""
        return self.event or self.type or "unknown"
    
    def get_tenant_id(self) -> Optional[str]:
        """Retorna o tenant ID."""
        return self.tenantId or self.tenant_id
    
    def get_phone(self) -> Optional[str]:
        """Extrai o telefone do payload."""
        # Tentar extrair de varias fontes
        contact = self.contact
        if not contact and self.ticket:
            contact = self.ticket.contact
        if not contact and self.message:
            contact = self.message.contact
        if not contact and self.message and self.message.ticket:
            contact = self.message.ticket.contact
        
        if contact and contact.number:
            return contact.number.replace("+", "").strip()
        return None
    
    def get_queue_id(self) -> Optional[str]:
        """Extrai o queue ID do payload."""
        if self.ticket and self.ticket.queueId:
            return str(self.ticket.queueId)
        if self.message and self.message.queueId:
            return str(self.message.queueId)
        if self.message and self.message.ticket and self.message.ticket.queueId:
            return str(self.message.ticket.queueId)
        return None
    
    def get_user_id(self) -> Optional[str]:
        """Extrai o user ID do payload."""
        if self.ticket and self.ticket.userId:
            return str(self.ticket.userId)
        if self.message and self.message.userId:
            return str(self.message.userId)
        if self.message and self.message.ticket and self.message.ticket.userId:
            return str(self.message.ticket.userId)
        return None
