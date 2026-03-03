"""
Follow-Up Message Generator - Geracao de mensagens de follow-up via Gemini.

Gera mensagens personalizadas baseadas no historico de conversa.
Fallback para mensagens padrao se Gemini falhar.

Extraido de reengajar_leads.py (Fase 5.6).
"""

import logging
from typing import Any, Dict, List

import google.generativeai as genai

from .salvador_config import FALLBACK_MESSAGES
from .lead_classifier import build_conversation_summary

logger = logging.getLogger(__name__)

LOG_PREFIX = "[Salvador]"


# ============================================================================
# HELPERS
# ============================================================================

def _log(msg: str, data: Any = None) -> None:
    extra = f" | {data}" if data else ""
    logger.info(f"{LOG_PREFIX} {msg}{extra}")


def _log_warn(msg: str) -> None:
    logger.warning(f"{LOG_PREFIX} {msg}")


def _log_error(msg: str) -> None:
    logger.error(f"{LOG_PREFIX} {msg}")


def get_lead_first_name(lead: Dict[str, Any]) -> str:
    """
    Extrai primeiro nome do lead.

    Args:
        lead: Dados do lead

    Returns:
        Primeiro nome ou string vazia se nao tiver nome real
    """
    nome = (lead.get("nome") or "").strip()
    if not nome or nome.lower() in ("cliente", "desconhecido", "sem nome", "lead"):
        return ""
    return nome.split()[0]


# ============================================================================
# MESSAGE GENERATION
# ============================================================================

async def generate_follow_up_message(
    lead: Dict[str, Any],
    agent: Dict[str, Any],
    history: List[Dict[str, Any]],
    step_number: int,
    custom_prompt: str = "",
) -> str:
    """
    Gera mensagem de follow-up personalizada via Gemini.
    Fallback para mensagem padrao se Gemini falhar.

    Args:
        lead: Dados do lead
        agent: Dados do agente
        history: Historico de conversa
        step_number: Numero do follow-up (1, 2, 3...)
        custom_prompt: Prompt do salvador_config (tem prioridade)

    Returns:
        Mensagem gerada ou fallback
    """
    first_name = get_lead_first_name(lead)

    summary = build_conversation_summary(history)
    pipeline_step = lead.get("pipeline_step") or "novo"

    # Prioridade: prompt do salvador_config > system_prompt do agente > default
    system_prompt = custom_prompt or agent.get("system_prompt") or (
        "Voce e um assistente de vendas amigavel e profissional."
    )

    nome_info = f'NOME: {first_name}' if first_name else 'NOME: (sem nome - nao use nome nenhum na mensagem)'

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
