# tests/test_transfer_declaration.py

"""
TDD — Function Declaration de transferir_departamento (2026-03-16)

Contexto: O Gemini inventou departamento='comercial' porque a declaration
tinha exemplos genéricos como "vendas", "suporte" que não existem.

Causa: Description da declaration com exemplos errados.

Correção:
1. Trocar exemplos para departamentos reais: 'atendimento', 'financeiro', 'cobrancas'
2. Remover queue_id da declaration (forçar uso de nomes)
"""

import pytest
from app.ai.tools.cobranca import TRANSFERIR_DEPARTAMENTO_DECLARATION


class TestTransferirDepartamentoDeclaration:
    """
    Testes para garantir que a function declaration
    tem os exemplos corretos de departamentos.
    """

    def test_description_contem_departamentos_reais(self):
        """
        A description do parâmetro 'departamento' deve listar
        os departamentos que realmente existem na configuração.
        """
        params = TRANSFERIR_DEPARTAMENTO_DECLARATION["parameters"]
        dept_description = params["properties"]["departamento"]["description"]

        # Deve conter os departamentos reais
        assert "atendimento" in dept_description.lower(), \
            "Description deve mencionar 'atendimento'"
        assert "financeiro" in dept_description.lower(), \
            "Description deve mencionar 'financeiro'"
        assert "cobrancas" in dept_description.lower() or "cobranças" in dept_description.lower(), \
            "Description deve mencionar 'cobrancas'"
        assert "lazaro" in dept_description.lower(), \
            "Description deve mencionar 'lazaro'"

    def test_description_nao_contem_departamentos_falsos(self):
        """
        A description NÃO deve conter exemplos de departamentos
        que não existem, como 'vendas', 'suporte', 'comercial'.
        """
        params = TRANSFERIR_DEPARTAMENTO_DECLARATION["parameters"]
        dept_description = params["properties"]["departamento"]["description"]

        # NÃO deve conter departamentos que não existem
        assert "vendas" not in dept_description.lower(), \
            "Description NÃO deve mencionar 'vendas' (não existe)"
        assert "suporte" not in dept_description.lower(), \
            "Description NÃO deve mencionar 'suporte' (não existe)"
        assert "comercial" not in dept_description.lower(), \
            "Description NÃO deve mencionar 'comercial' (não existe)"

    def test_queue_id_nao_existe_na_declaration(self):
        """
        O parâmetro queue_id NÃO deve existir na declaration.
        Isso força o Gemini a usar nomes de departamento ao invés de IDs.
        """
        params = TRANSFERIR_DEPARTAMENTO_DECLARATION["parameters"]
        properties = params["properties"]

        assert "queue_id" not in properties, \
            "queue_id NÃO deve existir na declaration (forçar uso de nomes)"

    def test_user_id_nao_existe_na_declaration(self):
        """
        O parâmetro user_id NÃO deve existir na declaration.
        O código deve resolver o user_id automaticamente pelo departamento.
        """
        params = TRANSFERIR_DEPARTAMENTO_DECLARATION["parameters"]
        properties = params["properties"]

        assert "user_id" not in properties, \
            "user_id NÃO deve existir na declaration (resolver automaticamente)"

    def test_motivo_e_required(self):
        """
        O parâmetro 'motivo' deve ser obrigatório.
        """
        params = TRANSFERIR_DEPARTAMENTO_DECLARATION["parameters"]
        required = params.get("required", [])

        assert "motivo" in required, \
            "motivo deve ser required"

    def test_departamento_e_required(self):
        """
        O parâmetro 'departamento' deve ser obrigatório.
        Se não for required, o Gemini pode não informar.
        """
        params = TRANSFERIR_DEPARTAMENTO_DECLARATION["parameters"]
        required = params.get("required", [])

        assert "departamento" in required, \
            "departamento deve ser required"
