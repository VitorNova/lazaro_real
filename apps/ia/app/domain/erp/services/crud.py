# apps/ia/app/domain/erp/services/crud.py
"""
Services CRUD para ERP.

Encapsulam lógica de negócio e usam Repository para acesso ao banco.
"""

from typing import Optional, List, Dict, Any
from decimal import Decimal


class CustomerService:
    """Service para operações com clientes."""

    def __init__(self, repository):
        self.repo = repository

    async def list_customers(
        self,
        tenant_id: str,
        tipo: Optional[str] = None,
        ativo: bool = True,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Lista clientes do tenant."""
        return await self.repo.list_customers(tenant_id)

    async def get_customer(
        self, tenant_id: str, customer_id: int
    ) -> Optional[Dict[str, Any]]:
        """Busca cliente por ID."""
        return await self.repo.get_customer(tenant_id, customer_id)

    async def create_customer(
        self, tenant_id: str, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Cria novo cliente."""
        data["tenant_id"] = tenant_id
        return await self.repo.create_customer(data)

    async def update_customer(
        self, tenant_id: str, customer_id: int, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Atualiza cliente existente."""
        return await self.repo.update_customer(tenant_id, customer_id, data)

    async def delete_customer(self, tenant_id: str, customer_id: int) -> bool:
        """Remove cliente."""
        return await self.repo.delete_customer(tenant_id, customer_id)


class ProductService:
    """Service para operações com produtos."""

    def __init__(self, repository):
        self.repo = repository

    async def list_products(
        self,
        tenant_id: str,
        tipo: Optional[str] = None,
        categoria: Optional[str] = None,
        ativo: bool = True,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Lista produtos do tenant."""
        return await self.repo.list_products(tenant_id)

    async def get_product(
        self, tenant_id: str, product_id: int
    ) -> Optional[Dict[str, Any]]:
        """Busca produto por ID."""
        return await self.repo.get_product(tenant_id, product_id)

    async def get_product_by_sku(
        self, tenant_id: str, sku: str
    ) -> Optional[Dict[str, Any]]:
        """Busca produto por SKU."""
        return await self.repo.get_product_by_sku(tenant_id, sku)

    async def create_product(
        self, tenant_id: str, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Cria novo produto."""
        data["tenant_id"] = tenant_id
        return await self.repo.create_product(data)

    async def update_product(
        self, tenant_id: str, product_id: int, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Atualiza produto existente."""
        return await self.repo.update_product(tenant_id, product_id, data)

    async def delete_product(self, tenant_id: str, product_id: int) -> bool:
        """Remove produto."""
        return await self.repo.delete_product(tenant_id, product_id)


class OrderService:
    """Service para operações com pedidos/OS."""

    def __init__(self, repository):
        self.repo = repository

    async def list_orders(
        self,
        tenant_id: str,
        status: Optional[str] = None,
        tipo: Optional[str] = None,
        customer_id: Optional[int] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Lista pedidos do tenant."""
        return await self.repo.list_orders(tenant_id)

    async def get_order(
        self, tenant_id: str, order_id: int
    ) -> Optional[Dict[str, Any]]:
        """Busca pedido por ID."""
        return await self.repo.get_order(tenant_id, order_id)

    async def create_order(
        self, tenant_id: str, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Cria novo pedido com cálculo de totais."""
        data["tenant_id"] = tenant_id

        # Calcular subtotal dos items
        items = data.get("items", [])
        subtotal = Decimal("0")
        for item in items:
            qty = Decimal(str(item.get("quantidade", 1)))
            price = Decimal(str(item.get("preco_unitario", 0)))
            item_discount = Decimal(str(item.get("desconto", 0)))
            subtotal += (qty * price) - item_discount

        # Aplicar desconto geral
        desconto = Decimal(str(data.get("desconto", 0)))
        total = subtotal - desconto

        data["subtotal"] = float(subtotal)
        data["total"] = float(total)
        data["status"] = data.get("status", "aberto")
        data["valor_pago"] = data.get("valor_pago", 0)

        return await self.repo.create_order(data)

    async def update_order(
        self, tenant_id: str, order_id: int, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Atualiza pedido existente."""
        return await self.repo.update_order(tenant_id, order_id, data)

    async def close_order(
        self, tenant_id: str, order_id: int, payment_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Fecha pedido com dados de pagamento."""
        data = {
            "status": "fechado",
            "valor_pago": payment_data.get("valor_pago", 0),
            "forma_pagamento": payment_data.get("forma_pagamento"),
        }
        return await self.repo.update_order(tenant_id, order_id, data)

    async def cancel_order(self, tenant_id: str, order_id: int) -> Dict[str, Any]:
        """Cancela pedido."""
        return await self.repo.update_order(tenant_id, order_id, {"status": "cancelado"})

    async def get_open_orders(self, tenant_id: str) -> List[Dict[str, Any]]:
        """Lista pedidos em aberto."""
        return await self.repo.get_open_orders(tenant_id)

    async def delete_order(self, tenant_id: str, order_id: int) -> bool:
        """Remove pedido."""
        return await self.repo.delete_order(tenant_id, order_id)
