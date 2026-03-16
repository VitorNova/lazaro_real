# tests/test_transfer_rejects_ia_queue.py

"""
TDD — Transferência não deve aceitar queue_ia como destino (2026-03-16)

Contexto: Lead "Studio Blessed" foi "transferido" para queue_id=537,
que é a própria fila da IA. O sistema aceitou e o lead ficou na mesma fila.

Causa: resolve_department() aceita qualquer queue_id, mesmo o queue_ia.

Correção: Rejeitar transferência quando queue_id == queue_ia.
"""

import pytest
from app.services.leadbox import resolve_department


class TestResolveDepartmentRejectsIAQueue:
    """
    Testes para garantir que resolve_department rejeita
    transferências para a fila da própria IA.
    """

    def setup_method(self):
        """Configuração padrão de handoff_triggers (igual produção)."""
        self.handoff_triggers = {
            "queue_ia": 537,
            "departments": {
                "atendimento": {
                    "id": 453,
                    "name": "Atendimento",
                    "userId": 815,
                    "default": True,
                    "keywords": [
                        "humano", "atendente", "pessoa", "falar", "ajuda",
                        "suporte", "conserto", "manutenção", "defeito", "quebrado",
                    ],
                },
                "financeiro": {
                    "id": 454,
                    "name": "Financeiro",
                    "userId": 814,
                    "keywords": [
                        "comprovante", "já paguei", "pago", "restrição",
                        "negativado", "cpf restrito", "pix enviado",
                    ],
                },
                "cobrancas": {
                    "id": 517,
                    "name": "Cobranças",
                    "userId": 1090,
                    "keywords": [
                        "boleto", "segunda via", "pagar mensalidade",
                        "mensalidade", "fatura", "cobrança",
                    ],
                },
            },
        }

    def test_rejeita_queue_id_igual_queue_ia(self):
        """
        Quando queue_id == queue_ia (537), deve retornar (None, None, None).
        Isso impede que o lead seja "transferido" para a própria fila da IA.
        """
        queue_id, user_id, dept_name = resolve_department(
            handoff_triggers=self.handoff_triggers,
            queue_id=537,  # queue_ia
            motivo="Cliente mudou o assunto",
        )

        assert queue_id is None, "Deveria rejeitar queue_id=537 (fila IA)"
        assert user_id is None
        assert dept_name is None

    def test_aceita_queue_id_valido(self):
        """
        Quando queue_id é um departamento válido (453, 454, 517),
        deve retornar os dados corretos.
        """
        queue_id, user_id, dept_name = resolve_department(
            handoff_triggers=self.handoff_triggers,
            queue_id=453,
            motivo="Transferir para atendimento",
        )

        assert queue_id == 453
        assert user_id == 815
        assert dept_name == "Atendimento"

    def test_queue_id_desconhecido_usa_default(self):
        """
        Quando queue_id não está nos departamentos configurados,
        deve usar o departamento default ao invés de aceitar cegamente.

        Antes: retornava (queue_id, None, "Desconhecido")
        Depois: retorna departamento default (453, 815, "Atendimento")
        """
        queue_id, user_id, dept_name = resolve_department(
            handoff_triggers=self.handoff_triggers,
            queue_id=999,  # não existe
            motivo="Departamento inventado",
        )

        # Deve usar o default (atendimento) ao invés de aceitar 999
        assert queue_id == 453, "Deveria usar departamento default, não aceitar 999"
        assert user_id == 815
        assert dept_name == "Atendimento"

    def test_departamento_comercial_nao_existe_usa_default(self):
        """
        Caso real: Gemini passou departamento='comercial' que não existe.
        Deve usar departamento default.
        """
        # Simulando o que aconteceu: departamento='comercial', queue_id=None
        queue_id, user_id, dept_name = resolve_department(
            handoff_triggers=self.handoff_triggers,
            queue_id=None,
            motivo="Cliente quer falar sobre vendas",  # sem keyword match
        )

        # Deve usar default
        assert queue_id == 453
        assert user_id == 815
        assert dept_name == "Atendimento"

    def test_keywords_match_funciona(self):
        """
        Quando motivo contém keyword de um departamento,
        deve usar esse departamento.
        """
        # "comprovante" é keyword do financeiro
        queue_id, user_id, dept_name = resolve_department(
            handoff_triggers=self.handoff_triggers,
            queue_id=None,
            motivo="Cliente enviou comprovante de pagamento",
        )

        assert queue_id == 454
        assert user_id == 814
        assert dept_name == "Financeiro"
