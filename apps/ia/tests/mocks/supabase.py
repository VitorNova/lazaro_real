# tests/mocks/supabase.py
"""
Mocks de Supabase para testes.

Classes:
- SelectChain: Mock de encadeamento SELECT com filtros
- UpdateChain: Mock de encadeamento UPDATE

Funções:
- make_supabase_mock_manutencao: Mock específico para fluxos de manutenção
"""

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock


class SelectChain:
    """
    Mock de encadeamento SELECT do Supabase.

    Suporta filtros: eq, neq, in_, is_, gt, gte, lt, lte, like, ilike
    Suporta: limit, order, single, execute

    Uso:
        chain = SelectChain([{"id": "1", "name": "Test"}])
        result = chain.eq("id", "1").limit(1).execute()
        assert result.data == [{"id": "1", "name": "Test"}]
    """

    def __init__(self, data: List[Dict[str, Any]]):
        self._data = data
        self._filtered = data.copy()

    def eq(self, column: str, value: Any) -> "SelectChain":
        """Filtra registros onde column == value."""
        self._filtered = [r for r in self._filtered if r.get(column) == value]
        return self

    def neq(self, column: str, value: Any) -> "SelectChain":
        """Filtra registros onde column != value."""
        self._filtered = [r for r in self._filtered if r.get(column) != value]
        return self

    def in_(self, column: str, values: List[Any]) -> "SelectChain":
        """Filtra registros onde column está em values."""
        self._filtered = [r for r in self._filtered if r.get(column) in values]
        return self

    def is_(self, column: str, value: Any) -> "SelectChain":
        """Filtra registros onde column IS value (para None/null)."""
        self._filtered = [r for r in self._filtered if r.get(column) is value]
        return self

    def gt(self, column: str, value: Any) -> "SelectChain":
        """Filtra registros onde column > value."""
        self._filtered = [r for r in self._filtered if r.get(column) is not None and r.get(column) > value]
        return self

    def gte(self, column: str, value: Any) -> "SelectChain":
        """Filtra registros onde column >= value."""
        self._filtered = [r for r in self._filtered if r.get(column) is not None and r.get(column) >= value]
        return self

    def lt(self, column: str, value: Any) -> "SelectChain":
        """Filtra registros onde column < value."""
        self._filtered = [r for r in self._filtered if r.get(column) is not None and r.get(column) < value]
        return self

    def lte(self, column: str, value: Any) -> "SelectChain":
        """Filtra registros onde column <= value."""
        self._filtered = [r for r in self._filtered if r.get(column) is not None and r.get(column) <= value]
        return self

    def like(self, column: str, pattern: str) -> "SelectChain":
        """Filtra registros onde column LIKE pattern (case-sensitive)."""
        import re
        regex = pattern.replace("%", ".*").replace("_", ".")
        self._filtered = [
            r for r in self._filtered
            if r.get(column) and re.search(regex, str(r.get(column)))
        ]
        return self

    def ilike(self, column: str, pattern: str) -> "SelectChain":
        """Filtra registros onde column ILIKE pattern (case-insensitive)."""
        import re
        regex = pattern.replace("%", ".*").replace("_", ".")
        self._filtered = [
            r for r in self._filtered
            if r.get(column) and re.search(regex, str(r.get(column)), re.IGNORECASE)
        ]
        return self

    def or_(self, *conditions: str) -> "SelectChain":
        """Suporta OR (simplificado - retorna todos os filtrados)."""
        return self

    def limit(self, count: int) -> "SelectChain":
        """Limita número de resultados."""
        self._filtered = self._filtered[:count]
        return self

    def order(self, column: str, desc: bool = False) -> "SelectChain":
        """Ordena resultados por coluna."""
        self._filtered = sorted(
            self._filtered,
            key=lambda x: x.get(column) or "",
            reverse=desc,
        )
        return self

    def single(self) -> MagicMock:
        """Retorna único resultado ou None."""
        result = MagicMock()
        result.data = self._filtered[0] if self._filtered else None
        return result

    def execute(self) -> MagicMock:
        """Executa query e retorna resultados."""
        result = MagicMock()
        result.data = self._filtered
        return result


class UpdateChain:
    """
    Mock de encadeamento UPDATE do Supabase.

    Captura dados passados para UPDATE para assertions.

    Uso:
        chain = UpdateChain(capture_list)
        chain.eq("id", "1").execute()
        # capture_list terá os dados capturados
    """

    def __init__(self, capture_list: List[Dict[str, Any]], update_data: Dict[str, Any] = None):
        self._capture_list = capture_list
        self._update_data = update_data or {}

    def eq(self, column: str, value: Any) -> "UpdateChain":
        """Adiciona filtro (apenas para encadeamento)."""
        return self

    def execute(self) -> MagicMock:
        """Executa UPDATE e captura dados."""
        if self._update_data:
            self._capture_list.append(self._update_data)
        result = MagicMock()
        result.data = [{"id": "updated-id"}]
        return result


def make_supabase_mock_manutencao(
    cliente_data: Optional[Dict[str, Any]] = None,
    contrato_data: Optional[Dict[str, Any]] = None,
) -> MagicMock:
    """
    Mock do Supabase para cenários de manutenção.

    Configura tabelas:
    - asaas_clientes: retorna cliente_data se fornecido
    - contract_details: retorna contrato_data se fornecido
    - Outras tabelas: retorna vazio com captura de UPDATE

    Args:
        cliente_data: Dados do cliente em asaas_clientes (ou None se não existe)
        contrato_data: Dados do contrato em contract_details (ou None se não existe)

    Returns:
        Mock do SupabaseService com:
        - mock._update_calls: Dict[str, List] com updates capturados por tabela
        - mock.update_lead_by_remotejid: MagicMock para método auxiliar

    Uso:
        mock = make_supabase_mock_manutencao(
            cliente_data={"id": "cus_123", "name": "João"},
            contrato_data={"id": "uuid", "maintenance_status": "notified"},
        )

        # Verificar updates
        update_calls = mock._update_calls.get("leads", [])
        assert len(update_calls) == 1
    """
    mock = MagicMock()
    mock._update_calls = {}

    def table_side_effect(table_name: str) -> MagicMock:
        t = MagicMock()

        if table_name == "asaas_clientes":
            # SELECT de cliente por CPF
            resp = MagicMock()
            resp.data = [cliente_data] if cliente_data else []

            select_chain = MagicMock()
            select_chain.eq.return_value = select_chain
            select_chain.is_.return_value = select_chain
            select_chain.limit.return_value = select_chain
            select_chain.execute.return_value = resp
            t.select.return_value = select_chain

        elif table_name == "contract_details":
            # SELECT de contrato por customer_id
            resp = MagicMock()
            resp.data = [contrato_data] if contrato_data else []

            select_chain = MagicMock()
            select_chain.eq.return_value = select_chain
            select_chain.is_.return_value = select_chain
            select_chain.limit.return_value = select_chain
            select_chain.execute.return_value = resp
            t.select.return_value = select_chain

        else:
            # Tabelas genéricas (ex: leads)
            resp = MagicMock()
            resp.data = [{"id": "lead-123"}]

            def capture_update(update_data: Dict[str, Any]) -> MagicMock:
                if table_name not in mock._update_calls:
                    mock._update_calls[table_name] = []
                mock._update_calls[table_name].append(update_data)

                update_chain = MagicMock()
                update_chain.eq.return_value = update_chain
                update_chain.execute.return_value = MagicMock(data=[{"id": "updated"}])
                return update_chain

            t.update.side_effect = capture_update
            t.select.return_value.eq.return_value.limit.return_value.execute.return_value = resp

        return t

    mock.client.table.side_effect = table_side_effect
    mock.update_lead_by_remotejid = MagicMock()

    return mock
