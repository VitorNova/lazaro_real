"""Formatadores reutilizaveis."""


def format_brl(value: float) -> str:
    """Formata valor em Real brasileiro (R$ 1.234,56)."""
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
