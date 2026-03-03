"""
Billing Job Configuration - Constantes e configuracoes para cobranca automatica.

Extraido de: app/jobs/cobrar_clientes.py (Fase 4.1)
"""

from typing import Dict, Set

# ============================================================================
# LOCK DISTRIBUIDO (Redis)
# ============================================================================

# Chave do lock no Redis (TTL: 30 minutos)
BILLING_JOB_LOCK_KEY = "lock:billing_job:global"
BILLING_JOB_LOCK_TTL = 1800  # 30 minutos


# ============================================================================
# STATUS DE PAGAMENTOS
# ============================================================================

# Status de pagamentos pagos (para pular)
PAID_STATUSES: Set[str] = {"RECEIVED", "CONFIRMED", "RECEIVED_IN_CASH"}

# Tipos de pagamento por cartao (skip PENDING, processar OVERDUE)
CARD_BILLING_TYPES: Set[str] = {"CREDIT_CARD", "DEBIT_CARD"}


# ============================================================================
# CONFIGURACAO DE RETRY (API Asaas)
# ============================================================================

ASAAS_RETRY_CONFIG: Dict[str, float] = {
    "max_retries": 2,
    "backoff_factor": 1.5,  # 1s, 1.5s
    "timeout": 30.0,
}


# ============================================================================
# VALIDACAO DE NOMES DE CLIENTES
# ============================================================================

# Nomes considerados invalidos (placeholders)
INVALID_NAMES: Set[str] = {"", "Sem nome", "Desconhecido", "Cliente", "Cliente Asaas"}


# ============================================================================
# TEMPLATES DEFAULT DE MENSAGENS
# ============================================================================

DEFAULT_MESSAGES: Dict[str, str] = {
    # Lembrete antes do vencimento
    "reminder": (
        "Ola {nome}! Lembrete: sua fatura de {valor} vence em {vencimento}. "
        "Evite juros pagando em dia."
    ),
    # No dia do vencimento
    "dueDate": (
        "Ola {nome}! Hoje e o dia do vencimento da sua fatura de {valor}. "
        "Efetue o pagamento para evitar juros."
    ),
    # Generico vencido
    "overdue": (
        "Ola {nome}! Sua fatura de {valor} venceu em {vencimento} e esta "
        "ha {dias_atraso} dias em atraso. Regularize sua situacao."
    ),
    # D+1 a D+5 (gentil)
    "overdue1": (
        "Ola {nome}! Sua fatura de {valor} venceu em {vencimento}. "
        "Evite juros, regularize: {link}"
    ),
    # D+6 a D+10 (firme)
    "overdue2": (
        "Ola {nome}! Sua fatura de {valor} esta ha {dias_atraso} dias em atraso. "
        "Regularize agora: {link}"
    ),
    # D+11 a D+15 (urgente)
    "overdue3": (
        "Ola {nome}! URGENTE: Sua fatura de {valor} esta ha {dias_atraso} dias vencida. "
        "Ultimo aviso antes de medidas adicionais: {link}"
    ),
    # Consolidado - multiplas faturas
    "overdueConsolidated1": (
        "Ola {nome}! Voce tem {qtd} faturas em atraso, totalizando {total}. "
        "Evite juros, regularize sua situacao: {link}"
    ),
    "overdueConsolidated2": (
        "Ola {nome}! Voce tem {qtd} faturas vencidas, totalizando {total}. "
        "Regularize agora: {link}"
    ),
    "overdueConsolidated3": (
        "Ola {nome}! URGENTE: Voce tem {qtd} faturas vencidas, totalizando {total}. "
        "Ultimo aviso antes de medidas adicionais: {link}"
    ),
}
