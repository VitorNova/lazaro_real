# tests/test_subscription_updated_reprocess.py
"""
TDD - SUBSCRIPTION_UPDATED deve re-extrair PDF (2026-03-16)

Contexto: Quando funcionário corrige patrimônio no PDF e atualiza subscription,
          o sistema deve re-extrair o PDF para atualizar contract_details.

Causa: SUBSCRIPTION_UPDATED só chamava sincronizar_contrato() sem re-extrair PDF.

Correção: Adicionar background task para processar PDF em SUBSCRIPTION_UPDATED.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


class TestSubscriptionUpdatedReprocess:
    """
    Testa se SUBSCRIPTION_UPDATED agenda re-extração de PDF.
    """

    @pytest.mark.asyncio
    async def test_subscription_updated_schedules_pdf_reprocess(self):
        """
        SUBSCRIPTION_UPDATED deve agendar task de re-extração de PDF
        com force_reprocess=True.
        """
        from app.domain.billing.handlers.webhook_handler import handle_asaas_event

        # Arrange
        mock_supabase = MagicMock()
        mock_background_tasks = MagicMock()
        mock_background_tasks.add_task = MagicMock()

        event = "SUBSCRIPTION_UPDATED"
        body = {
            "subscription": {
                "id": "sub_test123",
                "customer": "cus_test456",
                "value": 189.0,
                "status": "ACTIVE",
            }
        }
        agent_id = "14e6e5ce-4627-4e38-aac8-f0191669ff53"

        # Mock sincronizar_contrato para não fazer chamadas reais
        with patch(
            "app.domain.billing.handlers.webhook_handler.sincronizar_contrato",
            new_callable=AsyncMock
        ) as mock_sync:
            # Act
            result = await handle_asaas_event(
                event=event,
                body=body,
                supabase=mock_supabase,
                agent_id=agent_id,
                background_tasks=mock_background_tasks,
            )

        # Assert
        assert result is True, "handle_asaas_event deve retornar True para SUBSCRIPTION_UPDATED"

        # Verificar que sincronizar_contrato foi chamado
        mock_sync.assert_called_once()

        # CRÍTICO: Verificar que background_tasks.add_task foi chamado
        # para agendar re-extração de PDF
        assert mock_background_tasks.add_task.called, (
            "SUBSCRIPTION_UPDATED deve agendar task de re-extração de PDF"
        )

        # Verificar argumentos da task agendada
        call_args = mock_background_tasks.add_task.call_args
        task_func = call_args[0][0]  # primeiro argumento posicional
        task_kwargs = call_args[1]   # argumentos nomeados

        # Deve chamar processar_subscription_created_background
        assert "processar_subscription_created_background" in str(task_func), (
            "Deve agendar processar_subscription_created_background"
        )

        # Deve passar force_reprocess=True
        assert task_kwargs.get("force_reprocess") is True, (
            "Deve passar force_reprocess=True para forçar re-extração"
        )

        # Deve passar subscription_id correto
        assert task_kwargs.get("subscription_id") == "sub_test123", (
            "Deve passar subscription_id correto"
        )

        # Deve passar customer_id correto
        assert task_kwargs.get("customer_id") == "cus_test456", (
            "Deve passar customer_id correto"
        )

    @pytest.mark.asyncio
    async def test_subscription_updated_without_background_tasks(self):
        """
        SUBSCRIPTION_UPDATED sem background_tasks não deve quebrar.
        """
        from app.domain.billing.handlers.webhook_handler import handle_asaas_event

        # Arrange
        mock_supabase = MagicMock()

        event = "SUBSCRIPTION_UPDATED"
        body = {
            "subscription": {
                "id": "sub_test123",
                "customer": "cus_test456",
            }
        }
        agent_id = "14e6e5ce-4627-4e38-aac8-f0191669ff53"

        with patch(
            "app.domain.billing.handlers.webhook_handler.sincronizar_contrato",
            new_callable=AsyncMock
        ):
            # Act - sem passar background_tasks
            result = await handle_asaas_event(
                event=event,
                body=body,
                supabase=mock_supabase,
                agent_id=agent_id,
                background_tasks=None,
            )

        # Assert - não deve quebrar
        assert result is True

    @pytest.mark.asyncio
    async def test_subscription_created_still_works(self):
        """
        SUBSCRIPTION_CREATED deve continuar funcionando normalmente.
        """
        from app.domain.billing.handlers.webhook_handler import handle_asaas_event

        # Arrange
        mock_supabase = MagicMock()
        mock_background_tasks = MagicMock()
        mock_background_tasks.add_task = MagicMock()

        event = "SUBSCRIPTION_CREATED"
        body = {
            "subscription": {
                "id": "sub_new123",
                "customer": "cus_new456",
            }
        }
        agent_id = "14e6e5ce-4627-4e38-aac8-f0191669ff53"

        with patch(
            "app.domain.billing.handlers.webhook_handler.sincronizar_contrato",
            new_callable=AsyncMock
        ):
            # Act
            result = await handle_asaas_event(
                event=event,
                body=body,
                supabase=mock_supabase,
                agent_id=agent_id,
                background_tasks=mock_background_tasks,
            )

        # Assert
        assert result is True
        assert mock_background_tasks.add_task.called, (
            "SUBSCRIPTION_CREATED deve continuar agendando task"
        )
