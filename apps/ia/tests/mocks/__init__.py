# tests/mocks/__init__.py
"""
Mocks centralizados para testes do lazaro-ia.

Este pacote contém:
- supabase: Mocks para SelectChain, UpdateChain, e helpers
- manutencao: Fixtures e constantes para fluxos de manutenção

Uso:
    from tests.mocks.supabase import make_supabase_mock_manutencao
    from tests.mocks.manutencao import CLIENTE_COM_CONTRATO, make_cliente_asaas
"""

from tests.mocks.supabase import (
    SelectChain,
    UpdateChain,
    make_supabase_mock_manutencao,
)

from tests.mocks.manutencao import (
    make_cliente_asaas,
    make_contract_details,
    make_schedule,
    make_conversation_history,
    make_lead_manutencao,
    CLIENTE_COM_CONTRATO,
    CLIENTE_SEM_CONTRATO,
    CONTRATO_NOTIFICADO,
    CONTRATO_AGENDADO,
    AGENDAMENTO_MANHA,
    AGENDAMENTO_TARDE,
    LEAD_PEDINDO_REMARCACAO,
    LEAD_CPF_SALVO,
)

__all__ = [
    # Supabase
    "SelectChain",
    "UpdateChain",
    "make_supabase_mock_manutencao",
    # Manutencao factories
    "make_cliente_asaas",
    "make_contract_details",
    "make_schedule",
    "make_conversation_history",
    "make_lead_manutencao",
    # Manutencao constants
    "CLIENTE_COM_CONTRATO",
    "CLIENTE_SEM_CONTRATO",
    "CONTRATO_NOTIFICADO",
    "CONTRATO_AGENDADO",
    "AGENDAMENTO_MANHA",
    "AGENDAMENTO_TARDE",
    "LEAD_PEDINDO_REMARCACAO",
    "LEAD_CPF_SALVO",
]
