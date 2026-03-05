"""
Customer Phone Service - Resolucao de telefone de clientes para cobranca.

Extraido de: app/jobs/cobrar_clientes.py (Fase 3)

Funcionalidades:
- Normalizacao de telefone brasileiro
- Conversao para formato WhatsApp remoteJid
- Obtencao de telefone do pagamento
"""

import re
from typing import Any, Dict, Optional


def get_customer_phone(payment: Dict[str, Any]) -> Optional[str]:
    """
    Obtem telefone do pagamento normalizado.

    Prioriza mobile_phone sobre phone (ja vem do JOIN com asaas_clientes).

    Args:
        payment: Dados do pagamento com mobile_phone e/ou phone

    Returns:
        Telefone normalizado (ex: 5511999998888) ou None se invalido
    """
    phone = payment.get("mobile_phone") or payment.get("phone")
    if not phone:
        return None

    # Remove caracteres nao numericos
    cleaned = re.sub(r"\D", "", str(phone))

    # Adiciona codigo do pais se nao tiver
    if not cleaned.startswith("55"):
        cleaned = "55" + cleaned

    # Valida formato basico (12-13 digitos com DDI)
    if len(cleaned) < 12 or len(cleaned) > 13:
        return None

    return cleaned


def phone_to_remotejid(phone: str) -> str:
    """
    Converte telefone para formato remoteJid do WhatsApp.

    Args:
        phone: Telefone numerico

    Returns:
        RemoteJid no formato {phone}@s.whatsapp.net
    """
    cleaned = re.sub(r"\D", "", phone)
    return f"{cleaned}@s.whatsapp.net"
