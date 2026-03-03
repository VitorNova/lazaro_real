"""
Servico de sincronizacao de contratos/assinaturas Asaas.

Responsavel por:
- Sincronizar contratos na tabela asaas_contratos
- Processar delecao de contratos (soft delete)

Extraido de: app/webhooks/pagamentos.py (Fase 3.4)
"""

import logging
from datetime import datetime
from typing import Any, Dict

from app.services.gateway_pagamento import AsaasService
from app.domain.billing.services.customer_sync_service import (
    sincronizar_cliente,
    get_cached_customer,
    resolve_customer_name,
)

logger = logging.getLogger(__name__)


async def sincronizar_contrato(
    supabase: Any,
    subscription: Dict[str, Any],
    agent_id: str,
) -> None:
    """
    Sincroniza contrato/assinatura na tabela asaas_contratos.

    Campos: id, customer_id, customer_name, value, status, cycle,
            next_due_date, description, billing_type
    """
    subscription_id = subscription.get("id")
    customer_id = subscription.get("customer")

    if not subscription_id:
        logger.warning("[SINCRONIZAR CONTRATO] subscription_id ausente")
        return

    try:
        # ========================================================================
        # OTIMIZACAO: CACHE-FIRST, API COMO FALLBACK
        # ========================================================================
        # Verifica se o cliente ja esta cacheado localmente com dados frescos.
        # Evita chamadas redundantes a API do Asaas em processamento em lote.
        # Se cache miss ou stale, busca via API e sincroniza.
        # ========================================================================

        customer_name = "Desconhecido"

        if customer_id:
            # 1. Verificar cache local primeiro (TTL: 5 minutos)
            cached_customer = await get_cached_customer(supabase, customer_id, agent_id)

            if cached_customer:
                # Cache hit - usar dados do cache
                customer_name = cached_customer.get("name", "Desconhecido")
                logger.debug(
                    "[SINCRONIZAR CONTRATO] Cliente %s obtido do cache: %s",
                    customer_id,
                    customer_name
                )
            else:
                # Cache miss ou stale - buscar via API
                logger.debug(
                    "[SINCRONIZAR CONTRATO] Cache miss para cliente %s, buscando via API",
                    customer_id
                )

                # Buscar API key do agente
                try:
                    result = (
                        supabase.client
                        .table("agents")
                        .select("asaas_api_key")
                        .eq("id", agent_id)
                        .maybe_single()
                        .execute()
                    )

                    if result.data and result.data.get("asaas_api_key"):
                        asaas_api_key = result.data["asaas_api_key"]
                        asaas = AsaasService(api_key=asaas_api_key)

                        # Buscar dados completos do cliente via API Asaas
                        customer_from_api = await asaas.get_customer(customer_id)

                        if customer_from_api:
                            # Sincronizar cliente em asaas_clientes
                            await sincronizar_cliente(supabase, customer_from_api, agent_id)

                            # Usar nome do cliente da API
                            customer_name = customer_from_api.get("name", "Desconhecido")

                            logger.info(
                                "[SINCRONIZAR CONTRATO] Cliente %s sincronizado via API: %s",
                                customer_id,
                                customer_name
                            )
                        else:
                            logger.warning(
                                "[SINCRONIZAR CONTRATO] Cliente %s nao encontrado na API Asaas",
                                customer_id
                            )

                    else:
                        logger.warning(
                            "[SINCRONIZAR CONTRATO] Agent %s nao tem asaas_api_key configurada",
                            agent_id
                        )

                except Exception as e:
                    logger.error(
                        "[SINCRONIZAR CONTRATO] Erro ao sincronizar cliente %s via API: %s",
                        customer_id,
                        e
                    )
                    # Continua o processamento mesmo se falhar a sincronizacao do cliente

        # Fallback 1: Se nao conseguiu nome via API, buscar do cache local
        if customer_name == "Desconhecido" and customer_id:
            try:
                existing = (
                    supabase.client
                    .table("asaas_clientes")
                    .select("name")
                    .eq("id", customer_id)
                    .maybe_single()
                    .execute()
                )
                if existing.data and existing.data.get("name"):
                    customer_name = existing.data["name"]
                    logger.debug(
                        "[SINCRONIZAR CONTRATO] Nome do cliente obtido do cache local: %s",
                        customer_name
                    )
            except Exception:
                pass

        # Fallback 2: Se nao encontrou, tenta buscar de outro contrato do mesmo cliente
        if customer_name == "Desconhecido" and customer_id:
            try:
                existing = (
                    supabase.client
                    .table("asaas_contratos")
                    .select("customer_name")
                    .eq("customer_id", customer_id)
                    .neq("customer_name", "Desconhecido")
                    .limit(1)
                    .maybe_single()
                    .execute()
                )
                if existing.data and existing.data.get("customer_name"):
                    customer_name = existing.data["customer_name"]
                    logger.debug(
                        "[SINCRONIZAR CONTRATO] Nome do cliente obtido de outro contrato: %s",
                        customer_name
                    )
            except Exception:
                pass

        # Validacao final: usar funcao utilitaria para resolver nome
        customer_name = await resolve_customer_name(
            supabase, customer_id, customer_name, agent_id
        )

        now = datetime.utcnow().isoformat()

        record = {
            "id": subscription_id,
            "agent_id": agent_id,
            "customer_id": customer_id,
            "customer_name": customer_name,
            "value": subscription.get("value"),
            "status": subscription.get("status"),
            "cycle": subscription.get("cycle"),
            "next_due_date": subscription.get("nextDueDate"),
            "description": subscription.get("description"),
            "billing_type": subscription.get("billingType"),
            "updated_at": now,
            "deleted_at": None,
            "deleted_from_asaas": False,
        }

        supabase.client.table("asaas_contratos").upsert(
            record,
            on_conflict="id"
        ).execute()

        logger.info(
            "[SINCRONIZAR CONTRATO] Contrato %s sincronizado: R$ %.2f (%s)",
            subscription_id,
            subscription.get("value", 0),
            subscription.get("status")
        )

    except Exception as e:
        logger.error("[SINCRONIZAR CONTRATO] Erro ao sincronizar contrato %s: %s", subscription_id, e)


async def processar_contrato_deletado(
    supabase: Any,
    subscription: Dict[str, Any],
    agent_id: str,
) -> None:
    """
    Processa SUBSCRIPTION_DELETED - soft delete do contrato.

    Marca status = INACTIVE e deleted_at = now.
    """
    subscription_id = subscription.get("id")

    if not subscription_id:
        logger.warning("[CONTRATO DELETADO] subscription_id ausente")
        return

    try:
        now = datetime.utcnow().isoformat()

        supabase.client.table("asaas_contratos").update({
            "status": "INACTIVE",
            "deleted_at": now,
            "deleted_from_asaas": True,
            "updated_at": now,
        }).eq("id", subscription_id).execute()

        logger.info("[CONTRATO DELETADO] Contrato %s marcado como INACTIVE", subscription_id)

    except Exception as e:
        logger.error("[CONTRATO DELETADO] Erro ao deletar contrato %s: %s", subscription_id, e)
