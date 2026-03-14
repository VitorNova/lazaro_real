# tests/test_erp_models.py
"""
TDD — ERP Pydantic Models 2026-03-14

Contexto:
    Validar models Pydantic para CRUD do ERP.
    Baseado em Purple-Stock (UX) e djangoSIGE (regras BR).

Models:
    - Customer: cliente/fornecedor
    - Product: produto/serviço
    - Order: venda/OS
"""

import pytest
from pydantic import ValidationError
from decimal import Decimal


class TestCustomerModels:
    """Testes para models de Cliente."""

    def test_customer_create_valid(self):
        """CustomerCreate aceita dados válidos."""
        from apps.ia.app.domain.erp.models import CustomerCreate

        customer = CustomerCreate(
            tenant_id="aluga_ar",
            tipo="cliente",
            nome="João Silva",
            cpf_cnpj="12345678901",
            celular="11999999999",
            email="joao@email.com",
        )

        assert customer.nome == "João Silva"
        assert customer.tipo == "cliente"

    def test_customer_create_minimal(self):
        """CustomerCreate funciona com campos mínimos."""
        from apps.ia.app.domain.erp.models import CustomerCreate

        customer = CustomerCreate(
            tenant_id="aluga_ar",
            tipo="cliente",
            nome="Maria",
        )

        assert customer.nome == "Maria"
        assert customer.email is None

    def test_customer_create_invalid_tipo(self):
        """CustomerCreate rejeita tipo inválido."""
        from apps.ia.app.domain.erp.models import CustomerCreate

        with pytest.raises(ValidationError) as exc_info:
            CustomerCreate(
                tenant_id="aluga_ar",
                tipo="invalido",
                nome="João",
            )

        assert "tipo" in str(exc_info.value)

    def test_customer_response_includes_id(self):
        """CustomerResponse inclui id e timestamps."""
        from apps.ia.app.domain.erp.models import CustomerResponse

        customer = CustomerResponse(
            id=1,
            tenant_id="aluga_ar",
            tipo="cliente",
            nome="João",
            ativo=True,
            created_at="2026-03-14T10:00:00Z",
        )

        assert customer.id == 1
        assert customer.ativo is True


class TestProductModels:
    """Testes para models de Produto."""

    def test_product_create_valid(self):
        """ProductCreate aceita dados válidos."""
        from apps.ia.app.domain.erp.models import ProductCreate

        product = ProductCreate(
            tenant_id="aluga_ar",
            sku="AC-12000",
            nome="Ar Condicionado 12000 BTUs",
            tipo="produto",
            preco_venda=Decimal("1500.00"),
        )

        assert product.sku == "AC-12000"
        assert product.preco_venda == Decimal("1500.00")

    def test_product_create_service(self):
        """ProductCreate aceita tipo serviço."""
        from apps.ia.app.domain.erp.models import ProductCreate

        product = ProductCreate(
            tenant_id="aluga_ar",
            sku="INST-01",
            nome="Instalação",
            tipo="servico",
            preco_venda=Decimal("300.00"),
        )

        assert product.tipo == "servico"

    def test_product_create_invalid_tipo(self):
        """ProductCreate rejeita tipo inválido."""
        from apps.ia.app.domain.erp.models import ProductCreate

        with pytest.raises(ValidationError):
            ProductCreate(
                tenant_id="aluga_ar",
                sku="X",
                nome="X",
                tipo="invalido",
                preco_venda=Decimal("100.00"),
            )

    def test_product_create_negative_price_rejected(self):
        """ProductCreate rejeita preço negativo."""
        from apps.ia.app.domain.erp.models import ProductCreate

        with pytest.raises(ValidationError):
            ProductCreate(
                tenant_id="aluga_ar",
                sku="X",
                nome="X",
                tipo="produto",
                preco_venda=Decimal("-10.00"),
            )


class TestOrderModels:
    """Testes para models de Pedido/OS."""

    def test_order_create_valid(self):
        """OrderCreate aceita dados válidos."""
        from apps.ia.app.domain.erp.models import OrderCreate, OrderItem

        order = OrderCreate(
            tenant_id="aluga_ar",
            customer_id=1,
            tipo="venda",
            items=[
                OrderItem(
                    product_id=1,
                    sku="AC-12000",
                    nome="Ar Condicionado",
                    quantidade=1,
                    preco_unitario=Decimal("1500.00"),
                )
            ],
        )

        assert order.tipo == "venda"
        assert len(order.items) == 1
        assert order.items[0].subtotal == Decimal("1500.00")

    def test_order_create_os(self):
        """OrderCreate aceita tipo OS."""
        from apps.ia.app.domain.erp.models import OrderCreate

        order = OrderCreate(
            tenant_id="aluga_ar",
            customer_id=1,
            tipo="os",
            items=[],
        )

        assert order.tipo == "os"

    def test_order_create_invalid_tipo(self):
        """OrderCreate rejeita tipo inválido."""
        from apps.ia.app.domain.erp.models import OrderCreate

        with pytest.raises(ValidationError):
            OrderCreate(
                tenant_id="aluga_ar",
                customer_id=1,
                tipo="orcamento",
                items=[],
            )

    def test_order_item_calculates_subtotal(self):
        """OrderItem calcula subtotal automaticamente."""
        from apps.ia.app.domain.erp.models import OrderItem

        item = OrderItem(
            product_id=1,
            sku="AC-12000",
            nome="Ar Condicionado",
            quantidade=2,
            preco_unitario=Decimal("1500.00"),
        )

        assert item.subtotal == Decimal("3000.00")

    def test_order_item_with_discount(self):
        """OrderItem aplica desconto no subtotal."""
        from apps.ia.app.domain.erp.models import OrderItem

        item = OrderItem(
            product_id=1,
            sku="AC-12000",
            nome="Ar Condicionado",
            quantidade=1,
            preco_unitario=Decimal("1000.00"),
            desconto=Decimal("100.00"),
        )

        assert item.subtotal == Decimal("900.00")

    def test_order_response_includes_totals(self):
        """OrderResponse inclui totais calculados."""
        from apps.ia.app.domain.erp.models import OrderResponse, OrderItem

        order = OrderResponse(
            id=1,
            tenant_id="aluga_ar",
            customer_id=1,
            tipo="venda",
            status="aberto",
            items=[
                OrderItem(
                    product_id=1,
                    sku="AC-12000",
                    nome="Ar",
                    quantidade=2,
                    preco_unitario=Decimal("1000.00"),
                )
            ],
            subtotal=Decimal("2000.00"),
            desconto=Decimal("0"),
            total=Decimal("2000.00"),
            valor_pago=Decimal("0"),
            created_at="2026-03-14T10:00:00Z",
        )

        assert order.total == Decimal("2000.00")
        assert order.status == "aberto"


class TestOrderUpdate:
    """Testes para atualização de pedidos."""

    def test_order_close(self):
        """OrderUpdate permite fechar pedido."""
        from apps.ia.app.domain.erp.models import OrderUpdate

        update = OrderUpdate(
            status="fechado",
            valor_pago=Decimal("1500.00"),
            forma_pagamento="pix",
        )

        assert update.status == "fechado"
        assert update.forma_pagamento == "pix"

    def test_order_cancel(self):
        """OrderUpdate permite cancelar pedido."""
        from apps.ia.app.domain.erp.models import OrderUpdate

        update = OrderUpdate(
            status="cancelado",
            observacoes="Cliente desistiu",
        )

        assert update.status == "cancelado"
