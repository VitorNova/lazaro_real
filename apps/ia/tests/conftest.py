"""
Fixtures compartilhadas para testes do módulo IA.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def cliente_exemplo():
    """Dados de cliente para testes."""
    return {
        "id": "cus_abc123",
        "name": "João Silva",
        "cpf_cnpj": "12345678901",
        "mobile_phone": "66999887766",
        "email": "joao@email.com"
    }


@pytest.fixture
def cobranca_exemplo():
    """Dados de cobrança para testes."""
    return {
        "id": "pay_xyz789",
        "value": 150.00,
        "due_date": "2024-03-15",
        "status": "PENDING",
        "invoice_url": "https://asaas.com/i/xyz789",
        "billing_type": "PIX"
    }


@pytest.fixture
def contrato_exemplo():
    """Dados de contrato para testes."""
    return {
        "id": "contract_001",
        "numero_contrato": "2024-001",
        "data_inicio": "2024-01-01",
        "data_termino": "2025-01-01",
        "prazo_meses": 12,
        "valor_mensal": 300.00,
        "dia_vencimento": 10,
        "renovacao_automatica": True,
        "endereco_instalacao": "Rua das Flores, 123",
        "equipamentos": [
            {"marca": "Samsung", "modelo": "Wind Free", "btus": 12000, "patrimonio": "PAT001"}
        ],
        "qtd_ars": 1,
        "proxima_manutencao": "2024-06-01",
        "maintenance_status": "pending",
        "maintenance_type": "preventiva"
    }


@pytest.fixture
def lead_exemplo():
    """Dados de lead para testes."""
    return {
        "id": 123,
        "remotejid": "5566999887766@s.whatsapp.net",
        "nome": "João Silva",
        "asaas_customer_id": None,
        "billing_context": None
    }


@pytest.fixture
def lead_com_customer_id(lead_exemplo, cliente_exemplo):
    """Lead que já tem asaas_customer_id vinculado."""
    return {
        **lead_exemplo,
        "asaas_customer_id": cliente_exemplo["id"]
    }


@pytest.fixture
def billing_notification_exemplo(cliente_exemplo):
    """Dados de billing_notification para testes."""
    return {
        "customer_id": cliente_exemplo["id"],
        "customer_name": cliente_exemplo["name"],
        "phone": "66999887766",
        "sent_at": "2024-03-01T10:00:00"
    }


def create_mock_supabase_response(data):
    """Cria mock de resposta do Supabase."""
    mock_response = MagicMock()
    mock_response.data = data
    return mock_response


def create_mock_supabase_table(responses_by_method=None):
    """
    Cria mock de tabela Supabase com métodos encadeados.

    Args:
        responses_by_method: Dict mapeando método final -> dados de resposta
                            Ex: {"execute": [{"id": "123"}]}
    """
    responses_by_method = responses_by_method or {}

    mock_table = MagicMock()

    # Configurar métodos que retornam self (encadeamento)
    chainable_methods = [
        'select', 'insert', 'update', 'delete',
        'eq', 'neq', 'gt', 'gte', 'lt', 'lte',
        'is_', 'in_', 'or_', 'and_',
        'order', 'limit', 'offset',
        'single', 'maybe_single'
    ]

    for method in chainable_methods:
        getattr(mock_table, method).return_value = mock_table

    # Configurar execute para retornar resposta
    execute_data = responses_by_method.get("execute", [])
    mock_table.execute.return_value = create_mock_supabase_response(execute_data)

    return mock_table


class MockSupabaseClient:
    """Mock do cliente Supabase com suporte a múltiplas tabelas."""

    def __init__(self):
        self._tables = {}
        self._table_responses = {}

    def set_table_response(self, table_name: str, data: list):
        """Define resposta para uma tabela específica."""
        self._table_responses[table_name] = data

    def table(self, name: str):
        """Retorna mock da tabela."""
        if name not in self._tables:
            data = self._table_responses.get(name, [])
            self._tables[name] = create_mock_supabase_table({"execute": data})
        return self._tables[name]


@pytest.fixture
def mock_supabase_client():
    """Mock do cliente Supabase."""
    return MockSupabaseClient()
