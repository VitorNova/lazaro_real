# tests/test_billing_schedule_coverage.py
"""
TDD - Cobertura do Schedule de Cobrança - 2026-03-17

Contexto: Cliente ALESSANDRO não foi cobrado porque D+2 não está no schedule
Causa: DEFAULT_SCHEDULE = [-1, 0, 1, 3, 5, 7, 10, 12, 15] (falta o 2)
Correção: Adicionar D+2 ao schedule
"""

import pytest
from datetime import date


class TestBillingScheduleCoverage:
    """
    Testes para garantir que o schedule de cobrança não tem gaps críticos.
    """

    def test_schedule_includes_d_plus_2(self):
        """D+2 deve estar no schedule para evitar gaps nos primeiros dias."""
        from app.billing.ruler import DEFAULT_SCHEDULE

        assert 2 in DEFAULT_SCHEDULE, (
            f"D+2 não está no schedule! "
            f"Schedule atual: {DEFAULT_SCHEDULE}. "
            f"Clientes com vencimento em D+2 não receberão cobrança."
        )

    def test_schedule_covers_first_five_days(self):
        """Primeiros 5 dias após vencimento devem estar cobertos (D+1 a D+5)."""
        from app.billing.ruler import DEFAULT_SCHEDULE

        first_five = [1, 2, 3, 4, 5]
        covered = [d for d in first_five if d in DEFAULT_SCHEDULE]

        # Pelo menos 4 dos 5 primeiros dias devem estar cobertos
        assert len(covered) >= 4, (
            f"Schedule cobre apenas {covered} dos primeiros 5 dias. "
            f"Mínimo esperado: 4 dias cobertos."
        )

    def test_should_send_on_d_plus_2(self):
        """Vencimento no sábado, cobrança na terça (D+2) deve enviar."""
        from app.billing.ruler import evaluate

        # Caso real: vencimento sábado 14/03, hoje terça 17/03
        due_date = date(2026, 3, 14)
        today = date(2026, 3, 17)

        decision = evaluate(today, due_date)

        assert decision.should_send is True, (
            f"Cobrança D+2 deveria enviar! "
            f"Offset: {decision.offset}, should_send: {decision.should_send}"
        )
        assert decision.offset == 2, f"Offset esperado 2, obtido {decision.offset}"
        assert decision.phase == "overdue", f"Fase esperada 'overdue', obtida '{decision.phase}'"

    def test_schedule_has_reminder_before_due(self):
        """Schedule deve ter D-1 para lembrete antes do vencimento."""
        from app.billing.ruler import DEFAULT_SCHEDULE

        assert -1 in DEFAULT_SCHEDULE, "D-1 deve estar no schedule para lembretes"

    def test_schedule_has_due_date(self):
        """Schedule deve ter D0 para cobrança no vencimento."""
        from app.billing.ruler import DEFAULT_SCHEDULE

        assert 0 in DEFAULT_SCHEDULE, "D0 deve estar no schedule"
