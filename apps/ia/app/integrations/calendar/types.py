# ==============================================================================
# GOOGLE CALENDAR TYPES
# Tipos e utilitarios para integracao Google Calendar
# Baseado na implementacao TypeScript (apps/api/src/services/calendar/types.ts)
# ==============================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import TypedDict, Optional, Literal
import re


# ==============================================================================
# CONFIGURACAO
# ==============================================================================

class CalendarConfig(TypedDict):
    """Configuracao OAuth2 para Google Calendar."""
    client_id: str
    client_secret: str
    refresh_token: str
    calendar_id: str


# ==============================================================================
# ENUMS
# ==============================================================================

class AttendeeResponseStatus(str, Enum):
    """Status de resposta do participante."""
    NEEDS_ACTION = "needsAction"
    DECLINED = "declined"
    TENTATIVE = "tentative"
    ACCEPTED = "accepted"


class EventStatus(str, Enum):
    """Status do evento."""
    CONFIRMED = "confirmed"
    TENTATIVE = "tentative"
    CANCELLED = "cancelled"


class EntryPointType(str, Enum):
    """Tipo de ponto de entrada para conferencia."""
    VIDEO = "video"
    PHONE = "phone"
    SIP = "sip"
    MORE = "more"


class AvailabilityScenario(str, Enum):
    """Cenarios de disponibilidade para multiplas agendas."""
    PRIMARY_ONLY = "primary_only"       # Primaria tem, secundaria nao
    SECONDARY_ONLY = "secondary_only"   # Secundaria tem, primaria nao
    BOTH = "both"                       # Ambas tem horarios
    NONE = "none"                       # Nenhuma tem horarios


# ==============================================================================
# DATA/HORA DO EVENTO
# ==============================================================================

@dataclass
class EventDateTime:
    """Data/hora de um evento."""
    date_time: str  # ISO 8601
    time_zone: str


# ==============================================================================
# PARTICIPANTE
# ==============================================================================

@dataclass
class Attendee:
    """Participante de um evento."""
    email: str
    display_name: Optional[str] = None
    response_status: Optional[AttendeeResponseStatus] = None
    organizer: Optional[bool] = None
    self: Optional[bool] = None


# ==============================================================================
# CONFERENCIA (GOOGLE MEET)
# ==============================================================================

@dataclass
class EntryPoint:
    """Ponto de entrada para conferencia."""
    entry_point_type: EntryPointType
    uri: str
    label: Optional[str] = None
    pin: Optional[str] = None
    region_code: Optional[str] = None


@dataclass
class ConferenceSolution:
    """Solucao de conferencia."""
    key_type: str
    name: str
    icon_uri: Optional[str] = None


@dataclass
class ConferenceData:
    """Dados de conferencia (Google Meet)."""
    entry_points: list[EntryPoint] = field(default_factory=list)
    conference_solution: Optional[ConferenceSolution] = None
    conference_id: Optional[str] = None


# ==============================================================================
# EXTENDED PROPERTIES (METADADOS AGNES)
# ==============================================================================

@dataclass
class AgnesEventMetadata:
    """
    Metadados Agnes armazenados no evento do Google Calendar.
    Usados para identificar eventos criados pela Agnes e vincular ao lead.
    """
    source: Literal["agnes", "diana"]  # Agente que criou
    agent_id: str                       # UUID do agente
    remote_jid: str                     # WhatsApp JID (ex: "5511999999999@s.whatsapp.net")
    created_at: str                     # ISO timestamp
    lead_id: Optional[str] = None       # UUID do lead
    organization_id: Optional[str] = None  # UUID da organizacao


@dataclass
class ExtendedProperties:
    """Propriedades extendidas do evento."""
    private: Optional[dict[str, str]] = None   # Visivel apenas para o app
    shared: Optional[dict[str, str]] = None    # Visivel para todos


# ==============================================================================
# EVENTO DO CALENDARIO
# ==============================================================================

@dataclass
class CalendarEvent:
    """Evento do calendario."""
    id: str
    summary: str
    start: EventDateTime
    end: EventDateTime
    description: Optional[str] = None
    attendees: list[Attendee] = field(default_factory=list)
    conference_data: Optional[ConferenceData] = None
    status: Optional[EventStatus] = None
    html_link: Optional[str] = None
    created: Optional[str] = None
    updated: Optional[str] = None
    is_all_day: bool = False
    extended_properties: Optional[ExtendedProperties] = None
    agnes_metadata: Optional[AgnesEventMetadata] = None


# ==============================================================================
# INPUT PARA CRIACAO DE EVENTO
# ==============================================================================

@dataclass
class CreateEventInput:
    """Input para criar um evento."""
    summary: str
    start_date_time: str       # ISO 8601
    end_date_time: str         # ISO 8601
    timezone: str
    description: Optional[str] = None
    attendee_email: Optional[str] = None
    attendee_name: Optional[str] = None
    create_meet_link: bool = True
    send_notifications: bool = False
    agnes_metadata: Optional[AgnesEventMetadata] = None


@dataclass
class UpdateEventInput:
    """Input para atualizar um evento."""
    summary: Optional[str] = None
    description: Optional[str] = None
    start_date_time: Optional[str] = None
    end_date_time: Optional[str] = None
    timezone: Optional[str] = None
    attendee_email: Optional[str] = None
    attendee_name: Optional[str] = None


# ==============================================================================
# DISPONIBILIDADE
# ==============================================================================

@dataclass
class TimeSlot:
    """Slot de tempo."""
    start: str  # ISO 8601
    end: str    # ISO 8601


@dataclass
class AvailabilityResult:
    """Resultado de verificacao de disponibilidade."""
    date: str  # YYYY-MM-DD
    timezone: str
    work_hours_start: int
    work_hours_end: int
    slot_duration: int
    available_slots: list[TimeSlot] = field(default_factory=list)
    busy_slots: list[TimeSlot] = field(default_factory=list)


@dataclass
class AvailabilityParams:
    """Parametros para verificar disponibilidade."""
    date: str                   # YYYY-MM-DD
    work_hours_start: int       # 0-23
    work_hours_end: int         # 0-23
    slot_duration: int          # minutos
    timezone: str
    break_between_slots: int = 0  # minutos


# ==============================================================================
# CONFIGURACAO DE HORARIOS (MANHA/TARDE)
# ==============================================================================

@dataclass
class AccountScheduleConfig:
    """Configuracao de horarios de uma agenda especifica."""
    morning_enabled: bool
    morning_start: str          # HH:MM
    morning_end: str            # HH:MM
    afternoon_enabled: bool
    afternoon_start: str        # HH:MM
    afternoon_end: str          # HH:MM
    work_days: Optional[dict[str, bool]] = None  # { "seg": True, "ter": True, ... }


# ==============================================================================
# MULTI-CALENDAR
# ==============================================================================

@dataclass
class GoogleAccount:
    """Conta Google para multi-calendario."""
    email: str
    credentials: dict  # { refresh_token, access_token?, ... }
    calendar_id: str


@dataclass
class MultiCalendarConfig:
    """Configuracao para multiplas agendas."""
    client_id: str
    client_secret: str
    accounts: list[GoogleAccount]  # Ordenado por prioridade (0 = prioritario)


@dataclass
class AccountAvailability:
    """Disponibilidade de uma conta."""
    account: GoogleAccount
    availability: AvailabilityResult
    has_slots: bool


@dataclass
class MultiCalendarAvailabilityResult:
    """Resultado de disponibilidade para multiplas agendas."""
    scenario: AvailabilityScenario
    accounts_to_schedule: list[GoogleAccount]
    available_account: Optional[GoogleAccount]
    available_account_index: int
    primary_availability: Optional[AvailabilityResult]
    secondary_availability: Optional[AvailabilityResult]
    all_availabilities: list[AccountAvailability]
    available_slots: list[TimeSlot]
    message: str


@dataclass
class SecondaryEventResult:
    """Resultado de criacao de evento em conta secundaria."""
    account: GoogleAccount
    event: Optional[CalendarEvent]
    error: Optional[str] = None


@dataclass
class MultiCalendarEventResult:
    """Resultado de criacao de evento em multiplas agendas."""
    primary_account: GoogleAccount
    primary_event: CalendarEvent
    secondary_events: list[SecondaryEventResult]
    all_created: bool


@dataclass
class ConflictingEvent:
    """Evento conflitante."""
    account: str
    event_id: str
    summary: str
    start: str
    end: str


@dataclass
class ConflictCheckResult:
    """Resultado de verificacao de conflitos."""
    has_conflict: bool
    conflicting_events: list[ConflictingEvent]
    message: Optional[str] = None


# ==============================================================================
# HELPERS
# ==============================================================================

def extract_meet_link(event: CalendarEvent) -> Optional[str]:
    """Extrai o link do Google Meet de um evento."""
    if not event.conference_data or not event.conference_data.entry_points:
        return None

    for entry_point in event.conference_data.entry_points:
        if entry_point.entry_point_type == EntryPointType.VIDEO:
            return entry_point.uri

    return None


def format_time_slot(slot: TimeSlot, timezone: str) -> str:
    """
    Formata um slot de tempo para exibicao.
    Retorna formato "HH:MM - HH:MM".
    """
    from datetime import datetime
    import pytz

    tz = pytz.timezone(timezone)

    start = datetime.fromisoformat(slot.start.replace("Z", "+00:00"))
    end = datetime.fromisoformat(slot.end.replace("Z", "+00:00"))

    start_local = start.astimezone(tz)
    end_local = end.astimezone(tz)

    return f"{start_local.strftime('%H:%M')} - {end_local.strftime('%H:%M')}"


def time_string_to_hours(time: str) -> float:
    """
    Converte string HH:MM para hora numerica.
    Ex: "14:30" => 14.5
    """
    parts = time.split(":")
    hours = int(parts[0])
    minutes = int(parts[1]) if len(parts) > 1 else 0
    return hours + (minutes / 60)


def do_time_periods_overlap(
    start1: datetime,
    end1: datetime,
    start2: datetime,
    end2: datetime
) -> bool:
    """Verifica se dois periodos de tempo se sobrepoem."""
    return start1 < end2 and end1 > start2


def is_time_in_allowed_period(
    time: str,
    config: AccountScheduleConfig,
    duration_minutes: int = 60
) -> tuple[bool, str]:
    """
    Verifica se um horario especifico esta dentro dos periodos permitidos.
    Considera a duracao da reuniao para garantir que caiba inteira no periodo.

    Args:
        time: Horario no formato HH:MM
        config: Configuracao de periodos
        duration_minutes: Duracao da reuniao em minutos

    Returns:
        Tuple (allowed: bool, reason: str)
    """
    time_hours = time_string_to_hours(time)
    duration_hours = duration_minutes / 60
    end_time_hours = time_hours + duration_hours

    # Se nenhum periodo esta habilitado, bloquear
    if not config.morning_enabled and not config.afternoon_enabled:
        return False, "Nenhum periodo de atendimento esta habilitado para esta agenda."

    # Verificar periodo da manha
    if config.morning_enabled:
        morning_start = time_string_to_hours(config.morning_start)
        morning_end = time_string_to_hours(config.morning_end)
        if time_hours >= morning_start and end_time_hours <= morning_end:
            return True, "Horario dentro do periodo da manha."

    # Verificar periodo da tarde
    if config.afternoon_enabled:
        afternoon_start = time_string_to_hours(config.afternoon_start)
        afternoon_end = time_string_to_hours(config.afternoon_end)
        if time_hours >= afternoon_start and end_time_hours <= afternoon_end:
            return True, "Horario dentro do periodo da tarde."

    # Construir mensagem de erro com horarios disponiveis
    available_periods: list[str] = []

    if config.morning_enabled:
        morning_end = time_string_to_hours(config.morning_end)
        last_valid = morning_end - duration_hours
        last_valid_str = f"{int(last_valid):02d}:{int((last_valid % 1) * 60):02d}"
        available_periods.append(f"manha ({config.morning_start} as {last_valid_str})")

    if config.afternoon_enabled:
        afternoon_end = time_string_to_hours(config.afternoon_end)
        last_valid = afternoon_end - duration_hours
        last_valid_str = f"{int(last_valid):02d}:{int((last_valid % 1) * 60):02d}"
        available_periods.append(f"tarde ({config.afternoon_start} as {last_valid_str})")

    return (
        False,
        f"O horario {time} esta fora dos periodos de atendimento "
        f"(considerando duracao de {duration_minutes} minutos). "
        f"Horarios disponiveis: {' e '.join(available_periods)}."
    )


def is_day_allowed(
    date_str: str,
    work_days: Optional[dict[str, bool]] = None
) -> tuple[bool, str]:
    """
    Verifica se um dia da semana esta habilitado na configuracao.

    Args:
        date_str: Data no formato YYYY-MM-DD
        work_days: Configuracao de dias { "seg": True, "ter": False, ... }

    Returns:
        Tuple (allowed: bool, day_name: str)
    """
    from datetime import datetime

    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    day_of_week = date_obj.weekday()  # 0=segunda, 6=domingo

    day_map = {
        0: ("seg", "segunda-feira"),
        1: ("ter", "terca-feira"),
        2: ("qua", "quarta-feira"),
        3: ("qui", "quinta-feira"),
        4: ("sex", "sexta-feira"),
        5: ("sab", "sabado"),
        6: ("dom", "domingo"),
    }

    key, name = day_map[day_of_week]

    # Se nao tem configuracao de dias, usar padrao seg-sex
    if not work_days:
        default_allowed = day_of_week < 5  # segunda a sexta
        return default_allowed, name

    allowed = work_days.get(key, False)
    return allowed, name


def validate_schedule_time(
    date_str: str,
    time: str,
    config: AccountScheduleConfig,
    duration_minutes: int = 60
) -> tuple[bool, str]:
    """
    Valida completamente se um agendamento esta dentro do escopo permitido.

    Args:
        date_str: Data no formato YYYY-MM-DD
        time: Horario no formato HH:MM
        config: Configuracao de horarios da agenda
        duration_minutes: Duracao da reuniao em minutos

    Returns:
        Tuple (allowed: bool, reason: str)
    """
    # 1. Verificar dia da semana
    day_allowed, day_name = is_day_allowed(date_str, config.work_days)
    if not day_allowed:
        return False, f"Nao ha atendimento em {day_name}. Por favor, escolha outro dia."

    # 2. Verificar periodo (manha/tarde)
    period_allowed, reason = is_time_in_allowed_period(time, config, duration_minutes)
    if not period_allowed:
        return False, reason

    return True, "Horario dentro do escopo permitido."


def filter_slots_by_period(
    slots: list[TimeSlot],
    config: AccountScheduleConfig,
    timezone: str,
    duration_minutes: int = 60
) -> list[TimeSlot]:
    """
    Filtra slots disponiveis baseado na configuracao de periodos (manha/tarde).

    Args:
        slots: Lista de slots para filtrar
        config: Configuracao de periodos
        timezone: Timezone para formatacao
        duration_minutes: Duracao da reuniao em minutos

    Returns:
        Lista de slots filtrados
    """
    from datetime import datetime
    import pytz

    tz = pytz.timezone(timezone)
    filtered: list[TimeSlot] = []

    for slot in slots:
        slot_start = datetime.fromisoformat(slot.start.replace("Z", "+00:00"))
        slot_local = slot_start.astimezone(tz)
        time_str = slot_local.strftime("%H:%M")

        allowed, _ = is_time_in_allowed_period(time_str, config, duration_minutes)
        if allowed:
            filtered.append(slot)

    return filtered


def extract_remote_jid_from_event(event: CalendarEvent) -> Optional[str]:
    """
    Extrai remote_jid de um evento Agnes.
    Tenta primeiro extendedProperties, depois descricao.
    """
    # Primeiro tentar agnes_metadata
    if event.agnes_metadata and event.agnes_metadata.remote_jid:
        return event.agnes_metadata.remote_jid

    # Fallback: extrair da descricao
    if event.description:
        # Padrao: "Telefone: 5511999999999"
        phone_match = re.search(r"telefone:\s*(\d+)", event.description, re.IGNORECASE)
        if phone_match:
            phone = phone_match.group(1)
            return f"{phone}@s.whatsapp.net" if "@" not in phone else phone

    return None


def extract_customer_name_from_event(event: CalendarEvent) -> Optional[str]:
    """Extrai nome do cliente de um evento Agnes."""
    # Tentar extrair do titulo (formato: "Reuniao com Nome")
    if event.summary:
        title_match = re.search(r"reuni[aã]o com\s+(.+)", event.summary, re.IGNORECASE)
        if title_match:
            return title_match.group(1).strip()

    # Fallback: extrair da descricao
    if event.description:
        lead_match = re.search(r"lead:\s*(.+)", event.description, re.IGNORECASE)
        if lead_match:
            return lead_match.group(1).strip().split("\n")[0]

    return None
