"""
Billing Formatter Service - Formatacao de mensagens de cobranca.

Extraido de: app/jobs/cobrar_clientes.py (Fase 4.3)

Funcionalidades:
- Formatacao de valores em Real (BRL)
- Formatacao de mensagens com variaveis
- Selecao de templates por dias de atraso
- Templates consolidados (multiplas faturas)
"""

import re
from typing import Any, Dict, Optional

from app.core.utils.dias_uteis import format_date_br, parse_date

from app.domain.billing.models.billing_config import DEFAULT_MESSAGES


def format_brl(value: float) -> str:
    """Formata valor em Real brasileiro (R$ 1.234,56)."""
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_message(
    template: str,
    customer_name: str,
    value: float,
    due_date_str: str,
    *,
    days_overdue: Optional[int] = None,
    days_until_due: Optional[int] = None,
    payment_link: Optional[str] = None,
) -> str:
    """
    Formata mensagem substituindo variaveis.

    Suporta {var} e {{var}} para compatibilidade.

    Variaveis disponiveis:
    - {nome}: Nome do cliente
    - {valor}: Valor formatado em BRL
    - {vencimento}: Data de vencimento formatada
    - {dias_atraso}: Dias de atraso (apenas para overdue)
    - {dias}: Dias ate vencimento (apenas para reminder)
    - {link}: Link de pagamento (removido se nao fornecido)
    """
    formatted_value = format_brl(value)
    formatted_date = format_date_br(parse_date(due_date_str))

    message = template
    # Suporta {variavel} e {{variavel}}
    message = re.sub(r"\{\{?nome\}\}?", customer_name, message, flags=re.IGNORECASE)
    message = re.sub(r"\{\{?valor\}\}?", formatted_value, message, flags=re.IGNORECASE)
    message = re.sub(r"\{\{?vencimento\}\}?", formatted_date, message, flags=re.IGNORECASE)

    if days_overdue is not None:
        message = re.sub(r"\{\{?dias_atraso\}\}?", str(days_overdue), message, flags=re.IGNORECASE)

    if days_until_due is not None:
        message = re.sub(r"\{\{?dias\}\}?", str(days_until_due), message, flags=re.IGNORECASE)

    if payment_link:
        message = re.sub(r"\{\{?link\}\}?", payment_link, message, flags=re.IGNORECASE)
    else:
        message = re.sub(r"\s*\{\{?link\}\}?", "", message, flags=re.IGNORECASE)

    return message


def format_consolidated_message(
    template: str,
    customer_name: str,
    total_value: float,
    payment_count: int,
    max_days_overdue: int,
    payment_link: Optional[str] = None,
) -> str:
    """
    Formata mensagem consolidada (multiplas faturas do mesmo cliente).

    Variaveis disponiveis:
    - {nome}: Nome do cliente
    - {total}: Valor total formatado em BRL
    - {qtd}: Quantidade de faturas
    - {dias_atraso}: Maior numero de dias de atraso
    - {link}: Link de pagamento (removido se nao fornecido)
    """
    formatted_total = format_brl(total_value)

    message = template
    message = re.sub(r"\{\{?nome\}\}?", customer_name, message, flags=re.IGNORECASE)
    message = re.sub(r"\{\{?total\}\}?", formatted_total, message, flags=re.IGNORECASE)
    message = re.sub(r"\{\{?qtd\}\}?", str(payment_count), message, flags=re.IGNORECASE)
    message = re.sub(r"\{\{?dias_atraso\}\}?", str(max_days_overdue), message, flags=re.IGNORECASE)

    if payment_link:
        message = re.sub(r"\{\{?link\}\}?", payment_link, message, flags=re.IGNORECASE)
    else:
        message = re.sub(r"\s*\{\{?link\}\}?", "", message, flags=re.IGNORECASE)

    return message


def get_overdue_template(days_overdue: int, messages: Dict[str, Any]) -> str:
    """
    Seleciona template de cobranca baseado nos dias de atraso.

    Prioridade:
    1. Template especifico do dia (overdueDia1, overdueDia2...)
    2. Template por faixa:
       - D+1 a D+5: overdueTemplate1 (gentil)
       - D+6 a D+10: overdueTemplate2 (firme)
       - D+11 a D+15: overdueTemplate3 (urgente)
    3. DEFAULT_MESSAGES como fallback final
    """
    # Tenta template especifico do dia (ex: overdueDia1, overdueDia2...)
    specific_key = f"overdueDia{days_overdue}"
    if specific_key in messages:
        return messages[specific_key]

    # Fallback para templates por faixa
    if days_overdue <= 5:
        return messages.get("overdueTemplate1") or DEFAULT_MESSAGES["overdue1"]
    elif days_overdue <= 10:
        return messages.get("overdueTemplate2") or DEFAULT_MESSAGES["overdue2"]
    else:
        return messages.get("overdueTemplate3") or DEFAULT_MESSAGES["overdue3"]


def get_consolidated_overdue_template(max_days_overdue: int, messages: Dict[str, Any]) -> str:
    """
    Seleciona template consolidado baseado nos dias de atraso.

    Prioridade:
    1. Template consolidado especifico (overdueConsolidatedDia1...)
    2. Template por faixa:
       - D+1 a D+5: overdueConsolidatedTemplate1
       - D+6 a D+10: overdueConsolidatedTemplate2
       - D+11 a D+15: overdueConsolidatedTemplate3
    3. DEFAULT_MESSAGES como fallback final
    """
    # Tenta template consolidado especifico do dia
    specific_key = f"overdueConsolidatedDia{max_days_overdue}"
    if specific_key in messages:
        return messages[specific_key]

    # Fallback para templates por faixa
    if max_days_overdue <= 5:
        return messages.get("overdueConsolidatedTemplate1") or DEFAULT_MESSAGES["overdueConsolidated1"]
    elif max_days_overdue <= 10:
        return messages.get("overdueConsolidatedTemplate2") or DEFAULT_MESSAGES["overdueConsolidated2"]
    else:
        return messages.get("overdueConsolidatedTemplate3") or DEFAULT_MESSAGES["overdueConsolidated3"]
