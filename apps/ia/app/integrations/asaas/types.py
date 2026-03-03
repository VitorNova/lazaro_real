# apps/ia/app/integrations/asaas/types.py
"""
Tipos e constantes para a integração Asaas.

Baseado em apps/api/src/services/asaas/types.ts para paridade.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ============================================================================
# CONSTANTES
# ============================================================================

ASAAS_PRODUCTION_URL = "https://api.asaas.com/v3"
ASAAS_SANDBOX_URL = "https://sandbox.asaas.com/api/v3"

# Configuração de retry
MAX_RETRIES = 3
RETRY_DELAY_S = 1.0
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# Rate limiter: 30 requisições por minuto (janela deslizante)
RATE_LIMIT_MAX_REQUESTS = 30
RATE_LIMIT_WINDOW_S = 60


# ============================================================================
# ENUMS
# ============================================================================

class BillingType(str, Enum):
    """Tipo de cobrança."""
    BOLETO = "BOLETO"
    CREDIT_CARD = "CREDIT_CARD"
    DEBIT_CARD = "DEBIT_CARD"
    PIX = "PIX"
    UNDEFINED = "UNDEFINED"  # Permite cliente escolher


class Cycle(str, Enum):
    """Ciclo de assinatura."""
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"
    MONTHLY = "MONTHLY"
    BIMONTHLY = "BIMONTHLY"
    QUARTERLY = "QUARTERLY"
    SEMIANNUALLY = "SEMIANNUALLY"
    YEARLY = "YEARLY"


class ChargeType(str, Enum):
    """Tipo de cobrança."""
    DETACHED = "DETACHED"  # Cobrança avulsa
    RECURRENT = "RECURRENT"  # Cobrança recorrente
    INSTALLMENT = "INSTALLMENT"  # Parcelamento


class PaymentStatus(str, Enum):
    """Status de pagamento."""
    PENDING = "PENDING"
    RECEIVED = "RECEIVED"
    CONFIRMED = "CONFIRMED"
    OVERDUE = "OVERDUE"
    REFUNDED = "REFUNDED"
    RECEIVED_IN_CASH = "RECEIVED_IN_CASH"
    REFUND_REQUESTED = "REFUND_REQUESTED"
    REFUND_IN_PROGRESS = "REFUND_IN_PROGRESS"
    CHARGEBACK_REQUESTED = "CHARGEBACK_REQUESTED"
    CHARGEBACK_DISPUTE = "CHARGEBACK_DISPUTE"
    AWAITING_CHARGEBACK_REVERSAL = "AWAITING_CHARGEBACK_REVERSAL"
    DUNNING_REQUESTED = "DUNNING_REQUESTED"
    DUNNING_RECEIVED = "DUNNING_RECEIVED"
    AWAITING_RISK_ANALYSIS = "AWAITING_RISK_ANALYSIS"


class SubscriptionStatus(str, Enum):
    """Status de assinatura."""
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    EXPIRED = "EXPIRED"


class PaymentLinkStatus(str, Enum):
    """Status de link de pagamento."""
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


# ============================================================================
# TYPED DICTS - CUSTOMER
# ============================================================================

class AsaasCustomer(TypedDict, total=False):
    """Cliente Asaas."""
    id: str
    name: str
    email: Optional[str]
    phone: Optional[str]
    mobilePhone: Optional[str]
    cpfCnpj: Optional[str]
    personType: Optional[str]  # 'FISICA' | 'JURIDICA'
    postalCode: Optional[str]
    address: Optional[str]
    addressNumber: Optional[str]
    complement: Optional[str]
    province: Optional[str]
    city: Optional[int]
    cityName: Optional[str]
    state: Optional[str]
    country: Optional[str]
    company: Optional[str]
    externalReference: Optional[str]
    notificationDisabled: Optional[bool]
    additionalEmails: Optional[str]
    municipalInscription: Optional[str]
    stateInscription: Optional[str]
    observations: Optional[str]
    groupName: Optional[str]
    foreignCustomer: Optional[bool]
    dateCreated: Optional[str]
    deleted: Optional[bool]
    canDelete: Optional[bool]
    canEdit: Optional[bool]


class CreateCustomerInput(TypedDict, total=False):
    """Input para criar cliente."""
    name: str  # Required
    email: Optional[str]
    phone: Optional[str]
    mobilePhone: Optional[str]
    cpfCnpj: Optional[str]
    postalCode: Optional[str]
    address: Optional[str]
    addressNumber: Optional[str]
    complement: Optional[str]
    province: Optional[str]
    city: Optional[str]
    state: Optional[str]
    externalReference: Optional[str]
    notificationDisabled: Optional[bool]
    additionalEmails: Optional[str]
    groupName: Optional[str]


class UpdateCustomerInput(TypedDict, total=False):
    """Input para atualizar cliente."""
    name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    mobilePhone: Optional[str]
    cpfCnpj: Optional[str]
    postalCode: Optional[str]
    address: Optional[str]
    addressNumber: Optional[str]
    complement: Optional[str]
    province: Optional[str]
    city: Optional[str]
    state: Optional[str]
    externalReference: Optional[str]
    notificationDisabled: Optional[bool]
    additionalEmails: Optional[str]
    groupName: Optional[str]


# ============================================================================
# TYPED DICTS - SUBSCRIPTION
# ============================================================================

class DiscountConfig(TypedDict, total=False):
    """Configuração de desconto."""
    value: float
    dueDateLimitDays: Optional[int]
    type: Optional[str]  # 'FIXED' | 'PERCENTAGE'


class FineConfig(TypedDict, total=False):
    """Configuração de multa."""
    value: float
    type: Optional[str]  # 'FIXED' | 'PERCENTAGE'


class InterestConfig(TypedDict, total=False):
    """Configuração de juros."""
    value: float  # Percentual ao mês


class AsaasSubscription(TypedDict, total=False):
    """Assinatura Asaas."""
    id: str
    customer: str
    billingType: str
    value: float
    nextDueDate: str
    cycle: str
    description: Optional[str]
    endDate: Optional[str]
    maxPayments: Optional[int]
    status: str
    externalReference: Optional[str]
    dateCreated: str
    deleted: Optional[bool]


class CreateSubscriptionInput(TypedDict, total=False):
    """Input para criar assinatura."""
    customer: str  # Required - Customer ID
    billingType: str  # Required
    value: float  # Required
    nextDueDate: str  # Required - YYYY-MM-DD
    cycle: str  # Required
    description: Optional[str]
    endDate: Optional[str]  # YYYY-MM-DD
    maxPayments: Optional[int]
    externalReference: Optional[str]
    discount: Optional[DiscountConfig]
    fine: Optional[FineConfig]
    interest: Optional[InterestConfig]


class UpdateSubscriptionInput(TypedDict, total=False):
    """Input para atualizar assinatura."""
    billingType: Optional[str]
    value: Optional[float]
    nextDueDate: Optional[str]
    cycle: Optional[str]
    description: Optional[str]
    endDate: Optional[str]
    maxPayments: Optional[int]
    externalReference: Optional[str]
    discount: Optional[DiscountConfig]


# ============================================================================
# TYPED DICTS - PAYMENT LINK
# ============================================================================

class CallbackConfig(TypedDict, total=False):
    """Configuração de callback."""
    successUrl: Optional[str]
    autoRedirect: Optional[bool]


class AsaasPaymentLink(TypedDict, total=False):
    """Link de pagamento Asaas."""
    id: str
    name: str
    url: str
    value: Optional[float]
    description: Optional[str]
    billingType: str
    chargeType: str
    subscriptionCycle: Optional[str]
    maxInstallmentCount: Optional[int]
    dueDateLimitDays: Optional[int]
    active: bool
    dateCreated: str
    deleted: Optional[bool]
    externalReference: Optional[str]
    notificationEnabled: Optional[bool]


class CreatePaymentLinkInput(TypedDict, total=False):
    """Input para criar link de pagamento."""
    name: str  # Required
    description: Optional[str]
    value: Optional[float]
    billingType: str  # Required
    chargeType: str  # Required
    subscriptionCycle: Optional[str]  # Obrigatório se chargeType = RECURRENT
    maxInstallmentCount: Optional[int]
    dueDateLimitDays: Optional[int]
    externalReference: Optional[str]
    notificationEnabled: Optional[bool]
    discount: Optional[DiscountConfig]
    fine: Optional[FineConfig]
    interest: Optional[InterestConfig]
    callback: Optional[CallbackConfig]


class UpdatePaymentLinkInput(TypedDict, total=False):
    """Input para atualizar link de pagamento."""
    name: Optional[str]
    description: Optional[str]
    value: Optional[float]
    billingType: Optional[str]
    chargeType: Optional[str]
    subscriptionCycle: Optional[str]
    maxInstallmentCount: Optional[int]
    dueDateLimitDays: Optional[int]
    externalReference: Optional[str]
    notificationEnabled: Optional[bool]
    active: Optional[bool]


# ============================================================================
# TYPED DICTS - PAYMENT
# ============================================================================

class AsaasPayment(TypedDict, total=False):
    """Cobrança Asaas."""
    id: str
    customer: str
    subscription: Optional[str]
    installment: Optional[str]
    paymentLink: Optional[str]
    value: float
    netValue: float
    originalValue: Optional[float]
    interestValue: Optional[float]
    billingType: str
    status: str
    dueDate: str
    originalDueDate: Optional[str]
    paymentDate: Optional[str]
    clientPaymentDate: Optional[str]
    confirmedDate: Optional[str]
    creditDate: Optional[str]
    estimatedCreditDate: Optional[str]
    invoiceUrl: Optional[str]
    bankSlipUrl: Optional[str]
    transactionReceiptUrl: Optional[str]
    invoiceNumber: Optional[str]
    nossoNumero: Optional[str]
    description: Optional[str]
    externalReference: Optional[str]
    installmentCount: Optional[int]
    installmentNumber: Optional[int]
    dateCreated: str
    deleted: Optional[bool]
    anticipated: Optional[bool]
    anticipable: Optional[bool]
    canBePaidAfterDueDate: Optional[bool]
    pixTransaction: Optional[str]
    pixQrCodeId: Optional[str]
    discount: Optional[DiscountConfig]
    fine: Optional[FineConfig]
    interest: Optional[InterestConfig]
    postalService: Optional[bool]
    refunds: Optional[List[Any]]


class CreatePaymentInput(TypedDict, total=False):
    """Input para criar cobrança."""
    customer: str  # Required
    billingType: str  # Required
    value: float  # Required
    dueDate: str  # Required - YYYY-MM-DD
    description: Optional[str]
    externalReference: Optional[str]
    installmentCount: Optional[int]
    installmentValue: Optional[float]
    discount: Optional[DiscountConfig]
    fine: Optional[FineConfig]
    interest: Optional[InterestConfig]


# ============================================================================
# TYPED DICTS - API RESPONSE
# ============================================================================

class AsaasListResponse(TypedDict):
    """Resposta de listagem Asaas."""
    object: str
    hasMore: bool
    totalCount: int
    limit: int
    offset: int
    data: List[Dict[str, Any]]


class AsaasErrorDetail(TypedDict):
    """Detalhe de erro Asaas."""
    code: str
    description: str


class AsaasError(TypedDict):
    """Erro Asaas."""
    errors: List[AsaasErrorDetail]


# ============================================================================
# TYPED DICTS - FILTERS
# ============================================================================

class ListPaymentsFilter(TypedDict, total=False):
    """Filtros para listar pagamentos."""
    customer: Optional[str]
    subscription: Optional[str]
    installment: Optional[str]
    status: Optional[str]
    billingType: Optional[str]
    offset: Optional[int]
    limit: Optional[int]
    # Datas em formato YYYY-MM-DD
    # Usar chaves como 'dueDate[ge]', 'dueDate[le]', etc.


# ============================================================================
# TYPED DICTS - DOCUMENTS
# ============================================================================

class AsaasDocumentFile(TypedDict, total=False):
    """Arquivo de documento Asaas."""
    publicAccessUrl: Optional[str]
    downloadUrl: Optional[str]


class AsaasDocument(TypedDict, total=False):
    """Documento anexado a cobrança."""
    id: str
    name: str
    availableAfterPayment: bool
    type: str
    file: Optional[AsaasDocumentFile]


# ============================================================================
# TYPED DICTS - WEBHOOK
# ============================================================================

# Eventos de webhook
WEBHOOK_EVENTS = [
    "PAYMENT_CREATED",
    "PAYMENT_AWAITING_RISK_ANALYSIS",
    "PAYMENT_APPROVED_BY_RISK_ANALYSIS",
    "PAYMENT_REPROVED_BY_RISK_ANALYSIS",
    "PAYMENT_AUTHORIZED",
    "PAYMENT_UPDATED",
    "PAYMENT_CONFIRMED",
    "PAYMENT_RECEIVED",
    "PAYMENT_CREDIT_CARD_CAPTURE_REFUSED",
    "PAYMENT_ANTICIPATED",
    "PAYMENT_OVERDUE",
    "PAYMENT_DELETED",
    "PAYMENT_RESTORED",
    "PAYMENT_REFUNDED",
    "PAYMENT_PARTIALLY_REFUNDED",
    "PAYMENT_REFUND_IN_PROGRESS",
    "PAYMENT_RECEIVED_IN_CASH_UNDONE",
    "PAYMENT_CHARGEBACK_REQUESTED",
    "PAYMENT_CHARGEBACK_DISPUTE",
    "PAYMENT_AWAITING_CHARGEBACK_REVERSAL",
    "PAYMENT_DUNNING_RECEIVED",
    "PAYMENT_DUNNING_REQUESTED",
    "PAYMENT_BANK_SLIP_VIEWED",
    "PAYMENT_CHECKOUT_VIEWED",
    "PAYMENT_SPLIT_DIVERGENCE_BLOCK",
    "PAYMENT_SPLIT_DIVERGENCE_BLOCK_FINISHED",
]


class AsaasWebhookPayload(TypedDict, total=False):
    """Payload de webhook Asaas."""
    event: str
    payment: Optional[AsaasPayment]
    subscription: Optional[AsaasSubscription]


# ============================================================================
# PIX QR CODE
# ============================================================================

class PixQrCodeResponse(TypedDict):
    """Resposta de QR Code PIX."""
    encodedImage: str
    payload: str
    expirationDate: str
