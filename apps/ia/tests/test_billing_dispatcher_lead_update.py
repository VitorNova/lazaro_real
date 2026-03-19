# tests/test_billing_dispatcher_lead_update.py

"""
TDD — Desnormalizar Ultimo Disparo de Billing na Tabela de Leads (2026-03-19)

Contexto: Apos disparo de cobranca, queremos visualizar a data do ultimo disparo
          diretamente na tabela de leads sem fazer N queries.
Causa: Nao havia colunas last_billing_sent_at e last_billing_type no lead.
Correcao: Adicionar colunas e atualizar no dispatcher.py apos envio confirmado.
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.billing.models import EligiblePayment, RulerDecision, Payment


# ─── Helpers de Mock ────────────────────────────────────────────────────────


def make_supabase_mock_with_capture() -> MagicMock:
    """
    Mock do Supabase que captura chamadas UPDATE para assertions.
    """
    mock = MagicMock()
    mock._update_calls = {}

    def table_side_effect(table_name):
        t = MagicMock()
        resp = MagicMock()
        resp.data = []

        # SELECT chains
        t.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = resp
        t.select.return_value.eq.return_value.eq.return_value.execute.return_value = resp

        # UPDATE - captura argumentos
        def capture_update(update_data):
            if table_name not in mock._update_calls:
                mock._update_calls[table_name] = []
            mock._update_calls[table_name].append(update_data)
            update_chain = MagicMock()
            update_chain.eq.return_value.execute.return_value = MagicMock(data=[])
            return update_chain

        t.update.side_effect = capture_update

        # RPC
        mock.client.rpc.return_value.execute.return_value = MagicMock(data=[{"claimed": True}])

        return t

    mock.client.table.side_effect = table_side_effect
    mock.client.rpc.return_value.execute.return_value = MagicMock(data=[{"claimed": True}])
    return mock


def make_agent(table_leads: str = "LeadboxCRM_Ana_test") -> dict:
    """Cria agente de teste com table_leads configurado."""
    return {
        "id": "14e6e5ce-4627-4e38-aac8-f0191669ff53",
        "name": "Ana",
        "table_leads": table_leads,
        "table_messages": "leadbox_messages_Ana_test",
        "uazapi_base_url": "https://uazapi.test",
        "uazapi_token": "test-token",
        "handoff_triggers": {
            "api_url": "https://api.test",
            "api_token": "test-token",
        },
    }


def make_eligible_payment(phone: str = "556697194084") -> EligiblePayment:
    """Cria pagamento elegivel para teste."""
    from datetime import date
    return EligiblePayment(
        payment=Payment(
            id="pay_test123",
            customer_id="cus_test",
            customer_name="JOAO TESTE",
            value=150.0,
            due_date=date(2026, 3, 20),
            status="PENDING",
            billing_type="BOLETO",
            invoice_url="https://asaas.com/pay/test",
            bank_slip_url=None,
            subscription_id=None,
            source="api",
        ),
        phone=phone,
        customer_name="JOAO TESTE",
    )


def make_ruler_decision(phase: str = "reminder", offset: int = -1) -> RulerDecision:
    """Cria decisao da regua de cobranca."""
    return RulerDecision(
        should_send=True,
        phase=phase,
        template_key=f"{phase}_template",
        offset=offset,
    )


# ─── Testes ─────────────────────────────────────────────────────────────────


class TestDispatchUpdatesLeadBillingInfo:
    """
    Apos disparo de cobranca bem-sucedido, o lead deve ter
    last_billing_sent_at e last_billing_type atualizados.
    """

    @pytest.mark.asyncio
    async def test_dispatch_atualiza_last_billing_no_lead(self):
        """
        Apos envio bem-sucedido, dispatcher deve atualizar
        last_billing_sent_at e last_billing_type no lead.
        """
        # Arrange
        mock_supabase = make_supabase_mock_with_capture()
        agent = make_agent(table_leads="LeadboxCRM_Ana_test")
        eligible = make_eligible_payment(phone="556697194084")
        decision = make_ruler_decision(phase="reminder", offset=-1)
        messages_config = {"reminderTemplate": "Ola {nome}, sua fatura vence amanha!"}

        with patch("app.billing.dispatcher.get_supabase_service", return_value=mock_supabase), \
             patch("app.billing.dispatcher.leadbox_push_silent", new_callable=AsyncMock) as mock_push, \
             patch("app.billing.dispatcher.check_lead_availability", new_callable=AsyncMock) as mock_avail, \
             patch("app.billing.dispatcher.claim_notification", new_callable=AsyncMock) as mock_claim, \
             patch("app.billing.dispatcher.save_message_to_conversation_history", new_callable=AsyncMock), \
             patch("app.billing.dispatcher.get_dispatch_logger") as mock_logger, \
             patch("app.billing.dispatcher.update_notification_status", new_callable=AsyncMock), \
             patch("app.billing.dispatcher.get_leadbox_phone", new_callable=AsyncMock) as mock_phone:

            # Configurar mocks
            mock_avail.return_value = (True, None)
            mock_claim.return_value = True
            mock_push.return_value = {"message_sent_via_push": True}
            mock_phone.return_value = "556697194084"
            mock_logger.return_value = MagicMock(
                log_dispatch=AsyncMock(),
                log_failure=AsyncMock(),
            )

            # Act
            from app.billing.dispatcher import dispatch_single
            result = await dispatch_single(agent, eligible, decision, messages_config)

            # Assert - disparo bem-sucedido
            assert result.status == "sent"

            # Assert - lead foi atualizado com info de billing
            update_calls = mock_supabase._update_calls.get("LeadboxCRM_Ana_test", [])
            assert len(update_calls) >= 1, "Deveria ter atualizado o lead"

            last_update = update_calls[-1]
            assert "last_billing_sent_at" in last_update, "Deveria ter last_billing_sent_at"
            assert "last_billing_type" in last_update, "Deveria ter last_billing_type"
            assert last_update["last_billing_type"] == "reminder"

    @pytest.mark.asyncio
    async def test_dispatch_nao_atualiza_lead_se_falhou(self):
        """
        Se o disparo falhar, NAO deve atualizar as colunas de billing no lead.
        """
        # Arrange
        mock_supabase = make_supabase_mock_with_capture()
        agent = make_agent(table_leads="LeadboxCRM_Ana_test")
        eligible = make_eligible_payment(phone="556697194084")
        decision = make_ruler_decision(phase="overdue", offset=5)
        messages_config = {}

        with patch("app.billing.dispatcher.get_supabase_service", return_value=mock_supabase), \
             patch("app.billing.dispatcher.leadbox_push_silent", new_callable=AsyncMock) as mock_push, \
             patch("app.billing.dispatcher.check_lead_availability", new_callable=AsyncMock) as mock_avail, \
             patch("app.billing.dispatcher.claim_notification", new_callable=AsyncMock) as mock_claim, \
             patch("app.billing.dispatcher.get_dispatch_logger") as mock_logger, \
             patch("app.billing.dispatcher.update_notification_status", new_callable=AsyncMock), \
             patch("app.billing.dispatcher.get_leadbox_phone", new_callable=AsyncMock) as mock_phone:

            # Configurar mocks - simular falha no envio
            mock_avail.return_value = (True, None)
            mock_claim.return_value = True
            mock_push.side_effect = Exception("Erro de rede")
            mock_phone.return_value = "556697194084"
            mock_logger.return_value = MagicMock(
                log_dispatch=AsyncMock(),
                log_failure=AsyncMock(),
            )

            # Act
            from app.billing.dispatcher import dispatch_single
            result = await dispatch_single(agent, eligible, decision, messages_config)

            # Assert - disparo falhou
            assert result.status == "error"

            # Assert - lead NAO foi atualizado com info de billing
            update_calls = mock_supabase._update_calls.get("LeadboxCRM_Ana_test", [])
            billing_updates = [u for u in update_calls if "last_billing_sent_at" in u]
            assert len(billing_updates) == 0, "Nao deveria ter atualizado o lead em caso de falha"
