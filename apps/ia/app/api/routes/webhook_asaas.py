"""
Rotas FastAPI para webhook Asaas.

Responsavel por:
- Receber notificacoes do Asaas
- Rotear para handlers apropriados
- Endpoint de reprocessamento manual

Extraido de: app/webhooks/pagamentos.py (Fase 3.10)
Validacao Pydantic adicionada na Fase 5.
"""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.config import settings
from app.api.models.webhook_models import AsaasWebhookPayload, AsaasReprocessContractPayload
from app.services.supabase import get_supabase_service
from app.domain.billing.models.payment import LAZARO_AGENT_ID
from app.domain.billing.services.customer_sync_service import sincronizar_cliente
from app.domain.billing.services.customer_deletion_service import processar_cliente_deletado
from app.domain.billing.services.contract_sync_service import (
    sincronizar_contrato,
    processar_contrato_deletado,
)
from app.domain.billing.services.payment_sync_service import (
    sincronizar_cobranca,
    processar_cobranca_deletada,
)
from app.domain.billing.services.contract_extraction_service import (
    processar_customer_created_background,
    processar_subscription_created_background,
)
from app.domain.billing.services.payment_confirmed_service import (
    processar_pagamento_confirmado,
    processar_pagamento_recebido,
)
from app.domain.billing.services.payment_events_service import (
    processar_pagamento_vencido,
    processar_pagamento_estornado,
    processar_pagamento_estornado_parcial,
    processar_chargeback_solicitado,
    processar_chargeback_disputa,
    processar_aguardando_reversao_chargeback,
    processar_pagamento_restaurado,
    processar_pagamento_dinheiro_desfeito,
    processar_pagamento_antecipado,
    processar_captura_cartao_recusada,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/asaas")
async def asaas_webhook(request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
    """
    Webhook endpoint para notificacoes do Asaas.

    O Asaas espera resposta rapida (< 5s).
    Sempre retorna 200 para evitar reenvios.
    Valida payload com Pydantic para logging de erros.
    """
    try:
        body = await request.json()

        # Validar com Pydantic (warning only, nao rejeita)
        try:
            validated = AsaasWebhookPayload(**body)
            logger.debug("[ASAAS WEBHOOK] Payload validado com Pydantic")
        except ValidationError as e:
            logger.warning("[ASAAS WEBHOOK] Validacao Pydantic falhou: %s", e.errors())
            # Continuar processamento mesmo com erro de validacao

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
        _log_evento(event, payment, customer, subscription, agent_id)

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
        await _processar_evento(
            event=event,
            payment=payment,
            customer=customer,
            subscription=subscription,
            agent_id=agent_id,
            supabase=supabase,
            background_tasks=background_tasks,
        )

        logger.debug("[ASAAS WEBHOOK] Processado com sucesso")
        return JSONResponse(status_code=200, content={"status": "ok"})

    except Exception as e:
        logger.error(f"[ASAAS WEBHOOK] Erro: {e}", exc_info=True)
        # Sempre retornar 200 para o Asaas nao ficar reenviando
        return JSONResponse(status_code=200, content={"status": "error", "message": str(e)})


def _log_evento(
    event: str,
    payment: Optional[Dict[str, Any]],
    customer: Optional[Dict[str, Any]],
    subscription: Optional[Dict[str, Any]],
    agent_id: Optional[str],
) -> None:
    """Log do evento recebido."""
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


async def _processar_evento(
    event: str,
    payment: Optional[Dict[str, Any]],
    customer: Optional[Dict[str, Any]],
    subscription: Optional[Dict[str, Any]],
    agent_id: Optional[str],
    supabase: Any,
    background_tasks: BackgroundTasks,
) -> None:
    """Roteia evento para handler apropriado."""
    effective_agent_id = agent_id or LAZARO_AGENT_ID

    # CUSTOMER EVENTS
    if event == "CUSTOMER_CREATED" and customer:
        await sincronizar_cliente(supabase, customer, effective_agent_id)
        background_tasks.add_task(
            processar_customer_created_background,
            customer_id=customer.get("id"),
            customer_name=customer.get("name"),
            agent_id=effective_agent_id,
        )
        logger.info("[ASAAS WEBHOOK] CUSTOMER_CREATED sincronizado e PDF agendado: %s", customer.get("id"))

    elif event == "CUSTOMER_UPDATED" and customer:
        await sincronizar_cliente(supabase, customer, effective_agent_id)
        logger.info("[ASAAS WEBHOOK] CUSTOMER_UPDATED sincronizado: %s", customer.get("id"))

    elif event == "CUSTOMER_DELETED" and customer:
        await processar_cliente_deletado(supabase, customer, effective_agent_id)
        logger.info("[ASAAS WEBHOOK] CUSTOMER_DELETED processado: %s", customer.get("id"))

    # SUBSCRIPTION EVENTS
    elif event == "SUBSCRIPTION_CREATED" and subscription:
        if customer:
            await sincronizar_cliente(supabase, customer, effective_agent_id)
        await sincronizar_contrato(supabase, subscription, effective_agent_id)
        background_tasks.add_task(
            processar_subscription_created_background,
            subscription_id=subscription.get("id"),
            customer_id=subscription.get("customer"),
            agent_id=effective_agent_id,
        )
        logger.info(
            "[ASAAS WEBHOOK] SUBSCRIPTION_CREATED sincronizado e PDF agendado: %s (customer: %s)",
            subscription.get("id"),
            subscription.get("customer")
        )

    elif event == "SUBSCRIPTION_UPDATED" and subscription:
        await sincronizar_contrato(supabase, subscription, effective_agent_id)
        logger.info("[ASAAS WEBHOOK] SUBSCRIPTION_UPDATED sincronizado: %s", subscription.get("id"))

    elif event == "SUBSCRIPTION_DELETED" and subscription:
        await processar_contrato_deletado(supabase, subscription, effective_agent_id)
        logger.info("[ASAAS WEBHOOK] SUBSCRIPTION_DELETED processado: %s", subscription.get("id"))

    # PAYMENT EVENTS
    elif event == "PAYMENT_CREATED" and payment:
        await sincronizar_cobranca(supabase, payment, effective_agent_id)
        logger.info("[ASAAS WEBHOOK] PAYMENT_CREATED sincronizado: %s", payment.get("id"))

    elif event == "PAYMENT_UPDATED" and payment:
        await sincronizar_cobranca(supabase, payment, effective_agent_id)
        logger.info("[ASAAS WEBHOOK] PAYMENT_UPDATED sincronizado: %s", payment.get("id"))

    elif event == "PAYMENT_CONFIRMED" and payment:
        await processar_pagamento_confirmado(supabase, payment, agent_id)
        logger.info("[ASAAS WEBHOOK] PAYMENT_CONFIRMED processado: %s", payment.get("id"))

    elif event == "PAYMENT_RECEIVED" and payment:
        await processar_pagamento_recebido(supabase, payment, agent_id)
        logger.info("[ASAAS WEBHOOK] PAYMENT_RECEIVED processado: %s", payment.get("id"))

    elif event == "PAYMENT_OVERDUE" and payment:
        await processar_pagamento_vencido(supabase, payment, agent_id)
        logger.info("[ASAAS WEBHOOK] PAYMENT_OVERDUE processado: %s", payment.get("id"))

    elif event == "PAYMENT_CHECKOUT_VIEWED" and payment:
        payment_id = payment.get("id", "?")
        value = payment.get("value", 0)
        logger.info(
            "[ASAAS WEBHOOK] PAYMENT_CHECKOUT_VIEWED: Payment %s (R$ %.2f) visualizado pelo cliente",
            payment_id,
            value
        )

    elif event == "PAYMENT_DELETED" and payment:
        await processar_cobranca_deletada(supabase, payment, effective_agent_id)
        logger.info("[ASAAS WEBHOOK] PAYMENT_DELETED processado: %s", payment.get("id"))

    # ESTORNOS E CHARGEBACKS
    elif event == "PAYMENT_REFUNDED" and payment:
        await processar_pagamento_estornado(supabase, payment, agent_id)
        logger.info("[ASAAS WEBHOOK] PAYMENT_REFUNDED processado: %s", payment.get("id"))

    elif event == "PAYMENT_PARTIALLY_REFUNDED" and payment:
        await processar_pagamento_estornado_parcial(supabase, payment, agent_id)
        logger.info("[ASAAS WEBHOOK] PAYMENT_PARTIALLY_REFUNDED processado: %s", payment.get("id"))

    elif event == "PAYMENT_CHARGEBACK_REQUESTED" and payment:
        await processar_chargeback_solicitado(supabase, payment, agent_id)
        logger.warning("[ASAAS WEBHOOK] PAYMENT_CHARGEBACK_REQUESTED processado: %s", payment.get("id"))

    elif event == "PAYMENT_CHARGEBACK_DISPUTE" and payment:
        await processar_chargeback_disputa(supabase, payment, agent_id)
        logger.info("[ASAAS WEBHOOK] PAYMENT_CHARGEBACK_DISPUTE processado: %s", payment.get("id"))

    elif event == "PAYMENT_AWAITING_CHARGEBACK_REVERSAL" and payment:
        await processar_aguardando_reversao_chargeback(supabase, payment, agent_id)
        logger.info("[ASAAS WEBHOOK] PAYMENT_AWAITING_CHARGEBACK_REVERSAL processado: %s", payment.get("id"))

    # RESTAURACAO E OUTROS
    elif event == "PAYMENT_RESTORED" and payment:
        await processar_pagamento_restaurado(supabase, payment, agent_id)
        logger.info("[ASAAS WEBHOOK] PAYMENT_RESTORED processado: %s", payment.get("id"))

    elif event == "PAYMENT_RECEIVED_IN_CASH_UNDONE" and payment:
        await processar_pagamento_dinheiro_desfeito(supabase, payment, agent_id)
        logger.info("[ASAAS WEBHOOK] PAYMENT_RECEIVED_IN_CASH_UNDONE processado: %s", payment.get("id"))

    elif event == "PAYMENT_ANTICIPATED" and payment:
        await processar_pagamento_antecipado(supabase, payment, agent_id)
        logger.info("[ASAAS WEBHOOK] PAYMENT_ANTICIPATED processado: %s", payment.get("id"))

    elif event == "PAYMENT_CREDIT_CARD_CAPTURE_REFUSED" and payment:
        await processar_captura_cartao_recusada(supabase, payment, agent_id)
        logger.info("[ASAAS WEBHOOK] PAYMENT_CREDIT_CARD_CAPTURE_REFUSED processado: %s", payment.get("id"))


@router.post("/asaas/reprocess-contract")
async def reprocess_contract(
    payload: AsaasReprocessContractPayload,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    """
    Reprocessa um contrato especifico para extrair dados de documentos.

    Util para:
    - Contratos que falharam no processamento automatico
    - Contratos criados antes do webhook estar configurado
    - Reextrair dados apos correcao de bugs

    Payload validado por Pydantic:
    {
        "subscription_id": "sub_xxx",
        "agent_id": "uuid"
    }

    Returns:
        202 Accepted com status de processamento agendado
        404 Not Found se subscription nao existe
    """
    try:
        subscription_id = payload.subscription_id
        agent_id = payload.agent_id

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
            processar_subscription_created_background,
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
