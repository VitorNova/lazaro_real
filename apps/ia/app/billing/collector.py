"""Coleta de pagamentos da API Asaas com fallback para cache."""
import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Tuple

from app.billing.models import Payment, CollectorResult
from app.billing.normalizer import normalize_api_payment, dict_to_payment
from app.services.gateway_pagamento import create_asaas_service
from app.services.supabase import get_supabase_service

logger = logging.getLogger(__name__)

CACHE_MAX_AGE_HOURS = 6.0


async def fetch_from_api(
    asaas_api_key: str,
    status: str,
    due_date_start: date,
    due_date_end: date,
) -> Tuple[List[Dict[str, Any]], bool]:
    """Busca da API Asaas. Retorna (payments, success)."""
    try:
        asaas = create_asaas_service(api_key=asaas_api_key)
        params = {
            "status": status,
            "dueDate[ge]": due_date_start.strftime("%Y-%m-%d"),
            "dueDate[le]": due_date_end.strftime("%Y-%m-%d"),
            "offset": 0,
            "limit": 100,
        }

        all_payments: List[Dict] = []
        max_pages = 10

        for _ in range(max_pages):
            response = await asaas.list_payments(**params)
            data = response.get("data", [])
            all_payments.extend(data)

            if not response.get("hasMore", False):
                break
            params["offset"] += params["limit"]

        logger.info({
            "event": "api_fetch_success",
            "status": status,
            "count": len(all_payments),
        })
        return all_payments, True

    except Exception as e:
        logger.warning({"event": "api_fetch_failed", "error": str(e)})
        return [], False


async def fetch_from_cache(
    agent_id: str,
    status: str,
    due_date_start: date,
    due_date_end: date,
) -> Tuple[List[Dict[str, Any]], float]:
    """Busca do Supabase (cache). Retorna (payments, cache_age_hours)."""
    supabase = get_supabase_service()

    result = (
        supabase.client.table("asaas_cobrancas")
        .select("*, last_synced_at")
        .eq("agent_id", agent_id)
        .eq("status", status)
        .gte("due_date", due_date_start.strftime("%Y-%m-%d"))
        .lte("due_date", due_date_end.strftime("%Y-%m-%d"))
        .eq("deleted_from_asaas", False)
        .execute()
    )

    payments = result.data or []

    # Calcular idade do cache (mais antigo)
    cache_age = 0.0
    if payments:
        synced_times = [p.get("last_synced_at") for p in payments if p.get("last_synced_at")]
        if synced_times:
            oldest = min(synced_times)
            synced_at = datetime.fromisoformat(oldest.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            cache_age = (now - synced_at).total_seconds() / 3600

    return payments, cache_age


async def collect_payments(
    agent: Dict[str, Any],
    status: str,
    due_date_start: date,
    due_date_end: date,
) -> CollectorResult:
    """
    Busca pagamentos com fallback inteligente.

    - API OK -> source="api", degraded=False
    - API falhou + cache < 6h -> source="cache", degraded=False
    - API falhou + cache >= 6h -> source="cache", degraded=True (NAO COBRA)
    """
    agent_id = agent["id"]
    asaas_api_key = agent.get("asaas_api_key")

    # 1. Tentar API
    if asaas_api_key:
        api_payments, api_success = await fetch_from_api(
            asaas_api_key, status, due_date_start, due_date_end
        )
        if api_success:
            payments = [
                dict_to_payment(normalize_api_payment(p), "api")
                for p in api_payments
            ]
            return CollectorResult(
                payments=payments,
                source="api",
                cache_age_hours=0.0,
                degraded=False,
            )

    # 2. Fallback para cache
    cache_payments, cache_age = await fetch_from_cache(
        agent_id, status, due_date_start, due_date_end
    )

    degraded = cache_age >= CACHE_MAX_AGE_HOURS
    if degraded:
        logger.warning({
            "event": "collector_degraded",
            "agent_id": agent_id,
            "cache_age_hours": round(cache_age, 2),
            "status": status,
        })

    payments = [dict_to_payment(p, "cache") for p in cache_payments]
    return CollectorResult(
        payments=payments,
        source="cache",
        cache_age_hours=cache_age,
        degraded=degraded,
    )
