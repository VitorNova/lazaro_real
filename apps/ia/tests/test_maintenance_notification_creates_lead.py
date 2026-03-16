# tests/test_maintenance_notification_creates_lead.py

"""
TDD - Bug: Job de manutencao nao cria registro quando lead nao existe [2026-03-16]

Contexto: Job D-7 de manutencao envia mensagem mas nao salva contexto quando
          o lead nao existe na tabela leadbox_messages_*.
Causa: mark_notification_sent usa find_message_record_by_phone que apenas busca.
       Se nao encontra, loga warning e nao cria o registro.
Correcao: Criar registro na tabela de mensagens se nao existir, com:
          1. Mensagem fake "ola" role="user" (regra Gemini)
          2. Mensagem de manutencao role="model" com context e contract_id
"""

import pytest
from datetime import date
from unittest.mock import MagicMock, patch


# ─── Helpers de Mock (padrao CLAUDE.md) ─────────────────────────────────────

def make_supabase_mock(table_data: dict) -> MagicMock:
    """
    Cria mock do Supabase seguindo padrao CLAUDE.md.

    Args:
        table_data: Dict com nome_tabela -> lista de registros
                    Ex: {"leadbox_messages_Ana": [{"id": "1", "remotejid": "55..."}]}

    Returns:
        Mock configurado com side_effect para cada tabela.
        Permite capturar chamadas insert/update para assertions.
    """
    mock = MagicMock()

    # Armazena chamadas para verificacao posterior
    mock._insert_calls = {}
    mock._update_calls = {}

    def table_side_effect(table_name):
        t = MagicMock()
        t._table_name = table_name
        data = table_data.get(table_name, [])
        resp = MagicMock()
        resp.data = data

        # SELECT chains
        t.select.return_value.eq.return_value.eq.return_value \
         .limit.return_value.execute.return_value = resp
        t.select.return_value.eq.return_value \
         .limit.return_value.execute.return_value = resp
        t.select.return_value.or_.return_value \
         .limit.return_value.execute.return_value = resp
        t.select.return_value.execute.return_value = resp

        # INSERT - captura argumentos
        def capture_insert(insert_data):
            if table_name not in mock._insert_calls:
                mock._insert_calls[table_name] = []
            mock._insert_calls[table_name].append(insert_data)
            insert_result = MagicMock()
            insert_result.execute.return_value = MagicMock(data=[{"id": "new-id"}])
            return insert_result

        t.insert.side_effect = capture_insert

        # UPDATE - captura argumentos
        def capture_update(update_data):
            if table_name not in mock._update_calls:
                mock._update_calls[table_name] = []
            mock._update_calls[table_name].append(update_data)
            update_chain = MagicMock()
            update_chain.eq.return_value.execute.return_value = MagicMock(data=[{"id": "updated-id"}])
            return update_chain

        t.update.side_effect = capture_update

        return t

    mock.client.table.side_effect = table_side_effect
    return mock


# ─── Classe de Teste ─────────────────────────────────────────────────────────

class TestMarkNotificationSentCreatesLead:
    """
    TDD - Job de manutencao deve criar registro quando lead nao existe [2026-03-16]

    Contexto: Lead 556596101787 (MARIA JOSE DE MORAES RAMALHO) recebeu mensagem
              de manutencao D-7, mas o contexto nao foi salvo porque o lead
              nao existia na tabela leadbox_messages_Ana_14e6e5ce.
    Causa: mark_notification_sent usa find_message_record_by_phone que apenas
           busca. Se nao encontra, loga warning e nao cria o registro.
    Correcao: Se lead nao existe, criar registro com mensagem fake "ola"
              role="user" + mensagem de manutencao role="model" com context.

    Log original do bug:
    [WARNING] [MAINTENANCE] Lead nao encontrado para 55659961*** |
              customer_id=cus_000161829730 | contexto NAO salvo
    """

    @pytest.mark.asyncio
    async def test_cria_registro_quando_lead_nao_existe(self):
        """
        Quando o lead NAO existe na tabela de mensagens,
        deve criar novo registro com INSERT contendo:
        - Mensagem fake "ola" role="user" (regra Gemini)
        - Mensagem de manutencao role="model" com context e contract_id
        """
        # Arrange - tabela vazia (lead nao existe)
        mock_supabase = make_supabase_mock({
            "leadbox_messages_Ana_14e6e5ce": []  # vazio = lead nao existe
        })

        with patch(
            "app.domain.maintenance.services.notification_service.get_supabase_service",
            return_value=mock_supabase
        ), patch(
            "app.domain.maintenance.services.notification_service.find_message_record_by_phone",
            return_value=None  # Simula lead nao encontrado
        ):
            from app.domain.maintenance.services.notification_service import (
                mark_notification_sent,
            )

            # Act
            await mark_notification_sent(
                contract_id="0db9b1e8-f265-4b72-a747-9ddd1d907570",
                proxima_manutencao=date(2026, 3, 23),
                customer_phone="5565996101787",
                message_sent="Ola MARIA! Aqui e a ANA da Alugar Ar...",
                table_messages="leadbox_messages_Ana_14e6e5ce",
                customer_id="cus_000161829730",
            )

        # Assert - Deve ter chamado INSERT
        insert_calls = mock_supabase._insert_calls.get("leadbox_messages_Ana_14e6e5ce", [])
        assert len(insert_calls) == 1, "Deveria ter chamado INSERT uma vez"

        insert_data = insert_calls[0]
        assert "remotejid" in insert_data
        assert "conversation_history" in insert_data

        # Verificar estrutura do conversation_history
        history = insert_data["conversation_history"]
        messages = history.get("messages", [])
        assert len(messages) == 2, f"Esperado 2 mensagens, encontrado {len(messages)}"

        # Primeira mensagem: user fake "ola"
        assert messages[0]["role"] == "user"
        assert messages[0]["parts"][0]["text"] == "ola"
        assert messages[0].get("context") == "manutencao_preventiva"

        # Segunda mensagem: model com contexto
        assert messages[1]["role"] == "model"
        assert messages[1].get("context") == "manutencao_preventiva"
        assert messages[1].get("contract_id") == "0db9b1e8-f265-4b72-a747-9ddd1d907570"

    @pytest.mark.asyncio
    async def test_adiciona_ao_historico_quando_lead_existe(self):
        """
        Quando o lead JA existe na tabela de mensagens,
        deve adicionar a mensagem de manutencao ao historico existente via UPDATE.
        """
        # Arrange - Lead existe com historico
        existing_record = {
            "id": "existing-record-id",
            "remotejid": "556596101787@s.whatsapp.net",
            "conversation_history": {
                "messages": [
                    {"role": "user", "parts": [{"text": "oi"}], "timestamp": "2026-03-10T10:00:00Z"},
                    {"role": "model", "parts": [{"text": "Ola!"}], "timestamp": "2026-03-10T10:00:01Z"},
                ]
            }
        }

        mock_supabase = make_supabase_mock({
            "leadbox_messages_Ana_14e6e5ce": [existing_record]
        })

        with patch(
            "app.domain.maintenance.services.notification_service.get_supabase_service",
            return_value=mock_supabase
        ), patch(
            "app.domain.maintenance.services.notification_service.find_message_record_by_phone",
            return_value=existing_record  # Lead existe
        ):
            from app.domain.maintenance.services.notification_service import (
                mark_notification_sent,
            )

            # Act
            await mark_notification_sent(
                contract_id="0db9b1e8-test-contract",
                proxima_manutencao=date(2026, 3, 23),
                customer_phone="556596101787",
                message_sent="Ola! Manutencao preventiva...",
                table_messages="leadbox_messages_Ana_14e6e5ce",
                customer_id="cus_test",
            )

        # Assert - Deve ter chamado UPDATE (nao INSERT)
        update_calls = mock_supabase._update_calls.get("leadbox_messages_Ana_14e6e5ce", [])
        assert len(update_calls) == 1, "Deveria ter chamado UPDATE uma vez"

        update_data = update_calls[0]
        history = update_data.get("conversation_history", {})
        messages = history.get("messages", [])

        # Deve ter 3 mensagens: 2 existentes + 1 nova
        assert len(messages) == 3, f"Esperado 3 mensagens, encontrado {len(messages)}"

        # Nova mensagem deve ter context e contract_id
        new_msg = messages[-1]
        assert new_msg["role"] == "model"
        assert new_msg.get("context") == "manutencao_preventiva"
        assert new_msg.get("contract_id") == "0db9b1e8-test-contract"

    @pytest.mark.asyncio
    async def test_preserva_mensagens_existentes_ao_adicionar(self):
        """
        Ao adicionar mensagem de manutencao, deve preservar todas as
        mensagens existentes no historico.
        """
        # Arrange - Lead existe com 5 mensagens
        existing_messages = [
            {"role": "user", "parts": [{"text": "msg1"}], "timestamp": "2026-03-01T10:00:00Z"},
            {"role": "model", "parts": [{"text": "msg2"}], "timestamp": "2026-03-01T10:00:01Z"},
            {"role": "user", "parts": [{"text": "msg3"}], "timestamp": "2026-03-02T10:00:00Z"},
            {"role": "model", "parts": [{"text": "msg4"}], "timestamp": "2026-03-02T10:00:01Z"},
            {"role": "user", "parts": [{"text": "msg5"}], "timestamp": "2026-03-03T10:00:00Z"},
        ]

        existing_record = {
            "id": "record-with-5-msgs",
            "remotejid": "556596101787@s.whatsapp.net",
            "conversation_history": {"messages": existing_messages.copy()}
        }

        mock_supabase = make_supabase_mock({
            "leadbox_messages_Ana_14e6e5ce": [existing_record]
        })

        with patch(
            "app.domain.maintenance.services.notification_service.get_supabase_service",
            return_value=mock_supabase
        ), patch(
            "app.domain.maintenance.services.notification_service.find_message_record_by_phone",
            return_value=existing_record
        ):
            from app.domain.maintenance.services.notification_service import (
                mark_notification_sent,
            )

            # Act
            await mark_notification_sent(
                contract_id="contract-123",
                proxima_manutencao=date(2026, 3, 23),
                customer_phone="556596101787",
                message_sent="Manutencao preventiva...",
                table_messages="leadbox_messages_Ana_14e6e5ce",
                customer_id="cus_test",
            )

        # Assert
        update_calls = mock_supabase._update_calls.get("leadbox_messages_Ana_14e6e5ce", [])
        update_data = update_calls[0]
        history = update_data.get("conversation_history", {})
        messages = history.get("messages", [])

        # Deve ter 6 mensagens: 5 existentes + 1 nova
        assert len(messages) == 6, f"Esperado 6 mensagens, encontrado {len(messages)}"

        # Primeiras 5 devem ser as originais (preservadas)
        for i in range(5):
            assert messages[i]["parts"][0]["text"] == f"msg{i+1}"

        # Ultima deve ser a nova com context
        assert messages[5].get("context") == "manutencao_preventiva"
        assert messages[5].get("contract_id") == "contract-123"
