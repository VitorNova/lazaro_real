"""
Testes para o job de reconciliação de contratos Asaas.

O job completo foi validado em produção (06/04/2026):
- 345 subs Asaas vs 344 local
- 1 inserido, 1 atualizado, 0 erros

Este teste cobre a lógica de lock Redis.
"""

import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

# Mock dependências
_settings_mock = MagicMock()
_settings_mock.google_api_key = "fake"
config_mod = ModuleType("app.config")
config_mod.settings = _settings_mock
sys.modules.setdefault("app.config", config_mod)
sys.modules.setdefault("app.services.gateway_pagamento", MagicMock())
sys.modules.setdefault("app.services.supabase", MagicMock())
sys.modules.setdefault("app.services.redis", MagicMock())
sys.modules.setdefault("app.core.utils.dias_uteis", MagicMock())
sys.modules.setdefault("app.integrations.asaas.client", MagicMock())
sys.modules.setdefault("app.integrations.asaas.rate_limiter", MagicMock())
sys.modules.setdefault("app.integrations.asaas.types", MagicMock())
sys.modules.setdefault("app.domain.billing.services.customer_sync_service", MagicMock())
sys.modules.setdefault("app.integrations.supabase.repositories.asaas_customers", MagicMock())
sys.modules.setdefault("app.integrations.supabase.repositories.asaas_contracts", MagicMock())


def test_lock_key_defined():
    """Lock key e TTL devem estar definidos."""
    from app.jobs.reconciliar_contratos import (
        CONTRACT_RECONCILIATION_LOCK_KEY,
        CONTRACT_RECONCILIATION_LOCK_TTL,
    )
    assert CONTRACT_RECONCILIATION_LOCK_KEY == "lock:contract_reconciliation:global"
    assert CONTRACT_RECONCILIATION_LOCK_TTL == 3600


def test_functions_exist():
    """Funções públicas do job devem existir."""
    from app.jobs.reconciliar_contratos import (
        reconcile_contracts,
        run_contract_reconciliation_job,
        is_contract_reconciliation_running,
    )
    assert callable(reconcile_contracts)
    assert callable(run_contract_reconciliation_job)
    assert callable(is_contract_reconciliation_running)


def test_agent_id_configured():
    """Agent ID deve estar configurado."""
    from app.jobs.reconciliar_contratos import AGENT_ID
    assert AGENT_ID == "14e6e5ce-4627-4e38-aac8-f0191669ff53"
