"""
TDD — Confirmação de pagamento não encontra lead por mismatch de telefone (2026-03-24)

Contexto: 45% dos clientes que pagaram não receberam mensagem de confirmação.
Causa: payment_message_service usa .eq() exato no remotejid, mas Asaas e Leadbox
       guardam telefone em formatos diferentes (com/sem nono dígito).
Correção: Usar generate_phone_variants() + .or_() como lead_ensurer.py já faz.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock

# Módulo sob teste
from app.domain.billing.services.confirmacao_pagamento import (
    salvar_no_historico,
    ja_enviou_confirmacao,
)


def _make_supabase_mock(table_data: dict, remotejid_key: str = None):
    """
    Mock do Supabase que responde a .or_() e .eq() em remotejid.

    Se remotejid_key for fornecido, só retorna dados quando a query
    contiver esse valor (simulando o lead existir com esse JID).
    """
    mock = MagicMock()

    def table_side_effect(table_name):
        t = MagicMock()
        data = table_data.get(table_name, [])
        resp = MagicMock()
        resp.data = data

        # .select().or_().limit().execute() — query com variantes
        t.select.return_value.or_.return_value.limit.return_value.execute.return_value = resp

        # .select().eq().limit().execute() — query exata (comportamento atual bugado)
        # Só retorna dados se o eq matcher bater com remotejid_key
        def eq_side_effect(field, value):
            eq_result = MagicMock()
            if field == "remotejid" and remotejid_key and value != remotejid_key:
                # Mismatch: busca exata não encontra o lead
                empty_resp = MagicMock()
                empty_resp.data = []
                eq_result.limit.return_value.execute.return_value = empty_resp
            else:
                eq_result.limit.return_value.execute.return_value = resp
            return eq_result

        t.select.return_value.eq.side_effect = eq_side_effect

        # .update().eq().execute()
        t.update.return_value.eq.return_value.execute.return_value = MagicMock()

        return t

    mock.client.table.side_effect = table_side_effect
    return mock


class TestSalvarNoHistoricoPhoneVariants:
    """
    Testa que salvar_no_historico() encontra o lead mesmo quando
    o telefone do Asaas difere do Leadbox (com/sem nono dígito).
    """

    @pytest.mark.asyncio
    async def test_encontra_lead_com_nono_digito_diferente(self):
        """
        Asaas tem 5566991337555 (13 dígitos, com 9 extra).
        Leadbox tem 556699133755 (12 dígitos, sem 9 extra).
        Deve encontrar o lead e salvar a mensagem.
        """
        phone_asaas = "5566991337555"
        phone_leadbox_jid = "556699133755@s.whatsapp.net"

        lead_data = [{
            "id": 123,
            "conversation_history": {"messages": []},
        }]

        mock = _make_supabase_mock(
            {"leadbox_messages_Ana_14e6e5ce": lead_data},
            remotejid_key=phone_leadbox_jid,  # Lead existe com esse JID
        )

        result = await salvar_no_historico(
            supabase=mock,
            table_messages="leadbox_messages_Ana_14e6e5ce",
            phone=phone_asaas,
            mensagem="Confirmamos o recebimento!",
            payment_id="pay_abc123",
        )

        assert result is True, (
            "salvar_no_historico deveria encontrar o lead via variantes de telefone"
        )

    @pytest.mark.asyncio
    async def test_encontra_lead_sem_nono_digito(self):
        """
        Asaas tem 556697194084 (12 dígitos, sem 9 extra).
        Leadbox tem 5566997194084 (13 dígitos, com 9 extra).
        Deve encontrar o lead.
        """
        phone_asaas = "556697194084"
        phone_leadbox_jid = "5566997194084@s.whatsapp.net"

        lead_data = [{
            "id": 456,
            "conversation_history": {"messages": []},
        }]

        mock = _make_supabase_mock(
            {"leadbox_messages_Ana_14e6e5ce": lead_data},
            remotejid_key=phone_leadbox_jid,
        )

        result = await salvar_no_historico(
            supabase=mock,
            table_messages="leadbox_messages_Ana_14e6e5ce",
            phone=phone_asaas,
            mensagem="Confirmamos o recebimento!",
            payment_id="pay_def456",
        )

        assert result is True


class TestJaEnviouConfirmacaoPhoneVariants:
    """
    Testa que ja_enviou_confirmacao() encontra o lead com variantes.
    """

    @pytest.mark.asyncio
    async def test_detecta_duplicata_com_phone_diferente(self):
        """
        Lead existe com phone Leadbox, mas busca vem com phone Asaas.
        Deve encontrar e detectar que já enviou.
        """
        phone_asaas = "5566991337555"
        phone_leadbox_jid = "556699133755@s.whatsapp.net"

        lead_data = [{
            "id": 789,
            "conversation_history": {
                "messages": [{
                    "role": "model",
                    "context": "pagamento_confirmado",
                    "payment_id": "pay_xyz789",
                    "text": "Confirmamos!",
                }]
            },
        }]

        mock = _make_supabase_mock(
            {"leadbox_messages_Ana_14e6e5ce": lead_data},
            remotejid_key=phone_leadbox_jid,
        )

        result = await ja_enviou_confirmacao(
            supabase=mock,
            table_messages="leadbox_messages_Ana_14e6e5ce",
            phone=phone_asaas,
            payment_id="pay_xyz789",
        )

        assert result is True, (
            "ja_enviou_confirmacao deveria encontrar o lead via variantes"
        )
