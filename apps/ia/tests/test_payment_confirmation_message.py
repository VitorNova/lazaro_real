"""
Testes TDD para envio de mensagem de confirmação de pagamento.

Cenários:
1. Fluxo principal - mensagem enviada via UAZAPI
2. Identificação do cliente - múltiplas estratégias
3. Proteção contra duplicata - webhook 2x = 1 mensagem
4. Falhas - resiliência a erros
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch, call

# Imports que serão criados
from app.domain.billing.services.confirmacao_pagamento import (
    enviar_confirmacao_pagamento,
    buscar_dados_cliente,
    ja_enviou_confirmacao,
    formatar_mensagem_confirmacao,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def payment_data():
    """Dados de pagamento recebido do Asaas."""
    return {
        "id": "pay_abc123",
        "customer": "cus_xyz789",
        "value": 350.00,
        "paymentDate": "2024-03-07",
        "status": "RECEIVED",
    }


@pytest.fixture
def agent_data():
    """Dados do agente para envio."""
    return {
        "id": "14e6e5ce-4627-4e38-aac8-f0191669ff53",
        "name": "Ana",
        "uazapi_base_url": "https://uazapi.example.com",
        "uazapi_token": "token123",
        "table_leads": "LeadboxCRM_Ana_14e6e5ce",
        "table_messages": "leadbox_messages_Ana_14e6e5ce",
    }


@pytest.fixture
def cliente_asaas():
    """Cliente cadastrado no Asaas."""
    return {
        "id": "cus_xyz789",
        "name": "Maria Santos",
        "mobile_phone": "5566998887777",
        "phone": "5566998887777",
        "cpf_cnpj": "12345678901",
    }


@pytest.fixture
def lead_com_historico():
    """Lead com conversation_history existente."""
    return {
        "id": "lead_123",
        "remotejid": "5566998887777@s.whatsapp.net",
        "conversation_history": {
            "messages": [
                {
                    "role": "user",
                    "text": "Oi, quero pagar minha fatura",
                    "timestamp": "2024-03-06T10:00:00",
                }
            ]
        }
    }


@pytest.fixture
def mock_supabase():
    """Mock do serviço Supabase."""
    mock = MagicMock()
    mock.client = MagicMock()
    return mock


@pytest.fixture
def mock_uazapi():
    """Mock do serviço UAZAPI."""
    mock = AsyncMock()
    mock.send_text_message = AsyncMock(return_value={"success": True})
    return mock


# =============================================================================
# CENÁRIO 1: FLUXO PRINCIPAL
# =============================================================================

class TestFluxoPrincipal:
    """Testes do fluxo principal de confirmação de pagamento."""

    @pytest.mark.asyncio
    async def test_mensagem_enviada_com_sucesso(
        self, payment_data, agent_data, cliente_asaas, mock_supabase
    ):
        """Pagamento recebido → mensagem enviada via UAZAPI."""
        # Arrange
        mock_supabase.client.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = cliente_asaas

        with patch("app.domain.billing.services.confirmacao_pagamento.UazapiService") as mock_uazapi_class, \
             patch("app.domain.billing.services.confirmacao_pagamento.leadbox_push_silent") as mock_push:

            mock_push.return_value = {"success": False, "ticket_check_failed": True}
            mock_uazapi_instance = AsyncMock()
            mock_uazapi_instance.send_text_message = AsyncMock(return_value={"success": True})
            mock_uazapi_class.return_value = mock_uazapi_instance

            # Act
            result = await enviar_confirmacao_pagamento(
                supabase=mock_supabase,
                agent=agent_data,
                payment=payment_data,
            )

            # Assert
            assert result["success"] is True
            assert result["message_sent"] is True
            mock_uazapi_instance.send_text_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_mensagem_contem_nome_e_valor(
        self, payment_data, cliente_asaas
    ):
        """Mensagem deve conter nome do cliente e valor pago."""
        # Act
        mensagem = formatar_mensagem_confirmacao(
            nome_cliente=cliente_asaas["name"],
            valor=payment_data["value"],
        )

        # Assert
        assert "Maria" in mensagem  # Primeiro nome
        assert "350" in mensagem or "350,00" in mensagem
        assert "pagamento" in mensagem.lower()
        assert "confirmamos" in mensagem.lower() or "recebemos" in mensagem.lower()

    @pytest.mark.asyncio
    async def test_conversation_history_atualizado(
        self, payment_data, agent_data, cliente_asaas, lead_com_historico, mock_supabase
    ):
        """conversation_history deve ser atualizado com context='pagamento_confirmado'."""
        # Arrange
        phone = cliente_asaas["mobile_phone"]
        phone_jid = f"{phone}@s.whatsapp.net"

        # Mock para buscar cliente
        mock_table_clientes = MagicMock()
        mock_table_clientes.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = cliente_asaas

        # Mock para buscar lead (usa .or_() com variantes de telefone)
        mock_table_messages = MagicMock()
        mock_table_messages.select.return_value.or_.return_value.limit.return_value.execute.return_value.data = [lead_com_historico]
        mock_table_messages.update.return_value.eq.return_value.execute.return_value.data = lead_com_historico

        def table_router(name):
            if name == "asaas_clientes":
                return mock_table_clientes
            return mock_table_messages

        mock_supabase.client.table = table_router

        with patch("app.domain.billing.services.confirmacao_pagamento.UazapiService") as mock_uazapi_class, \
             patch("app.domain.billing.services.confirmacao_pagamento.leadbox_push_silent") as mock_push:

            mock_push.return_value = {"success": True, "message_sent_via_push": True}
            mock_uazapi_class.return_value = AsyncMock()

            # Act
            result = await enviar_confirmacao_pagamento(
                supabase=mock_supabase,
                agent=agent_data,
                payment=payment_data,
            )

            # Assert
            assert result["success"] is True
            assert result["history_updated"] is True


# =============================================================================
# CENÁRIO 2: IDENTIFICAÇÃO DO CLIENTE
# =============================================================================

class TestIdentificacaoCliente:
    """Testes de estratégias de identificação do cliente."""

    @pytest.mark.asyncio
    async def test_telefone_encontrado_via_asaas_clientes(
        self, payment_data, cliente_asaas, mock_supabase
    ):
        """Telefone deve ser buscado via asaas_clientes.mobile_phone."""
        # Arrange
        mock_supabase.client.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = cliente_asaas

        # Act
        dados = await buscar_dados_cliente(
            supabase=mock_supabase,
            customer_id=payment_data["customer"],
            payment_id=payment_data["id"],
        )

        # Assert
        assert dados is not None
        assert dados["phone"] == "5566998887777"
        assert dados["name"] == "Maria Santos"

    @pytest.mark.asyncio
    async def test_telefone_encontrado_via_billing_notifications(
        self, payment_data, mock_supabase
    ):
        """Fallback: telefone via billing_notifications.phone."""
        # Arrange - asaas_clientes não tem telefone
        cliente_sem_telefone = {"id": "cus_xyz789", "name": "Maria", "mobile_phone": None, "phone": None}
        billing_notification = {"phone": "5566998887777", "customer_name": "Maria Santos"}

        mock_table_clientes = MagicMock()
        mock_table_clientes.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = cliente_sem_telefone

        mock_table_billing = MagicMock()
        mock_table_billing.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [billing_notification]

        def table_router(name):
            if name == "asaas_clientes":
                return mock_table_clientes
            return mock_table_billing

        mock_supabase.client.table = table_router

        # Act
        dados = await buscar_dados_cliente(
            supabase=mock_supabase,
            customer_id=payment_data["customer"],
            payment_id=payment_data["id"],
        )

        # Assert
        assert dados is not None
        assert dados["phone"] == "5566998887777"

    @pytest.mark.asyncio
    async def test_telefone_nao_encontrado_retorna_none(
        self, payment_data, mock_supabase
    ):
        """Se telefone não encontrado em nenhum lugar, retorna None."""
        # Arrange
        cliente_sem_telefone = {"id": "cus_xyz789", "name": "Maria", "mobile_phone": None, "phone": None}

        mock_table = MagicMock()
        mock_table.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = cliente_sem_telefone
        mock_table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
        mock_supabase.client.table.return_value = mock_table

        # Act
        dados = await buscar_dados_cliente(
            supabase=mock_supabase,
            customer_id=payment_data["customer"],
            payment_id=payment_data["id"],
        )

        # Assert
        assert dados is None


# =============================================================================
# CENÁRIO 3: PROTEÇÃO CONTRA DUPLICATA
# =============================================================================

class TestProtecaoDuplicata:
    """Testes de proteção contra envio duplicado."""

    @pytest.mark.asyncio
    async def test_ja_enviou_confirmacao_retorna_true(
        self, payment_data, mock_supabase
    ):
        """Se já existe mensagem com context='pagamento_confirmado' e payment_id, retorna True."""
        # Arrange
        historico_com_confirmacao = {
            "messages": [
                {
                    "role": "model",
                    "text": "Confirmamos seu pagamento!",
                    "timestamp": "2024-03-07T10:00:00",
                    "context": "pagamento_confirmado",
                    "payment_id": "pay_abc123",
                }
            ]
        }

        lead_com_confirmacao = {
            "id": "lead_123",
            "remotejid": "5566998887777@s.whatsapp.net",
            "conversation_history": historico_com_confirmacao,
        }

        mock_supabase.client.table.return_value.select.return_value.or_.return_value.limit.return_value.execute.return_value.data = [lead_com_confirmacao]

        # Act
        ja_enviou = await ja_enviou_confirmacao(
            supabase=mock_supabase,
            table_messages="leadbox_messages_Ana_14e6e5ce",
            phone="5566998887777",
            payment_id="pay_abc123",
        )

        # Assert
        assert ja_enviou is True

    @pytest.mark.asyncio
    async def test_nao_enviou_confirmacao_retorna_false(
        self, payment_data, lead_com_historico, mock_supabase
    ):
        """Se não existe mensagem de confirmação para esse payment_id, retorna False."""
        # Arrange
        mock_supabase.client.table.return_value.select.return_value.or_.return_value.limit.return_value.execute.return_value.data = [lead_com_historico]

        # Act
        ja_enviou = await ja_enviou_confirmacao(
            supabase=mock_supabase,
            table_messages="leadbox_messages_Ana_14e6e5ce",
            phone="5566998887777",
            payment_id="pay_abc123",
        )

        # Assert
        assert ja_enviou is False

    @pytest.mark.asyncio
    async def test_webhook_duplicado_nao_envia_segunda_mensagem(
        self, payment_data, agent_data, cliente_asaas, mock_supabase
    ):
        """Webhook chegando 2x → apenas 1 mensagem enviada."""
        # Arrange - já existe confirmação no histórico
        historico_com_confirmacao = {
            "messages": [
                {
                    "role": "model",
                    "text": "Confirmamos seu pagamento!",
                    "context": "pagamento_confirmado",
                    "payment_id": "pay_abc123",
                }
            ]
        }
        lead = {"id": "lead_123", "remotejid": "5566998887777@s.whatsapp.net", "conversation_history": historico_com_confirmacao}

        mock_table_clientes = MagicMock()
        mock_table_clientes.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = cliente_asaas

        mock_table_messages = MagicMock()
        mock_table_messages.select.return_value.or_.return_value.limit.return_value.execute.return_value.data = [lead]

        def table_router(name):
            if name == "asaas_clientes":
                return mock_table_clientes
            return mock_table_messages

        mock_supabase.client.table = table_router

        with patch("app.domain.billing.services.confirmacao_pagamento.UazapiService") as mock_uazapi_class, \
             patch("app.domain.billing.services.confirmacao_pagamento.leadbox_push_silent") as mock_push:

            mock_uazapi_class.return_value = AsyncMock()

            # Act
            result = await enviar_confirmacao_pagamento(
                supabase=mock_supabase,
                agent=agent_data,
                payment=payment_data,
            )

            # Assert
            assert result["success"] is True
            assert result["message_sent"] is False
            assert result["reason"] == "already_sent"
            mock_push.assert_not_called()


# =============================================================================
# CENÁRIO 4: FALHAS
# =============================================================================

class TestFalhas:
    """Testes de resiliência a falhas."""

    @pytest.mark.asyncio
    async def test_uazapi_falha_erro_logado_sem_crash(
        self, payment_data, agent_data, cliente_asaas, mock_supabase
    ):
        """UAZAPI falha → erro logado, webhook retorna 200."""
        # Arrange
        mock_supabase.client.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = cliente_asaas
        mock_supabase.client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []

        with patch("app.domain.billing.services.confirmacao_pagamento.UazapiService") as mock_uazapi_class, \
             patch("app.domain.billing.services.confirmacao_pagamento.leadbox_push_silent") as mock_push:

            mock_push.return_value = {"success": False, "ticket_check_failed": True}
            mock_uazapi_instance = AsyncMock()
            mock_uazapi_instance.send_text_message = AsyncMock(return_value={"success": False, "error": "Connection timeout"})
            mock_uazapi_class.return_value = mock_uazapi_instance

            # Act - NÃO deve lançar exceção
            result = await enviar_confirmacao_pagamento(
                supabase=mock_supabase,
                agent=agent_data,
                payment=payment_data,
            )

            # Assert
            assert result["success"] is False
            assert result["message_sent"] is False
            assert "error" in result

    @pytest.mark.asyncio
    async def test_cliente_sem_telefone_skip_silencioso(
        self, payment_data, agent_data, mock_supabase
    ):
        """Cliente sem telefone cadastrado → skip silencioso com log."""
        # Arrange
        cliente_sem_telefone = {"id": "cus_xyz789", "name": "Maria", "mobile_phone": None, "phone": None}

        mock_table = MagicMock()
        mock_table.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = cliente_sem_telefone
        mock_table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
        mock_supabase.client.table.return_value = mock_table

        with patch("app.domain.billing.services.confirmacao_pagamento.UazapiService") as mock_uazapi_class, \
             patch("app.domain.billing.services.confirmacao_pagamento.leadbox_push_silent") as mock_push:

            # Act - NÃO deve lançar exceção
            result = await enviar_confirmacao_pagamento(
                supabase=mock_supabase,
                agent=agent_data,
                payment=payment_data,
            )

            # Assert
            assert result["success"] is False
            assert result["message_sent"] is False
            assert result["reason"] == "no_phone"
            mock_push.assert_not_called()

    @pytest.mark.asyncio
    async def test_leadbox_push_usa_uazapi_fallback(
        self, payment_data, agent_data, cliente_asaas, mock_supabase
    ):
        """Se Leadbox push falha, usa UAZAPI como fallback."""
        # Arrange
        lead = {"id": "lead_123", "remotejid": "5566998887777@s.whatsapp.net", "conversation_history": {"messages": []}}

        mock_table_clientes = MagicMock()
        mock_table_clientes.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = cliente_asaas

        mock_table_messages = MagicMock()
        mock_table_messages.select.return_value.or_.return_value.limit.return_value.execute.return_value.data = [lead]
        mock_table_messages.update.return_value.eq.return_value.execute.return_value.data = lead

        def table_router(name):
            if name == "asaas_clientes":
                return mock_table_clientes
            return mock_table_messages

        mock_supabase.client.table = table_router

        with patch("app.domain.billing.services.confirmacao_pagamento.UazapiService") as mock_uazapi_class, \
             patch("app.domain.billing.services.confirmacao_pagamento.leadbox_push_silent") as mock_push:

            # Leadbox falha
            mock_push.return_value = {"success": False, "ticket_check_failed": True}

            # UAZAPI funciona
            mock_uazapi_instance = AsyncMock()
            mock_uazapi_instance.send_text_message = AsyncMock(return_value={"success": True})
            mock_uazapi_class.return_value = mock_uazapi_instance

            # Act
            result = await enviar_confirmacao_pagamento(
                supabase=mock_supabase,
                agent=agent_data,
                payment=payment_data,
            )

            # Assert
            assert result["success"] is True
            assert result["message_sent"] is True
            mock_push.assert_called_once()  # Tentou Leadbox
            mock_uazapi_instance.send_text_message.assert_called_once()  # Fallback UAZAPI
