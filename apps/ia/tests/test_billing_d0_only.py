# tests/test_billing_d0_only.py

"""
TDD — Billing apenas D0 (2026-03-20)

Contexto: Mudança de régua - cobrar apenas no vencimento
Causa: Régua atual envia D-2, D-1, D0, D+1 a D+15
Correção: Alterar defaults para enviar apenas D0
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import date


class TestBillingD0OnlyDefaults:
    """
    Testa que os defaults de cobrança são apenas D0.

    Cenário: Agente SEM configuração explícita de autoCollection.
    Esperado: Não envia lembretes (D-2, D-1) nem cobranças após vencimento (D+1 a D+15).
    """

    @pytest.mark.asyncio
    async def test_reminder_days_default_is_empty_list(self):
        """
        Fallback de reminderDays deve ser lista vazia.

        ANTES: config.get("reminderDays") or [2, 1]  ← ERRADO
        DEPOIS: config.get("reminderDays") or []     ← CORRETO
        """
        from app.billing.agent_processor import process_agent

        # Agente sem configuração de autoCollection
        agent = {
            "id": "test-agent-id",
            "name": "TestAgent",
            "asaas_config": {},  # Vazio - usa defaults
            "asaas_api_key": "test_key",
        }

        # Mock das dependências
        with patch("app.billing.agent_processor.collect_payments") as mock_collect:
            # Configura mock para retornar vazio (não importa o resultado)
            mock_collect.return_value = MagicMock(
                degraded=False,
                payments=[]
            )

            await process_agent(agent, date(2026, 3, 20))

            # Se reminderDays default é [], collect_payments NÃO deve ser chamado
            # para datas futuras (fase 1 - lembretes)
            #
            # Verificar que NÃO foi chamado com status PENDING para datas != today
            calls = mock_collect.call_args_list

            pending_calls = [
                c for c in calls
                if c[0][1] == "PENDING" and c[0][2] != date(2026, 3, 20)
            ]

            assert len(pending_calls) == 0, (
                f"Fase 1 (lembretes) não deveria ser executada com reminderDays=[]. "
                f"Chamadas encontradas para datas futuras: {pending_calls}"
            )

    @pytest.mark.asyncio
    async def test_after_due_enabled_default_is_false(self):
        """
        Fallback de afterDue.enabled deve ser False.

        ANTES: after_due_config.get("enabled", True)   ← ERRADO
        DEPOIS: after_due_config.get("enabled", False) ← CORRETO
        """
        from app.billing.agent_processor import process_agent

        agent = {
            "id": "test-agent-id",
            "name": "TestAgent",
            "asaas_config": {},
            "asaas_api_key": "test_key",
        }

        with patch("app.billing.agent_processor.collect_payments") as mock_collect:
            mock_collect.return_value = MagicMock(
                degraded=False,
                payments=[]
            )

            await process_agent(agent, date(2026, 3, 20))

            # Se afterDue.enabled default é False, collect_payments NÃO deve
            # ser chamado com status OVERDUE (fase 3)
            calls = mock_collect.call_args_list

            overdue_calls = [c for c in calls if c[0][1] == "OVERDUE"]

            assert len(overdue_calls) == 0, (
                f"Fase 3 (overdue) não deveria ser executada com afterDue.enabled=False. "
                f"Chamadas OVERDUE encontradas: {overdue_calls}"
            )

    @pytest.mark.asyncio
    async def test_on_due_date_default_remains_true(self):
        """
        D0 (vencimento) continua habilitado por padrão.

        Esperado: onDueDate default permanece True.
        """
        from app.billing.agent_processor import process_agent

        agent = {
            "id": "test-agent-id",
            "name": "TestAgent",
            "asaas_config": {},
            "asaas_api_key": "test_key",
        }

        with patch("app.billing.agent_processor.collect_payments") as mock_collect:
            mock_collect.return_value = MagicMock(
                degraded=False,
                payments=[]
            )

            await process_agent(agent, date(2026, 3, 20))

            # Fase 2 (D0) DEVE ser executada - collect_payments com PENDING e today
            calls = mock_collect.call_args_list

            d0_calls = [
                c for c in calls
                if c[0][1] == "PENDING" and c[0][2] == date(2026, 3, 20)
            ]

            assert len(d0_calls) == 1, (
                f"Fase 2 (D0) deveria ser executada com onDueDate=True. "
                f"Chamadas D0 encontradas: {len(d0_calls)}"
            )

    @pytest.mark.asyncio
    async def test_only_d0_phase_executes_with_empty_config(self):
        """
        Com config vazia, apenas a fase D0 deve executar.

        Esperado:
        - Fase 1 (lembretes): NÃO executa
        - Fase 2 (D0): EXECUTA
        - Fase 3 (overdue): NÃO executa
        """
        from app.billing.agent_processor import process_agent

        agent = {
            "id": "test-agent-id",
            "name": "TestAgent",
            "asaas_config": {},
            "asaas_api_key": "test_key",
        }

        with patch("app.billing.agent_processor.collect_payments") as mock_collect:
            mock_collect.return_value = MagicMock(
                degraded=False,
                payments=[]
            )

            await process_agent(agent, date(2026, 3, 20))

            # Deve ter APENAS 1 chamada: PENDING para today (fase 2)
            assert mock_collect.call_count == 1, (
                f"Deveria ter apenas 1 chamada (fase D0). "
                f"Total de chamadas: {mock_collect.call_count}"
            )

            # E essa chamada deve ser PENDING para today
            call_args = mock_collect.call_args[0]
            assert call_args[1] == "PENDING", f"Status deveria ser PENDING, foi {call_args[1]}"
            assert call_args[2] == date(2026, 3, 20), f"Data deveria ser today"
