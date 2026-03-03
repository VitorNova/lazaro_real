"""
Phone Utilities - Funcoes utilitarias para manipulacao de telefones.

Extraido de: app/jobs/cobrar_clientes.py (Fase 4.7)

Funcionalidades:
- Mascaras para LGPD compliance
- Extracao e normalizacao de telefone
- Conversao para formato WhatsApp
"""

import re
from typing import Any, Dict, Optional


def mask_phone(phone: str) -> str:
    """
    Mascara telefone para logs (LGPD/GDPR compliance).

    Exemplo: 5566912345678 -> 5566****5678 (primeiros 4 + ultimos 4)
    """
    if not phone or len(phone) < 8:
        return "****"
    return phone[:4] + "*" * (len(phone) - 8) + phone[-4:]


def mask_customer_name(name: str) -> str:
    """
    Mascara nome de cliente para logs (LGPD/GDPR compliance).

    Exemplo: "Joao Silva" -> "J*********" (apenas primeira letra)
    """
    if not name or len(name) < 3:
        return "***"
    return name[0] + "*" * (len(name) - 1)


def get_customer_phone(payment: Dict[str, Any]) -> Optional[str]:
    """
    Obtem telefone do pagamento normalizado (ja vem do JOIN com asaas_clientes).
    Prioriza mobile_phone sobre phone.

    Normalizacao:
    - Remove caracteres nao numericos
    - Adiciona codigo do pais (55) se nao tiver
    - Valida formato (12-13 digitos)

    Args:
        payment: Dicionario com dados do pagamento (mobile_phone, phone)

    Returns:
        Telefone normalizado ou None se invalido
    """
    phone = payment.get("mobile_phone") or payment.get("phone")
    if not phone:
        return None

    # Remove caracteres nao numericos
    cleaned = re.sub(r"\D", "", str(phone))

    # Adiciona codigo do pais se nao tiver
    if not cleaned.startswith("55"):
        cleaned = "55" + cleaned

    # Valida formato basico (12-13 digitos: 55 + DDD + 8/9 digitos)
    if len(cleaned) < 12 or len(cleaned) > 13:
        return None

    return cleaned


def phone_to_remotejid(phone: str) -> str:
    """
    Converte telefone para formato remoteJid do WhatsApp.

    Exemplo: "5566912345678" -> "5566912345678@s.whatsapp.net"
    """
    cleaned = re.sub(r"\D", "", phone)
    return f"{cleaned}@s.whatsapp.net"


def normalize_phone(phone: str) -> Optional[str]:
    """
    Normaliza telefone para formato padrao brasileiro.

    - Remove caracteres nao numericos
    - Adiciona 55 se nao tiver
    - Valida comprimento (12-13 digitos)

    Returns:
        Telefone normalizado ou None se invalido
    """
    if not phone:
        return None

    cleaned = re.sub(r"\D", "", str(phone))

    if not cleaned.startswith("55"):
        cleaned = "55" + cleaned

    if len(cleaned) < 12 or len(cleaned) > 13:
        return None

    return cleaned


def extract_ddd(phone: str) -> Optional[str]:
    """
    Extrai DDD de um telefone normalizado.

    Exemplo: "5566912345678" -> "66"
    """
    cleaned = re.sub(r"\D", "", phone)

    if cleaned.startswith("55") and len(cleaned) >= 4:
        return cleaned[2:4]

    return None


def is_mobile(phone: str) -> bool:
    """
    Verifica se o telefone e celular (comeca com 9 apos DDD).

    Celulares brasileiros tem 9 digitos apos o DDD e comecam com 9.
    """
    cleaned = re.sub(r"\D", "", phone)

    if cleaned.startswith("55") and len(cleaned) >= 5:
        # Pega o primeiro digito apos o DDD (posicao 4)
        first_digit = cleaned[4]
        return first_digit == "9"

    return False
