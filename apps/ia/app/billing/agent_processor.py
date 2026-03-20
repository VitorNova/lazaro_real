"""Processador de cobranca por agente."""
import logging
from datetime import date
from typing import Any, Dict, List

from app.billing.collector import collect_payments
from app.billing.dispatcher import dispatch_single
from app.billing.eligibility import run_eligibility_checks
from app.billing.models import EligiblePayment
from app.billing.ruler import evaluate, DEFAULT_SCHEDULE
from app.core.utils.dias_uteis import add_business_days, subtract_business_days

logger = logging.getLogger(__name__)


async def process_agent(agent: Dict[str, Any], today: date) -> Dict[str, Any]:
    """
    Processa cobranca para um agente.

    Pipeline completo:
    1. PENDING - Lembretes D-2, D-1 (reminderDays)
    2. PENDING - Vencimento D0 (onDueDate)
    3. OVERDUE - Atrasos D+1 a D+15 (agrupado por cliente)

    Retorna estatisticas: sent, skipped, errors, degraded
    """
    config = (agent.get("asaas_config") or {}).get("autoCollection") or {}
    messages_config = config.get("messages") or {}
    max_attempts = (config.get("afterDue") or {}).get("maxAttempts", 15)

    # Construir schedule a partir da config do agente
    # BUG FIX: Antes usava DEFAULT_SCHEDULE hardcoded, ignorando overdueDays do agente
    reminder_days = config.get("reminderDays") or []
    overdue_days = (config.get("afterDue") or {}).get("overdueDays") or []
    schedule = [-d for d in reminder_days] + [0] + overdue_days

    stats = {"sent": 0, "skipped": 0, "errors": 0, "degraded": False}
    agent_id = agent["id"]

    # ========================================================================
    # FASE 1: PENDING - Lembretes (D-2, D-1)
    # ========================================================================
    for days_ahead in reminder_days:
        target_date = add_business_days(today, days_ahead)

        result = await collect_payments(agent, "PENDING", target_date, target_date)

        if result.degraded:
            stats["degraded"] = True
            logger.warning({
                "event": "reminder_skipped_degraded",
                "agent_id": agent_id,
                "days_ahead": days_ahead,
            })
            continue

        eligibility = await run_eligibility_checks(
            result.payments, agent_id, max_attempts
        )
        stats["skipped"] += len(eligibility.rejected)

        for eligible in eligibility.eligible:
            decision = evaluate(today, eligible.payment.due_date, schedule=schedule)

            if not decision.should_send:
                logger.info({
                    "event": "billing_skipped_not_in_schedule",
                    "phase": "reminder",
                    "payment_id": eligible.payment.id,
                    "customer_name": eligible.payment.customer_name,
                    "offset": decision.offset,
                    "due_date": str(eligible.payment.due_date),
                })
                stats["skipped"] += 1
                continue

            dispatch_result = await dispatch_single(
                agent, eligible, decision, messages_config
            )

            if dispatch_result.status == "sent":
                stats["sent"] += 1
            elif dispatch_result.status == "error":
                stats["errors"] += 1
            else:
                stats["skipped"] += 1

    # ========================================================================
    # FASE 2: PENDING - Vencimento hoje (D0)
    # ========================================================================
    on_due_date = config.get("onDueDate", True)

    if on_due_date:
        result = await collect_payments(agent, "PENDING", today, today)

        if result.degraded:
            stats["degraded"] = True
            logger.warning({
                "event": "duedate_skipped_degraded",
                "agent_id": agent_id,
            })
        else:
            eligibility = await run_eligibility_checks(
                result.payments, agent_id, max_attempts
            )
            stats["skipped"] += len(eligibility.rejected)

            for eligible in eligibility.eligible:
                decision = evaluate(today, eligible.payment.due_date, schedule=schedule)

                if not decision.should_send:
                    logger.info({
                        "event": "billing_skipped_not_in_schedule",
                        "phase": "due_date",
                        "payment_id": eligible.payment.id,
                        "customer_name": eligible.payment.customer_name,
                        "offset": decision.offset,
                        "due_date": str(eligible.payment.due_date),
                    })
                    stats["skipped"] += 1
                    continue

                dispatch_result = await dispatch_single(
                    agent, eligible, decision, messages_config
                )

                if dispatch_result.status == "sent":
                    stats["sent"] += 1
                elif dispatch_result.status == "error":
                    stats["errors"] += 1
                else:
                    stats["skipped"] += 1

    # ========================================================================
    # FASE 3: OVERDUE - Atrasos (D+1 a D+15, agrupado por cliente)
    # ========================================================================
    after_due_config = config.get("afterDue") or {}
    after_due_enabled = after_due_config.get("enabled", False)

    if after_due_enabled:
        # Buscar faturas vencidas nos ultimos 30 dias uteis
        thirty_ago = subtract_business_days(today, 30)
        yesterday = subtract_business_days(today, 1)

        result = await collect_payments(agent, "OVERDUE", thirty_ago, yesterday)

        if result.degraded:
            stats["degraded"] = True
            logger.warning({
                "event": "overdue_skipped_degraded",
                "agent_id": agent_id,
            })
        else:
            eligibility = await run_eligibility_checks(
                result.payments, agent_id, max_attempts
            )
            stats["skipped"] += len(eligibility.rejected)

            # Agrupar por customer_id para mensagens consolidadas futuras
            grouped: Dict[str, List[EligiblePayment]] = {}
            for eligible in eligibility.eligible:
                cid = eligible.payment.customer_id
                if cid not in grouped:
                    grouped[cid] = []
                grouped[cid].append(eligible)

            # Processar cada cliente
            for customer_id, customer_payments in grouped.items():
                # Por enquanto, processar cada fatura individualmente
                # TODO: Implementar mensagem consolidada quando > 1 fatura
                for eligible in customer_payments:
                    decision = evaluate(today, eligible.payment.due_date, schedule=schedule)

                    if not decision.should_send:
                        logger.info({
                            "event": "billing_skipped_not_in_schedule",
                            "phase": "overdue",
                            "payment_id": eligible.payment.id,
                            "customer_name": eligible.payment.customer_name,
                            "offset": decision.offset,
                            "due_date": str(eligible.payment.due_date),
                        })
                        stats["skipped"] += 1
                        continue

                    dispatch_result = await dispatch_single(
                        agent, eligible, decision, messages_config
                    )

                    if dispatch_result.status == "sent":
                        stats["sent"] += 1
                    elif dispatch_result.status == "error":
                        stats["errors"] += 1
                    else:
                        stats["skipped"] += 1

    logger.info({
        "event": "agent_processed",
        "agent_id": agent_id,
        "agent_name": agent.get("name"),
        "sent": stats["sent"],
        "skipped": stats["skipped"],
        "errors": stats["errors"],
        "degraded": stats["degraded"],
    })

    return stats
