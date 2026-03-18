"""
Job control endpoints for scheduled tasks.

This module provides endpoints for:
- Billing charge job
- Billing reconciliation job
- Calendar confirmation job
- Follow-up job (Salvador)
- Maintenance notifier job
"""

from typing import Any, Dict

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends

from app.core.config import app_state
from app.middleware.auth import get_current_user, require_admin

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


# =============================================================================
# BILLING CHARGE JOB
# =============================================================================

@router.post("/billing-charge/run")
async def run_billing_charge_manually(
    background_tasks: BackgroundTasks,
    _admin: dict = Depends(require_admin),  # SECURITY: Require admin
) -> Dict[str, Any]:
    """
    Executa o job de cobranca manualmente.
    Roda em background para nao bloquear a request.
    """
    from app.jobs.cobrar_clientes import run_billing_charge_job, is_billing_charge_running

    if await is_billing_charge_running():
        return {"status": "error", "message": "Job ja esta em execucao"}

    background_tasks.add_task(run_billing_charge_job)
    return {"status": "started", "message": "Billing charge job iniciado em background"}


@router.post("/billing-charge/run-force")
async def run_billing_charge_force(
    background_tasks: BackgroundTasks,
    _admin: dict = Depends(require_admin),  # SECURITY: Require admin
) -> Dict[str, Any]:
    """
    Executa o job de cobranca FORCANDO execucao (ignora verificacoes de horario/dia util).
    APENAS PARA DEBUG/TESTES.
    """
    from app.jobs.cobrar_clientes import is_billing_charge_running, _force_run_billing_charge

    if await is_billing_charge_running():
        return {"status": "error", "message": "Job ja esta em execucao"}

    background_tasks.add_task(_force_run_billing_charge)
    return {"status": "started", "message": "Billing charge job FORCADO iniciado em background"}


@router.get("/billing-charge/status")
async def billing_charge_status(
    _user: dict = Depends(get_current_user),  # SECURITY: Require auth
) -> Dict[str, Any]:
    """Retorna o status do job de cobranca."""
    from app.jobs.cobrar_clientes import is_billing_charge_running

    return {
        "running": await is_billing_charge_running(),
        "scheduler_active": app_state.scheduler is not None,
    }


# =============================================================================
# BILLING RECONCILIATION JOB
# =============================================================================

@router.post("/billing-reconciliation/run")
async def run_billing_reconciliation_manually(
    background_tasks: BackgroundTasks,
    _admin: dict = Depends(require_admin),
) -> Dict[str, Any]:
    """
    Executa o job de reconciliacao de cobrancas manualmente.
    Sincroniza asaas_cobrancas com API Asaas (fonte da verdade).
    """
    from app.jobs.reconciliar_pagamentos import run_billing_reconciliation_job, is_billing_reconciliation_running

    if await is_billing_reconciliation_running():
        return {"status": "error", "message": "Job ja esta em execucao"}

    background_tasks.add_task(run_billing_reconciliation_job)
    return {"status": "started", "message": "Billing reconciliation job iniciado em background"}


@router.post("/billing-reconciliation/run-force")
async def run_billing_reconciliation_force(
    background_tasks: BackgroundTasks,
    _admin: dict = Depends(require_admin),
) -> Dict[str, Any]:
    """
    Executa o job de reconciliacao FORCANDO execucao.
    APENAS PARA DEBUG/TESTES.
    """
    from app.jobs.reconciliar_pagamentos import is_billing_reconciliation_running, _force_run_billing_reconciliation

    if await is_billing_reconciliation_running():
        return {"status": "error", "message": "Job ja esta em execucao"}

    background_tasks.add_task(_force_run_billing_reconciliation)
    return {"status": "started", "message": "Billing reconciliation job FORCADO iniciado em background"}


@router.get("/billing-reconciliation/status")
async def billing_reconciliation_status(
    _user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Retorna o status do job de reconciliacao."""
    from app.jobs.reconciliar_pagamentos import is_billing_reconciliation_running

    return {
        "running": await is_billing_reconciliation_running(),
        "scheduler_active": app_state.scheduler is not None,
    }


# =============================================================================
# CALENDAR CONFIRMATION JOB
# =============================================================================

@router.post("/calendar-confirmation/run")
async def run_calendar_confirmation_manually(
    background_tasks: BackgroundTasks,
    _admin: dict = Depends(require_admin),
) -> Dict[str, Any]:
    """Executa o job de confirmacao de agenda manualmente."""
    from app.jobs.confirmar_agendamentos import run_calendar_confirmation_job, is_calendar_confirmation_running

    if is_calendar_confirmation_running():
        return {"status": "error", "message": "Job ja esta em execucao"}

    background_tasks.add_task(run_calendar_confirmation_job)
    return {"status": "started", "message": "Calendar confirmation job iniciado em background"}


@router.post("/calendar-confirmation/run-force")
async def run_calendar_confirmation_force(
    background_tasks: BackgroundTasks,
    _admin: dict = Depends(require_admin),
) -> Dict[str, Any]:
    """
    Executa o job de confirmacao de agenda FORCANDO execucao.
    APENAS PARA DEBUG/TESTES.
    """
    from app.jobs.confirmar_agendamentos import is_calendar_confirmation_running, _force_run_calendar_confirmation

    if is_calendar_confirmation_running():
        return {"status": "error", "message": "Job ja esta em execucao"}

    background_tasks.add_task(_force_run_calendar_confirmation)
    return {"status": "started", "message": "Calendar confirmation job FORCADO iniciado em background"}


@router.get("/calendar-confirmation/status")
async def calendar_confirmation_status(
    _user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Retorna o status do job de confirmacao de agenda."""
    from app.jobs.confirmar_agendamentos import is_calendar_confirmation_running

    return {
        "running": is_calendar_confirmation_running(),
        "scheduler_active": app_state.scheduler is not None,
    }


# =============================================================================
# FOLLOW-UP JOB (SALVADOR)
# =============================================================================

@router.post("/follow-up/run")
async def run_follow_up_manually(
    background_tasks: BackgroundTasks,
    _admin: dict = Depends(require_admin),
) -> Dict[str, Any]:
    """Executa o job de follow-up manualmente (respeita horario comercial)."""
    from app.jobs.reengajar_leads import run_follow_up_job, is_follow_up_running

    if is_follow_up_running():
        return {"status": "error", "message": "Job ja esta em execucao"}

    background_tasks.add_task(run_follow_up_job)
    return {"status": "started", "message": "Follow-up job iniciado em background"}


@router.post("/follow-up/run-force")
async def run_follow_up_force(
    background_tasks: BackgroundTasks,
    _admin: dict = Depends(require_admin),
) -> Dict[str, Any]:
    """
    Executa o job de follow-up FORCANDO execucao (ignora verificacoes de horario/dia util).
    APENAS PARA DEBUG/TESTES.
    """
    from app.jobs.reengajar_leads import is_follow_up_running, _force_run_follow_up

    if is_follow_up_running():
        return {"status": "error", "message": "Job ja esta em execucao"}

    background_tasks.add_task(_force_run_follow_up)
    return {"status": "started", "message": "Follow-up job FORCADO iniciado em background"}


@router.get("/follow-up/status")
async def follow_up_status(
    _user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Retorna o status do job de follow-up."""
    from app.jobs.reengajar_leads import is_follow_up_running

    return {
        "running": is_follow_up_running(),
        "scheduler_active": app_state.scheduler is not None,
    }


# =============================================================================
# MAINTENANCE NOTIFIER JOB
# =============================================================================

@router.post("/maintenance-notifier/run")
async def run_maintenance_notifier_manually(
    background_tasks: BackgroundTasks,
    _admin: dict = Depends(require_admin),
) -> Dict[str, Any]:
    """
    Executa o job de notificacao de manutencao preventiva manualmente.
    Respeita verificacoes de dia util e horario comercial.
    """
    from app.jobs.notificar_manutencoes import run_maintenance_notifier_job, is_maintenance_notifier_running

    if is_maintenance_notifier_running():
        return {"status": "error", "message": "Job ja esta em execucao"}

    background_tasks.add_task(run_maintenance_notifier_job)
    return {"status": "started", "message": "Maintenance notifier job iniciado em background"}


@router.post("/maintenance-notifier/run-force")
async def run_maintenance_notifier_force(
    background_tasks: BackgroundTasks,
    _admin: dict = Depends(require_admin),
) -> Dict[str, Any]:
    """
    Executa o job de notificacao de manutencao FORCANDO execucao.
    Ignora verificacoes de horario/dia util. APENAS PARA DEBUG/TESTES.
    """
    from app.jobs.notificar_manutencoes import is_maintenance_notifier_running, _force_run_maintenance_notifier

    if is_maintenance_notifier_running():
        return {"status": "error", "message": "Job ja esta em execucao"}

    background_tasks.add_task(_force_run_maintenance_notifier)
    return {"status": "started", "message": "Maintenance notifier job FORCADO iniciado em background"}


@router.get("/maintenance-notifier/status")
async def maintenance_notifier_status(
    _user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Retorna o status do job de manutencao preventiva."""
    from app.jobs.notificar_manutencoes import is_maintenance_notifier_running

    return {
        "running": is_maintenance_notifier_running(),
        "scheduler_active": app_state.scheduler is not None,
    }


@router.post("/maintenance-notifier/test")
async def test_maintenance_notifier(
    phone: str = "556697194084",
    _admin: dict = Depends(require_admin),
) -> Dict[str, Any]:
    """
    Envia notificacao de TESTE para um numero especifico.
    APENAS PARA DEBUG/TESTES.

    Args:
        phone: Numero de telefone (ex: 556697194084)
    """
    from app.jobs.notificar_manutencoes import test_maintenance_notification

    result = await test_maintenance_notification(phone)
    return result
