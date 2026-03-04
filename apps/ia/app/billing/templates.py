"""Templates de mensagem para cobranca."""
from typing import Any, Dict

DEFAULT_MESSAGES = {
    "reminder": (
        "Ola, {nome}! 😊 Tudo bem?\n\n"
        "Passando para lembrar que sua mensalidade de {valor} vence em {vencimento}.\n\n"
        "Para sua comodidade, segue o link de pagamento:\n"
        "🔗 {link}\n\n"
        "Qualquer duvida, estamos a disposicao!"
    ),
    "dueDate": (
        "Ola, {nome}! 😊\n\n"
        "Sua mensalidade de {valor} vence hoje ({vencimento}).\n\n"
        "Efetue o pagamento para manter tudo em dia:\n"
        "🔗 {link}\n\n"
        "Caso ja tenha pago, por favor desconsidere esta mensagem."
    ),
    "overdue": (
        "Ola, {nome}! Tudo bem?\n\n"
        "Notamos que a mensalidade de {valor} com vencimento em {vencimento} "
        "ainda permanece em aberto.\n\n"
        "🔗 Link para pagamento: {link}\n\n"
        "Caso ja tenha pago, por favor desconsidere esta mensagem. 💙"
    ),
    "overdue1": (
        "Ola, {nome}! Tudo bem?\n\n"
        "Notamos que a mensalidade de {valor} com vencimento em {vencimento} "
        "ainda permanece em aberto.\n\n"
        "Gostariamos de lembrar gentilmente sobre o pagamento, "
        "a fim de evitar qualquer inconveniente.\n"
        "🔗 Link para pagamento: {link}\n\n"
        "Caso ja tenha pago, por favor desconsidere esta mensagem. 💙"
    ),
    "overdue2": (
        "Ola, {nome}.\n\n"
        "Sua mensalidade de {valor} esta em atraso ha {dias_atraso} dias "
        "(vencimento: {vencimento}).\n\n"
        "Pedimos que regularize o quanto antes para evitar interrupcao no servico.\n"
        "🔗 Link para pagamento: {link}\n\n"
        "Teve algum problema? Responda esta mensagem que podemos ajudar. 🤝"
    ),
    "overdue3": (
        "{nome}, atencao! ⚠️\n\n"
        "Sua mensalidade de {valor} esta vencida ha {dias_atraso} dias.\n\n"
        "Essa e nossa ultima tentativa de contato antes de medidas adicionais. "
        "Regularize agora:\n"
        "🔗 {link}\n\n"
        "Esta com dificuldades? Responda para negociarmos uma solucao."
    ),
    "overdueConsolidated1": (
        "Ola, {nome}! Tudo bem?\n\n"
        "Identificamos que voce possui {qtd} faturas em aberto, "
        "totalizando {total}.\n\n"
        "Regularize para manter tudo em dia:\n"
        "🔗 {link}\n\n"
        "Caso ja tenha pago, por favor desconsidere. 💙"
    ),
    "overdueConsolidated2": (
        "Ola, {nome}.\n\n"
        "Voce possui {qtd} faturas vencidas, totalizando {total}.\n\n"
        "Pedimos que regularize o quanto antes para evitar interrupcao no servico.\n"
        "🔗 {link}\n\n"
        "Precisa de ajuda? Responda esta mensagem. 🤝"
    ),
    "overdueConsolidated3": (
        "{nome}, atencao! ⚠️\n\n"
        "Voce possui {qtd} faturas vencidas, totalizando {total}.\n\n"
        "Ultima tentativa de contato antes de medidas adicionais.\n"
        "🔗 {link}\n\n"
        "Esta com dificuldades? Responda para negociarmos."
    ),
}


def get_overdue_template(days_overdue: int, messages: Dict[str, Any]) -> str:
    """Seleciona template baseado nos dias de atraso."""
    specific_key = f"overdueDia{days_overdue}"
    if specific_key in messages:
        return messages[specific_key]

    if days_overdue <= 5:
        return messages.get("overdueTemplate1") or DEFAULT_MESSAGES["overdue1"]
    elif days_overdue <= 10:
        return messages.get("overdueTemplate2") or DEFAULT_MESSAGES["overdue2"]
    else:
        return messages.get("overdueTemplate3") or DEFAULT_MESSAGES["overdue3"]


def get_consolidated_overdue_template(max_days_overdue: int, messages: Dict[str, Any]) -> str:
    """Seleciona template consolidado baseado nos dias de atraso."""
    specific_key = f"overdueConsolidatedDia{max_days_overdue}"
    if specific_key in messages:
        return messages[specific_key]

    if max_days_overdue <= 5:
        return messages.get("overdueConsolidatedTemplate1") or DEFAULT_MESSAGES["overdueConsolidated1"]
    elif max_days_overdue <= 10:
        return messages.get("overdueConsolidatedTemplate2") or DEFAULT_MESSAGES["overdueConsolidated2"]
    else:
        return messages.get("overdueConsolidatedTemplate3") or DEFAULT_MESSAGES["overdueConsolidated3"]
