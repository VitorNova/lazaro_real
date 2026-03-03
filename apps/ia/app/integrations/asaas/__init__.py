# apps/ia/app/integrations/asaas/__init__.py
"""
Integração Asaas - Cliente HTTP para pagamentos.

Uso:
    from app.integrations.asaas import AsaasClient, get_asaas_client

    # Singleton (usa config do settings)
    client = get_asaas_client()
    customer = await client.get_customer("cus_xxxxx")

    # Instância customizada
    client = AsaasClient(api_key="sua_key")

Features:
- Rate limiting interno (30 req/min)
- Retry com backoff exponencial
- Tipos tipados (TypedDict)
"""

from .client import (
    AsaasClient,
    create_asaas_client,
    get_asaas_client,
)
from .rate_limiter import (
    RateLimiter,
    get_rate_limiter,
)
from .types import (
    # Constantes
    ASAAS_PRODUCTION_URL,
    ASAAS_SANDBOX_URL,
    MAX_RETRIES,
    RATE_LIMIT_MAX_REQUESTS,
    RATE_LIMIT_WINDOW_S,
    RETRY_DELAY_S,
    RETRYABLE_STATUS_CODES,
    WEBHOOK_EVENTS,
    # Enums
    BillingType,
    ChargeType,
    Cycle,
    PaymentLinkStatus,
    PaymentStatus,
    SubscriptionStatus,
    # TypedDicts - Customer
    AsaasCustomer,
    CreateCustomerInput,
    UpdateCustomerInput,
    # TypedDicts - Subscription
    AsaasSubscription,
    CreateSubscriptionInput,
    UpdateSubscriptionInput,
    # TypedDicts - Payment
    AsaasPayment,
    CreatePaymentInput,
    # TypedDicts - Payment Link
    AsaasPaymentLink,
    CreatePaymentLinkInput,
    UpdatePaymentLinkInput,
    # TypedDicts - Config
    DiscountConfig,
    FineConfig,
    InterestConfig,
    CallbackConfig,
    # TypedDicts - API Response
    AsaasListResponse,
    AsaasError,
    AsaasErrorDetail,
    # TypedDicts - Documents
    AsaasDocument,
    AsaasDocumentFile,
    # TypedDicts - Webhook
    AsaasWebhookPayload,
    # TypedDicts - PIX
    PixQrCodeResponse,
    # TypedDicts - Filters
    ListPaymentsFilter,
)

__all__ = [
    # Client
    "AsaasClient",
    "create_asaas_client",
    "get_asaas_client",
    # Rate Limiter
    "RateLimiter",
    "get_rate_limiter",
    # Constantes
    "ASAAS_PRODUCTION_URL",
    "ASAAS_SANDBOX_URL",
    "MAX_RETRIES",
    "RATE_LIMIT_MAX_REQUESTS",
    "RATE_LIMIT_WINDOW_S",
    "RETRY_DELAY_S",
    "RETRYABLE_STATUS_CODES",
    "WEBHOOK_EVENTS",
    # Enums
    "BillingType",
    "ChargeType",
    "Cycle",
    "PaymentLinkStatus",
    "PaymentStatus",
    "SubscriptionStatus",
    # TypedDicts - Customer
    "AsaasCustomer",
    "CreateCustomerInput",
    "UpdateCustomerInput",
    # TypedDicts - Subscription
    "AsaasSubscription",
    "CreateSubscriptionInput",
    "UpdateSubscriptionInput",
    # TypedDicts - Payment
    "AsaasPayment",
    "CreatePaymentInput",
    # TypedDicts - Payment Link
    "AsaasPaymentLink",
    "CreatePaymentLinkInput",
    "UpdatePaymentLinkInput",
    # TypedDicts - Config
    "DiscountConfig",
    "FineConfig",
    "InterestConfig",
    "CallbackConfig",
    # TypedDicts - API Response
    "AsaasListResponse",
    "AsaasError",
    "AsaasErrorDetail",
    # TypedDicts - Documents
    "AsaasDocument",
    "AsaasDocumentFile",
    # TypedDicts - Webhook
    "AsaasWebhookPayload",
    # TypedDicts - PIX
    "PixQrCodeResponse",
    # TypedDicts - Filters
    "ListPaymentsFilter",
]
