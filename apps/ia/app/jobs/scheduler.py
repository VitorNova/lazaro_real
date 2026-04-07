# ╔════════════════════════════════════════════════════════════╗
# ║  SCHEDULER — Agenda de todos os jobs automaticos           ║
# ╚════════════════════════════════════════════════════════════╝
"""
APScheduler configuration and job registration.

This module provides:
- Scheduler initialization
- Job registration for all scheduled tasks
- Scheduler lifecycle management
"""

import os
import structlog
from typing import Optional, Any

logger = structlog.get_logger(__name__)

# Controle do job de billing da tarde (16h45)
# Default: true (habilitado). Para desativar: BILLING_AFTERNOON_JOB_ENABLED=false
BILLING_AFTERNOON_ENABLED = os.getenv("BILLING_AFTERNOON_JOB_ENABLED", "true").lower() == "true"


def create_scheduler() -> Optional[Any]:
    """
    Create and configure the APScheduler instance.

    Returns:
        AsyncIOScheduler instance or None if APScheduler is not available
    """
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        return AsyncIOScheduler(
            job_defaults={'misfire_grace_time': 3600}
        )
    except ImportError:
        logger.warning("APScheduler not installed")
        return None


def register_jobs(scheduler: Any) -> None:
    """
    Register all scheduled jobs.

    Args:
        scheduler: AsyncIOScheduler instance
    """
    from apscheduler.triggers.cron import CronTrigger

    from app.cobranca.job_cobranca import run_billing_v2
    from app.jobs.reconciliar_contratos import run_contract_reconciliation_job
    from app.jobs.reconciliar_pagamentos import run_billing_reconciliation_job
    from app.jobs.notificar_manutencoes import run_maintenance_notifier_job
    from app.jobs.retry_deferred_job import retry_deferred_dispatches

    # Reconciliacao contratos: 5h30, seg-sex (ANTES da reconciliacao de pagamentos)
    scheduler.add_job(
        run_contract_reconciliation_job,
        CronTrigger(hour=5, minute=30, day_of_week="mon-fri", timezone="America/Sao_Paulo"),
        id="contract_reconciliation",
        name="Contract Reconciliation Job",
        replace_existing=True,
    )

    # Reconciliacao pagamentos: 6h horario de Brasilia, seg-sex (ANTES do billing charge)
    scheduler.add_job(
        run_billing_reconciliation_job,
        CronTrigger(hour=6, minute=0, day_of_week="mon-fri", timezone="America/Sao_Paulo"),
        id="billing_reconciliation",
        name="Billing Reconciliation Job",
        replace_existing=True,
    )

    # Reconciliacao pagamentos: 14h — captura mudanças do período da manhã
    scheduler.add_job(
        run_billing_reconciliation_job,
        CronTrigger(hour=14, minute=0, day_of_week="mon-fri", timezone="America/Sao_Paulo"),
        id="billing_reconciliation_afternoon",
        name="Billing Reconciliation Job - Tarde",
        replace_existing=True,
    )

    # Cobranca: 9h horario de Brasilia, seg-sex (DEPOIS da reconciliacao)
    scheduler.add_job(
        run_billing_v2,
        CronTrigger(hour=9, minute=0, day_of_week="mon-fri", timezone="America/Sao_Paulo"),
        id="billing_charge",
        name="Billing Charge Job V2",
        replace_existing=True,
    )

    # Cobranca tarde: 16h45 horario de Brasilia, seg-sex
    # Mesmo job, segundo horário para alcançar clientes ocupados pela manhã
    # Proteção contra duplicata via claim_notification (UNIQUE constraint)
    if BILLING_AFTERNOON_ENABLED:
        scheduler.add_job(
            run_billing_v2,
            CronTrigger(hour=16, minute=45, day_of_week="mon-fri", timezone="America/Sao_Paulo"),
            id="billing_charge_afternoon",
            name="Billing Charge Job V2 - Tarde",
            replace_existing=True,
        )

    # Manutencao preventiva (ANA/Lazaro): 09:00 dias uteis, timezone Cuiaba
    scheduler.add_job(
        run_maintenance_notifier_job,
        CronTrigger(hour=9, minute=0, day_of_week="mon-fri", timezone="America/Cuiaba"),
        id="maintenance_notifier",
        name="Maintenance Notifier Job (ANA)",
        replace_existing=True,
    )

    # Retry de dispatches adiados: 14h e 18h, seg-sex
    scheduler.add_job(
        retry_deferred_dispatches,
        CronTrigger(hour="14,18", minute=0, day_of_week="mon-fri", timezone="America/Sao_Paulo"),
        id="retry_deferred_dispatches",
        name="Retry Deferred Dispatches",
        replace_existing=True,
    )

    jobs_msg = (
        "APScheduler jobs registered: "
        "billing_reconciliation (6h,14h seg-sex), "
        "billing_charge (9h seg-sex), "
    )
    if BILLING_AFTERNOON_ENABLED:
        jobs_msg += "billing_charge_afternoon (16h45 seg-sex), "
    jobs_msg += (
        "maintenance_notifier (9h seg-sex Cuiaba), "
        "retry_deferred_dispatches (14h,18h seg-sex)"
    )
    logger.info(jobs_msg)


def start_scheduler(scheduler: Any) -> bool:
    """
    Start the scheduler.

    Args:
        scheduler: AsyncIOScheduler instance

    Returns:
        True if started successfully, False otherwise
    """
    try:
        register_jobs(scheduler)
        scheduler.start()
        return True
    except Exception as e:
        logger.error("Failed to start APScheduler", error=str(e))
        return False


def stop_scheduler(scheduler: Any) -> None:
    """
    Stop the scheduler gracefully.

    Args:
        scheduler: AsyncIOScheduler instance
    """
    if scheduler:
        try:
            scheduler.shutdown(wait=False)
            logger.info("APScheduler stopped")
        except Exception as e:
            logger.error("Error stopping APScheduler", error=str(e))
