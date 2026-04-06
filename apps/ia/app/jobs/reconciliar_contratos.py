# ╔════════════════════════════════════════════════════════════╗
# ║  RECONCILIAR CONTRATOS — Sincronizar assinaturas Asaas   ║
# ╚════════════════════════════════════════════════════════════╝
"""
Contract Reconciliation Job — Sincronizacao diaria Asaas -> asaas_contratos.

Objetivo:
- Sincronizar asaas_contratos com API Asaas (fonte da verdade)
- Inserir novas subscriptions que chegaram sem webhook
- Inativar subscriptions canceladas no Asaas
- Corrigir valores/status divergentes

Frequencia: 1x ao dia, 5h30 BRT (antes do reconciliar_pagamentos das 6h)
"""

import logging
from datetime import datetime
from typing import Any, Dict

from app.integrations.asaas.client import AsaasClient
from app.domain.billing.services.customer_sync_service import resolve_customer_name
from app.services.redis import get_redis_service
from app.services.supabase import get_supabase_service

logger = logging.getLogger(__name__)

CONTRACT_RECONCILIATION_LOCK_KEY = "lock:contract_reconciliation:global"
CONTRACT_RECONCILIATION_LOCK_TTL = 3600  # 1 hora

AGENT_ID = "14e6e5ce-4627-4e38-aac8-f0191669ff53"


async def reconcile_contracts() -> Dict[str, Any]:
    """
    Job de reconciliacao de contratos.

    Compara subscriptions ativas no Asaas com asaas_contratos local.
    Insere novos, atualiza divergentes, inativa cancelados.
    """
    redis = await get_redis_service()

    lock_acquired = await redis.client.set(
        CONTRACT_RECONCILIATION_LOCK_KEY, "1",
        nx=True, ex=CONTRACT_RECONCILIATION_LOCK_TTL,
    )
    if not lock_acquired:
        logger.warning(
            "[RECONCILIAR CONTRATOS] Job ja em execucao, pulando..."
        )
        return {"status": "skipped", "reason": "already_running"}

    try:
        supabase = get_supabase_service()
        sb = supabase.client

        agent_resp = sb.table("agents").select(
            "asaas_api_key"
        ).eq("id", AGENT_ID).limit(1).execute()

        if not agent_resp.data or not agent_resp.data[0].get("asaas_api_key"):
            logger.error("[RECONCILIAR CONTRATOS] API key nao encontrada")
            return {"status": "error", "reason": "no_api_key"}

        api_key = agent_resp.data[0]["asaas_api_key"]
        asaas = AsaasClient(api_key=api_key)

        stats = {
            "inserted": 0,
            "updated": 0,
            "inactivated": 0,
            "unchanged": 0,
            "errors": 0,
        }
        divergencias = []

        # Buscar subscriptions ativas via AsaasClient (com rate limiter)
        logger.info("[RECONCILIAR CONTRATOS] Buscando subscriptions no Asaas...")
        asaas_subs = await asaas.list_all_subscriptions(status="ACTIVE")

        logger.info(
            "[RECONCILIAR CONTRATOS] Asaas: %d subscriptions ativas",
            len(asaas_subs),
        )

        asaas_map = {s["id"]: s for s in asaas_subs}

        # Buscar contratos locais ativos
        local_resp = sb.table("asaas_contratos").select(
            "id, customer_id, customer_name, value, status"
        ).eq("agent_id", AGENT_ID).eq("status", "ACTIVE").execute()

        local_contracts = local_resp.data or []
        local_map = {c["id"]: c for c in local_contracts}

        logger.info(
            "[RECONCILIAR CONTRATOS] Local: %d contratos ativos",
            len(local_contracts),
        )

        # Comparar: Asaas → Local
        now = datetime.utcnow().isoformat()
        for sub_id, sub in asaas_map.items():
            try:
                local = local_map.get(sub_id)

                if not local:
                    customer_name = await resolve_customer_name(
                        supabase, sub["customer"], None, AGENT_ID,
                    )
                    sb.table("asaas_contratos").upsert({
                        "id": sub_id,
                        "agent_id": AGENT_ID,
                        "customer_id": sub["customer"],
                        "customer_name": customer_name,
                        "value": sub["value"],
                        "status": sub["status"],
                        "cycle": sub.get("cycle", "MONTHLY"),
                        "next_due_date": sub.get("nextDueDate"),
                        "description": sub.get("description"),
                        "billing_type": sub.get("billingType"),
                        "updated_at": now,
                    }, on_conflict="id").execute()

                    stats["inserted"] += 1
                    divergencias.append(
                        f"INSERIDO: {sub_id} | {customer_name} | R${sub['value']}"
                    )
                else:
                    changes = {}
                    local_value = float(local.get("value") or 0)
                    asaas_value = float(sub.get("value") or 0)

                    if abs(local_value - asaas_value) > 0.01:
                        changes["value"] = asaas_value
                        divergencias.append(
                            f"VALOR: {sub_id} | {local.get('customer_name')} | "
                            f"R${local_value} → R${asaas_value}"
                        )

                    if changes:
                        changes["updated_at"] = now
                        sb.table("asaas_contratos").update(
                            changes
                        ).eq("id", sub_id).execute()
                        stats["updated"] += 1
                    else:
                        stats["unchanged"] += 1

            except Exception as e:
                logger.error(
                    "[RECONCILIAR CONTRATOS] Erro em %s: %s", sub_id, e
                )
                stats["errors"] += 1

        # Detectar cancelados (no banco mas não no Asaas)
        for sub_id, local in local_map.items():
            if sub_id not in asaas_map:
                try:
                    sb.table("asaas_contratos").update({
                        "status": "INACTIVE",
                        "updated_at": now,
                    }).eq("id", sub_id).execute()
                    stats["inactivated"] += 1
                    divergencias.append(
                        f"INATIVADO: {sub_id} | {local.get('customer_name')} | "
                        f"R${local.get('value')}"
                    )
                except Exception as e:
                    logger.error(
                        "[RECONCILIAR CONTRATOS] Erro ao inativar %s: %s",
                        sub_id, e,
                    )
                    stats["errors"] += 1

        logger.info(
            "[RECONCILIAR CONTRATOS] Concluido: "
            "inserted=%d updated=%d inactivated=%d unchanged=%d errors=%d",
            stats["inserted"], stats["updated"], stats["inactivated"],
            stats["unchanged"], stats["errors"],
        )
        for d in divergencias:
            logger.info("[RECONCILIAR CONTRATOS] %s", d)

        return {"status": "completed", "stats": stats, "divergencias": divergencias}

    finally:
        await redis.client.delete(CONTRACT_RECONCILIATION_LOCK_KEY)


async def run_contract_reconciliation_job() -> Dict[str, Any]:
    """Entry point para o scheduler / execucao manual."""
    logger.info("[RECONCILIAR CONTRATOS] Executando job...")
    return await reconcile_contracts()


async def is_contract_reconciliation_running() -> bool:
    """Verifica se o job está em execução."""
    redis = await get_redis_service()
    return await redis.client.exists(CONTRACT_RECONCILIATION_LOCK_KEY) > 0
