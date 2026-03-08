"""
APScheduler configuration and job registration.

This module provides:
- Scheduler initialization
- Job registration for all scheduled tasks
- Scheduler lifecycle management
"""

import structlog
from typing import Optional, Any

logger = structlog.get_logger(__name__)


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
    from apscheduler.triggers.interval import IntervalTrigger

    from app.jobs.billing_job_v2 import run_billing_v2
    from app.jobs.reconciliar_pagamentos import run_billing_reconciliation_job
    from app.jobs.confirmar_agendamentos import run_calendar_confirmation_job
    from app.jobs.reengajar_leads import run_follow_up_job
    from app.jobs.notificar_manutencoes import run_maintenance_notifier_job

    # Reconciliacao: 6h horario de Brasilia, seg-sex (ANTES do billing charge)
    scheduler.add_job(
        run_billing_reconciliation_job,
        CronTrigger(hour=6, minute=0, day_of_week="mon-fri", timezone="America/Sao_Paulo"),
        id="billing_reconciliation",
        name="Billing Reconciliation Job",
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

    # Calendar confirmation: a cada 30 minutos
    scheduler.add_job(
        run_calendar_confirmation_job,
        IntervalTrigger(minutes=30),
        id="calendar_confirmation",
        name="Calendar Confirmation Job",
        replace_existing=True,
    )

    # Follow-up (Salvador): a cada 5 minutos
    scheduler.add_job(
        run_follow_up_job,
        IntervalTrigger(minutes=5),
        id="follow_up",
        name="Follow Up Job (Salvador)",
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

    logger.info(
        "APScheduler jobs registered: "
        "billing_reconciliation (6h seg-sex), "
        "billing_charge (9h seg-sex), "
        "calendar_confirmation (30min), "
        "follow_up (5min), "
        "maintenance_notifier (9h seg-sex Cuiaba)"
    )


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
