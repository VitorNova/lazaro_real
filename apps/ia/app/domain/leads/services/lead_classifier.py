"""
Lead Classifier - Classificacao IA para decidir se envia follow-up.

Usa Gemini para analisar historico de conversa e decidir se o lead
deve receber follow-up ou nao.

Extraido de reengajar_leads.py (Fase 5.5).
"""

import json
import logging
from typing import Any, Dict, List, Tuple

import google.generativeai as genai

from app.services.supabase import get_supabase_service

logger = logging.getLogger(__name__)

LOG_PREFIX = "[Salvador]"


# ============================================================================
# LOG HELPERS
# ============================================================================

def _log(msg: str, data: Any = None) -> None:
    extra = f" | {data}" if data else ""
    logger.info(f"{LOG_PREFIX} {msg}{extra}")


def _log_warn(msg: str) -> None:
    logger.warning(f"{LOG_PREFIX} {msg}")


def _log_error(msg: str) -> None:
    logger.error(f"{LOG_PREFIX} {msg}")


# ============================================================================
# CONVERSATION HISTORY
# ============================================================================

async def load_conversation_history(
    agent: Dict[str, Any],
    remotejid: str,
) -> List[Dict[str, Any]]:
    """
    Carrega historico de conversa do lead (ultimas 20 mensagens).

    Args:
        agent: Dados do agente
        remotejid: ID do lead no WhatsApp

    Returns:
        Lista de mensagens do historico
    """
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


def build_conversation_summary(
    history: List[Dict[str, Any]],
    max_messages: int = 20
) -> str:
    """
    Constroi resumo textual do historico de conversa.

    Args:
        history: Lista de mensagens
        max_messages: Maximo de mensagens a incluir

    Returns:
        String com resumo formatado
    """
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
# CLASSIFIER PROMPT
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


# ============================================================================
# CLASSIFIER
# ============================================================================

async def classify_lead_for_follow_up(
    history: List[Dict[str, Any]],
    lead_name: str,
) -> Tuple[bool, str]:
    """
    Classifica se o lead deve receber follow-up.

    Args:
        history: Lista de mensagens do historico
        lead_name: Nome do lead para logs

    Returns:
        Tupla (deve_enviar: bool, motivo: str)
    """
    summary = build_conversation_summary(history)

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
