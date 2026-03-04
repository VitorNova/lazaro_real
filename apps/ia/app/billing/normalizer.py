"""Normalizacao de dados da API Asaas para formato interno."""
from datetime import date
from typing import Any, Dict

from app.billing.models import Payment
from app.utils.dias_uteis import parse_date


def normalize_api_payment(payment: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza camelCase da API para snake_case."""
    return {
        **payment,
        "customer_id": payment.get("customer") or payment.get("customer_id", ""),
        "customer_name": payment.get("customerName") or payment.get("customer_name", ""),
        "due_date": payment.get("dueDate") or payment.get("due_date"),
        "billing_type": payment.get("billingType") or payment.get("billing_type", ""),
        "invoice_url": payment.get("invoiceUrl") or payment.get("invoice_url"),
        "bank_slip_url": payment.get("bankSlipUrl") or payment.get("bank_slip_url"),
        "subscription_id": payment.get("subscription") or payment.get("subscription_id"),
    }


def dict_to_payment(data: Dict[str, Any], source: str) -> Payment:
    """Converte dict normalizado para dataclass Payment."""
    due_date_raw = data.get("due_date")
    if isinstance(due_date_raw, str):
        due_date = parse_date(due_date_raw)
    elif isinstance(due_date_raw, date):
        due_date = due_date_raw
    else:
        raise ValueError(f"due_date invalido: {due_date_raw}")

    return Payment(
        id=data["id"],
        customer_id=data.get("customer_id", ""),
        customer_name=data.get("customer_name", ""),
        value=float(data.get("value", 0)),
        due_date=due_date,
        status=data.get("status", ""),
        billing_type=data.get("billing_type", ""),
        invoice_url=data.get("invoice_url"),
        bank_slip_url=data.get("bank_slip_url"),
        subscription_id=data.get("subscription_id"),
        source=source,
    )
