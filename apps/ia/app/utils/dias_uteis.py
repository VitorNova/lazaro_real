"""
DEPRECATED: Use app.core.utils.dias_uteis instead.

Este modulo e uma ponte de compatibilidade.
Todos os imports sao redirecionados para core/utils/dias_uteis.
"""

from app.core.utils.dias_uteis import (
    # Constants
    TZ_BRASILIA,
    FIXED_HOLIDAYS,
    # Functions
    get_easter_date,
    get_mobile_holidays,
    get_holidays_for_year,
    is_holiday,
    is_weekend,
    is_business_day,
    add_business_days,
    subtract_business_days,
    count_business_days,
    anticipate_to_friday,
    get_today_brasilia,
    get_now_brasilia,
    format_date,
    format_date_br,
    parse_date,
    is_business_hours,
)

__all__ = [
    "TZ_BRASILIA",
    "FIXED_HOLIDAYS",
    "get_easter_date",
    "get_mobile_holidays",
    "get_holidays_for_year",
    "is_holiday",
    "is_weekend",
    "is_business_day",
    "add_business_days",
    "subtract_business_days",
    "count_business_days",
    "anticipate_to_friday",
    "get_today_brasilia",
    "get_now_brasilia",
    "format_date",
    "format_date_br",
    "parse_date",
    "is_business_hours",
]
