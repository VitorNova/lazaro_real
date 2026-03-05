"""
Domain Maintenance Services - Manutenção Preventiva.

Módulos:
- slots_service: Controle de slots de agendamento (manhã/tarde)
- equipment_tools: Tools de identificação e agendamento de manutenção
- notification_service: Lógica de notificação D-7
"""

from .notification_service import (
    calcular_proxima_manutencao,
    get_customer_phone,
    format_maintenance_message,
    extract_equipamento_info,
    fetch_contracts_for_maintenance,
    mark_notification_sent,
    already_notified_this_cycle,
    get_maintenance_agent,
    process_maintenance_notifications,
    test_maintenance_notification,
    NOTIFY_DAYS_BEFORE,
    AGENT_ID_LAZARO,
    DEFAULT_MAINTENANCE_MESSAGE,
)

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
    # Notification service
    "calcular_proxima_manutencao",
    "get_customer_phone",
    "format_maintenance_message",
    "extract_equipamento_info",
    "fetch_contracts_for_maintenance",
    "mark_notification_sent",
    "already_notified_this_cycle",
    "get_maintenance_agent",
    "process_maintenance_notifications",
    "test_maintenance_notification",
    "NOTIFY_DAYS_BEFORE",
    "AGENT_ID_LAZARO",
    "DEFAULT_MAINTENANCE_MESSAGE",
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
