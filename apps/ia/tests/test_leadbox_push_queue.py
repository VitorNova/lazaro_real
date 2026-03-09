"""
TDD - Bug 2026-03-09: Lead recebeu disparo de manutencao mas caiu na fila errada.

Lead: GABRIEL PIRES DUARTE (556699725973, ticket #856633)
Problema: Recebeu disparo de manutencao com mensagem correta,
          mas ticket ficou no departamento "Aluga Ar" (fila generica)
          em vez da fila 545 (Manutencao).

Causa hipotetica: O PUT de confirmacao de fila apos o PUSH esta falhando
silenciosamente, e o PUSH ignora o forceTicketToDepartment.

Este teste verifica que:
1. leadbox_push_silent DEVE fazer PUT para queueId=545 apos criar ticket
2. Se o PUT falhar, a funcao DEVE retornar success=False ou indicar a falha
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from app.services.leadbox_push import (
    leadbox_push_silent,
    QUEUE_MAINTENANCE,
    QUEUE_BILLING,
    QUEUE_GENERIC,
)


class TestLeadboxPushQueue:
    """
    TDD - Bug GABRIEL PIRES DUARTE 2026-03-09:
    Lead recebeu disparo de manutencao mas ficou na fila errada.
    """

    @pytest.fixture
    def mock_supabase(self):
        """Mock do Supabase com config do agente."""
        mock = MagicMock()
        mock.client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{
                "handoff_triggers": {
                    "enabled": True,
                    "api_url": "https://leadbox.test/api",
                    "api_uuid": "test-uuid",
                    "api_token": "test-token",
                    "dispatch_departments": {
                        "manutencao": {"queueId": 545, "userId": 1095},
                        "billing": {"queueId": 544, "userId": 1095},
                    }
                }
            }]
        )
        return mock

    @pytest.mark.asyncio
    async def test_push_cria_ticket_na_fila_manutencao_quando_ticket_nao_existe(self, mock_supabase):
        """
        Cenario: Ticket NAO existe - PUSH deve criar na fila correta.

        Expectativa: O PUSH deve usar queueId=545 e o PUT de confirmacao
        tambem deve usar queueId=545.
        """
        with patch("app.services.leadbox_push.get_supabase_service", return_value=mock_supabase):
            with patch("httpx.AsyncClient") as mock_http:
                # Mock das respostas HTTP
                mock_client = AsyncMock()
                mock_http.return_value.__aenter__.return_value = mock_client

                # GET contacts - nao encontra contato (ticket nao existe)
                mock_client.get.return_value = AsyncMock(
                    status_code=200,
                    json=lambda: {"contacts": []}
                )
                mock_client.get.return_value.raise_for_status = MagicMock()

                # POST PUSH - cria ticket
                mock_client.post.return_value = AsyncMock(
                    status_code=200,
                    json=lambda: {"ticketId": 856633}
                )
                mock_client.post.return_value.raise_for_status = MagicMock()

                # PUT confirmacao - sucesso
                mock_client.put.return_value = AsyncMock(status_code=200)
                mock_client.put.return_value.raise_for_status = MagicMock()

                result = await leadbox_push_silent(
                    phone="5566999725973",
                    queue_id=QUEUE_MAINTENANCE,  # 545
                    agent_id="14e6e5ce-4627-4e38-aac8-f0191669ff53",
                    message="Mensagem de teste manutencao"
                )

                assert result["success"] is True
                assert result["ticket_id"] == 856633
                assert result["message_sent_via_push"] is True

                # Verificar que o PUT de confirmacao foi chamado com queueId=545
                put_calls = [call for call in mock_client.put.call_args_list]
                assert len(put_calls) >= 1, "PUT de confirmacao deve ser chamado"

                # Verificar o payload do PUT
                put_call = put_calls[0]
                put_payload = put_call.kwargs.get("json", {})
                assert put_payload.get("queueId") == QUEUE_MAINTENANCE, \
                    f"PUT deve usar queueId=545, recebeu: {put_payload}"

    @pytest.mark.asyncio
    async def test_push_move_ticket_para_fila_manutencao_quando_ticket_existe(self, mock_supabase):
        """
        Cenario: Ticket JA existe - PUT deve mover para fila correta.

        Este e o cenario mais provavel do bug: o ticket ja existia
        na fila generica e o PUT nao moveu para 545.
        """
        with patch("app.services.leadbox_push.get_supabase_service", return_value=mock_supabase):
            with patch("httpx.AsyncClient") as mock_http:
                mock_client = AsyncMock()
                mock_http.return_value.__aenter__.return_value = mock_client

                # GET contacts - encontra contato
                contacts_response = AsyncMock(
                    status_code=200,
                    json=lambda: {"contacts": [{"id": 123456}]}
                )
                contacts_response.raise_for_status = MagicMock()

                # GET tickets - encontra ticket aberto na fila generica
                tickets_response = AsyncMock(
                    status_code=200,
                    json=lambda: {"tickets": [{"id": 856633, "status": "open", "queueId": QUEUE_GENERIC}]}
                )
                tickets_response.raise_for_status = MagicMock()

                mock_client.get.side_effect = [contacts_response, tickets_response]

                # PUT para mover de fila - sucesso
                put_response = AsyncMock(status_code=200)
                put_response.raise_for_status = MagicMock()
                mock_client.put.return_value = put_response

                result = await leadbox_push_silent(
                    phone="5566999725973",
                    queue_id=QUEUE_MAINTENANCE,  # 545
                    agent_id="14e6e5ce-4627-4e38-aac8-f0191669ff53",
                    message="Mensagem de teste manutencao"
                )

                assert result["success"] is True
                assert result["ticket_existed"] is True
                assert result["ticket_id"] == 856633
                # Quando ticket existe, caller envia via UAZAPI
                assert result["message_sent_via_push"] is False

                # Verificar que o PUT foi chamado com queueId=545
                put_calls = mock_client.put.call_args_list
                assert len(put_calls) >= 1, "PUT deve ser chamado para mover ticket de fila"

                put_payload = put_calls[0].kwargs.get("json", {})
                assert put_payload.get("queueId") == QUEUE_MAINTENANCE, \
                    f"PUT deve usar queueId=545, recebeu: {put_payload}"

    @pytest.mark.asyncio
    async def test_put_confirmacao_falha_deve_indicar_no_resultado(self, mock_supabase):
        """
        Cenario: PUT de confirmacao FALHA apos PUSH.

        BUG ATUAL: Se o PUT falha, a funcao ainda retorna success=True.
        Isso faz com que o caller ache que tudo deu certo, mas o ticket
        ficou na fila errada.

        Expectativa: Se o PUT de confirmacao falhar, deve haver indicacao
        no resultado para que o caller possa tratar.
        """
        with patch("app.services.leadbox_push.get_supabase_service", return_value=mock_supabase):
            with patch("httpx.AsyncClient") as mock_http:
                mock_client = AsyncMock()
                mock_http.return_value.__aenter__.return_value = mock_client

                # GET contacts - nao encontra contato
                mock_client.get.return_value = AsyncMock(
                    status_code=200,
                    json=lambda: {"contacts": []}
                )
                mock_client.get.return_value.raise_for_status = MagicMock()

                # POST PUSH - cria ticket com sucesso
                mock_client.post.return_value = AsyncMock(
                    status_code=200,
                    json=lambda: {"ticketId": 856633}
                )
                mock_client.post.return_value.raise_for_status = MagicMock()

                # PUT confirmacao - FALHA
                mock_client.put.side_effect = httpx.HTTPStatusError(
                    "Internal Server Error",
                    request=MagicMock(),
                    response=MagicMock(status_code=500, text="Internal Server Error")
                )

                result = await leadbox_push_silent(
                    phone="5566999725973",
                    queue_id=QUEUE_MAINTENANCE,
                    agent_id="14e6e5ce-4627-4e38-aac8-f0191669ff53",
                    message="Mensagem de teste"
                )

                # ESTE TESTE DEVE FALHAR COM O CODIGO ATUAL
                # porque o PUT de confirmacao esta em try/except que ignora erro
                assert "queue_confirmation_failed" in result, \
                    "Resultado deve indicar se PUT de confirmacao falhou"
                assert result.get("queue_confirmation_failed") is True, \
                    "Quando PUT falha, deve indicar queue_confirmation_failed=True"


class TestQueueConstants:
    """Verificar que as constantes de fila estao corretas."""

    def test_queue_constants(self):
        assert QUEUE_BILLING == 544, "Fila de billing deve ser 544"
        assert QUEUE_MAINTENANCE == 545, "Fila de manutencao deve ser 545"
        assert QUEUE_GENERIC == 537, "Fila generica deve ser 537"
