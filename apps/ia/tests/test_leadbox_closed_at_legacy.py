# tests/test_leadbox_closed_at_legacy.py

"""
TDD - Bug: IA entra em conversa durante atendimento humano (2026-03-16)

Contexto: Lead Tamirys (556692360564) estava sendo atendida pela Nathalia,
mas a IA (Ana) enviou mensagem no meio da conversa.

Causa: Leadbox envia UpdateOnTicket com closedAt preenchido (timestamp antigo)
mas status=open. O sistema interpretava closedAt como "ticket fechado" e
removia a pausa da IA indevidamente.

Correção: Ignorar closedAt quando status=open. Só considerar fechado se
event_type=FinishedTicket OU status=closed.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestLeadboxClosedAtLegacy:
    """
    Testes para garantir que closedAt legado não reativa a IA indevidamente.
    """

    @pytest.fixture
    def mock_request(self):
        """Factory para criar mock de Request com payload JSON."""
        def _make_request(payload: dict):
            request = MagicMock()
            request.json = AsyncMock(return_value=payload)
            return request
        return _make_request

    @pytest.fixture
    def mock_background_tasks(self):
        return MagicMock()

    @pytest.mark.asyncio
    async def test_update_on_ticket_com_status_open_e_closed_at_nao_deve_fechar(
        self, mock_request, mock_background_tasks
    ):
        """
        UpdateOnTicket com status=open e closedAt preenchido NAO deve
        chamar handle_ticket_closed. O ticket foi reaberto e closedAt
        é um timestamp legado.
        """
        # Arrange - payload real do bug (ticket 856443)
        payload = {
            "event": "UpdateOnTicket",
            "tenantId": "123",
            "ticket": {
                "id": 856443,
                "status": "open",  # <-- ABERTO
                "closedAt": 1773430587953,  # <-- timestamp legado
                "queueId": 453,  # fila da Nathalia (humano)
                "userId": 123,
                "contact": {
                    "number": "556692360564"
                }
            }
        }

        with patch("app.api.routes.leadbox.handle_ticket_closed") as mock_closed, \
             patch("app.api.routes.leadbox.handle_queue_change") as mock_queue_change, \
             patch("app.api.routes.leadbox.handle_new_message") as mock_new_message:

            mock_queue_change.return_value = {"status": "ok"}

            from app.api.routes.leadbox import leadbox_webhook

            request = mock_request(payload)

            # Act
            result = await leadbox_webhook(request, mock_background_tasks)

            # Assert - NAO deve chamar handle_ticket_closed
            mock_closed.assert_not_called()

            # Assert - DEVE chamar handle_queue_change (fila 453 = humano)
            mock_queue_change.assert_called_once()
            call_args = mock_queue_change.call_args
            assert call_args[0][0] == "556692360564"  # phone
            assert call_args[0][1] == 453  # queue_id

    @pytest.mark.asyncio
    async def test_update_on_ticket_com_status_closed_deve_fechar(
        self, mock_request, mock_background_tasks
    ):
        """
        UpdateOnTicket com status=closed DEVE chamar handle_ticket_closed,
        independente do valor de closedAt.
        """
        payload = {
            "event": "UpdateOnTicket",
            "tenantId": "123",
            "ticket": {
                "id": 856443,
                "status": "closed",  # <-- FECHADO
                "closedAt": 1773430587953,
                "queueId": 453,
                "userId": 123,
                "contact": {
                    "number": "556692360564"
                }
            }
        }

        with patch("app.api.routes.leadbox.handle_ticket_closed") as mock_closed, \
             patch("app.api.routes.leadbox.handle_queue_change") as mock_queue_change:

            mock_closed.return_value = {"status": "ok", "event": "ticket_closed"}

            from app.api.routes.leadbox import leadbox_webhook

            request = mock_request(payload)

            # Act
            result = await leadbox_webhook(request, mock_background_tasks)

            # Assert - DEVE chamar handle_ticket_closed
            mock_closed.assert_called_once()

            # Assert - NAO deve chamar handle_queue_change
            mock_queue_change.assert_not_called()

    @pytest.mark.asyncio
    async def test_finished_ticket_sempre_deve_fechar(
        self, mock_request, mock_background_tasks
    ):
        """
        FinishedTicket SEMPRE deve chamar handle_ticket_closed,
        independente do status ou closedAt.
        """
        payload = {
            "event": "FinishedTicket",
            "tenantId": "123",
            "ticket": {
                "id": 856443,
                "status": "open",  # status pode estar open no momento do evento
                "closedAt": 1773430587953,
                "contact": {
                    "number": "556692360564"
                }
            }
        }

        with patch("app.api.routes.leadbox.handle_ticket_closed") as mock_closed, \
             patch("app.api.routes.leadbox.handle_queue_change") as mock_queue_change:

            mock_closed.return_value = {"status": "ok", "event": "ticket_closed"}

            from app.api.routes.leadbox import leadbox_webhook

            request = mock_request(payload)

            # Act
            result = await leadbox_webhook(request, mock_background_tasks)

            # Assert - DEVE chamar handle_ticket_closed
            mock_closed.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_on_ticket_sem_closed_at_deve_processar_fila(
        self, mock_request, mock_background_tasks
    ):
        """
        UpdateOnTicket normal (sem closedAt, status=open) deve processar
        mudanca de fila normalmente.
        """
        payload = {
            "event": "UpdateOnTicket",
            "tenantId": "123",
            "ticket": {
                "id": 856444,
                "status": "open",
                "closedAt": None,  # sem closedAt
                "queueId": 537,  # fila IA
                "userId": 456,
                "contact": {
                    "number": "556699999999"
                }
            }
        }

        with patch("app.api.routes.leadbox.handle_ticket_closed") as mock_closed, \
             patch("app.api.routes.leadbox.handle_queue_change") as mock_queue_change:

            mock_queue_change.return_value = {"status": "ok"}

            from app.api.routes.leadbox import leadbox_webhook

            request = mock_request(payload)

            # Act
            result = await leadbox_webhook(request, mock_background_tasks)

            # Assert - NAO deve chamar handle_ticket_closed
            mock_closed.assert_not_called()

            # Assert - DEVE chamar handle_queue_change
            mock_queue_change.assert_called_once()
            call_args = mock_queue_change.call_args
            assert call_args[0][1] == 537  # queue_id = fila IA

    @pytest.mark.asyncio
    async def test_update_on_ticket_com_queue_id_none_deve_fechar(
        self, mock_request, mock_background_tasks
    ):
        """
        UpdateOnTicket com queueId=None indica ticket removido da fila,
        deve chamar handle_ticket_closed (comportamento existente).
        """
        payload = {
            "event": "UpdateOnTicket",
            "tenantId": "123",
            "ticket": {
                "id": 856443,
                "status": "open",
                "closedAt": None,
                "queueId": None,  # removido da fila
                "userId": None,
                "contact": {
                    "number": "556692360564"
                }
            }
        }

        with patch("app.api.routes.leadbox.handle_ticket_closed") as mock_closed, \
             patch("app.api.routes.leadbox.handle_queue_change") as mock_queue_change:

            mock_closed.return_value = {"status": "ok", "event": "ticket_closed"}

            from app.api.routes.leadbox import leadbox_webhook

            request = mock_request(payload)

            # Act
            result = await leadbox_webhook(request, mock_background_tasks)

            # Assert - DEVE chamar handle_ticket_closed (queueId=None)
            mock_closed.assert_called_once()
