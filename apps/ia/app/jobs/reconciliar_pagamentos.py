# ╔════════════════════════════════════════════════════════════╗
# ║  RECONCILIAR — Sincronizar status de pagamentos            ║
# ╚════════════════════════════════════════════════════════════╝
"""
Billing Reconciliation Job - Sincronizacao diaria Asaas -> Supabase.

Objetivo:
- Sincronizar asaas_cobrancas com API Asaas (fonte da verdade)
- Detectar e corrigir divergencias (status diferente, cobranca deletada)
- Logar alertas de divergencias para auditoria

Frequencia: 1x ao dia, 6h BRT (antes do job de cobranca)

Autor: Executor
Data: 2026-02-19
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.services.gateway_pagamento import AsaasService, create_asaas_service
from app.services.redis import get_redis_service
from app.services.supabase import get_supabase_service
from app.core.utils.dias_uteis import get_today_brasilia
from app.domain.billing.services.confirmacao_pagamento import enviar_confirmacao_pagamento

logger = logging.getLogger(__name__)

# ============================================================================
# CUSTOMER NAME RESOLUTION (FIX: API /payments não retorna customerName)
# ============================================================================

INVALID_NAMES = {"", "Sem nome", "Desconhecido", "Cliente", "Cliente Asaas"}


def _is_valid_customer_name(name: Optional[str]) -> bool:
    """Verifica se o nome do cliente é válido (não vazio/placeholder)."""
    if not name:
        return False
    return name.strip() not in INVALID_NAMES


async def _resolve_customer_name(
    supabase,
    asaas_service: Optional[AsaasService],
    payment_id: str,
    customer_id: str,
    existing_name: str = "",
    api_customer_name: str = "",
) -> Optional[str]:
    """
    Resolve o nome do cliente para uma cobrança.

    Ordem de prioridade:
    1. Nome da API (se válido)
    2. Nome existente no banco (preservar valor anterior)
    3. Nome na tabela de clientes (asaas_clientes)
    4. Busca na API do Asaas (/customers/{id})

    Retorna None se não conseguir resolver (para não sobrescrever valor existente).
    """
    # 1. Se API retornou nome válido, usar
    if _is_valid_customer_name(api_customer_name):
        return api_customer_name

    # 2. Se registro existente tem nome válido, preservar
    if _is_valid_customer_name(existing_name):
        return existing_name

    if not customer_id:
        return None

    # 3. Tentar da tabela de clientes
    try:
        cliente = (
            supabase.client.table("asaas_clientes")
            .select("name")
            .eq("id", customer_id)
            .maybe_single()
            .execute()
        )
        if cliente.data and _is_valid_customer_name(cliente.data.get("name")):
            return cliente.data["name"]
    except Exception:
        pass

    # 4. Último recurso: API do Asaas
    if asaas_service:
        try:
            customer_from_api = await asaas_service.get_customer(customer_id)
            if customer_from_api and _is_valid_customer_name(customer_from_api.get("name")):
                return customer_from_api["name"]
        except Exception:
            pass

    # Não conseguiu resolver - retorna None para NÃO sobrescrever
    return None

# Lock distribuído via Redis (TTL: 2 horas)
RECONCILIATION_JOB_LOCK_KEY = "lock:billing_reconciliation:global"
RECONCILIATION_JOB_LOCK_TTL = 7200  # 2 horas





async def fetch_all_payments_from_asaas(
    asaas_service,
    status: str,
    start_date: datetime,
    end_date: datetime,
) -> List[Dict[str, Any]]:
    """
    Busca todos os pagamentos da API Asaas em um periodo.

    Args:
        asaas_service: Instancia do AsaasService
        status: Status do pagamento (PENDING, OVERDUE, RECEIVED, CONFIRMED)
        start_date: Data inicio do periodo
        end_date: Data fim do periodo

    Returns:
        Lista de pagamentos
    """
    try:
        params = {
            "status": status,
            "dueDate[ge]": start_date.strftime("%Y-%m-%d"),
            "dueDate[le]": end_date.strftime("%Y-%m-%d"),
            "offset": 0,
            "limit": 100,
        }

        all_payments = []
        page_count = 0
        max_pages = 20  # Max 2000 payments por status

        while True:
            response = await asaas_service.list_payments(**params)
            data = response.get("data", [])
            all_payments.extend(data)

            has_more = response.get("hasMore", False)
            if not has_more:
                break

            params["offset"] += params["limit"]
            page_count += 1

            if page_count >= max_pages:
                logger.warning(f"[RECONCILIAR PAGAMENTOS] Limite de paginacao atingido ({max_pages} paginas) para {status}")
                break

        logger.info(f"[RECONCILIAR PAGAMENTOS] Buscou {len(all_payments)} pagamentos {status} da API Asaas")
        return all_payments

    except Exception as e:
        logger.error(f"[RECONCILIAR PAGAMENTOS] Erro ao buscar {status} da API Asaas: {e}")
        return []


async def upsert_payment_to_cache(
    agent_id: str,
    payment: Dict[str, Any],
    source: str,
    asaas_service: Optional[AsaasService] = None,
) -> Optional[str]:
    """
    Insere ou atualiza cobranca no cache.
    Retorna descricao da divergencia se houver, None se igual.

    IMPORTANTE: Preserva customer_name existente se API não retornar nome válido.
    A API /payments não retorna customerName, então precisamos resolver de outras fontes.

    Args:
        agent_id: ID do agente
        payment: Dados do payment da API Asaas
        source: Fonte da sincronizacao ('reconciliation', 'api_sync', etc)
        asaas_service: Serviço Asaas para buscar cliente (opcional)

    Returns:
        Descricao da divergencia se detectada, None caso contrario
    """
    supabase = get_supabase_service()
    now = datetime.utcnow().isoformat()
    payment_id = payment.get("id", "")
    customer_id = payment.get("customer", "")

    try:
        # Buscar existente no cache (incluindo customer_name e ia_* para preservar/verificar)
        result = (
            supabase.client.table("asaas_cobrancas")
            .select("id, status, value, due_date, customer_name, ia_cobrou, ia_recebeu")
            .eq("id", payment_id)
            .eq("agent_id", agent_id)
            .execute()
        )

        divergence = None
        existing = result.data[0] if result.data else None
        existing_name = existing.get("customer_name", "") if existing else ""

        if existing:
            # Detectar divergencias
            if existing.get("status") != payment.get("status"):
                divergence = f"Status: {existing.get('status')} -> {payment.get('status')}"
            elif str(existing.get("value")) != str(payment.get("value")):
                divergence = f"Value: {existing.get('value')} -> {payment.get('value')}"
            elif str(existing.get("due_date")) != payment.get("dueDate"):
                divergence = f"DueDate: {existing.get('due_date')} -> {payment.get('dueDate')}"

        # Resolver nome do cliente (FIX: API /payments não retorna customerName)
        api_customer_name = payment.get("customerName", "")
        resolved_name = await _resolve_customer_name(
            supabase,
            asaas_service,
            payment_id,
            customer_id,
            existing_name,
            api_customer_name,
        )

        # Montar dados para UPSERT
        data = {
            "id": payment_id,
            "agent_id": agent_id,
            "customer_id": customer_id,
            "value": payment.get("value", 0.0),
            "status": payment.get("status", ""),
            "billing_type": payment.get("billingType", ""),
            "due_date": payment.get("dueDate"),
            "invoice_url": payment.get("invoiceUrl"),
            "bank_slip_url": payment.get("bankSlipUrl"),
            "subscription_id": payment.get("subscription"),
            "last_synced_at": now,
            "sync_source": source,
            "updated_at": now,
        }

        # PROTEÇÃO: Só incluir customer_name se tiver nome válido
        # Se resolved_name é None, NÃO sobrescrever o valor existente
        if resolved_name is not None:
            data["customer_name"] = resolved_name

        supabase.client.table("asaas_cobrancas").upsert(data, on_conflict="id").execute()

        # SAFETY NET: Marcar ia_recebeu se IA cobrou e pagamento foi confirmado
        # Isso garante que mesmo se o webhook falhar, a reconciliação corrige
        new_status = payment.get("status", "")
        if new_status in ("RECEIVED", "CONFIRMED", "RECEIVED_IN_CASH"):
            if existing:
                ia_cobrou = existing.get("ia_cobrou", False)
                ia_recebeu = existing.get("ia_recebeu", False)

                if ia_cobrou and not ia_recebeu:
                    # Buscar último step da notificação
                    try:
                        notif_res = (
                            supabase.client.table("billing_notifications")
                            .select("notification_type, days_from_due")
                            .eq("payment_id", payment_id)
                            .eq("status", "sent")
                            .order("sent_at", desc=True)
                            .limit(1)
                            .execute()
                        )

                        # FIX 2026-03-09: Enviar mensagem de confirmação ANTES de marcar ia_recebeu
                        # Bug: reconciliação marcava ia_recebeu=True mas não enviava mensagem
                        # Agora envia mensagem igual ao webhook PAYMENT_RECEIVED
                        try:
                            # Buscar dados do agente para enviar mensagem
                            agent_res = (
                                supabase.client.table("agents")
                                .select("id, name, uazapi_base_url, uazapi_token, table_leads, table_messages")
                                .eq("id", agent_id)
                                .limit(1)
                                .execute()
                            )

                            if agent_res.data:
                                agent_data = agent_res.data[0]
                                # Montar payment dict no formato esperado pela função
                                payment_for_msg = {
                                    "id": payment_id,
                                    "customer": customer_id,
                                    "value": payment.get("value", 0),
                                }

                                msg_result = await enviar_confirmacao_pagamento(
                                    supabase=supabase,
                                    agent=agent_data,
                                    payment=payment_for_msg,
                                )

                                if msg_result.get("success"):
                                    logger.info(f"[RECONCILIAR PAGAMENTOS] [SAFETY NET] Mensagem de confirmação enviada para {payment_id}")
                                else:
                                    logger.warning(f"[RECONCILIAR PAGAMENTOS] [SAFETY NET] Falha ao enviar mensagem: {msg_result.get('reason')}")
                            else:
                                logger.warning(f"[RECONCILIAR PAGAMENTOS] [SAFETY NET] Agente não encontrado: {agent_id}")
                        except Exception as msg_error:
                            logger.warning(f"[RECONCILIAR PAGAMENTOS] [SAFETY NET] Erro ao enviar mensagem de confirmação: {msg_error}")

                        ia_update = {
                            "ia_recebeu": True,
                            "ia_recebeu_at": now,
                        }
                        if notif_res.data:
                            ia_update["ia_recebeu_step"] = notif_res.data[0].get("notification_type")
                            ia_update["ia_recebeu_days_from_due"] = notif_res.data[0].get("days_from_due")

                        supabase.client.table("asaas_cobrancas").update(ia_update).eq("id", payment_id).execute()
                        logger.info(f"[RECONCILIAR PAGAMENTOS] [SAFETY NET] ia_recebeu marcado para {payment_id}")
                    except Exception as e:
                        logger.warning(f"[RECONCILIAR PAGAMENTOS] Erro ao marcar ia_recebeu (safety net) para {payment_id}: {e}")

        return divergence

    except Exception as e:
        logger.error(f"[RECONCILIAR PAGAMENTOS] Erro ao upsert payment {payment_id} no cache: {e}")
        return None


async def reconcile_agent(agent: Dict[str, Any]) -> Dict[str, int]:
    """
    Reconcilia cobrancas de um agente especifico.

    Args:
        agent: Dados do agente (id, name, asaas_api_key)

    Returns:
        Estatisticas da reconciliacao
    """
    stats = {
        "payments_synced": 0,
        "divergences_fixed": 0,
        "errors": 0,
    }

    agent_id = agent.get("id", "")
    agent_name = agent.get("name", "unknown")
    asaas_api_key = agent.get("asaas_api_key")

    if not asaas_api_key:
        logger.warning(f"[RECONCILIAR PAGAMENTOS] Agente {agent_name} sem asaas_api_key, pulando reconciliacao")
        return stats

    logger.info(f"[RECONCILIAR PAGAMENTOS] Reconciliando agente: {agent_name} ({agent_id[:8]}...)")

    try:
        asaas_service = create_asaas_service(api_key=asaas_api_key)

        # Buscar desde a primeira cobrança até fim do mês atual
        # (espelho completo do Asaas, não apenas janela parcial)
        hoje = get_today_brasilia()
        start_date = hoje.replace(year=2025, month=1, day=1)
        import calendar
        last_day = calendar.monthrange(hoje.year, hoje.month)[1]
        end_date = hoje.replace(day=last_day)

        # Buscar todos os status relevantes
        statuses = ["PENDING", "OVERDUE", "RECEIVED", "CONFIRMED"]

        for status in statuses:
            payments = await fetch_all_payments_from_asaas(
                asaas_service, status, start_date, end_date
            )

            for payment in payments:
                try:
                    divergence = await upsert_payment_to_cache(
                        agent_id=agent_id,
                        payment=payment,
                        source="reconciliation",
                        asaas_service=asaas_service,
                    )

                    if divergence:
                        stats["divergences_fixed"] += 1
                        logger.info(f"[RECONCILIAR PAGAMENTOS] Divergencia corrigida: {payment.get('id', 'unknown')} - {divergence}")

                    stats["payments_synced"] += 1

                except Exception as e:
                    logger.error(f"[RECONCILIAR PAGAMENTOS] Erro ao processar payment {payment.get('id', 'unknown')}: {e}")
                    stats["errors"] += 1

        logger.info(
            f"Agente {agent_name}: {stats['payments_synced']} synced, "
            f"{stats['divergences_fixed']} divergencias, {stats['errors']} erros"
        )

        # Reconciliar itens deletados no Asaas (amostragem rotativa)
        try:
            from app.domain.billing.services.deletion_reconciler import reconcile_deletions
            from app.services.supabase import get_supabase_service
            supabase = get_supabase_service()
            del_stats = await reconcile_deletions(supabase, asaas_service, agent_id)
            total_del = del_stats.get("payments_deleted", 0) + del_stats.get("contracts_deleted", 0) + del_stats.get("customers_deleted", 0)
            if total_del > 0:
                logger.info(f"Agente {agent_name}: {total_del} itens deletados detectados na reconciliação")
        except Exception as e:
            logger.warning(f"[RECONCILIAR PAGAMENTOS] Erro na reconciliação de deletados: {e}")

    except Exception as e:
        logger.error(f"[RECONCILIAR PAGAMENTOS] Erro ao reconciliar agente {agent_name}: {e}")
        stats["errors"] += 1

    return stats


async def reconcile_billing_data() -> Dict[str, Any]:
    """
    Job de reconciliacao: sincroniza asaas_cobrancas com API Asaas.
    Roda 1x/dia as 6h BRT.

    Returns:
        Estatisticas do processamento
    """
    redis = await get_redis_service()

    # Tenta adquirir lock distribuído
    lock_acquired = await redis.client.set(
        RECONCILIATION_JOB_LOCK_KEY, "1", nx=True, ex=RECONCILIATION_JOB_LOCK_TTL
    )
    if not lock_acquired:
        logger.warning("[RECONCILIAR PAGAMENTOS] Job ja esta em execucao em outra instancia, pulando...")
        return {"status": "skipped", "reason": "already_running"}

    logger.info("[RECONCILIAR PAGAMENTOS] Iniciando reconciliacao de cobrancas...")

    total_stats = {
        "agents_processed": 0,
        "payments_synced": 0,
        "divergences_fixed": 0,
        "errors": 0,
    }

    try:
        # Buscar agentes com Asaas configurado
        supabase = get_supabase_service()
        response = (
            supabase.client.table("agents")
            .select("id, name, asaas_api_key")
            .eq("status", "active")
            .not_.is_("asaas_api_key", "null")
            .neq("asaas_api_key", "")
            .execute()
        )

        agents = response.data or []
        logger.info(f"[RECONCILIAR PAGAMENTOS] Encontrados {len(agents)} agentes com Asaas configurado")

        for agent in agents:
            agent_stats = await reconcile_agent(agent)
            total_stats["payments_synced"] += agent_stats["payments_synced"]
            total_stats["divergences_fixed"] += agent_stats["divergences_fixed"]
            total_stats["errors"] += agent_stats["errors"]
            total_stats["agents_processed"] += 1

            # Pausa entre agentes para nao sobrecarregar API
            await asyncio.sleep(2)

        logger.info(
            f"Reconciliacao concluida: {total_stats['agents_processed']} agentes, "
            f"{total_stats['payments_synced']} payments, "
            f"{total_stats['divergences_fixed']} divergencias corrigidas, "
            f"{total_stats['errors']} erros"
        )

        return {"status": "completed", "stats": total_stats}

    except Exception as e:
        logger.error(f"[RECONCILIAR PAGAMENTOS] Erro no processamento de reconciliacao: {e}")
        return {"status": "error", "error": str(e)}

    finally:
        # Libera lock distribuído
        await redis.client.delete(RECONCILIATION_JOB_LOCK_KEY)


async def run_billing_reconciliation_job() -> Dict[str, Any]:
    """Entry point para o scheduler / execucao manual."""
    logger.info("[RECONCILIAR PAGAMENTOS] Executando billing reconciliation job...")
    return await reconcile_billing_data()


async def is_billing_reconciliation_running() -> bool:
    """Verifica se o job esta rodando (via lock Redis)."""
    redis = await get_redis_service()
    return await redis.client.exists(RECONCILIATION_JOB_LOCK_KEY) > 0


async def _force_run_billing_reconciliation() -> Dict[str, Any]:
    """
    Versao forcada do job - executa imediatamente.
    APENAS PARA DEBUG/TESTES.
    """
    logger.info("[RECONCILIAR PAGAMENTOS] === EXECUCAO FORCADA (reconciliacao) ===")
    return await reconcile_billing_data()
