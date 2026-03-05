"""
Billing Charge Job - Regua de cobranca automatizada via WhatsApp.

THIN DISPATCHER - Refatorado na Fase 3.
A logica de negocio foi movida para domain/billing/services/.

Fluxo:
1. Adquire lock distribuido (Redis)
2. Verifica dia util e horario comercial
3. Busca agentes com Asaas configurado
4. Processa cobrancas via billing_orchestrator
5. Libera lock
"""

import logging
import traceback
from typing import Any, Dict

from app.core.utils.dias_uteis import (
    get_today_brasilia,
    is_business_day,
    is_business_hours,
)

# Imports do domain/billing/services
from app.domain.billing.services import (
    acquire_billing_lock,
    release_billing_lock,
    is_billing_job_running,
    get_agents_with_asaas,
    process_agent_billing,
)

logger = logging.getLogger(__name__)


def _log(msg: str) -> None:
    """Log com prefixo do job."""
    logger.info(f"[BILLING JOB] {msg}")


def _log_warn(msg: str) -> None:
    logger.warning(f"[BILLING JOB] {msg}")


def _log_error(msg: str) -> None:
    logger.error(f"[BILLING JOB] {msg}")


async def process_billing_charges() -> Dict[str, Any]:
    """
    Processa todos os agentes com Asaas configurado.
    Retorna resumo da execucao.
    """
    # Tenta adquirir lock distribuido
    if not await acquire_billing_lock():
        return {"status": "skipped", "reason": "already_running"}

    today = get_today_brasilia()

    # So executa em dias uteis
    if not is_business_day(today):
        await release_billing_lock()
        _log("Hoje nao e dia util, pulando execucao")
        return {"status": "skipped", "reason": "not_business_day"}

    # Verifica horario comercial (8h-20h)
    if not is_business_hours(8, 20):
        await release_billing_lock()
        _log("Fora do horario comercial, pulando execucao")
        return {"status": "skipped", "reason": "outside_business_hours"}

    _log("Iniciando processamento de cobrancas...")

    total_stats = {"sent": 0, "skipped": 0, "errors": 0, "agents_processed": 0}

    try:
        agents = await get_agents_with_asaas()
        _log(f"Encontrados {len(agents)} agentes com Asaas configurado")

        for agent in agents:
            try:
                agent_stats = await process_agent_billing(agent)
                total_stats["sent"] += agent_stats["sent"]
                total_stats["skipped"] += agent_stats["skipped"]
                total_stats["errors"] += agent_stats["errors"]
                total_stats["agents_processed"] += 1
            except Exception as e:
                _log_error(f"Erro ao processar agente {agent.get('name')}: {e}")

        _log(
            f"Job finalizado: {total_stats['sent']} mensagens enviadas, "
            f"{total_stats['skipped']} puladas, {total_stats['errors']} erros"
        )

        return {"status": "completed", "stats": total_stats}

    except Exception as e:
        _log_error(f"Erro no processamento de cobrancas: {e}")
        return {"status": "error", "error": str(e)}

    finally:
        await release_billing_lock()


async def run_billing_charge_job() -> Dict[str, Any]:
    """Entry point para o scheduler / execucao manual."""
    _log("Executando billing charge job...")
    return await process_billing_charges()


async def is_billing_charge_running() -> bool:
    """Verifica se o job esta rodando (via lock Redis)."""
    return await is_billing_job_running()


async def _force_run_billing_charge() -> Dict[str, Any]:
    """
    Versao forcada do job - ignora verificacoes de horario/dia util.
    APENAS PARA DEBUG/TESTES.
    """
    if not await acquire_billing_lock():
        return {"status": "skipped", "reason": "already_running"}

    _log("=== EXECUCAO FORCADA (ignorando horario/dia util) ===")

    total_stats = {"sent": 0, "skipped": 0, "errors": 0, "agents_processed": 0}

    try:
        agents = await get_agents_with_asaas()
        _log(f"Encontrados {len(agents)} agentes com Asaas configurado")

        if not agents:
            _log("Nenhum agente com Asaas configurado encontrado")
            return {"status": "completed", "stats": total_stats, "message": "no_agents"}

        for agent in agents:
            _log(f"Processando agente: {agent.get('name')} ({agent.get('id')})")
            try:
                agent_stats = await process_agent_billing(agent)
                total_stats["sent"] += agent_stats.get("sent", 0)
                total_stats["skipped"] += agent_stats.get("skipped", 0)
                total_stats["errors"] += agent_stats.get("errors", 0)
                total_stats["agents_processed"] += 1
                _log(f"Agente {agent.get('name')}: {agent_stats}")
            except Exception as e:
                _log_error(f"Erro ao processar agente {agent.get('name')}: {e}")
                _log_error(traceback.format_exc())

        _log(
            f"=== Job finalizado: {total_stats['sent']} enviadas, "
            f"{total_stats['skipped']} puladas, {total_stats['errors']} erros ==="
        )

        return {"status": "completed", "stats": total_stats}

    except Exception as e:
        _log_error(f"Erro no processamento: {e}")
        _log_error(traceback.format_exc())
        return {"status": "error", "error": str(e)}

    finally:
        await release_billing_lock()
