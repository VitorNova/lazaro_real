"""
Follow-Up Job - Envio automatico de follow-ups inteligentes (Salvador).

Gera mensagens personalizadas por IA (Gemini) com base no historico de conversa,
em vez de usar templates fixos. Fallback para mensagens padrao se Gemini falhar.

Fluxo:
1. Busca agentes com follow_up_enabled = true
2. Para cada agente, busca leads elegiveis para follow-up
3. Verifica criterios: ultimo contato foi da IA, lead nao respondeu, nao pausado, etc
4. Detecta opt-out no historico de conversa
5. Rate limiting via Redis (max/dia, cooldown por lead)
6. Carrega historico de conversa e gera mensagem via Gemini
7. Envia mensagem via WhatsApp (UAZAPI)
8. Registra envio no banco (follow_up_notifications + follow_up_history)
9. Salva mensagem no conversation_history do lead
"""

import asyncio
import json
import logging
import traceback
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import google.generativeai as genai
import pytz

from app.services.supabase import get_supabase_service
from app.services.whatsapp_api import UazapiService
from app.core.utils.dias_uteis import (
    get_now_brasilia,
    get_today_brasilia,
    is_business_day,
    is_business_hours,
    is_weekend,
)

logger = logging.getLogger(__name__)

# Estado do job (evita execucao concorrente)
_is_running = False

# Prefixo para logs
LOG_PREFIX = "[Salvador]"


# ============================================================================
# OPT-OUT DETECTION
# ============================================================================

OPT_OUT_PATTERNS: List[str] = [
    "nao quero", "não quero",
    "para de mandar", "pare de mandar",
    "para de enviar", "pare de enviar",
    "nao me mande", "não me mande",
    "nao mande mais", "não mande mais",
    "me deixa em paz", "me deixe em paz",
    "nao tenho interesse", "não tenho interesse",
    "sem interesse",
    "para com isso", "pare com isso",
    "nao preciso", "não preciso",
    "cancelar", "desinscrever",
    "sai fora", "saia",
    "bloquear", "spam",
    "para por favor", "pare por favor",
]


def _detect_opt_out(message: str) -> bool:
    """Detecta se a mensagem contem pedido de opt-out."""
    if not message:
        return False
    lower = message.lower().strip()
    return any(pattern in lower for pattern in OPT_OUT_PATTERNS)


# ============================================================================
# FALLBACK MESSAGES (quando Gemini falha)
# ============================================================================

FALLBACK_MESSAGES: List[str] = [
    "Oi {nome}! Vi que nao conseguimos concluir nossa conversa. Posso ajudar com algo?",
    "Oi {nome}! Ainda estou por aqui caso precise de ajuda. Tem alguma duvida?",
    "Ola {nome}! Ultima tentativa de contato. Se precisar de algo, e so chamar!",
]

# Configuracao padrao de follow-up (formato real do Supabase)
DEFAULT_INACTIVITY_STEPS: List[Dict[str, Any]] = [
    {"delayMinutes": 1440, "useAI": True, "message": "", "template": "followup_1"},
    {"delayMinutes": 2880, "useAI": True, "message": "", "template": "followup_2"},
    {"delayMinutes": 4320, "useAI": True, "message": "", "template": "followup_3"},
]

DEFAULT_LIMITS: Dict[str, Any] = {
    "maxFollowUpsPerLead": 3,
    "maxFollowUpsPerDay": 50,
}

DEFAULT_SCHEDULE: Dict[str, int] = {
    "startHour": 8,
    "endHour": 20,
}

# Pipeline steps que bloqueiam follow-up
BLOCKED_PIPELINE_STEPS = {
    "agendado", "scheduled", "reuniao", "meeting",
    "fechado", "ganho", "won", "lost", "archived",
    "closed", "converted",
}

# Dias da semana por nome (weekday() retorna 0=seg ... 6=dom)
WEEKDAY_NAMES = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]


# ============================================================================
# SALVADOR CONFIG NORMALIZER
# ============================================================================

def _get_salvador_config(agent: Dict[str, Any]) -> Dict[str, Any]:
    """
    Retorna config normalizada do Salvador.

    Prioridade: salvador_config JSONB > follow_up_config legado > defaults.

    Formato esperado em salvador_config:
    {
        "schedule": { "days": [1,2,3,4,5], "start": "09:00", "end": "18:00" },
        "steps": [10, 30, 120, 1440],   # delays em MINUTOS
        "max_followups": 4,
        "prompt": "Voce e um assistente de vendas..."
    }

    days: lista de inteiros Python weekday() - 0=seg, 1=ter ... 6=dom
    """
    # 1. Tentar ler salvador_config JSONB
    raw = agent.get("salvador_config") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, json.JSONDecodeError):
            raw = {}

    # 2. Se salvador_config esta vazio, tentar migrar do formato legado
    if not raw:
        fc = agent.get("follow_up_config") or {}
        if isinstance(fc, str):
            try:
                fc = json.loads(fc)
            except (ValueError, json.JSONDecodeError):
                fc = {}

        if fc:
            # Tentar extrair steps do legado (pode ser lista de dicts com delayMinutes)
            legacy_steps = fc.get("steps") or []
            if legacy_steps and isinstance(legacy_steps[0], dict):
                raw["steps"] = [
                    int(s.get("delayMinutes", 1440)) for s in legacy_steps
                ]
            elif legacy_steps and isinstance(legacy_steps[0], (int, float)):
                raw["steps"] = [int(s) for s in legacy_steps]

    # 3. Normalizar schedule
    schedule_raw = raw.get("schedule") or {}
    if isinstance(schedule_raw, str):
        try:
            schedule_raw = json.loads(schedule_raw)
        except (ValueError, json.JSONDecodeError):
            schedule_raw = {}

    schedule_days = schedule_raw.get("days")
    if not schedule_days:
        schedule_days = [0, 1, 2, 3, 4]  # seg-sex

    start_str = schedule_raw.get("start", "08:00")
    end_str = schedule_raw.get("end", "20:00")

    try:
        start_hour = int(start_str.split(":")[0])
        start_minute = int(start_str.split(":")[1]) if ":" in start_str else 0
    except (ValueError, IndexError, AttributeError):
        start_hour, start_minute = 8, 0

    try:
        end_hour = int(end_str.split(":")[0])
        end_minute = int(end_str.split(":")[1]) if ":" in end_str else 0
    except (ValueError, IndexError, AttributeError):
        end_hour, end_minute = 20, 0

    # 4. Normalizar steps (lista de minutos de delay)
    steps_raw = raw.get("steps")
    if not steps_raw:
        steps_raw = [1440, 2880, 4320]  # defaults: 1d, 2d, 3d em minutos

    steps_minutes = []
    for s in steps_raw:
        try:
            steps_minutes.append(int(s))
        except (ValueError, TypeError):
            steps_minutes.append(1440)

    # 5. Max follow-ups
    max_followups = raw.get("max_followups")
    if not max_followups:
        # Tentar campo legado
        max_followups = agent.get("max_follow_ups") or len(steps_minutes)
    try:
        max_followups = int(max_followups)
    except (ValueError, TypeError):
        max_followups = len(steps_minutes)

    # 6. Prompt do Salvador
    prompt = raw.get("prompt") or agent.get("salvador_prompt") or ""

    return {
        "schedule": {
            "days": schedule_days,
            "start_hour": start_hour,
            "start_minute": start_minute,
            "end_hour": end_hour,
            "end_minute": end_minute,
        },
        "steps_minutes": steps_minutes,
        "max_followups": max_followups,
        "prompt": prompt,
    }


def _is_within_schedule(
    config: Dict[str, Any],
    tz_str: str = "America/Sao_Paulo",
) -> Tuple[bool, str]:
    """
    Verifica se o momento atual esta dentro do schedule configurado.
    Retorna (pode_rodar, motivo).
    """
    schedule = config.get("schedule", {})
    allowed_days = schedule.get("days", [0, 1, 2, 3, 4])
    start_hour = schedule.get("start_hour", 8)
    start_minute = schedule.get("start_minute", 0)
    end_hour = schedule.get("end_hour", 20)
    end_minute = schedule.get("end_minute", 0)

    try:
        tz = pytz.timezone(tz_str)
    except Exception:
        tz = pytz.timezone("America/Sao_Paulo")

    now = datetime.now(tz)
    weekday = now.weekday()

    # Verificar dia da semana
    if weekday not in allowed_days:
        day_name = WEEKDAY_NAMES[weekday] if weekday < len(WEEKDAY_NAMES) else str(weekday)
        return False, f"dia_bloqueado ({day_name})"

    # Verificar horario
    now_minutes = now.hour * 60 + now.minute
    start_minutes = start_hour * 60 + start_minute
    end_minutes = end_hour * 60 + end_minute

    if now_minutes < start_minutes:
        return False, f"antes_horario ({start_hour:02d}:{start_minute:02d})"
    if now_minutes >= end_minutes:
        return False, f"apos_horario ({end_hour:02d}:{end_minute:02d})"

    return True, "ok"


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
# HELPER FUNCTIONS
# ============================================================================

def _get_now_in_timezone(tz_str: str = "America/Cuiaba") -> datetime:
    """Retorna datetime atual no timezone especificado."""
    try:
        tz = pytz.timezone(tz_str)
    except Exception:
        tz = pytz.timezone("America/Cuiaba")
    return datetime.now(tz)


def _is_within_business_hours(
    tz_str: str = "America/Cuiaba",
    start_hour: int = 8,
    end_hour: int = 20,
) -> bool:
    """Verifica se estamos em horario comercial no timezone do agente."""
    now = _get_now_in_timezone(tz_str)
    return start_hour <= now.hour < end_hour


def _parse_iso_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """Parse de datetime ISO string para datetime aware (UTC se sem timezone)."""
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = pytz.utc.localize(dt)
        return dt
    except (ValueError, TypeError):
        return None


def _hours_since(dt_str: Optional[str], tz_str: str = "America/Cuiaba") -> Optional[float]:
    """Calcula horas desde um datetime ISO string ate agora."""
    dt = _parse_iso_datetime(dt_str)
    if not dt:
        return None
    now = _get_now_in_timezone(tz_str)
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    now_utc = now.astimezone(pytz.utc)
    dt_utc = dt.astimezone(pytz.utc)
    diff = (now_utc - dt_utc).total_seconds() / 3600
    return diff


def _get_delay_hours(step: Dict[str, Any]) -> float:
    """Converte delay de um step para horas."""
    delay_minutes = step.get("delayMinutes")
    if delay_minutes is not None:
        return float(delay_minutes) / 60.0

    delay = step.get("delay", 24)
    unit = step.get("unit", "hours")

    if unit == "minutes":
        return delay / 60
    elif unit == "days":
        return delay * 24
    else:
        return delay


def _get_lead_first_name(lead: Dict[str, Any]) -> str:
    """Extrai primeiro nome do lead. Retorna vazio se nao tiver nome real."""
    nome = (lead.get("nome") or "").strip()
    if not nome or nome.lower() in ("cliente", "desconhecido", "sem nome", "lead"):
        return ""
    return nome.split()[0]


def _phone_to_remotejid(phone: str) -> str:
    """Converte telefone para formato remoteJid do WhatsApp."""
    cleaned = "".join(filter(str.isdigit, phone))
    return f"{cleaned}@s.whatsapp.net"


# ============================================================================
# REDIS RATE LIMITING
# ============================================================================

async def _get_redis_client():
    """Obtem cliente Redis (retorna None se indisponivel)."""
    try:
        from app.services import get_redis_service
        redis_svc = await get_redis_service()
        return redis_svc.client
    except Exception:
        return None


async def _can_send_follow_up_redis(
    agent_id: str,
    remotejid: str,
    max_per_day: int = 50,
) -> Tuple[bool, str]:
    """Verifica rate limiting via Redis. Retorna (pode_enviar, motivo)."""
    redis_client = await _get_redis_client()
    if not redis_client:
        return True, "redis_unavailable"

    try:
        # Check daily limit por agente
        date_key = datetime.utcnow().strftime("%Y-%m-%d")
        daily_key = f"salvador:daily:{agent_id}:{date_key}"
        daily_count = await redis_client.get(daily_key)
        if daily_count and int(daily_count) >= max_per_day:
            return False, f"daily_limit ({daily_count}/{max_per_day})"

        # Check per-lead cooldown (evita flood)
        lead_key = f"salvador:lead:{agent_id}:{remotejid}"
        if await redis_client.exists(lead_key):
            return False, "lead_cooldown"

        return True, "ok"
    except Exception as e:
        _log_warn(f"Redis rate limit check error: {e}")
        return True, "redis_error"


async def _record_follow_up_redis(
    agent_id: str,
    remotejid: str,
    cooldown_seconds: int = 3600,
) -> None:
    """Registra envio no Redis para rate limiting."""
    redis_client = await _get_redis_client()
    if not redis_client:
        return

    try:
        # Incrementa contador diario
        date_key = datetime.utcnow().strftime("%Y-%m-%d")
        daily_key = f"salvador:daily:{agent_id}:{date_key}"
        await redis_client.incr(daily_key)
        await redis_client.expire(daily_key, 86400)

        # Seta cooldown por lead (default 1h entre follow-ups do mesmo lead)
        lead_key = f"salvador:lead:{agent_id}:{remotejid}"
        await redis_client.set(lead_key, "1", ex=cooldown_seconds)
    except Exception as e:
        _log_warn(f"Redis record error: {e}")


# ============================================================================
# CONVERSATION HISTORY
# ============================================================================

async def _load_conversation_history(
    agent: Dict[str, Any],
    remotejid: str,
) -> List[Dict[str, Any]]:
    """Carrega historico de conversa do lead (ultimas 20 mensagens)."""
    supabase = get_supabase_service()
    table_messages = agent.get("table_messages")
    if not table_messages:
        return []

    try:
        response = (
            supabase.client.table(table_messages)
            .select("conversation_history")
            .eq("remotejid", remotejid)
            .order("creat", desc=True)
            .limit(1)
            .execute()
        )

        if not response.data:
            return []

        history = response.data[0].get("conversation_history") or {}
        messages = history.get("messages", [])
        return messages[-20:]

    except Exception as e:
        _log_warn(f"Erro ao carregar historico de {remotejid}: {e}")
        return []


def _build_conversation_summary(history: List[Dict[str, Any]], max_messages: int = 20) -> str:
    """Constroi resumo textual do historico de conversa."""
    if not history:
        return "Sem historico de conversa."

    # Incluir primeira mensagem do usuario (mostra intencao original)
    first_user_msg = None
    for msg in history:
        if msg.get("role") == "user":
            text = ""
            if msg.get("content"):
                text = msg["content"]
            elif msg.get("parts"):
                parts = msg["parts"]
                if isinstance(parts, list):
                    for p in parts:
                        if isinstance(p, dict) and p.get("text"):
                            text = p["text"]
                            break
            if text:
                first_user_msg = f"[PRIMEIRA MSG DO LEAD]: {text[:500]}"
                break

    lines = []
    if first_user_msg:
        lines.append(first_user_msg)

    for msg in history[-max_messages:]:
        role = "Cliente" if msg.get("role") == "user" else "Assistente"
        text = ""
        if msg.get("content"):
            text = msg["content"]
        elif msg.get("parts"):
            parts = msg["parts"]
            if isinstance(parts, list):
                text = " ".join(
                    p.get("text", "") for p in parts if isinstance(p, dict)
                )
        if text:
            lines.append(f"{role}: {text[:500]}")

    return "\n".join(lines) if lines else "Sem historico de conversa."



# ============================================================================
# AI CLASSIFIER - Decide se deve ou nao enviar follow-up
# ============================================================================

CLASSIFIER_PROMPT = """Voce e um classificador de leads da Aluga Ar (aluguel de ar-condicionado).
Analise o historico e decida se o lead deve receber follow-up.

Responda APENAS com JSON:
{"acao": "ENVIAR", "motivo": "texto curto"}
ou
{"acao": "SKIP", "motivo": "texto curto"}

ENVIAR quando:
- Lead perguntou sobre aluguel e parou de responder
- Lead perguntou preco, BTUs, como funciona e sumiu
- Lead so mandou oi/ola e nao respondeu mais

SKIP para todo o resto:
- Conversa sobre manutencao, defeito, conserto, ar quebrado, pingando
- Conversa sobre pagamento, fatura, boleto, comprovante
- Lead ja fechou aluguel
- Lead disse que nao quer
- Lead ja e cliente resolvendo problema
- Conversa encerrada e assunto resolvido
- Qualquer assunto que NAO seja interesse em alugar ar-condicionado"""


async def _classify_lead_for_follow_up(
    history: List[Dict[str, Any]],
    lead_name: str,
) -> Tuple[bool, str]:
    """
    Classifica se o lead deve receber follow-up.
    Retorna (deve_enviar: bool, motivo: str)
    """
    summary = _build_conversation_summary(history)

    if not summary or summary.strip() == "Sem historico disponivel.":
        return False, "sem historico"

    try:
        from app.config import settings

        genai.configure(api_key=settings.google_api_key)

        model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            system_instruction=CLASSIFIER_PROMPT,
            generation_config={
                "temperature": 0.1,
                "max_output_tokens": 100,
            },
        )

        response = await model.generate_content_async(
            f"Historico do lead {lead_name}:\n{summary}"
        )

        if response and response.text:
            text = response.text.strip()
            text = text.replace("```json", "").replace("```", "").strip()

            result = json.loads(text)
            acao = result.get("acao", "SKIP").upper()
            motivo = result.get("motivo", "sem motivo")

            if acao == "ENVIAR":
                _log(f"Classificador: ENVIAR para {lead_name} - {motivo}")
                return True, motivo
            else:
                _log(f"Classificador: SKIP para {lead_name} - {motivo}")
                return False, motivo

    except json.JSONDecodeError as e:
        _log_warn(f"Classificador: JSON invalido para {lead_name}: {e}")
        return False, "erro parse json"
    except Exception as e:
        _log_error(f"Classificador: erro para {lead_name}: {e}")
        return False, f"erro: {e}"

    return False, "sem resposta do classificador"


# ============================================================================
# AI MESSAGE GENERATION (Gemini)
# ============================================================================

async def _generate_follow_up_message(
    lead: Dict[str, Any],
    agent: Dict[str, Any],
    history: List[Dict[str, Any]],
    step_number: int,
    custom_prompt: str = "",
) -> str:
    """
    Gera mensagem de follow-up personalizada via Gemini.
    Fallback para mensagem padrao se Gemini falhar.

    custom_prompt: prompt do salvador_config (tem prioridade sobre system_prompt do agente)
    """
    first_name = _get_lead_first_name(lead)

    summary = _build_conversation_summary(history)
    pipeline_step = lead.get("pipeline_step") or "novo"

    # Prioridade: prompt do salvador_config > system_prompt do agente > default
    system_prompt = custom_prompt or agent.get("system_prompt") or (
        "Voce e um assistente de vendas amigavel e profissional."
    )

    nome_info = f'NOME: {first_name}' if first_name else 'NOME: (sem nome — nao use nome nenhum na mensagem)'

    user_prompt = f"""{nome_info}
Follow-up numero: {step_number}
Status do lead: {pipeline_step}

Historico da conversa:
{summary}

Escreva APENAS a mensagem de follow-up. Nada mais."""

    try:
        from app.config import settings

        genai.configure(api_key=settings.google_api_key)

        model = genai.GenerativeModel(
            model_name=settings.gemini_model,
            system_instruction=system_prompt,
            generation_config={
                "temperature": 0.8,
                "max_output_tokens": 500,
            },
        )

        response = await model.generate_content_async(user_prompt)

        if response and response.text and response.text.strip():
            generated = response.text.strip()
            # Limpar aspas que Gemini as vezes coloca ao redor da mensagem
            if generated.startswith('"') and generated.endswith('"'):
                generated = generated[1:-1]
            _log(f"Gemini gerou mensagem ({len(generated)} chars) para {first_name}")
            return generated

    except Exception as e:
        _log_error(f"Erro ao gerar mensagem com Gemini: {e}")

    # Fallback
    idx = min(step_number - 1, len(FALLBACK_MESSAGES) - 1)
    if first_name:
        fallback = FALLBACK_MESSAGES[idx].replace("{nome}", first_name)
    else:
        fallback = FALLBACK_MESSAGES[idx].replace("Oi {nome}! ", "").replace("Ola {nome}! ", "").replace("{nome}", "")
    _log_warn(f"Usando fallback para {first_name or 'lead'}: {fallback[:50]}...")
    return fallback


# ============================================================================
# DATABASE FUNCTIONS
# ============================================================================

async def _resolve_shared_whatsapp(supabase, agents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Para agentes com uses_shared_whatsapp=true, copia uazapi_base_url/token do parent."""
    parent_ids = [
        a["parent_agent_id"] for a in agents
        if a.get("uses_shared_whatsapp") and a.get("parent_agent_id")
    ]
    if not parent_ids:
        return agents

    parent_resp = (
        supabase.client.table("agents")
        .select("id, uazapi_base_url, uazapi_token, uazapi_instance_id")
        .in_("id", parent_ids)
        .execute()
    )
    parents = {p["id"]: p for p in (parent_resp.data or [])}

    for agent in agents:
        if agent.get("uses_shared_whatsapp") and agent.get("parent_agent_id"):
            parent = parents.get(agent["parent_agent_id"])
            if parent:
                agent["uazapi_base_url"] = parent["uazapi_base_url"]
                agent["uazapi_token"] = parent["uazapi_token"]
                agent["uazapi_instance_id"] = parent["uazapi_instance_id"]
                _log(f"Agente {agent.get('name')} usando WhatsApp do parent {agent['parent_agent_id']}")

    return agents


async def _get_agents_with_follow_up() -> List[Dict[str, Any]]:
    """Busca agentes com follow-up habilitado."""
    supabase = get_supabase_service()
    try:
        response = (
            supabase.client.table("agents")
            .select(
                "id, name, follow_up_enabled, follow_up_config, "
                "salvador_config, salvador_prompt, max_follow_ups, "
                "uazapi_base_url, uazapi_token, uazapi_instance_id, "
                "table_leads, table_messages, timezone, "
                "handoff_triggers, system_prompt, "
                "uses_shared_whatsapp, parent_agent_id"
            )
            .eq("status", "active")
            .eq("follow_up_enabled", True)
            .execute()
        )

        agents = response.data or []

        # Resolver credenciais UAZAPI do parent para agentes com WhatsApp compartilhado
        agents = await _resolve_shared_whatsapp(supabase, agents)

        result = []
        for agent in agents:
            if agent.get("uazapi_base_url") and agent.get("uazapi_token"):
                result.append(agent)
            else:
                _log_warn(
                    f"Agente {agent.get('name')} sem UAZAPI configurado, pulando"
                )

        return result

    except Exception as e:
        _log_error(f"Erro ao buscar agentes com follow-up: {e}")
        return []


async def _get_eligible_leads(
    agent: Dict[str, Any],
    max_follow_ups: int,
) -> List[Dict[str, Any]]:
    """
    Busca leads elegiveis para follow-up.

    Criterios:
    - Atendimento nao finalizado
    - IA nao pausada
    - Na fila da IA (ou sem fila)
    - Ultima mensagem foi da IA (Msg_model > Msg_user)
    - Nao excedeu maxFollowUps
    - Nao optou por sair do follow-up
    - Pipeline step nao bloqueado
    """
    supabase = get_supabase_service()
    table_leads = agent.get("table_leads")
    table_messages = agent.get("table_messages")

    if not table_leads or not table_messages:
        _log_warn(f"Agente {agent.get('name')} sem tabelas configuradas")
        return []

    try:
        # Filtro de data minima: so leads com atividade nos ultimos 7 dias
        agent_tz_str = agent.get("timezone", "America/Sao_Paulo")
        try:
            agent_tz = pytz.timezone(agent_tz_str)
        except Exception:
            agent_tz = pytz.timezone("America/Sao_Paulo")
        min_date = datetime.now(agent_tz) - timedelta(days=7)
        min_date_str = min_date.isoformat()

        query = (
            supabase.client.table(table_leads)
            .select("*")
            .neq("Atendimento_Finalizado", "true")
            .gte("updated_date", min_date_str)
        )

        response = query.execute()
        all_leads = response.data or []
        _log(f"Filtro de 7 dias: {len(all_leads)} leads com atividade recente")

        eligible = []
        for lead in all_leads:
            # Filtro: IA nao pausada
            if lead.get("pausar_ia") is True:
                continue

            # Filtro: nao optou por sair
            if lead.get("follow_up_opted_out") is True:
                continue

            # Filtro: follow_up_count nao excedeu maximo
            follow_up_count = lead.get("follow_up_count") or 0
            if follow_up_count >= max_follow_ups:
                continue

            # Filtro: pipeline step bloqueado
            pipeline_step = (lead.get("pipeline_step") or "").lower()
            if pipeline_step in BLOCKED_PIPELINE_STEPS:
                continue

            # Filtro: tem agendamento marcado
            if lead.get("next_appointment_at"):
                continue

            # Filtro: verificar fila da IA
            handoff = agent.get("handoff_triggers") or {}
            queue_ia = handoff.get("queue_ia")
            current_queue = lead.get("current_queue_id")

            if current_queue is not None and queue_ia is not None:
                try:
                    if int(current_queue) != int(queue_ia):
                        continue
                except (ValueError, TypeError) as e:
                    _log_warn(
                        f"Erro ao comparar queues para {lead.get('remotejid')}: "
                        f"current={current_queue}, ia={queue_ia}, erro={e}"
                    )

            # Verificar timestamps de mensagem na tabela de mensagens
            remotejid = lead.get("remotejid")
            if not remotejid:
                continue

            try:
                msg_response = (
                    supabase.client.table(table_messages)
                    .select("Msg_model, Msg_user, creat")
                    .eq("remotejid", remotejid)
                    .order("creat", desc=True)
                    .limit(1)
                    .execute()
                )

                if not msg_response.data:
                    continue

                msg_record = msg_response.data[0]
                msg_model = msg_record.get("Msg_model")
                msg_user = msg_record.get("Msg_user")

                if not msg_model:
                    continue

                if msg_user:
                    model_dt = _parse_iso_datetime(msg_model)
                    user_dt = _parse_iso_datetime(msg_user)

                    if model_dt and user_dt and user_dt > model_dt:
                        continue

                lead["_last_ia_message_at"] = msg_model
                lead["_last_lead_message_at"] = msg_user

            except Exception as e:
                _log_warn(f"Erro ao verificar mensagens de {remotejid}: {e}")
                continue

            eligible.append(lead)

        return eligible

    except Exception as e:
        _log_error(f"Erro ao buscar leads elegiveis: {e}")
        return []


async def _record_follow_up_notification(
    agent_id: str,
    lead_phone: str,
    follow_up_number: int,
    message_sent: str,
) -> None:
    """Registra follow-up enviado na tabela follow_up_notifications."""
    supabase = get_supabase_service()
    try:
        supabase.client.table("follow_up_notifications").insert({
            "agent_id": agent_id,
            "lead_phone": lead_phone,
            "follow_up_number": follow_up_number,
            "message_sent": message_sent,
            "sent_at": datetime.utcnow().isoformat(),
            "lead_responded": False,
        }).execute()
    except Exception as e:
        _log_error(f"Erro ao registrar follow-up notification: {e}")


async def _log_follow_up_history(
    agent_id: str,
    lead: Dict[str, Any],
    remotejid: str,
    step_number: int,
    message: str,
    table_leads: str,
) -> Optional[str]:
    """Registra follow-up na tabela follow_up_history (metricas)."""
    supabase = get_supabase_service()
    try:
        lead_id = lead.get("id")
        # follow_up_history.lead_id e integer NOT NULL
        if not isinstance(lead_id, int):
            try:
                lead_id = int(lead_id)
            except (ValueError, TypeError):
                return None

        data = {
            "agent_id": agent_id,
            "lead_id": lead_id,
            "table_leads": table_leads,
            "remotejid": remotejid,
            "step_number": step_number,
            "follow_up_type": "inactivity",
            "message_sent": message,
            "lead_name": lead.get("nome") or lead.get("push_name"),
            "pipeline_step": lead.get("pipeline_step"),
        }

        result = (
            supabase.client.table("follow_up_history")
            .insert(data)
            .execute()
        )

        if result.data:
            return result.data[0].get("id")
    except Exception as e:
        _log_warn(f"Erro ao registrar follow_up_history: {e}")

    return None


async def _update_lead_follow_up(
    table_leads: str,
    lead_id: int,
    follow_up_count: int,
    follow_up_stage: int,
) -> None:
    """Atualiza campos de follow-up no lead apos envio."""
    supabase = get_supabase_service()
    try:
        supabase.client.table(table_leads).update({
            "follow_up_count": follow_up_count,
            "follow_up_stage": follow_up_stage,
            "last_follow_up_at": datetime.utcnow().isoformat(),
            "follow_count": follow_up_count,
            "updated_date": datetime.utcnow().isoformat(),
        }).eq("id", lead_id).execute()
    except Exception as e:
        _log_error(f"Erro ao atualizar lead follow-up: {e}")


async def _save_follow_up_to_history(
    table_messages: str,
    remotejid: str,
    message: str,
    follow_up_number: int,
) -> None:
    """Salva mensagem de follow-up no conversation_history do lead."""
    supabase = get_supabase_service()
    try:
        response = (
            supabase.client.table(table_messages)
            .select("id, conversation_history")
            .eq("remotejid", remotejid)
            .order("creat", desc=True)
            .limit(1)
            .execute()
        )

        if not response.data:
            return

        msg_record = response.data[0]
        history = msg_record.get("conversation_history") or {"messages": []}
        messages = history.get("messages", [])

        now = datetime.utcnow().isoformat()

        # Adicionar nota de contexto para a IA entender que foi follow-up
        context_note = "[CONTEXTO: Esta mensagem foi um follow-up automatico enviado porque o lead nao respondeu. O historico completo da conversa esta acima. Continue a conversa normalmente a partir do contexto anterior.]"
        message_with_context = f"{context_note}\n\n{message}"

        messages.append({
            "role": "model",
            "parts": [{"text": message_with_context}],
            "timestamp": now,
            "sender": "follow_up",
            "sender_name": f"Follow-up #{follow_up_number}",
            "type": "follow_up_notification",
            "follow_up_number": follow_up_number,
        })

        supabase.client.table(table_messages).update({
            "conversation_history": {"messages": messages},
            "Msg_model": now,
            "creat": now,
        }).eq("id", msg_record["id"]).execute()

    except Exception as e:
        _log_warn(f"Erro ao salvar follow-up no historico: {e}")


# ============================================================================
# MAIN PROCESSING
# ============================================================================

async def _process_agent_follow_up(
    agent: Dict[str, Any],
    force_mode: bool = False,
) -> Dict[str, int]:
    """
    Processa follow-ups para um agente especifico.
    Usa Gemini para gerar mensagens personalizadas com base no historico.

    force_mode=True ignora verificacoes de horario/dia (apenas para debug).
    """
    stats = {"sent": 0, "skipped": 0, "errors": 0}

    agent_id = agent.get("id", "")
    agent_name = agent.get("name", "Unknown")
    agent_tz = agent.get("timezone", "America/Sao_Paulo")

    # Obter configuracao normalizada do Salvador
    # Prioridade: salvador_config JSONB > follow_up_config legado > defaults
    salvador_cfg = _get_salvador_config(agent)
    steps_minutes = salvador_cfg["steps_minutes"]     # lista de delays em minutos
    max_follow_ups = salvador_cfg["max_followups"]
    salvador_prompt = salvador_cfg["prompt"]

    _log(
        f"Processando agente: {agent_name} ({agent_id[:8]}...) "
        f"| {len(steps_minutes)} steps | max={max_follow_ups}"
        f"| prompt={'sim' if salvador_prompt else 'nao'}"
    )

    # Verificar schedule (dias e horario)
    if not force_mode:
        can_run, reason = _is_within_schedule(salvador_cfg, agent_tz)
        if not can_run:
            _log(f"Agente {agent_name}: fora do schedule ({reason})")
            return stats

    # Rate limit diario (fixo: 50/dia por agente)
    max_per_day = 50

    # Buscar leads elegiveis
    eligible_leads = await _get_eligible_leads(agent, max_follow_ups)
    _log(f"Encontrados {len(eligible_leads)} leads elegiveis para follow-up")

    if not eligible_leads:
        return stats

    # Configurar UAZAPI
    uazapi = UazapiService(
        base_url=agent["uazapi_base_url"],
        api_key=agent["uazapi_token"],
    )

    table_leads = agent.get("table_leads", "")
    table_messages = agent.get("table_messages", "")

    for lead in eligible_leads:
        lead_id = lead.get("id")
        remotejid = lead.get("remotejid", "")
        nome = lead.get("nome") or lead.get("push_name") or "Cliente"
        telefone = lead.get("telefone") or remotejid.replace("@s.whatsapp.net", "").replace("@lid", "")
        first_name = _get_lead_first_name(lead)

        current_count = lead.get("follow_up_count") or 0
        next_follow_up_number = current_count + 1

        # Verificar se ainda ha steps a enviar
        if next_follow_up_number > len(steps_minutes):
            stats["skipped"] += 1
            continue

        # Delay do step atual em minutos (convertido para horas)
        delay_minutes = steps_minutes[next_follow_up_number - 1]
        required_delay_hours = delay_minutes / 60.0

        # Calcular horas desde ultima mensagem da IA
        last_ia_msg = lead.get("_last_ia_message_at") or lead.get("last_follow_up_at")
        hours_since_last = _hours_since(last_ia_msg, agent_tz)

        if hours_since_last is None:
            stats["skipped"] += 1
            continue

        # Verificar se ja passou tempo suficiente
        if hours_since_last < required_delay_hours:
            continue

        # ================================================================
        # RATE LIMITING via Redis
        # ================================================================
        can_send, reason = await _can_send_follow_up_redis(
            agent_id, remotejid, max_per_day
        )
        if not can_send:
            _log(f"Rate limited {telefone}: {reason}")
            stats["skipped"] += 1
            continue

        # ================================================================
        # CARREGAR HISTORICO + OPT-OUT CHECK
        # ================================================================
        conversation_history = await _load_conversation_history(agent, remotejid)

        # Verificar opt-out nas ultimas mensagens do usuario
        opt_out_detected = False
        for msg in reversed(conversation_history[-5:]):
            if msg.get("role") == "user":
                text = ""
                if msg.get("content"):
                    text = msg["content"]
                elif msg.get("parts"):
                    parts = msg["parts"]
                    if isinstance(parts, list):
                        text = " ".join(
                            p.get("text", "") for p in parts if isinstance(p, dict)
                        )
                if _detect_opt_out(text):
                    _log_warn(f"Opt-out detectado para {telefone}, marcando lead")
                    opt_out_detected = True
                    try:
                        supabase = get_supabase_service()
                        supabase.client.table(table_leads).update({
                            "follow_up_opted_out": True,
                            "follow_up_opted_out_at": datetime.utcnow().isoformat(),
                        }).eq("id", lead_id).execute()
                    except Exception:
                        pass
                    stats["skipped"] += 1
                    break

        if opt_out_detected:
            continue

        # ================================================================
        # CLASSIFICAR LEAD (Gemini Flash - decide se envia ou nao)
        # ================================================================
        deve_enviar, motivo = await _classify_lead_for_follow_up(
            conversation_history, first_name or "lead"
        )
        if not deve_enviar:
            _log(f"Lead {telefone} classificado como SKIP: {motivo}")
            stats["skipped"] += 1
            continue

        # ================================================================
        # GERAR MENSAGEM
        # ================================================================

        # Gera mensagem via Gemini usando prompt do salvador_config
        message = await _generate_follow_up_message(
            lead, agent, conversation_history, next_follow_up_number,
            custom_prompt=salvador_prompt,
        )

        # Verificar se Gemini decidiu nao enviar (SKIP)
        if message.strip().upper().startswith("SKIP"):
            _log(f"Gemini retornou SKIP para {telefone} - contexto nao requer follow-up")
            stats["skipped"] += 1
            continue

        _log(
            f"Lead {telefone} - {hours_since_last:.1f}h desde ultimo contato "
            f"- enviando follow-up #{next_follow_up_number} ({len(message)} chars)"
        )

        try:
            # Enviar mensagem via WhatsApp com assinatura do agente
            agent_name = agent.get("name", "Assistente")
            result = await uazapi.send_signed_message(telefone, message, agent_name)

            if not result.get("success"):
                raise ValueError(result.get("error", "Erro desconhecido ao enviar"))

            _log(f"Follow-up #{next_follow_up_number} enviado para {telefone} ({agent_name}): {message[:80]}...")

            # Registrar em Redis
            await _record_follow_up_redis(agent_id, remotejid)

            # Registrar notificacao (tabela legacy)
            await _record_follow_up_notification(
                agent_id, telefone, next_follow_up_number, message
            )

            # Registrar no follow_up_history (metricas)
            await _log_follow_up_history(
                agent_id, lead, remotejid,
                next_follow_up_number, message, table_leads
            )

            # Atualizar campos de follow-up no lead
            await _update_lead_follow_up(
                table_leads, lead_id, next_follow_up_number, next_follow_up_number
            )

            # Salvar no conversation_history
            await _save_follow_up_to_history(
                table_messages, remotejid, message, next_follow_up_number
            )

            stats["sent"] += 1

            # Rate limiting: esperar 1.5s entre envios
            await asyncio.sleep(1.5)

        except Exception as e:
            _log_error(f"Erro ao enviar follow-up para {telefone}: {e}")
            stats["errors"] += 1

    return stats


# ============================================================================
# JOB ENTRY POINTS
# ============================================================================

async def run_follow_up_job() -> Dict[str, Any]:
    """
    Job principal de follow-up (Salvador).
    Roda a cada 5 minutos via APScheduler.
    Respeita horario comercial e dias uteis.
    """
    global _is_running

    if _is_running:
        _log_warn("Job ja esta em execucao, pulando...")
        return {"status": "skipped", "reason": "already_running"}

    _is_running = True
    _log("Iniciando job de follow-up...")

    total_stats = {
        "sent": 0, "skipped": 0, "errors": 0,
        "agents_processed": 0
    }

    try:
        agents = await _get_agents_with_follow_up()
        _log(f"Encontrados {len(agents)} agentes com follow-up habilitado")

        if not agents:
            _log("Nenhum agente com follow-up habilitado encontrado")
            return {"status": "completed", "stats": total_stats, "message": "no_agents"}

        for agent in agents:
            agent_name = agent.get("name", "Unknown")
            agent_id = agent.get("id", "")
            _log(f"Processando agente: {agent_name} ({agent_id[:8]}...)")

            try:
                agent_stats = await _process_agent_follow_up(agent)
                total_stats["sent"] += agent_stats.get("sent", 0)
                total_stats["skipped"] += agent_stats.get("skipped", 0)
                total_stats["errors"] += agent_stats.get("errors", 0)
                total_stats["agents_processed"] += 1
                _log(f"Agente {agent_name}: {agent_stats}")
            except Exception as e:
                _log_error(f"Erro ao processar agente {agent_name}: {e}")
                _log_error(traceback.format_exc())
                total_stats["errors"] += 1

        _log(
            f"Job finalizado: {total_stats['sent']} follow-ups enviados, "
            f"{total_stats['skipped']} pulados, {total_stats['errors']} erros"
        )

        return {"status": "completed", "stats": total_stats}

    except Exception as e:
        _log_error(f"Erro no processamento: {e}")
        _log_error(traceback.format_exc())
        return {"status": "error", "error": str(e)}

    finally:
        _is_running = False


def is_follow_up_running() -> bool:
    """Verifica se o job esta em execucao."""
    return _is_running


async def _force_run_follow_up() -> Dict[str, Any]:
    """
    Versao forcada do job - ignora verificacoes de horario/dia util.
    APENAS PARA DEBUG/TESTES.
    """
    global _is_running

    if _is_running:
        _log_warn("Job ja esta em execucao, pulando...")
        return {"status": "skipped", "reason": "already_running"}

    _is_running = True
    _log("=== EXECUCAO FORCADA (ignorando horario/dia util) ===")

    total_stats = {
        "sent": 0, "skipped": 0, "errors": 0,
        "agents_processed": 0
    }

    try:
        supabase = get_supabase_service()
        response = (
            supabase.client.table("agents")
            .select(
                "id, name, follow_up_enabled, follow_up_config, "
                "salvador_config, salvador_prompt, max_follow_ups, "
                "uazapi_base_url, uazapi_token, uazapi_instance_id, "
                "table_leads, table_messages, timezone, "
                "handoff_triggers, system_prompt, "
                "uses_shared_whatsapp, parent_agent_id"
            )
            .eq("status", "active")
            .eq("follow_up_enabled", True)
            .execute()
        )

        agents = await _resolve_shared_whatsapp(supabase, response.data or [])
        agents = [
            a for a in agents
            if a.get("uazapi_base_url") and a.get("uazapi_token")
        ]

        _log(f"Encontrados {len(agents)} agentes com follow-up habilitado")

        if not agents:
            _log("Nenhum agente com follow-up habilitado encontrado")
            return {"status": "completed", "stats": total_stats, "message": "no_agents"}

        for agent in agents:
            agent_name = agent.get("name", "Unknown")
            agent_id = agent.get("id", "")
            _log(f"Processando agente: {agent_name} ({agent_id})")

            try:
                # force_mode=True ignora schedule (horario/dia)
                agent_stats = await _process_agent_follow_up(agent, force_mode=True)
                total_stats["sent"] += agent_stats.get("sent", 0)
                total_stats["skipped"] += agent_stats.get("skipped", 0)
                total_stats["errors"] += agent_stats.get("errors", 0)
                total_stats["agents_processed"] += 1
                _log(f"Agente {agent_name}: {agent_stats}")
            except Exception as e:
                _log_error(f"Erro ao processar agente {agent_name}: {e}")
                _log_error(traceback.format_exc())
                total_stats["errors"] += 1

        _log(
            f"=== Job finalizado: {total_stats['sent']} follow-ups enviados, "
            f"{total_stats['skipped']} pulados, {total_stats['errors']} erros ==="
        )

        return {"status": "completed", "stats": total_stats}

    except Exception as e:
        _log_error(f"Erro no processamento: {e}")
        _log_error(traceback.format_exc())
        return {"status": "error", "error": str(e)}

    finally:
        _is_running = False


# ============================================================================
# UTILITY: Reset follow-up counters when lead responds
# ============================================================================

async def reset_follow_up_on_lead_response(
    table_leads: str,
    remotejid: str,
    agent_id: Optional[str] = None,
) -> None:
    """
    Reseta contadores de follow-up quando o lead envia uma mensagem.

    Deve ser chamado no webhook do WhatsApp quando uma mensagem
    do lead (IsFromMe=false) e recebida.
    """
    supabase = get_supabase_service()
    try:
        now = datetime.utcnow().isoformat()

        # Resetar campos de follow-up no lead
        supabase.client.table(table_leads).update({
            "follow_up_count": 0,
            "follow_up_stage": 0,
            "last_lead_message_at": now,
            "updated_date": now,
        }).eq("remotejid", remotejid).execute()

        if agent_id:
            phone = remotejid.replace("@s.whatsapp.net", "").replace("@lid", "")

            # Marcar follow_up_notifications como respondidas
            try:
                supabase.client.table("follow_up_notifications").update({
                    "lead_responded": True,
                    "responded_at": now,
                }).eq("agent_id", agent_id).eq("lead_phone", phone).eq(
                    "lead_responded", False
                ).execute()
            except Exception as e:
                logger.warning(f"Erro ao atualizar follow_up_notifications: {e}")

            # Marcar follow_up_history como respondido
            try:
                last_fu = (
                    supabase.client.table("follow_up_history")
                    .select("id, sent_at")
                    .eq("remotejid", remotejid)
                    .eq("agent_id", agent_id)
                    .eq("lead_responded", False)
                    .order("sent_at", desc=True)
                    .limit(1)
                    .execute()
                )

                if last_fu.data:
                    fu_id = last_fu.data[0]["id"]
                    sent_at = _parse_iso_datetime(last_fu.data[0].get("sent_at"))
                    now_dt = datetime.utcnow()
                    if sent_at:
                        now_dt_utc = pytz.utc.localize(now_dt) if now_dt.tzinfo is None else now_dt
                        sent_at_utc = sent_at.astimezone(pytz.utc)
                        response_time = int((now_dt_utc - sent_at_utc).total_seconds() / 60)
                    else:
                        response_time = None

                    supabase.client.table("follow_up_history").update({
                        "lead_responded": True,
                        "responded_at": now,
                        "response_time_minutes": response_time,
                    }).eq("id", fu_id).execute()
            except Exception as e:
                logger.warning(f"Erro ao atualizar follow_up_history: {e}")

            # Limpar cooldown Redis do lead
            try:
                redis_client = await _get_redis_client()
                if redis_client:
                    lead_key = f"salvador:lead:{agent_id}:{remotejid}"
                    await redis_client.delete(lead_key)
            except Exception:
                pass

    except Exception as e:
        logger.error(f"Erro ao resetar follow-up para {remotejid}: {e}")
