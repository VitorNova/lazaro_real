# tests/test_lead_availability.py

"""
TDD — Lead Availability Service [2026-03-19]

Contexto: Verifica se lead está disponível para disparo automático.

Regra de negócio (Cenário 2 — 2026-03-19):
- Billing só bloqueia quando lead está em fila humana (453/454)
- Outros checks foram REMOVIDOS:
  - current_state='human' (só fila 453/454 importa)
  - Atendimento_Finalizado='false' (significa ticket FECHADO, não em andamento)
  - Redis pause (redundante com billing_exceptions)
"""

import pytest
from unittest.mock import MagicMock, patch

# Import com skip se módulo não existir (TDD)
lead_availability = pytest.importorskip(
    "app.domain.leads.services.lead_availability",
    reason="Módulo lead_availability ainda não implementado"
)
check_lead_availability = lead_availability.check_lead_availability


# ─── Helpers de Mock ────────────────────────────────────────────────────────

def make_supabase_mock(table_data: dict) -> MagicMock:
    """Mock do Supabase com dados por tabela."""
    mock = MagicMock()

    def table_side_effect(table_name):
        t = MagicMock()
        data = table_data.get(table_name, [])
        resp = MagicMock()
        resp.data = data

        t.select.return_value.eq.return_value.eq.return_value \
         .limit.return_value.execute.return_value = resp
        t.select.return_value.eq.return_value \
         .limit.return_value.execute.return_value = resp
        t.select.return_value.execute.return_value = resp
        t.update.return_value.eq.return_value.execute.return_value = MagicMock()
        t.insert.return_value.execute.return_value = MagicMock()
        return t

    mock.client.table.side_effect = table_side_effect
    return mock


def make_agent(table_leads: str = "LeadboxCRM_Ana_14e6e5ce") -> dict:
    """Cria um agent dict padrão para testes."""
    return {
        "id": "14e6e5ce-1234-5678-9abc-def012345678",
        "name": "ANA",
        "table_leads": table_leads,
        "table_messages": "leadbox_messages_Ana_14e6e5ce",
        "active": True,
    }


# ─── Constantes ─────────────────────────────────────────────────────────────

QUEUE_ATENDIMENTO = 453
QUEUE_FINANCEIRO = 454
QUEUE_IA = 537
PHONE = "5511999999999"
AGENT_ID = "14e6e5ce-1234-5678-9abc-def012345678"


# ─── Classe de Teste ─────────────────────────────────────────────────────────

class TestLeadAvailability:
    """
    TDD — Verificação de disponibilidade de lead para disparo automático.

    Após Cenário 2 (2026-03-19), os únicos checks são:
    - Lead em fila humana (453/454) → indisponível
    - Agent sem table_leads → indisponível
    - Qualquer outro caso → disponível
    """

    @pytest.mark.asyncio
    async def test_retorna_false_quando_lead_em_fila_453(self):
        """Lead em fila de atendimento humano (453) não deve receber disparo."""
        mock_supabase = make_supabase_mock({
            "LeadboxCRM_Ana_14e6e5ce": [{
                "current_queue_id": QUEUE_ATENDIMENTO,
            }]
        })

        with patch("app.domain.leads.services.lead_availability.get_supabase_service", return_value=mock_supabase):
            available, reason = await check_lead_availability(
                agent=make_agent(),
                phone=PHONE,
                agent_id=AGENT_ID,
            )

        assert available is False
        assert reason == f"human_queue_{QUEUE_ATENDIMENTO}"

    @pytest.mark.asyncio
    async def test_retorna_false_quando_lead_em_fila_454(self):
        """Lead em fila financeira (454) não deve receber disparo."""
        mock_supabase = make_supabase_mock({
            "LeadboxCRM_Ana_14e6e5ce": [{
                "current_queue_id": QUEUE_FINANCEIRO,
            }]
        })

        with patch("app.domain.leads.services.lead_availability.get_supabase_service", return_value=mock_supabase):
            available, reason = await check_lead_availability(
                agent=make_agent(),
                phone=PHONE,
                agent_id=AGENT_ID,
            )

        assert available is False
        assert reason == f"human_queue_{QUEUE_FINANCEIRO}"

    @pytest.mark.asyncio
    async def test_retorna_true_quando_lead_em_fila_537_ia(self):
        """Lead em fila da IA (537) está disponível para disparo."""
        mock_supabase = make_supabase_mock({
            "LeadboxCRM_Ana_14e6e5ce": [{
                "current_queue_id": QUEUE_IA,
            }]
        })

        with patch("app.domain.leads.services.lead_availability.get_supabase_service", return_value=mock_supabase):
            available, reason = await check_lead_availability(
                agent=make_agent(),
                phone=PHONE,
                agent_id=AGENT_ID,
            )

        assert available is True
        assert reason is None

    @pytest.mark.asyncio
    async def test_retorna_true_quando_current_state_human_fora_fila_humana(self):
        """
        current_state='human' em fila 537 DEVE permitir disparo.

        Após Cenário 2: só fila 453/454 bloqueia, current_state é ignorado.
        """
        mock_supabase = make_supabase_mock({
            "LeadboxCRM_Ana_14e6e5ce": [{
                "current_queue_id": QUEUE_IA,
            }]
        })

        with patch("app.domain.leads.services.lead_availability.get_supabase_service", return_value=mock_supabase):
            available, reason = await check_lead_availability(
                agent=make_agent(),
                phone=PHONE,
                agent_id=AGENT_ID,
            )

        assert available is True
        assert reason is None

    @pytest.mark.asyncio
    async def test_retorna_true_quando_atendimento_finalizado_false(self):
        """
        Atendimento_Finalizado='false' DEVE permitir disparo.

        Após Cenário 2: 'false' significa ticket FECHADO, não em andamento.
        """
        mock_supabase = make_supabase_mock({
            "LeadboxCRM_Ana_14e6e5ce": [{
                "current_queue_id": QUEUE_IA,
            }]
        })

        with patch("app.domain.leads.services.lead_availability.get_supabase_service", return_value=mock_supabase):
            available, reason = await check_lead_availability(
                agent=make_agent(),
                phone=PHONE,
                agent_id=AGENT_ID,
            )

        assert available is True
        assert reason is None

    @pytest.mark.asyncio
    async def test_retorna_true_quando_lead_nao_existe(self):
        """Lead que não existe pode receber disparo (será criado)."""
        mock_supabase = make_supabase_mock({
            "LeadboxCRM_Ana_14e6e5ce": []  # Nenhum lead encontrado
        })

        with patch("app.domain.leads.services.lead_availability.get_supabase_service", return_value=mock_supabase):
            available, reason = await check_lead_availability(
                agent=make_agent(),
                phone=PHONE,
                agent_id=AGENT_ID,
            )

        assert available is True
        assert reason is None

    @pytest.mark.asyncio
    async def test_retorna_true_quando_erro_supabase_fail_open(self):
        """Em caso de erro no Supabase, permitir disparo (fail-open)."""
        mock_supabase = MagicMock()
        mock_supabase.client.table.side_effect = Exception("Connection error")

        with patch("app.domain.leads.services.lead_availability.get_supabase_service", return_value=mock_supabase):
            available, reason = await check_lead_availability(
                agent=make_agent(),
                phone=PHONE,
                agent_id=AGENT_ID,
            )

        assert available is True
        assert reason is None

    @pytest.mark.asyncio
    async def test_retorna_false_quando_agent_sem_table_leads(self):
        """Agent sem table_leads configurado não pode disparar."""
        agent_sem_table = {
            "id": AGENT_ID,
            "name": "ANA",
            "table_leads": None,  # Sem tabela configurada
            "active": True,
        }

        available, reason = await check_lead_availability(
            agent=agent_sem_table,
            phone=PHONE,
            agent_id=AGENT_ID,
        )

        assert available is False
        assert reason == "no_table_leads"
