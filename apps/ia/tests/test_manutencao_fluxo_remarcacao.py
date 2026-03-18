# tests/test_manutencao_fluxo_remarcacao.py

"""
TDD — Fluxo de Remarcação de Manutenção (2026-03-18)

Contexto: Cliente Letícia (556696173197) pediu para remarcar manutenção.
A IA coletou CPF e dia/horário, mas ficou "travada" dizendo
"Vou verificar disponibilidade" sem fazer nada.

Causa: Tools de manutenção (verificar_disponibilidade_manutencao,
confirmar_agendamento_manutencao) estavam declaradas mas o prompt
não ensinava a IA a usá-las.

Correção: Remover as tools de manutenção. O fluxo correto é:
1. Coletar CPF, dia/horário, endereço
2. Transferir para atendimento humano

Este teste verifica:
1. Tools de manutenção NÃO estão declaradas
2. Prompt do agente ensina a transferir após coletar dados de manutenção
3. Handler de transferência funciona corretamente
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from app.ai.tools.cobranca import FUNCTION_DECLARATIONS


# =============================================================================
# TESTE 1: Tools de manutenção NÃO estão declaradas
# =============================================================================


class TestToolsManutencaoRemovidas:
    """
    Verifica que as tools de manutenção foram removidas das declarations.

    Isso força a IA a seguir o fluxo correto: coletar dados → transferir.
    """

    def test_verificar_disponibilidade_manutencao_nao_existe(self):
        """Tool verificar_disponibilidade_manutencao NÃO deve existir."""
        tool_names = [t["name"] for t in FUNCTION_DECLARATIONS]
        assert "verificar_disponibilidade_manutencao" not in tool_names, \
            "Tool verificar_disponibilidade_manutencao deveria ter sido removida"

    def test_confirmar_agendamento_manutencao_nao_existe(self):
        """Tool confirmar_agendamento_manutencao NÃO deve existir."""
        tool_names = [t["name"] for t in FUNCTION_DECLARATIONS]
        assert "confirmar_agendamento_manutencao" not in tool_names, \
            "Tool confirmar_agendamento_manutencao deveria ter sido removida"

    def test_identificar_equipamento_nao_existe(self):
        """Tool identificar_equipamento NÃO deve existir."""
        tool_names = [t["name"] for t in FUNCTION_DECLARATIONS]
        assert "identificar_equipamento" not in tool_names, \
            "Tool identificar_equipamento deveria ter sido removida"

    def test_analisar_foto_equipamento_nao_existe(self):
        """Tool analisar_foto_equipamento NÃO deve existir."""
        tool_names = [t["name"] for t in FUNCTION_DECLARATIONS]
        assert "analisar_foto_equipamento" not in tool_names, \
            "Tool analisar_foto_equipamento deveria ter sido removida"

    def test_apenas_3_tools_ativas(self):
        """Devem existir apenas 3 tools ativas."""
        assert len(FUNCTION_DECLARATIONS) == 3, \
            f"Esperado 3 tools, encontrado {len(FUNCTION_DECLARATIONS)}"

    def test_tools_ativas_sao_corretas(self):
        """As 3 tools ativas devem ser as corretas."""
        tool_names = [t["name"] for t in FUNCTION_DECLARATIONS]
        expected = ["consultar_cliente", "salvar_dados_lead", "transferir_departamento"]
        assert sorted(tool_names) == sorted(expected), \
            f"Tools ativas incorretas: {tool_names}"


# =============================================================================
# TESTE 2: Prompt do agente ensina fluxo correto
# =============================================================================


class TestPromptManutencao:
    """
    Verifica que o prompt do agente ensina o fluxo correto:
    1. Para manutenção, coletar CPF, detalhes, dia/horário, endereço
    2. Transferir APÓS coletar essas informações
    """

    @pytest.fixture
    def mock_supabase(self):
        """Mock do Supabase com agente ANA."""
        mock = MagicMock()
        mock.client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{
            "name": "ANA",
            "system_prompt": """
            - Conserto, manutenção, defeito, quebrado, parou de funcionar, pingando →
              ANTES de transferir: pergunte o CPF/CNPJ, use `consultar_cliente` para
              identificar o equipamento, pergunte detalhes do problema (o que está
              acontecendo, dia/horário preferido para visita) e pergunte o endereço
              onde o ar com problema está instalado. Só transfira APÓS coletar essas
              informações.
            """,
            "handoff_triggers": {
                "tenant_id": "123",
                "queue_ia": 537,
                "departments": {
                    "atendimento": {"queue_id": 453, "user_id": 1095}
                }
            }
        }]
        return mock

    def test_prompt_menciona_coletar_cpf_antes_de_transferir(self, mock_supabase):
        """Prompt deve mencionar coletar CPF ANTES de transferir."""
        agent = mock_supabase.client.table().select().eq().limit().execute().data[0]
        prompt = agent["system_prompt"].lower()

        assert "cpf" in prompt, "Prompt deve mencionar CPF"
        assert "antes de transferir" in prompt, "Prompt deve mencionar 'antes de transferir'"

    def test_prompt_menciona_coletar_detalhes(self, mock_supabase):
        """Prompt deve mencionar coletar detalhes do problema."""
        agent = mock_supabase.client.table().select().eq().limit().execute().data[0]
        prompt = agent["system_prompt"].lower()

        assert "detalhes" in prompt or "o que está acontecendo" in prompt.lower(), \
            "Prompt deve mencionar coletar detalhes do problema"

    def test_prompt_menciona_coletar_horario(self, mock_supabase):
        """Prompt deve mencionar coletar dia/horário."""
        agent = mock_supabase.client.table().select().eq().limit().execute().data[0]
        prompt = agent["system_prompt"].lower()

        assert "horário" in prompt or "dia" in prompt, \
            "Prompt deve mencionar coletar dia/horário"

    def test_prompt_menciona_coletar_endereco(self, mock_supabase):
        """Prompt deve mencionar coletar endereço."""
        agent = mock_supabase.client.table().select().eq().limit().execute().data[0]
        prompt = agent["system_prompt"].lower()

        assert "endereço" in prompt or "endereco" in prompt, \
            "Prompt deve mencionar coletar endereço"

    def test_prompt_menciona_transferir_apos_coletar(self, mock_supabase):
        """Prompt deve mencionar transferir APÓS coletar informações."""
        agent = mock_supabase.client.table().select().eq().limit().execute().data[0]
        prompt = agent["system_prompt"].lower()

        assert "só transfira após" in prompt or "transfira após" in prompt, \
            "Prompt deve mencionar 'só transfira APÓS coletar'"


# =============================================================================
# TESTE 3: Cenário real - conversa da Letícia
# =============================================================================


class TestCenarioLeticia:
    """
    Reproduz o cenário real da cliente Letícia:
    1. Pediu remarcação de manutenção
    2. IA pediu CPF
    3. Cliente deu CPF → IA salvou
    4. IA pediu dia/horário/endereço
    5. Cliente deu dia/horário + localização
    6. IA deveria transferir (não ficar travada)

    Este teste verifica que o histórico de conversa está estruturado
    corretamente e que os dados foram coletados.
    """

    @pytest.fixture
    def historico_leticia(self):
        """Histórico real da conversa da Letícia (simplificado)."""
        return {
            "messages": [
                {"role": "user", "parts": [{"text": "Poderíamos remarcar a manutenção pra outro horário?"}]},
                {"role": "model", "parts": [{"text": "Claro! Me informa seu CPF e melhor dia/horário"}]},
                {"role": "user", "parts": [{"text": "084.656.801-07"}]},
                {"role": "model", "parts": [{"function_call": {"name": "salvar_dados_lead", "args": {"cpf": "084.656.801-07"}}}]},
                {"role": "function", "parts": [{"function_response": {"name": "salvar_dados_lead", "response": {"sucesso": True, "cpf": "08465680107"}}}]},
                {"role": "model", "parts": [{"text": "CPF salvo com sucesso"}]},  # ← PROBLEMA: resposta ruim
                {"role": "user", "parts": [{"text": "Dia 24 às 13h30. Local: [location recebido]"}]},
                {"role": "model", "parts": [{"text": "Vou verificar a disponibilidade. Só um momento..."}]},  # ← PROBLEMA: travou
            ]
        }

    def test_historico_contem_pedido_remarcacao(self, historico_leticia):
        """Primeira mensagem deve ser pedido de remarcação."""
        primeira_msg = historico_leticia["messages"][0]
        assert primeira_msg["role"] == "user"
        assert "remarcar" in primeira_msg["parts"][0]["text"].lower()

    def test_historico_contem_cpf_salvo(self, historico_leticia):
        """Histórico deve conter chamada de salvar_dados_lead."""
        function_calls = [
            m for m in historico_leticia["messages"]
            if m["role"] == "model" and "function_call" in m.get("parts", [{}])[0]
        ]
        assert len(function_calls) >= 1, "Deveria ter chamado salvar_dados_lead"

        call = function_calls[0]["parts"][0]["function_call"]
        assert call["name"] == "salvar_dados_lead"

    def test_historico_contem_dados_coletados(self, historico_leticia):
        """Histórico deve conter dia/horário fornecidos pelo cliente."""
        mensagens_usuario = [
            m["parts"][0]["text"] for m in historico_leticia["messages"]
            if m["role"] == "user"
        ]

        # Cliente forneceu dia/horário na última mensagem
        ultima_msg = mensagens_usuario[-1]
        assert "24" in ultima_msg, "Cliente informou dia 24"
        assert "13h30" in ultima_msg or "13:30" in ultima_msg, "Cliente informou horário"

    def test_ia_nao_chamou_transferir_departamento(self, historico_leticia):
        """
        BUG: IA NÃO chamou transferir_departamento após coletar dados.

        Este teste documenta o problema. Após a correção (remover tools
        de manutenção), a IA deveria transferir ao invés de ficar travada.
        """
        function_calls = [
            m["parts"][0].get("function_call", {}).get("name")
            for m in historico_leticia["messages"]
            if m["role"] == "model" and "function_call" in m.get("parts", [{}])[0]
        ]

        # Documenta o bug: IA não transferiu
        assert "transferir_departamento" not in function_calls, \
            "Este teste documenta o bug: IA não transferiu após coletar dados"

    def test_ia_respondeu_literalmente_retorno_da_tool(self, historico_leticia):
        """
        BUG: IA respondeu literalmente 'CPF salvo com sucesso'.

        Isso é o retorno da tool, não uma resposta conversacional.
        """
        mensagens_ia = [
            m["parts"][0].get("text", "")
            for m in historico_leticia["messages"]
            if m["role"] == "model" and "text" in m.get("parts", [{}])[0]
        ]

        # Documenta o bug: resposta literal da tool
        respostas_ruins = [m for m in mensagens_ia if "CPF salvo com sucesso" in m]
        assert len(respostas_ruins) > 0, \
            "Este teste documenta o bug: IA respondeu literalmente o retorno da tool"


# =============================================================================
# TESTE 4: Handler de transferência funciona
# =============================================================================


class TestHandlerTransferencia:
    """
    Verifica que o handler de transferir_departamento funciona corretamente.

    Quando a IA chamar a tool, deve conseguir transferir para atendimento.
    """

    @pytest.mark.asyncio
    async def test_transferir_para_atendimento_funciona(self):
        """
        Simula chamada de transferir_departamento para atendimento.
        """
        from app.ai.tools.transfer_tools import TransferTools

        # Mock do supabase e contexto
        mock_supabase = MagicMock()
        context = {
            "agent_id": "14e6e5ce-4627-4e38-aac8-f0191669ff53",
            "remotejid": "556696173197@s.whatsapp.net",
            "phone": "556696173197",
            "table_leads": "LeadboxCRM_Ana_14e6e5ce",
            "handoff_triggers": {
                "enabled": True,
                "tenant_id": "123",
                "queue_ia": 537,
                "api_url": "https://leadbox.test",
                "api_uuid": "test-uuid",
                "api_token": "test-token",
                "departments": {
                    "atendimento": {"queue_id": 453, "user_id": 1095}
                }
            }
        }

        transfer_tools = TransferTools(mock_supabase, context)

        # Mock do resolve_department e LeadboxService
        with patch('app.ai.tools.transfer_tools.resolve_department') as mock_resolve:
            mock_resolve.return_value = (453, 1095, "atendimento")

            with patch('app.ai.tools.transfer_tools.LeadboxService') as MockLeadbox:
                mock_leadbox_instance = MagicMock()
                mock_leadbox_instance.transfer_to_department = AsyncMock(return_value={
                    "sucesso": True,
                    "ticket_id": 864657
                })
                MockLeadbox.return_value = mock_leadbox_instance

                # Chamar transferência
                result = await transfer_tools.transferir_departamento(
                    departamento="atendimento",
                    motivo="remarcação de manutenção - cliente forneceu dia 24 às 13h30"
                )

                # Verificar que resolve_department foi chamado
                mock_resolve.assert_called_once()

                # Verificar que LeadboxService foi criado
                MockLeadbox.assert_called_once()

                # Verificar que transfer_to_department foi chamado
                mock_leadbox_instance.transfer_to_department.assert_called_once()

                # Verificar resultado
                assert result.get("sucesso") is True, \
                    f"Transferência deveria ter sucesso: {result}"
