"""
Servico de processamento de eventos de pagamento (vencido, estorno, chargeback).

Responsavel por:
- Processar PAYMENT_OVERDUE
- Processar estornos (REFUNDED, PARTIALLY_REFUNDED)
- Processar chargebacks (REQUESTED, DISPUTE, REVERSAL)
- Processar restauracao (RESTORED)
- Processar outros eventos (ANTICIPATED, CAPTURE_REFUSED, etc.)

Extraido de: app/webhooks/pagamentos.py (Fase 3.9)
"""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


async def atualizar_status_cobranca(
    supabase: Any,
    payment: Dict[str, Any],
    agent_id: Optional[str],
    status: str,
    extra_fields: Optional[Dict[str, Any]] = None,
    billing_status: Optional[str] = None,
) -> None:
    """
    Helper generico para atualizar status de cobranca.

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


async def processar_pagamento_vencido(
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


async def processar_pagamento_estornado(
    supabase: Any,
    payment: Dict[str, Any],
    agent_id: Optional[str],
) -> None:
    """
    Processa PAYMENT_REFUNDED.

    Cobranca foi estornada (devolucao total).
    Atualiza status para REFUNDED.
    Reverte ia_recebeu para nao contar no dashboard como coletado pela IA.
    """
    extra_fields = {
        "refund_date": datetime.utcnow().isoformat(),
        "ia_recebeu": False,
        "ia_recebeu_at": None,
        "ia_recebeu_step": None,
        "ia_recebeu_days_from_due": None,
    }
    await atualizar_status_cobranca(
        supabase, payment, agent_id,
        status="REFUNDED",
        extra_fields=extra_fields,
        billing_status="refunded",
    )


async def processar_pagamento_estornado_parcial(
    supabase: Any,
    payment: Dict[str, Any],
    agent_id: Optional[str],
) -> None:
    """
    Processa PAYMENT_PARTIALLY_REFUNDED.

    Cobranca foi parcialmente estornada.
    Atualiza status para PARTIALLY_REFUNDED para manter paridade com Asaas.
    Reverte ia_recebeu para nao contar no dashboard como coletado pela IA.
    """
    extra_fields = {
        "refund_date": datetime.utcnow().isoformat(),
        "ia_recebeu": False,
        "ia_recebeu_at": None,
        "ia_recebeu_step": None,
        "ia_recebeu_days_from_due": None,
    }
    await atualizar_status_cobranca(
        supabase, payment, agent_id,
        status="PARTIALLY_REFUNDED",
        extra_fields=extra_fields,
        billing_status="refunded",
    )


async def processar_chargeback_solicitado(
    supabase: Any,
    payment: Dict[str, Any],
    agent_id: Optional[str],
) -> None:
    """
    Processa PAYMENT_CHARGEBACK_REQUESTED.

    Cliente solicitou chargeback (contestacao no cartao).
    CRITICO: Requer acao imediata do lojista.
    Reverte ia_recebeu para nao contar no dashboard como coletado pela IA.
    """
    extra_fields = {
        "chargeback_requested_at": datetime.utcnow().isoformat(),
        "ia_recebeu": False,
        "ia_recebeu_at": None,
        "ia_recebeu_step": None,
        "ia_recebeu_days_from_due": None,
    }
    await atualizar_status_cobranca(
        supabase, payment, agent_id,
        status="CHARGEBACK_REQUESTED",
        extra_fields=extra_fields,
        billing_status="chargeback",
    )
    logger.warning(
        "[ASAAS WEBHOOK] CHARGEBACK SOLICITADO! Payment: %s | Valor: R$ %.2f",
        payment.get("id"), payment.get("value", 0)
    )


async def processar_chargeback_disputa(
    supabase: Any,
    payment: Dict[str, Any],
    agent_id: Optional[str],
) -> None:
    """
    Processa PAYMENT_CHARGEBACK_DISPUTE.

    Chargeback esta em processo de disputa.
    """
    extra_fields = {
        "chargeback_dispute_at": datetime.utcnow().isoformat(),
    }
    await atualizar_status_cobranca(
        supabase, payment, agent_id,
        status="CHARGEBACK_DISPUTE",
        extra_fields=extra_fields,
        billing_status="chargeback",
    )


async def processar_aguardando_reversao_chargeback(
    supabase: Any,
    payment: Dict[str, Any],
    agent_id: Optional[str],
) -> None:
    """
    Processa PAYMENT_AWAITING_CHARGEBACK_REVERSAL.

    Aguardando reversao do chargeback pela bandeira.
    """
    await atualizar_status_cobranca(
        supabase, payment, agent_id,
        status="AWAITING_CHARGEBACK_REVERSAL",
        billing_status="chargeback",
    )


async def processar_pagamento_restaurado(
    supabase: Any,
    payment: Dict[str, Any],
    agent_id: Optional[str],
) -> None:
    """
    Processa PAYMENT_RESTORED.

    Cobranca restaurada (ex: apos reversao de chargeback).
    Volta ao status PENDING.
    """
    extra_fields = {
        "restored_at": datetime.utcnow().isoformat(),
        "chargeback_requested_at": None,
        "chargeback_dispute_at": None,
        "refund_date": None,
    }
    await atualizar_status_cobranca(
        supabase, payment, agent_id,
        status="PENDING",
        extra_fields=extra_fields,
        billing_status="pending",
    )


async def processar_pagamento_dinheiro_desfeito(
    supabase: Any,
    payment: Dict[str, Any],
    agent_id: Optional[str],
) -> None:
    """
    Processa PAYMENT_RECEIVED_IN_CASH_UNDONE.

    Confirmacao de recebimento em dinheiro foi desfeita.
    Volta ao status PENDING.
    """
    await atualizar_status_cobranca(
        supabase, payment, agent_id,
        status="PENDING",
        billing_status="pending",
    )


async def processar_pagamento_antecipado(
    supabase: Any,
    payment: Dict[str, Any],
    agent_id: Optional[str],
) -> None:
    """
    Processa PAYMENT_ANTICIPATED.

    Cobranca foi antecipada (recebimento antes do prazo normal).
    """
    extra_fields = {
        "anticipated_at": datetime.utcnow().isoformat(),
    }
    await atualizar_status_cobranca(
        supabase, payment, agent_id,
        status="RECEIVED",
        extra_fields=extra_fields,
        billing_status="paid",
    )


async def processar_captura_cartao_recusada(
    supabase: Any,
    payment: Dict[str, Any],
    agent_id: Optional[str],
) -> None:
    """
    Processa PAYMENT_CREDIT_CARD_CAPTURE_REFUSED.

    Captura do cartao de credito foi recusada apos pre-autorizacao.
    """
    await atualizar_status_cobranca(
        supabase, payment, agent_id,
        status="FAILED",
        billing_status="failed",
    )
