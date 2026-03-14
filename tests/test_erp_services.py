# tests/test_erp_services.py
"""
TDD — ERP Services 2026-03-14

Contexto:
    Services encapsulam lógica de negócio CRUD.
    Usam Repository para acesso ao banco.
    Validam dados com Pydantic models.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock
from decimal import Decimal


def make_repository_mock(data: list = None) -> MagicMock:
    """Cria mock de Repository."""
    if data is None:
        data = []
    mock = MagicMock()
    mock.list_customers = AsyncMock(return_value=data)
    mock.get_customer = AsyncMock(return_value=data[0] if data else None)
    mock.create_customer = AsyncMock(side_effect=lambda d: {**d, "id": 1})
    mock.update_customer = AsyncMock(side_effect=lambda t, i, d: {**d, "id": i})
    mock.delete_customer = AsyncMock(return_value=True)

    mock.list_products = AsyncMock(return_value=data)
    mock.get_product = AsyncMock(return_value=data[0] if data else None)
    mock.get_product_by_sku = AsyncMock(return_value=data[0] if data else None)
    mock.create_product = AsyncMock(side_effect=lambda d: {**d, "id": 1})
    mock.update_product = AsyncMock(side_effect=lambda t, i, d: {**d, "id": i})
    mock.delete_product = AsyncMock(return_value=True)

    mock.list_orders = AsyncMock(return_value=data)
    mock.get_order = AsyncMock(return_value=data[0] if data else None)
    mock.create_order = AsyncMock(side_effect=lambda d: {**d, "id": 1})
    mock.update_order = AsyncMock(side_effect=lambda t, i, d: {**d, "id": i})
    mock.delete_order = AsyncMock(return_value=True)
    mock.get_open_orders = AsyncMock(return_value=data)

    return mock


class TestCustomerService:
    """Testes para CustomerService."""

    @pytest.mark.asyncio
    async def test_list_customers(self):
        """list_customers retorna lista de clientes."""
        from apps.ia.app.domain.erp.services import CustomerService

        mock_repo = make_repository_mock([
            {"id": 1, "tenant_id": "aluga_ar", "nome": "João", "tipo": "cliente"},
        ])

        service = CustomerService(mock_repo)
        customers = await service.list_customers("aluga_ar")

        assert len(customers) == 1
        mock_repo.list_customers.assert_called_once_with("aluga_ar")

    @pytest.mark.asyncio
    async def test_get_customer(self):
        """get_customer retorna cliente por ID."""
        from apps.ia.app.domain.erp.services import CustomerService

        mock_repo = make_repository_mock([
            {"id": 1, "tenant_id": "aluga_ar", "nome": "João"},
        ])

        service = CustomerService(mock_repo)
        customer = await service.get_customer("aluga_ar", 1)

        assert customer["nome"] == "João"
        mock_repo.get_customer.assert_called_once_with("aluga_ar", 1)

    @pytest.mark.asyncio
    async def test_create_customer_valid(self):
        """create_customer cria cliente com dados válidos."""
        from apps.ia.app.domain.erp.services import CustomerService

        mock_repo = make_repository_mock([])

        service = CustomerService(mock_repo)
        customer = await service.create_customer("aluga_ar", {
            "tipo": "cliente",
            "nome": "Novo Cliente",
        })

        assert customer["id"] == 1
        assert customer["nome"] == "Novo Cliente"
        mock_repo.create_customer.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_customer_adds_tenant(self):
        """create_customer adiciona tenant_id automaticamente."""
        from apps.ia.app.domain.erp.services import CustomerService

        mock_repo = make_repository_mock([])

        service = CustomerService(mock_repo)
        await service.create_customer("aluga_ar", {
            "tipo": "cliente",
            "nome": "Cliente",
        })

        call_args = mock_repo.create_customer.call_args[0][0]
        assert call_args["tenant_id"] == "aluga_ar"

    @pytest.mark.asyncio
    async def test_update_customer(self):
        """update_customer atualiza cliente."""
        from apps.ia.app.domain.erp.services import CustomerService

        mock_repo = make_repository_mock([])

        service = CustomerService(mock_repo)
        customer = await service.update_customer("aluga_ar", 1, {"nome": "Atualizado"})

        assert customer["nome"] == "Atualizado"
        mock_repo.update_customer.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_customer(self):
        """delete_customer remove cliente."""
        from apps.ia.app.domain.erp.services import CustomerService

        mock_repo = make_repository_mock([])

        service = CustomerService(mock_repo)
        result = await service.delete_customer("aluga_ar", 1)

        assert result is True


class TestProductService:
    """Testes para ProductService."""

    @pytest.mark.asyncio
    async def test_list_products(self):
        """list_products retorna lista de produtos."""
        from apps.ia.app.domain.erp.services import ProductService

        mock_repo = make_repository_mock([
            {"id": 1, "tenant_id": "aluga_ar", "sku": "AC-01", "nome": "Ar"},
        ])

        service = ProductService(mock_repo)
        products = await service.list_products("aluga_ar")

        assert len(products) == 1

    @pytest.mark.asyncio
    async def test_get_product_by_sku(self):
        """get_product_by_sku retorna produto por SKU."""
        from apps.ia.app.domain.erp.services import ProductService

        mock_repo = make_repository_mock([
            {"id": 1, "tenant_id": "aluga_ar", "sku": "AC-01"},
        ])

        service = ProductService(mock_repo)
        product = await service.get_product_by_sku("aluga_ar", "AC-01")

        assert product["sku"] == "AC-01"

    @pytest.mark.asyncio
    async def test_create_product_adds_tenant(self):
        """create_product adiciona tenant_id automaticamente."""
        from apps.ia.app.domain.erp.services import ProductService

        mock_repo = make_repository_mock([])

        service = ProductService(mock_repo)
        await service.create_product("aluga_ar", {
            "sku": "NOVO-01",
            "nome": "Produto",
            "tipo": "produto",
            "preco_venda": 100.00,
        })

        call_args = mock_repo.create_product.call_args[0][0]
        assert call_args["tenant_id"] == "aluga_ar"


class TestOrderService:
    """Testes para OrderService."""

    @pytest.mark.asyncio
    async def test_list_orders(self):
        """list_orders retorna lista de pedidos."""
        from apps.ia.app.domain.erp.services import OrderService

        mock_repo = make_repository_mock([
            {"id": 1, "tenant_id": "aluga_ar", "tipo": "venda", "status": "aberto"},
        ])

        service = OrderService(mock_repo)
        orders = await service.list_orders("aluga_ar")

        assert len(orders) == 1

    @pytest.mark.asyncio
    async def test_create_order_calculates_totals(self):
        """create_order calcula subtotal e total."""
        from apps.ia.app.domain.erp.services import OrderService

        mock_repo = make_repository_mock([])

        service = OrderService(mock_repo)
        order = await service.create_order("aluga_ar", {
            "tipo": "venda",
            "items": [
                {"product_id": 1, "sku": "AC-01", "nome": "Ar", "quantidade": 2, "preco_unitario": 100.00},
            ],
        })

        call_args = mock_repo.create_order.call_args[0][0]
        assert call_args["subtotal"] == 200.00
        assert call_args["total"] == 200.00

    @pytest.mark.asyncio
    async def test_create_order_applies_discount(self):
        """create_order aplica desconto no total."""
        from apps.ia.app.domain.erp.services import OrderService

        mock_repo = make_repository_mock([])

        service = OrderService(mock_repo)
        order = await service.create_order("aluga_ar", {
            "tipo": "venda",
            "desconto": 50.00,
            "items": [
                {"product_id": 1, "sku": "AC-01", "nome": "Ar", "quantidade": 2, "preco_unitario": 100.00},
            ],
        })

        call_args = mock_repo.create_order.call_args[0][0]
        assert call_args["subtotal"] == 200.00
        assert call_args["total"] == 150.00

    @pytest.mark.asyncio
    async def test_close_order(self):
        """close_order fecha pedido com pagamento."""
        from apps.ia.app.domain.erp.services import OrderService

        mock_repo = make_repository_mock([])

        service = OrderService(mock_repo)
        order = await service.close_order("aluga_ar", 1, {
            "valor_pago": 150.00,
            "forma_pagamento": "pix",
        })

        call_args = mock_repo.update_order.call_args[0][2]
        assert call_args["status"] == "fechado"
        assert call_args["valor_pago"] == 150.00

    @pytest.mark.asyncio
    async def test_get_open_orders(self):
        """get_open_orders retorna pedidos em aberto."""
        from apps.ia.app.domain.erp.services import OrderService

        mock_repo = make_repository_mock([
            {"id": 1, "status": "aberto"},
        ])

        service = OrderService(mock_repo)
        orders = await service.get_open_orders("aluga_ar")

        assert len(orders) == 1
        mock_repo.get_open_orders.assert_called_once_with("aluga_ar")
