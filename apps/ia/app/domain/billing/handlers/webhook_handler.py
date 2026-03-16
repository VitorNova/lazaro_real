"""
Webhook handler para eventos do Asaas.

Roteia eventos para os services do domain/billing apropriados.
"""

import logging
from typing import Any, Dict, Optional

from starlette.background import BackgroundTasks

# Services do domain
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
from app.domain.billing.services.contract_extraction_service import (
    processar_customer_created_background,
    processar_subscription_created_background,
)

logger = logging.getLogger(__name__)

# Constante para agent_id padrão (Lazaro)
LAZARO_AGENT_ID = "14e6e5ce-4627-4e38-aac8-f0191669ff53"


async def handle_asaas_event(
    event: str,
    body: Dict[str, Any],
    supabase: Any,
    agent_id: Optional[str],
    background_tasks: Optional[BackgroundTasks] = None,
) -> bool:
    """
    Roteia eventos do Asaas para os services apropriados.

    Args:
        event: Tipo do evento (ex: CUSTOMER_CREATED, PAYMENT_CONFIRMED)
        body: Payload completo do webhook
        supabase: Cliente Supabase
        agent_id: ID do agente (opcional, usa LAZARO_AGENT_ID como fallback)
        background_tasks: BackgroundTasks para processamento async (opcional)

    Returns:
        True se o evento foi processado, False se não foi mapeado
    """
    payment = body.get("payment")
    customer = body.get("customer")
    subscription = body.get("subscription")

    effective_agent_id = agent_id or LAZARO_AGENT_ID

    # ========================================================================
    # CUSTOMER EVENTS
    # ========================================================================
    if event == "CUSTOMER_CREATED" and customer:
        await sincronizar_cliente(supabase, customer, effective_agent_id)
        if background_tasks:
            background_tasks.add_task(
                processar_customer_created_background,
                customer_id=customer.get("id"),
                customer_name=customer.get("name"),
                agent_id=effective_agent_id,
            )
        logger.info(
            "[WEBHOOK_HANDLER] CUSTOMER_CREATED sincronizado e PDF agendado: %s",
            customer.get("id"),
        )
        return True

    elif event == "CUSTOMER_UPDATED" and customer:
        await sincronizar_cliente(supabase, customer, effective_agent_id)
        logger.info(
            "[WEBHOOK_HANDLER] CUSTOMER_UPDATED sincronizado: %s",
            customer.get("id"),
        )
        return True

    elif event == "CUSTOMER_DELETED" and customer:
        await processar_cliente_deletado(supabase, customer, effective_agent_id)
        logger.info(
            "[WEBHOOK_HANDLER] CUSTOMER_DELETED processado: %s",
            customer.get("id"),
        )
        return True

    # ========================================================================
    # SUBSCRIPTION EVENTS
    # ========================================================================
    elif event == "SUBSCRIPTION_CREATED" and subscription:
        # Sincroniza cliente (se vier no payload) e contrato
        if customer:
            await sincronizar_cliente(supabase, customer, effective_agent_id)
        await sincronizar_contrato(supabase, subscription, effective_agent_id)
        if background_tasks:
            background_tasks.add_task(
                processar_subscription_created_background,
                subscription_id=subscription.get("id"),
                customer_id=subscription.get("customer"),
                agent_id=effective_agent_id,
            )
        logger.info(
            "[WEBHOOK_HANDLER] SUBSCRIPTION_CREATED sincronizado e PDF agendado: %s (customer: %s)",
            subscription.get("id"),
            subscription.get("customer"),
        )
        return True

    elif event == "SUBSCRIPTION_UPDATED" and subscription:
        await sincronizar_contrato(supabase, subscription, effective_agent_id)
        if background_tasks:
            background_tasks.add_task(
                processar_subscription_created_background,
                subscription_id=subscription.get("id"),
                customer_id=subscription.get("customer"),
                agent_id=effective_agent_id,
                force_reprocess=True,
            )
        logger.info(
            "[WEBHOOK_HANDLER] SUBSCRIPTION_UPDATED sincronizado e PDF agendado: %s",
            subscription.get("id"),
        )
        return True

    elif event == "SUBSCRIPTION_DELETED" and subscription:
        await processar_contrato_deletado(supabase, subscription, effective_agent_id)
        logger.info(
            "[WEBHOOK_HANDLER] SUBSCRIPTION_DELETED processado: %s",
            subscription.get("id"),
        )
        return True

    # ========================================================================
    # PAYMENT EVENTS - SYNC
    # ========================================================================
    elif event == "PAYMENT_CREATED" and payment:
        await sincronizar_cobranca(supabase, payment, effective_agent_id)
        logger.info(
            "[WEBHOOK_HANDLER] PAYMENT_CREATED sincronizado: %s",
            payment.get("id"),
        )
        return True

    elif event == "PAYMENT_UPDATED" and payment:
        await sincronizar_cobranca(supabase, payment, effective_agent_id)
        logger.info(
            "[WEBHOOK_HANDLER] PAYMENT_UPDATED sincronizado: %s",
            payment.get("id"),
        )
        return True

    elif event == "PAYMENT_CONFIRMED" and payment:
        await processar_pagamento_confirmado(supabase, payment, agent_id)
        logger.info(
            "[WEBHOOK_HANDLER] PAYMENT_CONFIRMED processado: %s",
            payment.get("id"),
        )
        return True

    elif event == "PAYMENT_RECEIVED" and payment:
        await processar_pagamento_recebido(supabase, payment, agent_id)
        logger.info(
            "[WEBHOOK_HANDLER] PAYMENT_RECEIVED processado: %s",
            payment.get("id"),
        )
        return True

    elif event == "PAYMENT_OVERDUE" and payment:
        await processar_pagamento_vencido(supabase, payment, agent_id)
        logger.info(
            "[WEBHOOK_HANDLER] PAYMENT_OVERDUE processado: %s",
            payment.get("id"),
        )
        return True

    elif event == "PAYMENT_CHECKOUT_VIEWED" and payment:
        # Apenas log para analytics - não precisa de processamento
        payment_id = payment.get("id", "?")
        value = payment.get("value", 0)
        logger.info(
            "[WEBHOOK_HANDLER] PAYMENT_CHECKOUT_VIEWED: Payment %s (R$ %.2f) visualizado pelo cliente",
            payment_id,
            value,
        )
        return True

    elif event == "PAYMENT_DELETED" and payment:
        await processar_cobranca_deletada(supabase, payment, effective_agent_id)
        logger.info(
            "[WEBHOOK_HANDLER] PAYMENT_DELETED processado: %s",
            payment.get("id"),
        )
        return True

    # ========================================================================
    # PAYMENT EVENTS - ESTORNOS E CHARGEBACKS (CRÍTICOS)
    # ========================================================================
    elif event == "PAYMENT_REFUNDED" and payment:
        await processar_pagamento_estornado(supabase, payment, agent_id)
        logger.info(
            "[WEBHOOK_HANDLER] PAYMENT_REFUNDED processado: %s",
            payment.get("id"),
        )
        return True

    elif event == "PAYMENT_PARTIALLY_REFUNDED" and payment:
        await processar_pagamento_estornado_parcial(supabase, payment, agent_id)
        logger.info(
            "[WEBHOOK_HANDLER] PAYMENT_PARTIALLY_REFUNDED processado: %s",
            payment.get("id"),
        )
        return True

    elif event == "PAYMENT_CHARGEBACK_REQUESTED" and payment:
        await processar_chargeback_solicitado(supabase, payment, agent_id)
        logger.warning(
            "[WEBHOOK_HANDLER] PAYMENT_CHARGEBACK_REQUESTED processado: %s",
            payment.get("id"),
        )
        return True

    elif event == "PAYMENT_CHARGEBACK_DISPUTE" and payment:
        await processar_chargeback_disputa(supabase, payment, agent_id)
        logger.info(
            "[WEBHOOK_HANDLER] PAYMENT_CHARGEBACK_DISPUTE processado: %s",
            payment.get("id"),
        )
        return True

    elif event == "PAYMENT_AWAITING_CHARGEBACK_REVERSAL" and payment:
        await processar_aguardando_reversao_chargeback(supabase, payment, agent_id)
        logger.info(
            "[WEBHOOK_HANDLER] PAYMENT_AWAITING_CHARGEBACK_REVERSAL processado: %s",
            payment.get("id"),
        )
        return True

    # ========================================================================
    # PAYMENT EVENTS - RESTAURAÇÃO E OUTROS
    # ========================================================================
    elif event == "PAYMENT_RESTORED" and payment:
        await processar_pagamento_restaurado(supabase, payment, agent_id)
        logger.info(
            "[WEBHOOK_HANDLER] PAYMENT_RESTORED processado: %s",
            payment.get("id"),
        )
        return True

    elif event == "PAYMENT_RECEIVED_IN_CASH_UNDONE" and payment:
        await processar_pagamento_dinheiro_desfeito(supabase, payment, agent_id)
        logger.info(
            "[WEBHOOK_HANDLER] PAYMENT_RECEIVED_IN_CASH_UNDONE processado: %s",
            payment.get("id"),
        )
        return True

    elif event == "PAYMENT_ANTICIPATED" and payment:
        await processar_pagamento_antecipado(supabase, payment, agent_id)
        logger.info(
            "[WEBHOOK_HANDLER] PAYMENT_ANTICIPATED processado: %s",
            payment.get("id"),
        )
        return True

    elif event == "PAYMENT_CREDIT_CARD_CAPTURE_REFUSED" and payment:
        await processar_captura_cartao_recusada(supabase, payment, agent_id)
        logger.info(
            "[WEBHOOK_HANDLER] PAYMENT_CREDIT_CARD_CAPTURE_REFUSED processado: %s",
            payment.get("id"),
        )
        return True

    # Evento não mapeado
    logger.warning("[WEBHOOK_HANDLER] Evento não mapeado: %s", event)
    return False
