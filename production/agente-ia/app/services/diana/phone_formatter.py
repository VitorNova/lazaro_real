"""
Diana v2 - Formatador de telefone.

Recebe QUALQUER formato de telefone brasileiro e retorna no formato
que a UAZAPI aceita: apenas digitos com DDI (5566999887766).
"""

import re
from typing import Optional


def format_phone(phone: str) -> Optional[str]:
    """
    Formata qualquer formato de telefone brasileiro para o padrao UAZAPI.

    Aceita todos esses formatos de entrada:
    - 66999887766
    - (66) 99988-7766
    - +55 66 99988-7766
    - 55 66 99988-7766
    - 5566999887766
    - 066999887766
    - 66 9 9988-7766
    - +55(66)99988-7766
    - whatsapp: 5566999887766

    Regras de formatacao:
    1. Remove TUDO que nao e digito
    2. Se comeca com 0, remove o 0
    3. Se tem 10 ou 11 digitos (sem DDI), adiciona 55
    4. Se tem 12 digitos (55 + DDD + 8 digitos), verifica se precisa add 9
    5. Se tem 13 digitos (55 + DDD + 9 digitos), OK

    Args:
        phone: Telefone em qualquer formato

    Returns:
        Telefone formatado (5566999887766) ou None se invalido
    """
    if not phone:
        return None

    # Remove TUDO que nao e digito
    cleaned = re.sub(r"\D", "", phone)

    if not cleaned:
        return None

    # Remove zero inicial se houver
    if cleaned.startswith("0") and len(cleaned) > 10:
        cleaned = cleaned[1:]

    # Se comecar com 0 depois de limpar (ex: 066999887766)
    while cleaned.startswith("0"):
        cleaned = cleaned[1:]

    # Determina tamanho para saber se precisa adicionar DDI/9
    length = len(cleaned)

    # 8 digitos: DDD sem 9 (antigo) - ex: 66998877
    # Nao tem como saber o DDD, invalido
    if length == 8:
        return None

    # 9 digitos: DDD com 9 ou numero sem DDD - ex: 669998877 ou 999887766
    if length == 9:
        # Verifica se comeca com 9 (celular com 9 digitos sem DDD)
        if cleaned.startswith("9"):
            # Nao tem DDD, invalido
            return None
        # Assume que e DDD + 8 digitos (precisa add 55 e 9)
        # Ex: 669988776 -> 5566999887766 (add 55 e 9 apos DDD)
        # Mas isso e ambiguo, melhor retornar None
        return None

    # 10 digitos: DDD + 8 digitos (precisa add 55 e 9)
    # Ex: 6699887766 -> 5566999887766
    if length == 10:
        ddd = cleaned[:2]
        numero = cleaned[2:]
        # Adiciona 9 se numero nao comecar com 9
        if not numero.startswith("9"):
            numero = "9" + numero
        return f"55{ddd}{numero}"

    # 11 digitos: DDD + 9 digitos (precisa add 55)
    # Ex: 66999887766 -> 5566999887766
    if length == 11:
        return f"55{cleaned}"

    # 12 digitos: 55 + DDD + 8 digitos (precisa add 9)
    # Ex: 556699887766 -> 5566999887766
    if length == 12:
        if cleaned.startswith("55"):
            ddd = cleaned[2:4]
            numero = cleaned[4:]
            # Adiciona 9 se numero nao comecar com 9
            if not numero.startswith("9"):
                numero = "9" + numero
            return f"55{ddd}{numero}"
        # Se nao comecar com 55, invalido
        return None

    # 13 digitos: 55 + DDD + 9 digitos (OK)
    # Ex: 5566999887766 -> 5566999887766
    if length == 13:
        if cleaned.startswith("55"):
            return cleaned
        return None

    # Mais de 13 digitos: invalido
    return None


def format_to_remotejid(phone: str) -> Optional[str]:
    """
    Formata telefone para remotejid do WhatsApp.

    Args:
        phone: Telefone em qualquer formato

    Returns:
        remotejid (5566999887766@s.whatsapp.net) ou None se invalido
    """
    formatted = format_phone(phone)
    if formatted:
        return f"{formatted}@s.whatsapp.net"
    return None


def extract_phone_from_remotejid(remotejid: str) -> Optional[str]:
    """
    Extrai numero de telefone limpo do remotejid.

    Args:
        remotejid: ID do WhatsApp (5566999887766@s.whatsapp.net)

    Returns:
        Numero limpo (5566999887766) ou None
    """
    if not remotejid:
        return None

    # Remove sufixo @s.whatsapp.net ou @g.us ou @lid
    cleaned = remotejid.split("@")[0]

    # Remove caracteres nao numericos
    cleaned = re.sub(r"\D", "", cleaned)

    return cleaned if cleaned else None


def is_valid_brazilian_phone(phone: str) -> bool:
    """
    Verifica se o telefone e valido apos formatacao.

    Args:
        phone: Telefone em qualquer formato

    Returns:
        True se valido, False caso contrario
    """
    formatted = format_phone(phone)
    if not formatted:
        return False

    # Deve ter 13 digitos (55 + DDD + 9 + numero)
    if len(formatted) != 13:
        return False

    # Deve comecar com 55
    if not formatted.startswith("55"):
        return False

    # DDD deve ser valido (11-99, alguns nao existem mas vamos aceitar)
    ddd = int(formatted[2:4])
    if ddd < 11 or ddd > 99:
        return False

    # Celular deve comecar com 9
    if formatted[4] != "9":
        return False

    return True
