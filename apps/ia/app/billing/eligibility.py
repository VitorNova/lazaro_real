"""Funil de elegibilidade - 6 checks em cadeia."""
import logging
from typing import List, Optional, Tuple

from app.billing.models import Payment, EligiblePayment, RejectedPayment, EligibilityResult
from app.core.utils.phone import normalize_phone, phone_to_remotejid
from app.domain.billing.services.billing_notifier import get_sent_count
from app.services.supabase import get_supabase_service

logger = logging.getLogger(__name__)

CARD_BILLING_TYPES = {"CREDIT_CARD", "DEBIT_CARD"}


# ============================================================================
# CHECKS (ordem importa!)
# ============================================================================

def check_card_pending(payment: Payment) -> Tuple[bool, Optional[str]]:
    """Check 1: Cartao PENDING = pula (cobrado automaticamente)."""
    if payment.billing_type in CARD_BILLING_TYPES and payment.status == "PENDING":
        return False, "card_pending"
    return True, None


async def check_active_contract(payment: Payment, agent_id: str) -> Tuple[bool, Optional[str]]:
    """Check 2: Contrato deve estar ACTIVE. BUG FIX #1."""
    if not payment.subscription_id:
        return True, None

    supabase = get_supabase_service()
    result = (
        supabase.client.table("asaas_contratos")
        .select("status")
        .eq("id", payment.subscription_id)
        .eq("agent_id", agent_id)
        .maybe_single()
        .execute()
    )

    if not result.data:
        return True, None

    if result.data.get("status") != "ACTIVE":
        return False, "contract_cancelled"
    return True, None


async def check_customer_and_phone(
    payment: Payment,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Check 3+4: Cliente valido + telefone valido.
    Combina duas validacoes numa query so.
    BUG FIX #3: Verifica deleted_from_asaas.
    """
    supabase = get_supabase_service()
    result = (
        supabase.client.table("asaas_clientes")
        .select("deleted_from_asaas, mobile_phone, phone")
        .eq("id", payment.customer_id)
        .maybe_single()
        .execute()
    )

    if not result.data:
        return False, "customer_not_found", None

    if result.data.get("deleted_from_asaas"):
        return False, "customer_deleted", None

    raw_phone = result.data.get("mobile_phone") or result.data.get("phone")
    phone = normalize_phone(raw_phone) if raw_phone else None

    if not phone:
        return False, "invalid_phone", None

    return True, None, phone


async def check_max_attempts(
    payment: Payment, agent_id: str, max_attempts: int
) -> Tuple[bool, Optional[str]]:
    """Check 5: Nao exceder maximo de tentativas."""
    sent_count = await get_sent_count(agent_id, payment.id)
    if sent_count >= max_attempts:
        return False, "max_attempts_reached"
    return True, None


async def check_no_exception(
    payment: Payment, agent_id: str, remotejid: str
) -> Tuple[bool, Optional[str]]:
    """Check 6: Nao ter excecao ativa (opt-out/pausa). BUG FIX #6."""
    supabase = get_supabase_service()

    # Query por remotejid
    result1 = (
        supabase.client.table("billing_exceptions")
        .select("id, reason")
        .eq("agent_id", agent_id)
        .eq("active", "true")
        .eq("remotejid", remotejid)
        .maybe_single()
        .execute()
    )

    # Query por payment_id
    result2 = (
        supabase.client.table("billing_exceptions")
        .select("id, reason")
        .eq("agent_id", agent_id)
        .eq("active", "true")
        .eq("payment_id", payment.id)
        .maybe_single()
        .execute()
    )

    # Verificar ambos os resultados
    result_data = None
    if result1 and result1.data:
        result_data = result1.data
    elif result2 and result2.data:
        result_data = result2.data

    if result_data:
        reason = result_data.get("reason", "manual")
        return False, f"exception_{reason}"
    return True, None


# ============================================================================
# ORQUESTRADOR
# ============================================================================

async def run_eligibility_checks(
    payments: List[Payment],
    agent_id: str,
    max_attempts: int = 15,
) -> EligibilityResult:
    """Executa todos os checks em ordem para cada payment."""
    eligible: List[EligiblePayment] = []
    rejected: List[RejectedPayment] = []

    for payment in payments:
        # Check 1: Card pending
        passed, reason = check_card_pending(payment)
        if not passed:
            rejected.append(RejectedPayment(payment, reason, "card_pending"))
            continue

        # Check 2: Active contract
        passed, reason = await check_active_contract(payment, agent_id)
        if not passed:
            rejected.append(RejectedPayment(payment, reason, "active_contract"))
            continue

        # Check 3+4: Customer valid + phone (query combinada)
        passed, reason, phone = await check_customer_and_phone(payment)
        if not passed:
            rejected.append(RejectedPayment(payment, reason, "customer_phone"))
            continue

        # Check 5: Max attempts
        passed, reason = await check_max_attempts(payment, agent_id, max_attempts)
        if not passed:
            rejected.append(RejectedPayment(payment, reason, "max_attempts"))
            continue

        # Check 6: No exception
        remotejid = phone_to_remotejid(phone)
        passed, reason = await check_no_exception(payment, agent_id, remotejid)
        if not passed:
            rejected.append(RejectedPayment(payment, reason, "no_exception"))
            continue

        # Passou todos os checks
        eligible.append(EligiblePayment(
            payment=payment,
            phone=phone,
            customer_name=payment.customer_name,
        ))

    logger.info({
        "event": "eligibility_complete",
        "agent_id": agent_id,
        "total": len(payments),
        "eligible": len(eligible),
        "rejected": len(rejected),
    })

    return EligibilityResult(eligible=eligible, rejected=rejected)
