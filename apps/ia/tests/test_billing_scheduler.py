# tests/test_billing_scheduler.py
"""
TDD — Segundo job de billing às 16h45 — 2026-03-19

Contexto: Adicionar segundo disparo do job de billing às 16h45
Causa: Clientes que estão ocupados às 9h podem ser alcançados à tarde
Correção: Novo job billing_charge_afternoon no scheduler
"""

import os
import pytest
from unittest.mock import MagicMock, patch


class TestBillingSchedulerAfternoon:
    """
    TDD — Segundo job de billing às 16h45

    Requisitos:
    - Job da tarde é registrado quando BILLING_AFTERNOON_JOB_ENABLED=true
    - Job da tarde NÃO é registrado quando BILLING_AFTERNOON_JOB_ENABLED=false
    - Job da tarde é agendado para 16h45 seg-sex
    - Job da manhã (billing_charge) permanece inalterado
    """

    def test_job_afternoon_registrado_quando_env_true(self):
        """Job da tarde é registrado quando BILLING_AFTERNOON_JOB_ENABLED=true"""
        with patch.dict(os.environ, {"BILLING_AFTERNOON_JOB_ENABLED": "true"}):
            # Reimportar para pegar nova env
            from importlib import reload
            import app.jobs.scheduler as scheduler_module

            reload(scheduler_module)

            scheduler = MagicMock()
            scheduler_module.register_jobs(scheduler)

            job_ids = [call.kwargs["id"] for call in scheduler.add_job.call_args_list]
            assert "billing_charge_afternoon" in job_ids, (
                f"Job billing_charge_afternoon não foi registrado. Jobs: {job_ids}"
            )

    def test_job_afternoon_nao_registrado_quando_env_false(self):
        """Job da tarde NÃO é registrado quando BILLING_AFTERNOON_JOB_ENABLED=false"""
        with patch.dict(os.environ, {"BILLING_AFTERNOON_JOB_ENABLED": "false"}):
            from importlib import reload
            import app.jobs.scheduler as scheduler_module

            reload(scheduler_module)

            scheduler = MagicMock()
            scheduler_module.register_jobs(scheduler)

            job_ids = [call.kwargs["id"] for call in scheduler.add_job.call_args_list]
            assert "billing_charge_afternoon" not in job_ids, (
                f"Job billing_charge_afternoon NÃO deveria ter sido registrado. Jobs: {job_ids}"
            )

    def test_job_afternoon_horario_correto(self):
        """Job da tarde é agendado para 16h45"""
        with patch.dict(os.environ, {"BILLING_AFTERNOON_JOB_ENABLED": "true"}):
            from importlib import reload
            import app.jobs.scheduler as scheduler_module

            reload(scheduler_module)

            scheduler = MagicMock()
            scheduler_module.register_jobs(scheduler)

            # Encontrar a chamada do job da tarde
            afternoon_call = None
            for call in scheduler.add_job.call_args_list:
                if call.kwargs.get("id") == "billing_charge_afternoon":
                    afternoon_call = call
                    break

            assert afternoon_call is not None, "Job billing_charge_afternoon não encontrado"

            trigger = afternoon_call.args[1]

            # Verificar hora=16, minute=45 usando nome do campo (não índice)
            hour_field = next(f for f in trigger.fields if f.name == "hour")
            minute_field = next(f for f in trigger.fields if f.name == "minute")

            assert hour_field.expressions[0].first == 16, (
                f"Hora deveria ser 16, mas é {hour_field.expressions[0].first}"
            )
            assert minute_field.expressions[0].first == 45, (
                f"Minuto deveria ser 45, mas é {minute_field.expressions[0].first}"
            )

    def test_job_manha_mantido_inalterado(self):
        """Job da manhã (billing_charge) permanece com ID original"""
        with patch.dict(os.environ, {"BILLING_AFTERNOON_JOB_ENABLED": "true"}):
            from importlib import reload
            import app.jobs.scheduler as scheduler_module

            reload(scheduler_module)

            scheduler = MagicMock()
            scheduler_module.register_jobs(scheduler)

            job_ids = [call.kwargs["id"] for call in scheduler.add_job.call_args_list]

            # billing_charge deve existir (não foi renomeado para billing_charge_morning)
            assert "billing_charge" in job_ids, (
                f"Job billing_charge deveria existir. Jobs: {job_ids}"
            )
            # billing_charge_morning NÃO deve existir
            assert "billing_charge_morning" not in job_ids, (
                f"Job billing_charge_morning NÃO deveria existir. Jobs: {job_ids}"
            )

    def test_job_afternoon_usa_mesma_funcao_run_billing_v2(self):
        """Job da tarde usa a mesma função run_billing_v2 do job da manhã"""
        with patch.dict(os.environ, {"BILLING_AFTERNOON_JOB_ENABLED": "true"}):
            from importlib import reload
            import app.jobs.scheduler as scheduler_module

            reload(scheduler_module)

            scheduler = MagicMock()
            scheduler_module.register_jobs(scheduler)

            # Encontrar funções usadas por cada job
            morning_func = None
            afternoon_func = None

            for call in scheduler.add_job.call_args_list:
                job_id = call.kwargs.get("id")
                func = call.args[0]

                if job_id == "billing_charge":
                    morning_func = func
                elif job_id == "billing_charge_afternoon":
                    afternoon_func = func

            assert afternoon_func is not None, "Job billing_charge_afternoon não encontrado"
            assert morning_func is not None, "Job billing_charge não encontrado"
            assert morning_func == afternoon_func, (
                "Job da tarde deveria usar a mesma função do job da manhã"
            )
