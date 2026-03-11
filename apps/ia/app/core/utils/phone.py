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


def generate_phone_variants(phone: str) -> list[str]:
    """
    Gera todas variantes possiveis de telefone para busca.

    O problema: telefones brasileiros podem ter ou nao o "9 extra" (nono digito)
    e podem vir com ou sem o DDI 55. Isso causa mismatch na busca.

    Exemplo real (bug IDALIA 11/03/2026):
    - Asaas tinha: 91989650040 -> normalizado: 5591989650040 (13 digitos)
    - Leadbox tinha: 559189650040 (12 digitos)
    - Busca simples nao encontrava o lead

    Args:
        phone: Telefone em qualquer formato

    Returns:
        Lista de variantes possiveis (sem @s.whatsapp.net)
    """
    if not phone:
        return []

    # Remove caracteres nao numericos
    cleaned = re.sub(r"\D", "", str(phone))

    if not cleaned:
        return []

    variants = set()

    # Garante que comeca com 55
    if not cleaned.startswith("55"):
        cleaned = "55" + cleaned

    # Adiciona versao original normalizada
    variants.add(cleaned)

    # Extrai DDD (posicoes 2-3 apos o 55)
    if len(cleaned) >= 4:
        ddd = cleaned[2:4]
        rest = cleaned[4:]  # Parte apos o DDD

        # Verifica se tem 9 digitos apos DDD (com nono digito)
        if len(rest) == 9 and rest.startswith("9"):
            # Versao SEM o nono digito (remove o 9 inicial)
            without_nine = "55" + ddd + rest[1:]
            variants.add(without_nine)
        # Verifica se tem 8 digitos apos DDD (sem nono digito)
        elif len(rest) == 8:
            # Versao COM o nono digito (adiciona 9 no inicio)
            with_nine = "55" + ddd + "9" + rest
            variants.add(with_nine)

    return list(variants)


def find_message_record_by_phone(
    supabase,
    table_messages: str,
    phone: str,
    customer_id: str = None
) -> Optional[dict]:
    """
    Busca registro de mensagem usando multiplas variantes de telefone.

    Estrategia:
    1. Gera todas variantes possiveis do telefone
    2. Busca com OR em todas variantes (remotejid)
    3. Fallback: busca por customer_id se fornecido

    Args:
        supabase: Cliente Supabase
        table_messages: Nome da tabela de mensagens do agente
        phone: Telefone para buscar
        customer_id: ID do cliente Asaas (opcional, usado como fallback)

    Returns:
        Registro da mensagem ou None se nao encontrar
    """
    if not phone and not customer_id:
        return None

    # Estrategia 1: Buscar por variantes de telefone
    if phone:
        variants = generate_phone_variants(phone)

        if variants:
            # Constroi query OR com todas variantes
            or_conditions = ",".join([
                f'remotejid.eq.{v}@s.whatsapp.net'
                for v in variants
            ])

            try:
                result = (
                    supabase.client.table(table_messages)
                    .select("*")
                    .or_(or_conditions)
                    .limit(1)
                    .execute()
                )

                if result.data and len(result.data) > 0:
                    return result.data[0]
            except Exception:
                pass  # Continua para fallback

    # Estrategia 2: Fallback por customer_id
    if customer_id:
        try:
            result = (
                supabase.client.table(table_messages)
                .select("*")
                .eq("asaas_customer_id", customer_id)
                .limit(1)
                .execute()
            )

            if result.data and len(result.data) > 0:
                return result.data[0]
        except Exception:
            pass

    return None
