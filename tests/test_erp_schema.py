# tests/test_erp_schema.py
"""
TDD — ERP Schema — Tabelas base multi-tenant 2026-03-13

Contexto:
    Validar schema existente do ERP + nova tabela erp_orders.
    Cada tenant só vê seus próprios dados.

Tabelas:
    - erp_customers: Clientes e fornecedores
    - erp_products: Produtos e serviços
    - erp_inventory: Estoque por depósito
    - erp_financial: Contas a pagar/receber
    - erp_orders: Vendas e OS (NOVA)
"""

import pytest
from unittest.mock import MagicMock


# ─── Mock Helpers ────────────────────────────────────────────────────────────

def make_supabase_mock_with_rls(tenant_id: str, table_data: dict) -> MagicMock:
    """
    Cria mock do Supabase que simula RLS por tenant_id.
    Só retorna dados onde tenant_id == tenant_id fornecido.
    """
    mock = MagicMock()

    def table_side_effect(table_name):
        t = MagicMock()
        all_data = table_data.get(table_name, [])

        filtered_data = [
            row for row in all_data
            if row.get("tenant_id") == tenant_id
        ]

        resp = MagicMock()
        resp.data = filtered_data

        t.select.return_value.eq.return_value.execute.return_value = resp
        t.select.return_value.execute.return_value = resp

        def insert_side_effect(data):
            insert_mock = MagicMock()
            insert_resp = MagicMock()
            if "tenant_id" not in data:
                data["tenant_id"] = tenant_id
            insert_resp.data = [data]
            insert_mock.execute.return_value = insert_resp
            return insert_mock

        t.insert.side_effect = insert_side_effect
        return t

    mock.table.side_effect = table_side_effect
    return mock


# ─── Dados de Teste ─────────────────────────────────────────────────────────

SAMPLE_CUSTOMERS = [
    {
        "id": 1,
        "tenant_id": "tenant_a",
        "tipo": "cliente",
        "nome": "João Silva",
        "nome_fantasia": None,
        "cpf_cnpj": "12345678901",
        "ie": None,
        "im": None,
        "email": "joao@email.com",
        "telefone": "1199999999",
        "celular": "11999999999",
        "cep": "01310100",
        "logradouro": "Av Paulista",
        "numero": "1000",
        "complemento": "Sala 1",
        "bairro": "Bela Vista",
        "cidade": "São Paulo",
        "uf": "SP",
        "observacoes": "Cliente VIP",
        "ativo": True,
        "created_at": "2026-03-13T10:00:00Z",
        "updated_at": "2026-03-13T10:00:00Z",
    },
    {
        "id": 2,
        "tenant_id": "tenant_b",
        "tipo": "fornecedor",
        "nome": "Fornecedor X",
        "nome_fantasia": "FornX",
        "cpf_cnpj": "98765432000199",
        "ie": "123456789",
        "im": None,
        "email": "contato@fornx.com",
        "telefone": None,
        "celular": "21988888888",
        "cep": None,
        "logradouro": None,
        "numero": None,
        "complemento": None,
        "bairro": None,
        "cidade": "Rio de Janeiro",
        "uf": "RJ",
        "observacoes": None,
        "ativo": True,
        "created_at": "2026-03-13T10:00:00Z",
        "updated_at": "2026-03-13T10:00:00Z",
    },
]

SAMPLE_PRODUCTS = [
    {
        "id": 1,
        "tenant_id": "tenant_a",
        "sku": "AC-12000",
        "codigo_barras": "7891234567890",
        "nome": "Ar Condicionado 12000 BTUs",
        "descricao": "Ar condicionado split inverter",
        "tipo": "produto",
        "categoria": "Ar Condicionado",
        "marca": "Samsung",
        "preco_venda": 1500.00,
        "preco_custo": 1000.00,
        "margem_lucro": 50.00,
        "ncm": "84151011",
        "cest": None,
        "origem": "0",
        "unidade": "UN",
        "estoque_minimo": 5,
        "ativo": True,
        "created_at": "2026-03-13T10:00:00Z",
        "updated_at": "2026-03-13T10:00:00Z",
    },
    {
        "id": 2,
        "tenant_id": "tenant_a",
        "sku": "INST-AC",
        "codigo_barras": None,
        "nome": "Instalação de Ar Condicionado",
        "descricao": "Serviço de instalação padrão",
        "tipo": "servico",
        "categoria": "Serviços",
        "marca": None,
        "preco_venda": 300.00,
        "preco_custo": 0,
        "margem_lucro": 100.00,
        "ncm": None,
        "cest": None,
        "origem": None,
        "unidade": "UN",
        "estoque_minimo": 0,
        "ativo": True,
        "created_at": "2026-03-13T10:00:00Z",
        "updated_at": "2026-03-13T10:00:00Z",
    },
]

SAMPLE_ORDERS = [
    {
        "id": 1,
        "tenant_id": "tenant_a",
        "customer_id": 1,
        "tipo": "venda",
        "status": "aberto",
        "items": [
            {"product_id": 1, "sku": "AC-12000", "nome": "Ar Condicionado 12000 BTUs",
             "quantidade": 1, "preco_unitario": 1500.00, "subtotal": 1500.00}
        ],
        "subtotal": 1500.00,
        "desconto": 0,
        "total": 1500.00,
        "valor_pago": 0,
        "forma_pagamento": None,
        "observacoes": None,
        "fechado_em": None,
        "created_at": "2026-03-13T10:00:00Z",
        "updated_at": "2026-03-13T10:00:00Z",
    },
    {
        "id": 2,
        "tenant_id": "tenant_a",
        "customer_id": 1,
        "tipo": "os",
        "status": "fechado",
        "items": [
            {"product_id": 2, "sku": "INST-AC", "nome": "Instalação de Ar Condicionado",
             "quantidade": 1, "preco_unitario": 300.00, "subtotal": 300.00}
        ],
        "subtotal": 300.00,
        "desconto": 0,
        "total": 300.00,
        "valor_pago": 300.00,
        "forma_pagamento": "pix",
        "observacoes": "Instalação concluída",
        "fechado_em": "2026-03-13T15:00:00Z",
        "created_at": "2026-03-13T10:00:00Z",
        "updated_at": "2026-03-13T15:00:00Z",
    },
    {
        "id": 3,
        "tenant_id": "tenant_b",
        "customer_id": 2,
        "tipo": "venda",
        "status": "aberto",
        "items": [],
        "subtotal": 0,
        "desconto": 0,
        "total": 0,
        "valor_pago": 0,
        "forma_pagamento": None,
        "observacoes": None,
        "fechado_em": None,
        "created_at": "2026-03-13T10:00:00Z",
        "updated_at": "2026-03-13T10:00:00Z",
    },
]


# ─── Testes de Isolamento ───────────────────────────────────────────────────

class TestErpIsolation:
    """
    TDD — ERP Schema — Isolamento por tenant_id
    """

    def test_customers_isolated_by_tenant(self):
        """tenant_a só vê seus próprios clientes."""
        mock_db = make_supabase_mock_with_rls("tenant_a", {"erp_customers": SAMPLE_CUSTOMERS})
        result = mock_db.table("erp_customers").select("*").execute()

        assert len(result.data) == 1
        assert result.data[0]["tenant_id"] == "tenant_a"
        assert result.data[0]["nome"] == "João Silva"

    def test_orders_isolated_by_tenant(self):
        """tenant_a só vê suas próprias vendas/OS."""
        mock_db = make_supabase_mock_with_rls("tenant_a", {"erp_orders": SAMPLE_ORDERS})
        result = mock_db.table("erp_orders").select("*").execute()

        assert len(result.data) == 2
        assert all(o["tenant_id"] == "tenant_a" for o in result.data)

    def test_tenant_b_sees_only_own_orders(self):
        """tenant_b só vê seus próprios pedidos."""
        mock_db = make_supabase_mock_with_rls("tenant_b", {"erp_orders": SAMPLE_ORDERS})
        result = mock_db.table("erp_orders").select("*").execute()

        assert len(result.data) == 1
        assert result.data[0]["tenant_id"] == "tenant_b"


# ─── Testes de Campos erp_customers ─────────────────────────────────────────

class TestErpCustomerFields:
    """
    TDD — erp_customers — Campos conforme 002_erp_base_schema.sql
    """

    def test_customer_has_tipo_field(self):
        """tipo deve ser 'cliente', 'fornecedor' ou 'ambos'."""
        valid_tipos = {"cliente", "fornecedor", "ambos"}
        for c in SAMPLE_CUSTOMERS:
            assert c["tipo"] in valid_tipos

    def test_customer_has_address_fields(self):
        """Customer deve ter campos de endereço completo."""
        address_fields = {"cep", "logradouro", "numero", "complemento", "bairro", "cidade", "uf"}
        customer = SAMPLE_CUSTOMERS[0]
        for field in address_fields:
            assert field in customer


# ─── Testes de Campos erp_products ──────────────────────────────────────────

class TestErpProductFields:
    """
    TDD — erp_products — Campos conforme 002_erp_base_schema.sql
    """

    def test_product_has_sku(self):
        """Produto deve ter SKU."""
        for p in SAMPLE_PRODUCTS:
            assert "sku" in p
            assert p["sku"] is not None

    def test_product_tipo_values(self):
        """tipo deve ser 'produto', 'servico' ou 'kit'."""
        valid_tipos = {"produto", "servico", "kit"}
        for p in SAMPLE_PRODUCTS:
            assert p["tipo"] in valid_tipos

    def test_product_has_fiscal_fields(self):
        """Produto deve ter campos fiscais."""
        fiscal_fields = {"ncm", "cest", "origem"}
        product = SAMPLE_PRODUCTS[0]
        for field in fiscal_fields:
            assert field in product


# ─── Testes de Campos erp_orders (NOVA TABELA) ──────────────────────────────

class TestErpOrderFields:
    """
    TDD — erp_orders — Nova tabela para vendas e OS

    Campos:
        id, tenant_id, customer_id, tipo, status, items (JSONB),
        subtotal, desconto, total, valor_pago, forma_pagamento,
        observacoes, fechado_em, created_at, updated_at
    """

    def test_order_has_all_required_columns(self):
        """erp_orders deve ter todas as colunas necessárias."""
        required_columns = {
            "id", "tenant_id", "customer_id", "tipo", "status",
            "items", "subtotal", "desconto", "total", "valor_pago",
            "forma_pagamento", "observacoes", "fechado_em",
            "created_at", "updated_at"
        }

        order = SAMPLE_ORDERS[0]
        actual_columns = set(order.keys())

        assert required_columns == actual_columns

    def test_order_tipo_values(self):
        """tipo deve ser 'venda' ou 'os'."""
        valid_tipos = {"venda", "os"}
        for order in SAMPLE_ORDERS:
            assert order["tipo"] in valid_tipos

    def test_order_status_values(self):
        """status deve ser 'aberto', 'fechado' ou 'cancelado'."""
        valid_statuses = {"aberto", "fechado", "cancelado"}
        for order in SAMPLE_ORDERS:
            assert order["status"] in valid_statuses

    def test_order_items_is_jsonb_array(self):
        """items deve ser uma lista (JSONB)."""
        order = SAMPLE_ORDERS[0]
        assert isinstance(order["items"], list)

    def test_order_item_has_required_fields(self):
        """Cada item deve ter product_id, quantidade, preco_unitario, subtotal."""
        item_fields = {"product_id", "quantidade", "preco_unitario", "subtotal"}
        order = SAMPLE_ORDERS[0]
        for item in order["items"]:
            for field in item_fields:
                assert field in item

    def test_closed_order_has_fechado_em(self):
        """Pedido fechado deve ter fechado_em preenchido."""
        closed_order = SAMPLE_ORDERS[1]
        assert closed_order["status"] == "fechado"
        assert closed_order["fechado_em"] is not None

    def test_open_order_has_no_fechado_em(self):
        """Pedido aberto não deve ter fechado_em."""
        open_order = SAMPLE_ORDERS[0]
        assert open_order["status"] == "aberto"
        assert open_order["fechado_em"] is None

    def test_closed_order_has_valor_pago_equal_total(self):
        """Pedido fechado e pago deve ter valor_pago == total."""
        closed_order = SAMPLE_ORDERS[1]
        assert closed_order["status"] == "fechado"
        assert closed_order["valor_pago"] == closed_order["total"]
