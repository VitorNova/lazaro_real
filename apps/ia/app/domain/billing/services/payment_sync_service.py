"""
Servico de sincronizacao de cobrancas/pagamentos Asaas.

Responsavel por:
- Sincronizar cobrancas na tabela asaas_cobrancas
- Processar delecao de cobrancas (soft delete)

Extraido de: app/webhooks/pagamentos.py (Fase 3.6)
Refatorado para usar AsaasPaymentsRepository (Fase 9.12)
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
from app.integrations.supabase.repositories import (
    asaas_payments_repository,
    asaas_customers_repository,
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

    if not payment_id:
        logger.warning("[SINCRONIZAR COBRANCA] payment_id ausente")
        return

    try:
        # ========================================================================
        # OTIMIZACAO: CACHE-FIRST, API COMO FALLBACK
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

        # Fallback: Se nao conseguiu nome via API, buscar do cache local via repository
        if customer_name == "Desconhecido" and customer_id:
            try:
                name = await asaas_customers_repository.find_name(
                    customer_id=customer_id,
                    agent_id=agent_id,
                )
                if name:
                    customer_name = name
                    logger.debug(
                        "[SINCRONIZAR COBRANCA] Nome do cliente obtido do cache local: %s",
                        customer_name
                    )
            except Exception:
                pass

        # Fallback: Buscar de outra cobranca do mesmo cliente via repository
        if customer_name == "Desconhecido" and customer_id:
            try:
                name = await asaas_payments_repository.find_name_by_customer_id(
                    customer_id=customer_id,
                    agent_id=agent_id,
                )
                if name:
                    customer_name = name
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

        # Usar repositorio para upsert (calcula dias_atraso automaticamente)
        await asaas_payments_repository.upsert(
            payment_id=payment_id,
            agent_id=agent_id,
            data=payment,
            customer_name=customer_name,
        )

        logger.info(
            "[SINCRONIZAR COBRANCA] Cobranca %s sincronizada: R$ %.2f | %s | venc: %s | cliente: %s",
            payment_id,
            payment.get("value", 0),
            payment.get("status", ""),
            payment.get("dueDate"),
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
        # Usar repositorio para soft delete
        await asaas_payments_repository.soft_delete(payment_id)

        logger.info("[COBRANCA DELETADA] Cobranca %s marcada como deletada", payment_id)

        # Tambem atualiza billing_notifications se existir
        try:
            now = datetime.utcnow().isoformat()
            supabase.client.table("billing_notifications").update({
                "status": "deleted",
                "updated_at": now,
            }).eq("payment_id", payment_id).execute()
        except Exception as e:
            logger.debug("[COBRANCA DELETADA] Erro ao atualizar billing_notifications: %s", e)

    except Exception as e:
        logger.error("[COBRANCA DELETADA] Erro ao deletar cobranca %s: %s", payment_id, e)
