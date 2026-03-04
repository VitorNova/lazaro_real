"""
Business Days Utility - Calculo de dias uteis considerando feriados brasileiros.

Portado de agnes-agent/src/utils/business-days.ts
"""

from datetime import date, datetime, timedelta
from typing import List

import pytz

# Timezone de Brasilia
TZ_BRASILIA = pytz.timezone("America/Sao_Paulo")

# Feriados nacionais fixos do Brasil (mes, dia)
FIXED_HOLIDAYS = [
    (1, 1),    # Confraternizacao Universal
    (4, 21),   # Tiradentes
    (5, 1),    # Dia do Trabalho
    (9, 7),    # Independencia do Brasil
    (10, 12),  # Nossa Senhora Aparecida
    (11, 2),   # Finados
    (11, 15),  # Proclamacao da Republica
    (12, 25),  # Natal
]


def get_easter_date(year: int) -> date:
    """Calcula a data da Pascoa usando o algoritmo de Meeus/Jones/Butcher."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def get_mobile_holidays(year: int) -> List[date]:
    """Retorna feriados moveis baseados na Pascoa."""
    easter = get_easter_date(year)
    holidays = []

    # Carnaval (segunda e terca antes da Quarta de Cinzas)
    carnival_monday = easter - timedelta(days=48)
    carnival_tuesday = easter - timedelta(days=47)
    holidays.extend([carnival_monday, carnival_tuesday])

    # Sexta-feira Santa (2 dias antes da Pascoa)
    good_friday = easter - timedelta(days=2)
    holidays.append(good_friday)

    # Corpus Christi (60 dias apos a Pascoa)
    corpus_christi = easter + timedelta(days=60)
    holidays.append(corpus_christi)

    return holidays


def get_holidays_for_year(year: int) -> List[date]:
    """Retorna todos os feriados de um ano especifico."""
    holidays = []

    # Feriados fixos
    for month, day in FIXED_HOLIDAYS:
        holidays.append(date(year, month, day))

    # Feriados moveis
    holidays.extend(get_mobile_holidays(year))

    return holidays


def is_holiday(d: date) -> bool:
    """Verifica se uma data e feriado."""
    holidays = get_holidays_for_year(d.year)
    return d in holidays


def is_weekend(d: date) -> bool:
    """Verifica se uma data e fim de semana (sabado ou domingo)."""
    return d.weekday() in (5, 6)  # 5=sabado, 6=domingo


def is_business_day(d: date) -> bool:
    """Verifica se uma data e dia util (nao e fim de semana nem feriado)."""
    return not is_weekend(d) and not is_holiday(d)


def add_business_days(d: date, days: int) -> date:
    """Adiciona N dias uteis a uma data."""
    result = d
    remaining = abs(days)
    direction = 1 if days >= 0 else -1

    while remaining > 0:
        result += timedelta(days=direction)
        if is_business_day(result):
            remaining -= 1

    return result


def subtract_business_days(d: date, days: int) -> date:
    """Subtrai N dias uteis de uma data."""
    return add_business_days(d, -days)


def anticipate_to_friday(d: date) -> date:
    """
    Antecipa data para sexta-feira se cair em fim de semana ou feriado.
    Usado para enviar notificacoes antes do vencimento quando este cai no final de semana.
    """
    result = d
    while not is_business_day(result):
        result -= timedelta(days=1)
    return result


def get_today_brasilia() -> date:
    """Retorna hoje no fuso horario de Brasilia (GMT-3)."""
    now = datetime.now(TZ_BRASILIA)
    return now.date()


def get_now_brasilia() -> datetime:
    """Retorna agora no fuso horario de Brasilia."""
    return datetime.now(TZ_BRASILIA)


def format_date(d: date) -> str:
    """Formata data no padrao YYYY-MM-DD."""
    return d.strftime("%Y-%m-%d")


def format_date_br(d: date) -> str:
    """Formata data no padrao DD/MM/YYYY."""
    return d.strftime("%d/%m/%Y")


def parse_date(date_str: str) -> date:
    """Parse de data no formato YYYY-MM-DD."""
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def is_business_hours(hour_start: int = 8, hour_end: int = 20) -> bool:
    """Verifica se estamos em horario comercial (Brasilia)."""
    now = get_now_brasilia()
    return hour_start <= now.hour < hour_end


def count_business_days(from_date: date, to_date: date) -> int:
    """
    Conta dias uteis entre duas datas.
    Retorna positivo se to_date > from_date, negativo se to_date < from_date.
    """
    if from_date == to_date:
        return 0

    if to_date > from_date:
        direction = 1
        start, end = from_date, to_date
    else:
        direction = -1
        start, end = to_date, from_date

    count = 0
    current = start
    while current < end:
        current += timedelta(days=1)
        if is_business_day(current):
            count += 1

    return count * direction
