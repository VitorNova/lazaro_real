"""
Context Detector - Deteccao e preparacao de contextos de conversa.

Este modulo contem funcoes para:
- Buscar prompts dinamicos por contexto (get_context_prompt)
- Detectar contexto especial nas mensagens (detect_conversation_context)
- Preparar system prompt com variaveis dinamicas (prepare_system_prompt)

Extraido de: app/webhooks/mensagens.py (Fase 2.2)
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

import pytz

logger = logging.getLogger(__name__)


# ============================================================================
# CONTEXT MAPPING - Mapeamento de contextos de disparo para prompts
# ============================================================================

CONTEXT_MAPPING = {
    "disparo_manutencao": "manutencao",
    "disparo_billing": "billing",
    "disparo_cobranca": "billing",
    "manutencao_preventiva": "manutencao",
}


# ============================================================================
# GET CONTEXT PROMPT - Busca prompt dinamico do agente
# ============================================================================

def get_context_prompt(context_prompts: Optional[Dict], context_type: str) -> Optional[str]:
    """
    Busca prompt dinamico do campo context_prompts do agente.

    O campo context_prompts e um JSONB no Supabase que armazena prompts
    por contexto (manutencao_preventiva, cobranca, etc). Isso permite
    editar prompts sem deploy e economiza tokens nas conversas normais.

    Args:
        context_prompts: Dict com prompts por contexto (do agent.context_prompts)
        context_type: Tipo de contexto (ex: 'manutencao_preventiva')

    Returns:
        Prompt string ou None se nao encontrado/inativo

    Estrutura esperada do context_prompts:
    {
        "manutencao_preventiva": {
            "prompt": "## CONTEXTO ESPECIAL...",
            "description": "Prompt para limpeza semestral",
            "active": true
        }
    }
    """
    print(f"[CONTEXT DEBUG] get_context_prompt() chamada com context_type='{context_type}'", flush=True)

    if not context_prompts:
        print(f"[CONTEXT DEBUG] context_prompts vazio ou None", flush=True)
        logger.info(f"[CONTEXT] context_prompts vazio ou None")
        return None

    # Tentar contexto original primeiro, depois o mapeado
    mapped_context = CONTEXT_MAPPING.get(context_type, context_type)
    if mapped_context != context_type:
        print(f"[CONTEXT DEBUG] Mapeando contexto '{context_type}' -> '{mapped_context}'", flush=True)

    context_config = context_prompts.get(mapped_context)
    if not context_config:
        print(f"[CONTEXT DEBUG] Contexto '{mapped_context}' (original: '{context_type}') NAO encontrado em context_prompts. Keys disponiveis: {list(context_prompts.keys())}", flush=True)
        logger.info(f"[CONTEXT] Contexto '{mapped_context}' nao encontrado em context_prompts")
        return None

    # Verificar se contexto esta ativo (default True para compatibilidade)
    # Verifica campo 'active' ou 'ativo' para compatibilidade
    is_active = context_config.get("active", context_config.get("ativo", True))
    if not is_active:
        print(f"[CONTEXT DEBUG] Contexto '{mapped_context}' esta INATIVO", flush=True)
        logger.info(f"[CONTEXT] Contexto '{mapped_context}' esta inativo")
        return None

    prompt = context_config.get("prompt")
    if prompt:
        print(f"[CONTEXT DEBUG] Prompt carregado para '{mapped_context}'! ({len(prompt)} chars)", flush=True)
        logger.info(f"[CONTEXT] Carregado prompt dinamico para '{mapped_context}' ({len(prompt)} chars)")

    return prompt


# ============================================================================
# DETECT CONVERSATION CONTEXT - Detecta contexto especial nas mensagens
# ============================================================================

def detect_conversation_context(
    conversation_history: dict,
    max_messages: int = 10,
    hours_window: int = 168
) -> Tuple[Optional[str], Optional[str]]:
    """
    Detecta contexto especial nas ultimas mensagens da conversa.

    O Job D-7 de manutencao adiciona `context: 'manutencao_preventiva'` nas mensagens.
    Esta funcao verifica se existe tal contexto dentro da janela de tempo.

    Args:
        conversation_history: Historico de mensagens (dict com 'messages')
        max_messages: Numero maximo de mensagens a verificar (default: 10)
        hours_window: Janela de tempo em horas (default: 168h = 7 dias)

    Returns:
        Tuple (context, ref_id) ou (None, None) se nao encontrar
    """
    print(f"[CONTEXT DEBUG] detect_conversation_context() chamada", flush=True)

    if not conversation_history:
        print(f"[CONTEXT DEBUG] conversation_history vazio ou None", flush=True)
        logger.info("[CONTEXT] conversation_history vazio ou None")
        return None, None

    messages = conversation_history.get("messages", [])
    if not messages:
        print(f"[CONTEXT DEBUG] Nenhuma mensagem no historico", flush=True)
        logger.info("[CONTEXT] Nenhuma mensagem no historico")
        return None, None

    # Verificar mensagens do FIM para o INICIO (mais recente primeiro)
    # Isso garante que se houver multiplos disparos (cobranca jan, cobranca fev),
    # pegamos o contexto MAIS RECENTE, nao o mais antigo.
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours_window)

    print(f"[CONTEXT DEBUG] Verificando {len(messages)} mensagens do FIM ao INICIO (janela de {hours_window}h)", flush=True)
    logger.info(f"[CONTEXT] Verificando {len(messages)} mensagens do FIM ao INICIO (janela de {hours_window}h)")

    # Iterar do fim para o inicio (reversed) - pega o contexto MAIS RECENTE
    for msg in reversed(messages):
        context = msg.get("context")
        if not context:
            continue

        # Verificar timestamp
        timestamp_str = msg.get("timestamp")
        if timestamp_str:
            try:
                # Parsear ISO timestamp
                msg_dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                if msg_dt.tzinfo is None:
                    msg_dt = msg_dt.replace(tzinfo=timezone.utc)

                if msg_dt >= cutoff:
                    # Pegar contract_id OU reference_id (cobranca usa reference_id)
                    ref_id = msg.get("contract_id") or msg.get("reference_id")
                    print(f"[CONTEXT DEBUG] ENCONTRADO context='{context}' ref_id='{ref_id}' (MAIS RECENTE)", flush=True)
                    logger.info(f"[CONTEXT] Detectado context='{context}' ref_id='{ref_id}' (mais recente, dentro de {hours_window}h)")
                    return context, ref_id
                else:
                    hours_ago = (now - msg_dt).total_seconds() / 3600
                    print(f"[CONTEXT DEBUG] Context '{context}' expirado ({hours_ago:.1f}h atras)", flush=True)
                    logger.info(f"[CONTEXT] Context '{context}' expirado ({hours_ago:.1f}h atras, limite={hours_window}h)")
            except Exception as e:
                logger.warning(f"[CONTEXT] Erro ao parsear timestamp '{timestamp_str}': {e}")
                # Se nao conseguir parsear, assume valido (fail-safe)
                ref_id = msg.get("contract_id") or msg.get("reference_id")
                print(f"[CONTEXT DEBUG] Usando context='{context}' ref_id='{ref_id}' (timestamp invalido)", flush=True)
                logger.info(f"[CONTEXT] Usando context='{context}' ref_id='{ref_id}' (timestamp invalido, assumindo valido)")
                return context, ref_id
        else:
            # Sem timestamp, assume valido
            ref_id = msg.get("contract_id") or msg.get("reference_id")
            print(f"[CONTEXT DEBUG] ENCONTRADO context='{context}' ref_id='{ref_id}' (sem timestamp)", flush=True)
            logger.info(f"[CONTEXT] Detectado context='{context}' ref_id='{ref_id}' (sem timestamp)")
            return context, ref_id

    print(f"[CONTEXT DEBUG] Nenhum context especial encontrado", flush=True)
    logger.info("[CONTEXT] Nenhum context especial encontrado nas mensagens recentes")
    return None, None


# ============================================================================
# PREPARE SYSTEM PROMPT - Substitui variaveis dinamicas no prompt
# ============================================================================

def prepare_system_prompt(system_prompt: str, timezone_str: str = "America/Cuiaba") -> str:
    """
    Substitui variaveis dinamicas no system prompt.

    Variaveis suportadas:
    - {data_hora_atual}: Data e hora atual no timezone especificado

    Args:
        system_prompt: Prompt original com variaveis
        timezone_str: Timezone para calcular data/hora (default: America/Cuiaba)

    Returns:
        Prompt com variaveis substituidas
    """
    try:
        tz = pytz.timezone(timezone_str)
    except Exception:
        tz = pytz.timezone("America/Cuiaba")

    now = datetime.now(tz)

    # Mapeamento manual de dias da semana e meses em portugues
    dias_semana = {
        0: "segunda-feira",
        1: "terca-feira",
        2: "quarta-feira",
        3: "quinta-feira",
        4: "sexta-feira",
        5: "sabado",
        6: "domingo"
    }

    meses = {
        1: "janeiro", 2: "fevereiro", 3: "marco", 4: "abril",
        5: "maio", 6: "junho", 7: "julho", 8: "agosto",
        9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro"
    }

    # Formato amigavel: "terca-feira, 28 de janeiro de 2026, 09:30"
    dia_semana = dias_semana.get(now.weekday(), now.strftime("%A"))
    mes = meses.get(now.month, now.strftime("%B"))
    data_hora_atual = f"{dia_semana}, {now.day} de {mes} de {now.year}, {now.strftime('%H:%M')}"

    # Substituir variaveis
    if "{data_hora_atual}" in system_prompt:
        system_prompt = system_prompt.replace("{data_hora_atual}", data_hora_atual)
        logger.debug(f"[PROMPT] Data/hora atual: {data_hora_atual} (timezone: {timezone_str})")

    return system_prompt
