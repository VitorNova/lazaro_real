"""
TDD - Bug 2026-03-09: notification_service deve reagir a queue_confirmation_failed.

Continuacao do bug GABRIEL PIRES DUARTE (ticket #856633).
O leadbox_push agora retorna queue_confirmation_failed=True quando o PUT falha,
mas o notification_service precisa tratar esse caso.

Comportamento esperado:
1. Se queue_confirmation_failed=True, deve logar WARNING
2. Deve registrar no dispatch_log que houve problema com a fila
3. Stats deve contabilizar como "queue_errors" para visibilidade
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date

from app.domain.maintenance.services.notification_service import (
    process_maintenance_notifications,
    QUEUE_MAINTENANCE,
)


class TestMaintenanceNotificationQueueHandling:
    """
    TDD - Bug GABRIEL PIRES DUARTE 2026-03-09:
    notification_service deve reagir quando leadbox_push retorna queue_confirmation_failed.
    """

    @pytest.fixture
    def mock_agent(self):
        return {
            "id": "14e6e5ce-4627-4e38-aac8-f0191669ff53",
            "name": "Ana",
            "uazapi_base_url": "https://uazapi.test",
            "uazapi_token": "test-token",
            "table_messages": "leadbox_messages_Ana_14e6e5ce",
        }

    @pytest.fixture
    def mock_contract_hoje(self):
        """Contrato que deve ser notificado hoje (D-7)."""
        return {
            "id": "test-contract-123",
            "customer_id": "cus_test",
            "nome": "GABRIEL PIRES DUARTE",
            "mobile_phone": "66999725973",
            "data_inicio": "2025-09-16",  # proxima manutencao = 2026-03-16, D-7 = 2026-03-09
            "endereco_instalacao": "Rua Teste, 123",
            "equipamentos": [{"marca": "AGRATTO", "btus": 9000}],
            "notificacao_enviada_at": None,
            "maintenance_status": None,
        }

    @pytest.mark.asyncio
    async def test_deve_logar_warning_quando_queue_confirmation_failed(
        self, mock_agent, mock_contract_hoje
    ):
        """
        Quando leadbox_push retorna queue_confirmation_failed=True,
        notification_service deve logar WARNING indicando o problema.
        """
        hoje = date(2026, 3, 9)  # D-7 para contrato com data_inicio 2025-09-16

        with patch(
            "app.domain.maintenance.services.notification_service.fetch_contracts_for_maintenance",
            new_callable=AsyncMock,
            return_value=[mock_contract_hoje],
        ):
            with patch(
                "app.domain.maintenance.services.notification_service.leadbox_push_silent",
                new_callable=AsyncMock,
                return_value={
                    "success": True,
                    "ticket_existed": False,
                    "ticket_id": 856633,
                    "message_sent_via_push": True,
                    "ticket_check_failed": False,
                    "queue_confirmation_failed": True,  # PUT falhou!
                },
            ):
                with patch(
                    "app.domain.maintenance.services.notification_service.mark_notification_sent",
                    new_callable=AsyncMock,
                ):
                    with patch(
                        "app.domain.maintenance.services.notification_service.get_dispatch_logger"
                    ) as mock_dispatch_logger:
                        mock_logger_instance = MagicMock()
                        mock_logger_instance.log_dispatch = AsyncMock()
                        mock_logger_instance.log_failure = AsyncMock()
                        mock_dispatch_logger.return_value = mock_logger_instance

                        with patch(
                            "app.domain.maintenance.services.notification_service.logger"
                        ) as mock_logger:
                            stats = await process_maintenance_notifications(
                                mock_agent["id"], mock_agent, hoje
                            )

                            # Deve ter logado warning sobre queue_confirmation_failed
                            warning_calls = [
                                call for call in mock_logger.warning.call_args_list
                                if "queue" in str(call).lower() or "fila" in str(call).lower()
                            ]
                            assert len(warning_calls) >= 1, \
                                "Deve logar WARNING quando queue_confirmation_failed=True"

    @pytest.mark.asyncio
    async def test_deve_registrar_queue_errors_nas_stats(
        self, mock_agent, mock_contract_hoje
    ):
        """
        Quando queue_confirmation_failed=True, stats deve incluir queue_errors.
        """
        hoje = date(2026, 3, 9)

        with patch(
            "app.domain.maintenance.services.notification_service.fetch_contracts_for_maintenance",
            new_callable=AsyncMock,
            return_value=[mock_contract_hoje],
        ):
            with patch(
                "app.domain.maintenance.services.notification_service.leadbox_push_silent",
                new_callable=AsyncMock,
                return_value={
                    "success": True,
                    "ticket_existed": False,
                    "ticket_id": 856633,
                    "message_sent_via_push": True,
                    "ticket_check_failed": False,
                    "queue_confirmation_failed": True,
                },
            ):
                with patch(
                    "app.domain.maintenance.services.notification_service.mark_notification_sent",
                    new_callable=AsyncMock,
                ):
                    with patch(
                        "app.domain.maintenance.services.notification_service.get_dispatch_logger"
                    ) as mock_dispatch_logger:
                        mock_logger_instance = MagicMock()
                        mock_logger_instance.log_dispatch = AsyncMock()
                        mock_dispatch_logger.return_value = mock_logger_instance

                        stats = await process_maintenance_notifications(
                            mock_agent["id"], mock_agent, hoje
                        )

                        # ESTE TESTE DEVE FALHAR COM O CODIGO ATUAL
                        assert "queue_errors" in stats, \
                            "Stats deve incluir queue_errors quando PUT de fila falha"
                        assert stats["queue_errors"] >= 1, \
                            "Deve contabilizar ao menos 1 queue_error"

    @pytest.mark.asyncio
    async def test_deve_registrar_no_dispatch_log_com_warning_de_fila(
        self, mock_agent, mock_contract_hoje
    ):
        """
        Quando queue_confirmation_failed=True, dispatch_log deve indicar o problema.
        """
        hoje = date(2026, 3, 9)

        with patch(
            "app.domain.maintenance.services.notification_service.fetch_contracts_for_maintenance",
            new_callable=AsyncMock,
            return_value=[mock_contract_hoje],
        ):
            with patch(
                "app.domain.maintenance.services.notification_service.leadbox_push_silent",
                new_callable=AsyncMock,
                return_value={
                    "success": True,
                    "ticket_existed": False,
                    "ticket_id": 856633,
                    "message_sent_via_push": True,
                    "ticket_check_failed": False,
                    "queue_confirmation_failed": True,
                },
            ):
                with patch(
                    "app.domain.maintenance.services.notification_service.mark_notification_sent",
                    new_callable=AsyncMock,
                ):
                    with patch(
                        "app.domain.maintenance.services.notification_service.get_dispatch_logger"
                    ) as mock_dispatch_logger:
                        mock_logger_instance = MagicMock()
                        mock_logger_instance.log_dispatch = AsyncMock()
                        mock_dispatch_logger.return_value = mock_logger_instance

                        await process_maintenance_notifications(
                            mock_agent["id"], mock_agent, hoje
                        )

                        # Verificar que log_dispatch foi chamado com metadata indicando problema
                        assert mock_logger_instance.log_dispatch.called, \
                            "Deve chamar log_dispatch mesmo com queue_confirmation_failed"

                        call_kwargs = mock_logger_instance.log_dispatch.call_args.kwargs
                        metadata = call_kwargs.get("metadata", {})

                        # ESTE TESTE DEVE FALHAR COM O CODIGO ATUAL
                        assert metadata.get("queue_confirmation_failed") is True, \
                            "Metadata deve indicar queue_confirmation_failed=True"
