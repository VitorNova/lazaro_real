# tests/test_fluxo_completo_remarcacao.py
"""
TDD — Fluxo Completo de Remarcacao de Manutencao (2026-03-18)

Contexto: Cliente recebe notificacao D-7, responde, fornece CPF.
          A IA deve identificar o cliente, buscar contrato, e instruir
          proximo passo (perguntar dia/horario).

Bug corrigido: salvar_dados_lead retornava apenas "CPF salvo com sucesso",
               fazendo a IA parar o fluxo ao inves de continuar.

Cenarios testados:
1. Cliente com contrato notificado → retorno enriquecido com instrucao
2. Mensagem nao contem texto que para o fluxo
3. Cliente sem contrato → instrucao alternativa
4. Cliente nao encontrado → instrucao para verificar CPF
"""

import pytest
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime

from tests.mocks.supabase import make_supabase_mock_manutencao
from tests.mocks.manutencao import (
    CLIENTE_COM_CONTRATO,
    CLIENTE_SEM_CONTRATO,
    CONTRATO_NOTIFICADO,
    CONTRATO_AGENDADO,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def context_completo():
    """Contexto minimo para CustomerTools."""
    return {
        "agent_id": "test-agent-123",
        "table_leads": "LeadboxCRM_Test",
        "remotejid": "5511999999999@s.whatsapp.net",
    }


@pytest.fixture
def supabase_cliente_contrato_notificado():
    """Mock Supabase com cliente e contrato notificado."""
    return make_supabase_mock_manutencao(
        cliente_data=CLIENTE_COM_CONTRATO,
        contrato_data=CONTRATO_NOTIFICADO,
    )


@pytest.fixture
def supabase_cliente_sem_contrato():
    """Mock Supabase com cliente mas sem contrato."""
    return make_supabase_mock_manutencao(
        cliente_data=CLIENTE_COM_CONTRATO,
        contrato_data=None,
    )


@pytest.fixture
def supabase_cliente_nao_encontrado():
    """Mock Supabase sem cliente."""
    return make_supabase_mock_manutencao(
        cliente_data=None,
        contrato_data=None,
    )


# ─── Testes ──────────────────────────────────────────────────────────────────


class TestFluxoCompletoRemarcacao:
    """
    TDD — Fluxo Completo de Remarcacao de Manutencao (2026-03-18)

    Valida que apos salvar CPF, a IA recebe dados enriquecidos
    que permitem continuar o fluxo de remarcacao.
    """

    @pytest.mark.asyncio
    async def test_apos_cpf_retorno_contem_cliente_e_contrato(
        self, context_completo, supabase_cliente_contrato_notificado
    ):
        """
        Cenario: Cliente fornece CPF, sistema encontra cliente e contrato notificado.
        Esperado: Retorno contem cliente{}, contrato{} e instrucao para continuar.
        """
        from app.ai.tools.customer_tools import CustomerTools

        tools = CustomerTools(context_completo, supabase_cliente_contrato_notificado)
        resultado = await tools.salvar_dados_lead(cpf="084.656.801-07")

        # Assert: operacao bem sucedida
        assert resultado["sucesso"] is True

        # Assert: cliente encontrado com dados
        assert resultado["cliente"] is not None
        assert "nome" in resultado["cliente"]

        # Assert: contrato encontrado com status notified
        assert resultado["contrato"] is not None
        assert resultado["contrato"]["maintenance_status"] == "notified"

        # Assert: instrucao presente para continuar fluxo
        assert resultado["instrucao"] is not None
        assert len(resultado["instrucao"]) > 0

    @pytest.mark.asyncio
    async def test_mensagem_nao_para_fluxo(
        self, context_completo, supabase_cliente_contrato_notificado
    ):
        """
        Cenario: Verificar que mensagem retornada nao contem textos que param o fluxo.
        Bug anterior: "CPF salvo com sucesso" fazia IA encerrar conversa.
        """
        from app.ai.tools.customer_tools import CustomerTools

        tools = CustomerTools(context_completo, supabase_cliente_contrato_notificado)
        resultado = await tools.salvar_dados_lead(cpf="08465680107")

        # Assert: mensagem NAO contem texto que para o fluxo
        mensagem = resultado.get("mensagem", "")
        assert "salvo com sucesso" not in mensagem.lower()
        assert "dados salvos" not in mensagem.lower()
        assert "registrado com sucesso" not in mensagem.lower()

        # Assert: instrucao presente e nao vazia
        assert resultado["instrucao"] is not None
        assert resultado["instrucao"] != ""

    @pytest.mark.asyncio
    async def test_instrucao_menciona_dia_horario_para_notified(
        self, context_completo, supabase_cliente_contrato_notificado
    ):
        """
        Cenario: Contrato com maintenance_status=notified.
        Esperado: Instrucao menciona perguntar dia e horario.
        """
        from app.ai.tools.customer_tools import CustomerTools

        tools = CustomerTools(context_completo, supabase_cliente_contrato_notificado)
        resultado = await tools.salvar_dados_lead(cpf="08465680107")

        instrucao = resultado.get("instrucao", "").lower()

        # Assert: instrucao direciona para proximo passo do fluxo
        assert "dia" in instrucao or "horario" in instrucao or "visita" in instrucao

    @pytest.mark.asyncio
    async def test_cliente_sem_contrato_instrucao_alternativa(
        self, context_completo, supabase_cliente_sem_contrato
    ):
        """
        Cenario: Cliente encontrado mas sem contrato ativo.
        Esperado: Instrucao alternativa (nao menciona manutencao).
        """
        from app.ai.tools.customer_tools import CustomerTools

        tools = CustomerTools(context_completo, supabase_cliente_sem_contrato)
        resultado = await tools.salvar_dados_lead(cpf="08465680107")

        assert resultado["sucesso"] is True
        assert resultado["cliente"] is not None
        assert resultado["contrato"] is None

        # Assert: instrucao presente mesmo sem contrato
        assert resultado["instrucao"] is not None
        assert len(resultado["instrucao"]) > 0

    @pytest.mark.asyncio
    async def test_cliente_nao_encontrado_instrucao_verificar(
        self, context_completo, supabase_cliente_nao_encontrado
    ):
        """
        Cenario: CPF nao encontra cliente no sistema.
        Esperado: Instrucao para verificar CPF ou coletar dados.
        """
        from app.ai.tools.customer_tools import CustomerTools

        tools = CustomerTools(context_completo, supabase_cliente_nao_encontrado)
        resultado = await tools.salvar_dados_lead(cpf="12345678901")

        assert resultado["sucesso"] is True
        assert resultado["cliente"] is None
        assert resultado["contrato"] is None

        # Assert: instrucao presente para caso nao encontrado
        assert resultado["instrucao"] is not None
        instrucao = resultado["instrucao"].lower()
        assert "cpf" in instrucao or "cadastro" in instrucao or "dados" in instrucao


class TestRetornoEnriquecidoEstrutura:
    """
    Valida estrutura completa do retorno enriquecido.
    """

    @pytest.mark.asyncio
    async def test_estrutura_completa_retorno(
        self, context_completo, supabase_cliente_contrato_notificado
    ):
        """
        Valida que retorno contem todos os campos esperados.
        """
        from app.ai.tools.customer_tools import CustomerTools

        tools = CustomerTools(context_completo, supabase_cliente_contrato_notificado)
        resultado = await tools.salvar_dados_lead(cpf="08465680107")

        # Campos obrigatorios
        assert "sucesso" in resultado
        assert "cpf" in resultado
        assert "tipo" in resultado
        assert "cliente" in resultado
        assert "contrato" in resultado
        assert "mensagem" in resultado
        assert "instrucao" in resultado

    @pytest.mark.asyncio
    async def test_tipo_documento_cpf(
        self, context_completo, supabase_cliente_contrato_notificado
    ):
        """
        Valida que tipo de documento e identificado corretamente.
        """
        from app.ai.tools.customer_tools import CustomerTools

        tools = CustomerTools(context_completo, supabase_cliente_contrato_notificado)

        # CPF
        resultado = await tools.salvar_dados_lead(cpf="08465680107")
        assert resultado["tipo"] == "CPF"

    @pytest.mark.asyncio
    async def test_cpf_limpo_no_retorno(
        self, context_completo, supabase_cliente_contrato_notificado
    ):
        """
        Valida que CPF retornado esta limpo (apenas numeros).
        """
        from app.ai.tools.customer_tools import CustomerTools

        tools = CustomerTools(context_completo, supabase_cliente_contrato_notificado)

        # CPF com formatacao
        resultado = await tools.salvar_dados_lead(cpf="084.656.801-07")
        assert resultado["cpf"] == "08465680107"
        assert "." not in resultado["cpf"]
        assert "-" not in resultado["cpf"]
