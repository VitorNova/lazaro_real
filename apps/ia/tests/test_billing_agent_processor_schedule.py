# tests/test_billing_agent_processor_schedule.py

"""
TDD — agent_processor deve usar overdueDays do agente, não DEFAULT_SCHEDULE [2026-03-19]

Contexto: Cliente ALESSANDRO (556699076079) recebeu apenas 1 cobrança porque D+4
          não está no DEFAULT_SCHEDULE hardcoded no ruler.py
Causa: agent_processor chama evaluate(today, due_date) SEM passar o schedule do agente
Correção: Construir schedule a partir da config do agente e passar para evaluate()

Bug identificado em: apps/ia/app/billing/agent_processor.py linhas 59, 105, 168
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import date

from app.billing.agent_processor import process_agent
from app.billing.models import Payment, EligiblePayment, EligibilityResult


# ─── Helpers ─────────────────────────────────────────────────────────────────

def make_agent_with_all_overdue_days() -> dict:
    """
    Cria agent com overdueDays incluindo TODOS os dias de D+1 a D+15.
    Isso inclui D+4, que NÃO está no DEFAULT_SCHEDULE.
    """
    return {
        "id": "14e6e5ce-test-test-test-000000000001",
        "name": "ANA_TEST",
        "asaas_config": {
            "autoCollection": {
                "reminderDays": [1],
                "onDueDate": True,
                "afterDue": {
                    "enabled": True,
                    "maxAttempts": 15,
                    "overdueDays": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
                }
            }
        }
    }


def make_payment_d_plus_4(today: date) -> Payment:
    """
    Cria payment com due_date tal que hoje seja D+4 (dias úteis).

    Exemplo: today=2026-03-19 (quinta), due_date=2026-03-14 (sábado)
    Dias úteis entre 14/03 e 19/03: seg 16, ter 17, qua 18, qui 19 = 4 dias
    """
    # 14/03/2026 é sábado, 19/03/2026 é quinta = 4 dias úteis depois
    due_date = date(2026, 3, 14)

    return Payment(
        id="pay_test_d4",
        customer_id="cus_test_123",
        customer_name="CLIENTE TESTE D+4",
        value=189.00,
        due_date=due_date,
        status="OVERDUE",
        billing_type="BOLETO",
        invoice_url="https://asaas.com/i/pay_test_d4",
        bank_slip_url=None,
        subscription_id="sub_test_123",
        source="cache",
    )


def make_eligible_payment(payment: Payment) -> EligiblePayment:
    """Cria EligiblePayment a partir de Payment."""
    return EligiblePayment(
        payment=payment,
        phone="5566999999999",
        customer_name=payment.customer_name,
    )


# ─── Classe de Teste ─────────────────────────────────────────────────────────

class TestAgentProcessorScheduleFromConfig:
    """
    TDD — agent_processor deve respeitar overdueDays da config do agente.

    O bug: evaluate() é chamado sem o parâmetro schedule, então usa DEFAULT_SCHEDULE
    que não inclui D+4, D+6, D+8, D+9, D+11, D+13, D+14.

    A correção: construir schedule a partir de reminderDays + [0] + overdueDays
    e passar para evaluate().
    """

    @pytest.mark.asyncio
    async def test_dispatch_chamado_para_d_plus_4_quando_config_inclui(self):
        """
        Se overdueDays do agente inclui D+4, dispatch_single DEVE ser chamado.

        Este teste FALHA com o código atual porque:
        - evaluate() usa DEFAULT_SCHEDULE = [-1, 0, 1, 2, 3, 5, 7, 10, 12, 15]
        - D+4 não está na lista
        - should_send = False
        - dispatch_single não é chamado

        Após correção:
        - evaluate() usa schedule construído do agente = [..., 4, ...]
        - D+4 está na lista
        - should_send = True
        - dispatch_single É chamado
        """
        agent = make_agent_with_all_overdue_days()
        today = date(2026, 3, 19)  # quinta-feira
        payment = make_payment_d_plus_4(today)
        eligible = make_eligible_payment(payment)

        # Mock collect_payments: retorna o payment D+4 na fase OVERDUE
        mock_collect_result = MagicMock()
        mock_collect_result.payments = [payment]
        mock_collect_result.degraded = False

        # Mock run_eligibility_checks: retorna como elegível
        mock_eligibility_result = EligibilityResult(
            eligible=[eligible],
            rejected=[],
        )

        with patch(
            "app.billing.agent_processor.collect_payments",
            new_callable=AsyncMock,
            return_value=mock_collect_result,
        ), patch(
            "app.billing.agent_processor.run_eligibility_checks",
            new_callable=AsyncMock,
            return_value=mock_eligibility_result,
        ), patch(
            "app.billing.agent_processor.dispatch_single",
            new_callable=AsyncMock,
        ) as mock_dispatch:
            # Configurar retorno do dispatch
            mock_dispatch.return_value = MagicMock(status="sent")

            # Executar
            stats = await process_agent(agent, today)

        # ASSERT: dispatch_single FOI chamado para o payment D+4
        assert mock_dispatch.called, (
            "dispatch_single NÃO foi chamado! "
            "O bug ainda existe: evaluate() está usando DEFAULT_SCHEDULE "
            "em vez do overdueDays do agente."
        )

        # Verificar que foi chamado com os argumentos corretos
        call_args = mock_dispatch.call_args
        called_eligible = call_args[0][1]  # segundo argumento posicional
        assert called_eligible.payment.id == "pay_test_d4"

    @pytest.mark.asyncio
    async def test_d_plus_4_esta_no_default_schedule(self):
        """
        Verificar se D+4 está no DEFAULT_SCHEDULE.

        Este teste documenta o bug: D+4 NÃO está no DEFAULT_SCHEDULE.
        """
        from app.billing.ruler import DEFAULT_SCHEDULE

        # D+4 NÃO está no DEFAULT_SCHEDULE (este é o bug)
        assert 4 not in DEFAULT_SCHEDULE, (
            "D+4 agora está no DEFAULT_SCHEDULE? "
            "Se sim, o bug foi corrigido alterando DEFAULT_SCHEDULE "
            "em vez de usar a config do agente."
        )

    @pytest.mark.asyncio
    async def test_dispatch_nao_chamado_para_offset_fora_do_config(self):
        """
        Se overdueDays do agente NÃO inclui um dia, dispatch NÃO deve ser chamado.

        Exemplo: overdueDays=[1,2,3,5] (sem 4), hoje=D+4 → não envia
        """
        agent = {
            "id": "14e6e5ce-test-test-test-000000000002",
            "name": "ANA_TEST_2",
            "asaas_config": {
                "autoCollection": {
                    "reminderDays": [1],
                    "onDueDate": True,
                    "afterDue": {
                        "enabled": True,
                        "maxAttempts": 15,
                        # Propositalmente SEM o 4
                        "overdueDays": [1, 2, 3, 5, 7, 10, 12, 15],
                    }
                }
            }
        }
        today = date(2026, 3, 19)  # D+4
        payment = make_payment_d_plus_4(today)
        eligible = make_eligible_payment(payment)

        mock_collect_result = MagicMock()
        mock_collect_result.payments = [payment]
        mock_collect_result.degraded = False

        mock_eligibility_result = EligibilityResult(
            eligible=[eligible],
            rejected=[],
        )

        with patch(
            "app.billing.agent_processor.collect_payments",
            new_callable=AsyncMock,
            return_value=mock_collect_result,
        ), patch(
            "app.billing.agent_processor.run_eligibility_checks",
            new_callable=AsyncMock,
            return_value=mock_eligibility_result,
        ), patch(
            "app.billing.agent_processor.dispatch_single",
            new_callable=AsyncMock,
        ) as mock_dispatch:
            mock_dispatch.return_value = MagicMock(status="sent")

            stats = await process_agent(agent, today)

        # ASSERT: dispatch_single NÃO foi chamado (D+4 não está no overdueDays)
        # Nota: Após correção, este teste deve continuar passando
        # porque estamos testando que a config do agente é respeitada
        assert not mock_dispatch.called or stats["skipped"] > 0, (
            "dispatch_single foi chamado mesmo com D+4 fora do overdueDays!"
        )
