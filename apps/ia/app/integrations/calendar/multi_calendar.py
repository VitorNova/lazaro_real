# ==============================================================================
# MULTI-CALENDAR CLIENT
# Cliente para multiplas agendas Google com prioridade
# Baseado na implementacao TypeScript (apps/api/src/services/calendar/multi-calendar.ts)
# ==============================================================================

from __future__ import annotations

import structlog
from datetime import datetime
from typing import Optional

from .client import GoogleCalendarClient, create_google_calendar_client
from .types import (
    CalendarConfig,
    CalendarEvent,
    CreateEventInput,
    AvailabilityResult,
    AvailabilityParams,
    TimeSlot,
    GoogleAccount,
    MultiCalendarConfig,
    AvailabilityScenario,
    AccountAvailability,
    MultiCalendarAvailabilityResult,
    MultiCalendarEventResult,
    SecondaryEventResult,
    ConflictCheckResult,
    ConflictingEvent,
    do_time_periods_overlap,
)

logger = structlog.get_logger(__name__)


class MultiCalendarClient:
    """Cliente para gerenciar multiplas agendas Google com prioridade."""

    def __init__(self, config: MultiCalendarConfig):
        """
        Inicializa o cliente.

        Args:
            config: Configuracao com multiplas contas (ordenadas por prioridade)
        """
        self.config = config
        self.clients: dict[str, GoogleCalendarClient] = {}

        # Criar clientes para cada conta
        for account in config.accounts:
            client = create_google_calendar_client(
                CalendarConfig(
                    client_id=config.client_id,
                    client_secret=config.client_secret,
                    refresh_token=account.credentials.get("refresh_token", ""),
                    calendar_id=account.calendar_id or "primary",
                )
            )
            self.clients[account.email] = client

    async def get_availability_with_priority(
        self,
        params: AvailabilityParams,
        agent_id: Optional[str] = None,
    ) -> MultiCalendarAvailabilityResult:
        """
        Verifica disponibilidade em todas as agendas e determina o cenario:
        - primary_only: Primaria tem, secundaria nao -> agendar so na primaria
        - secondary_only: Secundaria tem, primaria nao -> agendar so na secundaria
        - both: Ambas tem -> agendar em ambas
        - none: Nenhuma tem -> nao agendar

        Args:
            params: Parametros de disponibilidade
            agent_id: ID do agente (opcional) para filtrar slots customizados

        Returns:
            Resultado com cenario e disponibilidades
        """
        all_availabilities: list[AccountAvailability] = []

        logger.info(
            "multi_calendar_checking_availability",
            account_count=len(self.config.accounts),
            accounts=[a.email for a in self.config.accounts],
        )

        # Verificar disponibilidade em TODAS as contas
        for account in self.config.accounts:
            client = self.clients.get(account.email)

            if not client:
                logger.warning("multi_calendar_client_not_found", email=account.email)
                all_availabilities.append(
                    AccountAvailability(
                        account=account,
                        availability=AvailabilityResult(
                            date=params.date,
                            timezone=params.timezone,
                            work_hours_start=params.work_hours_start,
                            work_hours_end=params.work_hours_end,
                            slot_duration=params.slot_duration,
                            available_slots=[],
                            busy_slots=[],
                        ),
                        has_slots=False,
                    )
                )
                continue

            try:
                logger.debug(
                    "multi_calendar_checking_account",
                    email=account.email,
                )
                availability = await client.get_availability(params)

                # TODO: Aplicar filtro de slots customizado se agent_id fornecido
                # availability.available_slots = filter_slots_for_agent(...)

                has_slots = len(availability.available_slots) > 0
                logger.info(
                    "multi_calendar_account_result",
                    email=account.email,
                    has_slots=has_slots,
                    slot_count=len(availability.available_slots),
                )

                all_availabilities.append(
                    AccountAvailability(
                        account=account,
                        availability=availability,
                        has_slots=has_slots,
                    )
                )

            except Exception as e:
                logger.error(
                    "multi_calendar_check_error",
                    email=account.email,
                    error=str(e),
                )
                all_availabilities.append(
                    AccountAvailability(
                        account=account,
                        availability=AvailabilityResult(
                            date=params.date,
                            timezone=params.timezone,
                            work_hours_start=params.work_hours_start,
                            work_hours_end=params.work_hours_end,
                            slot_duration=params.slot_duration,
                            available_slots=[],
                            busy_slots=[],
                        ),
                        has_slots=False,
                    )
                )

        # Obter resultados da primaria e secundaria
        primary_result = all_availabilities[0] if len(all_availabilities) > 0 else None
        secondary_result = all_availabilities[1] if len(all_availabilities) > 1 else None

        primary_has_slots = primary_result.has_slots if primary_result else False
        secondary_has_slots = secondary_result.has_slots if secondary_result else False

        # Determinar cenario e contas onde agendar
        scenario: AvailabilityScenario
        accounts_to_schedule: list[GoogleAccount] = []
        available_account: Optional[GoogleAccount] = None
        available_account_index = -1
        available_slots: list[TimeSlot] = []
        message: str

        if primary_has_slots and secondary_has_slots:
            # AMBAS tem disponibilidade -> agendar em ambas
            scenario = AvailabilityScenario.BOTH
            accounts_to_schedule = [primary_result.account, secondary_result.account]
            available_account = primary_result.account
            available_account_index = 0
            # Combinar slots (usar intersecao)
            available_slots = self._get_intersection_slots(
                primary_result.availability.available_slots,
                secondary_result.availability.available_slots,
            )
            message = f"Horarios disponiveis em ambas agendas ({primary_result.account.email} e {secondary_result.account.email})"
            logger.info("multi_calendar_scenario_both")

        elif primary_has_slots and not secondary_has_slots:
            # PRIMARIA tem, SECUNDARIA nao -> agendar SOMENTE na primaria
            scenario = AvailabilityScenario.PRIMARY_ONLY
            accounts_to_schedule = [primary_result.account]
            available_account = primary_result.account
            available_account_index = 0
            available_slots = primary_result.availability.available_slots
            message = f"Agenda primaria ({primary_result.account.email}) tem horarios disponiveis"
            logger.info("multi_calendar_scenario_primary_only")

        elif not primary_has_slots and secondary_has_slots:
            # SECUNDARIA tem, PRIMARIA nao -> agendar SOMENTE na secundaria
            scenario = AvailabilityScenario.SECONDARY_ONLY
            accounts_to_schedule = [secondary_result.account]
            available_account = secondary_result.account
            available_account_index = 1
            available_slots = secondary_result.availability.available_slots
            message = f"Agenda secundaria ({secondary_result.account.email}) tem horarios disponiveis"
            logger.info("multi_calendar_scenario_secondary_only")

        else:
            # NENHUMA tem disponibilidade
            scenario = AvailabilityScenario.NONE
            accounts_to_schedule = []
            message = "Nenhuma agenda tem horarios disponiveis para esta data"
            logger.info("multi_calendar_scenario_none")

        return MultiCalendarAvailabilityResult(
            scenario=scenario,
            accounts_to_schedule=accounts_to_schedule,
            available_account=available_account,
            available_account_index=available_account_index,
            primary_availability=primary_result.availability if primary_result else None,
            secondary_availability=secondary_result.availability if secondary_result else None,
            all_availabilities=all_availabilities,
            available_slots=available_slots,
            message=message,
        )

    def _get_intersection_slots(
        self, primary_slots: list[TimeSlot], secondary_slots: list[TimeSlot]
    ) -> list[TimeSlot]:
        """Retorna a intersecao de slots disponiveis em ambas agendas."""
        return [
            primary_slot
            for primary_slot in primary_slots
            if any(
                primary_slot.start == secondary_slot.start
                and primary_slot.end == secondary_slot.end
                for secondary_slot in secondary_slots
            )
        ]

    async def get_availability_range_with_priority(
        self,
        dates: list[str],
        work_hours_start: int,
        work_hours_end: int,
        slot_duration: int,
        timezone: str,
        break_between_slots: int = 0,
        agent_id: Optional[str] = None,
    ) -> list[tuple[str, MultiCalendarAvailabilityResult]]:
        """
        Verifica disponibilidade para multiplos dias com prioridade.

        Args:
            dates: Lista de datas YYYY-MM-DD
            work_hours_start: Hora de inicio do expediente
            work_hours_end: Hora de fim do expediente
            slot_duration: Duracao do slot em minutos
            timezone: Timezone
            break_between_slots: Intervalo entre slots em minutos
            agent_id: ID do agente (opcional)

        Returns:
            Lista de tuplas (data, resultado)
        """
        results: list[tuple[str, MultiCalendarAvailabilityResult]] = []

        for date in dates:
            result = await self.get_availability_with_priority(
                AvailabilityParams(
                    date=date,
                    work_hours_start=work_hours_start,
                    work_hours_end=work_hours_end,
                    slot_duration=slot_duration,
                    timezone=timezone,
                    break_between_slots=break_between_slots,
                ),
                agent_id,
            )
            results.append((date, result))

        return results

    async def create_event_in_all_calendars(
        self,
        input: CreateEventInput,
        target_accounts: list[GoogleAccount],
        scenario: AvailabilityScenario = AvailabilityScenario.PRIMARY_ONLY,
    ) -> MultiCalendarEventResult:
        """
        Cria evento SOMENTE nas agendas especificadas pelo cenario.
        - primary_only: Cria apenas na primaria
        - secondary_only: Cria apenas na secundaria
        - both: Cria em ambas

        Args:
            input: Dados do evento
            target_accounts: Contas onde criar o evento
            scenario: Cenario de disponibilidade

        Returns:
            Resultado com eventos criados
        """
        logger.info(
            "multi_calendar_create_event",
            scenario=scenario.value,
            target_count=len(target_accounts),
            targets=[a.email for a in target_accounts],
        )

        if not target_accounts:
            raise ValueError("Nenhuma conta especificada para criar evento")

        # A primeira conta da lista sera a "principal"
        primary_account = target_accounts[0]
        primary_client = self.clients.get(primary_account.email)

        if not primary_client:
            raise ValueError(f"Client not found for primary account: {primary_account.email}")

        # Criar evento na conta principal (com Meet link)
        logger.info(
            "multi_calendar_creating_primary",
            email=primary_account.email,
            scenario=scenario.value,
        )
        primary_event = await primary_client.create_event(input)
        logger.info(
            "multi_calendar_primary_created",
            event_id=primary_event.id,
        )

        secondary_events: list[SecondaryEventResult] = []
        all_created = True

        # Se cenario e 'both', criar evento na segunda conta tambem
        if scenario == AvailabilityScenario.BOTH and len(target_accounts) > 1:
            secondary_account = target_accounts[1]
            secondary_client = self.clients.get(secondary_account.email)

            if not secondary_client:
                secondary_events.append(
                    SecondaryEventResult(
                        account=secondary_account,
                        event=None,
                        error="Client not found",
                    )
                )
                all_created = False
            else:
                try:
                    logger.info(
                        "multi_calendar_creating_secondary",
                        email=secondary_account.email,
                    )

                    # Criar evento igual (sem Meet link duplicado)
                    secondary_input = CreateEventInput(
                        summary=input.summary,
                        description=input.description,
                        start_date_time=input.start_date_time,
                        end_date_time=input.end_date_time,
                        timezone=input.timezone,
                        attendee_email=input.attendee_email,
                        attendee_name=input.attendee_name,
                        create_meet_link=False,  # Nao criar Meet duplicado
                        send_notifications=False,  # Nao notificar duplicado
                        agnes_metadata=input.agnes_metadata,
                    )

                    secondary_event = await secondary_client.create_event(secondary_input)

                    secondary_events.append(
                        SecondaryEventResult(
                            account=secondary_account,
                            event=secondary_event,
                        )
                    )

                except Exception as e:
                    logger.error(
                        "multi_calendar_secondary_error",
                        email=secondary_account.email,
                        error=str(e),
                    )
                    secondary_events.append(
                        SecondaryEventResult(
                            account=secondary_account,
                            event=None,
                            error=str(e),
                        )
                    )
                    all_created = False

        # Log do cenario
        if scenario == AvailabilityScenario.PRIMARY_ONLY:
            logger.info(
                "multi_calendar_event_created_primary_only",
                email=primary_account.email,
            )
        elif scenario == AvailabilityScenario.SECONDARY_ONLY:
            logger.info(
                "multi_calendar_event_created_secondary_only",
                email=primary_account.email,
            )
        elif scenario == AvailabilityScenario.BOTH:
            logger.info("multi_calendar_event_created_both")

        return MultiCalendarEventResult(
            primary_account=primary_account,
            primary_event=primary_event,
            secondary_events=secondary_events,
            all_created=all_created,
        )

    async def check_conflicts_directly(
        self,
        target_accounts: list[GoogleAccount],
        start_date_time: str,
        end_date_time: str,
        timezone: str = "America/Sao_Paulo",
    ) -> ConflictCheckResult:
        """
        Verifica conflitos diretamente no Google Calendar API.
        Faz uma chamada real para listEvents nas contas alvo.

        Args:
            target_accounts: Contas onde verificar conflitos
            start_date_time: Data/hora de inicio em ISO 8601
            end_date_time: Data/hora de fim em ISO 8601
            timezone: Timezone para formatacao das mensagens

        Returns:
            Resultado com informacao de conflito
        """
        import pytz

        requested_start = datetime.fromisoformat(start_date_time.replace("Z", "+00:00"))
        requested_end = datetime.fromisoformat(end_date_time.replace("Z", "+00:00"))
        conflicting_events: list[ConflictingEvent] = []

        logger.info(
            "multi_calendar_checking_conflicts",
            account_count=len(target_accounts),
            period=f"{start_date_time} to {end_date_time}",
        )

        for account in target_accounts:
            client = self.clients.get(account.email)
            if not client:
                logger.warning(
                    "multi_calendar_conflict_check_no_client",
                    email=account.email,
                )
                continue

            try:
                existing_events = await client.list_events(requested_start, requested_end)

                for evt in existing_events:
                    # Ignorar eventos cancelados e de dia inteiro
                    if evt.status and evt.status.value == "cancelled":
                        continue
                    if evt.is_all_day:
                        continue

                    evt_start = datetime.fromisoformat(
                        evt.start.date_time.replace("Z", "+00:00")
                    )
                    evt_end = datetime.fromisoformat(
                        evt.end.date_time.replace("Z", "+00:00")
                    )

                    # Verificar sobreposicao
                    if do_time_periods_overlap(
                        requested_start, requested_end, evt_start, evt_end
                    ):
                        logger.info(
                            "multi_calendar_conflict_found",
                            email=account.email,
                            event_id=evt.id,
                            summary=evt.summary,
                        )

                        conflicting_events.append(
                            ConflictingEvent(
                                account=account.email,
                                event_id=evt.id,
                                summary=evt.summary or "Evento sem titulo",
                                start=evt.start.date_time,
                                end=evt.end.date_time,
                            )
                        )

            except Exception as e:
                logger.error(
                    "multi_calendar_conflict_check_error",
                    email=account.email,
                    error=str(e),
                )

        if conflicting_events:
            first_conflict = conflicting_events[0]
            conflict_start = datetime.fromisoformat(
                first_conflict.start.replace("Z", "+00:00")
            )
            tz = pytz.timezone(timezone)
            conflict_local = conflict_start.astimezone(tz)
            conflict_formatted = conflict_local.strftime("%H:%M")

            return ConflictCheckResult(
                has_conflict=True,
                conflicting_events=conflicting_events,
                message=f"Ja existe um evento as {conflict_formatted}: \"{first_conflict.summary}\"",
            )

        logger.info("multi_calendar_no_conflicts")
        return ConflictCheckResult(
            has_conflict=False,
            conflicting_events=[],
        )

    async def delete_event_from_all_calendars(
        self,
        event_ids: list[tuple[str, str]],  # [(account_email, event_id), ...]
    ) -> None:
        """
        Deleta evento de todas as agendas.

        Args:
            event_ids: Lista de tuplas (email da conta, ID do evento)
        """
        for account_email, event_id in event_ids:
            client = self.clients.get(account_email)
            if client:
                try:
                    await client.delete_event(event_id)
                except Exception as e:
                    logger.error(
                        "multi_calendar_delete_error",
                        email=account_email,
                        event_id=event_id,
                        error=str(e),
                    )

    @property
    def account_count(self) -> int:
        """Retorna numero de contas configuradas."""
        return len(self.config.accounts)

    @property
    def has_multiple_accounts(self) -> bool:
        """Retorna se tem multiplas contas."""
        return len(self.config.accounts) > 1


# ==============================================================================
# FACTORY FUNCTIONS
# ==============================================================================


def create_multi_calendar_client(config: MultiCalendarConfig) -> MultiCalendarClient:
    """Cria cliente de multi-calendario."""
    return MultiCalendarClient(config)


def create_multi_calendar_client_from_accounts(
    accounts: Optional[list[GoogleAccount]],
    client_id: str,
    client_secret: str,
) -> Optional[MultiCalendarClient]:
    """
    Cria cliente de multi-calendario a partir de google_accounts do banco.

    Args:
        accounts: Lista de contas Google (ou None)
        client_id: Client ID do OAuth2
        client_secret: Client Secret do OAuth2

    Returns:
        MultiCalendarClient ou None se nao houver contas
    """
    if not accounts or len(accounts) == 0:
        return None

    return create_multi_calendar_client(
        MultiCalendarConfig(
            client_id=client_id,
            client_secret=client_secret,
            accounts=accounts,
        )
    )
