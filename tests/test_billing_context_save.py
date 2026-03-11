# tests/test_billing_context_save.py
"""
TDD - Bug RODRIGO BORGES 11/03/2026 - Contexto billing nao salvo

Contexto:
    Job de billing envia mensagem de cobranca mas nao salva contexto no
    conversation_history porque telefone no Asaas (5566996465228) difere
    do Leadbox (556696465228). O "9 extra" causa mismatch na busca.

Causa:
    lead_ensurer.py:ensure_message_record_exists() e
    lead_ensurer.py:save_message_to_conversation_history() fazem busca
    simples por remotejid sem gerar variantes de telefone.

Correcao:
    Usar find_message_record_by_phone() que ja gera variantes e busca com OR.
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock, call
from datetime import datetime


# ─── Helpers de Mock ────────────────────────────────────────────────────────

def make_strict_supabase_mock(table_data: dict, expected_remotejid: str = None) -> MagicMock:
    """
    Cria mock do Supabase que SÓ retorna dados se a busca usar OR query
    ou se o remotejid exato for passado.

    Se expected_remotejid for definido, busca simples com .eq() só retorna
    dados se remotejid == expected_remotejid.
    """
    mock = MagicMock()
    call_log = []

    def table_side_effect(table_name):
        t = MagicMock()
        data = table_data.get(table_name, [])

        # Resposta vazia por padrao
        empty_resp = MagicMock()
        empty_resp.data = []

        # Resposta com dados
        data_resp = MagicMock()
        data_resp.data = data

        def eq_side_effect(field, value):
            call_log.append(("eq", field, value))
            eq_mock = MagicMock()

            # Se busca por remotejid, verificar se e o esperado
            if field == "remotejid" and expected_remotejid:
                if value == expected_remotejid:
                    eq_mock.order.return_value.limit.return_value.execute.return_value = data_resp
                    eq_mock.limit.return_value.execute.return_value = data_resp
                else:
                    # Busca simples com remotejid errado -> retorna vazio
                    eq_mock.order.return_value.limit.return_value.execute.return_value = empty_resp
                    eq_mock.limit.return_value.execute.return_value = empty_resp
            else:
                eq_mock.order.return_value.limit.return_value.execute.return_value = data_resp
                eq_mock.limit.return_value.execute.return_value = data_resp
                eq_mock.execute.return_value = data_resp

            return eq_mock

        def or_side_effect(conditions):
            call_log.append(("or_", conditions))
            or_mock = MagicMock()
            # OR query sempre retorna dados (busca com variantes funciona)
            or_mock.order.return_value.limit.return_value.execute.return_value = data_resp
            or_mock.limit.return_value.execute.return_value = data_resp
            return or_mock

        select_mock = MagicMock()
        select_mock.eq = eq_side_effect
        select_mock.or_ = or_side_effect
        select_mock.execute.return_value = data_resp

        t.select.return_value = select_mock

        # UPDATE
        t.update.return_value.eq.return_value.execute.return_value = MagicMock()

        # INSERT
        t.insert.return_value.execute.return_value = MagicMock(data=[{"id": "new-id"}])

        return t

    mock.client.table.side_effect = table_side_effect
    mock._call_log = call_log
    return mock


# ─── Testes de ensure_message_record_exists ─────────────────────────────────

class TestEnsureMessageRecordExists:
    """
    Testes para ensure_message_record_exists() em lead_ensurer.py.

    A funcao deve encontrar registro de mensagem usando variantes de telefone.
    """

    @pytest.mark.asyncio
    async def test_nao_encontra_com_busca_simples_quando_telefone_diferente(self):
        """
        Bug RODRIGO BORGES: busca simples com .eq() nao encontra registro
        quando telefone tem 9 extra diferente.

        Este teste verifica o comportamento ATUAL (bugado).
        Deve FALHAR após a correcao, entao invertemos a logica.
        """
        from app.domain.billing.services.lead_ensurer import ensure_message_record_exists

        # Lead existe com telefone SEM o 9 extra (556696465228)
        # Mas vamos buscar com telefone COM 9 extra (5566996465228)
        mock_db = make_strict_supabase_mock(
            table_data={
                "leadbox_messages_Ana_14e6e5ce": [{
                    "id": "msg-123",
                    "remotejid": "556696465228@s.whatsapp.net",  # SEM 9
                    "conversation_history": {"messages": []}
                }]
            },
            expected_remotejid="556696465228@s.whatsapp.net"  # Dados so retornam pra esse
        )

        agent = {
            "name": "Ana",
            "table_messages": "leadbox_messages_Ana_14e6e5ce",
            "table_leads": "LeadboxCRM_Ana_14e6e5ce"
        }

        # Buscar com telefone COM o 9 extra (5566996465228)
        # Codigo bugado vai buscar por "5566996465228@s.whatsapp.net"
        # Mock so retorna dados pra "556696465228@s.whatsapp.net"
        # Entao codigo bugado NAO encontra -> cria novo (retorna "new-id")
        # Codigo corrigido USA OR query -> encontra -> retorna "msg-123"
        with patch("app.domain.billing.services.lead_ensurer.get_supabase_service", return_value=mock_db):
            result = await ensure_message_record_exists(
                agent=agent,
                phone="5566996465228",  # COM 9 extra
                lead_id=123,
                payment={"id": "pay-123", "customer_id": "cus-123"}
            )

        # Se codigo esta corrigido, deve encontrar registro existente
        # Se codigo esta bugado, vai criar novo e retornar "new-id"
        assert result == "msg-123", f"Esperado msg-123, obteve {result}. Codigo ainda usa busca simples?"


class TestSaveMessageToConversationHistory:
    """
    Testes para save_message_to_conversation_history() em lead_ensurer.py.
    """

    @pytest.mark.asyncio
    async def test_salva_mensagem_quando_telefone_diferente(self):
        """
        save_message_to_conversation_history deve encontrar lead
        mesmo quando telefone Asaas difere do Leadbox.
        """
        from app.domain.billing.services.lead_ensurer import save_message_to_conversation_history

        # Lead existe com telefone SEM o 9 extra
        mock_db = make_strict_supabase_mock(
            table_data={
                "leadbox_messages_Ana_14e6e5ce": [{
                    "id": "msg-789",
                    "remotejid": "556696465228@s.whatsapp.net",
                    "conversation_history": {"messages": []}
                }],
                "LeadboxCRM_Ana_14e6e5ce": [{
                    "id": 123,
                    "remotejid": "556696465228@s.whatsapp.net"
                }]
            },
            expected_remotejid="556696465228@s.whatsapp.net"
        )

        agent = {
            "name": "Ana",
            "table_messages": "leadbox_messages_Ana_14e6e5ce",
            "table_leads": "LeadboxCRM_Ana_14e6e5ce"
        }

        payment = {
            "id": "pay-123",
            "customer_id": "cus-123",
            "value": 189.0
        }

        # Salvar com telefone COM o 9 extra
        with patch("app.domain.billing.services.lead_ensurer.get_supabase_service", return_value=mock_db):
            # Nao deve lancar excecao - deve encontrar e salvar
            await save_message_to_conversation_history(
                agent=agent,
                phone="5566996465228",  # COM 9 extra
                message="Sua fatura vence amanha",
                notification_type="reminder_d1",
                payment=payment
            )

        # Verificar que OR query foi usada (codigo corrigido)
        # Se codigo bugado, usaria .eq() e nao encontraria
        call_log = mock_db._call_log
        or_calls = [c for c in call_log if c[0] == "or_"]

        assert len(or_calls) > 0, f"Esperado uso de .or_() mas so encontrei: {call_log}"


# ─── Testes de Formato de Contexto ──────────────────────────────────────────

class TestBillingContextFormat:
    """
    Testes para garantir que mensagens salvas tem formato correto.
    """

    def test_contexto_billing_detectavel(self):
        """
        Mensagem salva deve ter context='billing' que detect_conversation_context encontra
        """
        from app.domain.messaging.context.context_detector import detect_conversation_context

        history = {
            "messages": [
                {
                    "role": "model",
                    "parts": [{"text": "Sua fatura vence amanha"}],
                    "timestamp": "2026-03-11T10:00:00.000000",
                    "context": "billing",
                    "reference_id": "pay-123"
                }
            ]
        }

        context, ref_id = detect_conversation_context(history)

        assert context == "billing"
        assert ref_id == "pay-123"
