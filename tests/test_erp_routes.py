# tests/test_erp_routes.py
"""
TDD — ERP API Routes 2026-03-14

Contexto:
    Endpoints REST para ERP.
    Autenticação: tenant_id via header X-Tenant-ID.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi.testclient import TestClient


def make_service_mock(data: list = None):
    """Cria mock de Service."""
    if data is None:
        data = []
    mock = MagicMock()
    mock.list_customers = AsyncMock(return_value=data)
    mock.get_customer = AsyncMock(return_value=data[0] if data else None)
    mock.create_customer = AsyncMock(side_effect=lambda t, d: {**d, "id": 1, "tenant_id": t})
    mock.update_customer = AsyncMock(side_effect=lambda t, i, d: {**d, "id": i})
    mock.delete_customer = AsyncMock(return_value=True)

    mock.list_products = AsyncMock(return_value=data)
    mock.get_product = AsyncMock(return_value=data[0] if data else None)
    mock.create_product = AsyncMock(side_effect=lambda t, d: {**d, "id": 1, "tenant_id": t})
    mock.update_product = AsyncMock(side_effect=lambda t, i, d: {**d, "id": i})
    mock.delete_product = AsyncMock(return_value=True)

    mock.list_orders = AsyncMock(return_value=data)
    mock.get_order = AsyncMock(return_value=data[0] if data else None)
    mock.create_order = AsyncMock(side_effect=lambda t, d: {**d, "id": 1, "tenant_id": t, "status": "aberto"})
    mock.update_order = AsyncMock(side_effect=lambda t, i, d: {**d, "id": i})
    mock.close_order = AsyncMock(side_effect=lambda t, i, d: {"id": i, "status": "fechado", **d})
    mock.get_open_orders = AsyncMock(return_value=data)

    return mock


@pytest.fixture
def client():
    """TestClient com mocks injetados."""
    import importlib.util
    # Importar diretamente sem passar pelo __init__.py quebrado
    spec = importlib.util.spec_from_file_location(
        'erp', '/var/www/lazaro-real/apps/ia/app/api/routes/erp.py'
    )
    erp_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(erp_module)
    router = erp_module.router
    get_customer_service = erp_module.get_customer_service
    get_product_service = erp_module.get_product_service
    get_order_service = erp_module.get_order_service
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router, prefix="/api/erp")

    mock_customer_service = make_service_mock([{"id": 1, "nome": "João", "tipo": "cliente"}])
    mock_product_service = make_service_mock([{"id": 1, "sku": "AC-01", "nome": "Ar"}])
    mock_order_service = make_service_mock([{"id": 1, "tipo": "venda", "status": "aberto", "total": 100}])

    app.dependency_overrides[get_customer_service] = lambda: mock_customer_service
    app.dependency_overrides[get_product_service] = lambda: mock_product_service
    app.dependency_overrides[get_order_service] = lambda: mock_order_service

    return TestClient(app)


class TestCustomerRoutes:
    """Testes para /api/erp/customers."""

    def test_list_customers(self, client):
        """GET /customers retorna lista."""
        response = client.get("/api/erp/customers", headers={"X-Tenant-ID": "aluga_ar"})
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_list_customers_requires_tenant(self, client):
        """GET /customers sem tenant retorna 400."""
        response = client.get("/api/erp/customers")
        assert response.status_code == 400

    def test_get_customer(self, client):
        """GET /customers/{id} retorna cliente."""
        response = client.get("/api/erp/customers/1", headers={"X-Tenant-ID": "aluga_ar"})
        assert response.status_code == 200
        assert response.json()["nome"] == "João"

    def test_create_customer(self, client):
        """POST /customers cria cliente."""
        response = client.post(
            "/api/erp/customers",
            json={"tipo": "cliente", "nome": "Novo"},
            headers={"X-Tenant-ID": "aluga_ar"},
        )
        assert response.status_code == 201
        assert response.json()["id"] == 1

    def test_update_customer(self, client):
        """PUT /customers/{id} atualiza cliente."""
        response = client.put(
            "/api/erp/customers/1",
            json={"nome": "Atualizado"},
            headers={"X-Tenant-ID": "aluga_ar"},
        )
        assert response.status_code == 200

    def test_delete_customer(self, client):
        """DELETE /customers/{id} remove cliente."""
        response = client.delete("/api/erp/customers/1", headers={"X-Tenant-ID": "aluga_ar"})
        assert response.status_code == 204


class TestProductRoutes:
    """Testes para /api/erp/products."""

    def test_list_products(self, client):
        """GET /products retorna lista."""
        response = client.get("/api/erp/products", headers={"X-Tenant-ID": "aluga_ar"})
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_get_product(self, client):
        """GET /products/{id} retorna produto."""
        response = client.get("/api/erp/products/1", headers={"X-Tenant-ID": "aluga_ar"})
        assert response.status_code == 200
        assert response.json()["sku"] == "AC-01"

    def test_create_product(self, client):
        """POST /products cria produto."""
        response = client.post(
            "/api/erp/products",
            json={"sku": "NOVO-01", "nome": "Produto", "tipo": "produto", "preco_venda": 100},
            headers={"X-Tenant-ID": "aluga_ar"},
        )
        assert response.status_code == 201

    def test_update_product(self, client):
        """PUT /products/{id} atualiza produto."""
        response = client.put(
            "/api/erp/products/1",
            json={"nome": "Atualizado"},
            headers={"X-Tenant-ID": "aluga_ar"},
        )
        assert response.status_code == 200

    def test_delete_product(self, client):
        """DELETE /products/{id} remove produto."""
        response = client.delete("/api/erp/products/1", headers={"X-Tenant-ID": "aluga_ar"})
        assert response.status_code == 204


class TestOrderRoutes:
    """Testes para /api/erp/orders."""

    def test_list_orders(self, client):
        """GET /orders retorna lista."""
        response = client.get("/api/erp/orders", headers={"X-Tenant-ID": "aluga_ar"})
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_get_order(self, client):
        """GET /orders/{id} retorna pedido."""
        response = client.get("/api/erp/orders/1", headers={"X-Tenant-ID": "aluga_ar"})
        assert response.status_code == 200
        assert response.json()["tipo"] == "venda"

    def test_create_order(self, client):
        """POST /orders cria pedido."""
        response = client.post(
            "/api/erp/orders",
            json={"tipo": "venda", "items": []},
            headers={"X-Tenant-ID": "aluga_ar"},
        )
        assert response.status_code == 201
        assert response.json()["status"] == "aberto"

    def test_update_order(self, client):
        """PUT /orders/{id} atualiza pedido."""
        response = client.put(
            "/api/erp/orders/1",
            json={"observacoes": "Urgente"},
            headers={"X-Tenant-ID": "aluga_ar"},
        )
        assert response.status_code == 200

    def test_close_order(self, client):
        """POST /orders/{id}/close fecha pedido."""
        response = client.post(
            "/api/erp/orders/1/close",
            json={"valor_pago": 100, "forma_pagamento": "pix"},
            headers={"X-Tenant-ID": "aluga_ar"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "fechado"


class TestDashboardRoute:
    """Testes para /api/erp/dashboard."""

    def test_get_dashboard(self, client):
        """GET /dashboard retorna totais."""
        response = client.get("/api/erp/dashboard", headers={"X-Tenant-ID": "aluga_ar"})
        assert response.status_code == 200
        data = response.json()
        assert "vendas_hoje" in data
        assert "total_clientes" in data
