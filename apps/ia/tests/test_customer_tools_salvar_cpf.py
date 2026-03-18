# tests/test_customer_tools_salvar_cpf.py

"""
TDD — Enriquecimento de salvar_dados_lead (2026-03-18)

Contexto: salvar_dados_lead retorna {"sucesso": True, "mensagem": "CPF salvo com sucesso"}
A IA não tem contexto para continuar a conversa e ecoa o retorno literalmente.

Causa: A tool salva o CPF mas não busca dados do cliente/contrato.

Correção: Após salvar CPF, buscar cliente em asaas_clientes e contrato em
contract_details, retornando dados contextuais para orientar a IA.

Cenários:
1. CPF salvo, cliente encontrado, contrato com manutenção notificada
2. CPF salvo, cliente NÃO encontrado no Asaas
3. CPF salvo, cliente encontrado, sem contrato ativo
4. Regressão: mensagem NÃO deve ser "CPF salvo com sucesso" literalmente
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, date, timedelta


# =============================================================================
# HELPERS - Mock de Supabase para cenários de manutenção
# =============================================================================


def make_supabase_mock_manutencao(
    cliente_data: dict = None,
    contrato_data: dict = None,
) -> MagicMock:
    """
    Mock do Supabase para cenários de salvar_dados_lead com enriquecimento.

    Args:
        cliente_data: Dados do cliente em asaas_clientes (ou None se não existe)
        contrato_data: Dados do contrato em contract_details (ou None se não existe)

    Returns:
        Mock do SupabaseService
    """
    mock = MagicMock()

    # Track de chamadas para assertions
    mock._update_calls = {}

    def table_side_effect(table_name):
        t = MagicMock()

        if table_name == "asaas_clientes":
            # SELECT de cliente por CPF
            resp = MagicMock()
            resp.data = [cliente_data] if cliente_data else []

            # Encadeamento: .select().eq().eq().is_().limit().execute()
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
            # Tabela de leads (para update)
            resp = MagicMock()
            resp.data = [{"id": "lead-123"}]

            def capture_update(update_data):
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

    # Método usado pelo CustomerTools atual
    mock.update_lead_by_remotejid = MagicMock()

    return mock


# =============================================================================
# FIXTURES DE DADOS
# =============================================================================


@pytest.fixture
def cliente_leticia():
    """Cliente Letícia com contrato e manutenção notificada."""
    return {
        "id": "cus_abc123",
        "name": "Letícia Paula Gusmão",
        "cpf_cnpj": "08465680107",
        "mobile_phone": "5566996173197",
        "email": "leticia@email.com",
    }


@pytest.fixture
def contrato_manutencao_notificada():
    """Contrato com manutenção preventiva notificada (D-7)."""
    proxima = (date.today() + timedelta(days=7)).isoformat()
    return {
        "id": "contract-uuid-123",
        "customer_id": "cus_abc123",
        "numero_contrato": "2024/001",
        "maintenance_status": "notified",
        "proxima_manutencao": proxima,
        "endereco_instalacao": "Rua das Flores, 123 - Centro",
        "equipamentos": [
            {"marca": "LG", "btus": 12000, "tipo": "Split", "local": "Sala"}
        ],
        "valor_mensal": 150.00,
    }


@pytest.fixture
def contrato_sem_manutencao():
    """Contrato sem manutenção agendada."""
    return {
        "id": "contract-uuid-456",
        "customer_id": "cus_abc123",
        "numero_contrato": "2024/002",
        "maintenance_status": "pending",
        "proxima_manutencao": None,
        "endereco_instalacao": "Av. Brasil, 456",
        "equipamentos": [],
        "valor_mensal": 200.00,
    }


# =============================================================================
# CENÁRIO 1: CPF salvo, cliente encontrado, contrato notificado
# =============================================================================


class TestCenario1ClienteComContratoNotificado:
    """
    Cenário ideal: cliente existe, tem contrato, manutenção foi notificada.

    Retorno esperado:
    - cliente{} com dados do Asaas
    - contrato{} com dados de manutenção
    - mensagem contextual orientando próximo passo
    """

    @pytest.mark.asyncio
    async def test_retorno_contem_dados_cliente(
        self, cliente_leticia, contrato_manutencao_notificada
    ):
        """Retorno deve conter dados do cliente encontrado."""
        from app.ai.tools.customer_tools import CustomerTools

        mock_supabase = make_supabase_mock_manutencao(
            cliente_data=cliente_leticia,
            contrato_data=contrato_manutencao_notificada,
        )

        context = {
            "agent_id": "14e6e5ce-4627-4e38-aac8-f0191669ff53",
            "remotejid": "556696173197@s.whatsapp.net",
            "table_leads": "LeadboxCRM_Ana_14e6e5ce",
        }

        tools = CustomerTools(context, mock_supabase)
        result = await tools.salvar_dados_lead(cpf="08465680107")

        assert result.get("sucesso") is True
        assert "cliente" in result, "Retorno deve conter campo 'cliente'"
        assert result["cliente"]["nome"] == "Letícia Paula Gusmão"
        assert result["cliente"]["cpf"] == "08465680107"

    @pytest.mark.asyncio
    async def test_retorno_contem_dados_contrato(
        self, cliente_leticia, contrato_manutencao_notificada
    ):
        """Retorno deve conter dados do contrato com manutenção."""
        from app.ai.tools.customer_tools import CustomerTools

        mock_supabase = make_supabase_mock_manutencao(
            cliente_data=cliente_leticia,
            contrato_data=contrato_manutencao_notificada,
        )

        context = {
            "agent_id": "14e6e5ce-4627-4e38-aac8-f0191669ff53",
            "remotejid": "556696173197@s.whatsapp.net",
            "table_leads": "LeadboxCRM_Ana_14e6e5ce",
        }

        tools = CustomerTools(context, mock_supabase)
        result = await tools.salvar_dados_lead(cpf="08465680107")

        assert "contrato" in result, "Retorno deve conter campo 'contrato'"
        assert result["contrato"]["maintenance_status"] == "notified"
        assert result["contrato"]["endereco"] is not None

    @pytest.mark.asyncio
    async def test_mensagem_contextual_manutencao(
        self, cliente_leticia, contrato_manutencao_notificada
    ):
        """Mensagem deve orientar sobre manutenção pendente."""
        from app.ai.tools.customer_tools import CustomerTools

        mock_supabase = make_supabase_mock_manutencao(
            cliente_data=cliente_leticia,
            contrato_data=contrato_manutencao_notificada,
        )

        context = {
            "agent_id": "14e6e5ce-4627-4e38-aac8-f0191669ff53",
            "remotejid": "556696173197@s.whatsapp.net",
            "table_leads": "LeadboxCRM_Ana_14e6e5ce",
        }

        tools = CustomerTools(context, mock_supabase)
        result = await tools.salvar_dados_lead(cpf="08465680107")

        mensagem = result.get("mensagem", "").lower()
        # Mensagem deve mencionar manutenção ou contexto do cliente
        assert "manutenção" in mensagem or "cliente" in mensagem or "letícia" in mensagem.lower(), \
            f"Mensagem deveria ser contextual, não genérica: {result.get('mensagem')}"


# =============================================================================
# CENÁRIO 2: CPF salvo, cliente NÃO encontrado
# =============================================================================


class TestCenario2ClienteNaoEncontrado:
    """
    Cliente não existe no Asaas.

    Retorno esperado:
    - cliente=None
    - contrato=None
    - mensagem orientando próximo passo (ex: confirmar CPF ou cadastrar)
    """

    @pytest.mark.asyncio
    async def test_cliente_none_quando_nao_encontrado(self):
        """Retorno deve ter cliente=None quando CPF não existe."""
        from app.ai.tools.customer_tools import CustomerTools

        mock_supabase = make_supabase_mock_manutencao(
            cliente_data=None,  # Não existe
            contrato_data=None,
        )

        context = {
            "agent_id": "14e6e5ce-4627-4e38-aac8-f0191669ff53",
            "remotejid": "556696173197@s.whatsapp.net",
            "table_leads": "LeadboxCRM_Ana_14e6e5ce",
        }

        tools = CustomerTools(context, mock_supabase)
        result = await tools.salvar_dados_lead(cpf="12345678901")

        assert result.get("sucesso") is True, "CPF deve ser salvo mesmo sem cliente"
        assert result.get("cliente") is None, "cliente deve ser None"

    @pytest.mark.asyncio
    async def test_mensagem_orienta_proximo_passo(self):
        """Mensagem deve orientar o que fazer quando cliente não existe."""
        from app.ai.tools.customer_tools import CustomerTools

        mock_supabase = make_supabase_mock_manutencao(
            cliente_data=None,
            contrato_data=None,
        )

        context = {
            "agent_id": "14e6e5ce-4627-4e38-aac8-f0191669ff53",
            "remotejid": "556696173197@s.whatsapp.net",
            "table_leads": "LeadboxCRM_Ana_14e6e5ce",
        }

        tools = CustomerTools(context, mock_supabase)
        result = await tools.salvar_dados_lead(cpf="12345678901")

        mensagem = result.get("mensagem", "")
        # Não deve ser genérica "CPF salvo com sucesso"
        assert "salvo com sucesso" not in mensagem.lower(), \
            "Mensagem não deve ser genérica quando cliente não encontrado"


# =============================================================================
# CENÁRIO 3: CPF salvo, cliente existe, sem contrato
# =============================================================================


class TestCenario3ClienteSemContrato:
    """
    Cliente existe no Asaas mas não tem contrato ativo.

    Retorno esperado:
    - cliente{} com dados
    - contrato=None
    - mensagem contextual
    """

    @pytest.mark.asyncio
    async def test_contrato_none_quando_nao_existe(self, cliente_leticia):
        """Retorno deve ter contrato=None quando não existe."""
        from app.ai.tools.customer_tools import CustomerTools

        mock_supabase = make_supabase_mock_manutencao(
            cliente_data=cliente_leticia,
            contrato_data=None,  # Sem contrato
        )

        context = {
            "agent_id": "14e6e5ce-4627-4e38-aac8-f0191669ff53",
            "remotejid": "556696173197@s.whatsapp.net",
            "table_leads": "LeadboxCRM_Ana_14e6e5ce",
        }

        tools = CustomerTools(context, mock_supabase)
        result = await tools.salvar_dados_lead(cpf="08465680107")

        assert result.get("sucesso") is True
        assert result.get("cliente") is not None, "cliente deve existir"
        assert result.get("contrato") is None, "contrato deve ser None"


# =============================================================================
# CENÁRIO 4: Regressão - mensagem não deve ser literal
# =============================================================================


class TestCenario4RegressaoMensagemLiteral:
    """
    Regressão do bug: IA ecoava "CPF salvo com sucesso" literalmente.

    A mensagem de retorno NUNCA deve ser apenas "CPF salvo com sucesso"
    ou "CNPJ salvo com sucesso" sem contexto adicional.
    """

    @pytest.mark.asyncio
    async def test_mensagem_nao_e_literal_cpf_salvo(self, cliente_leticia, contrato_manutencao_notificada):
        """Mensagem NÃO deve ser 'CPF salvo com sucesso' literalmente."""
        from app.ai.tools.customer_tools import CustomerTools

        mock_supabase = make_supabase_mock_manutencao(
            cliente_data=cliente_leticia,
            contrato_data=contrato_manutencao_notificada,
        )

        context = {
            "agent_id": "14e6e5ce-4627-4e38-aac8-f0191669ff53",
            "remotejid": "556696173197@s.whatsapp.net",
            "table_leads": "LeadboxCRM_Ana_14e6e5ce",
        }

        tools = CustomerTools(context, mock_supabase)
        result = await tools.salvar_dados_lead(cpf="08465680107")

        mensagem = result.get("mensagem", "")

        # Lista de mensagens proibidas (literais demais)
        mensagens_proibidas = [
            "CPF salvo com sucesso",
            "CNPJ salvo com sucesso",
            "cpf salvo com sucesso",
            "cnpj salvo com sucesso",
        ]

        for proibida in mensagens_proibidas:
            assert mensagem != proibida, \
                f"Mensagem não deve ser literal: '{proibida}'"

    @pytest.mark.asyncio
    async def test_mensagem_nao_e_literal_sem_cliente(self):
        """Mesmo sem cliente, mensagem não deve ser literal."""
        from app.ai.tools.customer_tools import CustomerTools

        mock_supabase = make_supabase_mock_manutencao(
            cliente_data=None,
            contrato_data=None,
        )

        context = {
            "agent_id": "14e6e5ce-4627-4e38-aac8-f0191669ff53",
            "remotejid": "556696173197@s.whatsapp.net",
            "table_leads": "LeadboxCRM_Ana_14e6e5ce",
        }

        tools = CustomerTools(context, mock_supabase)
        result = await tools.salvar_dados_lead(cpf="12345678901")

        mensagem = result.get("mensagem", "")

        assert mensagem != "CPF salvo com sucesso", \
            "Mensagem não deve ser literal mesmo sem cliente"

    @pytest.mark.asyncio
    async def test_retorno_contem_instrucao_para_ia(self, cliente_leticia, contrato_manutencao_notificada):
        """Retorno deve conter campo 'instrucao' para orientar a IA."""
        from app.ai.tools.customer_tools import CustomerTools

        mock_supabase = make_supabase_mock_manutencao(
            cliente_data=cliente_leticia,
            contrato_data=contrato_manutencao_notificada,
        )

        context = {
            "agent_id": "14e6e5ce-4627-4e38-aac8-f0191669ff53",
            "remotejid": "556696173197@s.whatsapp.net",
            "table_leads": "LeadboxCRM_Ana_14e6e5ce",
        }

        tools = CustomerTools(context, mock_supabase)
        result = await tools.salvar_dados_lead(cpf="08465680107")

        # Deve ter instrução ou próximo_passo para a IA
        tem_orientacao = (
            "instrucao" in result or
            "proximo_passo" in result or
            "acao" in result or
            "contexto" in result
        )

        assert tem_orientacao, \
            f"Retorno deve conter orientação para a IA continuar: {result.keys()}"
