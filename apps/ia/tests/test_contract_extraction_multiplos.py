# tests/test_contract_extraction_multiplos.py
"""
TDD - Suporte a multiplos contratos por subscription (2026-03-19)

Contexto: O sistema fazia merge de TODOS os PDFs assumindo que eram
do mesmo contrato. Quando PDFs tinham numeros diferentes (678-1, 683-1),
apenas o primeiro era salvo e os demais descartados.

Causa: merge_contract_data() usava primeiro numero_contrato encontrado.

Correcao: Agrupar PDFs por numero_contrato antes do merge.
Cada numero_contrato gera um contract_details separado.

Casos afetados:
- TANGARA ALOJAMENTOS: 3 PDFs (678-1, 683-1, 686-1) -> apenas 678-1 salvo
- ALEX DOS SANTOS: 15 PDFs distintos -> apenas 532-1 salvo
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Dict, List, Any


# ─── Helpers de Mock ────────────────────────────────────────────────────────

def make_supabase_mock_with_capture() -> MagicMock:
    """
    Mock do Supabase que captura chamadas upsert para assertions.
    """
    mock = MagicMock()
    mock._upsert_calls = []  # Lista de (table_name, record, on_conflict)

    def table_side_effect(table_name):
        t = MagicMock()

        # SELECT
        select_chain = MagicMock()
        select_chain.eq.return_value = select_chain
        select_chain.maybe_single.return_value = select_chain
        select_chain.execute.return_value = MagicMock(data=None)
        t.select.return_value = select_chain

        # UPSERT - captura argumentos
        def capture_upsert(record, on_conflict=None):
            mock._upsert_calls.append({
                "table": table_name,
                "record": record,
                "on_conflict": on_conflict,
            })
            result = MagicMock()
            result.execute.return_value = MagicMock(data=[{"id": "new-id"}])
            return result

        t.upsert.side_effect = capture_upsert
        return t

    mock.client.table.side_effect = table_side_effect
    return mock


def make_contract_data(numero_contrato: str, equipamentos: List[Dict]) -> Dict[str, Any]:
    """Cria dados de contrato extraidos de um PDF."""
    return {
        "numero_contrato": numero_contrato,
        "locatario_nome": f"Cliente do contrato {numero_contrato}",
        "locatario_cpf_cnpj": "12345678901",
        "equipamentos": equipamentos,
        "data_inicio": "2026-01-01",
        "data_termino": "2027-01-01",
        "valor_mensal": 189.00,
    }


def make_pdf_data(doc_id: str, doc_name: str, payment_id: str = "pay_test") -> Dict[str, Any]:
    """Cria metadados de um PDF."""
    return {
        "payment_id": payment_id,
        "doc_id": doc_id,
        "doc_name": doc_name,
        "doc_url": f"https://asaas.com/file/{doc_id}",
    }


def make_equipamento(patrimonio: str, marca: str = "SPRINGER", btus: int = 12000) -> Dict[str, Any]:
    """Cria um equipamento."""
    return {
        "patrimonio": patrimonio,
        "marca": marca,
        "modelo": "INVERTER",
        "btus": btus,
        "valor_comercial": 2700.00,
    }


# ─── Testes da funcao agrupar_contratos_por_numero ──────────────────────────

class TestAgruparContratosPorNumero:
    """
    Testa a nova funcao que agrupa PDFs pelo numero_contrato.
    """

    def test_agrupa_pdfs_por_numero_contrato_diferente(self):
        """
        Dado: 3 PDFs com numeros de contrato diferentes (678-1, 683-1, 686-1)
        Quando: agrupar_contratos_por_numero() e chamado
        Entao: Retorna 3 grupos, cada um com 1 PDF
        """
        # Arrange
        all_contract_data = [
            make_contract_data("678-1", [make_equipamento("0571")]),
            make_contract_data("683-1", [make_equipamento("0585")]),
            make_contract_data("686-1", [make_equipamento("0590")]),
        ]
        all_pdf_data = [
            make_pdf_data("doc1", "678-1.pdf"),
            make_pdf_data("doc2", "683-1.pdf"),
            make_pdf_data("doc3", "686-1.pdf"),
        ]

        # Act
        from app.domain.billing.services.contract_extraction_service import (
            agrupar_contratos_por_numero,
        )
        grupos = agrupar_contratos_por_numero(all_contract_data, all_pdf_data)

        # Assert
        assert len(grupos) == 3, "Deveria criar 3 grupos (um por numero_contrato)"
        assert "678-1" in grupos
        assert "683-1" in grupos
        assert "686-1" in grupos

        # Cada grupo deve ter exatamente 1 PDF
        for numero, (contracts, pdfs) in grupos.items():
            assert len(contracts) == 1, f"Grupo {numero} deveria ter 1 contrato"
            assert len(pdfs) == 1, f"Grupo {numero} deveria ter 1 PDF"

    def test_agrupa_pdfs_mesmo_numero_contrato(self):
        """
        Dado: 2 PDFs com o MESMO numero de contrato (paginas do mesmo contrato)
        Quando: agrupar_contratos_por_numero() e chamado
        Entao: Retorna 1 grupo com 2 PDFs
        """
        # Arrange
        all_contract_data = [
            make_contract_data("678-1", [make_equipamento("0571")]),
            make_contract_data("678-1", [make_equipamento("0572")]),  # Mesmo numero
        ]
        all_pdf_data = [
            make_pdf_data("doc1", "678-1_pagina1.pdf"),
            make_pdf_data("doc2", "678-1_pagina2.pdf"),
        ]

        # Act
        from app.domain.billing.services.contract_extraction_service import (
            agrupar_contratos_por_numero,
        )
        grupos = agrupar_contratos_por_numero(all_contract_data, all_pdf_data)

        # Assert
        assert len(grupos) == 1, "Deveria criar apenas 1 grupo (mesmo numero_contrato)"
        assert "678-1" in grupos

        contracts, pdfs = grupos["678-1"]
        assert len(contracts) == 2, "Grupo deveria ter 2 contratos para merge"
        assert len(pdfs) == 2, "Grupo deveria ter 2 PDFs"

    def test_agrupa_pdf_sem_numero_contrato(self):
        """
        Dado: 1 PDF sem numero_contrato extraido
        Quando: agrupar_contratos_por_numero() e chamado
        Entao: Vai para grupo especial "__sem_numero__"
        """
        # Arrange
        all_contract_data = [
            {
                "numero_contrato": None,  # Sem numero
                "locatario_nome": "Cliente X",
                "equipamentos": [make_equipamento("0001")],
            },
        ]
        all_pdf_data = [
            make_pdf_data("doc1", "contrato_sem_numero.pdf"),
        ]

        # Act
        from app.domain.billing.services.contract_extraction_service import (
            agrupar_contratos_por_numero,
        )
        grupos = agrupar_contratos_por_numero(all_contract_data, all_pdf_data)

        # Assert
        assert len(grupos) == 1
        assert "__sem_numero__" in grupos

    def test_agrupa_misto_com_e_sem_numero(self):
        """
        Dado: 3 PDFs - 2 com numeros diferentes e 1 sem numero
        Quando: agrupar_contratos_por_numero() e chamado
        Entao: Retorna 3 grupos
        """
        # Arrange
        all_contract_data = [
            make_contract_data("678-1", [make_equipamento("0571")]),
            make_contract_data("683-1", [make_equipamento("0585")]),
            {"numero_contrato": None, "equipamentos": [make_equipamento("0001")]},
        ]
        all_pdf_data = [
            make_pdf_data("doc1", "678-1.pdf"),
            make_pdf_data("doc2", "683-1.pdf"),
            make_pdf_data("doc3", "sem_numero.pdf"),
        ]

        # Act
        from app.domain.billing.services.contract_extraction_service import (
            agrupar_contratos_por_numero,
        )
        grupos = agrupar_contratos_por_numero(all_contract_data, all_pdf_data)

        # Assert
        assert len(grupos) == 3
        assert "678-1" in grupos
        assert "683-1" in grupos
        assert "__sem_numero__" in grupos


# ─── Testes do fluxo completo de salvamento ─────────────────────────────────

class TestSalvarMultiplosContratos:
    """
    Testa que o sistema salva N registros quando ha N contratos distintos.
    """

    @pytest.mark.asyncio
    async def test_salva_um_registro_por_contrato_distinto(self):
        """
        Dado: 3 PDFs com numeros de contrato diferentes (678-1, 683-1, 686-1)
        Quando: _salvar_multiplos_contratos() e chamado
        Entao: 3 registros sao inseridos em contract_details
        """
        # Arrange
        mock_supabase = make_supabase_mock_with_capture()

        grupos = {
            "678-1": (
                [make_contract_data("678-1", [make_equipamento("0571")])],
                [make_pdf_data("doc1", "678-1.pdf")],
            ),
            "683-1": (
                [make_contract_data("683-1", [make_equipamento("0585")])],
                [make_pdf_data("doc2", "683-1.pdf")],
            ),
            "686-1": (
                [make_contract_data("686-1", [make_equipamento("0590")])],
                [make_pdf_data("doc3", "686-1.pdf")],
            ),
        }

        # Act
        from app.domain.billing.services.contract_extraction_service import (
            _salvar_multiplos_contratos,
        )
        await _salvar_multiplos_contratos(
            supabase=mock_supabase,
            grupos=grupos,
            subscription_id="sub_test123",
            customer_id="cus_test123",
            customer_name="TANGARA ALOJAMENTOS",
            agent_id="agent_test123",
            log_prefix="[TEST]",
        )

        # Assert
        upserts = mock_supabase._upsert_calls
        assert len(upserts) == 3, f"Deveria ter 3 upserts, teve {len(upserts)}"

        # Verificar que cada contrato foi salvo separadamente
        numeros_salvos = [u["record"]["numero_contrato"] for u in upserts]
        assert "678-1" in numeros_salvos
        assert "683-1" in numeros_salvos
        assert "686-1" in numeros_salvos

        # Cada registro deve ter apenas seus proprios equipamentos
        for upsert in upserts:
            record = upsert["record"]
            numero = record["numero_contrato"]
            equipamentos = record["equipamentos"]

            assert len(equipamentos) == 1, f"Contrato {numero} deveria ter 1 equipamento"

    @pytest.mark.asyncio
    async def test_faz_merge_quando_mesmo_numero_contrato(self):
        """
        Dado: 2 PDFs com o MESMO numero de contrato (678-1)
        Quando: _salvar_multiplos_contratos() e chamado
        Entao: 1 registro e inserido com equipamentos de ambos os PDFs
        """
        # Arrange
        mock_supabase = make_supabase_mock_with_capture()

        grupos = {
            "678-1": (
                [
                    make_contract_data("678-1", [make_equipamento("0571")]),
                    make_contract_data("678-1", [make_equipamento("0572")]),
                ],
                [
                    make_pdf_data("doc1", "678-1_p1.pdf"),
                    make_pdf_data("doc2", "678-1_p2.pdf"),
                ],
            ),
        }

        # Act
        from app.domain.billing.services.contract_extraction_service import (
            _salvar_multiplos_contratos,
        )
        await _salvar_multiplos_contratos(
            supabase=mock_supabase,
            grupos=grupos,
            subscription_id="sub_test123",
            customer_id="cus_test123",
            customer_name="Cliente Teste",
            agent_id="agent_test123",
            log_prefix="[TEST]",
        )

        # Assert
        upserts = mock_supabase._upsert_calls
        assert len(upserts) == 1, "Deveria ter apenas 1 upsert (mesmo contrato)"

        record = upserts[0]["record"]
        assert record["numero_contrato"] == "678-1"
        assert len(record["equipamentos"]) == 2, "Deveria ter 2 equipamentos (merge)"

    @pytest.mark.asyncio
    async def test_upsert_usa_on_conflict_com_numero_contrato(self):
        """
        Verifica que o upsert usa on_conflict incluindo numero_contrato
        para permitir multiplos contratos por subscription.
        """
        # Arrange
        mock_supabase = make_supabase_mock_with_capture()

        grupos = {
            "678-1": (
                [make_contract_data("678-1", [make_equipamento("0571")])],
                [make_pdf_data("doc1", "678-1.pdf")],
            ),
        }

        # Act
        from app.domain.billing.services.contract_extraction_service import (
            _salvar_multiplos_contratos,
        )
        await _salvar_multiplos_contratos(
            supabase=mock_supabase,
            grupos=grupos,
            subscription_id="sub_test123",
            customer_id="cus_test123",
            customer_name="Cliente Teste",
            agent_id="agent_test123",
            log_prefix="[TEST]",
        )

        # Assert
        upsert = mock_supabase._upsert_calls[0]
        on_conflict = upsert["on_conflict"]

        # O on_conflict DEVE incluir numero_contrato
        assert "numero_contrato" in on_conflict, (
            f"on_conflict deveria incluir numero_contrato, mas foi: {on_conflict}"
        )


# ─── Testes de reprocessamento ──────────────────────────────────────────────

class TestReprocessamentoNaoDuplica:
    """
    Testa que reprocessar a mesma subscription nao cria duplicatas.
    """

    @pytest.mark.asyncio
    async def test_reprocessamento_atualiza_em_vez_de_duplicar(self):
        """
        Dado: Contrato 678-1 ja existe no banco
        Quando: Reprocessar a subscription com o mesmo PDF
        Entao: Atualiza o registro existente (upsert), nao cria duplicata
        """
        # Arrange
        mock_supabase = make_supabase_mock_with_capture()

        # Simular que ja existe um registro
        def table_with_existing(table_name):
            t = MagicMock()

            # SELECT retorna registro existente
            select_chain = MagicMock()
            select_chain.eq.return_value = select_chain
            select_chain.maybe_single.return_value = select_chain
            select_chain.execute.return_value = MagicMock(data={
                "id": "existing-id",
                "subscription_id": "sub_test123",
                "numero_contrato": "678-1",
            })
            t.select.return_value = select_chain

            # UPSERT
            def capture_upsert(record, on_conflict=None):
                mock_supabase._upsert_calls.append({
                    "table": table_name,
                    "record": record,
                    "on_conflict": on_conflict,
                })
                result = MagicMock()
                result.execute.return_value = MagicMock(data=[{"id": "existing-id"}])
                return result

            t.upsert.side_effect = capture_upsert
            return t

        mock_supabase.client.table.side_effect = table_with_existing

        grupos = {
            "678-1": (
                [make_contract_data("678-1", [make_equipamento("0571")])],
                [make_pdf_data("doc1", "678-1.pdf")],
            ),
        }

        # Act
        from app.domain.billing.services.contract_extraction_service import (
            _salvar_multiplos_contratos,
        )
        await _salvar_multiplos_contratos(
            supabase=mock_supabase,
            grupos=grupos,
            subscription_id="sub_test123",
            customer_id="cus_test123",
            customer_name="Cliente Teste",
            agent_id="agent_test123",
            log_prefix="[TEST]",
        )

        # Assert - deve ter feito upsert (update), nao insert duplicado
        assert len(mock_supabase._upsert_calls) == 1
        # O upsert com on_conflict garante que atualiza em vez de duplicar


# ─── Teste de integracao do fluxo completo ──────────────────────────────────

class TestFluxoCompletoIntegracao:
    """
    Testa o fluxo completo de processar_subscription_created_background
    com multiplos contratos distintos.
    """

    @pytest.mark.asyncio
    async def test_processar_subscription_com_multiplos_contratos(self):
        """
        Simula o cenario real do TANGARA ALOJAMENTOS:
        - 1 subscription
        - 1 payment com 3 PDFs (678-1, 683-1, 686-1)
        - Deve criar 3 registros em contract_details
        """
        # Este teste requer mock mais complexo do AsaasService
        # Sera implementado apos a funcao principal estar funcionando
        pytest.skip("Teste de integracao - implementar apos funcoes base")
