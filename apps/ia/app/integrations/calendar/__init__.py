# ==============================================================================
# GOOGLE CALENDAR INTEGRATION
# Integracao completa com Google Calendar (OAuth2 + Multi-Agenda)
# Baseado na implementacao TypeScript (apps/api/src/services/calendar/)
# ==============================================================================

"""
Google Calendar Integration para Lazaro-v2.

Este modulo fornece:
- GoogleCalendarClient: Cliente OAuth2 para uma agenda
- MultiCalendarClient: Cliente para multiplas agendas com prioridade
- Tipos e helpers para manipulacao de eventos

Exemplo de uso basico:
    from app.integrations.calendar import (
        GoogleCalendarClient,
        create_google_calendar_client,
        CalendarConfig,
        CreateEventInput,
    )

    config = CalendarConfig(
        client_id="...",
        client_secret="...",
        refresh_token="...",
        calendar_id="primary",
    )

    client = create_google_calendar_client(config)
    event = await client.create_event(CreateEventInput(
        summary="Reuniao com Cliente",
        start_date_time="2024-01-15T10:00:00",
        end_date_time="2024-01-15T11:00:00",
        timezone="America/Sao_Paulo",
        create_meet_link=True,
    ))

Exemplo de uso com multi-calendario:
    from app.integrations.calendar import (
        MultiCalendarClient,
        create_multi_calendar_client_from_accounts,
        GoogleAccount,
        AvailabilityParams,
        AvailabilityScenario,
    )

    accounts = [
        GoogleAccount(
            email="primary@example.com",
            credentials={"refresh_token": "..."},
            calendar_id="primary",
        ),
        GoogleAccount(
            email="secondary@example.com",
            credentials={"refresh_token": "..."},
            calendar_id="primary",
        ),
    ]

    client = create_multi_calendar_client_from_accounts(
        accounts=accounts,
        client_id="...",
        client_secret="...",
    )

    result = await client.get_availability_with_priority(
        AvailabilityParams(
            date="2024-01-15",
            work_hours_start=8,
            work_hours_end=18,
            slot_duration=60,
            timezone="America/Sao_Paulo",
        )
    )

    if result.scenario != AvailabilityScenario.NONE:
        event_result = await client.create_event_in_all_calendars(
            input=create_input,
            target_accounts=result.accounts_to_schedule,
            scenario=result.scenario,
        )
"""

# ==============================================================================
# TYPES
# ==============================================================================

from .types import (
    # Configuracao
    CalendarConfig,
    # Enums
    AttendeeResponseStatus,
    EventStatus,
    EntryPointType,
    AvailabilityScenario,
    # Data/Hora
    EventDateTime,
    # Participante
    Attendee,
    # Conferencia (Google Meet)
    EntryPoint,
    ConferenceSolution,
    ConferenceData,
    # Extended Properties
    AgnesEventMetadata,
    ExtendedProperties,
    # Evento
    CalendarEvent,
    # Input
    CreateEventInput,
    UpdateEventInput,
    # Disponibilidade
    TimeSlot,
    AvailabilityResult,
    AvailabilityParams,
    # Configuracao de horarios
    AccountScheduleConfig,
    # Multi-calendar
    GoogleAccount,
    MultiCalendarConfig,
    AccountAvailability,
    MultiCalendarAvailabilityResult,
    SecondaryEventResult,
    MultiCalendarEventResult,
    ConflictingEvent,
    ConflictCheckResult,
    # Helpers
    extract_meet_link,
    format_time_slot,
    time_string_to_hours,
    do_time_periods_overlap,
    is_time_in_allowed_period,
    is_day_allowed,
    validate_schedule_time,
    filter_slots_by_period,
    extract_remote_jid_from_event,
    extract_customer_name_from_event,
)

# ==============================================================================
# CLIENT
# ==============================================================================

from .client import (
    GoogleCalendarClient,
    create_google_calendar_client,
)

# ==============================================================================
# MULTI-CALENDAR
# ==============================================================================

from .multi_calendar import (
    MultiCalendarClient,
    create_multi_calendar_client,
    create_multi_calendar_client_from_accounts,
)

# ==============================================================================
# EXPORTS
# ==============================================================================

__all__ = [
    # Configuracao
    "CalendarConfig",
    # Enums
    "AttendeeResponseStatus",
    "EventStatus",
    "EntryPointType",
    "AvailabilityScenario",
    # Data/Hora
    "EventDateTime",
    # Participante
    "Attendee",
    # Conferencia
    "EntryPoint",
    "ConferenceSolution",
    "ConferenceData",
    # Extended Properties
    "AgnesEventMetadata",
    "ExtendedProperties",
    # Evento
    "CalendarEvent",
    # Input
    "CreateEventInput",
    "UpdateEventInput",
    # Disponibilidade
    "TimeSlot",
    "AvailabilityResult",
    "AvailabilityParams",
    # Configuracao de horarios
    "AccountScheduleConfig",
    # Multi-calendar types
    "GoogleAccount",
    "MultiCalendarConfig",
    "AccountAvailability",
    "MultiCalendarAvailabilityResult",
    "SecondaryEventResult",
    "MultiCalendarEventResult",
    "ConflictingEvent",
    "ConflictCheckResult",
    # Helpers
    "extract_meet_link",
    "format_time_slot",
    "time_string_to_hours",
    "do_time_periods_overlap",
    "is_time_in_allowed_period",
    "is_day_allowed",
    "validate_schedule_time",
    "filter_slots_by_period",
    "extract_remote_jid_from_event",
    "extract_customer_name_from_event",
    # Clients
    "GoogleCalendarClient",
    "create_google_calendar_client",
    "MultiCalendarClient",
    "create_multi_calendar_client",
    "create_multi_calendar_client_from_accounts",
]
