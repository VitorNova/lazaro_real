"""
Domain Maintenance Services - Manutenção Preventiva.

Módulos:
- slots_service: Controle de slots de agendamento (manhã/tarde)
- equipment_tools: Tools de identificação e agendamento de manutenção
"""

from .slots_service import (
    TIMEZONE_LAZARO,
    AGENT_ID_LAZARO,
    PERIODOS,
    SERVICE_NAME,
    verificar_slot,
    listar_slots_disponiveis,
    registrar_agendamento,
)

from .equipment_tools import (
    identificar_equipamento,
    analisar_foto_equipamento,
    verificar_disponibilidade_manutencao,
    confirmar_agendamento_manutencao,
    MAINTENANCE_FUNCTION_DECLARATIONS,
)

__all__ = [
    # Slots
    "TIMEZONE_LAZARO",
    "AGENT_ID_LAZARO",
    "PERIODOS",
    "SERVICE_NAME",
    "verificar_slot",
    "listar_slots_disponiveis",
    "registrar_agendamento",
    # Equipment tools
    "identificar_equipamento",
    "analisar_foto_equipamento",
    "verificar_disponibilidade_manutencao",
    "confirmar_agendamento_manutencao",
    "MAINTENANCE_FUNCTION_DECLARATIONS",
]
