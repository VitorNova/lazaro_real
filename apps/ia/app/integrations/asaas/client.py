# ╔════════════════════════════════════════════════════════════╗
# ║  CLIENTE ASAAS — Chamadas HTTP para API de pagamentos      ║
# ╚════════════════════════════════════════════════════════════╝
# apps/ia/app/integrations/asaas/client.py
"""
AsaasClient - Cliente HTTP para a API Asaas.

Refatorado de app/services/gateway_pagamento.py com:
- Rate limiter (30 req/min)
- Retry com backoff exponencial
- Tipos tipados

Baseado em apps/api/src/services/asaas/client.ts para paridade.
"""

import asyncio
from typing import Any, Dict, List, Optional

import httpx
import structlog

from .rate_limiter import RateLimiter, get_rate_limiter
from .types import (
    ASAAS_PRODUCTION_URL,
    MAX_RETRIES,
    RETRY_DELAY_S,
    RETRYABLE_STATUS_CODES,
    AsaasCustomer,
    AsaasDocument,
    AsaasPayment,
    AsaasPaymentLink,
    AsaasSubscription,
    CreateCustomerInput,
    CreatePaymentInput,
    CreatePaymentLinkInput,
    CreateSubscriptionInput,
    PixQrCodeResponse,
    UpdateCustomerInput,
    UpdatePaymentLinkInput,
    UpdateSubscriptionInput,
)

logger = structlog.get_logger(__name__)


class AsaasClient:
    """
    Cliente para a API do Asaas.

    Features:
    - Rate limiting interno (30 req/min)
    - Retry automático para erros transientes (429, 5xx)
    - Backoff exponencial
    - Logging estruturado

    Uso:
        client = AsaasClient(api_key="sua_api_key")
        customer = await client.get_customer("cus_xxxxx")
    """

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
        rate_limiter: Optional[RateLimiter] = None,
    ):
        """
        Inicializa o cliente Asaas.

        Args:
            api_key: Chave de API do Asaas.
            base_url: URL base da API (padrão: produção).
            timeout: Timeout para requisições em segundos.
            rate_limiter: Rate limiter customizado (usa singleton se None).
        """
        if not api_key:
            raise ValueError("api_key é obrigatório")

        self.api_key = api_key
        self.base_url = (base_url or ASAAS_PRODUCTION_URL).rstrip("/")
        self.timeout = timeout
        self.rate_limiter = rate_limiter or get_rate_limiter()

        self._headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "access_token": self.api_key,
        }

        logger.info("asaas_client_initialized",
            integration="asaas",
            base_url=self.base_url)

    # ========================================================================
    # HTTP CORE
    # ========================================================================

    async def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Executa requisição HTTP com rate limiting e retry.
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        last_error: Optional[Exception] = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                # Aplicar rate limiter ANTES de cada tentativa
                await self.rate_limiter.acquire()

                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.request(
                        method=method,
                        url=url,
                        headers=self._headers,
                        json=data,
                        params=params,
                    )
                    response.raise_for_status()

                    try:
                        return response.json()
                    except Exception:
                        return {"success": True, "raw": response.text}

            except httpx.HTTPStatusError as e:
                last_error = e
                status = e.response.status_code

                # Tratamento especial para 429 (rate limit da API)
                if status == 429:
                    # Backoff exponencial até 30s
                    wait_time = min(30.0, RETRY_DELAY_S * (3 ** attempt))
                    logger.warning("asaas_rate_limited",
                        integration="asaas",
                        wait_time_seconds=wait_time,
                        endpoint=endpoint,
                        attempt=attempt,
                        max_retries=MAX_RETRIES)
                    await asyncio.sleep(wait_time)
                    continue

                # Retry para outros erros transientes
                if status in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES:
                    delay = RETRY_DELAY_S * attempt
                    logger.warning("asaas_request_retry",
                        integration="asaas",
                        method=method,
                        endpoint=endpoint,
                        status_code=status,
                        attempt=attempt,
                        delay_seconds=delay)
                    await asyncio.sleep(delay)
                    continue

                # Log erro e re-raise
                logger.error("asaas_request_failed",
                    integration="asaas",
                    method=method,
                    endpoint=endpoint,
                    status_code=status,
                    response_text=e.response.text[:500])
                raise

            except httpx.RequestError as e:
                last_error = e
                error_type = type(e).__name__

                if attempt < MAX_RETRIES:
                    delay = RETRY_DELAY_S * attempt
                    logger.warning("asaas_request_network_retry",
                        integration="asaas",
                        method=method,
                        endpoint=endpoint,
                        error_type=error_type,
                        attempt=attempt,
                        delay_seconds=delay)
                    await asyncio.sleep(delay)
                    continue

                logger.error("asaas_request_network_failed",
                    integration="asaas",
                    method=method,
                    endpoint=endpoint,
                    error=str(e))
                raise

        raise last_error or Exception("AsaasClient request failed")

    async def _get(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """GET request."""
        return await self._request("GET", endpoint, params=params)

    async def _post(
        self, endpoint: str, data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """POST request."""
        return await self._request("POST", endpoint, data=data)

    async def _put(
        self, endpoint: str, data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """PUT request."""
        return await self._request("PUT", endpoint, data=data)

    async def _delete(self, endpoint: str) -> Dict[str, Any]:
        """DELETE request."""
        return await self._request("DELETE", endpoint)

    # ========================================================================
    # CUSTOMERS
    # ========================================================================

    async def create_customer(self, data: CreateCustomerInput) -> AsaasCustomer:
        """Cria um novo cliente."""
        return await self._post("/customers", dict(data))

    async def get_customer(self, customer_id: str) -> Optional[AsaasCustomer]:
        """Obtém um cliente por ID."""
        try:
            return await self._get(f"/customers/{customer_id}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    async def find_customer_by_email(self, email: str) -> Optional[AsaasCustomer]:
        """Busca cliente por email."""
        result = await self._get("/customers", params={"email": email})
        data = result.get("data", [])
        return data[0] if data else None

    async def find_customer_by_cpf_cnpj(self, cpf_cnpj: str) -> Optional[AsaasCustomer]:
        """Busca cliente por CPF/CNPJ."""
        result = await self._get("/customers", params={"cpfCnpj": cpf_cnpj})
        data = result.get("data", [])
        return data[0] if data else None

    async def get_or_create_customer(self, data: CreateCustomerInput) -> AsaasCustomer:
        """Busca ou cria cliente por email/CPF."""
        if data.get("email"):
            existing = await self.find_customer_by_email(data["email"])
            if existing:
                return existing
        if data.get("cpfCnpj"):
            existing = await self.find_customer_by_cpf_cnpj(data["cpfCnpj"])
            if existing:
                return existing
        return await self.create_customer(data)

    async def update_customer(
        self, customer_id: str, data: UpdateCustomerInput
    ) -> AsaasCustomer:
        """Atualiza um cliente."""
        return await self._put(f"/customers/{customer_id}", dict(data))

    async def list_customers(
        self, offset: int = 0, limit: int = 100
    ) -> Dict[str, Any]:
        """Lista clientes com paginação."""
        return await self._get("/customers", params={"offset": offset, "limit": limit})

    # ========================================================================
    # PAYMENTS
    # ========================================================================

    async def create_payment(self, data: CreatePaymentInput) -> AsaasPayment:
        """Cria uma nova cobrança."""
        result = await self._post("/payments", dict(data))
        payment_id = result.get("id")
        logger.info("asaas_payment_created",
            integration="asaas",
            payment_id=payment_id,
            customer_id=data.get("customer"),
            value=data.get("value"),
            due_date=data.get("dueDate"),
            billing_type=data.get("billingType"))
        return result

    async def get_payment(self, payment_id: str) -> Optional[AsaasPayment]:
        """Obtém uma cobrança por ID."""
        try:
            result = await self._get(f"/payments/{payment_id}")
            logger.debug("asaas_payment_retrieved",
                integration="asaas",
                payment_id=payment_id,
                status=result.get("status") if result else None)
            return result
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.debug("asaas_payment_not_found",
                    integration="asaas",
                    payment_id=payment_id)
                return None
            raise

    async def list_payments(
        self,
        customer_id: Optional[str] = None,
        status: Optional[str] = None,
        subscription: Optional[str] = None,
        offset: int = 0,
        limit: int = 100,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Lista cobranças com filtros."""
        params: Dict[str, Any] = {"offset": offset, "limit": limit}
        if customer_id:
            params["customer"] = customer_id
        if status:
            params["status"] = status
        if subscription:
            params["subscription"] = subscription
        params.update(kwargs)
        return await self._get("/payments", params=params)

    async def list_payments_by_customer(self, customer_id: str) -> List[AsaasPayment]:
        """Lista todas as cobranças de um cliente."""
        result = await self.list_payments(customer_id=customer_id)
        return result.get("data", [])

    async def list_all_payments(
        self,
        customer_id: Optional[str] = None,
        status: Optional[str] = None,
        max_pages: int = 10,
        limit: int = 100,
        **kwargs: Any,
    ) -> List[AsaasPayment]:
        """Lista todas as cobranças com paginação automática."""
        all_payments: List[AsaasPayment] = []
        offset = 0

        for _ in range(max_pages):
            result = await self.list_payments(
                customer_id=customer_id,
                status=status,
                offset=offset,
                limit=limit,
                **kwargs,
            )
            all_payments.extend(result.get("data", []))

            if not result.get("hasMore", False):
                break

            offset += limit

        return all_payments

    async def cancel_payment(self, payment_id: str) -> None:
        """Cancela uma cobrança."""
        try:
            await self._delete(f"/payments/{payment_id}")
            logger.info("asaas_payment_cancelled",
                integration="asaas",
                payment_id=payment_id)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning("asaas_payment_cancel_not_found",
                    integration="asaas",
                    payment_id=payment_id)
                return
            raise

    async def get_pix_qrcode(self, payment_id: str) -> Optional[PixQrCodeResponse]:
        """Obtém QR Code PIX de uma cobrança."""
        try:
            return await self._get(f"/payments/{payment_id}/pixQrCode")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    # ========================================================================
    # SUBSCRIPTIONS
    # ========================================================================

    async def create_subscription(
        self, data: CreateSubscriptionInput
    ) -> AsaasSubscription:
        """Cria uma nova assinatura."""
        return await self._post("/subscriptions", dict(data))

    async def get_subscription(
        self, subscription_id: str
    ) -> Optional[AsaasSubscription]:
        """Obtém uma assinatura por ID."""
        try:
            return await self._get(f"/subscriptions/{subscription_id}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    async def update_subscription(
        self, subscription_id: str, data: UpdateSubscriptionInput
    ) -> AsaasSubscription:
        """Atualiza uma assinatura."""
        return await self._put(f"/subscriptions/{subscription_id}", dict(data))

    async def cancel_subscription(self, subscription_id: str) -> None:
        """Cancela uma assinatura."""
        try:
            await self._delete(f"/subscriptions/{subscription_id}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return
            raise

    async def list_all_subscriptions(
        self,
        status: str = "ACTIVE",
        max_pages: int = 10,
        limit: int = 100,
    ) -> List[AsaasSubscription]:
        """Lista todas as subscriptions com paginação automática."""
        all_subs: List[AsaasSubscription] = []
        offset = 0

        for _ in range(max_pages):
            result = await self._get(
                "/subscriptions",
                params={"status": status, "offset": offset, "limit": limit},
            )
            all_subs.extend(result.get("data", []))

            if not result.get("hasMore", False):
                break

            offset += limit

        return all_subs

    async def list_subscriptions_by_customer(
        self, customer_id: str
    ) -> List[AsaasSubscription]:
        """Lista todas as assinaturas de um cliente."""
        result = await self._get("/subscriptions", params={"customer": customer_id})
        return result.get("data", [])

    async def list_payments_by_subscription(
        self, subscription_id: str
    ) -> List[AsaasPayment]:
        """Lista todos os pagamentos de uma assinatura."""
        result = await self._get("/payments", params={"subscription": subscription_id})
        return result.get("data", [])

    # ========================================================================
    # PAYMENT LINKS
    # ========================================================================

    async def create_payment_link(
        self, data: CreatePaymentLinkInput
    ) -> AsaasPaymentLink:
        """Cria um novo link de pagamento."""
        return await self._post("/paymentLinks", dict(data))

    async def get_payment_link(self, link_id: str) -> Optional[AsaasPaymentLink]:
        """Obtém um link de pagamento por ID."""
        try:
            return await self._get(f"/paymentLinks/{link_id}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    async def update_payment_link(
        self, link_id: str, data: UpdatePaymentLinkInput
    ) -> AsaasPaymentLink:
        """Atualiza um link de pagamento."""
        return await self._put(f"/paymentLinks/{link_id}", dict(data))

    async def delete_payment_link(self, link_id: str) -> None:
        """Deleta um link de pagamento."""
        try:
            await self._delete(f"/paymentLinks/{link_id}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return
            raise

    async def list_payment_links(
        self, offset: int = 0, limit: int = 100
    ) -> Dict[str, Any]:
        """Lista links de pagamento."""
        return await self._get(
            "/paymentLinks", params={"offset": offset, "limit": limit}
        )

    # ========================================================================
    # DOCUMENTS
    # ========================================================================

    async def list_payment_documents(self, payment_id: str) -> List[AsaasDocument]:
        """Lista documentos anexados a uma cobrança."""
        try:
            result = await self._get(f"/payments/{payment_id}/documents")
            return result.get("data", [])
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return []
            raise

    async def download_document(self, url: str) -> bytes:
        """Baixa um documento por URL."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(url, headers=self._headers)
            response.raise_for_status()
            return response.content

    # ========================================================================
    # CONNECTION TEST
    # ========================================================================

    async def test_connection(self) -> Dict[str, Any]:
        """Testa a conexão com a API do Asaas."""
        try:
            result = await self._get("/customers", params={"limit": 1})
            return {
                "success": True,
                "message": "Conexão com Asaas estabelecida com sucesso!",
                "total_customers": result.get("totalCount", 0),
            }
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == 401:
                return {
                    "success": False,
                    "message": "API Key inválida ou não autorizada",
                }
            if status == 403:
                return {
                    "success": False,
                    "message": "Acesso negado. Verifique permissões da API Key",
                }
            return {"success": False, "message": f"Erro HTTP {status}"}
        except Exception as e:
            return {"success": False, "message": str(e)}


# ============================================================================
# FACTORY & SINGLETON
# ============================================================================

_asaas_client: Optional[AsaasClient] = None


def get_asaas_client(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> AsaasClient:
    """
    Retorna instância singleton do AsaasClient.

    Na primeira chamada, requer api_key. Chamadas subsequentes
    retornam a mesma instância.
    """
    global _asaas_client

    if _asaas_client is None:
        if not api_key:
            # Import config apenas quando necessário
            from app.config import settings
            api_key = settings.asaas_api_key
            base_url = base_url or settings.asaas_api_url

        if not api_key:
            raise ValueError("ASAAS_API_KEY é obrigatório")

        _asaas_client = AsaasClient(api_key=api_key, base_url=base_url)

    return _asaas_client


def create_asaas_client(
    api_key: str,
    base_url: Optional[str] = None,
) -> AsaasClient:
    """
    Cria nova instância do AsaasClient (não singleton).

    Útil quando você precisa de um cliente com API key diferente.
    """
    return AsaasClient(api_key=api_key, base_url=base_url)
