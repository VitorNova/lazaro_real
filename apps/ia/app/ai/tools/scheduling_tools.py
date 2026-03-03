"""
Tools de agendamento para IA (Google Calendar).

Handlers para function calling do Gemini relacionados a:
- Consultar agenda
- Criar agendamentos
- Cancelar agendamentos
- Reagendar

Extraido de: apps/ia/app/webhooks/mensagens.py (Fase 2.9)
"""

from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional

import structlog

from app.config import settings
from app.services.agenda import (
    GoogleCalendarOAuth,
    GoogleCalendarOAuthError,
    create_google_calendar_oauth,
)
from app.services.supabase import SupabaseService

logger = structlog.get_logger(__name__)

# Timezone padrao do sistema
DEFAULT_TIMEZONE = "America/Sao_Paulo"


class SchedulingTools:
    """
    Colecao de tools de agendamento para function calling.

    Usa Google Calendar OAuth2 para gerenciar eventos.
    """

    def __init__(
        self,
        supabase: SupabaseService,
        context: Dict[str, Any],
    ):
        """
        Inicializa as tools de agendamento.

        Args:
            supabase: Servico Supabase para persistencia
            context: Contexto de processamento (agent_id, remotejid, etc)
        """
        self.supabase = supabase
        self.context = context
        self.logger = logger.bind(component="SchedulingTools")

    def _get_lead_timezone(self) -> str:
        """Busca o timezone salvo do lead ou retorna o padrao."""
        try:
            remotejid = self.context.get("remotejid")
            table_leads = self.context.get("table_leads")
            lead = self.supabase.get_lead_by_remotejid(table_leads, remotejid)

            if lead and lead.get("timezone"):
                return lead["timezone"]

            return DEFAULT_TIMEZONE
        except Exception as e:
            self.logger.warning("timezone_fetch_error", error=str(e))
            return DEFAULT_TIMEZONE

    def _get_calendar_client(
        self,
        timezone: Optional[str] = None,
    ) -> Optional[GoogleCalendarOAuth]:
        """
        Cria cliente Google Calendar OAuth2.

        Args:
            timezone: Timezone a usar (opcional, usa do lead se nao fornecido)

        Returns:
            Cliente GoogleCalendarOAuth ou None se nao configurado
        """
        agent_id = self.context.get("agent_id")
        google_creds = self.supabase.get_agent_google_credentials(agent_id)

        if not google_creds:
            self.logger.warning(
                "google_calendar_not_configured",
                agent_id=agent_id,
            )
            return None

        refresh_token = google_creds.get("refresh_token")
        client_id = settings.google_client_id
        client_secret = settings.google_client_secret

        if not client_id or not client_secret or not refresh_token:
            self.logger.error("google_calendar_incomplete_config")
            return None

        tz = timezone or self._get_lead_timezone()
        calendar_id = google_creds.get("calendar_id", "primary")

        return create_google_calendar_oauth(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            calendar_id=calendar_id,
            timezone=tz,
        )

    async def consulta_agenda(
        self,
        date: str = None,
        duration: int = 30,
        days_ahead: int = 5,
        lead_city: str = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Consulta horarios disponiveis na agenda do agente.

        Args:
            date: Data especifica (YYYY-MM-DD) ou None para proximos dias
            duration: Duracao do slot em minutos
            days_ahead: Quantos dias a frente consultar
            lead_city: Cidade do lead (para ajuste de timezone)

        Returns:
            Dict com sucesso, horarios_disponiveis e mensagem
        """
        self.logger.debug(
            "consulta_agenda_start",
            date=date,
            duration=duration,
            days_ahead=days_ahead,
        )

        try:
            lead_timezone = self._get_lead_timezone()
            calendar = self._get_calendar_client(lead_timezone)

            if not calendar:
                return {
                    "sucesso": False,
                    "mensagem": "Google Calendar nao esta configurado para este agente.",
                }

            # Configuracoes de horario de trabalho
            work_hours_start = 9
            work_hours_end = 18

            if date:
                # Buscar disponibilidade para data especifica
                slots = calendar.get_availability(
                    date=date,
                    work_hours_start=work_hours_start,
                    work_hours_end=work_hours_end,
                    slot_duration=duration,
                    timezone=lead_timezone,
                )

                if not slots:
                    return {
                        "sucesso": True,
                        "horarios_disponiveis": [],
                        "mensagem": f"Nao ha horarios disponiveis em {date} com duracao de {duration} minutos.",
                    }

                # Formatar horarios
                horarios_formatados = [
                    {
                        "data": date,
                        "horario": slot["time"],
                        "inicio": slot["start"],
                        "fim": slot["end"],
                    }
                    for slot in slots
                ]

                return {
                    "sucesso": True,
                    "horarios_disponiveis": horarios_formatados,
                    "total": len(horarios_formatados),
                    "mensagem": f"Encontrados {len(horarios_formatados)} horarios disponiveis em {date}.",
                }

            else:
                # Buscar disponibilidade para proximos dias
                availability = calendar.get_multiple_days_availability(
                    days_ahead=days_ahead,
                    work_hours_start=work_hours_start,
                    work_hours_end=work_hours_end,
                    slot_duration=duration,
                    timezone=lead_timezone,
                )

                if not availability:
                    return {
                        "sucesso": True,
                        "horarios_disponiveis": {},
                        "mensagem": f"Nao ha horarios disponiveis nos proximos {days_ahead} dias.",
                    }

                # Formatar resposta
                total_slots = sum(len(slots) for slots in availability.values())

                # Formato compacto para a IA
                slots_compactos = {
                    date: [slot["time"] for slot in slots]
                    for date, slots in availability.items()
                }

                return {
                    "sucesso": True,
                    "slots": slots_compactos,
                    "total": total_slots,
                    "duracao": duration,
                    "mensagem": f"Encontrados {total_slots} horarios disponiveis nos proximos {len(availability)} dias.",
                }

        except GoogleCalendarOAuthError as e:
            self.logger.error("calendar_oauth_error", error=str(e))
            return {
                "sucesso": False,
                "mensagem": f"Erro ao acessar Google Calendar: {str(e)}",
            }
        except Exception as e:
            self.logger.error("consulta_agenda_error", error=str(e), exc_info=True)
            return {
                "sucesso": False,
                "mensagem": f"Erro ao consultar agenda: {str(e)}",
            }

    async def agendar(
        self,
        date: str,
        time: str,
        duration: int = 30,
        title: str = None,
        description: str = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Cria um agendamento no Google Calendar do agente.
        Gera automaticamente um link do Google Meet.

        Args:
            date: Data do agendamento (YYYY-MM-DD)
            time: Horario do agendamento (HH:MM)
            duration: Duracao em minutos
            title: Titulo do evento (opcional)
            description: Descricao do evento (opcional)

        Returns:
            Dict com sucesso, event_id, link_meet, data, horario e mensagem
        """
        self.logger.debug(
            "agendar_start",
            date=date,
            time=time,
            duration=duration,
        )

        try:
            lead_timezone = self._get_lead_timezone()
            calendar = self._get_calendar_client(lead_timezone)

            if not calendar:
                return {
                    "sucesso": False,
                    "mensagem": "Google Calendar nao esta configurado para este agente.",
                }

            # Buscar dados do lead para o evento
            phone = self.context.get("phone")
            remotejid = self.context.get("remotejid")
            table_leads = self.context.get("table_leads")

            lead = self.supabase.get_lead_by_remotejid(table_leads, remotejid)
            lead_name = lead.get("nome", "Cliente") if lead else "Cliente"
            lead_email = lead.get("email") if lead else None

            # Montar data/hora ISO
            start_datetime = f"{date}T{time}:00"
            start_dt = datetime.strptime(start_datetime, "%Y-%m-%dT%H:%M:%S")
            end_dt = start_dt + timedelta(minutes=duration)
            end_datetime = end_dt.strftime("%Y-%m-%dT%H:%M:%S")

            # Criar titulo e descricao
            event_title = title or f"Reuniao com {lead_name}"
            event_description = description or f"""Agendamento realizado via WhatsApp

Lead: {lead_name}
Telefone: {phone}
{"Email: " + lead_email if lead_email else ""}

Observacoes: {description or 'Nenhuma'}
"""

            # Criar evento
            event = calendar.create_event(
                summary=event_title,
                description=event_description,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                timezone=lead_timezone,
                attendee_email=lead_email,
                create_meet_link=True,
            )

            # Atualizar lead com info do agendamento
            if lead:
                self.supabase.update_lead(
                    table_leads,
                    lead["id"],
                    {
                        "next_appointment_at": start_datetime,
                        "next_appointment_link": event.get("hangoutLink", ""),
                        "last_scheduled_at": datetime.utcnow().isoformat(),
                    },
                )

            # Formatar data para resposta
            formatted_date = start_dt.strftime("%d/%m/%Y")
            formatted_time = start_dt.strftime("%H:%M")
            meet_link = event.get("hangoutLink", "")

            self.logger.debug(
                "evento_criado",
                event_id=event.get("id"),
                meet_link=meet_link,
            )

            return {
                "sucesso": True,
                "event_id": event.get("id"),
                "link_meet": meet_link,
                "data": formatted_date,
                "horario": formatted_time,
                "mensagem": f"Agendamento confirmado para {formatted_date} as {formatted_time}."
                + (f" Link da reuniao: {meet_link}" if meet_link else ""),
            }

        except GoogleCalendarOAuthError as e:
            self.logger.error("calendar_oauth_error_agendar", error=str(e))
            return {
                "sucesso": False,
                "mensagem": f"Erro ao criar agendamento: {str(e)}",
            }
        except Exception as e:
            self.logger.error("agendar_error", error=str(e), exc_info=True)
            return {
                "sucesso": False,
                "mensagem": f"Erro ao criar agendamento: {str(e)}",
            }

    async def cancelar(
        self,
        event_id: str = None,
        reason: str = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Cancela um agendamento existente.

        Args:
            event_id: ID do evento no Google Calendar
            reason: Motivo do cancelamento (opcional)

        Returns:
            Dict com sucesso e mensagem
        """
        self.logger.debug(
            "cancelar_start",
            event_id=event_id,
            reason=reason,
        )

        try:
            calendar = self._get_calendar_client()

            if not calendar:
                return {
                    "sucesso": False,
                    "mensagem": "Google Calendar nao esta configurado para este agente.",
                }

            # Se nao tiver event_id, tentar buscar do lead
            if not event_id:
                remotejid = self.context.get("remotejid")
                table_leads = self.context.get("table_leads")
                lead = self.supabase.get_lead_by_remotejid(table_leads, remotejid)

                if lead and lead.get("next_appointment_at"):
                    return {
                        "sucesso": False,
                        "mensagem": "Nao consegui identificar qual agendamento cancelar. Pode me informar mais detalhes?",
                    }
                else:
                    return {
                        "sucesso": False,
                        "mensagem": "Nao encontrei nenhum agendamento pendente para voce.",
                    }

            # Deletar evento
            success = calendar.delete_event(event_id)

            if success:
                # Limpar agendamento do lead
                remotejid = self.context.get("remotejid")
                table_leads = self.context.get("table_leads")
                self.supabase.update_lead_by_remotejid(
                    table_leads,
                    remotejid,
                    {
                        "next_appointment_at": None,
                        "next_appointment_link": None,
                    },
                )

                self.logger.debug("evento_cancelado", event_id=event_id)

                return {
                    "sucesso": True,
                    "mensagem": f"Agendamento cancelado com sucesso."
                    + (f" Motivo: {reason}" if reason else ""),
                }
            else:
                return {
                    "sucesso": False,
                    "mensagem": "Agendamento nao encontrado ou ja foi cancelado.",
                }

        except GoogleCalendarOAuthError as e:
            self.logger.error("calendar_oauth_error_cancelar", error=str(e))
            return {
                "sucesso": False,
                "mensagem": f"Erro ao cancelar agendamento: {str(e)}",
            }
        except Exception as e:
            self.logger.error("cancelar_error", error=str(e), exc_info=True)
            return {
                "sucesso": False,
                "mensagem": f"Erro ao cancelar agendamento: {str(e)}",
            }

    async def reagendar(
        self,
        event_id: str = None,
        nova_data: str = None,
        novo_horario: str = None,
        duration: int = 30,
        reason: str = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Reagenda um evento existente para nova data/hora.

        Args:
            event_id: ID do evento no Google Calendar
            nova_data: Nova data (YYYY-MM-DD)
            novo_horario: Novo horario (HH:MM)
            duration: Duracao em minutos
            reason: Motivo do reagendamento (opcional)

        Returns:
            Dict com sucesso, event_id, link_meet, nova_data, novo_horario e mensagem
        """
        self.logger.debug(
            "reagendar_start",
            event_id=event_id,
            nova_data=nova_data,
            novo_horario=novo_horario,
        )

        try:
            if not nova_data or not novo_horario:
                return {
                    "sucesso": False,
                    "mensagem": "Por favor, informe a nova data e horario desejados.",
                }

            calendar = self._get_calendar_client()

            if not calendar:
                return {
                    "sucesso": False,
                    "mensagem": "Google Calendar nao esta configurado para este agente.",
                }

            # Se nao tiver event_id, nao conseguimos reagendar
            if not event_id:
                return {
                    "sucesso": False,
                    "mensagem": "Nao consegui identificar qual agendamento reagendar. Pode me informar mais detalhes?",
                }

            # Montar nova data/hora
            lead_timezone = self._get_lead_timezone()
            new_start = f"{nova_data}T{novo_horario}:00"
            start_dt = datetime.strptime(new_start, "%Y-%m-%dT%H:%M:%S")
            end_dt = start_dt + timedelta(minutes=duration)
            new_end = end_dt.strftime("%Y-%m-%dT%H:%M:%S")

            # Atualizar evento
            updated_event = calendar.update_event(
                event_id=event_id,
                new_start=new_start,
                new_end=new_end,
                timezone=lead_timezone,
            )

            # Atualizar lead
            remotejid = self.context.get("remotejid")
            table_leads = self.context.get("table_leads")
            self.supabase.update_lead_by_remotejid(
                table_leads,
                remotejid,
                {
                    "next_appointment_at": new_start,
                    "next_appointment_link": updated_event.get("hangoutLink", ""),
                },
            )

            formatted_date = start_dt.strftime("%d/%m/%Y")
            formatted_time = start_dt.strftime("%H:%M")

            self.logger.debug(
                "evento_reagendado",
                event_id=event_id,
                nova_data=formatted_date,
                novo_horario=formatted_time,
            )

            return {
                "sucesso": True,
                "event_id": updated_event.get("id"),
                "link_meet": updated_event.get("hangoutLink", ""),
                "nova_data": formatted_date,
                "novo_horario": formatted_time,
                "mensagem": f"Agendamento reagendado com sucesso para {formatted_date} as {formatted_time}."
                + (f" Motivo: {reason}" if reason else ""),
            }

        except GoogleCalendarOAuthError as e:
            self.logger.error("calendar_oauth_error_reagendar", error=str(e))
            return {
                "sucesso": False,
                "mensagem": f"Erro ao reagendar: {str(e)}",
            }
        except Exception as e:
            self.logger.error("reagendar_error", error=str(e), exc_info=True)
            return {
                "sucesso": False,
                "mensagem": f"Erro ao reagendar: {str(e)}",
            }

    def get_handlers(self) -> Dict[str, Callable]:
        """
        Retorna dicionario de handlers para registro no tool registry.

        Returns:
            Dict com nome_tool -> handler
        """
        return {
            "consulta_agenda": self.consulta_agenda,
            "agendar": self.agendar,
            "cancelar_agendamento": self.cancelar,
            "reagendar": self.reagendar,
        }


# Factory function para criar tools de agendamento
def create_scheduling_tools(
    supabase: SupabaseService,
    context: Dict[str, Any],
) -> SchedulingTools:
    """
    Cria instancia de SchedulingTools.

    Args:
        supabase: Servico Supabase
        context: Contexto de processamento

    Returns:
        Instancia configurada de SchedulingTools
    """
    return SchedulingTools(supabase, context)
