"""
Salvador Config - Configuracao e normalizacao do agente Salvador (follow-up).

Extraido de reengajar_leads.py (Fase 5.2).
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Tuple

import pytz


# ============================================================================
# CONSTANTES
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

def get_salvador_config(agent: Dict[str, Any]) -> Dict[str, Any]:
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


def is_within_schedule(
    config: Dict[str, Any],
    tz_str: str = "America/Sao_Paulo",
) -> Tuple[bool, str]:
    """
    Verifica se o momento atual esta dentro do schedule configurado.

    Args:
        config: Configuracao normalizada do Salvador
        tz_str: Timezone string (default: America/Sao_Paulo)

    Returns:
        Tupla (pode_rodar, motivo)
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
