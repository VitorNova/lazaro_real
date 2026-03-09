"""
TDD - Bug 2026-03-09: Lead Kassia Lais (556696512468) na fila IA 537 nao recebeu resposta.

Causa raiz:
- Banco tinha ticket_id=828821 (antigo)
- Lead enviou mensagem, Leadbox criou ticket novo 857387 na fila 537
- Codigo fez PUT /tickets/828821, API retornou 409 Conflict
- Codigo ignorou 409 e interpretou como queue_id=None
- Mensagem foi ignorada porque "API fila=None, confirmado nao-IA"

Correcao necessaria:
- Tratar status 409 em get_current_queue()
- Extrair dados do ticket novo do body da resposta (campo "error" contem JSON stringificado)
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx


class TestGetCurrentQueue409Conflict:
    """
    Testa o tratamento do status 409 Conflict em get_current_queue().

    Quando um ticket foi substituido por outro, a API Leadbox retorna 409
    com os dados do ticket novo no campo "error" como JSON stringificado.
    """

    @pytest.mark.asyncio
    async def test_409_conflict_deve_extrair_dados_do_ticket_novo(self):
        """
        Bug real: Kassia Lais (556696512468) - ticket 828821 substituido por 857387.

        Quando PUT /tickets/828821 retorna 409, o codigo deve:
        1. Detectar que eh 409 Conflict
        2. Parsear o JSON do campo "error"
        3. Retornar os dados do ticket novo (857387)
        """
        from app.services.leadbox import get_current_queue

        # Simular resposta 409 da API Leadbox
        ticket_novo = {
            "id": 857387,
            "queueId": 537,
            "userId": 1095,
            "status": "pending",
            "contactId": 652356
        }

        mock_response_409 = MagicMock()
        mock_response_409.status_code = 409
        mock_response_409.json.return_value = {"error": json.dumps(ticket_novo)}

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.put.return_value = mock_response_409

            result = await get_current_queue(
                api_url="https://enterprise-135api.leadbox.app.br",
                api_token="fake-token",
                phone="556696512468",
                ticket_id=828821,  # Ticket antigo
                ia_queue_id=537
            )

        # Deve retornar dados do ticket novo, nao None
        assert result is not None, "get_current_queue deve retornar dados quando recebe 409"
        assert result.get("queue_id") == 537, f"queue_id deve ser 537, recebeu {result.get('queue_id')}"
        assert result.get("ticket_id") == 857387, f"ticket_id deve ser 857387, recebeu {result.get('ticket_id')}"
        assert result.get("user_id") == 1095, f"user_id deve ser 1095, recebeu {result.get('user_id')}"
        assert result.get("status") == "pending", f"status deve ser pending, recebeu {result.get('status')}"

    @pytest.mark.asyncio
    async def test_200_continua_funcionando_normalmente(self):
        """
        Garantir que o tratamento de 409 nao quebra o caso normal (200).
        """
        from app.services.leadbox import get_current_queue

        ticket_data = {
            "id": 857387,
            "queueId": 537,
            "userId": 1095,
            "status": "pending"
        }

        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200
        mock_response_200.json.return_value = ticket_data

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.put.return_value = mock_response_200

            result = await get_current_queue(
                api_url="https://enterprise-135api.leadbox.app.br",
                api_token="fake-token",
                phone="556696512468",
                ticket_id=857387,
                ia_queue_id=537
            )

        assert result is not None
        assert result.get("queue_id") == 537
        assert result.get("ticket_id") == 857387

    @pytest.mark.asyncio
    async def test_409_com_json_invalido_deve_fazer_fallback(self):
        """
        Se o 409 tiver JSON invalido no error, deve fazer fallback para estrategia 2.
        """
        from app.services.leadbox import get_current_queue

        mock_response_409 = MagicMock()
        mock_response_409.status_code = 409
        mock_response_409.json.return_value = {"error": "not a json"}

        # Mock para fallback - GET /contacts
        mock_response_contacts = MagicMock()
        mock_response_contacts.status_code = 200
        mock_response_contacts.json.return_value = {
            "contacts": [{"id": 652356, "name": "Kassia"}]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.put.return_value = mock_response_409
            mock_instance.get.return_value = mock_response_contacts

            # Deve tentar fallback, nao crashar
            result = await get_current_queue(
                api_url="https://enterprise-135api.leadbox.app.br",
                api_token="fake-token",
                phone="556696512468",
                ticket_id=828821,
                ia_queue_id=537
            )

        # Pode retornar None ou dados do contato, mas nao deve crashar
        # O importante eh nao levantar excecao


class TestIntegracaoMensagemProcessor:
    """
    Testa que a correcao do 409 resolve o bug de mensagens ignoradas.
    """

    @pytest.mark.asyncio
    async def test_lead_fila_ia_com_ticket_substituido_deve_processar(self):
        """
        Cenario completo do bug Kassia:
        1. Banco tem ticket antigo 828821, queue_id=453
        2. Lead envia mensagem
        3. Leadbox cria ticket novo 857387, queue_id=537
        4. Sistema consulta ticket 828821, recebe 409 com dados do 857387
        5. Sistema deve reconhecer que lead esta na fila IA e processar
        """
        # Este teste sera implementado apos a correcao do get_current_queue
        # Por enquanto, apenas documenta o cenario
        pass
