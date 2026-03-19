# tests/test_billing_lead_availability.py

"""
TDD — Billing só bloqueia em fila humana (453/454) [2026-03-19]

Contexto: lead_availability tinha checks redundantes que bloqueavam billing incorretamente
- Atendimento_Finalizado="false" bloqueava (mas significa ticket FECHADO)
- current_state="human" bloqueava mesmo fora de fila humana
- redis_paused bloqueava (redundante com billing_exceptions)

Correção: Manter APENAS check de fila humana (453/454), remover outros checks

Regra de negócio: Cobrança só bloqueia quando lead está em departamento humano.
Em qualquer outro caso, dispara normalmente.
"""

import pytest
from unittest.mock import patch, MagicMock

from app.domain.leads.services.lead_availability import check_lead_availability
from app.integrations.leadbox.types import QUEUE_ATENDIMENTO, QUEUE_FINANCEIRO


# ─── Helpers ─────────────────────────────────────────────────────────────────

def make_agent_with_table() -> dict:
    """Cria agent com table_leads configurado."""
    return {
        "id": "14e6e5ce-test-test-test-000000000001",
        "name": "ANA_TEST",
        "table_leads": "LeadboxCRM_Ana_14e6e5ce",
    }


def make_supabase_response(data: list) -> MagicMock:
    """Cria mock de response do Supabase."""
    mock = MagicMock()
    mock.data = data
    return mock


# ─── Classe de Teste ─────────────────────────────────────────────────────────

class TestBillingLeadAvailability:
    """
    TDD — Billing só bloqueia quando lead está em fila humana (453/454).

    Checks que DEVEM bloquear:
    - Fila 453 (Atendimento)
    - Fila 454 (Financeiro)

    Checks que NÃO DEVEM bloquear (após correção):
    - Atendimento_Finalizado="false"
    - current_state="human" fora de 453/454
    - Redis pause
    - Qualquer outra fila (537, 544, 517, etc)
    """

    @pytest.mark.asyncio
    async def test_bloqueia_quando_em_fila_453(self):
        """Lead em fila 453 (atendimento) DEVE ser bloqueado."""
        agent = make_agent_with_table()
        phone = "5566999999999"

        lead_data = [{
            "current_queue_id": QUEUE_ATENDIMENTO,  # 453
            "current_state": "active",
            "Atendimento_Finalizado": "true",
        }]

        with patch("app.domain.leads.services.lead_availability.get_supabase_service") as mock_supa:
            mock_supa.return_value.client.table.return_value.select.return_value \
                .eq.return_value.limit.return_value.execute.return_value = make_supabase_response(lead_data)

            available, reason = await check_lead_availability(agent, phone, agent["id"])

        assert available is False, "Lead em fila 453 DEVE ser bloqueado"
        assert reason == "human_queue_453"

    @pytest.mark.asyncio
    async def test_bloqueia_quando_em_fila_454(self):
        """Lead em fila 454 (financeiro) DEVE ser bloqueado."""
        agent = make_agent_with_table()
        phone = "5566999999999"

        lead_data = [{
            "current_queue_id": QUEUE_FINANCEIRO,  # 454
            "current_state": "active",
            "Atendimento_Finalizado": "true",
        }]

        with patch("app.domain.leads.services.lead_availability.get_supabase_service") as mock_supa:
            mock_supa.return_value.client.table.return_value.select.return_value \
                .eq.return_value.limit.return_value.execute.return_value = make_supabase_response(lead_data)

            available, reason = await check_lead_availability(agent, phone, agent["id"])

        assert available is False, "Lead em fila 454 DEVE ser bloqueado"
        assert reason == "human_queue_454"

    @pytest.mark.asyncio
    async def test_dispara_com_atendimento_finalizado_false(self):
        """
        Atendimento_Finalizado='false' NÃO DEVE bloquear.

        Este teste FALHA com código atual porque:
        - Código atual verifica: if atendimento_finalizado == "false": return False
        - Mas "false" significa ticket FECHADO (sem atendimento ativo)

        Após correção:
        - Check de Atendimento_Finalizado é removido
        - Lead em fila 537 com Atendimento_Finalizado="false" DEVE disparar
        """
        agent = make_agent_with_table()
        phone = "5566999999999"

        lead_data = [{
            "current_queue_id": 537,  # Fila IA (não humana)
            "current_state": "active",
            "Atendimento_Finalizado": "false",  # Ticket fechado
        }]

        with patch("app.domain.leads.services.lead_availability.get_supabase_service") as mock_supa:
            mock_supa.return_value.client.table.return_value.select.return_value \
                .eq.return_value.limit.return_value.execute.return_value = make_supabase_response(lead_data)

            available, reason = await check_lead_availability(agent, phone, agent["id"])

        assert available is True, (
            "Atendimento_Finalizado='false' NÃO deve bloquear! "
            "Isso significa ticket FECHADO, não atendimento em andamento."
        )
        assert reason is None

    @pytest.mark.asyncio
    async def test_dispara_com_current_state_human_fora_fila_humana(self):
        """
        current_state='human' em fila 517 NÃO DEVE bloquear.

        Este teste FALHA com código atual porque:
        - Código atual verifica: if current_state == "human": return False
        - Mas se não está em fila 453/454, não há atendente ativo

        Após correção:
        - Check de current_state é removido
        - Só fila 453/454 bloqueia
        """
        agent = make_agent_with_table()
        phone = "5566999999999"

        lead_data = [{
            "current_queue_id": 517,  # Fila diferente (não 453/454)
            "current_state": "human",  # Marcado como human
            "Atendimento_Finalizado": "true",
        }]

        with patch("app.domain.leads.services.lead_availability.get_supabase_service") as mock_supa:
            mock_supa.return_value.client.table.return_value.select.return_value \
                .eq.return_value.limit.return_value.execute.return_value = make_supabase_response(lead_data)

            available, reason = await check_lead_availability(agent, phone, agent["id"])

        assert available is True, (
            "current_state='human' em fila 517 NÃO deve bloquear! "
            "Só filas 453/454 indicam atendimento humano real."
        )
        assert reason is None

    @pytest.mark.asyncio
    async def test_dispara_quando_lead_nao_existe(self):
        """Lead não existente DEVE permitir disparo (será criado)."""
        agent = make_agent_with_table()
        phone = "5566999999999"

        # Query retorna vazio
        lead_data = []

        with patch("app.domain.leads.services.lead_availability.get_supabase_service") as mock_supa:
            mock_supa.return_value.client.table.return_value.select.return_value \
                .eq.return_value.limit.return_value.execute.return_value = make_supabase_response(lead_data)

            available, reason = await check_lead_availability(agent, phone, agent["id"])

        assert available is True, "Lead não existente DEVE permitir disparo"
        assert reason is None

    @pytest.mark.asyncio
    async def test_dispara_em_fila_537(self):
        """Lead em fila 537 (IA) DEVE permitir disparo."""
        agent = make_agent_with_table()
        phone = "5566999999999"

        lead_data = [{
            "current_queue_id": 537,
            "current_state": "active",
            "Atendimento_Finalizado": "true",
        }]

        with patch("app.domain.leads.services.lead_availability.get_supabase_service") as mock_supa:
            mock_supa.return_value.client.table.return_value.select.return_value \
                .eq.return_value.limit.return_value.execute.return_value = make_supabase_response(lead_data)

            available, reason = await check_lead_availability(agent, phone, agent["id"])

        assert available is True, "Lead em fila 537 (IA) DEVE permitir disparo"
        assert reason is None

    @pytest.mark.asyncio
    async def test_dispara_em_fila_544(self):
        """Lead em fila 544 (billing) DEVE permitir disparo."""
        agent = make_agent_with_table()
        phone = "5566999999999"

        lead_data = [{
            "current_queue_id": 544,
            "current_state": "active",
            "Atendimento_Finalizado": "false",  # Também testa que false não bloqueia
        }]

        with patch("app.domain.leads.services.lead_availability.get_supabase_service") as mock_supa:
            mock_supa.return_value.client.table.return_value.select.return_value \
                .eq.return_value.limit.return_value.execute.return_value = make_supabase_response(lead_data)

            available, reason = await check_lead_availability(agent, phone, agent["id"])

        assert available is True, "Lead em fila 544 (billing) DEVE permitir disparo"
        assert reason is None
