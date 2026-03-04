"""
Calendar Confirmation Job - Lembretes de agenda via WhatsApp.

Envia lembretes 24h e 2h antes de eventos do Google Calendar.
Portado de agnes-agent/src/jobs/calendar-event-confirmation.job.ts

Fluxo:
1. Busca agentes com google_calendar_enabled = true e google_credentials
2. Para cada agente, conecta ao Google Calendar via OAuth
3. Busca eventos das proximas 48 horas
4. Para cada evento, verifica se esta na janela de 24h ou 2h
5. Envia lembrete via WhatsApp (UAZAPI)
6. Registra envio no Supabase (calendar_notifications)
"""

import logging
import re
import traceback
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pytz

from app.config import settings
from app.services.supabase import get_supabase_service
from app.services.uazapi import UazapiService
from app.services.calendar import GoogleCalendarOAuth, GoogleCalendarOAuthError

logger = logging.getLogger(__name__)

# Estado do job
_is_running = False

# Prefixo para logs
LOG_PREFIX = "[CALENDAR JOB]"


# ============================================================================
# LOG HELPERS
# ============================================================================

def _log(msg: str, data: Any = None) -> None:
    extra = f" | {data}" if data else ""
    logger.info(f"{msg}{extra}")


def _log_warn(msg: str) -> None:
    logger.warning(msg)


def _log_error(msg: str) -> None:
    logger.error(msg)


# ============================================================================
# DEFAULT TEMPLATES
# ============================================================================

DEFAULT_TEMPLATE_24H = (
    "Olá {nome}! 👋\n\n"
    "Lembrete: você tem um compromisso agendado para AMANHÃ às {horario}.\n\n"
    "📅 {titulo}\n"
    "🕐 {data} às {horario}\n"
    "📍 {local_ou_link_meet}\n\n"
    "Confirma sua presença? Responda:\n"
    "✅ SIM - Confirmado\n"
    "❌ NÃO - Preciso remarcar"
)

DEFAULT_TEMPLATE_2H = (
    "Olá {nome}! ⏰\n\n"
    "Seu compromisso é em 2 HORAS!\n\n"
    "📅 {titulo}\n"
    "🕐 Hoje às {horario}\n"
    "📍 {local_ou_link_meet}\n\n"
    "Nos vemos em breve! 😊"
)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _extract_phone_from_event(event: Dict[str, Any]) -> Optional[str]:
    """
    Extrai telefone do lead a partir do evento do Google Calendar.

    Prioridade:
    1. extendedProperties.private.leadPhone
    2. description (regex para telefone)
    3. None (nao encontrado)
    """
    # 1. extendedProperties.private.leadPhone
    ext_props = event.get("extendedProperties", {})
    private_props = ext_props.get("private", {})
    lead_phone = private_props.get("leadPhone")
    if lead_phone:
        return _clean_phone(lead_phone)

    # 2. Buscar telefone na descricao via regex
    description = event.get("description", "")
    if description:
        # Padroes comuns de telefone brasileiro
        patterns = [
            r"(?:Telefone|Tel|Phone|Fone|WhatsApp|Celular)[:\s]*(\+?[\d\s\-()]{10,})",
            r"(?:55)?(?:\d{2})?(?:9\d{8})",  # Formato brasileiro
            r"\b\d{10,13}\b",  # Sequencia de 10-13 digitos
        ]
        for pattern in patterns:
            match = re.search(pattern, description, re.IGNORECASE)
            if match:
                phone = match.group(0) if match.lastindex is None else match.group(1)
                cleaned = _clean_phone(phone)
                if len(cleaned) >= 10:
                    return cleaned

    return None


def _extract_lead_name(event: Dict[str, Any]) -> str:
    """Extrai nome do lead do evento."""
    # 1. extendedProperties.private.leadName
    ext_props = event.get("extendedProperties", {})
    private_props = ext_props.get("private", {})
    lead_name = private_props.get("leadName")
    if lead_name:
        return lead_name

    # 2. Primeiro attendee
    attendees = event.get("attendees", [])
    if attendees:
        name = attendees[0].get("displayName")
        if name:
            return name
        # Usar parte do email como nome
        email = attendees[0].get("email", "")
        if email:
            return email.split("@")[0].replace(".", " ").title()

    # 3. Buscar nome na descricao
    description = event.get("description", "")
    if description:
        match = re.search(r"(?:Cliente|Nome|Name)[:\s]*([^\n]+)", description, re.IGNORECASE)
        if match:
            return match.group(1).strip()

    return "Cliente"


def _clean_phone(phone: str) -> str:
    """Remove caracteres nao-numericos do telefone."""
    clean = "".join(filter(str.isdigit, phone))
    if len(clean) == 10 or len(clean) == 11:
        clean = f"55{clean}"
    return clean


def _get_event_location(event: Dict[str, Any]) -> str:
    """Extrai local ou link meet do evento."""
    # 1. Hangout/Meet link
    hangout_link = event.get("hangoutLink", "")
    if hangout_link:
        return hangout_link

    # 2. Conference data
    conference_data = event.get("conferenceData", {})
    entry_points = conference_data.get("entryPoints", [])
    for entry in entry_points:
        if entry.get("entryPointType") == "video":
            return entry.get("uri", "")

    # 3. Location field
    location = event.get("location", "")
    if location:
        return location

    return "A definir"


def _format_template(
    template: str,
    nome: str,
    titulo: str,
    data: str,
    horario: str,
    local_ou_link_meet: str
) -> str:
    """Formata template com variaveis."""
    return template.format(
        nome=nome,
        titulo=titulo,
        data=data,
        horario=horario,
        local_ou_link_meet=local_ou_link_meet,
    )


def _parse_event_datetime(event: Dict[str, Any]) -> Optional[datetime]:
    """Extrai datetime de inicio do evento."""
    start = event.get("start", {})
    dt_str = start.get("dateTime")
    if not dt_str:
        return None  # Evento de dia inteiro, ignorar

    # Parsear ISO format
    if dt_str.endswith("Z"):
        dt_str = dt_str[:-1] + "+00:00"

    try:
        return datetime.fromisoformat(dt_str)
    except ValueError:
        _log_error(f"Erro ao parsear data: {dt_str}")
        return None


# ============================================================================
# NOTIFICATION CHECK / SEND
# ============================================================================

async def _check_already_notified(
    agent_id: str,
    event_id: str,
    notification_type: str
) -> bool:
    """Verifica se ja enviou notificacao para este evento/tipo."""
    try:
        svc = get_supabase_service()
        result = svc.client.table("calendar_notifications") \
            .select("id") \
            .eq("agent_id", agent_id) \
            .eq("event_id", event_id) \
            .eq("notification_type", notification_type) \
            .limit(1) \
            .execute()

        return bool(result.data and len(result.data) > 0)
    except Exception as e:
        _log_error(f"Erro ao verificar notificacao: {e}")
        return False


async def _record_notification(
    agent_id: str,
    event_id: str,
    phone: str,
    notification_type: str,
    event_start: str,
    message_sent: str
) -> None:
    """Registra notificacao enviada no Supabase."""
    try:
        svc = get_supabase_service()
        svc.client.table("calendar_notifications").insert({
            "agent_id": agent_id,
            "event_id": event_id,
            "phone": phone,
            "notification_type": notification_type,
            "event_start": event_start,
            "message_sent": message_sent,
            "sent_at": datetime.utcnow().isoformat(),
        }).execute()
    except Exception as e:
        _log_error(f"Erro ao registrar notificacao: {e}")


async def _send_reminder(
    uazapi: UazapiService,
    phone: str,
    message: str
) -> bool:
    """Envia lembrete via WhatsApp."""
    try:
        result = await uazapi.send_text_message(phone, message)
        return result.get("success", False)
    except Exception as e:
        _log_error(f"Erro ao enviar lembrete para {phone}: {e}")
        return False


# ============================================================================
# AGENT PROCESSING
# ============================================================================

async def _get_agents_with_calendar() -> List[Dict[str, Any]]:
    """Busca agentes com Google Calendar habilitado."""
    try:
        svc = get_supabase_service()
        result = svc.client.table("agents") \
            .select("id,name,google_credentials,google_calendar_id,google_calendar_enabled,"
                    "schedule_confirmation_enabled,schedule_confirmation_config,"
                    "uazapi_base_url,uazapi_token,timezone") \
            .eq("google_calendar_enabled", True) \
            .execute()

        agents = result.data or []
        # Filtrar apenas os que tem credenciais
        return [
            a for a in agents
            if a.get("google_credentials") and a.get("google_credentials", {}).get("refresh_token")
        ]
    except Exception as e:
        _log_error(f"Erro ao buscar agentes com calendar: {e}")
        return []


async def _process_agent_calendar(agent: Dict[str, Any]) -> Dict[str, Any]:
    """Processa eventos de um agente."""
    stats = {"sent_24h": 0, "sent_2h": 0, "skipped": 0, "errors": 0}

    agent_id = agent.get("id", "")
    agent_name = agent.get("name", "Unknown")
    tz_str = agent.get("timezone", "America/Sao_Paulo")

    # Verificar se confirmacao esta habilitada
    if not agent.get("schedule_confirmation_enabled", True):
        _log(f"Confirmacao desabilitada para {agent_name}")
        return stats

    # Obter templates (customizados ou default)
    config = agent.get("schedule_confirmation_config") or {}
    template_24h = config.get("defaultConfirmationMessage24h") or DEFAULT_TEMPLATE_24H
    template_2h = config.get("defaultConfirmationMessage2h") or DEFAULT_TEMPLATE_2H

    # Configurar UAZAPI para este agente
    uazapi_base_url = agent.get("uazapi_base_url")
    uazapi_token = agent.get("uazapi_token")

    if not uazapi_base_url or not uazapi_token:
        _log_warn(f"Agente {agent_name} sem UAZAPI configurado")
        return stats

    uazapi = UazapiService(base_url=uazapi_base_url, api_key=uazapi_token)

    # Conectar ao Google Calendar
    google_creds = agent.get("google_credentials", {})
    calendar_id = agent.get("google_calendar_id", "primary")

    try:
        calendar = GoogleCalendarOAuth(
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            refresh_token=google_creds.get("refresh_token"),
            calendar_id=calendar_id,
            timezone=tz_str
        )
    except GoogleCalendarOAuthError as e:
        _log_error(f"Erro ao conectar Calendar para {agent_name}: {e}")
        stats["errors"] += 1
        return stats

    # Calcular janela de busca (agora ate +48h)
    tz_obj = pytz.timezone(tz_str)
    now = datetime.now(tz_obj)
    time_max = now + timedelta(hours=48)

    _log(f"Buscando eventos de {now.isoformat()} ate {time_max.isoformat()}")

    try:
        events = calendar.list_events(
            time_min=now.isoformat(),
            time_max=time_max.isoformat(),
            timezone=tz_str
        )
    except Exception as e:
        _log_error(f"Erro ao buscar eventos para {agent_name}: {e}")
        stats["errors"] += 1
        return stats

    _log(f"Encontrados {len(events)} eventos nas proximas 48h")

    for event in events:
        event_id = event.get("id", "")
        event_title = event.get("summary", "Evento sem titulo")

        # Parsear data do evento
        event_dt = _parse_event_datetime(event)
        if not event_dt:
            continue

        # Converter para timezone do agente
        if event_dt.tzinfo is None:
            event_dt = tz_obj.localize(event_dt)
        else:
            event_dt = event_dt.astimezone(tz_obj)

        # Calcular horas ate o evento
        hours_until = (event_dt - now).total_seconds() / 3600

        # Extrair telefone
        phone = _extract_phone_from_event(event)
        if not phone:
            _log(f"Evento \"{event_title}\" - sem telefone identificavel, pulando")
            stats["skipped"] += 1
            continue

        # Extrair dados do lead
        lead_name = _extract_lead_name(event)
        location = _get_event_location(event)
        event_date = event_dt.strftime("%d/%m/%Y")
        event_time = event_dt.strftime("%H:%M")

        # Verificar janela de 24h (entre 23h e 25h)
        if 23.0 <= hours_until <= 25.0:
            # Verificar duplicata
            already = await _check_already_notified(agent_id, event_id, "24h")
            if already:
                _log(f"Evento \"{event_title}\" - lembrete 24h ja enviado, pulando")
                stats["skipped"] += 1
                continue

            # Formatar e enviar
            message = _format_template(
                template_24h, lead_name, event_title,
                event_date, event_time, location
            )

            _log(f"Evento \"{event_title}\" - faltam {hours_until:.1f}h - enviando lembrete 24h")
            _log(f"Enviando para {phone}...")

            success = await _send_reminder(uazapi, phone, message)
            if success:
                await _record_notification(
                    agent_id, event_id, phone, "24h",
                    event_dt.isoformat(), message
                )
                stats["sent_24h"] += 1
                _log(f"✅ Lembrete 24h enviado para {phone}")
            else:
                stats["errors"] += 1
                _log_error(f"❌ Falha ao enviar lembrete 24h para {phone}")

        # Verificar janela de 2h (entre 1h30 e 2h30)
        elif 1.5 <= hours_until <= 2.5:
            # Verificar duplicata
            already = await _check_already_notified(agent_id, event_id, "2h")
            if already:
                _log(f"Evento \"{event_title}\" - lembrete 2h ja enviado, pulando")
                stats["skipped"] += 1
                continue

            # Formatar e enviar
            message = _format_template(
                template_2h, lead_name, event_title,
                event_date, event_time, location
            )

            _log(f"Evento \"{event_title}\" - faltam {hours_until:.1f}h - enviando lembrete 2h")
            _log(f"Enviando para {phone}...")

            success = await _send_reminder(uazapi, phone, message)
            if success:
                await _record_notification(
                    agent_id, event_id, phone, "2h",
                    event_dt.isoformat(), message
                )
                stats["sent_2h"] += 1
                _log(f"✅ Lembrete 2h enviado para {phone}")
            else:
                stats["errors"] += 1
                _log_error(f"❌ Falha ao enviar lembrete 2h para {phone}")

        else:
            _log(f"Evento \"{event_title}\" - faltam {hours_until:.1f}h - fora da janela (pulando)")
            stats["skipped"] += 1

    return stats


# ============================================================================
# MAIN JOB FUNCTIONS
# ============================================================================

async def run_calendar_confirmation_job() -> Dict[str, Any]:
    """
    Job principal de confirmacao de agenda.
    Roda a cada 30 minutos via APScheduler.
    """
    global _is_running

    if _is_running:
        _log_warn("Job ja esta em execucao, pulando...")
        return {"status": "skipped", "reason": "already_running"}

    _is_running = True
    _log("Iniciando job de confirmacao de agenda...")

    total_stats = {
        "sent_24h": 0, "sent_2h": 0, "skipped": 0,
        "errors": 0, "agents_processed": 0
    }

    try:
        agents = await _get_agents_with_calendar()
        _log(f"Encontrados {len(agents)} agentes com Google Calendar configurado")

        if not agents:
            _log("Nenhum agente com Calendar configurado encontrado")
            return {"status": "completed", "stats": total_stats, "message": "no_agents"}

        for agent in agents:
            agent_name = agent.get("name", "Unknown")
            agent_id = agent.get("id", "")
            _log(f"Processando agente: {agent_name} ({agent_id})")

            try:
                agent_stats = await _process_agent_calendar(agent)
                total_stats["sent_24h"] += agent_stats.get("sent_24h", 0)
                total_stats["sent_2h"] += agent_stats.get("sent_2h", 0)
                total_stats["skipped"] += agent_stats.get("skipped", 0)
                total_stats["errors"] += agent_stats.get("errors", 0)
                total_stats["agents_processed"] += 1
                _log(f"Agente {agent_name}: {agent_stats}")
            except Exception as e:
                _log_error(f"Erro ao processar agente {agent_name}: {e}")
                _log_error(traceback.format_exc())
                total_stats["errors"] += 1

        total_sent = total_stats["sent_24h"] + total_stats["sent_2h"]
        _log(
            f"Job finalizado: {total_sent} lembretes enviados "
            f"({total_stats['sent_24h']} de 24h, {total_stats['sent_2h']} de 2h), "
            f"{total_stats['skipped']} pulados, {total_stats['errors']} erros"
        )

        return {"status": "completed", "stats": total_stats}

    except Exception as e:
        _log_error(f"Erro no processamento: {e}")
        _log_error(traceback.format_exc())
        return {"status": "error", "error": str(e)}

    finally:
        _is_running = False


def is_calendar_confirmation_running() -> bool:
    """Verifica se o job esta em execucao."""
    return _is_running


async def _force_run_calendar_confirmation() -> Dict[str, Any]:
    """
    Versao forcada do job - para debug/testes.
    Mesma logica, sem restricoes.
    """
    global _is_running

    if _is_running:
        _log_warn("Job ja esta em execucao, pulando...")
        return {"status": "skipped", "reason": "already_running"}

    _is_running = True
    _log("=== EXECUCAO FORCADA (debug/teste) ===")

    total_stats = {
        "sent_24h": 0, "sent_2h": 0, "skipped": 0,
        "errors": 0, "agents_processed": 0
    }

    try:
        agents = await _get_agents_with_calendar()
        _log(f"Encontrados {len(agents)} agentes com Google Calendar configurado")

        if not agents:
            _log("Nenhum agente com Calendar configurado encontrado")
            return {"status": "completed", "stats": total_stats, "message": "no_agents"}

        for agent in agents:
            agent_name = agent.get("name", "Unknown")
            agent_id = agent.get("id", "")
            _log(f"Processando agente: {agent_name} ({agent_id})")

            try:
                agent_stats = await _process_agent_calendar(agent)
                total_stats["sent_24h"] += agent_stats.get("sent_24h", 0)
                total_stats["sent_2h"] += agent_stats.get("sent_2h", 0)
                total_stats["skipped"] += agent_stats.get("skipped", 0)
                total_stats["errors"] += agent_stats.get("errors", 0)
                total_stats["agents_processed"] += 1
                _log(f"Agente {agent_name}: {agent_stats}")
            except Exception as e:
                _log_error(f"Erro ao processar agente {agent_name}: {e}")
                _log_error(traceback.format_exc())
                total_stats["errors"] += 1

        total_sent = total_stats["sent_24h"] + total_stats["sent_2h"]
        _log(
            f"=== Job finalizado: {total_sent} lembretes enviados "
            f"({total_stats['sent_24h']} de 24h, {total_stats['sent_2h']} de 2h), "
            f"{total_stats['skipped']} pulados, {total_stats['errors']} erros ==="
        )

        return {"status": "completed", "stats": total_stats}

    except Exception as e:
        _log_error(f"Erro no processamento: {e}")
        _log_error(traceback.format_exc())
        return {"status": "error", "error": str(e)}

    finally:
        _is_running = False
