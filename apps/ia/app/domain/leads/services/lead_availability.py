"""
Lead Availability Service - Verifica se lead está disponível para disparo.

Usado por jobs de billing e manutenção para evitar disparar mensagens
automáticas quando o lead está em atendimento humano.

Cenários de indisponibilidade:
- Lead em fila humana (453, 454)
- Agent sem table_leads configurado

REMOVIDOS em 2026-03-19 (Cenário 2 — billing só bloqueia em fila humana):
- current_state='human' — só fila 453/454 indica atendimento real
- Atendimento_Finalizado='false' — significa ticket FECHADO, não em andamento
- Redis pause — redundante com billing_exceptions

Estratégia de erro: Fail-open (em caso de erro, permite disparo).
"""

import structlog
from typing import Optional, Tuple

from app.services.supabase import get_supabase_service
from app.integrations.leadbox.types import QUEUE_ATENDIMENTO, QUEUE_FINANCEIRO

logger = structlog.get_logger(__name__)

# Filas humanas onde NÃO devemos disparar mensagens automáticas
HUMAN_QUEUES = {QUEUE_ATENDIMENTO, QUEUE_FINANCEIRO}  # 453, 454


async def check_lead_availability(
    agent: dict,
    phone: str,
    agent_id: str,
) -> Tuple[bool, Optional[str]]:
    """
    Verifica se lead está disponível para receber disparo automático.

    Args:
        agent: Dicionário do agente com table_leads
        phone: Número de telefone do lead (sem @s.whatsapp.net)
        agent_id: UUID do agente

    Returns:
        Tuple[bool, Optional[str]]: (disponível, motivo_se_indisponível)

    Exemplos:
        >>> available, reason = await check_lead_availability(agent, "5511999999999", agent_id)
        >>> if not available:
        ...     await dispatch_logger.log_deferred(phone, "billing", reason, context)
    """
    remotejid = f"{phone}@s.whatsapp.net"
    table_leads = agent.get("table_leads")

    # 0. Agent sem table_leads configurado
    if not table_leads:
        logger.warning(
            "[AVAILABILITY] Agent sem table_leads",
            agent_id=agent_id[:8] if agent_id else "N/A",
        )
        return False, "no_table_leads"

    try:
        supabase = get_supabase_service()

        # 1. Buscar estado no Supabase (só precisa de current_queue_id)
        response = (
            supabase.client.table(table_leads)
            .select("current_queue_id")
            .eq("remotejid", remotejid)
            .limit(1)
            .execute()
        )

        if not response.data:
            # Lead não existe, pode disparar (será criado)
            logger.debug(
                "[AVAILABILITY] Lead não existe, disponível",
                phone=phone[-4:],
            )
            return True, None

        lead = response.data[0]
        current_queue = lead.get("current_queue_id")

        # 2. Verificar se está em fila humana (453, 454)
        if current_queue in HUMAN_QUEUES:
            logger.info(
                "[AVAILABILITY] Lead em fila humana",
                phone=phone[-4:],
                queue=current_queue,
            )
            return False, f"human_queue_{current_queue}"

        # Lead disponível
        return True, None

    except Exception as e:
        # Decisão: fail-open intencional (2026-03-19)
        # Motivo: job roda 1x/dia sem retry intraday.
        # Perder o disparo do dia é pior do que disparar sem
        # confirmar fila. billing_exceptions ainda protege opt-outs.
        logger.error(
            "[AVAILABILITY] Erro ao verificar, fail-open",
            error=str(e),
            phone=phone[-4:],
        )
        return True, None
