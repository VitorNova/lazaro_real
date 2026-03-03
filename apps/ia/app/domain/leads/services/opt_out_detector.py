"""
Opt-Out Detector - Deteccao de pedidos de descadastramento em mensagens.

Extraido de reengajar_leads.py (Fase 5.1).
"""

from typing import List


# ============================================================================
# OPT-OUT PATTERNS
# ============================================================================

OPT_OUT_PATTERNS: List[str] = [
    "nao quero", "não quero",
    "para de mandar", "pare de mandar",
    "para de enviar", "pare de enviar",
    "nao me mande", "não me mande",
    "nao mande mais", "não mande mais",
    "me deixa em paz", "me deixe em paz",
    "nao tenho interesse", "não tenho interesse",
    "sem interesse",
    "para com isso", "pare com isso",
    "nao preciso", "não preciso",
    "cancelar", "desinscrever",
    "sai fora", "saia",
    "bloquear", "spam",
    "para por favor", "pare por favor",
]


# ============================================================================
# DETECTOR
# ============================================================================

def detect_opt_out(message: str) -> bool:
    """
    Detecta se a mensagem contem pedido de opt-out.

    Args:
        message: Texto da mensagem a analisar

    Returns:
        True se detectar pedido de opt-out, False caso contrario
    """
    if not message:
        return False
    lower = message.lower().strip()
    return any(pattern in lower for pattern in OPT_OUT_PATTERNS)
