"""Dataclasses tipadas para o pipeline de cobranca."""
from dataclasses import dataclass
from datetime import date
from typing import List, Optional


@dataclass
class Payment:
    """Representa uma cobranca normalizada."""
    id: str
    customer_id: str
    customer_name: str
    value: float
    due_date: date
    status: str  # "PENDING" | "OVERDUE"
    billing_type: str
    invoice_url: Optional[str]
    bank_slip_url: Optional[str]
    subscription_id: Optional[str]
    source: str  # "api" | "cache"


@dataclass
class CollectorResult:
    """Resultado da coleta de pagamentos."""
    payments: List[Payment]
    source: str  # "api" | "cache"
    cache_age_hours: float
    degraded: bool  # True = cache > 6h, NAO COBRA


@dataclass
class EligiblePayment:
    """Pagamento que passou em todos os checks."""
    payment: Payment
    phone: str  # normalizado, com 55
    customer_name: str


@dataclass
class RejectedPayment:
    """Pagamento rejeitado por um check."""
    payment: Payment
    reason: str  # "contract_cancelled", "customer_deleted", etc
    check_name: str


@dataclass
class EligibilityResult:
    """Resultado do funil de elegibilidade."""
    eligible: List[EligiblePayment]
    rejected: List[RejectedPayment]


@dataclass
class RulerDecision:
    """Decisao da regua de cobranca."""
    should_send: bool
    offset: int  # D-1, D0, D+3...
    template_key: str
    phase: str  # "reminder" | "due_date" | "overdue"


@dataclass
class DispatchResult:
    """Resultado do envio de notificacao."""
    status: str  # "sent" | "duplicate" | "error"
    payment_id: str
    template_used: str
    offset: int
    error: Optional[str]
