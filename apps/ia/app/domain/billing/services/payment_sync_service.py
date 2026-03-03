"""
Servico de sincronizacao de cobrancas/pagamentos Asaas.

Responsavel por:
- Sincronizar cobrancas na tabela asaas_cobrancas
- Processar delecao de cobrancas (soft delete)

Extraido de: app/webhooks/pagamentos.py (Fase 3.6)
"""

import logging
from datetime import datetime, date
from typing import Any, Dict

from app.services.gateway_pagamento import AsaasService
from app.domain.billing.services.customer_sync_service import (
    sincronizar_cliente,
    get_cached_customer,
    resolve_customer_name,
)

logger = logging.getLogger(__name__)


async def sincronizar_cobranca(
    supabase: Any,
    payment: Dict[str, Any],
    agent_id: str,
) -> None:
    """
    Sincroniza cobranca na tabela asaas_cobrancas.

    IMPORTANTE: Antes de sincronizar a cobranca, SEMPRE busca dados atualizados
    do cliente via API do Asaas e sincroniza em asaas_clientes.
    A API do Asaas e a fonte da verdade para dados de clientes.

    Campos: id, customer_id, customer_name, subscription_id, value, net_value,
            status, billing_type, due_date, payment_date, date_created,
            description, invoice_url, bank_slip_url, dias_atraso
    """
    payment_id = payment.get("id")
    customer_id = payment.get("customer")
    subscription_id = payment.get("subscription")

    if not payment_id:
        logger.warning("[SINCRONIZAR COBRANCA] payment_id ausente")
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
                    "[SINCRONIZAR COBRANCA] Cliente %s obtido do cache: %s",
                    customer_id,
                    customer_name
                )
            else:
                # Cache miss ou stale - buscar via API
                logger.debug(
                    "[SINCRONIZAR COBRANCA] Cache miss para cliente %s, buscando via API",
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
                                "[SINCRONIZAR COBRANCA] Cliente %s sincronizado via API: %s",
                                customer_id,
                                customer_name
                            )
                        else:
                            logger.warning(
                                "[SINCRONIZAR COBRANCA] Cliente %s nao encontrado na API Asaas",
                                customer_id
                            )

                    else:
                        logger.warning(
                            "[SINCRONIZAR COBRANCA] Agent %s nao tem asaas_api_key configurada",
                            agent_id
                        )

                except Exception as e:
                    logger.error(
                        "[SINCRONIZAR COBRANCA] Erro ao sincronizar cliente %s via API: %s",
                        customer_id,
                        e
                    )
                    # Continua o processamento mesmo se falhar a sincronizacao do cliente

        # Fallback: Se nao conseguiu nome via API, buscar do cache local
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
                        "[SINCRONIZAR COBRANCA] Nome do cliente obtido do cache local: %s",
                        customer_name
                    )
            except Exception:
                pass

        # Fallback: Buscar de outra cobranca do mesmo cliente
        if customer_name == "Desconhecido" and customer_id:
            try:
                existing = (
                    supabase.client
                    .table("asaas_cobrancas")
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
                        "[SINCRONIZAR COBRANCA] Nome do cliente obtido de outra cobranca: %s",
                        customer_name
                    )
            except Exception:
                pass

        # Validacao final: usar funcao utilitaria para resolver nome
        customer_name = await resolve_customer_name(
            supabase, customer_id, customer_name, agent_id
        )

        # Calcular dias de atraso se vencido
        dias_atraso = 0
        status = payment.get("status", "")
        due_date = payment.get("dueDate")

        if status == "OVERDUE" and due_date:
            try:
                hoje = date.today()
                venc = datetime.strptime(due_date, "%Y-%m-%d").date()
                diff = (hoje - venc).days
                dias_atraso = diff if diff > 0 else 0
            except Exception:
                pass

        now = datetime.utcnow().isoformat()

        record = {
            "id": payment_id,
            "agent_id": agent_id,
            "customer_id": customer_id,
            "customer_name": customer_name,
            "subscription_id": subscription_id,
            "value": payment.get("value"),
            "net_value": payment.get("netValue"),
            "status": status,
            "billing_type": payment.get("billingType"),
            "due_date": due_date,
            "payment_date": payment.get("paymentDate"),
            "date_created": payment.get("dateCreated"),
            "description": payment.get("description"),
            "invoice_url": payment.get("invoiceUrl"),
            "bank_slip_url": payment.get("bankSlipUrl"),
            "dias_atraso": dias_atraso,
            "updated_at": now,
            "deleted_at": None,
            "deleted_from_asaas": False,
        }

        supabase.client.table("asaas_cobrancas").upsert(
            record,
            on_conflict="id"
        ).execute()

        logger.info(
            "[SINCRONIZAR COBRANCA] Cobranca %s sincronizada: R$ %.2f | %s | venc: %s | cliente: %s",
            payment_id,
            payment.get("value", 0),
            status,
            due_date,
            customer_name
        )

    except Exception as e:
        logger.error("[SINCRONIZAR COBRANCA] Erro ao sincronizar cobranca %s: %s", payment_id, e)


async def processar_cobranca_deletada(
    supabase: Any,
    payment: Dict[str, Any],
    agent_id: str,
) -> None:
    """
    Processa PAYMENT_DELETED - soft delete da cobranca.

    Marca a cobranca como deletada em asaas_cobrancas.
    """
    payment_id = payment.get("id")

    if not payment_id:
        logger.warning("[COBRANCA DELETADA] payment_id ausente")
        return

    try:
        now = datetime.utcnow().isoformat()

        supabase.client.table("asaas_cobrancas").update({
            "deleted_at": now,
            "deleted_from_asaas": True,
            "updated_at": now,
        }).eq("id", payment_id).execute()

        logger.info("[COBRANCA DELETADA] Cobranca %s marcada como deletada", payment_id)

        # Tambem atualiza billing_notifications se existir
        try:
            supabase.client.table("billing_notifications").update({
                "status": "deleted",
                "updated_at": now,
            }).eq("payment_id", payment_id).execute()
        except Exception as e:
            logger.debug("[COBRANCA DELETADA] Erro ao atualizar billing_notifications: %s", e)

    except Exception as e:
        logger.error("[COBRANCA DELETADA] Erro ao deletar cobranca %s: %s", payment_id, e)
