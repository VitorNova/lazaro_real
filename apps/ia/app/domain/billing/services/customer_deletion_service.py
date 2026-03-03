"""
Servico de delecao de clientes Asaas.

Responsavel por:
- Soft delete de clientes (CUSTOMER_DELETED)
- Soft delete de contratos relacionados
- Soft delete de cobrancas relacionadas
- Soft delete de contract_details relacionados

Extraido de: app/webhooks/pagamentos.py (Fase 3.5)
"""

import logging
from datetime import datetime
from typing import Any, Dict

logger = logging.getLogger(__name__)


async def processar_cliente_deletado(
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
