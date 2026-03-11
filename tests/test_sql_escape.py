# tests/test_sql_escape.py
"""
TDD - Auditoria de Seguranca 11/03/2026 - NoSQL Injection via .ilike()

Contexto:
    Queries com .ilike() nao escapam wildcards % e _, permitindo
    pattern matching malicioso. Atacante pode usar phone=999_9999
    para match multiplos leads.

Causa:
    Funcoes em payment_confirmed_service.py, customer_sync_service.py
    usam .ilike(f"%{phone}%") sem escapar wildcards.

Correcao:
    Criar escape_ilike_pattern() e aplicar em todas as queries.
"""

import pytest


class TestEscapeIlikePattern:
    """
    Testes para funcao escape_ilike_pattern() em sql_escape.py.

    A funcao deve escapar wildcards do PostgreSQL/Supabase para
    busca literal em queries .ilike().
    """

    def test_escapa_underscore(self):
        """
        _ (underscore) e wildcard single-char no PostgreSQL.
        Deve ser escapado para \_ para busca literal.

        Input: "999_9999"
        Output: "999\\_9999"
        """
        from app.core.utils.sql_escape import escape_ilike_pattern

        result = escape_ilike_pattern("999_9999")
        assert result == "999\\_9999", f"Esperado 999\\_9999, obteve {result}"

    def test_escapa_percent(self):
        """
        % (percent) e wildcard multi-char no PostgreSQL.
        Deve ser escapado para \\% para busca literal.

        Input: "100%"
        Output: "100\\%"
        """
        from app.core.utils.sql_escape import escape_ilike_pattern

        result = escape_ilike_pattern("100%")
        assert result == "100\\%", f"Esperado 100\\%, obteve {result}"

    def test_escapa_backslash(self):
        """
        \\ (backslash) e char de escape no PostgreSQL.
        Deve ser escapado para \\\\ para busca literal.

        Input: "path\\file"
        Output: "path\\\\file"
        """
        from app.core.utils.sql_escape import escape_ilike_pattern

        result = escape_ilike_pattern("path\\file")
        assert result == "path\\\\file", f"Esperado path\\\\file, obteve {result}"

    def test_telefone_normal_nao_muda(self):
        """
        Telefone normal (apenas digitos) nao deve ser alterado.

        Input: "5511987654321"
        Output: "5511987654321"
        """
        from app.core.utils.sql_escape import escape_ilike_pattern

        result = escape_ilike_pattern("5511987654321")
        assert result == "5511987654321", f"Telefone normal foi alterado: {result}"

    def test_string_vazia(self):
        """String vazia deve retornar string vazia."""
        from app.core.utils.sql_escape import escape_ilike_pattern

        result = escape_ilike_pattern("")
        assert result == "", f"String vazia retornou: {result}"

    def test_multiplos_wildcards(self):
        """
        String com multiplos wildcards deve escapar todos.

        Input: "test_100%_data"
        Output: "test\\_100\\%\\_data"
        """
        from app.core.utils.sql_escape import escape_ilike_pattern

        result = escape_ilike_pattern("test_100%_data")
        assert result == "test\\_100\\%\\_data", f"Obteve: {result}"


class TestPaymentServiceUsesEscape:
    """
    Testes para verificar que payment_confirmed_service.py
    usa escape_ilike_pattern() nas queries.
    """

    def test_payment_confirmed_service_importa_escape(self):
        """
        payment_confirmed_service.py deve importar escape_ilike_pattern.
        """
        import re

        with open("apps/ia/app/domain/billing/services/payment_confirmed_service.py", "r") as f:
            content = f.read()

        # Deve ter import da funcao
        has_import = "escape_ilike_pattern" in content
        assert has_import, "payment_confirmed_service.py nao importa escape_ilike_pattern"

    def test_payment_confirmed_service_usa_escape_em_ilike(self):
        """
        Queries .ilike() devem usar escape_ilike_pattern().
        Nao deve ter .ilike(f"%{variavel}%") sem escape.
        """
        import re

        with open("apps/ia/app/domain/billing/services/payment_confirmed_service.py", "r") as f:
            content = f.read()

        # Padrao vulneravel: .ilike("campo", f"%{var}%") SEM escape_ilike_pattern
        # Primeiro encontra todos os .ilike com f-string
        all_ilike = re.findall(r'\.ilike\([^)]+f["\']%\{[^}]+\}%["\']\)', content)

        # Filtra apenas os que NAO usam escape_ilike_pattern
        vulnerable = [m for m in all_ilike if "escape_ilike_pattern" not in m]

        assert len(vulnerable) == 0, f"Encontrado ilike vulneravel (sem escape): {vulnerable}"


class TestCustomerSyncServiceUsesEscape:
    """
    Testes para verificar que customer_sync_service.py
    usa escape_ilike_pattern() nas queries.
    """

    def test_customer_sync_service_importa_escape(self):
        """
        customer_sync_service.py deve importar escape_ilike_pattern.
        """
        with open("apps/ia/app/domain/billing/services/customer_sync_service.py", "r") as f:
            content = f.read()

        has_import = "escape_ilike_pattern" in content
        assert has_import, "customer_sync_service.py nao importa escape_ilike_pattern"

    def test_customer_sync_service_usa_escape_em_ilike(self):
        """
        Queries .ilike() devem usar escape_ilike_pattern().
        """
        import re

        with open("apps/ia/app/domain/billing/services/customer_sync_service.py", "r") as f:
            content = f.read()

        # Encontra todos os .ilike com f-string
        all_ilike = re.findall(r'\.ilike\([^)]+f["\']%\{[^}]+\}%["\']\)', content)

        # Filtra apenas os que NAO usam escape_ilike_pattern
        vulnerable = [m for m in all_ilike if "escape_ilike_pattern" not in m]

        assert len(vulnerable) == 0, f"Encontrado ilike vulneravel (sem escape): {vulnerable}"
