# ==============================================================================
# GOOGLE CALENDAR CLIENT
# Cliente OAuth2 para Google Calendar
# Baseado na implementacao TypeScript (apps/api/src/services/calendar/client.ts)
# ==============================================================================

from __future__ import annotations

import structlog
from datetime import datetime, timedelta
from typing import Optional, Any
import random
import string

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import pytz

from .types import (
    CalendarConfig,
    CalendarEvent,
    CreateEventInput,
    UpdateEventInput,
    AvailabilityResult,
    AvailabilityParams,
    TimeSlot,
    EventDateTime,
    Attendee,
    AttendeeResponseStatus,
    EventStatus,
    ConferenceData,
    ConferenceSolution,
    EntryPoint,
    EntryPointType,
    ExtendedProperties,
    AgnesEventMetadata,
    do_time_periods_overlap,
)

logger = structlog.get_logger(__name__)


class GoogleCalendarClient:
    """Cliente para Google Calendar com OAuth2."""

    def __init__(self, config: CalendarConfig):
        """
        Inicializa o cliente.

        Args:
            config: Configuracao com credenciais OAuth2
        """
        self.calendar_id = config["calendar_id"]

        # Criar credenciais OAuth2
        credentials = Credentials(
            token=None,
            refresh_token=config["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=config["client_id"],
            client_secret=config["client_secret"],
        )

        # Criar servico do Calendar
        self.service = build("calendar", "v3", credentials=credentials)
        self._config = config

    async def create_event(self, input: CreateEventInput) -> CalendarEvent:
        """
        Cria um evento no calendario.
        Se agnes_metadata for fornecido, adiciona extendedProperties.
        """
        try:
            event_body: dict[str, Any] = {
                "summary": input.summary,
                "start": {
                    "dateTime": input.start_date_time,
                    "timeZone": input.timezone,
                },
                "end": {
                    "dateTime": input.end_date_time,
                    "timeZone": input.timezone,
                },
            }

            if input.description:
                event_body["description"] = input.description

            # Adicionar participante se fornecido
            if input.attendee_email:
                attendee = {"email": input.attendee_email}
                if input.attendee_name:
                    attendee["displayName"] = input.attendee_name
                event_body["attendees"] = [attendee]

            # Configurar Google Meet se solicitado
            if input.create_meet_link:
                request_id = f"meet-{int(datetime.now().timestamp())}-{''.join(random.choices(string.ascii_lowercase + string.digits, k=7))}"
                event_body["conferenceData"] = {
                    "createRequest": {
                        "requestId": request_id,
                        "conferenceSolutionKey": {"type": "hangoutsMeet"},
                    }
                }

            # Adicionar extendedProperties com metadados Agnes
            if input.agnes_metadata:
                event_body["extendedProperties"] = {
                    "private": {
                        "source": input.agnes_metadata.source,
                        "agent_id": input.agnes_metadata.agent_id,
                        "remote_jid": input.agnes_metadata.remote_jid,
                        "lead_id": input.agnes_metadata.lead_id or "",
                        "organization_id": input.agnes_metadata.organization_id or "",
                        "created_at": input.agnes_metadata.created_at,
                    }
                }
                logger.info(
                    "calendar_adding_agnes_metadata",
                    agent_id=input.agnes_metadata.agent_id,
                    remote_jid=input.agnes_metadata.remote_jid,
                )

            response = (
                self.service.events()
                .insert(
                    calendarId=self.calendar_id,
                    body=event_body,
                    conferenceDataVersion=1 if input.create_meet_link else 0,
                    sendUpdates="all" if input.send_notifications else "none",
                )
                .execute()
            )

            return self._parse_event(response)

        except HttpError as e:
            logger.error("calendar_create_event_error", error=str(e))
            raise self._handle_error(e, "create_event")

    async def list_events(
        self, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Lista eventos em um periodo."""
        try:
            response = (
                self.service.events()
                .list(
                    calendarId=self.calendar_id,
                    timeMin=start_date.isoformat() + "Z" if start_date.tzinfo is None else start_date.isoformat(),
                    timeMax=end_date.isoformat() + "Z" if end_date.tzinfo is None else end_date.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )

            events = response.get("items", [])
            return [self._parse_event(event) for event in events]

        except HttpError as e:
            logger.error("calendar_list_events_error", error=str(e))
            raise self._handle_error(e, "list_events")

    async def get_event(self, event_id: str) -> Optional[CalendarEvent]:
        """Obtem um evento especifico."""
        try:
            response = (
                self.service.events()
                .get(calendarId=self.calendar_id, eventId=event_id)
                .execute()
            )
            return self._parse_event(response)

        except HttpError as e:
            if e.resp.status == 404:
                return None
            logger.error("calendar_get_event_error", error=str(e))
            raise self._handle_error(e, "get_event")

    async def get_availability(self, params: AvailabilityParams) -> AvailabilityResult:
        """Calcula disponibilidade para uma data."""
        try:
            # Criar datas de inicio e fim do dia
            day_start = datetime.fromisoformat(f"{params.date}T00:00:00")
            day_end = datetime.fromisoformat(f"{params.date}T23:59:59")

            # Buscar eventos do dia
            events = await self.list_events(day_start, day_end)

            # Extrair periodos ocupados (ignorar eventos de dia inteiro e cancelados)
            busy_slots: list[TimeSlot] = []
            for event in events:
                if event.status == EventStatus.CANCELLED:
                    continue
                if event.is_all_day:
                    continue
                busy_slots.append(
                    TimeSlot(start=event.start.date_time, end=event.end.date_time)
                )

            # Calcular slots disponiveis
            available_slots = self._calculate_available_slots(
                date=params.date,
                work_hours_start=params.work_hours_start,
                work_hours_end=params.work_hours_end,
                slot_duration=params.slot_duration,
                break_between_slots=params.break_between_slots,
                timezone=params.timezone,
                busy_slots=busy_slots,
            )

            return AvailabilityResult(
                date=params.date,
                timezone=params.timezone,
                work_hours_start=params.work_hours_start,
                work_hours_end=params.work_hours_end,
                slot_duration=params.slot_duration,
                available_slots=available_slots,
                busy_slots=busy_slots,
            )

        except HttpError as e:
            logger.error("calendar_get_availability_error", error=str(e))
            raise self._handle_error(e, "get_availability")

    def _calculate_available_slots(
        self,
        date: str,
        work_hours_start: int,
        work_hours_end: int,
        slot_duration: int,
        break_between_slots: int,
        timezone: str,
        busy_slots: list[TimeSlot],
    ) -> list[TimeSlot]:
        """Calcula slots disponiveis baseado nos eventos existentes."""
        available_slots: list[TimeSlot] = []
        slot_duration_td = timedelta(minutes=slot_duration)
        break_duration_td = timedelta(minutes=break_between_slots)

        # Obter timezone
        tz = pytz.timezone(timezone)

        # Criar horarios de inicio e fim do expediente no timezone correto
        base_date = datetime.strptime(date, "%Y-%m-%d")

        # Criar datetime com timezone
        start_of_work = tz.localize(
            base_date.replace(hour=work_hours_start, minute=0, second=0)
        )
        end_of_work = tz.localize(
            base_date.replace(hour=work_hours_end, minute=0, second=0)
        )

        logger.debug(
            "calendar_calculating_slots",
            timezone=timezone,
            work_hours=f"{work_hours_start}-{work_hours_end}",
            start_utc=start_of_work.isoformat(),
            end_utc=end_of_work.isoformat(),
        )

        # Converter busy slots para datetime
        busy_periods: list[tuple[datetime, datetime]] = []
        for slot in busy_slots:
            busy_start = datetime.fromisoformat(slot.start.replace("Z", "+00:00"))
            busy_end = datetime.fromisoformat(slot.end.replace("Z", "+00:00"))
            busy_periods.append((busy_start, busy_end))

        current_time = start_of_work

        while current_time + slot_duration_td <= end_of_work:
            slot_end = current_time + slot_duration_td

            # Verificar se o slot conflita com algum periodo ocupado
            has_conflict = any(
                do_time_periods_overlap(current_time, slot_end, busy_start, busy_end)
                for busy_start, busy_end in busy_periods
            )

            if not has_conflict:
                available_slots.append(
                    TimeSlot(
                        start=current_time.isoformat(),
                        end=slot_end.isoformat(),
                    )
                )

            # Avancar para o proximo slot
            current_time = slot_end + break_duration_td

        return available_slots

    async def get_availability_range(
        self,
        start_date: str,
        end_date: str,
        work_hours_start: int,
        work_hours_end: int,
        slot_duration: int,
        timezone: str,
        break_between_slots: int = 0,
    ) -> list[AvailabilityResult]:
        """Obtem disponibilidade para multiplos dias."""
        results: list[AvailabilityResult] = []

        current = datetime.strptime(start_date, "%Y-%m-%d")
        last = datetime.strptime(end_date, "%Y-%m-%d")

        while current <= last:
            date_str = current.strftime("%Y-%m-%d")
            availability = await self.get_availability(
                AvailabilityParams(
                    date=date_str,
                    work_hours_start=work_hours_start,
                    work_hours_end=work_hours_end,
                    slot_duration=slot_duration,
                    timezone=timezone,
                    break_between_slots=break_between_slots,
                )
            )
            results.append(availability)
            current += timedelta(days=1)

        return results

    async def update_event(
        self, event_id: str, input: UpdateEventInput
    ) -> CalendarEvent:
        """Atualiza um evento."""
        try:
            # Buscar evento atual
            current_event = await self.get_event(event_id)
            if not current_event:
                raise ValueError(f"Event not found: {event_id}")

            update_data: dict[str, Any] = {}

            if input.summary is not None:
                update_data["summary"] = input.summary

            if input.description is not None:
                update_data["description"] = input.description

            if input.start_date_time:
                update_data["start"] = {
                    "dateTime": input.start_date_time,
                    "timeZone": input.timezone or current_event.start.time_zone,
                }

            if input.end_date_time:
                update_data["end"] = {
                    "dateTime": input.end_date_time,
                    "timeZone": input.timezone or current_event.end.time_zone,
                }

            if input.attendee_email:
                attendee = {"email": input.attendee_email}
                if input.attendee_name:
                    attendee["displayName"] = input.attendee_name
                update_data["attendees"] = [attendee]

            response = (
                self.service.events()
                .patch(
                    calendarId=self.calendar_id,
                    eventId=event_id,
                    body=update_data,
                    sendUpdates="all",
                )
                .execute()
            )

            return self._parse_event(response)

        except HttpError as e:
            logger.error("calendar_update_event_error", error=str(e))
            raise self._handle_error(e, "update_event")

    async def delete_event(self, event_id: str) -> None:
        """Deleta um evento."""
        try:
            (
                self.service.events()
                .delete(
                    calendarId=self.calendar_id,
                    eventId=event_id,
                    sendUpdates="all",
                )
                .execute()
            )
        except HttpError as e:
            if e.resp.status == 404:
                return  # Ignorar se ja foi deletado
            logger.error("calendar_delete_event_error", error=str(e))
            raise self._handle_error(e, "delete_event")

    async def cancel_event(self, event_id: str) -> CalendarEvent:
        """Cancela um evento (nao deleta, apenas marca como cancelado)."""
        try:
            response = (
                self.service.events()
                .patch(
                    calendarId=self.calendar_id,
                    eventId=event_id,
                    body={"status": "cancelled"},
                    sendUpdates="all",
                )
                .execute()
            )
            return self._parse_event(response)

        except HttpError as e:
            logger.error("calendar_cancel_event_error", error=str(e))
            raise self._handle_error(e, "cancel_event")

    async def list_agnes_events(
        self,
        start_date: datetime,
        end_date: datetime,
        agent_id: Optional[str] = None,
    ) -> list[CalendarEvent]:
        """
        Lista eventos criados pela Agnes em um periodo.
        Filtra por extendedProperties.private.source = 'agnes'.
        """
        try:
            response = (
                self.service.events()
                .list(
                    calendarId=self.calendar_id,
                    timeMin=start_date.isoformat() + "Z" if start_date.tzinfo is None else start_date.isoformat(),
                    timeMax=end_date.isoformat() + "Z" if end_date.tzinfo is None else end_date.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                    privateExtendedProperty=["source=agnes"],
                )
                .execute()
            )

            events = response.get("items", [])

            # Filtrar por agent_id se fornecido
            if agent_id:
                events = [
                    e
                    for e in events
                    if e.get("extendedProperties", {})
                    .get("private", {})
                    .get("agent_id")
                    == agent_id
                ]

            parsed_events = [self._parse_event(e) for e in events]
            logger.info(
                "calendar_list_agnes_events",
                count=len(parsed_events),
                agent_id=agent_id,
            )

            return parsed_events

        except HttpError as e:
            logger.error("calendar_list_agnes_events_error", error=str(e))
            raise self._handle_error(e, "list_agnes_events")

    async def list_agnes_events_with_fallback(
        self,
        start_date: datetime,
        end_date: datetime,
        agent_id: Optional[str] = None,
    ) -> list[CalendarEvent]:
        """
        Lista eventos da Agnes usando fallback de descricao.
        Para eventos antigos que nao tem extendedProperties.
        """
        try:
            # Primeiro buscar eventos com extendedProperties
            agnes_events = await self.list_agnes_events(start_date, end_date, agent_id)
            agnes_event_ids = {e.id for e in agnes_events}

            # Depois buscar TODOS os eventos do periodo
            all_events = await self.list_events(start_date, end_date)

            # Filtrar eventos que podem ser da Agnes (descricao padrao)
            fallback_events: list[CalendarEvent] = []
            for event in all_events:
                if event.id in agnes_event_ids:
                    continue
                if event.status == EventStatus.CANCELLED:
                    continue

                description = (event.description or "").lower()
                is_agnes_description = (
                    "agendamento realizado via whatsapp" in description
                    or "agendamento via whatsapp" in description
                    or ("lead:" in description and "telefone:" in description)
                )

                if is_agnes_description:
                    fallback_events.append(event)

            combined = agnes_events + fallback_events
            logger.info(
                "calendar_list_agnes_events_with_fallback",
                agnes_count=len(agnes_events),
                fallback_count=len(fallback_events),
            )

            return combined

        except HttpError as e:
            logger.error("calendar_list_agnes_events_fallback_error", error=str(e))
            raise self._handle_error(e, "list_agnes_events_with_fallback")

    def _parse_event(self, event: dict[str, Any]) -> CalendarEvent:
        """Parseia evento da API para formato interno."""
        # Evento de dia inteiro tem .date ao inves de .dateTime
        start_data = event.get("start", {})
        end_data = event.get("end", {})
        is_all_day = "date" in start_data and "dateTime" not in start_data

        # Parsear extendedProperties
        ext_props_raw = event.get("extendedProperties")
        extended_properties: Optional[ExtendedProperties] = None
        agnes_metadata: Optional[AgnesEventMetadata] = None

        if ext_props_raw:
            extended_properties = ExtendedProperties(
                private=ext_props_raw.get("private"),
                shared=ext_props_raw.get("shared"),
            )

            # Extrair agnesMetadata se for evento Agnes
            private = ext_props_raw.get("private", {})
            if private.get("source") == "agnes":
                agnes_metadata = AgnesEventMetadata(
                    source="agnes",
                    agent_id=private.get("agent_id", ""),
                    remote_jid=private.get("remote_jid", ""),
                    lead_id=private.get("lead_id") or None,
                    organization_id=private.get("organization_id") or None,
                    created_at=private.get("created_at", ""),
                )

        # Parsear conferenceData
        conference_data: Optional[ConferenceData] = None
        conf_raw = event.get("conferenceData")
        if conf_raw:
            entry_points: list[EntryPoint] = []
            for ep in conf_raw.get("entryPoints", []):
                entry_points.append(
                    EntryPoint(
                        entry_point_type=EntryPointType(ep.get("entryPointType", "video")),
                        uri=ep.get("uri", ""),
                        label=ep.get("label"),
                        pin=ep.get("pin"),
                        region_code=ep.get("regionCode"),
                    )
                )

            solution = conf_raw.get("conferenceSolution")
            conference_solution: Optional[ConferenceSolution] = None
            if solution:
                conference_solution = ConferenceSolution(
                    key_type=solution.get("key", {}).get("type", ""),
                    name=solution.get("name", ""),
                    icon_uri=solution.get("iconUri"),
                )

            conference_data = ConferenceData(
                entry_points=entry_points,
                conference_solution=conference_solution,
                conference_id=conf_raw.get("conferenceId"),
            )

        # Parsear attendees
        attendees: list[Attendee] = []
        for att in event.get("attendees", []):
            response_status = att.get("responseStatus")
            attendees.append(
                Attendee(
                    email=att.get("email", ""),
                    display_name=att.get("displayName"),
                    response_status=(
                        AttendeeResponseStatus(response_status)
                        if response_status
                        else None
                    ),
                    organizer=att.get("organizer"),
                    self=att.get("self"),
                )
            )

        # Status
        status_str = event.get("status")
        status = EventStatus(status_str) if status_str else None

        return CalendarEvent(
            id=event.get("id", ""),
            summary=event.get("summary", ""),
            description=event.get("description"),
            is_all_day=is_all_day,
            start=EventDateTime(
                date_time=start_data.get("dateTime") or start_data.get("date", ""),
                time_zone=start_data.get("timeZone", "America/Sao_Paulo"),
            ),
            end=EventDateTime(
                date_time=end_data.get("dateTime") or end_data.get("date", ""),
                time_zone=end_data.get("timeZone", "America/Sao_Paulo"),
            ),
            attendees=attendees,
            conference_data=conference_data,
            status=status,
            html_link=event.get("htmlLink"),
            created=event.get("created"),
            updated=event.get("updated"),
            extended_properties=extended_properties,
            agnes_metadata=agnes_metadata,
        )

    def _handle_error(self, error: HttpError, operation: str) -> Exception:
        """Trata erros de forma padronizada."""
        return Exception(f"[GoogleCalendarClient] {operation} failed: {error}")


def create_google_calendar_client(config: CalendarConfig) -> GoogleCalendarClient:
    """Factory function para criar cliente do Google Calendar."""
    return GoogleCalendarClient(config)
