"""Regua de cobranca - decide quando e qual template usar."""
from datetime import date
from typing import List, Optional

from app.billing.models import RulerDecision
from app.core.utils.dias_uteis import count_business_days

DEFAULT_SCHEDULE = [-1, 0, 1, 2, 3, 5, 7, 10, 12, 15]


def calculate_offset(today: date, due_date: date) -> int:
    """
    Calcula offset em dias UTEIS (nao corridos).

    - Negativo = antes do vencimento (D-1, D-2)
    - Zero = dia do vencimento (D0)
    - Positivo = apos vencimento (D+1, D+3...)

    BUG FIX #2: Venceu sexta -> D+1 e segunda, nao sabado.
    """
    return count_business_days(due_date, today)


def determine_phase(offset: int) -> str:
    """Determina fase: 'reminder', 'due_date', 'overdue'."""
    if offset < 0:
        return "reminder"
    elif offset == 0:
        return "due_date"
    return "overdue"


def should_send_today(offset: int, schedule: Optional[List[int]] = None) -> bool:
    """Verifica se deve enviar hoje baseado no schedule."""
    if schedule is None:
        schedule = DEFAULT_SCHEDULE
    return offset in schedule


def select_template_key(offset: int, phase: str) -> str:
    """Seleciona chave do template baseado no offset e fase."""
    if phase == "reminder":
        return "reminder"
    elif phase == "due_date":
        return "dueDate"
    else:
        if offset <= 5:
            return "overdue1"
        elif offset <= 10:
            return "overdue2"
        return "overdue3"


def evaluate(
    today: date,
    due_date: date,
    schedule: Optional[List[int]] = None,
) -> RulerDecision:
    """Avalia se deve enviar e qual template usar."""
    offset = calculate_offset(today, due_date)
    phase = determine_phase(offset)
    should_send = should_send_today(offset, schedule)
    template_key = select_template_key(offset, phase) if should_send else ""

    return RulerDecision(
        should_send=should_send,
        offset=offset,
        template_key=template_key,
        phase=phase,
    )
