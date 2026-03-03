"""
Billing Rules Service - Regras de negocio para cobranca automatica.

Extraido de: app/jobs/cobrar_clientes.py (Fase 4.6)

Funcionalidades:
- Verificacao se pagamento deve ser pulado (cartao pendente)
- Busca de agentes com Asaas configurado
"""

import logging
from typing import Any, Dict, List

from app.services.supabase import get_supabase_service

from app.domain.billing.models.billing_config import CARD_BILLING_TYPES

logger = logging.getLogger(__name__)


def _log(msg: str) -> None:
    """Log com prefixo do job."""
    logger.info(f"[BILLING JOB] {msg}")


def _log_warn(msg: str) -> None:
    logger.warning(f"[BILLING JOB] {msg}")


def _log_error(msg: str) -> None:
    logger.error(f"[BILLING JOB] {msg}")


def should_skip_payment(
    payment: Dict[str, Any],
    is_overdue: bool = False,
) -> bool:
    """
    Verifica se o pagamento deve ser ignorado.

    Regras:
    - Cartao PENDING: pular (cobrado automaticamente pelo Asaas)
    - Cartao OVERDUE: processar (pagamento falhou)
    - Assinaturas boleto/pix: processar normalmente

    Args:
        payment: Dados do pagamento
        is_overdue: Se esta processando pagamentos vencidos

    Returns:
        True se deve pular, False se deve processar
    """
    billing_type = payment.get("billing_type", "")
    if billing_type in CARD_BILLING_TYPES and not is_overdue:
        return True

    return False


async def get_agents_with_asaas() -> List[Dict[str, Any]]:
    """
    Busca agentes com Asaas configurado e cobranca habilitada.

    Cobranca automatica e HABILITADA POR PADRAO para todos com asaas_api_key.
    So e desabilitada se explicitamente: asaas_config.autoCollection.enabled = false

    Retorna lista de agentes com campos:
    - id, name, asaas_api_key, asaas_config
    - uazapi_base_url, uazapi_token, uazapi_instance_id
    - table_leads, table_messages, handoff_triggers
    """
    supabase = get_supabase_service()
    try:
        response = (
            supabase.client.table("agents")
            .select(
                "id, name, asaas_api_key, asaas_config, "
                "uazapi_base_url, uazapi_token, uazapi_instance_id, "
                "table_leads, table_messages, handoff_triggers"
            )
            .eq("status", "active")
            .not_.is_("asaas_api_key", "null")
            .neq("asaas_api_key", "")
            .execute()
        )

        agents = response.data or []

        # Filtrar: so pula se explicitamente enabled === false
        result = []
        for agent in agents:
            asaas_config = agent.get("asaas_config") or {}
            auto_collection = asaas_config.get("autoCollection") or {}
            enabled = auto_collection.get("enabled")
            # Se nao definido ou True, processa. So pula se explicitamente False
            if enabled is not False:
                result.append(agent)

        return result

    except Exception as e:
        _log_error(f"Erro ao buscar agentes com Asaas: {e}")
        return []
