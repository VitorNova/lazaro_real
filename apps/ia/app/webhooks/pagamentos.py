"""
Asaas Webhook Handler.

Recebe notificacoes de pagamento do Asaas e atualiza o sistema.

Eventos tratados:

CUSTOMER:
- CUSTOMER_CREATED         - Cliente criado (sincroniza em asaas_clientes + processa PDF)
- CUSTOMER_UPDATED         - Cliente atualizado (sincroniza em asaas_clientes)
- CUSTOMER_DELETED         - Cliente removido (soft delete em asaas_clientes + contratos + cobrancas)

SUBSCRIPTION:
- SUBSCRIPTION_CREATED     - Assinatura criada (sincroniza em asaas_contratos + processa PDF)
- SUBSCRIPTION_UPDATED     - Assinatura atualizada (sincroniza em asaas_contratos)
- SUBSCRIPTION_DELETED     - Assinatura removida (soft delete em asaas_contratos)

PAYMENT - Criacao/Atualizacao:
- PAYMENT_CREATED          - Cobranca criada (sincroniza em asaas_cobrancas)
- PAYMENT_UPDATED          - Cobranca atualizada (sincroniza em asaas_cobrancas)
- PAYMENT_CONFIRMED        - Pagamento confirmado, saldo ainda nao disponivel (status -> CONFIRMED)
- PAYMENT_RECEIVED         - Pagamento recebido/pago, saldo disponivel (status -> RECEIVED, marca pago)
- PAYMENT_OVERDUE          - Cobranca vencida (status -> OVERDUE)
- PAYMENT_DELETED          - Cobranca removida (soft delete em asaas_cobrancas)
- PAYMENT_CHECKOUT_VIEWED  - Cliente visualizou link de pagamento (apenas log para analytics)

PAYMENT - Estornos e Chargebacks:
- PAYMENT_REFUNDED                      - Cobranca estornada (devolucao total)
- PAYMENT_PARTIALLY_REFUNDED            - Cobranca parcialmente estornada
- PAYMENT_CHARGEBACK_REQUESTED          - CRITICO: Chargeback solicitado pelo cliente
- PAYMENT_CHARGEBACK_DISPUTE            - Chargeback em processo de disputa
- PAYMENT_AWAITING_CHARGEBACK_REVERSAL  - Aguardando reversao de chargeback

PAYMENT - Outros:
- PAYMENT_RESTORED                      - Cobranca restaurada (ex: apos reversao chargeback)
- PAYMENT_RECEIVED_IN_CASH_UNDONE       - Confirmacao de dinheiro desfeita
- PAYMENT_ANTICIPATED                   - Cobranca antecipada
- PAYMENT_CREDIT_CARD_CAPTURE_REFUSED   - Captura do cartao recusada

Identificacao do agente:
- Via externalReference no formato "agentId:leadId"
- Fallback: busca na tabela asaas_cobrancas pelo payment.id
- Para eventos sem agentId identificavel: usa agent_id fixo do Lazaro

Idempotencia:
- Eventos processados sao registrados em asaas_webhook_events
- Eventos duplicados sao ignorados (retorna 200)

Sincronizacao:
- Todas as tabelas usam upsert (inserir se nao existe, atualizar se existe)
- Chaves: customer_id (asaas_clientes), subscription_id (asaas_contratos), payment_id (asaas_cobrancas)
"""

import asyncio
import base64
import json
import logging
from datetime import datetime
from dateutil.relativedelta import relativedelta
from functools import wraps
from typing import Any, Dict, List, Optional

import pymupdf
import google.generativeai as genai
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.services.gateway_pagamento import AsaasService
from app.services.supabase import get_supabase_service

logger = logging.getLogger(__name__)

router = APIRouter()

# Agent ID do Lazaro (fixo para CUSTOMER_CREATED)
LAZARO_AGENT_ID = "14e6e5ce-4627-4e38-aac8-f0191669ff53"

# Extensoes de arquivo suportadas para extracao de contratos
SUPPORTED_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png', '.gif', '.webp'}

# Mapeamento de extensao para MIME type
MIME_TYPES = {
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.gif': 'image/gif',
    '.webp': 'image/webp',
}


# ============================================================================
# RETRY DECORATOR COM BACKOFF EXPONENCIAL
# ============================================================================

def async_retry(max_retries: int = 3, initial_delay: float = 2.0, backoff_factor: float = 2.0):
    """
    Decorator para retry com backoff exponencial em funcoes async.

    Args:
        max_retries: Numero maximo de tentativas
        initial_delay: Delay inicial em segundos
        backoff_factor: Fator de multiplicacao do delay a cada retry
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            delay = initial_delay
            last_error = None
            for attempt in range(1, max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_retries:
                        logger.warning(
                            "[%s] Tentativa %d/%d falhou: %s. Retry em %.1fs...",
                            func.__name__, attempt, max_retries, e, delay
                        )
                        await asyncio.sleep(delay)
                        delay *= backoff_factor
                    else:
                        logger.error(
                            "[%s] Todas as %d tentativas falharam. Ultimo erro: %s",
                            func.__name__, max_retries, e
                        )
            raise last_error
        return wrapper
    return decorator


# ============================================================================
# WEBHOOK ENDPOINT
# ============================================================================

@router.post("/asaas")
async def asaas_webhook(request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
    """
    Webhook endpoint para notificacoes do Asaas.

    O Asaas espera resposta rapida (< 5s).
    Sempre retorna 200 para evitar reenvios.
    """
    try:
        body = await request.json()

        event_id: Optional[str] = body.get("id")
        event: Optional[str] = body.get("event")
        payment: Optional[Dict[str, Any]] = body.get("payment")
        customer: Optional[Dict[str, Any]] = body.get("customer")
        subscription: Optional[Dict[str, Any]] = body.get("subscription")

        # 1. Validar auth token (se configurado)
        expected_token = settings.asaas_webhook_token
        if expected_token:
            auth_token = request.headers.get("asaas-access-token")
            if auth_token != expected_token:
                logger.debug("[ASAAS WEBHOOK] Token invalido")
                return JSONResponse(status_code=401, content={"error": "Unauthorized"})

        if not event_id or not event:
            logger.debug("[ASAAS WEBHOOK] Payload sem event id ou type")
            return JSONResponse(status_code=400, content={"error": "Missing event id or type"})

        # 2. Extrair agentId e leadId do externalReference
        agent_id: Optional[str] = None
        lead_id: Optional[str] = None

        if payment and payment.get("externalReference"):
            parts = payment["externalReference"].split(":")
            agent_id = parts[0] if len(parts) > 0 else None
            lead_id = parts[1] if len(parts) > 1 else None

        # Fallback: buscar agent_id na tabela asaas_cobrancas
        supabase = get_supabase_service()

        if not agent_id and payment and payment.get("id"):
            try:
                result = (
                    supabase.client
                    .table("asaas_cobrancas")
                    .select("agent_id")
                    .eq("id", payment["id"])
                    .maybe_single()
                    .execute()
                )
                if result.data and result.data.get("agent_id"):
                    agent_id = result.data["agent_id"]
            except Exception as e:
                logger.debug("[ASAAS WEBHOOK] Erro ao buscar cobranca: %s", e)

        # Log do evento
        if payment:
            payment_id = payment.get("id", "?")
            value = payment.get("value", 0)
            logger.info("[ASAAS WEBHOOK] Evento: %s | Payment: %s | R$ %.2f", event, payment_id, value)
        elif customer:
            customer_id = customer.get("id", "?")
            customer_name = customer.get("name", "?")
            logger.info("[ASAAS WEBHOOK] Evento: %s | Customer: %s (%s)", event, customer_id, customer_name)
        elif subscription:
            subscription_id = subscription.get("id", "?")
            subscription_customer = subscription.get("customer", "?")
            subscription_value = subscription.get("value", 0)
            logger.info(
                "[ASAAS WEBHOOK] Evento: %s | Subscription: %s | Customer: %s | R$ %.2f",
                event, subscription_id, subscription_customer, subscription_value
            )
        else:
            logger.info("[ASAAS WEBHOOK] Evento: %s", event)

        if agent_id:
            logger.debug("[ASAAS WEBHOOK] Agente identificado: %s", agent_id)

        # 3. Verificar idempotencia
        try:
            existing = (
                supabase.client
                .table("asaas_webhook_events")
                .select("id")
                .eq("id", event_id)
                .maybe_single()
                .execute()
            )
            if existing.data:
                logger.debug("[ASAAS WEBHOOK] Evento duplicado ignorado: %s", event_id)
                return JSONResponse(status_code=200, content={"status": "already_processed"})
        except Exception as e:
            # Se tabela nao existir, segue sem idempotencia
            logger.debug("[ASAAS WEBHOOK] Aviso idempotencia: %s", e)

        # 4. Registrar evento
        try:
            supabase.client.table("asaas_webhook_events").insert({
                "id": event_id,
                "event": event,
                "payment_id": payment.get("id") if payment else None,
                "customer_id": customer.get("id") if customer else (subscription.get("customer") if subscription else None),
                "subscription_id": subscription.get("id") if subscription else None,
                "agent_id": agent_id or LAZARO_AGENT_ID,
                "payload": body,
                "processed_at": datetime.utcnow().isoformat(),
            }).execute()
        except Exception as e:
            logger.debug("[ASAAS WEBHOOK] Aviso ao registrar evento: %s", e)

        # 5. Processar por tipo de evento
        # ========================================================================
        # CUSTOMER EVENTS
        # ========================================================================
        if event == "CUSTOMER_CREATED" and customer:
            # Sincroniza cliente em asaas_clientes + processa PDF em background
            await _sincronizar_cliente(supabase, customer, agent_id or LAZARO_AGENT_ID)
            background_tasks.add_task(
                _processar_customer_created_background,
                customer_id=customer.get("id"),
                customer_name=customer.get("name"),
                agent_id=agent_id or LAZARO_AGENT_ID,
            )
            logger.info("[ASAAS WEBHOOK] CUSTOMER_CREATED sincronizado e PDF agendado: %s", customer.get("id"))

        elif event == "CUSTOMER_UPDATED" and customer:
            # Apenas sincroniza cliente em asaas_clientes
            await _sincronizar_cliente(supabase, customer, agent_id or LAZARO_AGENT_ID)
            logger.info("[ASAAS WEBHOOK] CUSTOMER_UPDATED sincronizado: %s", customer.get("id"))

        elif event == "CUSTOMER_DELETED" and customer:
            # Soft delete do cliente e dados relacionados
            await _processar_cliente_deletado(supabase, customer, agent_id or LAZARO_AGENT_ID)
            logger.info("[ASAAS WEBHOOK] CUSTOMER_DELETED processado: %s", customer.get("id"))

        # ========================================================================
        # SUBSCRIPTION EVENTS
        # ========================================================================
        elif event == "SUBSCRIPTION_CREATED" and subscription:
            # Sincroniza cliente (se vier no payload) e contrato em asaas_contratos + processa PDF em background
            # Importante: Asaas nem sempre manda CUSTOMER_CREATED quando cliente ja existe
            if customer:
                await _sincronizar_cliente(supabase, customer, agent_id or LAZARO_AGENT_ID)
            await _sincronizar_contrato(supabase, subscription, agent_id or LAZARO_AGENT_ID)
            background_tasks.add_task(
                _processar_subscription_created_background,
                subscription_id=subscription.get("id"),
                customer_id=subscription.get("customer"),
                agent_id=agent_id or LAZARO_AGENT_ID,
            )
            logger.info(
                "[ASAAS WEBHOOK] SUBSCRIPTION_CREATED sincronizado e PDF agendado: %s (customer: %s)",
                subscription.get("id"),
                subscription.get("customer")
            )

        elif event == "SUBSCRIPTION_UPDATED" and subscription:
            # Apenas sincroniza contrato em asaas_contratos
            await _sincronizar_contrato(supabase, subscription, agent_id or LAZARO_AGENT_ID)
            logger.info("[ASAAS WEBHOOK] SUBSCRIPTION_UPDATED sincronizado: %s", subscription.get("id"))

        elif event == "SUBSCRIPTION_DELETED" and subscription:
            # Soft delete do contrato
            await _processar_contrato_deletado(supabase, subscription, agent_id or LAZARO_AGENT_ID)
            logger.info("[ASAAS WEBHOOK] SUBSCRIPTION_DELETED processado: %s", subscription.get("id"))

        # ========================================================================
        # PAYMENT EVENTS
        # ========================================================================
        elif event == "PAYMENT_CREATED" and payment:
            # Sincroniza cobranca em asaas_cobrancas
            await _sincronizar_cobranca(supabase, payment, agent_id or LAZARO_AGENT_ID)
            logger.info("[ASAAS WEBHOOK] PAYMENT_CREATED sincronizado: %s", payment.get("id"))

        elif event == "PAYMENT_UPDATED" and payment:
            # Sincroniza cobranca em asaas_cobrancas
            await _sincronizar_cobranca(supabase, payment, agent_id or LAZARO_AGENT_ID)
            logger.info("[ASAAS WEBHOOK] PAYMENT_UPDATED sincronizado: %s", payment.get("id"))

        elif event == "PAYMENT_CONFIRMED" and payment:
            # Pagamento confirmado (saldo ainda nao disponivel)
            await _processar_pagamento_confirmado(supabase, payment, agent_id)
            logger.info("[ASAAS WEBHOOK] PAYMENT_CONFIRMED processado: %s", payment.get("id"))

        elif event == "PAYMENT_RECEIVED" and payment:
            # Pagamento recebido/pago (saldo disponivel)
            await _processar_pagamento_recebido(supabase, payment, agent_id)
            logger.info("[ASAAS WEBHOOK] PAYMENT_RECEIVED processado: %s", payment.get("id"))

        elif event == "PAYMENT_OVERDUE" and payment:
            # Cobranca vencida
            await _processar_pagamento_vencido(supabase, payment, agent_id)
            logger.info("[ASAAS WEBHOOK] PAYMENT_OVERDUE processado: %s", payment.get("id"))

        elif event == "PAYMENT_CHECKOUT_VIEWED" and payment:
            # Cliente visualizou link de pagamento (apenas log para analytics)
            payment_id = payment.get("id", "?")
            value = payment.get("value", 0)
            logger.info(
                "[ASAAS WEBHOOK] PAYMENT_CHECKOUT_VIEWED: Payment %s (R$ %.2f) visualizado pelo cliente",
                payment_id,
                value
            )

        elif event == "PAYMENT_DELETED" and payment:
            # Soft delete da cobranca
            await _processar_cobranca_deletada(supabase, payment, agent_id or LAZARO_AGENT_ID)
            logger.info("[ASAAS WEBHOOK] PAYMENT_DELETED processado: %s", payment.get("id"))

        # ========================================================================
        # PAYMENT EVENTS - ESTORNOS E CHARGEBACKS (CRÍTICOS)
        # ========================================================================
        elif event == "PAYMENT_REFUNDED" and payment:
            # Cobrança estornada (devolução total)
            await _processar_pagamento_estornado(supabase, payment, agent_id)
            logger.info("[ASAAS WEBHOOK] PAYMENT_REFUNDED processado: %s", payment.get("id"))

        elif event == "PAYMENT_PARTIALLY_REFUNDED" and payment:
            # Cobrança parcialmente estornada
            await _processar_pagamento_estornado_parcial(supabase, payment, agent_id)
            logger.info("[ASAAS WEBHOOK] PAYMENT_PARTIALLY_REFUNDED processado: %s", payment.get("id"))

        elif event == "PAYMENT_CHARGEBACK_REQUESTED" and payment:
            # CRÍTICO: Chargeback solicitado - requer ação imediata
            await _processar_chargeback_solicitado(supabase, payment, agent_id)
            logger.warning("[ASAAS WEBHOOK] PAYMENT_CHARGEBACK_REQUESTED processado: %s", payment.get("id"))

        elif event == "PAYMENT_CHARGEBACK_DISPUTE" and payment:
            # Chargeback em disputa
            await _processar_chargeback_disputa(supabase, payment, agent_id)
            logger.info("[ASAAS WEBHOOK] PAYMENT_CHARGEBACK_DISPUTE processado: %s", payment.get("id"))

        elif event == "PAYMENT_AWAITING_CHARGEBACK_REVERSAL" and payment:
            # Aguardando reversão de chargeback
            await _processar_aguardando_reversao_chargeback(supabase, payment, agent_id)
            logger.info("[ASAAS WEBHOOK] PAYMENT_AWAITING_CHARGEBACK_REVERSAL processado: %s", payment.get("id"))

        # ========================================================================
        # PAYMENT EVENTS - RESTAURAÇÃO E OUTROS
        # ========================================================================
        elif event == "PAYMENT_RESTORED" and payment:
            # Cobrança restaurada (ex: após reversão de chargeback)
            await _processar_pagamento_restaurado(supabase, payment, agent_id)
            logger.info("[ASAAS WEBHOOK] PAYMENT_RESTORED processado: %s", payment.get("id"))

        elif event == "PAYMENT_RECEIVED_IN_CASH_UNDONE" and payment:
            # Confirmação de dinheiro desfeita
            await _processar_pagamento_dinheiro_desfeito(supabase, payment, agent_id)
            logger.info("[ASAAS WEBHOOK] PAYMENT_RECEIVED_IN_CASH_UNDONE processado: %s", payment.get("id"))

        elif event == "PAYMENT_ANTICIPATED" and payment:
            # Cobrança antecipada
            await _processar_pagamento_antecipado(supabase, payment, agent_id)
            logger.info("[ASAAS WEBHOOK] PAYMENT_ANTICIPATED processado: %s", payment.get("id"))

        elif event == "PAYMENT_CREDIT_CARD_CAPTURE_REFUSED" and payment:
            # Captura do cartão recusada
            await _processar_captura_cartao_recusada(supabase, payment, agent_id)
            logger.info("[ASAAS WEBHOOK] PAYMENT_CREDIT_CARD_CAPTURE_REFUSED processado: %s", payment.get("id"))

        logger.debug("[ASAAS WEBHOOK] Processado com sucesso")
        return JSONResponse(status_code=200, content={"status": "ok"})

    except Exception as e:
        logger.error(f"[ASAAS WEBHOOK] Erro: {e}", exc_info=True)
        # Sempre retornar 200 para o Asaas nao ficar reenviando
        return JSONResponse(status_code=200, content={"status": "error", "message": str(e)})


# ============================================================================
# ENDPOINT DE REPROCESSAMENTO MANUAL
# ============================================================================

@router.post("/asaas/reprocess-contract")
async def reprocess_contract(
    request: Request,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    """
    Reprocessa um contrato especifico para extrair dados de documentos.

    Util para:
    - Contratos que falharam no processamento automatico
    - Contratos criados antes do webhook estar configurado
    - Reextrair dados apos correcao de bugs

    Body:
    {
        "subscription_id": "sub_xxx",
        "agent_id": "uuid"
    }

    Returns:
        202 Accepted com status de processamento agendado
        400 Bad Request se faltam parametros
        404 Not Found se subscription nao existe
    """
    try:
        body = await request.json()
        subscription_id = body.get("subscription_id")
        agent_id = body.get("agent_id")

        if not subscription_id or not agent_id:
            return JSONResponse(
                status_code=400,
                content={"error": "subscription_id and agent_id required"}
            )

        logger.info(
            "[REPROCESS CONTRACT] Solicitado reprocessamento: subscription=%s agent=%s",
            subscription_id, agent_id
        )

        # Buscar customer_id da subscription
        supabase = get_supabase_service()
        result = (
            supabase.client
            .table("asaas_contratos")
            .select("customer_id")
            .eq("id", subscription_id)
            .maybe_single()
            .execute()
        )

        if not result.data:
            logger.warning("[REPROCESS CONTRACT] Subscription %s nao encontrada", subscription_id)
            return JSONResponse(
                status_code=404,
                content={"error": f"Subscription {subscription_id} not found in asaas_contratos"}
            )

        customer_id = result.data.get("customer_id")

        if not customer_id:
            logger.warning("[REPROCESS CONTRACT] Subscription %s sem customer_id", subscription_id)
            return JSONResponse(
                status_code=400,
                content={"error": f"Subscription {subscription_id} has no customer_id"}
            )

        # Agendar reprocessamento em background com force_reprocess=True
        background_tasks.add_task(
            _processar_subscription_created_background,
            subscription_id=subscription_id,
            customer_id=customer_id,
            agent_id=agent_id,
            force_reprocess=True,
        )

        logger.info(
            "[REPROCESS CONTRACT] Reprocessamento agendado: subscription=%s customer=%s",
            subscription_id, customer_id
        )

        return JSONResponse(
            status_code=202,
            content={
                "status": "processing",
                "message": f"Reprocessamento agendado para subscription {subscription_id}",
                "subscription_id": subscription_id,
                "customer_id": customer_id,
            }
        )

    except Exception as e:
        logger.error("[REPROCESS CONTRACT] Erro: %s", e, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


# ============================================================================
# SINCRONIZACAO DE DADOS - Funções de upsert para tabelas do dashboard
# ============================================================================

async def _sincronizar_cliente(
    supabase: Any,
    customer: Dict[str, Any],
    agent_id: str,
) -> None:
    """
    Sincroniza cliente na tabela asaas_clientes.

    Busca dados completos do cliente via API Asaas e faz upsert.
    Campos: id, agent_id, name, cpf_cnpj, email, phone, mobile_phone,
            address, address_number, complement, province, city, state, postal_code,
            date_created, external_reference, observations
    """
    customer_id = customer.get("id")
    if not customer_id:
        logger.warning("[SINCRONIZAR CLIENTE] customer_id ausente")
        return

    try:
        # Busca API key do agente para consultar dados completos
        result = (
            supabase.client
            .table("agents")
            .select("asaas_api_key")
            .eq("id", agent_id)
            .maybe_single()
            .execute()
        )

        customer_data = customer  # Usa dados do webhook como fallback

        if result.data and result.data.get("asaas_api_key"):
            try:
                asaas = AsaasService(api_key=result.data["asaas_api_key"])
                full_customer = await asaas.get_customer(customer_id)
                if full_customer:
                    customer_data = full_customer
                    logger.debug("[SINCRONIZAR CLIENTE] Dados completos obtidos via API")
            except Exception as e:
                logger.warning("[SINCRONIZAR CLIENTE] Erro ao buscar via API, usando dados do webhook: %s", e)

        now = datetime.utcnow().isoformat()

        record = {
            "id": customer_id,
            "agent_id": agent_id,
            "name": customer_data.get("name"),
            "cpf_cnpj": customer_data.get("cpfCnpj"),
            "email": customer_data.get("email"),
            "phone": customer_data.get("phone"),
            "mobile_phone": customer_data.get("mobilePhone"),
            "address": customer_data.get("address"),
            "address_number": customer_data.get("addressNumber"),
            "complement": customer_data.get("complement"),
            "province": customer_data.get("province"),
            "city": customer_data.get("city"),
            "state": customer_data.get("state"),
            "postal_code": customer_data.get("postalCode"),
            "date_created": customer_data.get("dateCreated"),
            "external_reference": customer_data.get("externalReference"),
            "observations": customer_data.get("observations"),
            "updated_at": now,
            "deleted_at": None,
            "deleted_from_asaas": False,
        }

        supabase.client.table("asaas_clientes").upsert(
            record,
            on_conflict="id,agent_id"
        ).execute()

        logger.info("[SINCRONIZAR CLIENTE] Cliente %s sincronizado: %s", customer_id, customer_data.get("name"))

    except Exception as e:
        logger.error("[SINCRONIZAR CLIENTE] Erro ao sincronizar cliente %s: %s", customer_id, e)


# ============================================================================
# FUNÇÃO UTILITÁRIA: get_cached_customer
# ============================================================================
# Verifica se o cliente já está cacheado localmente com dados frescos.
# Evita chamadas redundantes à API do Asaas quando o cliente já foi
# sincronizado recentemente (dentro do TTL).
# ============================================================================

# TTL padrão para cache de cliente: 5 minutos
CUSTOMER_CACHE_TTL_MINUTES = 5


async def _get_cached_customer(
    supabase: Any,
    customer_id: str,
    agent_id: str,
    ttl_minutes: int = CUSTOMER_CACHE_TTL_MINUTES,
) -> Optional[Dict[str, Any]]:
    """
    Busca cliente no cache local (asaas_clientes) se estiver fresco.

    Args:
        supabase: Cliente Supabase
        customer_id: ID do cliente no Asaas
        agent_id: ID do agente
        ttl_minutes: Tempo máximo desde última atualização (minutos)

    Returns:
        Dict com dados do cliente se cacheado e fresco, None se não encontrado ou stale
    """
    if not customer_id:
        return None

    try:
        result = (
            supabase.client
            .table("asaas_clientes")
            .select("name, updated_at")
            .eq("id", customer_id)
            .eq("agent_id", agent_id)
            .maybe_single()
            .execute()
        )

        if not result.data:
            return None

        # Verificar se está dentro do TTL
        updated_at = result.data.get("updated_at")
        if updated_at:
            try:
                # Parse ISO format datetime
                if isinstance(updated_at, str):
                    last_update = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                else:
                    last_update = updated_at

                # Verificar se está dentro do TTL
                from datetime import timezone
                now = datetime.now(timezone.utc)
                if last_update.tzinfo is None:
                    last_update = last_update.replace(tzinfo=timezone.utc)

                age_minutes = (now - last_update).total_seconds() / 60

                if age_minutes <= ttl_minutes:
                    name = result.data.get("name")
                    if name and not _is_invalid_customer_name(name):
                        logger.debug(
                            "[CACHE] Cliente %s encontrado no cache (%.1f min)",
                            customer_id, age_minutes
                        )
                        return result.data
                else:
                    logger.debug(
                        "[CACHE] Cliente %s stale (%.1f min > %d min TTL)",
                        customer_id, age_minutes, ttl_minutes
                    )
            except Exception as e:
                logger.debug("[CACHE] Erro ao parsear updated_at: %s", e)

        return None

    except Exception as e:
        logger.debug("[CACHE] Erro ao buscar cliente %s no cache: %s", customer_id, e)
        return None


# ============================================================================
# FUNÇÃO UTILITÁRIA: resolve_customer_name
# ============================================================================
# Resolve o nome do cliente usando hierarquia de fontes:
# 1. Se proposed_name é válido → usa ele
# 2. Se não, busca em asaas_clientes
# 3. Se não, busca em asaas_cobrancas (nome existente)
# 4. Se não, busca em asaas_contratos (nome existente)
# 5. Último recurso: retorna proposed_name original
# ============================================================================

def _is_invalid_customer_name(name) -> bool:
    """Verifica se o nome é inválido/fallback."""
    if not name or not str(name).strip():
        return True
    lower = str(name).lower().strip()
    if lower in ("desconhecido", "sem nome", "cliente", "?"):
        return True
    if lower.startswith("cliente #"):
        return True
    # Padrão "Cliente abc123" (6 caracteres hex)
    import re
    if re.match(r"^cliente [a-f0-9]{6}$", lower):
        return True
    return False


async def resolve_customer_name(
    supabase: Any,
    customer_id,
    proposed_name,
    agent_id=None,
) -> str:
    """
    Resolve o nome do cliente usando hierarquia de fontes.

    Args:
        supabase: Cliente do Supabase
        customer_id: ID do cliente no Asaas
        proposed_name: Nome proposto (pode ser fallback)
        agent_id: ID do agente (opcional, para filtrar por agente)

    Returns:
        Nome resolvido ou fallback original
    """
    # 1. Se proposed_name é válido, usa ele
    if proposed_name and not _is_invalid_customer_name(proposed_name):
        return proposed_name

    if not customer_id:
        return proposed_name or "Desconhecido"

    # 2. Busca em asaas_clientes
    try:
        query = supabase.client.table("asaas_clientes").select("name").eq("id", customer_id)
        if agent_id:
            query = query.eq("agent_id", agent_id)
        result = query.maybe_single().execute()

        if result.data and result.data.get("name"):
            name = result.data["name"]
            if not _is_invalid_customer_name(name):
                logger.debug("[RESOLVE_NAME] Nome obtido de asaas_clientes: %s", name)
                return name
    except Exception as e:
        logger.debug("[RESOLVE_NAME] Erro ao buscar em asaas_clientes: %s", e)

    # 3. Busca em asaas_cobrancas (nome existente válido)
    try:
        query = (
            supabase.client
            .table("asaas_cobrancas")
            .select("customer_name")
            .eq("customer_id", customer_id)
            .neq("customer_name", "Desconhecido")
            .neq("customer_name", "Sem nome")
            .neq("customer_name", "")
            .limit(1)
        )
        if agent_id:
            query = query.eq("agent_id", agent_id)
        result = query.maybe_single().execute()

        if result.data and result.data.get("customer_name"):
            name = result.data["customer_name"]
            if not _is_invalid_customer_name(name):
                logger.debug("[RESOLVE_NAME] Nome obtido de asaas_cobrancas: %s", name)
                return name
    except Exception as e:
        logger.debug("[RESOLVE_NAME] Erro ao buscar em asaas_cobrancas: %s", e)

    # 4. Busca em asaas_contratos (nome existente válido)
    try:
        query = (
            supabase.client
            .table("asaas_contratos")
            .select("customer_name")
            .eq("customer_id", customer_id)
            .neq("customer_name", "Desconhecido")
            .neq("customer_name", "Sem nome")
            .neq("customer_name", "")
            .limit(1)
        )
        if agent_id:
            query = query.eq("agent_id", agent_id)
        result = query.maybe_single().execute()

        if result.data and result.data.get("customer_name"):
            name = result.data["customer_name"]
            if not _is_invalid_customer_name(name):
                logger.debug("[RESOLVE_NAME] Nome obtido de asaas_contratos: %s", name)
                return name
    except Exception as e:
        logger.debug("[RESOLVE_NAME] Erro ao buscar em asaas_contratos: %s", e)

    # 5. Último recurso: retorna proposed_name original
    return proposed_name or "Desconhecido"


async def _sincronizar_contrato(
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
        # OTIMIZAÇÃO: CACHE-FIRST, API COMO FALLBACK
        # ========================================================================
        # Verifica se o cliente já está cacheado localmente com dados frescos.
        # Evita chamadas redundantes à API do Asaas em processamento em lote.
        # Se cache miss ou stale, busca via API e sincroniza.
        # ========================================================================

        customer_name = "Desconhecido"

        if customer_id:
            # 1. Verificar cache local primeiro (TTL: 5 minutos)
            cached_customer = await _get_cached_customer(supabase, customer_id, agent_id)

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
                            await _sincronizar_cliente(supabase, customer_from_api, agent_id)

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

        # Fallback 1: Se não conseguiu nome via API, buscar do cache local
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

        # Fallback 2: Se não encontrou, tenta buscar de outro contrato do mesmo cliente
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

        # Validação final: usar função utilitária para resolver nome
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


async def _processar_contrato_deletado(
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


async def _processar_cliente_deletado(
    supabase: Any,
    customer: Dict[str, Any],
    agent_id: str,
) -> None:
    """
    Processa CUSTOMER_DELETED - soft delete do cliente e dados relacionados.

    Marca o cliente como deletado em asaas_clientes.
    Tambem marca contratos e cobrancas relacionados como deletados.
    """
    customer_id = customer.get("id")

    if not customer_id:
        logger.warning("[CLIENTE DELETADO] customer_id ausente")
        return

    try:
        now = datetime.utcnow().isoformat()

        # 1. Soft delete do cliente
        supabase.client.table("asaas_clientes").update({
            "deleted_at": now,
            "deleted_from_asaas": True,
            "updated_at": now,
        }).eq("id", customer_id).execute()

        logger.info("[CLIENTE DELETADO] Cliente %s marcado como deletado", customer_id)

        # 2. Soft delete dos contratos do cliente
        supabase.client.table("asaas_contratos").update({
            "status": "INACTIVE",
            "deleted_at": now,
            "deleted_from_asaas": True,
            "updated_at": now,
        }).eq("customer_id", customer_id).execute()

        logger.info("[CLIENTE DELETADO] Contratos do cliente %s marcados como INACTIVE", customer_id)

        # 3. Soft delete das cobrancas do cliente
        supabase.client.table("asaas_cobrancas").update({
            "deleted_at": now,
            "deleted_from_asaas": True,
            "updated_at": now,
        }).eq("customer_id", customer_id).execute()

        logger.info("[CLIENTE DELETADO] Cobrancas do cliente %s marcadas como deletadas", customer_id)

        # 4. Soft delete dos contract_details do cliente
        try:
            supabase.client.table("contract_details").update({
                "deleted_at": now,
                "updated_at": now,
            }).eq("customer_id", customer_id).execute()
            logger.info("[CLIENTE DELETADO] Contract details do cliente %s marcados como deletados", customer_id)
        except Exception as e:
            logger.debug("[CLIENTE DELETADO] Erro ao deletar contract_details (pode nao existir): %s", e)

    except Exception as e:
        logger.error("[CLIENTE DELETADO] Erro ao deletar cliente %s: %s", customer_id, e)


async def _processar_cobranca_deletada(
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


async def _sincronizar_cobranca(
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
        # OTIMIZAÇÃO: CACHE-FIRST, API COMO FALLBACK
        # ========================================================================
        # Verifica se o cliente já está cacheado localmente com dados frescos.
        # Evita chamadas redundantes à API do Asaas em processamento em lote.
        # Se cache miss ou stale, busca via API e sincroniza.
        # ========================================================================

        customer_name = "Desconhecido"

        if customer_id:
            # 1. Verificar cache local primeiro (TTL: 5 minutos)
            cached_customer = await _get_cached_customer(supabase, customer_id, agent_id)

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
                            await _sincronizar_cliente(supabase, customer_from_api, agent_id)

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

        # Validação final: usar função utilitária para resolver nome
        customer_name = await resolve_customer_name(
            supabase, customer_id, customer_name, agent_id
        )

        # Calcular dias de atraso se vencido
        dias_atraso = 0
        status = payment.get("status", "")
        due_date = payment.get("dueDate")

        if status == "OVERDUE" and due_date:
            try:
                from datetime import date
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


# ============================================================================
# CUSTOMER_CREATED - Processamento em Background
# ============================================================================

async def _processar_customer_created_background(
    customer_id: str,
    customer_name: str,
    agent_id: str,
) -> None:
    """
    Processa CUSTOMER_CREATED em background.

    Fluxo:
    1. Busca assinaturas do cliente
    2. Para cada assinatura, busca pagamentos
    3. Para cada pagamento, busca documentos PDF
    4. Extrai texto do PDF com pymupdf
    5. Envia para Gemini extrair dados estruturados
    6. Salva em contract_details
    """
    logger.info("[CUSTOMER_CREATED] Iniciando processamento background para %s (%s)", customer_id, customer_name)

    try:
        # Busca a API key do agente
        supabase = get_supabase_service()
        result = (
            supabase.client
            .table("agents")
            .select("asaas_api_key")
            .eq("id", agent_id)
            .maybe_single()
            .execute()
        )

        if not result.data or not result.data.get("asaas_api_key"):
            logger.error("[CUSTOMER_CREATED] Agent %s nao tem asaas_api_key", agent_id)
            return

        asaas_api_key = result.data["asaas_api_key"]
        asaas = AsaasService(api_key=asaas_api_key)

        # 1. Listar assinaturas do cliente
        logger.info("[CUSTOMER_CREATED] Buscando assinaturas de %s...", customer_id)
        subscriptions = await asaas.list_subscriptions_by_customer(customer_id)

        if not subscriptions:
            logger.info("[CUSTOMER_CREATED] Cliente %s nao tem assinaturas", customer_id)
            return

        logger.info("[CUSTOMER_CREATED] Encontradas %d assinaturas", len(subscriptions))

        # 2. Para cada assinatura, buscar PDFs
        for sub in subscriptions:
            subscription_id = sub.get("id")
            if not subscription_id:
                continue

            logger.info("[CUSTOMER_CREATED] Processando assinatura %s...", subscription_id)

            # Verificar se ja foi processado
            try:
                existing = (
                    supabase.client
                    .table("contract_details")
                    .select("id")
                    .eq("subscription_id", subscription_id)
                    .eq("agent_id", agent_id)
                    .maybe_single()
                    .execute()
                )

                if existing and existing.data:
                    logger.info("[CUSTOMER_CREATED] Assinatura %s ja processada, pulando", subscription_id)
                    continue
            except Exception as e:
                logger.warning("[CUSTOMER_CREATED] Erro ao verificar contract_details existente: %s", e)

            # Buscar pagamentos
            await asyncio.sleep(0.2)  # Rate limit
            payments = await asaas.list_payments_by_subscription(subscription_id)

            if not payments:
                logger.debug("[CUSTOMER_CREATED] Assinatura %s sem pagamentos", subscription_id)
                continue

            logger.info("[CUSTOMER_CREATED] Encontrados %d pagamentos", len(payments))

            # 3. Buscar PDFs de todos os pagamentos
            all_pdf_data: List[Dict[str, Any]] = []
            all_contract_data: List[Dict[str, Any]] = []

            for payment in payments[:5]:  # Limita a 5 pagamentos
                payment_id = payment.get("id")
                if not payment_id:
                    continue

                await asyncio.sleep(0.2)  # Rate limit
                docs = await asaas.list_payment_documents(payment_id)

                # Filtrar documentos suportados (PDF + imagens)
                supported_docs = [
                    d for d in docs
                    if any(d.get("name", "").lower().endswith(ext) for ext in SUPPORTED_EXTENSIONS)
                ]

                for doc in supported_docs:
                    doc_url = (
                        doc.get("file", {}).get("publicAccessUrl") or
                        doc.get("file", {}).get("downloadUrl")
                    )

                    if not doc_url:
                        continue

                    doc_name = doc.get("name", "")
                    doc_name_lower = doc_name.lower()

                    try:
                        # 4. Baixar documento
                        logger.info("[CUSTOMER_CREATED] Baixando documento %s...", doc_name)
                        doc_bytes = await asaas.download_document(doc_url)

                        # 5. Extrair dados baseado no tipo de arquivo
                        contract_data = None

                        if doc_name_lower.endswith(".pdf"):
                            # Fluxo PDF: pymupdf + Gemini Text
                            pdf_text = _extract_text_from_pdf(doc_bytes)

                            if not pdf_text or len(pdf_text.strip()) < 50:
                                logger.warning("[CUSTOMER_CREATED] PDF %s sem texto legivel", doc_name)
                                continue

                            logger.info("[CUSTOMER_CREATED] Extraindo dados do PDF com Gemini...")
                            contract_data = await _extract_contract_with_gemini(pdf_text)
                        else:
                            # Fluxo Imagem: Gemini Vision direto
                            logger.info("[CUSTOMER_CREATED] Extraindo dados da imagem com Gemini Vision...")
                            contract_data = await _extract_contract_from_image(doc_bytes, doc_name)

                        if contract_data:
                            # Corrigir valores que parecem errados (2.70 -> 2700.00)
                            contract_data = _corrigir_valores_comerciais(contract_data)
                            all_contract_data.append(contract_data)
                            all_pdf_data.append({
                                "payment_id": payment_id,
                                "doc_id": doc.get("id"),
                                "doc_name": doc_name,
                                "doc_url": doc_url,
                            })
                            logger.info(
                                "[CUSTOMER_CREATED] Extraidos %d equipamentos de %s",
                                len(contract_data.get("equipamentos", [])),
                                doc_name
                            )

                        await asyncio.sleep(0.5)  # Rate limit Gemini

                    except Exception as e:
                        logger.warning("[CUSTOMER_CREATED] Erro ao processar documento %s: %s", doc_name, e)

            if not all_pdf_data:
                logger.info("[CUSTOMER_CREATED] Nenhum documento encontrado para assinatura %s", subscription_id)
                continue

            # 6. Merge dados de todos os PDFs
            merged_data = _merge_contract_data(all_contract_data)

            # Calcular campos derivados
            equipamentos = merged_data.get("equipamentos", [])
            qtd_ars = len(equipamentos)
            valor_comercial_total = sum(eq.get("valor_comercial") or 0 for eq in equipamentos)

            # Calcular proxima_manutencao = data_inicio + 6 meses
            # Usa relativedelta para tratar corretamente dias que não existem em todos os meses
            # Ex: 31/03 + 6 meses = 30/09 (não 31/09 que não existe)
            proxima_manutencao = None
            if merged_data.get("data_inicio"):
                try:
                    inicio = datetime.strptime(merged_data["data_inicio"], "%Y-%m-%d")
                    proxima = inicio + relativedelta(months=6)
                    proxima_manutencao = proxima.strftime("%Y-%m-%d")
                except Exception as e:
                    logger.warning("[CUSTOMER_CREATED] Erro ao calcular proxima_manutencao: %s", e)

            # 7. Salvar em contract_details
            numero_contrato = merged_data.get("numero_contrato")

            # VERIFICAR DUPLICATA: Se ja existe contrato com mesmo numero_contrato, nao criar novo
            contrato_duplicado = False
            if numero_contrato:
                try:
                    existing = supabase.client.table("contract_details").select("id, subscription_id").eq(
                        "agent_id", agent_id
                    ).eq("numero_contrato", numero_contrato).execute()

                    if existing.data and len(existing.data) > 0:
                        existing_sub = existing.data[0].get("subscription_id")
                        if existing_sub != subscription_id:
                            logger.warning(
                                "[CUSTOMER_CREATED] DUPLICATA DETECTADA! Contrato %s ja existe (subscription %s). Ignorando novo (subscription %s)",
                                numero_contrato, existing_sub, subscription_id
                            )
                            contrato_duplicado = True
                except Exception as e:
                    logger.debug("[CUSTOMER_CREATED] Erro ao verificar duplicata: %s", e)

            if not contrato_duplicado:
                record = {
                    "agent_id": agent_id,
                    "subscription_id": subscription_id,
                    "customer_id": customer_id,
                    "payment_id": all_pdf_data[0]["payment_id"],
                    "document_id": ",".join(p["doc_id"] for p in all_pdf_data if p.get("doc_id")),
                    "numero_contrato": numero_contrato,
                    "locatario_nome": merged_data.get("locatario_nome") or customer_name,
                    "locatario_cpf_cnpj": merged_data.get("locatario_cpf_cnpj"),
                    "locatario_telefone": merged_data.get("locatario_telefone"),
                    "locatario_endereco": merged_data.get("locatario_endereco"),
                    "fiador_nome": merged_data.get("fiador_nome"),
                    "fiador_cpf": merged_data.get("fiador_cpf"),
                    "fiador_telefone": merged_data.get("fiador_telefone"),
                    "equipamentos": equipamentos,
                    "qtd_ars": qtd_ars,
                    "valor_comercial_total": valor_comercial_total,
                    "endereco_instalacao": merged_data.get("endereco_instalacao"),
                    "prazo_meses": merged_data.get("prazo_meses"),
                    "data_inicio": merged_data.get("data_inicio"),
                    "data_termino": merged_data.get("data_termino"),
                    "dia_vencimento": merged_data.get("dia_vencimento"),
                    "valor_mensal": merged_data.get("valor_mensal"),
                    "proxima_manutencao": proxima_manutencao,
                    "pdf_url": all_pdf_data[0]["doc_url"],
                    "pdf_filename": ", ".join(p["doc_name"] for p in all_pdf_data if p.get("doc_name")),
                    "parsed_at": datetime.utcnow().isoformat(),
                    "updated_at": datetime.utcnow().isoformat(),
                }

                try:
                    supabase.client.table("contract_details").upsert(
                        record,
                        on_conflict="subscription_id,agent_id"
                    ).execute()

                    logger.info(
                        "[CUSTOMER_CREATED] Contrato salvo! Assinatura: %s | Contrato: %s | %d equipamentos | R$ %.2f valor comercial",
                        subscription_id,
                        numero_contrato or "N/A",
                        qtd_ars,
                        valor_comercial_total
                    )
                except Exception as e:
                    logger.error("[CUSTOMER_CREATED] Erro ao salvar contract_details: %s", e)

        logger.info("[CUSTOMER_CREATED] Processamento concluido para cliente %s", customer_id)

    except Exception as e:
        logger.error("[CUSTOMER_CREATED] Erro no processamento background: %s", e, exc_info=True)


# ============================================================================
# SUBSCRIPTION_CREATED - Processamento em Background
# ============================================================================

@async_retry(max_retries=3, initial_delay=2.0, backoff_factor=2.0)
async def _processar_subscription_created_background(
    subscription_id: str,
    customer_id: str,
    agent_id: str,
    force_reprocess: bool = False,
) -> None:
    """
    Processa SUBSCRIPTION_CREATED em background.

    Similar ao CUSTOMER_CREATED, mas parte diretamente da subscription.
    Util quando o cliente ja existe e o Asaas nao envia CUSTOMER_CREATED.

    Fluxo:
    1. Busca pagamentos da subscription
    2. Para cada pagamento, busca documentos PDF
    3. Extrai texto do PDF com pymupdf
    4. Envia para Gemini extrair dados estruturados
    5. Salva em contract_details
    """
    logger.info(
        "[SUBSCRIPTION_CREATED] Iniciando processamento background para subscription %s (customer %s)",
        subscription_id, customer_id
    )

    try:
        # Busca a API key do agente
        supabase = get_supabase_service()
        result = (
            supabase.client
            .table("agents")
            .select("asaas_api_key")
            .eq("id", agent_id)
            .maybe_single()
            .execute()
        )

        if not result.data or not result.data.get("asaas_api_key"):
            logger.error("[SUBSCRIPTION_CREATED] Agent %s nao tem asaas_api_key", agent_id)
            return

        asaas_api_key = result.data["asaas_api_key"]
        asaas = AsaasService(api_key=asaas_api_key)

        # Verificar se ja foi processado (ignorar se force_reprocess=True)
        if not force_reprocess:
            try:
                existing = (
                    supabase.client
                    .table("contract_details")
                    .select("id")
                    .eq("subscription_id", subscription_id)
                    .eq("agent_id", agent_id)
                    .maybe_single()
                    .execute()
                )

                if existing and existing.data:
                    logger.info("[SUBSCRIPTION_CREATED] Subscription %s ja processada, pulando", subscription_id)
                    return
            except Exception as e:
                logger.warning("[SUBSCRIPTION_CREATED] Erro ao verificar contract_details existente: %s", e)
                # Continua o processamento mesmo com erro na verificacao
        else:
            logger.info("[SUBSCRIPTION_CREATED] Reprocessamento forcado para subscription %s", subscription_id)

        # Buscar pagamentos da subscription
        logger.info("[SUBSCRIPTION_CREATED] Buscando pagamentos da subscription %s...", subscription_id)
        payments = await asaas.list_payments_by_subscription(subscription_id)

        if not payments:
            logger.info("[SUBSCRIPTION_CREATED] Subscription %s sem pagamentos ainda", subscription_id)
            return

        logger.info("[SUBSCRIPTION_CREATED] Encontrados %d pagamentos", len(payments))

        # Buscar PDFs de todos os pagamentos
        all_pdf_data: List[Dict[str, Any]] = []
        all_contract_data: List[Dict[str, Any]] = []

        for payment in payments[:5]:  # Limita a 5 pagamentos
            payment_id = payment.get("id")
            if not payment_id:
                continue

            await asyncio.sleep(0.2)  # Rate limit
            docs = await asaas.list_payment_documents(payment_id)

            # Filtrar documentos suportados (PDF + imagens)
            supported_docs = [
                d for d in docs
                if any(d.get("name", "").lower().endswith(ext) for ext in SUPPORTED_EXTENSIONS)
            ]

            for doc in supported_docs:
                doc_url = (
                    doc.get("file", {}).get("publicAccessUrl") or
                    doc.get("file", {}).get("downloadUrl")
                )

                if not doc_url:
                    continue

                doc_name = doc.get("name", "")
                doc_name_lower = doc_name.lower()

                try:
                    # Baixar documento
                    logger.info("[SUBSCRIPTION_CREATED] Baixando documento %s...", doc_name)
                    doc_bytes = await asaas.download_document(doc_url)

                    # Extrair dados baseado no tipo de arquivo
                    contract_data = None

                    if doc_name_lower.endswith(".pdf"):
                        # Fluxo PDF: pymupdf + Gemini Text
                        pdf_text = _extract_text_from_pdf(doc_bytes)

                        if not pdf_text or len(pdf_text.strip()) < 50:
                            logger.warning("[SUBSCRIPTION_CREATED] PDF %s sem texto legivel", doc_name)
                            continue

                        logger.info("[SUBSCRIPTION_CREATED] Extraindo dados do PDF com Gemini...")
                        contract_data = await _extract_contract_with_gemini(pdf_text)
                    else:
                        # Fluxo Imagem: Gemini Vision direto
                        logger.info("[SUBSCRIPTION_CREATED] Extraindo dados da imagem com Gemini Vision...")
                        contract_data = await _extract_contract_from_image(doc_bytes, doc_name)

                    if contract_data:
                        # Corrigir valores que parecem errados (2.70 -> 2700.00)
                        contract_data = _corrigir_valores_comerciais(contract_data)
                        all_contract_data.append(contract_data)
                        all_pdf_data.append({
                            "payment_id": payment_id,
                            "doc_id": doc.get("id"),
                            "doc_name": doc_name,
                            "doc_url": doc_url,
                        })
                        logger.info(
                            "[SUBSCRIPTION_CREATED] Extraidos %d equipamentos de %s",
                            len(contract_data.get("equipamentos", [])),
                            doc_name
                        )

                    await asyncio.sleep(0.5)  # Rate limit Gemini

                except Exception as e:
                    logger.warning("[SUBSCRIPTION_CREATED] Erro ao processar documento %s: %s", doc_name, e)

        if not all_pdf_data:
            logger.info("[SUBSCRIPTION_CREATED] Nenhum documento encontrado para subscription %s", subscription_id)
            return

        # Merge dados de todos os PDFs
        merged_data = _merge_contract_data(all_contract_data)

        # Calcular campos derivados
        equipamentos = merged_data.get("equipamentos", [])
        qtd_ars = len(equipamentos)
        valor_comercial_total = sum(eq.get("valor_comercial") or 0 for eq in equipamentos)

        # Calcular proxima_manutencao = data_inicio + 6 meses
        # Usa relativedelta para tratar corretamente dias que não existem em todos os meses
        proxima_manutencao = None
        if merged_data.get("data_inicio"):
            try:
                inicio = datetime.strptime(merged_data["data_inicio"], "%Y-%m-%d")
                proxima = inicio + relativedelta(months=6)
                proxima_manutencao = proxima.strftime("%Y-%m-%d")
            except Exception as e:
                logger.warning("[SUBSCRIPTION_CREATED] Erro ao calcular proxima_manutencao: %s", e)

        # Salvar em contract_details
        numero_contrato = merged_data.get("numero_contrato")

        # VERIFICAR DUPLICATA: Se ja existe contrato com mesmo numero_contrato, nao criar novo
        contrato_duplicado = False
        if numero_contrato:
            try:
                existing = supabase.client.table("contract_details").select("id, subscription_id").eq(
                    "agent_id", agent_id
                ).eq("numero_contrato", numero_contrato).execute()

                if existing.data and len(existing.data) > 0:
                    existing_sub = existing.data[0].get("subscription_id")
                    if existing_sub != subscription_id:
                        logger.warning(
                            "[SUBSCRIPTION_CREATED] DUPLICATA DETECTADA! Contrato %s ja existe (subscription %s). Ignorando novo (subscription %s)",
                            numero_contrato, existing_sub, subscription_id
                        )
                        contrato_duplicado = True
            except Exception as e:
                logger.debug("[SUBSCRIPTION_CREATED] Erro ao verificar duplicata: %s", e)

        if not contrato_duplicado:
            record = {
                "agent_id": agent_id,
                "subscription_id": subscription_id,
                "customer_id": customer_id,
                "payment_id": all_pdf_data[0]["payment_id"],
                "document_id": ",".join(p["doc_id"] for p in all_pdf_data if p.get("doc_id")),
                "numero_contrato": numero_contrato,
                "locatario_nome": merged_data.get("locatario_nome"),
                "locatario_cpf_cnpj": merged_data.get("locatario_cpf_cnpj"),
                "locatario_telefone": merged_data.get("locatario_telefone"),
                "locatario_endereco": merged_data.get("locatario_endereco"),
                "fiador_nome": merged_data.get("fiador_nome"),
                "fiador_cpf": merged_data.get("fiador_cpf"),
                "fiador_telefone": merged_data.get("fiador_telefone"),
                "equipamentos": equipamentos,
                "qtd_ars": qtd_ars,
                "valor_comercial_total": valor_comercial_total,
                "endereco_instalacao": merged_data.get("endereco_instalacao"),
                "prazo_meses": merged_data.get("prazo_meses"),
                "data_inicio": merged_data.get("data_inicio"),
                "data_termino": merged_data.get("data_termino"),
                "dia_vencimento": merged_data.get("dia_vencimento"),
                "valor_mensal": merged_data.get("valor_mensal"),
                "proxima_manutencao": proxima_manutencao,
                "pdf_url": all_pdf_data[0]["doc_url"],
                "pdf_filename": ", ".join(p["doc_name"] for p in all_pdf_data if p.get("doc_name")),
                "parsed_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            }

            try:
                supabase.client.table("contract_details").upsert(
                    record,
                    on_conflict="subscription_id,agent_id"
                ).execute()

                logger.info(
                    "[SUBSCRIPTION_CREATED] Contrato salvo! Subscription: %s | Contrato: %s | %d equipamentos | R$ %.2f valor comercial",
                    subscription_id,
                    numero_contrato or "N/A",
                    qtd_ars,
                    valor_comercial_total
                )
            except Exception as e:
                logger.error("[SUBSCRIPTION_CREATED] Erro ao salvar contract_details: %s", e)

        logger.info("[SUBSCRIPTION_CREATED] Processamento concluido para subscription %s", subscription_id)

    except Exception as e:
        logger.error("[SUBSCRIPTION_CREATED] Erro no processamento background: %s", e, exc_info=True)


def _extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extrai texto de um PDF usando pymupdf."""
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()
        return "\n".join(text_parts)
    except Exception as e:
        logger.error("[PDF] Erro ao extrair texto: %s", e)
        return ""


async def _extract_contract_with_gemini(pdf_text: str) -> Optional[Dict[str, Any]]:
    """
    Envia texto do PDF para Gemini e extrai dados estruturados.
    Usa o mesmo prompt do TypeScript.
    """
    try:
        genai.configure(api_key=settings.google_api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")

        prompt = """Analise o texto de um contrato de locacao de ar-condicionado e extraia os dados em JSON.

=== REGRA CRITICA: NUMERO DO CONTRATO ===
O NUMERO DO CONTRATO e o identificador unico mais importante!

LOCALIZACAO: Esta SEMPRE no TOPO da primeira pagina, na PRIMEIRA LINHA do documento.
Fica no TITULO principal, junto com "CONTRATO DE LOCACAO DE BEM MOVEL".

Exemplo de onde encontrar (TOPO DO DOCUMENTO):
  ┌──────────────────────────────────────────────┐
  │ CONTRATO DE LOCACAO DE BEM MOVEL **399-1**   │  <-- NUMERO AQUI NO TITULO!
  │ Pelo presente instrumento...                  │
  └──────────────────────────────────────────────┘

Formato: "CONTRATO DE LOCACAO DE BEM MOVEL 399-1" -> numero_contrato = "399-1"
Outros formatos: "Contrato nº 123", "CONTRATO 456-2", "Nº 789"

INSTRUCOES:
- LEIA AS PRIMEIRAS LINHAS do documento para encontrar este numero
- O numero SEMPRE aparece junto ao titulo "CONTRATO DE LOCACAO..."
- NAO procure no meio ou final do documento - o numero esta no TOPO/CABECALHO
- Se nao encontrar no topo, retorne null
- Este numero identifica o contrato de forma unica

IMPORTANTE - Existem DOIS tipos de contrato. Identifique qual e e extraia corretamente:

=== TIPO 1: Tabela com coluna "item" (descricao) ===
Colunas: codigo | item (descricao) | Valor Locacao | Valor Comercial
Exemplo: "000307  PATRIMONIO 0540 - AR CONDICIONADO VG 12.000 BTUS INVERTER   189,00   2.700,00"
- O codigo "000307" NAO e o patrimonio
- Extraia "0540" do texto "PATRIMONIO 0540" na descricao
- BTUS: Extraia da descricao do item (ex: "12.000 BTUS" -> 12000)
- Cada linha = 1 equipamento

=== TIPO 2: Tabela com coluna "MARCA" contendo patrimonios ===
Colunas: MARCA | MODELO | BTUS | VALOR COMERCIAL
Exemplo: "SPRINGER MIDEA, Patrimonios 0329/ 0330/ 0331/ 0332 0333/ 0334  |  CONVENCIONAL  |  9.000 CADA  |  R$2.500,00"
- A marca e "SPRINGER MIDEA"
- Os patrimonios estao apos "Patrimonios" separados por "/" ou espaco: 0329, 0330, 0331, 0332, 0333, 0334
- BTUS: Extraia da coluna BTUS (ex: "9.000 CADA" -> 9000)
- CADA patrimonio = 1 equipamento separado no JSON
- Se ha 11 patrimonios, gere 11 objetos no array "equipamentos" (todos com mesmo btus)

REGRAS GERAIS:
- Patrimonio e sempre um codigo numerico de 3-4 digitos (ex: "0540", "0329", "155")
- Se aparecer "PATRI", "Patrimonio" ou "Patrimonios", extraia os numeros que seguem
- Nunca use o "codigo" da primeira coluna como patrimonio
- BTUS: Sempre extrair como numero inteiro (9.000 -> 9000, 12.000 -> 12000)

Texto do contrato:
---
""" + pdf_text[:8000] + """
---

Retorne APENAS um JSON valido (sem markdown, sem ```) com esta estrutura:
{
  "numero_contrato": "string ou null",
  "locatario_nome": "string",
  "locatario_cpf_cnpj": "string ou null",
  "locatario_telefone": "string ou null",
  "locatario_endereco": "string ou null",
  "fiador_nome": "string ou null",
  "fiador_cpf": "string ou null",
  "fiador_telefone": "string ou null",
  "equipamentos": [
    {
      "patrimonio": "string (codigo numerico extraido, ex: '0540' ou '0329')",
      "marca": "string (nome da marca sem os patrimonios)",
      "modelo": "string ou null",
      "btus": 12000,
      "valor_comercial": 2700.00
    }
  ],
  "endereco_instalacao": "string ou null",
  "prazo_meses": 12,
  "data_inicio": "YYYY-MM-DD",
  "data_termino": "YYYY-MM-DD",
  "dia_vencimento": 15,
  "valor_mensal": 189.00
}

Se um campo nao existir, use null. Datas em YYYY-MM-DD. Valores em numero decimal."""

        response = await model.generate_content_async(prompt)
        text = response.text

        # Limpar markdown se houver
        cleaned = text.replace("```json\n", "").replace("```\n", "").replace("```", "").strip()

        return json.loads(cleaned)

    except Exception as e:
        logger.error("[GEMINI] Erro ao extrair dados do contrato: %s", e)
        return None


async def _extract_contract_from_image(image_bytes: bytes, filename: str) -> Optional[Dict[str, Any]]:
    """
    Extrai dados de contrato de uma imagem usando Gemini Vision.

    Suporta JPEG, PNG, GIF e WebP.

    Args:
        image_bytes: Bytes da imagem
        filename: Nome do arquivo para detectar MIME type

    Returns:
        Dicionario com dados do contrato ou None se erro
    """
    try:
        genai.configure(api_key=settings.google_api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")

        # Detectar MIME type pela extensao
        ext = '.' + filename.lower().split('.')[-1]
        mime_type = MIME_TYPES.get(ext, 'image/jpeg')

        # Converter para base64
        image_b64 = base64.b64encode(image_bytes).decode('utf-8')

        prompt = """Analise esta IMAGEM de um contrato de locacao de ar-condicionado e extraia os dados em JSON.

=== REGRA CRITICA: NUMERO DO CONTRATO ===
O NUMERO DO CONTRATO e o identificador unico mais importante!

LOCALIZACAO: Esta SEMPRE no TOPO da imagem, na PRIMEIRA LINHA visivel.
Fica no TITULO principal, junto com "CONTRATO DE LOCACAO DE BEM MOVEL".

Exemplo de onde encontrar (TOPO DA IMAGEM):
  ┌──────────────────────────────────────────────┐
  │ CONTRATO DE LOCACAO DE BEM MOVEL **399-1**   │  <-- NUMERO AQUI NO TITULO!
  │ Pelo presente instrumento...                  │
  └──────────────────────────────────────────────┘

Formato: "CONTRATO DE LOCACAO DE BEM MOVEL 399-1" -> numero_contrato = "399-1"
Outros formatos: "Contrato nº 123", "CONTRATO 456-2", "Nº 789"

INSTRUCOES:
- OLHE PARA O TOPO DA IMAGEM para encontrar este numero
- O numero SEMPRE aparece junto ao titulo "CONTRATO DE LOCACAO..."
- NAO procure no meio ou final - o numero esta no TOPO/CABECALHO
- Se nao encontrar no topo, retorne null

IMPORTANTE - Leia todo o texto visivel na imagem e extraia:

1. DADOS DO LOCATARIO: Nome, CPF/CNPJ, telefone, endereco
2. DADOS DO FIADOR: Nome, CPF, telefone (se houver)
3. EQUIPAMENTOS: Para cada ar-condicionado, extraia:
   - Patrimonio: codigo numerico de 3-4 digitos (ex: "0540", "0329")
   - Marca: nome da marca (ex: "SPRINGER", "LG", "SAMSUNG")
   - Modelo: modelo do equipamento (ex: "INVERTER", "CONVENCIONAL")
   - BTUS: potencia como numero inteiro (ex: 9000, 12000, 18000)
   - Valor comercial: valor do equipamento em reais

4. CONTRATO: numero, endereco instalacao, prazo em meses, data inicio/termino, dia vencimento, valor mensal

REGRAS:
- Patrimonio e sempre um codigo numerico (NAO e codigo de produto)
- Se aparecer "PATRI", "Patrimonio" ou "Patrimonios", extraia os numeros que seguem
- BTUS: 9.000 -> 9000, 12.000 -> 12000
- Valores monetarios: extraia como numero decimal (2.700,00 -> 2700.00)

Retorne APENAS um JSON valido (sem markdown, sem ```) com esta estrutura:
{
  "numero_contrato": "string ou null",
  "locatario_nome": "string",
  "locatario_cpf_cnpj": "string ou null",
  "locatario_telefone": "string ou null",
  "locatario_endereco": "string ou null",
  "fiador_nome": "string ou null",
  "fiador_cpf": "string ou null",
  "fiador_telefone": "string ou null",
  "equipamentos": [
    {
      "patrimonio": "string (codigo numerico extraido)",
      "marca": "string",
      "modelo": "string ou null",
      "btus": 12000,
      "valor_comercial": 2700.00
    }
  ],
  "endereco_instalacao": "string ou null",
  "prazo_meses": 12,
  "data_inicio": "YYYY-MM-DD",
  "data_termino": "YYYY-MM-DD",
  "dia_vencimento": 15,
  "valor_mensal": 189.00
}

Se um campo nao existir ou nao for legivel, use null. Datas em YYYY-MM-DD. Valores em numero decimal."""

        # Criar conteudo multimodal: imagem + prompt
        response = await model.generate_content_async([
            {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": image_b64
                }
            },
            prompt
        ])

        text = response.text

        # Limpar markdown se houver
        cleaned = text.replace("```json\n", "").replace("```\n", "").replace("```", "").strip()

        logger.info("[GEMINI VISION] Resposta extraida com sucesso de %s", filename)
        return json.loads(cleaned)

    except Exception as e:
        logger.error("[GEMINI VISION] Erro ao extrair dados da imagem %s: %s", filename, e)
        return None


def _corrigir_valores_comerciais(contract_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Corrige valores comerciais que parecem estar errados devido a confusao de separador decimal.

    O Gemini as vezes interpreta "2.700" (formato BR) como 2.70 (formato US).
    Valores de aluguel de AR-condicionado sao tipicamente entre R$ 1.000 e R$ 10.000.
    Se o valor extraido for < 100, provavelmente esta errado e deve ser multiplicado por 1000.

    Tambem corrige valor_mensal se necessario (alugueis mensais tipicamente > R$ 100).
    """
    if not contract_data:
        return contract_data

    # Corrigir valores comerciais dos equipamentos
    equipamentos = contract_data.get("equipamentos", [])
    for eq in equipamentos:
        valor_comercial = eq.get("valor_comercial")
        if valor_comercial is not None and valor_comercial > 0 and valor_comercial < 100:
            valor_corrigido = valor_comercial * 1000
            logger.warning(
                "[CORRECAO VALOR] Equipamento patrimonio %s: valor_comercial %.2f -> %.2f (multiplicado por 1000)",
                eq.get("patrimonio", "?"),
                valor_comercial,
                valor_corrigido
            )
            eq["valor_comercial"] = valor_corrigido

    # Corrigir valor_mensal se muito baixo
    valor_mensal = contract_data.get("valor_mensal")
    if valor_mensal is not None and valor_mensal > 0 and valor_mensal < 50:
        valor_corrigido = valor_mensal * 1000
        logger.warning(
            "[CORRECAO VALOR] valor_mensal %.2f -> %.2f (multiplicado por 1000)",
            valor_mensal,
            valor_corrigido
        )
        contract_data["valor_mensal"] = valor_corrigido

    return contract_data


def _merge_contract_data(data_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Merge dados de multiplos PDFs em um unico registro.
    Campos escalares: usa primeiro valor nao-null.
    Equipamentos: concatena todos os arrays.
    """
    if not data_list:
        return {}

    if len(data_list) == 1:
        return data_list[0]

    result: Dict[str, Any] = {}

    scalar_fields = [
        "numero_contrato", "locatario_nome", "locatario_cpf_cnpj",
        "locatario_telefone", "locatario_endereco", "fiador_nome",
        "fiador_cpf", "fiador_telefone", "endereco_instalacao",
        "prazo_meses", "data_inicio", "data_termino",
        "dia_vencimento", "valor_mensal",
    ]

    for field in scalar_fields:
        for data in data_list:
            if data.get(field) is not None:
                result[field] = data[field]
                break

    # Merge equipamentos
    all_equipamentos = []
    for data in data_list:
        if data.get("equipamentos") and isinstance(data["equipamentos"], list):
            all_equipamentos.extend(data["equipamentos"])

    result["equipamentos"] = all_equipamentos

    return result


# ============================================================================
# PROCESSAMENTO DE EVENTOS DE PAGAMENTO
# ============================================================================

async def _processar_pagamento_confirmado(
    supabase: Any,
    payment: Dict[str, Any],
    agent_id: Optional[str],
) -> None:
    """
    Processa PAYMENT_CONFIRMED.

    Pagamento confirmado mas saldo ainda nao disponivel.
    Atualiza status para CONFIRMED.
    """
    now = datetime.utcnow().isoformat()
    payment_id = payment.get("id", "")
    value = payment.get("value", 0)

    # Atualizar asaas_cobrancas
    if agent_id:
        try:
            supabase.client.table("asaas_cobrancas").update({
                "status": "CONFIRMED",
                "payment_date": payment.get("paymentDate"),
                "updated_at": now,
            }).eq("id", payment_id).eq("agent_id", agent_id).execute()
        except Exception as e:
            logger.debug("[ASAAS WEBHOOK] Erro ao atualizar asaas_cobrancas: %s", e)

    logger.debug("[ASAAS WEBHOOK] Pagamento confirmado: %s (R$ %.2f)", payment_id, value)


async def _buscar_telefone_cliente(
    supabase: Any,
    customer_id: str,
    payment_id: str,
) -> Optional[str]:
    """
    Busca telefone do cliente para encontrar o lead.

    Prioridade:
    1. asaas_clientes.mobile_phone
    2. asaas_clientes.phone
    3. billing_notifications.phone (fallback)

    Returns:
        Telefone normalizado (últimos 9 dígitos) ou None se não encontrar.
    """
    import re

    def normalizar_telefone(phone: str) -> Optional[str]:
        """Remove não-numéricos e retorna últimos 9 dígitos."""
        if not phone:
            return None
        digits = re.sub(r"\D", "", phone)
        if len(digits) >= 9:
            return digits[-9:]  # Últimos 9 dígitos para match flexível
        return None

    # 1. Tentar asaas_clientes primeiro (cache local)
    try:
        result = (
            supabase.client.table("asaas_clientes")
            .select("mobile_phone, phone")
            .eq("id", customer_id)
            .maybe_single()
            .execute()
        )
        if result.data:
            phone = result.data.get("mobile_phone") or result.data.get("phone")
            normalized = normalizar_telefone(phone)
            if normalized:
                logger.debug("[ASAAS WEBHOOK] Telefone encontrado em asaas_clientes: %s", normalized[-4:])
                return normalized
    except Exception as e:
        logger.warning("[ASAAS WEBHOOK] Erro ao buscar telefone em asaas_clientes: %s", e)

    # 2. Fallback: billing_notifications
    try:
        result = (
            supabase.client.table("billing_notifications")
            .select("phone")
            .eq("payment_id", payment_id)
            .limit(1)
            .execute()
        )
        if result.data and len(result.data) > 0:
            phone = result.data[0].get("phone")
            normalized = normalizar_telefone(phone)
            if normalized:
                logger.debug("[ASAAS WEBHOOK] Telefone encontrado em billing_notifications: %s", normalized[-4:])
                return normalized
    except Exception as e:
        logger.warning("[ASAAS WEBHOOK] Erro ao buscar telefone em billing_notifications: %s", e)

    logger.warning("[ASAAS WEBHOOK] Telefone não encontrado para customer_id=%s", customer_id)
    return None


async def _atualizar_lead_pagamento(
    supabase: Any,
    agent_id: str,
    customer_id: str,
    payment_id: str,
) -> None:
    """
    Atualiza lead quando pagamento é recebido.

    - Vincula asaas_customer_id ao lead
    - Move para pipeline_step = 'cliente'
    - Marca venda_realizada = 'true'
    - Atualiza journey_stage = 'cliente'
    """
    # Validação inicial
    if not agent_id or not customer_id:
        logger.debug("[ASAAS WEBHOOK] agent_id ou customer_id não informado, pulando atualização de lead")
        return

    now = datetime.utcnow().isoformat()

    # 1. Buscar table_leads do agente
    try:
        agent_result = (
            supabase.client.table("agents")
            .select("table_leads")
            .eq("id", agent_id)
            .maybe_single()
            .execute()
        )
        if not agent_result.data or not agent_result.data.get("table_leads"):
            logger.warning("[ASAAS WEBHOOK] table_leads não encontrado para agent_id=%s", agent_id[:8])
            return
        table_leads = agent_result.data["table_leads"]
    except Exception as e:
        logger.error("[ASAAS WEBHOOK] Erro ao buscar table_leads: %s", e)
        return

    # 2. Buscar telefone do cliente
    telefone = await _buscar_telefone_cliente(supabase, customer_id, payment_id)
    if not telefone:
        logger.warning("[ASAAS WEBHOOK] Não foi possível encontrar telefone para atualizar lead")
        return

    # 3. Buscar lead na tabela dinâmica pelo telefone
    try:
        # Busca flexível: telefone pode estar com ou sem código do país
        lead_result = (
            supabase.client.table(table_leads)
            .select("id, nome, pipeline_step, asaas_customer_id")
            .ilike("telefone", f"%{telefone}%")
            .maybe_single()
            .execute()
        )

        if not lead_result.data:
            logger.warning(
                "[ASAAS WEBHOOK] Lead não encontrado com telefone %s na tabela %s",
                telefone[-4:], table_leads
            )
            return

        lead_id = lead_result.data["id"]
        lead_nome = lead_result.data.get("nome", "Desconhecido")
        pipeline_atual = lead_result.data.get("pipeline_step", "")

    except Exception as e:
        logger.error("[ASAAS WEBHOOK] Erro ao buscar lead pelo telefone: %s", e)
        return

    # 4. Atualizar lead
    try:
        supabase.client.table(table_leads).update({
            "asaas_customer_id": customer_id,
            "pipeline_step": "cliente",
            "venda_realizada": "true",
            "journey_stage": "cliente",
            "updated_date": now,
        }).eq("id", lead_id).execute()

        logger.info(
            "[ASAAS WEBHOOK] Lead atualizado após pagamento: id=%s, nome=%s, pipeline: %s -> cliente",
            lead_id, lead_nome[:20] if lead_nome else "?", pipeline_atual
        )
    except Exception as e:
        logger.error("[ASAAS WEBHOOK] Erro ao atualizar lead id=%s: %s", lead_id, e)


async def _processar_pagamento_recebido(
    supabase: Any,
    payment: Dict[str, Any],
    agent_id: Optional[str],
) -> None:
    """
    Processa PAYMENT_RECEIVED.

    Pagamento recebido/pago (saldo disponivel).
    Atualiza status para RECEIVED e marca como pago em billing_notifications.
    Se a IA cobrou este pagamento (ia_cobrou = true), marca ia_recebeu = true.
    """
    now = datetime.utcnow().isoformat()
    payment_id = payment.get("id", "")
    value = payment.get("value", 0)

    # Atualizar asaas_cobrancas
    if agent_id:
        try:
            # Primeiro, buscar se ia_cobrou = true para marcar ia_recebeu
            cobranca_res = (
                supabase.client.table("asaas_cobrancas")
                .select("ia_cobrou")
                .eq("id", payment_id)
                .eq("agent_id", agent_id)
                .limit(1)
                .execute()
            )

            update_data = {
                "status": "RECEIVED",
                "payment_date": payment.get("paymentDate"),
                "updated_at": now,
            }

            # Se IA cobrou, buscar step da última notificação e marcar ia_recebeu
            if cobranca_res.data and cobranca_res.data[0].get("ia_cobrou"):
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
                    if notif_res.data:
                        update_data["ia_recebeu"] = True
                        update_data["ia_recebeu_at"] = now
                        update_data["ia_recebeu_step"] = notif_res.data[0].get("notification_type")
                        update_data["ia_recebeu_days_from_due"] = notif_res.data[0].get("days_from_due")
                        logger.info(
                            "[ASAAS WEBHOOK] Pagamento %s: IA cobrou e recebeu! Step=%s, Days=%s",
                            payment_id,
                            update_data.get("ia_recebeu_step"),
                            update_data.get("ia_recebeu_days_from_due"),
                        )
                    else:
                        # ia_cobrou mas sem notificação encontrada (raro)
                        update_data["ia_recebeu"] = True
                        update_data["ia_recebeu_at"] = now
                except Exception as e:
                    logger.warning("[ASAAS WEBHOOK] Erro ao buscar step de notificação: %s", e)
                    update_data["ia_recebeu"] = True
                    update_data["ia_recebeu_at"] = now

            supabase.client.table("asaas_cobrancas").update(
                update_data
            ).eq("id", payment_id).eq("agent_id", agent_id).execute()
        except Exception as e:
            logger.debug("[ASAAS WEBHOOK] Erro ao atualizar asaas_cobrancas: %s", e)

    # Atualizar billing_notifications (tabela unificada)
    try:
        supabase.client.table("billing_notifications").update({
            "status": "paid",
            "updated_at": now,
        }).eq("payment_id", payment_id).execute()
    except Exception as e:
        logger.debug("[ASAAS WEBHOOK] Erro ao atualizar billing_notifications: %s", e)

    logger.debug("[ASAAS WEBHOOK] Pagamento recebido: %s (R$ %.2f)", payment_id, value)

    # Atualizar lead (pipeline_step, venda_realizada, etc.)
    customer_id = payment.get("customer", "")
    if agent_id and customer_id:
        try:
            await _atualizar_lead_pagamento(supabase, agent_id, customer_id, payment_id)
        except Exception as e:
            logger.error("[ASAAS WEBHOOK] Erro ao atualizar lead após pagamento: %s", e)


async def _processar_pagamento_vencido(
    supabase: Any,
    payment: Dict[str, Any],
    agent_id: Optional[str],
) -> None:
    """Processa PAYMENT_OVERDUE."""
    now = datetime.utcnow().isoformat()
    payment_id = payment.get("id", "")
    value = payment.get("value", 0)

    # Atualizar asaas_cobrancas
    if agent_id:
        try:
            supabase.client.table("asaas_cobrancas").update({
                "status": "OVERDUE",
                "updated_at": now,
            }).eq("id", payment_id).eq("agent_id", agent_id).execute()
        except Exception as e:
            logger.debug("[ASAAS WEBHOOK] Erro ao atualizar asaas_cobrancas: %s", e)

    # Atualizar billing_notifications (tabela unificada)
    try:
        supabase.client.table("billing_notifications").update({
            "status": "overdue",
            "updated_at": now,
        }).eq("payment_id", payment_id).execute()
    except Exception as e:
        logger.debug("[ASAAS WEBHOOK] Erro ao atualizar billing_notifications: %s", e)

    logger.debug("[ASAAS WEBHOOK] Pagamento vencido: %s (R$ %.2f)", payment_id, value)


# ============================================================================
# HELPER: Atualizar status genérico de cobrança
# ============================================================================

async def _atualizar_status_cobranca(
    supabase: Any,
    payment: Dict[str, Any],
    agent_id: Optional[str],
    status: str,
    extra_fields: Optional[Dict[str, Any]] = None,
    billing_status: Optional[str] = None,
) -> None:
    """
    Helper genérico para atualizar status de cobrança.

    Usado pelos handlers de eventos que apenas mudam o status.

    Args:
        supabase: Cliente Supabase
        payment: Dados do pagamento do webhook
        agent_id: ID do agente (opcional)
        status: Novo status para asaas_cobrancas
        extra_fields: Campos extras para atualizar em asaas_cobrancas
        billing_status: Status para billing_notifications (se diferente)
    """
    now = datetime.utcnow().isoformat()
    payment_id = payment.get("id", "")
    value = payment.get("value", 0)

    # Atualizar asaas_cobrancas
    if agent_id:
        try:
            update_data = {
                "status": status,
                "updated_at": now,
            }
            if extra_fields:
                update_data.update(extra_fields)

            supabase.client.table("asaas_cobrancas").update(
                update_data
            ).eq("id", payment_id).eq("agent_id", agent_id).execute()
        except Exception as e:
            logger.debug("[ASAAS WEBHOOK] Erro ao atualizar asaas_cobrancas: %s", e)

    # Atualizar billing_notifications se billing_status especificado
    if billing_status:
        try:
            supabase.client.table("billing_notifications").update({
                "status": billing_status,
                "updated_at": now,
            }).eq("payment_id", payment_id).execute()
        except Exception as e:
            logger.debug("[ASAAS WEBHOOK] Erro ao atualizar billing_notifications: %s", e)

    logger.debug("[ASAAS WEBHOOK] Status atualizado: %s -> %s (R$ %.2f)", payment_id, status, value)


# ============================================================================
# PAYMENT_REFUNDED - Cobrança estornada
# ============================================================================

async def _processar_pagamento_estornado(
    supabase: Any,
    payment: Dict[str, Any],
    agent_id: Optional[str],
) -> None:
    """
    Processa PAYMENT_REFUNDED.

    Cobrança foi estornada (devolução total).
    Atualiza status para REFUNDED.
    Reverte ia_recebeu para não contar no dashboard como coletado pela IA.
    """
    extra_fields = {
        "refund_date": datetime.utcnow().isoformat(),
        "ia_recebeu": False,
        "ia_recebeu_at": None,
    }
    await _atualizar_status_cobranca(
        supabase, payment, agent_id,
        status="REFUNDED",
        extra_fields=extra_fields,
        billing_status="refunded",
    )


# ============================================================================
# PAYMENT_PARTIALLY_REFUNDED - Cobrança parcialmente estornada
# ============================================================================

async def _processar_pagamento_estornado_parcial(
    supabase: Any,
    payment: Dict[str, Any],
    agent_id: Optional[str],
) -> None:
    """
    Processa PAYMENT_PARTIALLY_REFUNDED.

    Cobrança foi parcialmente estornada.
    Atualiza status para PARTIALLY_REFUNDED para manter paridade com Asaas.
    Reverte ia_recebeu para não contar no dashboard como coletado pela IA.
    """
    extra_fields = {
        "refund_date": datetime.utcnow().isoformat(),
        "ia_recebeu": False,
        "ia_recebeu_at": None,
    }
    await _atualizar_status_cobranca(
        supabase, payment, agent_id,
        status="PARTIALLY_REFUNDED",
        extra_fields=extra_fields,
        billing_status="refunded",
    )


# ============================================================================
# PAYMENT_CHARGEBACK_REQUESTED - Chargeback solicitado
# ============================================================================

async def _processar_chargeback_solicitado(
    supabase: Any,
    payment: Dict[str, Any],
    agent_id: Optional[str],
) -> None:
    """
    Processa PAYMENT_CHARGEBACK_REQUESTED.

    Cliente solicitou chargeback (contestação no cartão).
    CRÍTICO: Requer ação imediata do lojista.
    Reverte ia_recebeu para não contar no dashboard como coletado pela IA.
    """
    extra_fields = {
        "chargeback_requested_at": datetime.utcnow().isoformat(),
        "ia_recebeu": False,
        "ia_recebeu_at": None,
    }
    await _atualizar_status_cobranca(
        supabase, payment, agent_id,
        status="CHARGEBACK_REQUESTED",
        extra_fields=extra_fields,
        billing_status="chargeback",
    )
    logger.warning(
        "[ASAAS WEBHOOK] CHARGEBACK SOLICITADO! Payment: %s | Valor: R$ %.2f",
        payment.get("id"), payment.get("value", 0)
    )


# ============================================================================
# PAYMENT_CHARGEBACK_DISPUTE - Chargeback em disputa
# ============================================================================

async def _processar_chargeback_disputa(
    supabase: Any,
    payment: Dict[str, Any],
    agent_id: Optional[str],
) -> None:
    """
    Processa PAYMENT_CHARGEBACK_DISPUTE.

    Chargeback está em processo de disputa.
    """
    extra_fields = {
        "chargeback_dispute_at": datetime.utcnow().isoformat(),
    }
    await _atualizar_status_cobranca(
        supabase, payment, agent_id,
        status="CHARGEBACK_DISPUTE",
        extra_fields=extra_fields,
        billing_status="chargeback",
    )


# ============================================================================
# PAYMENT_AWAITING_CHARGEBACK_REVERSAL - Aguardando reversão de chargeback
# ============================================================================

async def _processar_aguardando_reversao_chargeback(
    supabase: Any,
    payment: Dict[str, Any],
    agent_id: Optional[str],
) -> None:
    """
    Processa PAYMENT_AWAITING_CHARGEBACK_REVERSAL.

    Aguardando reversão do chargeback pela bandeira.
    """
    await _atualizar_status_cobranca(
        supabase, payment, agent_id,
        status="AWAITING_CHARGEBACK_REVERSAL",
        billing_status="chargeback",
    )


# ============================================================================
# PAYMENT_RESTORED - Cobrança restaurada
# ============================================================================

async def _processar_pagamento_restaurado(
    supabase: Any,
    payment: Dict[str, Any],
    agent_id: Optional[str],
) -> None:
    """
    Processa PAYMENT_RESTORED.

    Cobrança restaurada (ex: após reversão de chargeback).
    Volta ao status PENDING.
    """
    extra_fields = {
        "restored_at": datetime.utcnow().isoformat(),
        "chargeback_requested_at": None,
        "chargeback_dispute_at": None,
        "refund_date": None,
    }
    await _atualizar_status_cobranca(
        supabase, payment, agent_id,
        status="PENDING",
        extra_fields=extra_fields,
        billing_status="pending",
    )


# ============================================================================
# PAYMENT_RECEIVED_IN_CASH_UNDONE - Confirmação de dinheiro desfeita
# ============================================================================

async def _processar_pagamento_dinheiro_desfeito(
    supabase: Any,
    payment: Dict[str, Any],
    agent_id: Optional[str],
) -> None:
    """
    Processa PAYMENT_RECEIVED_IN_CASH_UNDONE.

    Confirmação de recebimento em dinheiro foi desfeita.
    Volta ao status PENDING.
    """
    await _atualizar_status_cobranca(
        supabase, payment, agent_id,
        status="PENDING",
        billing_status="pending",
    )


# ============================================================================
# PAYMENT_ANTICIPATED - Cobrança antecipada
# ============================================================================

async def _processar_pagamento_antecipado(
    supabase: Any,
    payment: Dict[str, Any],
    agent_id: Optional[str],
) -> None:
    """
    Processa PAYMENT_ANTICIPATED.

    Cobrança foi antecipada (recebimento antes do prazo normal).
    """
    extra_fields = {
        "anticipated_at": datetime.utcnow().isoformat(),
    }
    await _atualizar_status_cobranca(
        supabase, payment, agent_id,
        status="RECEIVED",
        extra_fields=extra_fields,
        billing_status="paid",
    )


# ============================================================================
# PAYMENT_CREDIT_CARD_CAPTURE_REFUSED - Captura do cartão recusada
# ============================================================================

async def _processar_captura_cartao_recusada(
    supabase: Any,
    payment: Dict[str, Any],
    agent_id: Optional[str],
) -> None:
    """
    Processa PAYMENT_CREDIT_CARD_CAPTURE_REFUSED.

    Captura do cartão de crédito foi recusada após pré-autorização.
    """
    await _atualizar_status_cobranca(
        supabase, payment, agent_id,
        status="FAILED",
        billing_status="failed",
    )
