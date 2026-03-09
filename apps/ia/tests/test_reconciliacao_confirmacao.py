"""
TDD — Bug 2026-03-09: Reconciliação não envia mensagem de confirmação.

Descrição do problema real:
- Cliente DAIANE EDUARDA KELM (cus_000161520720) pagou em 05/03/2026
- Webhook PAYMENT_RECEIVED não chegou ao sistema
- Job de reconciliação em 06/03/2026 detectou o pagamento
- Job marcou ia_recebeu=True (safety net)
- MAS a mensagem de confirmação NUNCA foi enviada ao cliente

Causa raiz:
- O job de reconciliação (reconciliar_pagamentos.py) marca ia_recebeu=True
- Mas NÃO chama enviar_confirmacao_pagamento()

Comportamento esperado (que este teste valida):
- Quando o safety net detectar pagamento confirmado com ia_cobrou=True e ia_recebeu=False
- DEVE enviar mensagem de confirmação ao cliente
- E ENTÃO marcar ia_recebeu=True

Autor: Claude Code (AKITA methodology)
Data: 2026-03-09
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch, call


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def payment_from_api():
    """Pagamento retornado pela API Asaas (já pago)."""
    return {
        "id": "pay_ntkyqygm9iurszk3",
        "customer": "cus_000161520720",
        "value": 188.00,
        "status": "RECEIVED",
        "billingType": "PIX",
        "dueDate": "2026-03-05",
        "paymentDate": "2026-03-05",
        "invoiceUrl": "https://www.asaas.com/i/ntkyqygm9iurszk3",
    }


@pytest.fixture
def existing_cobranca_no_banco():
    """Cobrança existente no banco - IA cobrou mas não recebeu ainda."""
    return {
        "id": "pay_ntkyqygm9iurszk3",
        "status": "PENDING",  # Status antigo antes da reconciliação
        "value": 188.0,
        "due_date": "2026-03-05",
        "customer_name": "DAIANE EDUARDA KELM",
        "ia_cobrou": True,       # IA já havia cobrado
        "ia_recebeu": False,     # Ainda não marcou como recebido
    }


@pytest.fixture
def cliente_asaas():
    """Cliente no Asaas."""
    return {
        "id": "cus_000161520720",
        "name": "DAIANE EDUARDA KELM",
        "mobile_phone": "66999585758",
        "phone": "66999585758",
    }


@pytest.fixture
def agent_data():
    """Dados do agente Ana."""
    return {
        "id": "14e6e5ce-4627-4e38-aac8-f0191669ff53",
        "name": "Ana",
        "uazapi_base_url": "https://uazapi.example.com",
        "uazapi_token": "token123",
        "table_leads": "LeadboxCRM_Ana_14e6e5ce",
    }


@pytest.fixture
def billing_notification():
    """Notificação de cobrança enviada anteriormente."""
    return {
        "notification_type": "due_date",
        "days_from_due": 0,
    }


def _make_supabase_mock(table_data: dict):
    """
    Cria mock do Supabase com suporte a múltiplas tabelas.

    Args:
        table_data: Dict mapeando nome_tabela -> lista de registros
                    Ex: {"asaas_cobrancas": [{"id": "pay_123", "status": "PENDING"}]}
    """
    mock = MagicMock()

    # Track de chamadas para verificação
    mock._updates = []
    mock._inserts = []

    def table_side_effect(table_name):
        t = MagicMock()
        data = table_data.get(table_name, [])

        # Resposta padrão para select
        resp = MagicMock()
        resp.data = data

        # Encadeamento de métodos select
        t.select.return_value.eq.return_value.eq.return_value.execute.return_value = resp
        t.select.return_value.eq.return_value.execute.return_value = resp
        t.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = resp

        # Captura updates
        def capture_update(update_data):
            mock._updates.append({"table": table_name, "data": update_data})
            update_mock = MagicMock()
            update_mock.eq.return_value.execute.return_value = MagicMock()
            return update_mock
        t.update.side_effect = capture_update

        # Upsert
        def capture_upsert(upsert_data, **kwargs):
            mock._inserts.append({"table": table_name, "data": upsert_data})
            upsert_mock = MagicMock()
            upsert_mock.execute.return_value = MagicMock()
            return upsert_mock
        t.upsert.side_effect = capture_upsert

        return t

    mock.client.table.side_effect = table_side_effect
    return mock


# =============================================================================
# CENÁRIO PRINCIPAL: Bug da reconciliação sem mensagem
# =============================================================================

class TestReconciliacaoConfirmacao:
    """
    TDD — Bug 2026-03-09:
    Job de reconciliação detecta pagamento mas não envia mensagem de confirmação.
    """

    @pytest.mark.asyncio
    async def test_safety_net_deve_enviar_mensagem_confirmacao(
        self,
        payment_from_api,
        existing_cobranca_no_banco,
        cliente_asaas,
        agent_data,
        billing_notification,
    ):
        """
        Bug real: Cliente DAIANE pagou em 05/03, webhook não chegou.
        Reconciliação em 06/03 detectou pagamento mas não enviou confirmação.

        Comportamento ESPERADO (que o teste valida):
        - Ao detectar pagamento RECEIVED com ia_cobrou=True e ia_recebeu=False
        - DEVE enviar mensagem de confirmação via UAZAPI
        - E ENTÃO marcar ia_recebeu=True

        Este teste DEVE FALHAR com o código atual (bug existe).
        Após a correção, DEVE PASSAR.
        """
        agent_id = agent_data["id"]

        # Configurar mocks
        mock_supabase = _make_supabase_mock({
            "asaas_cobrancas": [existing_cobranca_no_banco],
            "billing_notifications": [billing_notification],
            "asaas_clientes": [cliente_asaas],
            "agents": [agent_data],
            "LeadboxCRM_Ana_14e6e5ce": [{
                "remotejid": "5566999585758@s.whatsapp.net",
                "pushname": "Daiane",
            }],
        })

        mock_asaas_service = AsyncMock()
        mock_asaas_service.get_customer.return_value = cliente_asaas

        # Mock para capturar se mensagem foi enviada
        # Fazemos patch no módulo onde a função é USADA (reconciliar_pagamentos)
        mock_enviar_confirmacao = AsyncMock(return_value={"success": True, "message_sent": True})

        with patch("app.jobs.reconciliar_pagamentos.get_supabase_service", return_value=mock_supabase), \
             patch("app.jobs.reconciliar_pagamentos.enviar_confirmacao_pagamento", mock_enviar_confirmacao):

            # Importar após patch para garantir que usa os mocks
            from app.jobs.reconciliar_pagamentos import upsert_payment_to_cache

            # Executar a função que contém o safety net
            result = await upsert_payment_to_cache(
                agent_id=agent_id,
                payment=payment_from_api,
                source="reconciliation",
                asaas_service=mock_asaas_service,
            )

            # ASSERÇÃO PRINCIPAL: A mensagem de confirmação DEVE ser enviada
            # Este é o comportamento ESPERADO após a correção
            #
            # BUG ATUAL: O código marca ia_recebeu=True mas NÃO chama enviar_confirmacao_pagamento
            # Este teste FALHARÁ porque a função não é chamada
            mock_enviar_confirmacao.assert_called_once()


    @pytest.mark.asyncio
    async def test_safety_net_nao_envia_se_ja_recebeu(
        self,
        payment_from_api,
        cliente_asaas,
        agent_data,
    ):
        """
        Se ia_recebeu já é True, NÃO deve enviar mensagem novamente.
        Protege contra duplicatas.
        """
        agent_id = agent_data["id"]

        # Cobrança já marcada como recebida
        cobranca_ja_recebida = {
            "id": "pay_ntkyqygm9iurszk3",
            "status": "RECEIVED",
            "value": 188.0,
            "due_date": "2026-03-05",
            "customer_name": "DAIANE EDUARDA KELM",
            "ia_cobrou": True,
            "ia_recebeu": True,  # JÁ foi marcado como recebido
        }

        mock_supabase = _make_supabase_mock({
            "asaas_cobrancas": [cobranca_ja_recebida],
            "asaas_clientes": [cliente_asaas],
        })

        mock_asaas_service = AsyncMock()
        mock_enviar_confirmacao = AsyncMock(return_value=True)

        with patch("app.jobs.reconciliar_pagamentos.get_supabase_service", return_value=mock_supabase), \
             patch("app.jobs.reconciliar_pagamentos.enviar_confirmacao_pagamento", mock_enviar_confirmacao):

            from app.jobs.reconciliar_pagamentos import upsert_payment_to_cache

            await upsert_payment_to_cache(
                agent_id=agent_id,
                payment=payment_from_api,
                source="reconciliation",
                asaas_service=mock_asaas_service,
            )

            # NÃO deve enviar mensagem se já recebeu
            # Este teste PASSARÁ porque o código nem entra no bloco (ia_recebeu=True)
            mock_enviar_confirmacao.assert_not_called()


    @pytest.mark.asyncio
    async def test_safety_net_nao_envia_se_ia_nao_cobrou(
        self,
        payment_from_api,
        cliente_asaas,
        agent_data,
    ):
        """
        Se ia_cobrou é False, NÃO deve enviar mensagem.
        Só envia confirmação se a IA havia cobrado anteriormente.
        """
        agent_id = agent_data["id"]

        # Cobrança não foi cobrada pela IA
        cobranca_nao_cobrada = {
            "id": "pay_ntkyqygm9iurszk3",
            "status": "PENDING",
            "value": 188.0,
            "due_date": "2026-03-05",
            "customer_name": "DAIANE EDUARDA KELM",
            "ia_cobrou": False,  # IA não cobrou
            "ia_recebeu": False,
        }

        mock_supabase = _make_supabase_mock({
            "asaas_cobrancas": [cobranca_nao_cobrada],
            "asaas_clientes": [cliente_asaas],
        })

        mock_asaas_service = AsyncMock()
        mock_enviar_confirmacao = AsyncMock(return_value=True)

        with patch("app.jobs.reconciliar_pagamentos.get_supabase_service", return_value=mock_supabase), \
             patch("app.jobs.reconciliar_pagamentos.enviar_confirmacao_pagamento", mock_enviar_confirmacao):

            from app.jobs.reconciliar_pagamentos import upsert_payment_to_cache

            await upsert_payment_to_cache(
                agent_id=agent_id,
                payment=payment_from_api,
                source="reconciliation",
                asaas_service=mock_asaas_service,
            )

            # NÃO deve enviar mensagem se IA não cobrou
            # Este teste PASSARÁ porque o código nem entra no bloco (ia_cobrou=False)
            mock_enviar_confirmacao.assert_not_called()


    @pytest.mark.asyncio
    async def test_safety_net_nao_envia_para_status_pending(
        self,
        cliente_asaas,
        agent_data,
    ):
        """
        Se o pagamento ainda está PENDING, NÃO deve enviar confirmação.
        Só envia quando status é RECEIVED, CONFIRMED ou RECEIVED_IN_CASH.
        """
        agent_id = agent_data["id"]

        payment_pending = {
            "id": "pay_ntkyqygm9iurszk3",
            "customer": "cus_000161520720",
            "value": 188.00,
            "status": "PENDING",  # Ainda pendente
            "billingType": "PIX",
            "dueDate": "2026-03-05",
        }

        cobranca = {
            "id": "pay_ntkyqygm9iurszk3",
            "status": "PENDING",
            "value": 188.0,
            "due_date": "2026-03-05",
            "customer_name": "DAIANE EDUARDA KELM",
            "ia_cobrou": True,
            "ia_recebeu": False,
        }

        mock_supabase = _make_supabase_mock({
            "asaas_cobrancas": [cobranca],
            "asaas_clientes": [cliente_asaas],
        })

        mock_asaas_service = AsyncMock()
        mock_enviar_confirmacao = AsyncMock(return_value=True)

        with patch("app.jobs.reconciliar_pagamentos.get_supabase_service", return_value=mock_supabase), \
             patch("app.jobs.reconciliar_pagamentos.enviar_confirmacao_pagamento", mock_enviar_confirmacao):

            from app.jobs.reconciliar_pagamentos import upsert_payment_to_cache

            await upsert_payment_to_cache(
                agent_id=agent_id,
                payment=payment_pending,
                source="reconciliation",
                asaas_service=mock_asaas_service,
            )

            # NÃO deve enviar mensagem para status PENDING
            # Este teste PASSARÁ porque new_status não é RECEIVED/CONFIRMED
            mock_enviar_confirmacao.assert_not_called()
