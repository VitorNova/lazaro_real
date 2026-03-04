"""
CalendarService - Servico de integracao com Google Calendar.

Este servico gerencia:
- Busca de slots disponiveis
- Criacao de eventos com Google Meet
- Atualizacao de eventos
- Cancelamento de eventos

Usa Google Calendar API com Service Account.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import pytz

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import settings

# Configurar logging
logger = logging.getLogger(__name__)

# Scopes necessarios para Google Calendar API
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]


class CalendarServiceError(Exception):
    """Excecao customizada para erros do CalendarService."""
    pass


class CalendarService:
    """
    Servico para integracao com Google Calendar.

    Gerencia:
    - Busca de horarios disponiveis
    - Criacao de eventos (com Meet automatico)
    - Atualizacao e cancelamento

    Exemplo de uso:
        service = CalendarService()
        service.initialize()
        slots = service.get_available_slots(
            data_inicio="2026-01-27T09:00:00",
            data_fim="2026-01-27T18:00:00",
            duracao_minutos=30
        )
    """

    def __init__(
        self,
        credentials_json: Optional[str] = None,
        calendar_id: str = "primary",
        timezone: str = "America/Sao_Paulo"
    ):
        """
        Inicializa o CalendarService.

        Args:
            credentials_json: JSON das credenciais da service account.
                             Se None, usa settings.google_calendar_credentials
            calendar_id: ID do calendario (default: "primary")
            timezone: Fuso horario (default: "America/Sao_Paulo")
        """
        self._credentials_json = credentials_json or settings.google_calendar_credentials
        self._calendar_id = calendar_id
        self._timezone = timezone
        self._service = None
        self._initialized = False

        logger.info(
            f"CalendarService criado. calendar_id={calendar_id}, "
            f"timezone={timezone}, has_credentials={bool(self._credentials_json)}"
        )

    def initialize(self) -> None:
        """
        Inicializa o cliente Google Calendar com service account.

        Raises:
            CalendarServiceError: Se as credenciais forem invalidas ou ausentes
        """
        if self._initialized:
            logger.debug("CalendarService ja inicializado")
            return

        if not self._credentials_json:
            raise CalendarServiceError(
                "GOOGLE_CALENDAR_CREDENTIALS nao configurado. "
                "Defina a variavel de ambiente com o JSON da service account."
            )

        try:
            # Parse do JSON de credenciais
            if isinstance(self._credentials_json, str):
                credentials_info = json.loads(self._credentials_json)
            else:
                credentials_info = self._credentials_json

            # Criar credenciais
            credentials = service_account.Credentials.from_service_account_info(
                credentials_info,
                scopes=SCOPES
            )

            # Build do servico
            self._service = build("calendar", "v3", credentials=credentials)
            self._initialized = True

            logger.info(
                f"CalendarService inicializado com sucesso. "
                f"service_account={credentials_info.get('client_email', 'N/A')}"
            )

        except json.JSONDecodeError as e:
            raise CalendarServiceError(f"JSON de credenciais invalido: {e}")

        except Exception as e:
            raise CalendarServiceError(f"Erro ao inicializar CalendarService: {e}")

    def _ensure_initialized(self) -> None:
        """Garante que o servico esta inicializado."""
        if not self._initialized or not self._service:
            self.initialize()

    def _parse_datetime(self, dt_str: str) -> datetime:
        """
        Parseia string de data/hora para datetime.

        Suporta formatos:
        - ISO 8601: 2026-01-27T09:00:00
        - ISO com timezone: 2026-01-27T09:00:00-03:00
        - ISO com Z: 2026-01-27T09:00:00Z

        Args:
            dt_str: String de data/hora

        Returns:
            datetime object
        """
        # Remover Z e adicionar +00:00 se necessario
        if dt_str.endswith("Z"):
            dt_str = dt_str[:-1] + "+00:00"

        # Tentar diferentes formatos
        formats = [
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ]

        for fmt in formats:
            try:
                return datetime.strptime(dt_str, fmt)
            except ValueError:
                continue

        # Se nenhum formato funcionar, tentar fromisoformat
        try:
            return datetime.fromisoformat(dt_str)
        except ValueError:
            raise ValueError(f"Formato de data/hora invalido: {dt_str}")

    def get_available_slots(
        self,
        data_inicio: str,
        data_fim: str,
        duracao_minutos: int = 30,
        intervalo_minutos: int = 30
    ) -> List[str]:
        """
        Busca horarios disponiveis no calendario.

        Args:
            data_inicio: Data/hora de inicio da busca (ISO format)
            data_fim: Data/hora de fim da busca (ISO format)
            duracao_minutos: Duracao de cada slot em minutos (default: 30)
            intervalo_minutos: Intervalo entre slots em minutos (default: 30)

        Returns:
            Lista de slots disponiveis em formato ISO 8601

        Example:
            slots = service.get_available_slots(
                data_inicio="2026-01-27T09:00:00",
                data_fim="2026-01-27T18:00:00",
                duracao_minutos=30
            )
            # Retorna: ["2026-01-27T09:00:00", "2026-01-27T09:30:00", ...]
        """
        self._ensure_initialized()

        try:
            start_dt = self._parse_datetime(data_inicio)
            end_dt = self._parse_datetime(data_fim)

            logger.info(
                f"Buscando slots disponiveis de {start_dt} ate {end_dt}, "
                f"duracao={duracao_minutos}min"
            )

            # Buscar eventos existentes no periodo
            events_result = self._service.events().list(
                calendarId=self._calendar_id,
                timeMin=start_dt.isoformat() + "Z" if start_dt.tzinfo is None else start_dt.isoformat(),
                timeMax=end_dt.isoformat() + "Z" if end_dt.tzinfo is None else end_dt.isoformat(),
                singleEvents=True,
                orderBy="startTime"
            ).execute()

            events = events_result.get("items", [])

            logger.debug(f"Encontrados {len(events)} eventos existentes")

            # Extrair periodos ocupados
            busy_periods = []
            for event in events:
                event_start = event.get("start", {})
                event_end = event.get("end", {})

                # Pegar dateTime ou date
                start_str = event_start.get("dateTime") or event_start.get("date")
                end_str = event_end.get("dateTime") or event_end.get("date")

                if start_str and end_str:
                    busy_start = self._parse_datetime(start_str)
                    busy_end = self._parse_datetime(end_str)
                    busy_periods.append((busy_start, busy_end))

            # Gerar todos os slots possiveis
            available_slots = []
            current = start_dt
            slot_duration = timedelta(minutes=duracao_minutos)
            interval = timedelta(minutes=intervalo_minutos)

            while current + slot_duration <= end_dt:
                slot_end = current + slot_duration

                # Verificar se o slot conflita com algum periodo ocupado
                is_available = True
                for busy_start, busy_end in busy_periods:
                    # Normalizar timezones para comparacao
                    current_naive = current.replace(tzinfo=None) if current.tzinfo else current
                    slot_end_naive = slot_end.replace(tzinfo=None) if slot_end.tzinfo else slot_end
                    busy_start_naive = busy_start.replace(tzinfo=None) if busy_start.tzinfo else busy_start
                    busy_end_naive = busy_end.replace(tzinfo=None) if busy_end.tzinfo else busy_end

                    # Verificar overlap
                    if current_naive < busy_end_naive and slot_end_naive > busy_start_naive:
                        is_available = False
                        break

                if is_available:
                    # Formatar slot em ISO 8601
                    slot_str = current.strftime("%Y-%m-%dT%H:%M:%S")
                    available_slots.append(slot_str)

                current += interval

            logger.info(f"Encontrados {len(available_slots)} slots disponiveis")

            return available_slots

        except HttpError as e:
            logger.error(f"Erro HTTP ao buscar slots: {e}")
            raise CalendarServiceError(f"Erro ao buscar horarios disponiveis: {e}")

        except Exception as e:
            logger.error(f"Erro ao buscar slots: {e}")
            raise CalendarServiceError(f"Erro ao buscar horarios disponiveis: {e}")

    def create_event(
        self,
        data_hora: str,
        nome_cliente: str,
        telefone: str,
        email: Optional[str] = None,
        observacoes: Optional[str] = None,
        duracao_minutos: int = 30,
        titulo: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Cria um evento no calendario com Google Meet automatico.

        Args:
            data_hora: Data/hora do evento (ISO format)
            nome_cliente: Nome do cliente
            telefone: Telefone do cliente
            email: Email do cliente (opcional, sera adicionado como convidado)
            observacoes: Observacoes adicionais (opcional)
            duracao_minutos: Duracao do evento em minutos (default: 30)
            titulo: Titulo customizado (default: "Reuniao com {nome_cliente}")

        Returns:
            Dict com id do evento e hangoutLink

        Example:
            result = service.create_event(
                data_hora="2026-01-27T10:00:00",
                nome_cliente="Joao Silva",
                telefone="5511999999999",
                email="joao@email.com",
                duracao_minutos=30
            )
            # Retorna: {"id": "abc123", "hangoutLink": "https://meet.google.com/xxx"}
        """
        self._ensure_initialized()

        try:
            start_dt = self._parse_datetime(data_hora)
            end_dt = start_dt + timedelta(minutes=duracao_minutos)

            # Construir titulo
            event_title = titulo or f"Reuniao com {nome_cliente}"

            # Construir descricao
            description_parts = [
                f"Cliente: {nome_cliente}",
                f"Telefone: {telefone}",
            ]

            if email:
                description_parts.append(f"Email: {email}")

            if observacoes:
                description_parts.append(f"\nObservacoes:\n{observacoes}")

            description = "\n".join(description_parts)

            # Construir evento
            event: Dict[str, Any] = {
                "summary": event_title,
                "description": description,
                "start": {
                    "dateTime": start_dt.isoformat(),
                    "timeZone": self._timezone,
                },
                "end": {
                    "dateTime": end_dt.isoformat(),
                    "timeZone": self._timezone,
                },
                # Habilitar Google Meet automaticamente
                "conferenceData": {
                    "createRequest": {
                        "requestId": f"meet-{start_dt.strftime('%Y%m%d%H%M%S')}-{telefone[-4:]}",
                        "conferenceSolutionKey": {
                            "type": "hangoutsMeet"
                        }
                    }
                },
                # Lembretes
                "reminders": {
                    "useDefault": False,
                    "overrides": [
                        {"method": "popup", "minutes": 30},
                        {"method": "popup", "minutes": 10},
                    ]
                }
            }

            # Adicionar convidado se tiver email
            if email:
                event["attendees"] = [
                    {"email": email, "displayName": nome_cliente}
                ]

            logger.info(
                f"Criando evento: {event_title} em {data_hora}, "
                f"cliente={nome_cliente}, telefone={telefone}"
            )

            # Criar evento com conferenceDataVersion=1 para habilitar Meet
            created_event = self._service.events().insert(
                calendarId=self._calendar_id,
                body=event,
                conferenceDataVersion=1,
                sendUpdates="all" if email else "none"
            ).execute()

            event_id = created_event.get("id", "")
            hangout_link = created_event.get("hangoutLink", "")

            # Tentar obter link do conferenceData se hangoutLink nao estiver disponivel
            if not hangout_link:
                conference_data = created_event.get("conferenceData", {})
                entry_points = conference_data.get("entryPoints", [])
                for entry in entry_points:
                    if entry.get("entryPointType") == "video":
                        hangout_link = entry.get("uri", "")
                        break

            logger.info(
                f"Evento criado com sucesso. id={event_id}, "
                f"hangoutLink={hangout_link or 'N/A'}"
            )

            return {
                "id": event_id,
                "hangoutLink": hangout_link,
                "htmlLink": created_event.get("htmlLink", ""),
                "summary": event_title,
                "start": data_hora,
                "end": end_dt.isoformat(),
            }

        except HttpError as e:
            logger.error(f"Erro HTTP ao criar evento: {e}")
            raise CalendarServiceError(f"Erro ao criar evento: {e}")

        except Exception as e:
            logger.error(f"Erro ao criar evento: {e}")
            raise CalendarServiceError(f"Erro ao criar evento: {e}")

    def delete_event(self, event_id: str) -> bool:
        """
        Deleta um evento do calendario.

        Args:
            event_id: ID do evento a ser deletado

        Returns:
            True se deletado com sucesso, False caso contrario
        """
        self._ensure_initialized()

        try:
            logger.info(f"Deletando evento: {event_id}")

            self._service.events().delete(
                calendarId=self._calendar_id,
                eventId=event_id,
                sendUpdates="all"
            ).execute()

            logger.info(f"Evento {event_id} deletado com sucesso")
            return True

        except HttpError as e:
            if e.resp.status == 404:
                logger.warning(f"Evento {event_id} nao encontrado")
                return False
            logger.error(f"Erro HTTP ao deletar evento: {e}")
            raise CalendarServiceError(f"Erro ao deletar evento: {e}")

        except Exception as e:
            logger.error(f"Erro ao deletar evento: {e}")
            raise CalendarServiceError(f"Erro ao deletar evento: {e}")

    def update_event(
        self,
        event_id: str,
        nova_data_hora: str,
        duracao_minutos: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Atualiza a data/hora de um evento existente.

        Args:
            event_id: ID do evento a ser atualizado
            nova_data_hora: Nova data/hora do evento (ISO format)
            duracao_minutos: Nova duracao (opcional, mantem a anterior se None)

        Returns:
            Dict com dados atualizados do evento

        Example:
            result = service.update_event(
                event_id="abc123",
                nova_data_hora="2026-01-28T14:00:00"
            )
        """
        self._ensure_initialized()

        try:
            logger.info(f"Atualizando evento {event_id} para {nova_data_hora}")

            # Buscar evento existente
            existing_event = self._service.events().get(
                calendarId=self._calendar_id,
                eventId=event_id
            ).execute()

            # Calcular nova duracao
            new_start = self._parse_datetime(nova_data_hora)

            if duracao_minutos:
                new_end = new_start + timedelta(minutes=duracao_minutos)
            else:
                # Calcular duracao original
                old_start_str = existing_event.get("start", {}).get("dateTime")
                old_end_str = existing_event.get("end", {}).get("dateTime")

                if old_start_str and old_end_str:
                    old_start = self._parse_datetime(old_start_str)
                    old_end = self._parse_datetime(old_end_str)
                    original_duration = old_end - old_start
                    new_end = new_start + original_duration
                else:
                    # Fallback para 30 minutos
                    new_end = new_start + timedelta(minutes=30)

            # Atualizar datas
            existing_event["start"] = {
                "dateTime": new_start.isoformat(),
                "timeZone": self._timezone,
            }
            existing_event["end"] = {
                "dateTime": new_end.isoformat(),
                "timeZone": self._timezone,
            }

            # Salvar alteracoes
            updated_event = self._service.events().update(
                calendarId=self._calendar_id,
                eventId=event_id,
                body=existing_event,
                sendUpdates="all"
            ).execute()

            hangout_link = updated_event.get("hangoutLink", "")

            logger.info(f"Evento {event_id} atualizado com sucesso")

            return {
                "id": updated_event.get("id", ""),
                "hangoutLink": hangout_link,
                "htmlLink": updated_event.get("htmlLink", ""),
                "summary": updated_event.get("summary", ""),
                "start": nova_data_hora,
                "end": new_end.isoformat(),
            }

        except HttpError as e:
            if e.resp.status == 404:
                raise CalendarServiceError(f"Evento {event_id} nao encontrado")
            logger.error(f"Erro HTTP ao atualizar evento: {e}")
            raise CalendarServiceError(f"Erro ao atualizar evento: {e}")

        except Exception as e:
            logger.error(f"Erro ao atualizar evento: {e}")
            raise CalendarServiceError(f"Erro ao atualizar evento: {e}")

    def get_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        """
        Busca um evento pelo ID.

        Args:
            event_id: ID do evento

        Returns:
            Dict com dados do evento ou None se nao encontrado
        """
        self._ensure_initialized()

        try:
            event = self._service.events().get(
                calendarId=self._calendar_id,
                eventId=event_id
            ).execute()

            return {
                "id": event.get("id", ""),
                "summary": event.get("summary", ""),
                "description": event.get("description", ""),
                "start": event.get("start", {}).get("dateTime"),
                "end": event.get("end", {}).get("dateTime"),
                "hangoutLink": event.get("hangoutLink", ""),
                "htmlLink": event.get("htmlLink", ""),
                "status": event.get("status", ""),
            }

        except HttpError as e:
            if e.resp.status == 404:
                return None
            raise CalendarServiceError(f"Erro ao buscar evento: {e}")

        except Exception as e:
            logger.error(f"Erro ao buscar evento: {e}")
            raise CalendarServiceError(f"Erro ao buscar evento: {e}")


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_calendar_service: Optional[CalendarService] = None


def get_calendar_service() -> CalendarService:
    """
    Retorna instancia singleton do CalendarService.

    A instancia e inicializada automaticamente na primeira chamada.

    Returns:
        Instancia do CalendarService
    """
    global _calendar_service

    if _calendar_service is None:
        _calendar_service = CalendarService()
        _calendar_service.initialize()

    return _calendar_service


def reset_calendar_service() -> None:
    """
    Reseta a instancia singleton do CalendarService.

    Util para testes ou recarregar credenciais.
    """
    global _calendar_service

    if _calendar_service is not None:
        logger.info("Resetando CalendarService")
        _calendar_service = None


# ============================================================================
# GOOGLE CALENDAR OAUTH2 CLIENT
# Baseado no agnes-agent Node.js - Usa refresh_token do agente
# ============================================================================

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request


class GoogleCalendarOAuthError(Exception):
    """Excecao customizada para erros do GoogleCalendarOAuth."""
    pass


class GoogleCalendarOAuth:
    """
    Cliente Google Calendar usando OAuth2 (refresh_token do agente).

    Diferente do CalendarService que usa Service Account, este cliente
    usa as credenciais OAuth2 do usuario (refresh_token) para acessar
    o calendario pessoal do usuario.

    Baseado no agnes-agent Node.js.

    Exemplo de uso:
        client = GoogleCalendarOAuth(
            client_id="...",
            client_secret="...",
            refresh_token="1//...",
            calendar_id="primary"
        )
        slots = client.get_availability("2026-01-28", 9, 18, 30, "America/Sao_Paulo")
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        calendar_id: str = "primary",
        timezone: str = "America/Sao_Paulo"
    ):
        """
        Inicializa o cliente OAuth2.

        Args:
            client_id: Google OAuth Client ID
            client_secret: Google OAuth Client Secret
            refresh_token: Refresh token do usuario (obtido via OAuth consent)
            calendar_id: ID do calendario (default: "primary")
            timezone: Fuso horario padrao (default: "America/Sao_Paulo")
        """
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._calendar_id = calendar_id
        self._timezone = timezone
        self._service = None
        self._credentials = None

        logger.info(
            f"GoogleCalendarOAuth criado. calendar_id={calendar_id}, "
            f"timezone={timezone}, has_refresh_token={bool(refresh_token)}"
        )

        # Inicializar automaticamente
        self._initialize()

    def _initialize(self) -> None:
        """
        Inicializa o cliente Google Calendar com OAuth2.

        Cria credentials usando refresh_token e configura auto-refresh.
        """
        if not self._refresh_token:
            raise GoogleCalendarOAuthError(
                "refresh_token e obrigatorio para autenticacao OAuth2"
            )

        if not self._client_id or not self._client_secret:
            raise GoogleCalendarOAuthError(
                "GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET sao obrigatorios"
            )

        try:
            # Criar credentials com refresh_token
            # O token de acesso sera obtido automaticamente ao fazer a primeira requisicao
            self._credentials = Credentials(
                token=None,  # Sera obtido via refresh
                refresh_token=self._refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=self._client_id,
                client_secret=self._client_secret,
                scopes=SCOPES
            )

            # Forcar refresh para obter access_token valido
            self._credentials.refresh(Request())

            # Build do servico
            self._service = build("calendar", "v3", credentials=self._credentials)

            logger.info("GoogleCalendarOAuth inicializado com sucesso via refresh_token")

        except Exception as e:
            logger.error(f"Erro ao inicializar GoogleCalendarOAuth: {e}")
            raise GoogleCalendarOAuthError(f"Erro ao inicializar OAuth2: {e}")

    def _ensure_valid_credentials(self) -> None:
        """Garante que as credenciais estao validas, fazendo refresh se necessario."""
        if self._credentials and self._credentials.expired:
            logger.debug("Credenciais expiradas, fazendo refresh...")
            self._credentials.refresh(Request())

    def _parse_datetime(self, dt_str: str) -> datetime:
        """
        Parseia string de data/hora para datetime.

        Suporta formatos ISO 8601 com e sem timezone.
        """
        if dt_str.endswith("Z"):
            dt_str = dt_str[:-1] + "+00:00"

        formats = [
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ]

        for fmt in formats:
            try:
                return datetime.strptime(dt_str, fmt)
            except ValueError:
                continue

        try:
            return datetime.fromisoformat(dt_str)
        except ValueError:
            raise ValueError(f"Formato de data/hora invalido: {dt_str}")

    def get_availability(
        self,
        date: str,
        work_hours_start: int = 9,
        work_hours_end: int = 18,
        slot_duration: int = 30,
        timezone: Optional[str] = None
    ) -> List[Dict]:
        """
        Busca horarios disponiveis para uma data especifica.

        Args:
            date: Data no formato YYYY-MM-DD
            work_hours_start: Hora de inicio do expediente (default: 9)
            work_hours_end: Hora de fim do expediente (default: 18)
            slot_duration: Duracao de cada slot em minutos (default: 30)
            timezone: Fuso horario (default: usa o do construtor)

        Returns:
            Lista de slots disponiveis: [{"start": "ISO", "end": "ISO", "time": "HH:MM"}, ...]
        """
        self._ensure_valid_credentials()
        tz = timezone or self._timezone

        try:
            # Usar pytz para timezone correto
            tz_obj = pytz.timezone(tz)

            # Criar datas de inicio e fim do dia COM timezone
            day_start_naive = datetime.strptime(f"{date}T00:00:00", "%Y-%m-%dT%H:%M:%S")
            day_end_naive = datetime.strptime(f"{date}T23:59:59", "%Y-%m-%dT%H:%M:%S")

            day_start = tz_obj.localize(day_start_naive)
            day_end = tz_obj.localize(day_end_naive)

            logger.info(
                f"Buscando disponibilidade em {date}, "
                f"horario={work_hours_start}h-{work_hours_end}h, slot={slot_duration}min, tz={tz}"
            )

            # Buscar eventos do dia - agora com timezone correto
            events_result = self._service.events().list(
                calendarId=self._calendar_id,
                timeMin=day_start.isoformat(),
                timeMax=day_end.isoformat(),
                singleEvents=True,
                orderBy="startTime"
            ).execute()

            events = events_result.get("items", [])

            logger.debug(f"Encontrados {len(events)} eventos no dia {date}")

            # Extrair periodos ocupados (ignorar eventos de dia inteiro e cancelados)
            busy_periods = []
            for event in events:
                if event.get("status") == "cancelled":
                    continue

                event_start = event.get("start", {})
                event_end = event.get("end", {})

                # Pegar dateTime (eventos com hora) ou ignorar (eventos de dia inteiro)
                start_str = event_start.get("dateTime")
                end_str = event_end.get("dateTime")

                if start_str and end_str:
                    busy_start = self._parse_datetime(start_str)
                    busy_end = self._parse_datetime(end_str)
                    busy_periods.append((busy_start, busy_end))

            # Calcular slots disponiveis
            available_slots = []
            slot_delta = timedelta(minutes=slot_duration)

            # Criar horario de inicio do expediente COM timezone
            current_time = tz_obj.localize(datetime.strptime(
                f"{date}T{work_hours_start:02d}:00:00",
                "%Y-%m-%dT%H:%M:%S"
            ))
            end_of_work = tz_obj.localize(datetime.strptime(
                f"{date}T{work_hours_end:02d}:00:00",
                "%Y-%m-%dT%H:%M:%S"
            ))

            # Converter busy_periods para o mesmo timezone
            busy_periods_local = []
            for busy_start, busy_end in busy_periods:
                # Se tem timezone, converter para timezone local
                if busy_start.tzinfo is not None:
                    busy_start_local = busy_start.astimezone(tz_obj)
                else:
                    busy_start_local = tz_obj.localize(busy_start)
                if busy_end.tzinfo is not None:
                    busy_end_local = busy_end.astimezone(tz_obj)
                else:
                    busy_end_local = tz_obj.localize(busy_end)
                busy_periods_local.append((busy_start_local, busy_end_local))
                logger.debug(f"Busy period (local): {busy_start_local.strftime('%H:%M')} - {busy_end_local.strftime('%H:%M')}")

            while current_time + slot_delta <= end_of_work:
                slot_end = current_time + slot_delta

                # Verificar se o slot conflita com algum periodo ocupado
                is_available = True
                for busy_start, busy_end in busy_periods_local:
                    # Comparar diretamente (todos estao no mesmo timezone agora)
                    if current_time < busy_end and slot_end > busy_start:
                        is_available = False
                        logger.debug(f"Slot {current_time.strftime('%H:%M')} conflita com {busy_start.strftime('%H:%M')}-{busy_end.strftime('%H:%M')}")
                        break

                if is_available:
                    time_str = current_time.strftime("%H:%M")
                    available_slots.append({
                        "start": current_time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "end": slot_end.strftime("%Y-%m-%dT%H:%M:%S"),
                        "time": time_str,
                    })

                # Avancar para proximo slot (sem intervalo entre slots)
                current_time = slot_end

            logger.info(f"Encontrados {len(available_slots)} slots disponiveis em {date}")

            return available_slots

        except HttpError as e:
            logger.error(f"Erro HTTP ao buscar disponibilidade: {e}")
            raise GoogleCalendarOAuthError(f"Erro ao buscar horarios: {e}")
        except Exception as e:
            logger.error(f"Erro ao buscar disponibilidade: {e}")
            raise GoogleCalendarOAuthError(f"Erro ao buscar horarios: {e}")

    def list_events(
        self,
        time_min: str,
        time_max: str,
        timezone: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Lista eventos brutos do calendario em um periodo.

        Args:
            time_min: Data/hora minima (ISO format)
            time_max: Data/hora maxima (ISO format)
            timezone: Fuso horario (default: usa o do construtor)

        Returns:
            Lista de eventos brutos do Google Calendar
        """
        self._ensure_valid_credentials()
        tz = timezone or self._timezone

        try:
            tz_obj = pytz.timezone(tz)

            # Parse datas
            start_dt = self._parse_datetime(time_min)
            end_dt = self._parse_datetime(time_max)

            # Tornar timezone-aware se necessario
            if start_dt.tzinfo is None:
                start_dt = tz_obj.localize(start_dt)
            if end_dt.tzinfo is None:
                end_dt = tz_obj.localize(end_dt)

            logger.info(
                f"Listando eventos de {start_dt.isoformat()} ate {end_dt.isoformat()}"
            )

            events_result = self._service.events().list(
                calendarId=self._calendar_id,
                timeMin=start_dt.isoformat(),
                timeMax=end_dt.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=100
            ).execute()

            events = events_result.get("items", [])

            # Filtrar eventos cancelados
            active_events = [
                e for e in events
                if e.get("status") != "cancelled"
            ]

            logger.info(f"Encontrados {len(active_events)} eventos ativos no periodo")

            return active_events

        except HttpError as e:
            logger.error(f"Erro HTTP ao listar eventos: {e}")
            raise GoogleCalendarOAuthError(f"Erro ao listar eventos: {e}")
        except Exception as e:
            logger.error(f"Erro ao listar eventos: {e}")
            raise GoogleCalendarOAuthError(f"Erro ao listar eventos: {e}")

    def check_slot_available(
        self,
        start_datetime: str,
        end_datetime: str,
        timezone: Optional[str] = None
    ) -> Tuple[bool, List[str]]:
        """
        Verifica se um slot especifico esta disponivel.

        Args:
            start_datetime: Data/hora de inicio (ISO format ou YYYY-MM-DDTHH:MM:SS)
            end_datetime: Data/hora de fim (ISO format ou YYYY-MM-DDTHH:MM:SS)
            timezone: Fuso horario (default: usa o do construtor)

        Returns:
            Tuple (is_available, alternative_times):
            - is_available: True se o slot esta livre
            - alternative_times: Lista de horarios alternativos se ocupado
        """
        self._ensure_valid_credentials()
        tz = timezone or self._timezone
        tz_obj = pytz.timezone(tz)

        try:
            # Parse das datas do slot
            slot_start = self._parse_datetime(start_datetime)
            slot_end = self._parse_datetime(end_datetime)

            # Tornar timezone-aware se necessario
            if slot_start.tzinfo is None:
                slot_start = tz_obj.localize(slot_start)
            if slot_end.tzinfo is None:
                slot_end = tz_obj.localize(slot_end)

            # Extrair data e duracao
            date = slot_start.strftime("%Y-%m-%d")
            duration = int((slot_end - slot_start).total_seconds() / 60)

            # Buscar eventos do dia
            day_start = tz_obj.localize(datetime.strptime(f"{date}T00:00:00", "%Y-%m-%dT%H:%M:%S"))
            day_end = tz_obj.localize(datetime.strptime(f"{date}T23:59:59", "%Y-%m-%dT%H:%M:%S"))

            events_result = self._service.events().list(
                calendarId=self._calendar_id,
                timeMin=day_start.isoformat(),
                timeMax=day_end.isoformat(),
                singleEvents=True,
                orderBy="startTime"
            ).execute()

            events = events_result.get("items", [])

            # Verificar conflito com cada evento
            for event in events:
                if event.get("status") == "cancelled":
                    continue

                event_start_str = event.get("start", {}).get("dateTime")
                event_end_str = event.get("end", {}).get("dateTime")

                if not event_start_str or not event_end_str:
                    continue  # Evento de dia inteiro, ignorar

                event_start = self._parse_datetime(event_start_str)
                event_end = self._parse_datetime(event_end_str)

                # Tornar timezone-aware se necessario
                if event_start.tzinfo is None:
                    event_start = tz_obj.localize(event_start)
                if event_end.tzinfo is None:
                    event_end = tz_obj.localize(event_end)

                # Verificar overlap: slot_start < event_end AND slot_end > event_start
                if slot_start < event_end and slot_end > event_start:
                    logger.info(
                        f"Conflito detectado: slot {slot_start.strftime('%H:%M')}-{slot_end.strftime('%H:%M')} "
                        f"conflita com evento {event_start.strftime('%H:%M')}-{event_end.strftime('%H:%M')}"
                    )

                    # Buscar horarios alternativos
                    alternatives = self.get_availability(
                        date=date,
                        work_hours_start=9,
                        work_hours_end=18,
                        slot_duration=duration,
                        timezone=tz
                    )
                    alt_times = [s["time"] for s in alternatives[:5]]

                    return (False, alt_times)

            # Nenhum conflito encontrado
            return (True, [])

        except Exception as e:
            logger.error(f"Erro ao verificar disponibilidade do slot: {e}")
            # Em caso de erro, permitir criacao (fail-open)
            return (True, [])

    def create_event(
        self,
        summary: str,
        description: str,
        start_datetime: str,
        end_datetime: str,
        timezone: Optional[str] = None,
        attendee_email: Optional[str] = None,
        create_meet_link: bool = True
    ) -> Dict:
        """
        Cria um evento no calendario com Google Meet automatico.

        Args:
            summary: Titulo do evento
            description: Descricao do evento
            start_datetime: Data/hora de inicio (ISO format)
            end_datetime: Data/hora de fim (ISO format)
            timezone: Fuso horario (default: usa o do construtor)
            attendee_email: Email do participante (opcional)
            create_meet_link: Se True, cria link do Google Meet (default: True)

        Returns:
            Dict com id, hangoutLink, htmlLink do evento criado
        """
        self._ensure_valid_credentials()
        tz = timezone or self._timezone

        try:
            logger.info(f"Criando evento: {summary} em {start_datetime}")

            # Verificar se o horario esta disponivel antes de criar
            is_available, alternatives = self.check_slot_available(
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                timezone=tz
            )

            if not is_available:
                alt_str = ", ".join(alternatives) if alternatives else "nenhum disponivel hoje"
                raise GoogleCalendarOAuthError(
                    f"Horario nao disponivel (ja existe evento neste horario). "
                    f"Horarios livres: {alt_str}"
                )

            # Construir evento
            event: Dict[str, Any] = {
                "summary": summary,
                "description": description,
                "start": {
                    "dateTime": start_datetime,
                    "timeZone": tz,
                },
                "end": {
                    "dateTime": end_datetime,
                    "timeZone": tz,
                },
                "reminders": {
                    "useDefault": False,
                    "overrides": [
                        {"method": "popup", "minutes": 30},
                        {"method": "popup", "minutes": 10},
                    ]
                }
            }

            # Adicionar Google Meet se solicitado
            if create_meet_link:
                event["conferenceData"] = {
                    "createRequest": {
                        "requestId": f"meet-{datetime.now().strftime('%Y%m%d%H%M%S')}-{id(self)}",
                        "conferenceSolutionKey": {
                            "type": "hangoutsMeet"
                        }
                    }
                }

            # Adicionar participante se fornecido
            if attendee_email:
                event["attendees"] = [
                    {"email": attendee_email}
                ]

            # Criar evento
            created_event = self._service.events().insert(
                calendarId=self._calendar_id,
                body=event,
                conferenceDataVersion=1 if create_meet_link else 0,
                sendUpdates="all" if attendee_email else "none"
            ).execute()

            event_id = created_event.get("id", "")
            hangout_link = created_event.get("hangoutLink", "")

            # Tentar obter link do conferenceData se hangoutLink nao estiver disponivel
            if not hangout_link:
                conference_data = created_event.get("conferenceData", {})
                entry_points = conference_data.get("entryPoints", [])
                for entry in entry_points:
                    if entry.get("entryPointType") == "video":
                        hangout_link = entry.get("uri", "")
                        break

            logger.info(
                f"Evento criado com sucesso. id={event_id}, "
                f"hangoutLink={hangout_link or 'N/A'}"
            )

            return {
                "id": event_id,
                "hangoutLink": hangout_link,
                "htmlLink": created_event.get("htmlLink", ""),
                "summary": summary,
                "start": start_datetime,
                "end": end_datetime,
            }

        except HttpError as e:
            logger.error(f"Erro HTTP ao criar evento: {e}")
            raise GoogleCalendarOAuthError(f"Erro ao criar evento: {e}")
        except Exception as e:
            logger.error(f"Erro ao criar evento: {e}")
            raise GoogleCalendarOAuthError(f"Erro ao criar evento: {e}")

    def get_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        """
        Busca um evento pelo ID.

        Args:
            event_id: ID do evento

        Returns:
            Dict com dados do evento ou None se nao encontrado
        """
        self._ensure_valid_credentials()

        try:
            event = self._service.events().get(
                calendarId=self._calendar_id,
                eventId=event_id
            ).execute()

            return {
                "id": event.get("id", ""),
                "summary": event.get("summary", ""),
                "description": event.get("description", ""),
                "start": event.get("start", {}).get("dateTime"),
                "end": event.get("end", {}).get("dateTime"),
                "hangoutLink": event.get("hangoutLink", ""),
                "htmlLink": event.get("htmlLink", ""),
                "status": event.get("status", ""),
            }

        except HttpError as e:
            if e.resp.status == 404:
                return None
            logger.error(f"Erro HTTP ao buscar evento: {e}")
            raise GoogleCalendarOAuthError(f"Erro ao buscar evento: {e}")
        except Exception as e:
            logger.error(f"Erro ao buscar evento: {e}")
            raise GoogleCalendarOAuthError(f"Erro ao buscar evento: {e}")

    def delete_event(self, event_id: str) -> bool:
        """
        Deleta um evento do calendario.

        Args:
            event_id: ID do evento a ser deletado

        Returns:
            True se deletado com sucesso, False se evento nao encontrado
        """
        self._ensure_valid_credentials()

        try:
            logger.info(f"Deletando evento: {event_id}")

            self._service.events().delete(
                calendarId=self._calendar_id,
                eventId=event_id,
                sendUpdates="all"
            ).execute()

            logger.info(f"Evento {event_id} deletado com sucesso")
            return True

        except HttpError as e:
            if e.resp.status == 404:
                logger.warning(f"Evento {event_id} nao encontrado")
                return False
            logger.error(f"Erro HTTP ao deletar evento: {e}")
            raise GoogleCalendarOAuthError(f"Erro ao deletar evento: {e}")
        except Exception as e:
            logger.error(f"Erro ao deletar evento: {e}")
            raise GoogleCalendarOAuthError(f"Erro ao deletar evento: {e}")

    def update_event(
        self,
        event_id: str,
        new_start: str,
        new_end: str,
        timezone: Optional[str] = None
    ) -> Dict:
        """
        Atualiza a data/hora de um evento existente.

        Args:
            event_id: ID do evento a ser atualizado
            new_start: Nova data/hora de inicio (ISO format)
            new_end: Nova data/hora de fim (ISO format)
            timezone: Fuso horario (default: usa o do construtor)

        Returns:
            Dict com dados atualizados do evento
        """
        self._ensure_valid_credentials()
        tz = timezone or self._timezone

        try:
            logger.info(f"Atualizando evento {event_id} para {new_start}")

            # Buscar evento existente
            existing_event = self._service.events().get(
                calendarId=self._calendar_id,
                eventId=event_id
            ).execute()

            # Atualizar datas
            existing_event["start"] = {
                "dateTime": new_start,
                "timeZone": tz,
            }
            existing_event["end"] = {
                "dateTime": new_end,
                "timeZone": tz,
            }

            # Salvar alteracoes
            updated_event = self._service.events().update(
                calendarId=self._calendar_id,
                eventId=event_id,
                body=existing_event,
                sendUpdates="all"
            ).execute()

            hangout_link = updated_event.get("hangoutLink", "")

            logger.info(f"Evento {event_id} atualizado com sucesso")

            return {
                "id": updated_event.get("id", ""),
                "hangoutLink": hangout_link,
                "htmlLink": updated_event.get("htmlLink", ""),
                "summary": updated_event.get("summary", ""),
                "start": new_start,
                "end": new_end,
            }

        except HttpError as e:
            if e.resp.status == 404:
                raise GoogleCalendarOAuthError(f"Evento {event_id} nao encontrado")
            logger.error(f"Erro HTTP ao atualizar evento: {e}")
            raise GoogleCalendarOAuthError(f"Erro ao atualizar evento: {e}")
        except Exception as e:
            logger.error(f"Erro ao atualizar evento: {e}")
            raise GoogleCalendarOAuthError(f"Erro ao atualizar evento: {e}")

    def get_multiple_days_availability(
        self,
        days_ahead: int = 5,
        work_hours_start: int = 9,
        work_hours_end: int = 18,
        slot_duration: int = 30,
        timezone: Optional[str] = None,
        work_days: Optional[List[str]] = None
    ) -> Dict[str, List[Dict]]:
        """
        Busca horarios disponiveis para multiplos dias a frente.

        Args:
            days_ahead: Quantos dias a frente buscar (default: 5)
            work_hours_start: Hora de inicio do expediente
            work_hours_end: Hora de fim do expediente
            slot_duration: Duracao de cada slot em minutos
            timezone: Fuso horario
            work_days: Lista de dias permitidos ['monday', 'tuesday', ...]
                       Se None, usa segunda a sexta

        Returns:
            Dict com {date: [slots], ...}
        """
        tz = timezone or self._timezone

        # Dias da semana permitidos (default: seg-sex)
        allowed_days = set()
        if work_days:
            day_map = {
                'monday': 0, 'tuesday': 1, 'wednesday': 2,
                'thursday': 3, 'friday': 4, 'saturday': 5, 'sunday': 6
            }
            for day in work_days:
                if day.lower() in day_map:
                    allowed_days.add(day_map[day.lower()])
        else:
            # Default: segunda a sexta
            allowed_days = {0, 1, 2, 3, 4}

        result = {}
        current_date = datetime.now()
        days_found = 0
        max_iterations = 30  # Evitar loop infinito

        while days_found < days_ahead and max_iterations > 0:
            current_date += timedelta(days=1)
            max_iterations -= 1

            # Verificar se e um dia de trabalho permitido
            if current_date.weekday() not in allowed_days:
                continue

            date_str = current_date.strftime("%Y-%m-%d")

            try:
                slots = self.get_availability(
                    date=date_str,
                    work_hours_start=work_hours_start,
                    work_hours_end=work_hours_end,
                    slot_duration=slot_duration,
                    timezone=tz
                )

                if slots:
                    result[date_str] = slots
                    days_found += 1

            except Exception as e:
                logger.warning(f"Erro ao buscar disponibilidade para {date_str}: {e}")
                continue

        return result


# ============================================================================
# FACTORY FUNCTION
# ============================================================================

def create_google_calendar_oauth(
    client_id: str,
    client_secret: str,
    refresh_token: str,
    calendar_id: str = "primary",
    timezone: str = "America/Sao_Paulo"
) -> GoogleCalendarOAuth:
    """
    Factory function para criar cliente OAuth2 do Google Calendar.

    Args:
        client_id: Google OAuth Client ID
        client_secret: Google OAuth Client Secret
        refresh_token: Refresh token do usuario
        calendar_id: ID do calendario (default: "primary")
        timezone: Fuso horario (default: "America/Sao_Paulo")

    Returns:
        Instancia de GoogleCalendarOAuth
    """
    return GoogleCalendarOAuth(
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
        calendar_id=calendar_id,
        timezone=timezone
    )
