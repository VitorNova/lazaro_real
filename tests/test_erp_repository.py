# tests/test_erp_repository.py
"""
TDD — ERP Repository 2026-03-14

Contexto:
    Repository para queries Supabase das tabelas ERP.
    Todas as queries filtram por tenant_id.

Tabelas:
    - erp_customers
    - erp_products
    - erp_orders
"""

import pytest
from unittest.mock import MagicMock, AsyncMock
from decimal import Decimal


def make_supabase_mock(table_data: dict) -> MagicMock:
    """Cria mock do Supabase com dados por tabela."""
    mock = MagicMock()

    def table_side_effect(table_name):
        t = MagicMock()
        data = table_data.get(table_name, [])
        resp = MagicMock()
        resp.data = data

        # SELECT - configurar para retornar self em cada método encadeado
        select_mock = MagicMock()
        select_mock.eq.return_value = select_mock
        select_mock.limit.return_value = select_mock
        select_mock.execute.return_value = resp
        t.select.return_value = select_mock

        # INSERT
        def insert_fn(data_to_insert):
            insert_mock = MagicMock()
            insert_resp = MagicMock()
            inserted = {**data_to_insert, "id": 1}
            insert_resp.data = [inserted]
            insert_mock.execute.return_value = insert_resp
            return insert_mock
        t.insert.side_effect = insert_fn

        # UPDATE
        def update_fn(data_to_update):
            update_mock = MagicMock()
            eq_mock = MagicMock()
            update_resp = MagicMock()
            updated = {**data_to_update, "id": 1}
            update_resp.data = [updated]
            eq_mock.execute.return_value = update_resp
            update_mock.eq.return_value = eq_mock
            return update_mock
        t.update.side_effect = update_fn

        # DELETE
        delete_mock = MagicMock()
        delete_eq = MagicMock()
        delete_resp = MagicMock()
        delete_resp.data = []
        delete_eq.execute.return_value = delete_resp
        delete_mock.eq.return_value = delete_eq
        t.delete.return_value = delete_mock

        return t

    mock.table.side_effect = table_side_effect
    return mock


class TestCustomerRepository:
    """Testes para CustomerRepository."""

    @pytest.mark.asyncio
    async def test_list_customers_by_tenant(self):
        """list_customers retorna apenas clientes do tenant."""
        from apps.ia.app.domain.erp.repository import CustomerRepository

        mock_db = make_supabase_mock({
            "erp_customers": [
                {"id": 1, "tenant_id": "aluga_ar", "nome": "João"},
                {"id": 2, "tenant_id": "aluga_ar", "nome": "Maria"},
            ]
        })

        repo = CustomerRepository(mock_db)
        customers = await repo.list_customers("aluga_ar")

        assert len(customers) == 2
        mock_db.table.assert_called_with("erp_customers")

    @pytest.mark.asyncio
    async def test_get_customer_by_id(self):
        """get_customer retorna cliente por ID."""
        from apps.ia.app.domain.erp.repository import CustomerRepository

        mock_db = make_supabase_mock({
            "erp_customers": [{"id": 1, "tenant_id": "aluga_ar", "nome": "João"}]
        })

        repo = CustomerRepository(mock_db)
        customer = await repo.get_customer("aluga_ar", 1)

        assert customer["nome"] == "João"

    @pytest.mark.asyncio
    async def test_create_customer(self):
        """create_customer insere novo cliente."""
        from apps.ia.app.domain.erp.repository import CustomerRepository

        mock_db = make_supabase_mock({"erp_customers": []})

        repo = CustomerRepository(mock_db)
        customer = await repo.create_customer({
            "tenant_id": "aluga_ar",
            "tipo": "cliente",
            "nome": "Novo Cliente",
        })

        assert customer["id"] == 1
        assert customer["nome"] == "Novo Cliente"

    @pytest.mark.asyncio
    async def test_update_customer(self):
        """update_customer atualiza cliente existente."""
        from apps.ia.app.domain.erp.repository import CustomerRepository

        mock_db = make_supabase_mock({"erp_customers": []})

        repo = CustomerRepository(mock_db)
        customer = await repo.update_customer("aluga_ar", 1, {"nome": "Nome Atualizado"})

        assert customer["nome"] == "Nome Atualizado"

    @pytest.mark.asyncio
    async def test_delete_customer(self):
        """delete_customer remove cliente."""
        from apps.ia.app.domain.erp.repository import CustomerRepository

        mock_db = make_supabase_mock({"erp_customers": []})

        repo = CustomerRepository(mock_db)
        result = await repo.delete_customer("aluga_ar", 1)

        assert result is True


class TestProductRepository:
    """Testes para ProductRepository."""

    @pytest.mark.asyncio
    async def test_list_products_by_tenant(self):
        """list_products retorna apenas produtos do tenant."""
        from apps.ia.app.domain.erp.repository import ProductRepository

        mock_db = make_supabase_mock({
            "erp_products": [
                {"id": 1, "tenant_id": "aluga_ar", "sku": "AC-01", "nome": "Ar"},
            ]
        })

        repo = ProductRepository(mock_db)
        products = await repo.list_products("aluga_ar")

        assert len(products) == 1
        assert products[0]["sku"] == "AC-01"

    @pytest.mark.asyncio
    async def test_get_product_by_sku(self):
        """get_product_by_sku retorna produto por SKU."""
        from apps.ia.app.domain.erp.repository import ProductRepository

        mock_db = make_supabase_mock({
            "erp_products": [{"id": 1, "tenant_id": "aluga_ar", "sku": "AC-01"}]
        })

        repo = ProductRepository(mock_db)
        product = await repo.get_product_by_sku("aluga_ar", "AC-01")

        assert product["sku"] == "AC-01"

    @pytest.mark.asyncio
    async def test_create_product(self):
        """create_product insere novo produto."""
        from apps.ia.app.domain.erp.repository import ProductRepository

        mock_db = make_supabase_mock({"erp_products": []})

        repo = ProductRepository(mock_db)
        product = await repo.create_product({
            "tenant_id": "aluga_ar",
            "sku": "NOVO-01",
            "nome": "Produto Novo",
            "tipo": "produto",
            "preco_venda": 100.00,
        })

        assert product["id"] == 1
        assert product["sku"] == "NOVO-01"


class TestOrderRepository:
    """Testes para OrderRepository."""

    @pytest.mark.asyncio
    async def test_list_orders_by_tenant(self):
        """list_orders retorna apenas pedidos do tenant."""
        from apps.ia.app.domain.erp.repository import OrderRepository

        mock_db = make_supabase_mock({
            "erp_orders": [
                {"id": 1, "tenant_id": "aluga_ar", "tipo": "venda", "status": "aberto"},
                {"id": 2, "tenant_id": "aluga_ar", "tipo": "os", "status": "fechado"},
            ]
        })

        repo = OrderRepository(mock_db)
        orders = await repo.list_orders("aluga_ar")

        assert len(orders) == 2

    @pytest.mark.asyncio
    async def test_list_orders_by_status(self):
        """list_orders filtra por status."""
        from apps.ia.app.domain.erp.repository import OrderRepository

        mock_db = make_supabase_mock({
            "erp_orders": [
                {"id": 1, "tenant_id": "aluga_ar", "status": "aberto"},
            ]
        })

        repo = OrderRepository(mock_db)
        orders = await repo.list_orders("aluga_ar", status="aberto")

        assert len(orders) == 1

    @pytest.mark.asyncio
    async def test_create_order(self):
        """create_order insere novo pedido."""
        from apps.ia.app.domain.erp.repository import OrderRepository

        mock_db = make_supabase_mock({"erp_orders": []})

        repo = OrderRepository(mock_db)
        order = await repo.create_order({
            "tenant_id": "aluga_ar",
            "customer_id": 1,
            "tipo": "venda",
            "status": "aberto",
            "items": [],
            "subtotal": 0,
            "desconto": 0,
            "total": 0,
            "valor_pago": 0,
        })

        assert order["id"] == 1
        assert order["tipo"] == "venda"

    @pytest.mark.asyncio
    async def test_close_order(self):
        """close_order atualiza status para fechado."""
        from apps.ia.app.domain.erp.repository import OrderRepository

        mock_db = make_supabase_mock({"erp_orders": []})

        repo = OrderRepository(mock_db)
        order = await repo.update_order("aluga_ar", 1, {
            "status": "fechado",
            "valor_pago": 1500.00,
            "forma_pagamento": "pix",
        })

        assert order["status"] == "fechado"
