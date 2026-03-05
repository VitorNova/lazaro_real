"""
Tools de Manutenção - PONTE para domain/maintenance/services/equipment_tools.py

Este arquivo é uma ponte para manter compatibilidade com imports legados.
A implementação real está em: app/domain/maintenance/services/equipment_tools.py

Migrado na Fase 9.6 da refatoração.
"""

# Re-exportar tudo de equipment_tools para compatibilidade
from app.domain.maintenance.services.equipment_tools import (
    MAINTENANCE_FUNCTION_DECLARATIONS,
    analisar_foto_equipamento,
    confirmar_agendamento_manutencao,
    identificar_equipamento,
    verificar_disponibilidade_manutencao,
)

__all__ = [
    "MAINTENANCE_FUNCTION_DECLARATIONS",
    "identificar_equipamento",
    "analisar_foto_equipamento",
    "verificar_disponibilidade_manutencao",
    "confirmar_agendamento_manutencao",
]
