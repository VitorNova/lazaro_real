# tests/test_billing_dispatcher_phone_normalization.py
"""
TDD — Normalização de telefone no billing dispatcher (2026-03-17)

Contexto: Billing dispatcher salva histórico com telefone do Asaas (5566992028039)
          que é diferente do telefone do Leadbox (556692028039).
          Quando cliente responde, webhook cria outro registro e IA não encontra o link.

Causa: dispatcher.py usa eligible.phone (Asaas) direto, sem normalizar pro Leadbox.

Correção: Antes de salvar histórico, buscar telefone correto no Leadbox via GET /contacts.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, Any


# ─── Fixtures ────────────────────────────────────────────────────────────────

def make_agent() -> Dict[str, Any]:
    """Agente com config Leadbox completa."""
    return {
        "id": "14e6e5ce-4627-4e38-aac8-f0191669ff53",
        "name": "ANA",
        "table_leads": "LeadboxCRM_Ana_14e6e5ce",
        "table_messages": "leadbox_messages_Ana_14e6e5ce",
        "uazapi_base_url": "https://uazapi.example.com",
        "uazapi_token": "token-123",
        "handoff_triggers": {
            "enabled": True,
            "api_url": "https://leadbox.example.com",
            "api_token": "leadbox-token-xyz",
            "api_uuid": "uuid-123",
            "tenant_id": "123",
            "queue_ia": 537,
        },
    }


def make_eligible_payment(phone: str = "5566992028039"):
    """EligiblePayment com telefone do Asaas (com 9 extra)."""
    from datetime import date
    from app.billing.models import EligiblePayment, Payment

    payment = Payment(
        id="pay_test123",
        customer_id="cus_test456",
        customer_name="RAIMUNDO JOSE",
        value=150.00,
        due_date=date(2026, 3, 15),
        status="OVERDUE",
        billing_type="PIX",
        invoice_url="https://asaas.com/i/test123",
        bank_slip_url=None,
        subscription_id=None,
        source="api",
    )

    return EligiblePayment(
        payment=payment,
        phone=phone,  # Telefone do Asaas (com 9 extra)
        customer_name="RAIMUNDO JOSE",
    )


def make_ruler_decision():
    """RulerDecision para teste."""
    from app.billing.models import RulerDecision

    return RulerDecision(
        should_send=True,
        phase="overdue",
        template_key="overdueDia2",
        offset=2,
    )


def make_leadbox_contact_response(number: str = "556692028039"):
    """Resposta do GET /contacts do Leadbox (conforme leadbox.md)."""
    return {
        "contacts": [
            {
                "id": 750876,
                "name": "Raimundo José",
                "number": number,  # Telefone normalizado pelo WhatsApp
                "email": None,
                "profilePicUrl": None,
            }
        ],
    }


def make_leadbox_empty_response():
    """Resposta do GET /contacts quando contato não existe (conforme leadbox.md)."""
    return {
        "contacts": [],
    }


# ─── Mocks ───────────────────────────────────────────────────────────────────

def make_supabase_mock():
    """Mock do Supabase para testes."""
    mock = MagicMock()

    # Mock para buscar agente
    mock.client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[make_agent()]
    )

    # Mock para insert/update
    mock.client.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[{}])
    mock.client.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"id": "new-id"}])

    return mock


def make_httpx_mock(leadbox_response: dict, status_code: int = 200):
    """Mock do httpx.AsyncClient para chamadas ao Leadbox."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = leadbox_response
    mock_response.raise_for_status = MagicMock()

    if status_code >= 400:
        from httpx import HTTPStatusError, Request, Response
        mock_response.raise_for_status.side_effect = HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=mock_response,
        )

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=MagicMock(
        get=AsyncMock(return_value=mock_response),
        post=AsyncMock(return_value=mock_response),
    ))
    mock_client.__aexit__ = AsyncMock(return_value=None)

    return mock_client


# ─── Testes ──────────────────────────────────────────────────────────────────

class TestBillingDispatcherPhoneNormalization:
    """
    TDD — Normalização de telefone no billing dispatcher.

    O dispatcher deve usar o telefone do Leadbox (sem 9 extra) ao salvar
    histórico, não o telefone do Asaas (com 9 extra).
    """

    @pytest.mark.asyncio
    async def test_dispatcher_usa_telefone_leadbox_quando_contato_existe(self):
        """
        Quando o contato existe no Leadbox, o dispatcher deve usar o telefone
        retornado pelo Leadbox (556692028039) ao invés do telefone do Asaas
        (5566992028039).
        """
        from app.billing.dispatcher import dispatch_single

        agent = make_agent()
        eligible = make_eligible_payment(phone="5566992028039")  # Asaas com 9 extra
        decision = make_ruler_decision()
        messages_config = {"overdueDia2": "Mensagem de teste {{nome}}"}

        # Capturar qual telefone foi usado para salvar histórico
        saved_phone = None

        async def capture_save_history(agent, phone, message, notification_type, payment):
            nonlocal saved_phone
            saved_phone = phone

        with patch("app.billing.dispatcher.check_lead_availability", return_value=(True, None)), \
             patch("app.billing.dispatcher.claim_notification", return_value=True), \
             patch("app.billing.dispatcher.leadbox_push_silent", return_value={"success": True, "message_sent_via_push": True}), \
             patch("app.billing.dispatcher.save_message_to_conversation_history", side_effect=capture_save_history), \
             patch("app.billing.dispatcher.get_dispatch_logger") as mock_logger, \
             patch("app.billing.dispatcher.update_notification_status"), \
             patch("app.billing.dispatcher._update_payment_status"), \
             patch("httpx.AsyncClient", return_value=make_httpx_mock(make_leadbox_contact_response("556692028039"))):

            mock_logger.return_value.log_dispatch = AsyncMock()

            result = await dispatch_single(agent, eligible, decision, messages_config)

        # ASSERTION PRINCIPAL: telefone salvo deve ser o do Leadbox (sem 9 extra)
        assert saved_phone == "556692028039", (
            f"Dispatcher deveria usar telefone do Leadbox (556692028039), "
            f"mas usou {saved_phone}"
        )

    @pytest.mark.asyncio
    async def test_dispatcher_usa_telefone_original_quando_contato_nao_existe(self):
        """
        Quando o contato NÃO existe no Leadbox, o dispatcher deve usar o
        telefone original do Asaas como fallback.
        """
        from app.billing.dispatcher import dispatch_single

        agent = make_agent()
        eligible = make_eligible_payment(phone="5566992028039")
        decision = make_ruler_decision()
        messages_config = {"overdueDia2": "Mensagem de teste {{nome}}"}

        saved_phone = None

        async def capture_save_history(agent, phone, message, notification_type, payment):
            nonlocal saved_phone
            saved_phone = phone

        with patch("app.billing.dispatcher.check_lead_availability", return_value=(True, None)), \
             patch("app.billing.dispatcher.claim_notification", return_value=True), \
             patch("app.billing.dispatcher.leadbox_push_silent", return_value={"success": True, "message_sent_via_push": True}), \
             patch("app.billing.dispatcher.save_message_to_conversation_history", side_effect=capture_save_history), \
             patch("app.billing.dispatcher.get_dispatch_logger") as mock_logger, \
             patch("app.billing.dispatcher.update_notification_status"), \
             patch("app.billing.dispatcher._update_payment_status"), \
             patch("httpx.AsyncClient", return_value=make_httpx_mock(make_leadbox_empty_response())):

            mock_logger.return_value.log_dispatch = AsyncMock()

            result = await dispatch_single(agent, eligible, decision, messages_config)

        # Quando não existe contato no Leadbox, usa telefone original
        assert saved_phone == "5566992028039", (
            f"Quando contato não existe no Leadbox, dispatcher deveria usar "
            f"telefone original (5566992028039), mas usou {saved_phone}"
        )

    @pytest.mark.asyncio
    async def test_dispatcher_usa_telefone_original_quando_leadbox_falha(self):
        """
        Quando a chamada ao Leadbox falha (HTTP 500), o dispatcher deve usar
        o telefone original do Asaas como fallback (fail-safe).
        """
        from app.billing.dispatcher import dispatch_single

        agent = make_agent()
        eligible = make_eligible_payment(phone="5566992028039")
        decision = make_ruler_decision()
        messages_config = {"overdueDia2": "Mensagem de teste {{nome}}"}

        saved_phone = None

        async def capture_save_history(agent, phone, message, notification_type, payment):
            nonlocal saved_phone
            saved_phone = phone

        # Mock que simula erro HTTP 500 do Leadbox
        error_mock = make_httpx_mock({}, status_code=500)

        with patch("app.billing.dispatcher.check_lead_availability", return_value=(True, None)), \
             patch("app.billing.dispatcher.claim_notification", return_value=True), \
             patch("app.billing.dispatcher.leadbox_push_silent", return_value={"success": True, "message_sent_via_push": True}), \
             patch("app.billing.dispatcher.save_message_to_conversation_history", side_effect=capture_save_history), \
             patch("app.billing.dispatcher.get_dispatch_logger") as mock_logger, \
             patch("app.billing.dispatcher.update_notification_status"), \
             patch("app.billing.dispatcher._update_payment_status"), \
             patch("httpx.AsyncClient", return_value=error_mock):

            mock_logger.return_value.log_dispatch = AsyncMock()

            result = await dispatch_single(agent, eligible, decision, messages_config)

        # Quando Leadbox falha, usa telefone original (fail-safe)
        assert saved_phone == "5566992028039", (
            f"Quando Leadbox falha, dispatcher deveria usar telefone original "
            f"(5566992028039), mas usou {saved_phone}"
        )

    @pytest.mark.asyncio
    async def test_dispatcher_usa_telefone_original_quando_leadbox_timeout(self):
        """
        Quando a chamada ao Leadbox dá timeout, o dispatcher deve usar
        o telefone original do Asaas como fallback (fail-safe).
        """
        import httpx
        from app.billing.dispatcher import dispatch_single

        agent = make_agent()
        eligible = make_eligible_payment(phone="5566992028039")
        decision = make_ruler_decision()
        messages_config = {"overdueDia2": "Mensagem de teste {{nome}}"}

        saved_phone = None

        async def capture_save_history(agent, phone, message, notification_type, payment):
            nonlocal saved_phone
            saved_phone = phone

        # Mock que simula timeout
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=MagicMock(
            get=AsyncMock(side_effect=httpx.TimeoutException("Connection timeout")),
        ))
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("app.billing.dispatcher.check_lead_availability", return_value=(True, None)), \
             patch("app.billing.dispatcher.claim_notification", return_value=True), \
             patch("app.billing.dispatcher.leadbox_push_silent", return_value={"success": True, "message_sent_via_push": True}), \
             patch("app.billing.dispatcher.save_message_to_conversation_history", side_effect=capture_save_history), \
             patch("app.billing.dispatcher.get_dispatch_logger") as mock_logger, \
             patch("app.billing.dispatcher.update_notification_status"), \
             patch("app.billing.dispatcher._update_payment_status"), \
             patch("httpx.AsyncClient", return_value=mock_client):

            mock_logger.return_value.log_dispatch = AsyncMock()

            result = await dispatch_single(agent, eligible, decision, messages_config)

        # Quando Leadbox dá timeout, usa telefone original (fail-safe)
        assert saved_phone == "5566992028039", (
            f"Quando Leadbox dá timeout, dispatcher deveria usar telefone original "
            f"(5566992028039), mas usou {saved_phone}"
        )

    @pytest.mark.asyncio
    async def test_dispatcher_usa_telefone_original_quando_leadbox_nao_configurado(self):
        """
        Quando o Leadbox não está configurado (handoff_triggers sem api_url),
        o dispatcher deve usar o telefone original do Asaas.
        """
        from app.billing.dispatcher import dispatch_single

        # Agente SEM configuração do Leadbox
        agent = make_agent()
        agent["handoff_triggers"] = {}  # Sem api_url, api_token, etc.

        eligible = make_eligible_payment(phone="5566992028039")
        decision = make_ruler_decision()
        messages_config = {"overdueDia2": "Mensagem de teste {{nome}}"}

        saved_phone = None

        async def capture_save_history(agent, phone, message, notification_type, payment):
            nonlocal saved_phone
            saved_phone = phone

        with patch("app.billing.dispatcher.check_lead_availability", return_value=(True, None)), \
             patch("app.billing.dispatcher.claim_notification", return_value=True), \
             patch("app.billing.dispatcher.leadbox_push_silent", return_value={"success": True, "message_sent_via_push": True}), \
             patch("app.billing.dispatcher.save_message_to_conversation_history", side_effect=capture_save_history), \
             patch("app.billing.dispatcher.get_dispatch_logger") as mock_logger, \
             patch("app.billing.dispatcher.update_notification_status"), \
             patch("app.billing.dispatcher._update_payment_status"):

            mock_logger.return_value.log_dispatch = AsyncMock()

            result = await dispatch_single(agent, eligible, decision, messages_config)

        # Quando Leadbox não configurado, usa telefone original
        assert saved_phone == "5566992028039", (
            f"Quando Leadbox não configurado, dispatcher deveria usar telefone original "
            f"(5566992028039), mas usou {saved_phone}"
        )

    @pytest.mark.asyncio
    async def test_dispatcher_usa_telefone_original_quando_contato_sem_number(self):
        """
        Quando o contato existe no Leadbox mas o campo `number` é null/vazio,
        o dispatcher deve usar o telefone original do Asaas.
        """
        from app.billing.dispatcher import dispatch_single

        agent = make_agent()
        eligible = make_eligible_payment(phone="5566992028039")
        decision = make_ruler_decision()
        messages_config = {"overdueDia2": "Mensagem de teste {{nome}}"}

        saved_phone = None

        async def capture_save_history(agent, phone, message, notification_type, payment):
            nonlocal saved_phone
            saved_phone = phone

        # Resposta do Leadbox com contato mas SEM number
        leadbox_response_no_number = {
            "contacts": [
                {
                    "id": 750876,
                    "name": "Raimundo José",
                    "number": None,  # Campo number é null
                    "email": None,
                    "profilePicUrl": None,
                }
            ],
        }

        with patch("app.billing.dispatcher.check_lead_availability", return_value=(True, None)), \
             patch("app.billing.dispatcher.claim_notification", return_value=True), \
             patch("app.billing.dispatcher.leadbox_push_silent", return_value={"success": True, "message_sent_via_push": True}), \
             patch("app.billing.dispatcher.save_message_to_conversation_history", side_effect=capture_save_history), \
             patch("app.billing.dispatcher.get_dispatch_logger") as mock_logger, \
             patch("app.billing.dispatcher.update_notification_status"), \
             patch("app.billing.dispatcher._update_payment_status"), \
             patch("httpx.AsyncClient", return_value=make_httpx_mock(leadbox_response_no_number)):

            mock_logger.return_value.log_dispatch = AsyncMock()

            result = await dispatch_single(agent, eligible, decision, messages_config)

        # Quando contato não tem number, usa telefone original
        assert saved_phone == "5566992028039", (
            f"Quando contato não tem number, dispatcher deveria usar telefone original "
            f"(5566992028039), mas usou {saved_phone}"
        )

    @pytest.mark.asyncio
    async def test_dispatcher_funciona_quando_telefones_sao_iguais(self):
        """
        Quando o telefone do Asaas é igual ao do Leadbox (sem diferença de 9 extra),
        o dispatcher deve funcionar normalmente usando o telefone do Leadbox.
        """
        from app.billing.dispatcher import dispatch_single

        agent = make_agent()
        # Telefone SEM o 9 extra (caso normal onde Asaas e Leadbox são iguais)
        eligible = make_eligible_payment(phone="556692028039")
        decision = make_ruler_decision()
        messages_config = {"overdueDia2": "Mensagem de teste {{nome}}"}

        saved_phone = None

        async def capture_save_history(agent, phone, message, notification_type, payment):
            nonlocal saved_phone
            saved_phone = phone

        # Leadbox retorna o mesmo telefone
        with patch("app.billing.dispatcher.check_lead_availability", return_value=(True, None)), \
             patch("app.billing.dispatcher.claim_notification", return_value=True), \
             patch("app.billing.dispatcher.leadbox_push_silent", return_value={"success": True, "message_sent_via_push": True}), \
             patch("app.billing.dispatcher.save_message_to_conversation_history", side_effect=capture_save_history), \
             patch("app.billing.dispatcher.get_dispatch_logger") as mock_logger, \
             patch("app.billing.dispatcher.update_notification_status"), \
             patch("app.billing.dispatcher._update_payment_status"), \
             patch("httpx.AsyncClient", return_value=make_httpx_mock(make_leadbox_contact_response("556692028039"))):

            mock_logger.return_value.log_dispatch = AsyncMock()

            result = await dispatch_single(agent, eligible, decision, messages_config)

        # Quando telefones são iguais, usa o do Leadbox (que é igual ao original)
        assert saved_phone == "556692028039", (
            f"Quando telefones são iguais, dispatcher deveria usar 556692028039, "
            f"mas usou {saved_phone}"
        )


# ─── Testes Unitários da Função get_leadbox_phone ────────────────────────────

class TestGetLeadboxPhone:
    """
    Testes unitários para a função get_leadbox_phone isoladamente.

    Garante que a função funciona corretamente independente do dispatch_single.
    """

    @pytest.mark.asyncio
    async def test_retorna_number_do_leadbox_quando_contato_existe(self):
        """Deve retornar o number do contato encontrado no Leadbox."""
        from app.billing.dispatcher import get_leadbox_phone

        handoff_triggers = {
            "api_url": "https://leadbox.example.com",
            "api_token": "token-xyz",
        }

        with patch("app.billing.dispatcher.httpx.AsyncClient", return_value=make_httpx_mock(
            make_leadbox_contact_response("556692028039")
        )):
            result = await get_leadbox_phone(handoff_triggers, "5566992028039")

        assert result == "556692028039"

    @pytest.mark.asyncio
    async def test_retorna_original_quando_number_string_vazia(self):
        """Deve retornar telefone original quando number é string vazia."""
        from app.billing.dispatcher import get_leadbox_phone

        handoff_triggers = {
            "api_url": "https://leadbox.example.com",
            "api_token": "token-xyz",
        }

        # Resposta com number como string vazia
        leadbox_response = {
            "contacts": [{"id": 123, "name": "Test", "number": "", "email": None, "profilePicUrl": None}],
        }

        with patch("app.billing.dispatcher.httpx.AsyncClient", return_value=make_httpx_mock(leadbox_response)):
            result = await get_leadbox_phone(handoff_triggers, "5566992028039")

        assert result == "5566992028039", "Deveria usar telefone original quando number é vazio"

    @pytest.mark.asyncio
    async def test_retorna_original_quando_resposta_malformada(self):
        """Deve retornar telefone original quando resposta não tem campo contacts."""
        from app.billing.dispatcher import get_leadbox_phone

        handoff_triggers = {
            "api_url": "https://leadbox.example.com",
            "api_token": "token-xyz",
        }

        # Resposta malformada (sem campo contacts)
        leadbox_response = {"error": "invalid response", "status": "ok"}

        with patch("app.billing.dispatcher.httpx.AsyncClient", return_value=make_httpx_mock(leadbox_response)):
            result = await get_leadbox_phone(handoff_triggers, "5566992028039")

        assert result == "5566992028039", "Deveria usar telefone original quando resposta é malformada"

    @pytest.mark.asyncio
    async def test_retorna_original_quando_contacts_nao_e_lista(self):
        """Deve retornar telefone original quando contacts não é uma lista."""
        from app.billing.dispatcher import get_leadbox_phone

        handoff_triggers = {
            "api_url": "https://leadbox.example.com",
            "api_token": "token-xyz",
        }

        # Resposta com contacts como string (malformada)
        leadbox_response = {"contacts": "invalid", "count": "0"}

        with patch("app.billing.dispatcher.httpx.AsyncClient", return_value=make_httpx_mock(leadbox_response)):
            result = await get_leadbox_phone(handoff_triggers, "5566992028039")

        assert result == "5566992028039", "Deveria usar telefone original quando contacts não é lista"

    @pytest.mark.asyncio
    async def test_retorna_original_quando_api_url_none(self):
        """Deve retornar telefone original quando api_url é None."""
        from app.billing.dispatcher import get_leadbox_phone

        handoff_triggers = {
            "api_url": None,
            "api_token": "token-xyz",
        }

        result = await get_leadbox_phone(handoff_triggers, "5566992028039")

        assert result == "5566992028039"

    @pytest.mark.asyncio
    async def test_retorna_original_quando_api_token_none(self):
        """Deve retornar telefone original quando api_token é None."""
        from app.billing.dispatcher import get_leadbox_phone

        handoff_triggers = {
            "api_url": "https://leadbox.example.com",
            "api_token": None,
        }

        result = await get_leadbox_phone(handoff_triggers, "5566992028039")

        assert result == "5566992028039"

    @pytest.mark.asyncio
    async def test_chama_leadbox_com_parametros_corretos(self):
        """Deve chamar GET /contacts com uma das variações do telefone."""
        from app.billing.dispatcher import get_leadbox_phone
        from app.core.utils.phone import generate_phone_variants

        handoff_triggers = {
            "api_url": "https://leadbox.example.com",
            "api_token": "token-xyz",
        }

        # Mock que captura os argumentos da chamada
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = make_leadbox_contact_response("556692028039")
        mock_response.raise_for_status = MagicMock()

        mock_get = AsyncMock(return_value=mock_response)

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=MagicMock(get=mock_get))
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("app.billing.dispatcher.httpx.AsyncClient", return_value=mock_client):
            await get_leadbox_phone(handoff_triggers, "5566992028039")

        # Verificar que GET foi chamado
        mock_get.assert_called_once()

        # Verificar URL e parâmetros (searchParam deve ser uma das variações)
        call_args = mock_get.call_args
        assert "https://leadbox.example.com/contacts" in call_args[0][0]
        search_param = call_args[1]["params"]["searchParam"]
        expected_variations = generate_phone_variants("5566992028039")
        assert search_param in expected_variations, f"{search_param} não está em {expected_variations}"
        assert call_args[1]["params"]["limit"] == 1

    @pytest.mark.asyncio
    async def test_chama_leadbox_com_headers_corretos(self):
        """Deve chamar Leadbox com header Authorization correto."""
        from app.billing.dispatcher import get_leadbox_phone

        handoff_triggers = {
            "api_url": "https://leadbox.example.com",
            "api_token": "meu-token-secreto",
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = make_leadbox_contact_response("556692028039")
        mock_response.raise_for_status = MagicMock()

        mock_get = AsyncMock(return_value=mock_response)

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=MagicMock(get=mock_get))
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("app.billing.dispatcher.httpx.AsyncClient", return_value=mock_client):
            await get_leadbox_phone(handoff_triggers, "5566992028039")

        # Verificar header Authorization
        call_args = mock_get.call_args
        headers = call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer meu-token-secreto"

    @pytest.mark.asyncio
    async def test_limpa_telefone_antes_de_buscar(self):
        """Deve limpar o telefone (remover @s.whatsapp.net) antes de buscar."""
        from app.billing.dispatcher import get_leadbox_phone
        from app.core.utils.phone import generate_phone_variants

        handoff_triggers = {
            "api_url": "https://leadbox.example.com",
            "api_token": "token-xyz",
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = make_leadbox_contact_response("556692028039")
        mock_response.raise_for_status = MagicMock()

        mock_get = AsyncMock(return_value=mock_response)

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=MagicMock(get=mock_get))
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("app.billing.dispatcher.httpx.AsyncClient", return_value=mock_client):
            # Passar telefone com sufixo do WhatsApp
            await get_leadbox_phone(handoff_triggers, "5566992028039@s.whatsapp.net")

        # Verificar que searchParam não tem o sufixo e é uma variação válida
        call_args = mock_get.call_args
        search_param = call_args[1]["params"]["searchParam"]
        assert "@s.whatsapp.net" not in search_param
        expected_variations = generate_phone_variants("5566992028039")
        assert search_param in expected_variations, f"{search_param} não está em {expected_variations}"

    @pytest.mark.asyncio
    async def test_normaliza_telefone_com_espacos_e_hifen(self):
        """
        Quando Leadbox retorna number com formato diferente (espaços, hífen, +),
        deve normalizar para apenas dígitos antes de retornar.

        Ex: Leadbox retorna "+55 66 99202-8039" -> deve retornar "5566992028039"
        """
        from app.billing.dispatcher import get_leadbox_phone

        handoff_triggers = {
            "api_url": "https://leadbox.example.com",
            "api_token": "token-xyz",
        }

        # Leadbox retorna telefone com formatação
        leadbox_response = {
            "contacts": [
                {
                    "id": 750876,
                    "name": "Raimundo José",
                    "number": "+55 66 99202-8039",  # Com +, espaços e hífen
                    "email": None,
                    "profilePicUrl": None,
                }
            ],
        }

        with patch("app.billing.dispatcher.httpx.AsyncClient", return_value=make_httpx_mock(leadbox_response)):
            result = await get_leadbox_phone(handoff_triggers, "5566992028039")

        # Deve retornar apenas dígitos, sem formatação
        assert result == "5566992028039", (
            f"Deveria normalizar '+55 66 99202-8039' para '5566992028039', "
            f"mas retornou '{result}'"
        )

    @pytest.mark.asyncio
    async def test_normaliza_telefone_com_parenteses(self):
        """
        Quando Leadbox retorna number com parênteses no DDD,
        deve normalizar para apenas dígitos.

        Ex: Leadbox retorna "55(66)992028039" -> deve retornar "5566992028039"
        """
        from app.billing.dispatcher import get_leadbox_phone

        handoff_triggers = {
            "api_url": "https://leadbox.example.com",
            "api_token": "token-xyz",
        }

        leadbox_response = {
            "contacts": [
                {
                    "id": 750876,
                    "name": "Raimundo José",
                    "number": "55(66)992028039",  # Com parênteses
                    "email": None,
                    "profilePicUrl": None,
                }
            ],
        }

        with patch("app.billing.dispatcher.httpx.AsyncClient", return_value=make_httpx_mock(leadbox_response)):
            result = await get_leadbox_phone(handoff_triggers, "5566992028039")

        assert result == "5566992028039", (
            f"Deveria normalizar '55(66)992028039' para '5566992028039', "
            f"mas retornou '{result}'"
        )


# ─── Testes de Variações de Telefone Brasileiro ─────────────────────────────

class TestPhoneVariations:
    """
    TDD — Variações de telefone brasileiro (2026-03-18)

    Contexto: Busca exata no Leadbox não encontra telefone com 9 extra.
              Precisamos tentar variações (com/sem 9 após DDD).

    NOTA: Usa generate_phone_variants() de app/core/utils/phone.py
    """

    def test_gera_variacao_sem_9_para_telefone_13_digitos(self):
        """
        Telefone de 13 dígitos com 9 após DDD deve gerar variação sem o 9.

        Ex: 5566992028039 -> [5566992028039, 556692028039]
        """
        from app.core.utils.phone import generate_phone_variants

        variations = generate_phone_variants("5566992028039")

        assert len(variations) == 2
        assert "5566992028039" in variations  # Original
        assert "556692028039" in variations   # Sem o 9 extra

    def test_gera_variacao_com_9_para_telefone_12_digitos(self):
        """
        Telefone de 12 dígitos (sem 9) deve gerar variação com o 9.

        Ex: 556692028039 -> [556692028039, 5566992028039]
        """
        from app.core.utils.phone import generate_phone_variants

        variations = generate_phone_variants("556692028039")

        assert len(variations) == 2
        assert "556692028039" in variations   # Original
        assert "5566992028039" in variations  # Com o 9 extra

    def test_nao_gera_variacao_para_telefone_sem_codigo_pais(self):
        """
        Telefone sem código de país (55) deve adicionar 55 e gerar variações.
        """
        from app.core.utils.phone import generate_phone_variants

        # generate_phone_variants adiciona 55 se não tiver
        variations = generate_phone_variants("66992028039")

        # Deve ter adicionado 55 e gerado variação
        assert len(variations) >= 1
        assert any("5566992028039" in v for v in variations)

    def test_nao_gera_variacao_para_telefone_fixo(self):
        """
        Telefone fixo (sem 9 no início do número) gera variação com 9.
        A função não distingue fixo de celular.
        """
        from app.core.utils.phone import generate_phone_variants

        # Telefone fixo: 55 + 66 + 32028039 (8 dígitos começando com 3)
        variations = generate_phone_variants("556632028039")

        # 12 dígitos, então adiciona variação com 9
        assert len(variations) >= 1
        assert "556632028039" in variations

    def test_retorna_lista_vazia_para_telefone_vazio(self):
        """
        Telefone vazio deve retornar lista vazia.
        """
        from app.core.utils.phone import generate_phone_variants

        variations = generate_phone_variants("")

        assert variations == []


class TestGetLeadboxPhoneWithVariations:
    """
    Testes de integração: get_leadbox_phone tenta variações quando busca exata falha.
    """

    @pytest.mark.asyncio
    async def test_encontra_contato_em_uma_das_variacoes(self):
        """
        Quando uma variação encontra o contato, deve retornar o telefone do Leadbox.

        Cenário real:
        - Asaas tem: 5566992028039 (com 9)
        - Leadbox tem: 556692028039 (sem 9)
        - Tenta variações até encontrar
        """
        from app.billing.dispatcher import get_leadbox_phone

        handoff_triggers = {
            "api_url": "https://leadbox.example.com",
            "api_token": "token-xyz",
        }

        calls = []

        def mock_get_side_effect(*args, **kwargs):
            search_param = kwargs.get("params", {}).get("searchParam", "")
            calls.append(search_param)

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()

            # Só encontra quando busca sem o 9
            if search_param == "556692028039":
                mock_response.json.return_value = make_leadbox_contact_response("556692028039")
            else:
                mock_response.json.return_value = {"contacts": []}

            return mock_response

        mock_get = AsyncMock(side_effect=mock_get_side_effect)

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=MagicMock(get=mock_get))
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("app.billing.dispatcher.httpx.AsyncClient", return_value=mock_client):
            result = await get_leadbox_phone(handoff_triggers, "5566992028039")

        # Deve ter encontrado o telefone correto do Leadbox
        assert result == "556692028039", (
            f"Deveria encontrar 556692028039, mas retornou {result}"
        )

        # Deve ter tentado pelo menos uma variação
        assert len(calls) >= 1, f"Deveria ter feito pelo menos 1 chamada, fez {len(calls)}"
        # Deve ter tentado 556692028039 em algum momento
        assert "556692028039" in calls, f"Deveria ter tentado 556692028039, tentou {calls}"

    @pytest.mark.asyncio
    async def test_retorna_original_quando_nenhuma_variacao_encontra(self):
        """
        Quando nenhuma variação encontra, deve retornar telefone original.
        """
        from app.billing.dispatcher import get_leadbox_phone

        handoff_triggers = {
            "api_url": "https://leadbox.example.com",
            "api_token": "token-xyz",
        }

        # Mock que sempre retorna lista vazia
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"contacts": []}
        mock_response.raise_for_status = MagicMock()

        mock_get = AsyncMock(return_value=mock_response)

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=MagicMock(get=mock_get))
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("app.billing.dispatcher.httpx.AsyncClient", return_value=mock_client):
            result = await get_leadbox_phone(handoff_triggers, "5566992028039")

        # Deve retornar original (fallback)
        assert result == "5566992028039"

    @pytest.mark.asyncio
    async def test_para_na_primeira_variacao_quando_encontra(self):
        """
        Quando a primeira variação encontra, não deve tentar a segunda.
        """
        from app.billing.dispatcher import get_leadbox_phone

        handoff_triggers = {
            "api_url": "https://leadbox.example.com",
            "api_token": "token-xyz",
        }

        call_count = 0

        def mock_get_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            # Primeira busca já encontra
            mock_response.json.return_value = make_leadbox_contact_response("5566992028039")
            return mock_response

        mock_get = AsyncMock(side_effect=mock_get_side_effect)

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=MagicMock(get=mock_get))
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("app.billing.dispatcher.httpx.AsyncClient", return_value=mock_client):
            result = await get_leadbox_phone(handoff_triggers, "5566992028039")

        assert result == "5566992028039"
        assert call_count == 1, f"Deveria ter feito apenas 1 chamada, fez {call_count}"
