"""
AsaasService - Servico de integracao com Asaas para pagamentos.

Este servico gerencia:
- Clientes (customers)
- Cobrancas (payments)
- Assinaturas (subscriptions)
- Links de pagamento (payment links)
- QR Code PIX
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

ASAAS_PRODUCTION_URL = "https://api.asaas.com/v3"
ASAAS_SANDBOX_URL = "https://sandbox.asaas.com/api/v3"

MAX_RETRIES = 3
RETRY_DELAY_S = 1.0
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class AsaasService:
    """
    Cliente para a API do Asaas.

    Suporta ambientes de producao e sandbox.
    Implementa retry automatico para erros transientes.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.api_key = api_key or settings.asaas_api_key
        self.base_url = (base_url or settings.asaas_api_url or ASAAS_PRODUCTION_URL).rstrip("/")
        self.timeout = timeout

        if not self.api_key:
            raise ValueError("ASAAS_API_KEY e obrigatorio.")

        self._headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "access_token": self.api_key,
        }

        logger.info(f"AsaasService inicializado: {self.base_url}")

    # ========================================================================
    # HTTP
    # ========================================================================

    async def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        last_error: Optional[Exception] = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
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
                if status in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES:
                    delay = RETRY_DELAY_S * attempt
                    logger.warning(f"[Asaas] {method} {endpoint} -> {status}, retry {attempt} em {delay}s")
                    await asyncio.sleep(delay)
                    continue
                logger.error(f"[Asaas] {method} {endpoint} -> {status}: {e.response.text}")
                raise

            except httpx.RequestError as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    delay = RETRY_DELAY_S * attempt
                    logger.warning(f"[Asaas] {method} {endpoint} erro conexao, retry {attempt} em {delay}s")
                    await asyncio.sleep(delay)
                    continue
                logger.error(f"[Asaas] {method} {endpoint} erro: {e}")
                raise

        raise last_error or Exception("Asaas request failed")

    async def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self._request("GET", endpoint, params=params)

    async def _post(self, endpoint: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self._request("POST", endpoint, data=data)

    async def _put(self, endpoint: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self._request("PUT", endpoint, data=data)

    async def _delete(self, endpoint: str) -> Dict[str, Any]:
        return await self._request("DELETE", endpoint)

    # ========================================================================
    # CUSTOMERS
    # ========================================================================

    async def create_customer(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return await self._post("/customers", data)

    async def get_customer(self, customer_id: str) -> Optional[Dict[str, Any]]:
        try:
            return await self._get(f"/customers/{customer_id}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    async def find_customer_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        result = await self._get("/customers", params={"email": email})
        data = result.get("data", [])
        return data[0] if data else None

    async def find_customer_by_cpf_cnpj(self, cpf_cnpj: str) -> Optional[Dict[str, Any]]:
        result = await self._get("/customers", params={"cpfCnpj": cpf_cnpj})
        data = result.get("data", [])
        return data[0] if data else None

    async def get_or_create_customer(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if data.get("email"):
            existing = await self.find_customer_by_email(data["email"])
            if existing:
                return existing
        if data.get("cpfCnpj"):
            existing = await self.find_customer_by_cpf_cnpj(data["cpfCnpj"])
            if existing:
                return existing
        return await self.create_customer(data)

    async def list_customers(self, offset: int = 0, limit: int = 100) -> Dict[str, Any]:
        return await self._get("/customers", params={"offset": offset, "limit": limit})

    # ========================================================================
    # PAYMENTS
    # ========================================================================

    async def create_payment(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return await self._post("/payments", data)

    async def get_payment(self, payment_id: str) -> Optional[Dict[str, Any]]:
        try:
            return await self._get(f"/payments/{payment_id}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    async def list_payments(
        self,
        customer_id: Optional[str] = None,
        status: Optional[str] = None,
        offset: int = 0,
        limit: int = 100,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"offset": offset, "limit": limit}
        if customer_id:
            params["customer"] = customer_id
        if status:
            params["status"] = status
        params.update(kwargs)
        return await self._get("/payments", params=params)

    async def list_payments_by_customer(self, customer_id: str) -> List[Dict[str, Any]]:
        result = await self.list_payments(customer_id=customer_id)
        return result.get("data", [])

    async def cancel_payment(self, payment_id: str) -> None:
        try:
            await self._delete(f"/payments/{payment_id}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return
            raise

    async def get_pix_qrcode(self, payment_id: str) -> Optional[Dict[str, Any]]:
        try:
            return await self._get(f"/payments/{payment_id}/pixQrCode")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    # ========================================================================
    # SUBSCRIPTIONS
    # ========================================================================

    async def create_subscription(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return await self._post("/subscriptions", data)

    async def get_subscription(self, subscription_id: str) -> Optional[Dict[str, Any]]:
        try:
            return await self._get(f"/subscriptions/{subscription_id}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    async def cancel_subscription(self, subscription_id: str) -> None:
        try:
            await self._delete(f"/subscriptions/{subscription_id}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return
            raise

    # ========================================================================
    # SUBSCRIPTIONS (CONTRATOS)
    # ========================================================================

    async def list_subscriptions_by_customer(self, customer_id: str) -> List[Dict[str, Any]]:
        """Lista todas as assinaturas de um cliente."""
        result = await self._get("/subscriptions", params={"customer": customer_id})
        return result.get("data", [])

    async def list_payments_by_subscription(self, subscription_id: str) -> List[Dict[str, Any]]:
        """Lista todos os pagamentos de uma assinatura."""
        result = await self._get("/payments", params={"subscription": subscription_id})
        return result.get("data", [])

    # ========================================================================
    # DOCUMENTS
    # ========================================================================

    async def list_payment_documents(self, payment_id: str) -> List[Dict[str, Any]]:
        """Lista documentos anexados a um pagamento."""
        result = await self._get(f"/payments/{payment_id}/documents")
        return result.get("data", [])

    async def download_document(self, url: str) -> bytes:
        """Baixa um documento por URL (retorna bytes do arquivo)."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(url, headers=self._headers)
            response.raise_for_status()
            return response.content

    # ========================================================================
    # PAYMENT LINKS
    # ========================================================================

    async def create_payment_link(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return await self._post("/paymentLinks", data)

    async def get_payment_link(self, link_id: str) -> Optional[Dict[str, Any]]:
        try:
            return await self._get(f"/paymentLinks/{link_id}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    async def delete_payment_link(self, link_id: str) -> None:
        try:
            await self._delete(f"/paymentLinks/{link_id}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return
            raise

    # ========================================================================
    # CONNECTION TEST
    # ========================================================================

    async def test_connection(self) -> Dict[str, Any]:
        try:
            result = await self._get("/customers", params={"limit": 1})
            return {
                "success": True,
                "message": "Conexao com Asaas estabelecida com sucesso!",
                "total_customers": result.get("totalCount", 0),
            }
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == 401:
                return {"success": False, "message": "API Key invalida ou nao autorizada"}
            if status == 403:
                return {"success": False, "message": "Acesso negado. Verifique permissoes da API Key"}
            return {"success": False, "message": f"Erro HTTP {status}"}
        except Exception as e:
            return {"success": False, "message": str(e)}


# ============================================================================
# SINGLETON
# ============================================================================

_asaas_service: Optional[AsaasService] = None


def get_asaas_service(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> AsaasService:
    """Retorna instancia singleton do AsaasService."""
    global _asaas_service

    if _asaas_service is None:
        _asaas_service = AsaasService(api_key=api_key, base_url=base_url)

    return _asaas_service


def create_asaas_service(
    api_key: str,
    base_url: Optional[str] = None,
) -> AsaasService:
    """Cria nova instancia do AsaasService (nao singleton)."""
    return AsaasService(api_key=api_key, base_url=base_url)
