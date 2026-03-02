"""
WhatsApp Webhook Handler - Processamento de mensagens do WhatsApp via UAZAPI.

Este modulo implementa:
- WhatsAppWebhookHandler: Classe para processar mensagens do webhook
- FastAPI Router com endpoints POST/GET para /webhook/whatsapp

Fluxo de processamento:
1. Webhook recebe mensagem do UAZAPI
2. Valida (nao grupo)
3. Se from_me: detecta human takeover (humano respondeu pelo celular → pausa IA)
4. Verifica comandos de controle (/p, /a, /r)
5. Verifica se bot esta pausado para o lead
6. Adiciona mensagem ao buffer Redis
7. Agenda processamento apos 14 segundos
8. Busca historico de conversa no Supabase
9. Envia para Gemini processar
10. Envia resposta via UAZAPI
11. Salva historico atualizado no Supabase
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import pytz
from typing import Any, Dict, List, Optional, TypedDict

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response

from app.config import settings
from app.services.ia_gemini import GeminiService, get_gemini_service
from app.services.redis import (
    BUFFER_DELAY_SECONDS,
    RedisService,
    get_redis_service,
)
from app.services.supabase import (
    SupabaseService,
    get_supabase_service,
    ConversationHistory,
)
from app.services.whatsapp_api import UazapiService, get_uazapi_service
from app.tools.cobranca import FUNCTION_DECLARATIONS, get_function_declarations

# Diana v2 - Prospecao ativa
from app.services.diana import get_diana_campaign_service

# Observer - Agente observador de conversas
from app.services.observer import analyze_conversation

# Leadbox - Verificacao de fila em tempo real + atribuicao automatica
from app.services.leadbox import get_current_queue, LeadboxService

# Configurar logging
logger = logging.getLogger(__name__)


# ============================================================================
# GET CONTEXT PROMPT - Busca prompt dinamico do campo context_prompts do agente
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

    # Mapeamento de contextos de disparo para prompts
    # O dispatch service usa 'disparo_X' mas os prompts estao em 'X'
    CONTEXT_MAPPING = {
        "disparo_manutencao": "manutencao",
        "disparo_billing": "billing",
        "disparo_cobranca": "billing",
        "manutencao_preventiva": "manutencao",
    }

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
) -> tuple:
    """
    Detecta contexto especial nas ultimas mensagens da conversa.

    O Job D-7 de manutencao adiciona `context: 'manutencao_preventiva'` nas mensagens.
    Esta funcao verifica se existe tal contexto dentro da janela de tempo.

    Args:
        conversation_history: Historico de mensagens (dict com 'messages')
        max_messages: Numero maximo de mensagens a verificar (default: 10)
        hours_window: Janela de tempo em horas (default: 72h = 3 dias)

    Returns:
        Tuple (context, contract_id) ou (None, None) se nao encontrar
    """
    # Print para debug imediato (aparece sempre)
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

    # Verificar mensagens do FIM para o INÍCIO (mais recente primeiro)
    # Isso garante que se houver múltiplos disparos (cobrança jan, cobrança fev),
    # pegamos o contexto MAIS RECENTE, não o mais antigo.
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours_window)

    print(f"[CONTEXT DEBUG] Verificando {len(messages)} mensagens do FIM ao INICIO (janela de {hours_window}h)", flush=True)
    logger.info(f"[CONTEXT] Verificando {len(messages)} mensagens do FIM ao INICIO (janela de {hours_window}h)")

    # Iterar do fim para o início (reversed) - pega o contexto MAIS RECENTE
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
                    # Pegar contract_id OU reference_id (cobrança usa reference_id)
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
# GET CONTRACT DATA FOR MAINTENANCE - Busca dados do contrato para manutencao
# ============================================================================

def get_contract_data_for_maintenance(supabase: SupabaseService, contract_id: str) -> Optional[Dict[str, Any]]:
    """
    Busca dados do contrato para contexto de manutencao preventiva.

    Quando o Job D-7 dispara a notificacao, ele salva o contract_id no conversation_history.
    Esta funcao busca os dados completos do contrato para injetar no prompt,
    evitando que a Ana peca dados que ela ja tem.

    Args:
        supabase: Instancia do SupabaseService
        contract_id: UUID do contrato em contract_details

    Returns:
        Dict com dados do contrato ou None se nao encontrar
        {
            "cliente_nome": str,
            "cliente_telefone": str,
            "equipamentos": List[Dict],  # [{marca, btus, patrimonio}, ...]
            "endereco_instalacao": str,
            "proxima_manutencao": str,  # YYYY-MM-DD
        }
    """
    print(f"[CONTRACT] Buscando dados do contrato {contract_id}", flush=True)

    if not contract_id:
        print(f"[CONTRACT] contract_id vazio", flush=True)
        return None

    try:
        # Buscar contrato com JOIN em asaas_clientes
        result = supabase.client.table("contract_details").select(
            "id, locatario_nome, locatario_telefone, equipamentos, endereco_instalacao, proxima_manutencao, customer_id"
        ).eq("id", contract_id).maybe_single().execute()

        if not result.data:
            print(f"[CONTRACT] Contrato {contract_id} nao encontrado", flush=True)
            logger.warning(f"[CONTRACT] Contrato {contract_id} nao encontrado")
            return None

        contract = result.data
        print(f"[CONTRACT] Contrato encontrado: {contract.get('locatario_nome')}", flush=True)

        # Dados basicos do contrato
        data = {
            "contract_id": contract.get("id"),
            "cliente_nome": contract.get("locatario_nome") or "Cliente",
            "cliente_telefone": contract.get("locatario_telefone"),
            "equipamentos": contract.get("equipamentos") or [],
            "endereco_instalacao": contract.get("endereco_instalacao"),
            "proxima_manutencao": str(contract.get("proxima_manutencao")) if contract.get("proxima_manutencao") else None,
        }

        # Se nao tem telefone no contrato, buscar em asaas_clientes
        if not data["cliente_telefone"] and contract.get("customer_id"):
            try:
                customer_result = supabase.client.table("asaas_clientes").select(
                    "phone, mobile_phone"
                ).eq("id", contract.get("customer_id")).maybe_single().execute()

                if customer_result.data:
                    data["cliente_telefone"] = (
                        customer_result.data.get("mobile_phone") or
                        customer_result.data.get("phone")
                    )
                    print(f"[CONTRACT] Telefone obtido de asaas_clientes: {data['cliente_telefone']}", flush=True)
            except Exception as e:
                logger.warning(f"[CONTRACT] Erro ao buscar telefone em asaas_clientes: {e}")

        logger.info(f"[CONTRACT] Dados carregados para contrato {contract_id}: {data['cliente_nome']}, {len(data['equipamentos'])} equipamento(s)")
        return data

    except Exception as e:
        print(f"[CONTRACT] Erro ao buscar contrato: {e}", flush=True)
        logger.error(f"[CONTRACT] Erro ao buscar contrato {contract_id}: {e}")
        return None


def build_maintenance_context_prompt(contract_data: Dict[str, Any]) -> str:
    """
    Constroi o prompt de contexto com os dados do contrato.

    Este prompt e injetado ALEM do prompt de manutencao do context_prompts,
    adicionando os dados especificos do contrato do cliente.

    Args:
        contract_data: Dict retornado por get_contract_data_for_maintenance()

    Returns:
        String com o prompt formatado
    """
    # Formatar equipamentos
    equipamentos_str = ""
    for i, equip in enumerate(contract_data.get("equipamentos", []), 1):
        marca = equip.get("marca", "N/I")
        btus = equip.get("btus", "N/I")
        patrimonio = equip.get("patrimonio", "")
        patrimonio_str = f" (patrimonio {patrimonio})" if patrimonio else ""
        equipamentos_str += f"  {i}. {marca} {btus} BTUs{patrimonio_str}\n"

    if not equipamentos_str:
        equipamentos_str = "  (nao informado)\n"

    # Formatar endereco
    endereco = contract_data.get("endereco_instalacao") or "(nao informado no contrato)"

    # Formatar data da manutencao
    prox_manut = contract_data.get("proxima_manutencao") or "(a definir)"

    # Criar string do equipamento principal para exemplos
    equip_principal = ""
    if contract_data.get("equipamentos"):
        eq = contract_data["equipamentos"][0]
        equip_principal = f"{eq.get('marca', 'seu ar')} {eq.get('btus', '')} BTUs".strip()
    else:
        equip_principal = "seu ar-condicionado"

    prompt = f"""
## DADOS DO CONTRATO (JA CARREGADOS - NAO PERGUNTE)

**Cliente:** {contract_data.get("cliente_nome", "Cliente")}
**Contract ID:** {contract_data.get("contract_id", "")}
**Equipamento(s):**
{equipamentos_str}
**Endereco de instalacao:** {endereco}
**Proxima manutencao prevista:** {prox_manut}

## INSTRUCOES IMPORTANTES

VOCE JA TEM TODAS AS INFORMACOES DO CONTRATO ACIMA.

### O QUE VOCE DEVE FAZER:

**SEMPRE MENCIONE O EQUIPAMENTO** nas suas respostas!

### O QUE VOCE NAO DEVE FAZER:

**NAO PECA** telefone, CPF, endereco ou dados do cliente - voce ja os tem.
**NAO PECA** marca, modelo ou BTUs do ar-condicionado - voce ja sabe.

### FLUXO PARA MANUTENCAO:

1. Confirme com o cliente qual equipamento esta com problema (se tiver mais de um)
2. Pergunte QUAL O PROBLEMA (pingando, nao gela, barulho, nao liga, etc)
3. Pergunte DIA e PERIODO preferido para a visita tecnica (manha ou tarde)
4. Apos coletar tudo, transfira para o departamento usando `transferir_departamento`

### IMPORTANTE:

- Voce so COLETA as informacoes. O agendamento real sera feito pela equipe.
- Se o cliente perguntar sobre cobrancas ou pagamento, use `consultar_cliente`.
- Sempre mencione o equipamento nas suas respostas.

### EXEMPLO DE RESPOSTA:

"Entendi, o seu {equip_principal} esta pingando. Vou passar para nossa equipe tecnica agendar a visita. Tem preferencia de dia e horario?"

Se o cliente mencionar DEFEITO, PROBLEMA ou CONSERTO (nao manutencao preventiva):
- Transfira para a Nathalia (setor tecnico) usando `transferir_departamento`
"""

    return prompt


# ============================================================================
# TIMEZONE MAPPING - Estados brasileiros
# ============================================================================

TIMEZONE_MAP = {
    # GMT-3 (Brasília) - Maioria dos estados
    "SP": "America/Sao_Paulo",
    "RJ": "America/Sao_Paulo",
    "MG": "America/Sao_Paulo",
    "PR": "America/Sao_Paulo",
    "SC": "America/Sao_Paulo",
    "RS": "America/Sao_Paulo",
    "ES": "America/Sao_Paulo",
    "BA": "America/Sao_Paulo",
    "SE": "America/Sao_Paulo",
    "AL": "America/Sao_Paulo",
    "PE": "America/Sao_Paulo",
    "PB": "America/Sao_Paulo",
    "RN": "America/Sao_Paulo",
    "CE": "America/Sao_Paulo",
    "PI": "America/Sao_Paulo",
    "MA": "America/Sao_Paulo",
    "PA": "America/Sao_Paulo",
    "AP": "America/Sao_Paulo",
    "TO": "America/Sao_Paulo",
    "GO": "America/Sao_Paulo",
    "DF": "America/Sao_Paulo",

    # GMT-4 (Manaus/Cuiabá)
    "MT": "America/Cuiaba",
    "MS": "America/Campo_Grande",
    "RO": "America/Porto_Velho",
    "AM": "America/Manaus",
    "RR": "America/Boa_Vista",

    # GMT-5 (Acre)
    "AC": "America/Rio_Branco",
}

DEFAULT_TIMEZONE = "America/Sao_Paulo"


# Mapeamento de timezone para descrição amigável
TIMEZONE_DESCRIPTIONS = {
    "America/Sao_Paulo": "GMT-3 (horário de Brasília)",
    "America/Cuiaba": "GMT-4 (horário de Cuiabá)",
    "America/Campo_Grande": "GMT-4 (horário de Campo Grande)",
    "America/Manaus": "GMT-4 (horário de Manaus)",
    "America/Porto_Velho": "GMT-4 (horário de Porto Velho)",
    "America/Boa_Vista": "GMT-4 (horário de Boa Vista)",
    "America/Rio_Branco": "GMT-5 (horário do Acre)",
}


# ============================================================================
# PREPARE SYSTEM PROMPT - Substitui variáveis dinâmicas
# ============================================================================

def prepare_system_prompt(system_prompt: str, timezone: str = "America/Cuiaba") -> str:
    """
    Substitui variáveis dinâmicas no system prompt.

    Variáveis suportadas:
    - {data_hora_atual}: Data e hora atual no timezone especificado

    Args:
        system_prompt: Prompt original com variáveis
        timezone: Timezone para calcular data/hora (default: America/Cuiaba)

    Returns:
        Prompt com variáveis substituídas
    """
    try:
        tz = pytz.timezone(timezone)
    except Exception:
        tz = pytz.timezone("America/Cuiaba")

    now = datetime.now(tz)

    # Mapeamento manual de dias da semana e meses em português
    dias_semana = {
        0: "segunda-feira",
        1: "terça-feira",
        2: "quarta-feira",
        3: "quinta-feira",
        4: "sexta-feira",
        5: "sábado",
        6: "domingo"
    }

    meses = {
        1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril",
        5: "maio", 6: "junho", 7: "julho", 8: "agosto",
        9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro"
    }

    # Formato amigável: "terça-feira, 28 de janeiro de 2026, 09:30"
    dia_semana = dias_semana.get(now.weekday(), now.strftime("%A"))
    mes = meses.get(now.month, now.strftime("%B"))
    data_hora_atual = f"{dia_semana}, {now.day} de {mes} de {now.year}, {now.strftime('%H:%M')}"

    # Substituir variáveis
    if "{data_hora_atual}" in system_prompt:
        system_prompt = system_prompt.replace("{data_hora_atual}", data_hora_atual)
        logger.debug(f"[PROMPT] Data/hora atual: {data_hora_atual} (timezone: {timezone})")

    return system_prompt


# ============================================================================
# TYPE DEFINITIONS
# ============================================================================

class ExtractedMessage(TypedDict, total=False):
    """Dados extraidos da mensagem do webhook."""
    phone: str
    remotejid: str
    text: str
    is_group: bool
    from_me: bool
    message_id: Optional[str]
    timestamp: str
    push_name: Optional[str]
    instance_id: Optional[str]
    token: Optional[str]  # Token da instancia UAZAPI
    media_type: Optional[str]  # audio, ptt, image, video, etc
    media_url: Optional[str]  # URL direta da midia (Leadbox envia diretamente)


class ProcessingContext(TypedDict):
    """Contexto para processamento de mensagens."""
    agent_id: str
    agent_name: str  # Nome do agente para assinatura de mensagens (ex: "Ana")
    remotejid: str
    phone: str
    table_leads: str
    table_messages: str
    system_prompt: str
    uazapi_token: Optional[str]  # Token da instancia UAZAPI do agente
    uazapi_base_url: Optional[str]  # URL base da instancia UAZAPI do agente
    handoff_triggers: Optional[Dict[str, Any]]  # Config do Leadbox para transferencia
    audio_message_id: Optional[str]  # ID da mensagem de audio para download
    image_message_id: Optional[str]  # ID da mensagem de imagem para download
    image_url: Optional[str]  # URL direta da imagem (Leadbox envia diretamente)
    context_prompts: Optional[Dict[str, Any]]  # Prompts dinamicos por contexto (RAG simplificado)


# ============================================================================
# WHATSAPP WEBHOOK HANDLER
# ============================================================================

class WhatsAppWebhookHandler:
    """
    Handler para processamento de mensagens do webhook WhatsApp.

    Responsabilidades:
    - Extrair dados das mensagens do webhook
    - Gerenciar buffer de mensagens com delay
    - Processar comandos de controle (/p, /a, /r)
    - Orquestrar fluxo completo de processamento
    """

    # Delay do buffer em segundos (14s para agrupar mensagens)
    buffer_delay: int = BUFFER_DELAY_SECONDS

    # Controle de tasks de processamento agendadas
    _scheduled_tasks: Dict[str, asyncio.Task] = {}
    _processing_keys: set = set()  # Keys em processamento ativo (passou do sleep)

    def __init__(
        self,
        redis_service: Optional[RedisService] = None,
        supabase_service: Optional[SupabaseService] = None,
        gemini_service: Optional[GeminiService] = None,
        uazapi_service: Optional[UazapiService] = None,
    ):
        """
        Inicializa o handler com os servicos necessarios.

        Args:
            redis_service: Servico Redis para buffer e locks
            supabase_service: Servico Supabase para dados
            gemini_service: Servico Gemini para IA
            uazapi_service: Servico UAZAPI para WhatsApp
        """
        self._redis = redis_service
        self._supabase = supabase_service
        self._gemini = gemini_service
        self._uazapi = uazapi_service

    async def _get_redis(self) -> RedisService:
        """Obtem instancia do RedisService (lazy loading)."""
        if self._redis is None:
            self._redis = await get_redis_service(settings.redis_url)
        return self._redis

    def _get_supabase(self) -> SupabaseService:
        """Obtem instancia do SupabaseService (lazy loading)."""
        if self._supabase is None:
            self._supabase = get_supabase_service()
        return self._supabase

    def _get_gemini(self) -> GeminiService:
        """Obtem instancia do GeminiService (lazy loading)."""
        if self._gemini is None:
            self._gemini = get_gemini_service()
        return self._gemini

    def _get_uazapi(self) -> UazapiService:
        """Obtem instancia do UazapiService (lazy loading)."""
        if self._uazapi is None:
            self._uazapi = get_uazapi_service()
        return self._uazapi

    # ========================================================================
    # MESSAGE EXTRACTION
    # ========================================================================

    def _extract_message_data(self, webhook_data: Dict[str, Any]) -> Optional[ExtractedMessage]:
        """
        Extrai dados relevantes da mensagem do webhook UAZAPI.

        Formato: EventType, message.chatid, message.text

        Args:
            webhook_data: Dados brutos do webhook

        Returns:
            ExtractedMessage com dados extraidos ou None se invalido
        """
        try:
            # ==================================================================
            # FORMATO UAZAPI (EventType: messages)
            # ==================================================================
            if webhook_data.get("EventType") == "messages" and webhook_data.get("message"):
                msg = webhook_data.get("message", {})

                # Ignorar mensagens enviadas pela API (evita loops)
                if msg.get("wasSentByApi", False):
                    logger.debug("Mensagem enviada pela API, ignorando")
                    return None

                # Extrair chatid (remoteJid)
                remotejid = msg.get("chatid", "")
                if not remotejid:
                    # Fallback: tentar sender_pn
                    remotejid = msg.get("sender_pn", "")

                if not remotejid:
                    logger.debug("Mensagem UAZAPI sem chatid")
                    return None

                # Verificar se e grupo
                chat = webhook_data.get("chat", {})
                is_group = msg.get("isGroup", False) or "@g.us" in remotejid or chat.get("wa_isGroup", False)

                # Verificar se e mensagem propria
                from_me = msg.get("fromMe", False)

                # Extrair telefone do remotejid
                phone = remotejid.replace("@s.whatsapp.net", "").replace("@lid", "").replace("@c.us", "")

                # Extrair texto - UAZAPI usa 'text' ou 'content'
                text = msg.get("text", "")
                content = msg.get("content")
                if not text and content:
                    if isinstance(content, str):
                        text = content
                    elif isinstance(content, dict):
                        # content pode ser dict com URL de midia
                        text = content.get("text", "") or ""

                # Detectar tipo de midia
                media_type = msg.get("mediaType") or msg.get("messageType", "")

                # Se for audio, marcar como tal (nao precisa de texto)
                if media_type in ["audio", "ptt", "AudioMessage"]:
                    text = "[AUDIO]"  # Placeholder, sera substituido pela transcricao

                # Se nao tem texto, verificar tipo de midia
                if not text:
                    if media_type:
                        text = f"[{media_type} recebido]"
                    else:
                        logger.debug(f"Mensagem UAZAPI sem texto de {remotejid}")
                        return None

                # Dados adicionais
                message_id = msg.get("messageid", "")
                timestamp = msg.get("messageTimestamp", datetime.utcnow().timestamp() * 1000)
                push_name = msg.get("senderName", "")

                # URL da midia (Leadbox envia diretamente, UAZAPI pode enviar em content)
                media_url = msg.get("mediaUrl", "")
                if not media_url and isinstance(content, dict):
                    media_url = content.get("url", "")

                # Instance ID - UAZAPI usa 'instanceName' no root
                instance_id = webhook_data.get("instanceName", "")

                # Token da instancia (pode ser usado para identificar agente)
                token = webhook_data.get("token", "")

                # Converter timestamp (UAZAPI envia em milissegundos)
                if isinstance(timestamp, (int, float)):
                    if timestamp > 9999999999:  # Se em milissegundos
                        timestamp = timestamp / 1000
                    timestamp = datetime.fromtimestamp(timestamp).isoformat()

                return ExtractedMessage(
                    phone=phone,
                    remotejid=remotejid,
                    text=text.strip(),
                    is_group=is_group,
                    from_me=from_me,
                    message_id=message_id,
                    timestamp=timestamp,
                    push_name=push_name,
                    instance_id=instance_id,
                    token=token,
                    media_type=media_type if media_type else None,
                    media_url=media_url if media_url else None,
                )

            # Formato não reconhecido
            logger.debug("Webhook não é formato UAZAPI, ignorando")
            return None

        except Exception as e:
            logger.error(f"Erro ao extrair dados da mensagem: {e}")
            return None

    # ========================================================================
    # CONTROL COMMANDS
    # ========================================================================

    async def _handle_control_command(
        self,
        phone: str,
        remotejid: str,
        command: str,
        agent_id: str,
        table_leads: str,
        table_messages: str,
    ) -> Optional[str]:
        """
        Processa comandos de controle (/p, /a, /r).

        Comandos:
        - /p ou /pausar: Pausa o bot para o lead
        - /a ou /ativar: Reativa o bot para o lead
        - /r ou /reset ou /reiniciar: Limpa historico de conversa

        Args:
            phone: Telefone do lead
            remotejid: RemoteJid completo
            command: Comando recebido
            agent_id: ID do agente
            table_leads: Nome da tabela de leads
            table_messages: Nome da tabela de mensagens

        Returns:
            Mensagem de resposta ou None se nao for comando
        """
        cmd = command.lower().strip()
        supabase = self._get_supabase()
        redis = await self._get_redis()

        # Comando PAUSAR
        if cmd in ["/p", "/pausar", "/pause"]:
            logger.info(f"Comando PAUSAR recebido de {phone}")

            # Pausar no Supabase
            supabase.set_lead_paused(table_leads, remotejid, paused=True, reason="Comando /p do usuario")

            # Pausar no Redis (sem TTL - permanente ate /a)
            await redis.pause_set(agent_id, phone)

            return "Bot pausado. Envie /a para reativar."

        # Comando ATIVAR
        if cmd in ["/a", "/ativar", "/activate"]:
            logger.info(f"Comando ATIVAR recebido de {phone}")

            # Reativar no Supabase (pausar_ia)
            supabase.set_lead_paused(table_leads, remotejid, paused=False)

            # Limpar Atendimento_Finalizado e restaurar responsavel para AI
            supabase.update_lead_by_remotejid(
                table_leads,
                remotejid,
                {"Atendimento_Finalizado": "false", "responsavel": "AI"},
            )

            # Reativar no Redis
            await redis.pause_clear(agent_id, phone)

            return "Bot reativado. Estou de volta!"

        # Comando RESET
        if cmd in ["/r", "/reset", "/reiniciar", "/restart"]:
            logger.info(f"Comando RESET completo recebido de {phone}")

            # 1. Limpar historico de conversa no Supabase
            supabase.clear_conversation_history(table_messages, remotejid)

            # 2. Limpar buffer e pause no Redis
            await redis.buffer_clear(agent_id, phone)
            await redis.pause_clear(agent_id, phone)

            # 3. Reativar no Supabase (pausar_ia)
            supabase.set_lead_paused(table_leads, remotejid, paused=False)

            # 4. Resetar lead completamente no Supabase
            supabase.update_lead_by_remotejid(
                table_leads,
                remotejid,
                {
                    "Atendimento_Finalizado": "false",
                    "responsavel": "AI",
                    "status": "open",
                    "paused_by": None,
                    "paused_at": None,
                    "resumed_at": None,
                    "transfer_reason": None,
                    "pipeline_step": "novo",
                    "ultimo_intent": None,
                },
            )

            return "Lead resetado. Podemos comecar uma nova conversa!"

        return None

    # ========================================================================
    # MESSAGE PROCESSING
    # ========================================================================

    async def _schedule_processing(
        self,
        agent_id: str,
        phone: str,
        remotejid: str,
        context: ProcessingContext,
    ) -> None:
        """
        Agenda processamento das mensagens apos o delay do buffer.

        Cancela task anterior SOMENTE se ainda estiver no sleep (aguardando buffer).
        Se a task ja estiver processando (Gemini, envio), NAO cancela para evitar
        perda de mensagens (race condition fix 03/02/2026).

        Args:
            agent_id: ID do agente
            phone: Telefone do lead
            remotejid: RemoteJid completo
            context: Contexto de processamento
        """
        task_key = f"{agent_id}:{phone}"

        # Cancelar task anterior SOMENTE se ainda estiver dormindo (no sleep)
        if task_key in self._scheduled_tasks:
            old_task = self._scheduled_tasks[task_key]
            if not old_task.done():
                if task_key in self._processing_keys:
                    # Task ja esta processando (passou do sleep), NAO cancelar
                    # A nova mensagem ja esta no buffer e sera processada no proximo ciclo
                    logger.debug(f"[DEBUG 3/6] Task para {phone} ja esta PROCESSANDO - nova msg ficara no buffer para proximo ciclo")
                else:
                    old_task.cancel()
                    logger.debug(f"[DEBUG 3/6] Task anterior CANCELADA para {phone} (ainda estava no sleep)")

        # Criar nova task com delay
        async def delayed_process():
            try:
                await asyncio.sleep(self.buffer_delay)
                # Marcar como processando ANTES de consumir o buffer
                # Isso impede que novas mensagens cancelem esta task
                self._processing_keys.add(task_key)
                await self._process_buffered_messages(
                    agent_id=agent_id,
                    phone=phone,
                    remotejid=remotejid,
                    context=context,
                )
            except asyncio.CancelledError:
                logger.debug(f"Task cancelada para {phone} (durante sleep)")
            except Exception as e:
                logger.error(f"Erro no processamento agendado: {e}")
            finally:
                # Remover flag de processamento
                self._processing_keys.discard(task_key)
                # So limpar da lista se esta task ainda for a referencia atual
                # (evita deletar referencia de uma task mais nova)
                current = asyncio.current_task()
                if self._scheduled_tasks.get(task_key) is current:
                    del self._scheduled_tasks[task_key]

        # Agendar nova task
        task = asyncio.create_task(delayed_process())
        self._scheduled_tasks[task_key] = task

        logger.debug(f"[DEBUG 3/6] PROCESSAMENTO AGENDADO para {phone} em {self.buffer_delay} segundos")

    async def _process_buffered_messages(
        self,
        agent_id: str,
        phone: str,
        remotejid: str,
        context: ProcessingContext,
    ) -> None:
        """
        Processa todas as mensagens acumuladas no buffer.

        Implementa:
        - Lock distribuido para evitar processamento duplicado
        - Leitura atomica do buffer
        - Envio de typing indicator
        - Processamento via Gemini
        - Envio de resposta via UAZAPI
        - Persistencia do historico

        Args:
            agent_id: ID do agente
            phone: Telefone do lead
            remotejid: RemoteJid completo
            context: Contexto de processamento
        """
        print(f"[PROCESS] Iniciando processamento para {phone} (agente: {agent_id[:8]})", flush=True)

        redis = await self._get_redis()
        supabase = self._get_supabase()
        gemini = self._get_gemini()

        # Criar instancia do UazapiService com o token do agente
        agent_uazapi_token = context.get("uazapi_token")
        agent_uazapi_base_url = context.get("uazapi_base_url")

        if agent_uazapi_token and agent_uazapi_base_url:
            logger.debug(f"[DEBUG 4/6] USANDO UAZAPI do agente: {agent_uazapi_base_url[:30]}...")
            uazapi = UazapiService(base_url=agent_uazapi_base_url, api_key=agent_uazapi_token)
        else:
            logger.debug(f"[DEBUG 4/6] USANDO UAZAPI global (fallback)")
            uazapi = self._get_uazapi()

        # Tentar adquirir lock
        lock_acquired = await redis.lock_acquire(agent_id, phone)
        if not lock_acquired:
            logger.debug(f"Lock nao adquirido para {phone}, processamento ja em andamento")
            return

        # =================================================================
        # HEARTBEAT: Task que renova o lock a cada 20s enquanto processa
        # Previne expiração do lock durante retry do Gemini ou processamento longo
        # =================================================================
        heartbeat_task: Optional[asyncio.Task] = None
        heartbeat_running = True

        async def lock_heartbeat():
            """Renova o lock a cada 20s enquanto o processamento está ativo."""
            HEARTBEAT_INTERVAL = 20  # Renova a cada 20s (TTL é 60s)
            while heartbeat_running:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                if heartbeat_running:  # Verificar novamente após sleep
                    try:
                        extended = await redis.lock_extend(agent_id, phone, ttl=60)
                        if extended:
                            logger.debug(f"[LOCK HEARTBEAT] Renovado para {phone}")
                        else:
                            logger.warning(f"[LOCK HEARTBEAT] Falha ao renovar para {phone} - lock expirou?")
                    except Exception as hb_err:
                        logger.warning(f"[LOCK HEARTBEAT] Erro: {hb_err}")

        heartbeat_task = asyncio.create_task(lock_heartbeat())
        logger.debug(f"[LOCK HEARTBEAT] Iniciado para {phone}")

        try:
            # ================================================================
            # VERIFICAR FILA DO LEADBOX APÓS DELAY (defesa em profundidade)
            # Re-busca lead do Supabase para pegar current_queue_id atualizado
            # ================================================================
            handoff = context.get("handoff_triggers") or {}
            QUEUE_IA = int(handoff.get("queue_ia", 537))

            # Construir set de todas as filas de IA (principal + dispatch departments)
            IA_QUEUES_LOCAL = {QUEUE_IA}
            dispatch_depts = handoff.get("dispatch_departments") or {}
            if dispatch_depts.get("billing"):
                try:
                    IA_QUEUES_LOCAL.add(int(dispatch_depts["billing"]["queueId"]))
                except (ValueError, TypeError, KeyError):
                    pass
            if dispatch_depts.get("manutencao"):
                try:
                    IA_QUEUES_LOCAL.add(int(dispatch_depts["manutencao"]["queueId"]))
                except (ValueError, TypeError, KeyError):
                    pass
            logger.debug(f"[LEADBOX] Filas de IA (pós-delay): {IA_QUEUES_LOCAL}")

            table_leads = context.get("table_leads", "")
            if table_leads:
                fresh_lead = supabase.get_lead_by_remotejid(table_leads, remotejid)
                if fresh_lead:
                    # Check 1: current_queue_id (banco local)
                    fresh_queue_raw = fresh_lead.get("current_queue_id")
                    if fresh_queue_raw:
                        try:
                            current_queue = int(fresh_queue_raw)
                        except (ValueError, TypeError):
                            current_queue = None
                        if current_queue is not None and current_queue not in IA_QUEUES_LOCAL:
                            logger.debug(f"[LEADBOX] Verificação pós-delay: lead {phone} na fila {current_queue} - IGNORANDO (não está em filas IA {IA_QUEUES_LOCAL})")
                            await redis.buffer_clear(agent_id, phone)
                            return
                        else:
                            logger.debug(f"[LEADBOX] Verificação pós-delay: lead {phone} na fila {current_queue} - OK, processando (filas IA: {IA_QUEUES_LOCAL})")
                    else:
                        logger.debug(f"[LEADBOX] Verificação pós-delay: lead {phone} sem current_queue_id no banco - prosseguindo para check em tempo real")

                    # ============================================================
                    # CHECK EM TEMPO REAL: consulta API do Leadbox diretamente
                    # Executado quando:
                    #   - current_queue_id está vazio no banco (webhook pode ter falhado)
                    #   - OU sempre que houver ticket_id disponível (confirma estado atual)
                    # Fail-open: se a API falhar, prossegue normalmente
                    # ============================================================
                    handoff_triggers = context.get("handoff_triggers") or {}
                    lb_api_url = handoff_triggers.get("api_url")
                    lb_api_token = handoff_triggers.get("api_token")
                    lb_type = handoff_triggers.get("type", "")

                    # Só consulta se for agente do tipo leadbox com credenciais configuradas
                    if lb_type == "leadbox" and lb_api_url and lb_api_token:
                        ticket_id_raw = fresh_lead.get("ticket_id")
                        ticket_id = int(ticket_id_raw) if ticket_id_raw else None

                        # Consulta quando: sem queue_id no banco (webhook falhou) OU tem ticket_id (confirma estado)
                        should_check = (not fresh_queue_raw) or (ticket_id is not None)
                        if should_check:
                            try:
                                print(f"[LEADBOX REALTIME CHECK] Consultando API para lead {phone} (ticket_id={ticket_id})", flush=True)
                                lb_ia_queue_id = handoff_triggers.get("ia_queue_id")
                                realtime_result = await get_current_queue(
                                    api_url=lb_api_url,
                                    api_token=lb_api_token,
                                    phone=phone,
                                    ticket_id=ticket_id,
                                    ia_queue_id=int(lb_ia_queue_id) if lb_ia_queue_id else None,
                                )
                                if realtime_result:
                                    realtime_queue = realtime_result.get("queue_id")
                                    if realtime_queue is not None:
                                        try:
                                            realtime_queue = int(realtime_queue)
                                        except (ValueError, TypeError):
                                            realtime_queue = None

                                    if realtime_queue is not None and realtime_queue not in IA_QUEUES_LOCAL:
                                        print(f"[LEADBOX REALTIME CHECK] Lead {phone} na fila {realtime_queue} - IGNORANDO (não está em filas IA {IA_QUEUES_LOCAL})", flush=True)
                                        logger.info(f"[LEADBOX REALTIME CHECK] Lead {phone} na fila {realtime_queue} - IGNORANDO (não está em filas IA {IA_QUEUES_LOCAL})")
                                        # Atualizar banco com dado real para próximas verificações
                                        try:
                                            update_fields = {"current_queue_id": str(realtime_queue)}
                                            if realtime_result.get("ticket_id"):
                                                update_fields["ticket_id"] = str(realtime_result["ticket_id"])
                                            if realtime_result.get("user_id"):
                                                update_fields["current_user_id"] = str(realtime_result["user_id"])
                                            supabase.update_lead_by_remotejid(table_leads, remotejid, update_fields)
                                            logger.debug(f"[LEADBOX REALTIME CHECK] Banco atualizado: queue={realtime_queue}")
                                        except Exception as update_err:
                                            logger.warning(f"[LEADBOX REALTIME CHECK] Erro ao atualizar banco: {update_err}")
                                        await redis.buffer_clear(agent_id, phone)
                                        return
                                    else:
                                        print(f"[LEADBOX REALTIME CHECK] Lead {phone} na fila {realtime_queue} - OK (está em filas IA {IA_QUEUES_LOCAL})", flush=True)
                                        logger.info(f"[LEADBOX REALTIME CHECK] Lead {phone} na fila {realtime_queue} - OK, processando (filas IA: {IA_QUEUES_LOCAL})")
                                        # Atualizar banco com dado real
                                        if realtime_queue is not None and not fresh_queue_raw:
                                            try:
                                                update_fields = {"current_queue_id": str(realtime_queue)}
                                                if realtime_result.get("ticket_id"):
                                                    update_fields["ticket_id"] = str(realtime_result["ticket_id"])
                                                supabase.update_lead_by_remotejid(table_leads, remotejid, update_fields)
                                                logger.debug(f"[LEADBOX REALTIME CHECK] Banco atualizado com fila IA: queue={realtime_queue}")
                                            except Exception as update_err:
                                                logger.warning(f"[LEADBOX REALTIME CHECK] Erro ao atualizar banco: {update_err}")
                                else:
                                    print(f"[LEADBOX REALTIME CHECK] Lead {phone} - API não retornou dados, prosseguindo (fail-open)", flush=True)
                                    logger.info(f"[LEADBOX REALTIME CHECK] Lead {phone} - API sem dados, fail-open")
                            except Exception as lb_err:
                                print(f"[LEADBOX REALTIME CHECK] Lead {phone} - Erro na API ({lb_err}), prosseguindo (fail-open)", flush=True)
                                logger.warning(f"[LEADBOX REALTIME CHECK] Lead {phone} - Erro ao consultar Leadbox: {lb_err} - prosseguindo")

                    # Check 2: Atendimento_Finalizado (defesa extra)
                    if fresh_lead.get("Atendimento_Finalizado") == "true":
                        logger.debug(f"[LEADBOX] Verificação pós-delay: lead {phone} com Atendimento_Finalizado=true - REGISTRANDO MÉTRICA E IGNORANDO")

                        # Registrar que lead mandou mensagem após pausa (conversa com humano)
                        current_count = fresh_lead.get("human_message_count") or 0
                        supabase.update_lead_by_remotejid(
                            table_leads,
                            remotejid,
                            {
                                "last_human_message_at": datetime.utcnow().isoformat(),
                                "human_message_count": current_count + 1,
                            }
                        )
                        logger.info(f"[HUMAN_METRIC] Lead {phone} enviou msg #{current_count + 1} após pausa da IA")

                        await redis.buffer_clear(agent_id, phone)
                        return
                else:
                    logger.debug(f"[LEADBOX] Verificação pós-delay: lead {phone} não encontrado no Supabase")

            # Verificar se ainda esta pausado (Redis)
            is_paused = await redis.pause_is_paused(agent_id, phone)
            if not is_paused and table_leads:
                # Também verificar no Supabase (Leadbox webhook só atualiza Supabase)
                is_paused = supabase.is_lead_paused(table_leads, remotejid)
            if is_paused:
                logger.info(f"Bot pausado para {phone}, ignorando mensagens")

                # Registrar métrica de mensagem durante pausa
                if table_leads:
                    lead_for_metric = supabase.get_lead_by_remotejid(table_leads, remotejid)
                    if lead_for_metric:
                        current_count = lead_for_metric.get("human_message_count") or 0
                        supabase.update_lead_by_remotejid(
                            table_leads,
                            remotejid,
                            {
                                "last_human_message_at": datetime.utcnow().isoformat(),
                                "human_message_count": current_count + 1,
                            }
                        )
                        logger.info(f"[HUMAN_METRIC] Lead {phone} enviou msg #{current_count + 1} durante pausa")

                await redis.buffer_clear(agent_id, phone)
                return

            # ================================================================
            # CHECK DIANA - Prospect de prospecao ativa
            # Se for prospect Diana, processa com IA da campanha e retorna
            # ================================================================
            try:
                diana_service = get_diana_campaign_service()
                # Peek no buffer para ver a mensagem (sem limpar)
                diana_messages = await redis.buffer_get_messages(agent_id, phone)
                if diana_messages:
                    diana_text = "\n".join(diana_messages)
                    diana_response = await diana_service.process_response(
                        agent_id=agent_id,
                        remotejid=remotejid,
                        message_text=diana_text,
                        uazapi_base_url=context.get("uazapi_base_url", ""),
                        uazapi_token=context.get("uazapi_token", ""),
                    )
                    if diana_response:
                        # E prospect Diana - limpar buffer e enviar resposta
                        await redis.buffer_clear(agent_id, phone)
                        logger.debug(f"[DIANA] Prospect encontrado: {phone} - enviando resposta")

                        # Criar instancia UAZAPI
                        if context.get("uazapi_token") and context.get("uazapi_base_url"):
                            diana_uazapi = UazapiService(
                                base_url=context.get("uazapi_base_url"),
                                api_key=context.get("uazapi_token"),
                            )
                        else:
                            diana_uazapi = self._get_uazapi()

                        # Enviar resposta
                        await diana_uazapi.send_text(phone, diana_response)
                        logger.info(f"[DIANA] Resposta enviada para prospect {phone}")
                        return  # Processamento Diana concluido
            except Exception as diana_error:
                # Se der erro no Diana, continua processamento normal
                logger.debug(f"[DIANA] Erro (nao critico, continuando fluxo normal): {diana_error}")

            # =================================================================
            # IMPORTANTE: NÃO limpar buffer antes de processar!
            # Só limpamos após sucesso do Gemini para não perder mensagens
            # =================================================================
            messages = await redis.buffer_get_messages(agent_id, phone)

            if not messages:
                logger.debug(f"[DEBUG 4/6] BUFFER VAZIO para {phone} - nada a processar")
                return

            # Flag para controlar se devemos limpar o buffer ao final
            should_clear_buffer = False

            # Concatenar mensagens do buffer
            combined_text = "\n".join(messages)
            logger.debug(f"[DEBUG 4/6] INICIANDO PROCESSAMENTO APOS BUFFER:")
            logger.debug(f"  -> Phone: {phone}")
            logger.debug(f"  -> Qtd mensagens no buffer: {len(messages)}")
            logger.debug(f"  -> Texto combinado: {combined_text[:150]}...")

            # Verificar se ha mensagem de audio para processar
            audio_data = None
            audio_message_id = context.get("audio_message_id")

            if "[AUDIO]" in combined_text and audio_message_id:
                logger.debug(f"[DEBUG 4/6] DETECTADO AUDIO - Baixando midia...")
                try:
                    media_result = await uazapi.download_media(
                        message_id=audio_message_id,
                        return_base64=True,
                        generate_mp3=True,
                    )

                    if media_result.get("success") and media_result.get("base64Data"):
                        audio_data = {
                            "base64": media_result["base64Data"],
                            "mimetype": media_result.get("mimetype", "audio/mp3"),
                        }
                        logger.debug(f"[DEBUG 4/6] AUDIO BAIXADO com sucesso! mimetype={audio_data['mimetype']}")
                        # Substitui placeholder por contexto
                        combined_text = combined_text.replace("[AUDIO]", "[Mensagem de voz do usuario]")
                    else:
                        logger.debug(f"[DEBUG 4/6] FALHA ao baixar audio: {media_result.get('error')}")
                        combined_text = combined_text.replace("[AUDIO]", "[Mensagem de voz recebida]")
                except Exception as e:
                    logger.debug(f"[DEBUG 4/6] ERRO ao baixar audio: {e}")
                    combined_text = combined_text.replace("[AUDIO]", "[Mensagem de voz recebida]")

            elif "[AUDIO]" in combined_text:
                # Audio detectado mas sem message_id para download
                logger.debug(f"[DEBUG 4/6] AUDIO detectado mas sem message_id para download")
                combined_text = combined_text.replace("[AUDIO]", "[Mensagem de voz recebida]")

            # Verificar se ha mensagem de imagem para processar
            # Aceita multiplas variantes de placeholder de imagem
            image_data = None
            image_message_id = context.get("image_message_id")
            image_url = context.get("image_url")  # URL direta (Leadbox)

            # Detectar qualquer variante de placeholder de imagem
            image_placeholders = [
                "[Imagem recebida]", "[image recebido]", "[imageMessage recebido]",
                "[document recebido]", "[documentMessage recebido]"
            ]
            has_image_placeholder = any(p in combined_text for p in image_placeholders)

            if has_image_placeholder:
                is_document = any("document" in p.lower() for p in image_placeholders if p in combined_text)
                media_label = "documento" if is_document else "imagem"
                logger.info(f"[MEDIA] Detectado {media_label} - url={image_url[:50] if image_url else None}, message_id={image_message_id}")

                # PRIORIDADE 1: Usar URL direta (Leadbox envia URL completa)
                if image_url:
                    try:
                        import httpx
                        async with httpx.AsyncClient(timeout=30.0) as client:
                            resp = await client.get(image_url)
                            if resp.status_code == 200:
                                image_bytes = resp.content
                                # Detectar mimetype do header ou da URL
                                content_type = resp.headers.get("content-type", "image/jpeg")
                                if ";" in content_type:
                                    content_type = content_type.split(";")[0].strip()

                                import base64
                                image_b64 = base64.b64encode(image_bytes).decode("utf-8")
                                image_data = {
                                    "base64": image_b64,
                                    "mimetype": content_type,
                                }
                                logger.info(f"[MEDIA] Baixada via URL direta! mimetype={content_type}, size={len(image_b64)} chars")
                                # Substituir placeholders
                                for placeholder in image_placeholders:
                                    replacement = "[Cliente enviou um documento - analisando...]" if "document" in placeholder.lower() else "[Cliente enviou uma imagem - analisando...]"
                                    combined_text = combined_text.replace(placeholder, replacement)
                            else:
                                logger.warning(f"[MEDIA] Falha ao baixar URL direta: status={resp.status_code}")
                    except Exception as e:
                        logger.error(f"[MEDIA] Erro ao baixar via URL direta: {e}")

                # PRIORIDADE 2: Usar UAZAPI download (se nao tem URL direta)
                elif image_message_id:
                    try:
                        media_result = await uazapi.download_media(
                            message_id=image_message_id,
                            return_base64=True,
                            generate_mp3=False,
                        )

                        if media_result.get("success") and media_result.get("base64Data"):
                            image_data = {
                                "base64": media_result["base64Data"],
                                "mimetype": media_result.get("mimetype", "image/jpeg"),
                            }
                            logger.info(f"[MEDIA] Baixada via UAZAPI! mimetype={image_data['mimetype']}, size={len(image_data['base64'])} chars")
                            # Substituir placeholders
                            for placeholder in image_placeholders:
                                replacement = "[Cliente enviou um documento - analisando...]" if "document" in placeholder.lower() else "[Cliente enviou uma imagem - analisando...]"
                                combined_text = combined_text.replace(placeholder, replacement)
                        else:
                            logger.warning(f"[MEDIA] Falha ao baixar via UAZAPI: {media_result.get('error')}")
                    except Exception as e:
                        logger.error(f"[MEDIA] Erro ao baixar via UAZAPI: {e}")
                else:
                    logger.warning(f"[MEDIA] Placeholder detectado mas sem URL nem message_id para download")

            # Enviar typing indicator
            logger.debug(f"[DEBUG 4/6] ENVIANDO TYPING para {phone}...")
            typing_result = await uazapi.send_typing(phone, duration=5000)
            logger.debug(f"[DEBUG 4/6] TYPING resultado: {typing_result}")

            # Buscar historico de conversa
            logger.debug(f"[DEBUG 4/6] BUSCANDO HISTORICO de conversa...")
            history = supabase.get_conversation_history(
                context["table_messages"],
                remotejid
            )
            logger.debug(f"[DEBUG 4/6] HISTORICO: {len(history.get('messages', [])) if history else 0} mensagens")

            # ================================================================
            # DETECTAR CONTEXTO ESPECIAL (manutencao preventiva)
            # Job D-7 adiciona context='manutencao_preventiva' nas mensagens
            # ================================================================
            print(f"[CONTEXT DEBUG] Iniciando deteccao de contexto para phone={phone}", flush=True)
            conversation_context, contract_id = detect_conversation_context(history)
            print(f"[CONTEXT DEBUG] Resultado: conversation_context='{conversation_context}' contract_id='{contract_id}'", flush=True)

            # Fallback: verificar lead_origin se context expirou ou histórico vazio
            if not conversation_context:
                table_leads = context.get("table_leads", "")
                if table_leads:
                    lead_for_context = supabase.get_lead_by_remotejid(table_leads, remotejid)
                    if lead_for_context:
                        lead_origin = lead_for_context.get("lead_origin")
                        print(f"[CONTEXT DEBUG] Fallback check: lead_origin='{lead_origin}'", flush=True)
                        # Mapear lead_origin para context
                        ORIGIN_TO_CONTEXT = {
                            "manutencao_preventiva": "manutencao_preventiva",
                            "disparo_cobranca": "disparo_billing",
                            "disparo_manutencao": "disparo_manutencao",
                        }
                        if lead_origin in ORIGIN_TO_CONTEXT:
                            conversation_context = ORIGIN_TO_CONTEXT[lead_origin]
                            print(f"[CONTEXT DEBUG] FALLBACK ATIVADO: lead_origin='{lead_origin}' -> context='{conversation_context}'", flush=True)
                            logger.info(f"[CONTEXT] Fallback para lead_origin='{lead_origin}' -> context='{conversation_context}' (phone={phone})")

            # Injetar prompt dinamico se houver contexto especial (RAG simplificado)
            # Prompts sao carregados do campo context_prompts do agente (JSONB no Supabase)
            effective_system_prompt = context["system_prompt"]
            print(f"[CONTEXT DEBUG] conversation_context final='{conversation_context}' context_prompts existe={bool(context.get('context_prompts'))}", flush=True)
            if conversation_context:
                context_prompt = get_context_prompt(context.get("context_prompts"), conversation_context)
                if context_prompt:
                    effective_system_prompt = context["system_prompt"] + "\n\n" + context_prompt
                    print(f"[PROMPT DEBUG] SUCESSO! Prompt injetado ({len(context_prompt)} chars)", flush=True)
                    logger.info(f"[PROMPT] Injetado contexto dinamico '{conversation_context}' para {phone} (contract_id={contract_id})")

                    # ================================================================
                    # REGISTRAR PRIMEIRA RESPOSTA DO CLIENTE (FUNIL)
                    # Atualiza cliente_respondeu_at e status para 'contacted'
                    # ================================================================
                    if contract_id and conversation_context == "manutencao_preventiva":
                        try:
                            cd_check = supabase.client.table("contract_details").select(
                                "id, cliente_respondeu_at"
                            ).eq("id", contract_id).single().execute()

                            if cd_check.data and cd_check.data.get("cliente_respondeu_at") is None:
                                supabase.client.table("contract_details").update({
                                    "cliente_respondeu_at": datetime.utcnow().isoformat(),
                                    "maintenance_status": "contacted",
                                }).eq("id", contract_id).execute()
                                print(f"[MANUT] Cliente respondeu - contract {contract_id} -> 'contacted'", flush=True)
                                logger.info(f"[MANUT] Cliente respondeu - contract {contract_id} atualizado para 'contacted'")
                        except Exception as e:
                            logger.warning(f"[MANUT] Erro ao registrar resposta: {e}")

                    # ================================================================
                    # BUSCAR DADOS DO CONTRATO SE TEMOS contract_id
                    # Isso evita que a Ana peca dados que ela ja tem
                    # ================================================================
                    if contract_id and conversation_context == "manutencao_preventiva":
                        print(f"[CONTRACT DEBUG] Buscando dados do contrato {contract_id} para injetar no prompt", flush=True)
                        contract_data = get_contract_data_for_maintenance(supabase, contract_id)
                        if contract_data:
                            contract_prompt = build_maintenance_context_prompt(contract_data)
                            effective_system_prompt = effective_system_prompt + "\n\n" + contract_prompt
                            print(f"[CONTRACT DEBUG] Dados do contrato injetados! Cliente: {contract_data.get('cliente_nome')}", flush=True)
                            logger.info(f"[CONTRACT] Dados do contrato {contract_id} injetados para {phone}: {contract_data.get('cliente_nome')}, {len(contract_data.get('equipamentos', []))} equipamento(s)")
                        else:
                            print(f"[CONTRACT DEBUG] Nao foi possivel buscar dados do contrato {contract_id}", flush=True)
                            logger.warning(f"[CONTRACT] Falha ao buscar dados do contrato {contract_id} para {phone}")
                else:
                    print(f"[PROMPT DEBUG] FALHA! get_context_prompt retornou None", flush=True)

            # ================================================================
            # INJETAR CONTEXTO DE ATENDIMENTOS ANTERIORES
            # Se o cliente já teve mais de 1 atendimento, informar a IA
            # ================================================================
            total_atendimentos = context.get("total_atendimentos", 1)
            lead_nome = context.get("lead_nome", "")
            if total_atendimentos > 1:
                atendimentos_prompt = f"""
## HISTÓRICO DO CLIENTE
Este cliente ({lead_nome or 'sem nome registrado'}) já teve {total_atendimentos - 1} atendimento(s) anterior(es) com você.
Considere que ele já conhece o processo e pode estar retornando para acompanhamento ou nova demanda.
"""
                effective_system_prompt = effective_system_prompt + "\n" + atendimentos_prompt
                logger.debug(f"[SESSION] Contexto de {total_atendimentos} atendimentos injetado para {phone}")

            # Atualizar context com o prompt efetivo
            context["system_prompt"] = effective_system_prompt

            # Preparar mensagens para o Gemini
            gemini_messages = self._prepare_gemini_messages(history, combined_text)
            logger.debug(f"[DEBUG 4/6] MENSAGENS PREPARADAS: {len(gemini_messages)} mensagens para Gemini")

            # Verificar se agente tem Google Calendar configurado
            google_creds = supabase.get_agent_google_credentials(context["agent_id"])
            has_calendar = bool(google_creds and google_creds.get("refresh_token"))

            # Obter declarations filtradas (sem calendar tools se agente nao tem calendar)
            function_declarations = get_function_declarations(has_calendar)

            # SEMPRE inicializar com as tools corretas para este agente
            # (diferentes agentes podem ter diferentes configs de calendar)
            print(f"[GEMINI] Inicializando com {len(function_declarations)} tools (calendar={has_calendar})", flush=True)
            gemini.initialize(
                function_declarations=function_declarations,
                system_instruction=context["system_prompt"],
            )
            logger.debug(f"[DEBUG 5/6] GEMINI INICIALIZADO com {len(function_declarations)} tools")

            # SEMPRE registrar handlers com contexto atual (para ter acesso a phone, handoff_triggers, etc)
            handlers = self._create_function_handlers(context)
            gemini.register_tool_handlers(handlers)
            logger.debug(f"[DEBUG 5/6] HANDLERS REGISTRADOS com contexto do agente")

            # Enviar para o Gemini
            logger.debug(f"[DEBUG 5/6] ENVIANDO PARA GEMINI...")
            logger.debug(f"[DEBUG 5/6] System prompt: {context['system_prompt'][:100]}...")
            logger.debug(f"[DEBUG 5/6] Audio data presente: {bool(audio_data)}, Image data presente: {bool(image_data)}")
            response = await gemini.send_message(
                messages=gemini_messages,
                system_prompt=context["system_prompt"],
                audio_data=audio_data,
                image_data=image_data,
            )

            # =================================================================
            # VERIFICAR SE GEMINI RETORNOU ERRO (após retry exausto)
            # Se houve erro, NÃO limpar buffer e enviar fallback
            # =================================================================
            if response.get("error"):
                logger.error(
                    f"[GEMINI ERROR] Falha após {response.get('attempts', '?')} tentativas para {phone}",
                    extra={
                        "phone": phone,
                        "agent_id": agent_id[:8],
                        "error_type": response.get("error_type"),
                        "error_message": response.get("error_message", "")[:200],
                        "attempts": response.get("attempts"),
                    },
                )

                # IMPORTANTE: NÃO limpar buffer - mensagens preservadas para retry futuro
                logger.info(f"[GEMINI ERROR] Buffer PRESERVADO para {phone} ({len(messages)} mensagens)")

                # Enviar mensagem de fallback para o cliente
                fallback_msg = "Desculpe, estou com uma dificuldade técnica momentânea. Um momento por favor, já volto a te responder! 🙏"
                try:
                    await uazapi.send_text(phone, fallback_msg)
                    logger.info(f"[GEMINI ERROR] Fallback enviado para {phone}")
                except Exception as fallback_err:
                    logger.warning(f"[GEMINI ERROR] Falha ao enviar fallback: {fallback_err}")

                # Retorna sem limpar buffer - mensagens serão reprocessadas na próxima tentativa
                return

            # Gemini respondeu com sucesso - podemos limpar o buffer
            should_clear_buffer = True

            # Extrair resposta de texto
            response_text = response.get("text", "")
            logger.debug(f"[DEBUG 5/6] RESPOSTA DO GEMINI ({len(response_text)} chars): {response_text[:200] if response_text else 'VAZIA'}...")

            if not response_text:
                logger.warning(f"Gemini retornou resposta vazia para {phone}")
                response_text = "Desculpe, nao consegui processar sua mensagem. Pode repetir?"

            # Enviar resposta com quebra natural (simula digitação humana)
            # Cada chunk recebe assinatura do agente (ex: "Ana:\n<mensagem>")
            agent_name = context.get("agent_name", "Assistente")
            logger.debug(f"[DEBUG 6/6] ENVIANDO RESPOSTA via UAZAPI (ai_response)...")
            logger.debug(f"[DEBUG 6/6] UAZAPI URL: {uazapi.base_url}")
            logger.debug(f"[DEBUG 6/6] Telefone: {phone}, Agente: {agent_name}")
            send_result = await uazapi.send_ai_response(phone, response_text, agent_name, delay=2.0)

            logger.debug(
                f"[DEBUG 6/6] {send_result['success_count']}/{send_result['total_chunks']} "
                f"chunks enviados com sucesso"
            )

            # ================================================================
            # VERIFICAR SE ENVIO FALHOU - NÃO salvar histórico inconsistente
            # ================================================================
            if not send_result["all_success"]:
                logger.error(
                    f"[UAZAPI SEND FAIL] phone={phone} "
                    f"chunks_ok={send_result['success_count']}/{send_result['total_chunks']} "
                    f"erro={send_result['first_error']}"
                )

                # Salvar mensagem na fila de retry para tentar depois
                await self._queue_failed_send(
                    redis=redis,
                    agent_id=agent_id,
                    phone=phone,
                    response_text=response_text,
                    error=send_result["first_error"],
                )

                # NÃO salvar histórico - resposta não chegou ao cliente
                # NÃO limpar buffer - manter mensagem do usuário para reprocessar
                should_clear_buffer = False
                logger.warning(
                    f"[HISTÓRICO] NÃO salvo para {phone} - resposta não foi entregue ao cliente. "
                    f"Mensagem salva na fila de retry."
                )
                return  # Sai sem salvar histórico

            # ================================================================
            # SUCESSO: Salvar historico atualizado
            # ================================================================
            self._save_conversation_history(
                supabase=supabase,
                table_messages=context["table_messages"],
                remotejid=remotejid,
                user_message=combined_text,
                assistant_message=response_text,
                history=history,
                tool_interactions=response.get("tool_interactions", []),
            )

            # Atualizar lead
            supabase.update_lead_by_remotejid(
                context["table_leads"],
                remotejid,
                {"ultimo_intent": combined_text[:200]}
            )

            # Observer: analisar conversa e extrair insights
            try:
                # Extrair tools usadas da resposta do Gemini
                tools_used = [fc.get("name") for fc in response.get("function_calls", [])]

                # Buscar queue_ia do contexto do agente
                handoff_triggers = context.get("handoff_triggers") or {}
                observer_queue_ia = handoff_triggers.get("queue_ia")

                # Buscar lead para obter ID
                lead = supabase.get_lead_by_remotejid(context["table_leads"], remotejid)
                if lead and lead.get("id"):
                    await analyze_conversation(
                        table_leads=context["table_leads"],
                        table_messages=context["table_messages"],
                        lead_id=lead["id"],
                        remotejid=remotejid,
                        tools_used=tools_used,
                        agent_id=context.get("agent_id"),
                        queue_ia=observer_queue_ia,
                    )
            except Exception as obs_error:
                # Observer e opcional, nao deve falhar o fluxo principal
                logger.warning(f"[Observer] Erro ao analisar conversa: {obs_error}")

            logger.info(f"Processamento concluido para {phone}")

            # =================================================================
            # SUCESSO: Limpar buffer após processamento completo
            # =================================================================
            if should_clear_buffer:
                await redis.buffer_clear(agent_id, phone)
                logger.debug(f"[BUFFER] Limpo após sucesso para {phone}")

        except Exception as e:
            logger.error(f"Erro ao processar mensagens de {phone}: {e}", exc_info=True)

            # =================================================================
            # ERRO INESPERADO: NÃO limpar buffer para preservar mensagens
            # =================================================================
            logger.warning(f"[BUFFER] PRESERVADO após erro inesperado para {phone}")

            # Tentar enviar mensagem de erro
            try:
                await uazapi.send_text(
                    phone,
                    "Desculpe, estou com uma dificuldade técnica. Um momento por favor! 🙏"
                )
            except Exception:
                pass

        finally:
            # =================================================================
            # CLEANUP: Parar heartbeat e liberar lock
            # =================================================================
            # 1. Parar o heartbeat
            heartbeat_running = False
            if heartbeat_task and not heartbeat_task.done():
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
                logger.debug(f"[LOCK HEARTBEAT] Cancelado para {phone}")

            # 2. Liberar lock explicitamente
            released = await redis.lock_release(agent_id, phone)
            if released:
                logger.debug(f"[LOCK] Liberado explicitamente para {phone}")
            else:
                logger.warning(f"[LOCK] Já havia expirado para {phone} (não encontrado para liberar)")

    def _prepare_gemini_messages(
        self,
        history: Optional[ConversationHistory],
        new_message: str,
    ) -> List[Dict[str, Any]]:
        """
        Prepara lista de mensagens para enviar ao Gemini.

        Args:
            history: Historico de conversa existente
            new_message: Nova mensagem do usuario

        Returns:
            Lista de mensagens formatadas para o Gemini
        """
        messages = []

        # Adicionar historico existente (limitado)
        if history and history.get("messages"):
            existing = history["messages"]
            # Limitar a ultimas N mensagens para contexto
            max_history = settings.max_conversation_history
            limited = existing[-max_history:] if len(existing) > max_history else existing

            for msg in limited:
                messages.append({
                    "role": msg.get("role", "user"),
                    "parts": msg.get("parts", [{"text": ""}]),
                })

        # Adicionar nova mensagem
        messages.append({
            "role": "user",
            "parts": [{"text": new_message}],
        })

        return messages

    def _save_conversation_history(
        self,
        supabase: SupabaseService,
        table_messages: str,
        remotejid: str,
        user_message: str,
        assistant_message: str,
        history: Optional[ConversationHistory],
        tool_interactions: Optional[List[Dict]] = None,
    ) -> None:
        """
        Salva o historico de conversa atualizado.

        Args:
            supabase: Servico Supabase
            table_messages: Nome da tabela de mensagens
            remotejid: RemoteJid do lead
            user_message: Mensagem do usuario
            assistant_message: Resposta do assistente
            history: Historico existente
            tool_interactions: Lista de function_call + function_response (opcional)
        """
        now = datetime.utcnow().isoformat()

        # Inicializar ou usar historico existente
        if history is None:
            history = {"messages": []}

        # Adicionar mensagem do usuario
        history["messages"].append({
            "role": "user",
            "parts": [{"text": user_message}],
            "timestamp": now,
        })

        # Adicionar blocos de tool interaction (se houver)
        if tool_interactions:
            for ti in tool_interactions:
                # Function call do model
                history["messages"].append({
                    "role": "model",
                    "parts": [{"function_call": ti["function_call"]}],
                    "timestamp": now,
                })
                # Function response
                history["messages"].append({
                    "role": "function",
                    "parts": [{"function_response": ti["function_response"]}],
                    "timestamp": now,
                })

        # Adicionar resposta do modelo (texto final)
        history["messages"].append({
            "role": "model",
            "parts": [{"text": assistant_message}],
            "timestamp": now,
        })

        # Salvar no Supabase
        # Esta funcao salva tanto a mensagem do usuario quanto a do modelo.
        # Passamos last_message_role="model" para atualizar Msg_model,
        # e set_user_timestamp=True para atualizar Msg_user tambem.
        supabase.upsert_conversation_history(
            table_messages,
            remotejid,
            history,
            last_message_role="model",
            set_user_timestamp=False,
        )

    async def _queue_failed_send(
        self,
        redis: RedisService,
        agent_id: str,
        phone: str,
        response_text: str,
        error: Optional[str],
    ) -> None:
        """
        Salva mensagem que falhou ao enviar na fila de retry do Redis.

        A mensagem será reprocessada no startup ou via task periódica.

        Args:
            redis: Servico Redis
            agent_id: ID do agente
            phone: Telefone do destinatario
            response_text: Texto da resposta que não foi enviada
            error: Erro que ocorreu no envio
        """
        import json
        from datetime import datetime

        key = f"failed_send:{agent_id}:{phone}"
        now = datetime.utcnow().isoformat()

        # Verificar se já existe uma mensagem pendente para este lead
        existing = await redis.cache_get(key)

        if existing and isinstance(existing, dict):
            # Já existe mensagem pendente - concatenar (não perder contexto)
            attempts = existing.get("attempts", 0) + 1
            response_text = f"{existing.get('text', '')}\n\n---\n\n{response_text}"
            logger.info(
                f"[UAZAPI RETRY QUEUE] Mensagem CONCATENADA para {phone}. "
                f"Total de tentativas acumuladas: {attempts}"
            )
        else:
            attempts = 1

        payload = {
            "text": response_text,
            "timestamp": now,
            "attempts": attempts,
            "last_error": error,
            "agent_id": agent_id,
        }

        # TTL de 24 horas - se não conseguir reenviar em 24h, desiste
        await redis.cache_set(key, payload, ttl=86400)

        logger.info(
            f"[UAZAPI RETRY QUEUE] Mensagem salva para retry posterior. "
            f"phone={phone} agent={agent_id} attempts={attempts} erro={error}"
        )

    def _split_response(
        self,
        text: str,
        max_length: int = 4000,
    ) -> List[str]:
        """
        Divide resposta longa em partes menores.

        Tenta dividir em quebras de paragrafo ou sentencas.

        Args:
            text: Texto para dividir
            max_length: Tamanho maximo de cada parte

        Returns:
            Lista de partes do texto
        """
        if len(text) <= max_length:
            return [text]

        parts = []
        remaining = text

        while remaining:
            if len(remaining) <= max_length:
                parts.append(remaining)
                break

            # Tentar encontrar ponto de quebra
            chunk = remaining[:max_length]

            # Procurar por quebra de paragrafo
            break_point = chunk.rfind("\n\n")
            if break_point == -1:
                # Procurar por quebra de linha
                break_point = chunk.rfind("\n")
            if break_point == -1:
                # Procurar por ponto final
                break_point = chunk.rfind(". ")
            if break_point == -1:
                # Procurar por espaco
                break_point = chunk.rfind(" ")
            if break_point == -1:
                # Forcar quebra no limite
                break_point = max_length

            parts.append(remaining[:break_point + 1].strip())
            remaining = remaining[break_point + 1:].strip()

        return parts

    def _create_function_handlers(
        self,
        context: ProcessingContext,
    ) -> Dict[str, Any]:
        """
        Cria dicionario de handlers para as tools.

        Args:
            context: Contexto de processamento

        Returns:
            Dicionario com nome -> handler
        """
        from app.services.leadbox import LeadboxService, resolve_department
        from app.services.agenda import GoogleCalendarOAuth, GoogleCalendarOAuthError, create_google_calendar_oauth
        from app.config import settings

        supabase = self._get_supabase()

        # ====================================================================
        # HELPER: BUSCAR TIMEZONE DO LEAD
        # ====================================================================
        def get_lead_timezone() -> str:
            """Busca o timezone salvo do lead ou retorna o padrão."""
            try:
                remotejid = context.get("remotejid")
                table_leads = context.get("table_leads")
                lead = supabase.get_lead_by_remotejid(table_leads, remotejid)

                if lead and lead.get("timezone"):
                    return lead["timezone"]

                return DEFAULT_TIMEZONE
            except Exception as e:
                logger.warning(f"[TIMEZONE] Erro ao buscar timezone do lead: {e}")
                return DEFAULT_TIMEZONE

        # ====================================================================
        # HANDLER: CONSULTA AGENDA (GOOGLE CALENDAR OAUTH2)
        # ====================================================================
        async def consulta_agenda_handler(
            date: str = None,
            duration: int = 30,
            days_ahead: int = 5,
            lead_city: str = None,
            **kwargs
        ):
            """
            Consulta horarios disponiveis na agenda do agente.

            Usa OAuth2 com refresh_token armazenado no Supabase.
            """
            logger.debug(f"[CALENDAR] ========== CONSULTA AGENDA ==========")
            logger.debug(f"[CALENDAR] date={date}, duration={duration}, days_ahead={days_ahead}")

            try:
                # Buscar credenciais Google do agente
                agent_id = context.get("agent_id")
                google_creds = supabase.get_agent_google_credentials(agent_id)

                if not google_creds:
                    logger.warning(f"[Calendar] Google Calendar nao configurado para agente {agent_id}")
                    return {
                        "sucesso": False,
                        "mensagem": "Google Calendar nao esta configurado para este agente. Por favor, conecte sua conta Google nas configuracoes."
                    }

                refresh_token = google_creds.get("refresh_token")
                if not refresh_token:
                    return {
                        "sucesso": False,
                        "mensagem": "Credenciais Google incompletas. Por favor, reconecte sua conta Google."
                    }

                # Verificar se temos client_id e client_secret
                client_id = settings.google_client_id
                client_secret = settings.google_client_secret

                if not client_id or not client_secret:
                    logger.error("[Calendar] GOOGLE_CLIENT_ID ou GOOGLE_CLIENT_SECRET nao configurado")
                    return {
                        "sucesso": False,
                        "mensagem": "Configuracao do servidor incompleta para Google Calendar."
                    }

                # Buscar timezone do lead (ou usar padrão)
                lead_timezone = get_lead_timezone()
                logger.debug(f"[CALENDAR] Usando timezone do lead: {lead_timezone}")

                # Criar cliente OAuth2
                calendar_id = google_creds.get("calendar_id", "primary")
                calendar = create_google_calendar_oauth(
                    client_id=client_id,
                    client_secret=client_secret,
                    refresh_token=refresh_token,
                    calendar_id=calendar_id,
                    timezone=lead_timezone
                )

                # Configuracoes de horario de trabalho (podem vir do agente no futuro)
                work_hours_start = 9
                work_hours_end = 18

                if date:
                    # Buscar disponibilidade para data especifica
                    slots = calendar.get_availability(
                        date=date,
                        work_hours_start=work_hours_start,
                        work_hours_end=work_hours_end,
                        slot_duration=duration,
                        timezone=lead_timezone
                    )

                    if not slots:
                        return {
                            "sucesso": True,
                            "horarios_disponiveis": [],
                            "mensagem": f"Nao ha horarios disponiveis em {date} com duracao de {duration} minutos."
                        }

                    # Formatar horarios
                    horarios_formatados = [
                        {
                            "data": date,
                            "horario": slot["time"],
                            "inicio": slot["start"],
                            "fim": slot["end"]
                        }
                        for slot in slots
                    ]

                    return {
                        "sucesso": True,
                        "horarios_disponiveis": horarios_formatados,
                        "total": len(horarios_formatados),
                        "mensagem": f"Encontrados {len(horarios_formatados)} horarios disponiveis em {date}."
                    }

                else:
                    # Buscar disponibilidade para proximos dias
                    availability = calendar.get_multiple_days_availability(
                        days_ahead=days_ahead,
                        work_hours_start=work_hours_start,
                        work_hours_end=work_hours_end,
                        slot_duration=duration,
                        timezone=lead_timezone
                    )

                    if not availability:
                        return {
                            "sucesso": True,
                            "horarios_disponiveis": {},
                            "mensagem": f"Nao ha horarios disponiveis nos proximos {days_ahead} dias."
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
                        "mensagem": f"Encontrados {total_slots} horarios disponiveis nos proximos {len(availability)} dias."
                    }

            except GoogleCalendarOAuthError as e:
                logger.error(f"[Calendar] Erro OAuth: {e}")
                return {
                    "sucesso": False,
                    "mensagem": f"Erro ao acessar Google Calendar: {str(e)}"
                }
            except Exception as e:
                logger.error(f"[Calendar] Erro ao consultar agenda: {e}", exc_info=True)
                return {
                    "sucesso": False,
                    "mensagem": f"Erro ao consultar agenda: {str(e)}"
                }

        # ====================================================================
        # HANDLER: AGENDAR (CRIAR EVENTO)
        # ====================================================================
        async def agendar_handler(
            date: str,
            time: str,
            duration: int = 30,
            title: str = None,
            description: str = None,
            **kwargs
        ):
            """
            Cria um agendamento no Google Calendar do agente.
            Gera automaticamente um link do Google Meet.
            """
            logger.debug(f"[CALENDAR] ========== AGENDAR ==========")
            logger.debug(f"[CALENDAR] date={date}, time={time}, duration={duration}")

            try:
                # Buscar credenciais Google do agente
                agent_id = context.get("agent_id")
                google_creds = supabase.get_agent_google_credentials(agent_id)

                if not google_creds:
                    return {
                        "sucesso": False,
                        "mensagem": "Google Calendar nao esta configurado para este agente."
                    }

                refresh_token = google_creds.get("refresh_token")
                client_id = settings.google_client_id
                client_secret = settings.google_client_secret

                if not client_id or not client_secret or not refresh_token:
                    return {
                        "sucesso": False,
                        "mensagem": "Configuracao incompleta para Google Calendar."
                    }

                # Buscar dados do lead para o evento
                phone = context.get("phone")
                remotejid = context.get("remotejid")
                table_leads = context.get("table_leads")

                lead = supabase.get_lead_by_remotejid(table_leads, remotejid)
                lead_name = lead.get("nome", "Cliente") if lead else "Cliente"
                lead_email = lead.get("email") if lead else None

                # Buscar timezone do lead (ou usar padrão)
                lead_timezone = get_lead_timezone()
                logger.debug(f"[CALENDAR] Usando timezone do lead: {lead_timezone}")

                # Criar cliente OAuth2
                calendar_id = google_creds.get("calendar_id", "primary")
                calendar = create_google_calendar_oauth(
                    client_id=client_id,
                    client_secret=client_secret,
                    refresh_token=refresh_token,
                    calendar_id=calendar_id,
                    timezone=lead_timezone
                )

                # Montar data/hora ISO
                start_datetime = f"{date}T{time}:00"
                # Calcular hora de fim
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
                    create_meet_link=True
                )

                # Atualizar lead com info do agendamento
                if lead:
                    supabase.update_lead(
                        table_leads,
                        lead["id"],
                        {
                            "next_appointment_at": start_datetime,
                            "next_appointment_link": event.get("hangoutLink", ""),
                            "last_scheduled_at": datetime.utcnow().isoformat(),
                        }
                    )

                # Formatar data para resposta
                formatted_date = start_dt.strftime("%d/%m/%Y")
                formatted_time = start_dt.strftime("%H:%M")

                meet_link = event.get("hangoutLink", "")

                logger.debug(f"[CALENDAR] Evento criado: id={event.get('id')}, meet={meet_link}")

                return {
                    "sucesso": True,
                    "event_id": event.get("id"),
                    "link_meet": meet_link,
                    "data": formatted_date,
                    "horario": formatted_time,
                    "mensagem": f"Agendamento confirmado para {formatted_date} as {formatted_time}." + (f" Link da reuniao: {meet_link}" if meet_link else "")
                }

            except GoogleCalendarOAuthError as e:
                logger.error(f"[Calendar] Erro OAuth ao agendar: {e}")
                return {
                    "sucesso": False,
                    "mensagem": f"Erro ao criar agendamento: {str(e)}"
                }
            except Exception as e:
                logger.error(f"[Calendar] Erro ao agendar: {e}", exc_info=True)
                return {
                    "sucesso": False,
                    "mensagem": f"Erro ao criar agendamento: {str(e)}"
                }

        # ====================================================================
        # HANDLER: CANCELAR AGENDAMENTO
        # ====================================================================
        async def cancelar_agendamento_handler(
            event_id: str = None,
            reason: str = None,
            **kwargs
        ):
            """
            Cancela um agendamento existente.
            Se event_id nao for fornecido, tenta buscar o ultimo agendamento do lead.
            """
            logger.debug(f"[CALENDAR] ========== CANCELAR AGENDAMENTO ==========")
            logger.debug(f"[CALENDAR] event_id={event_id}, reason={reason}")

            try:
                # Buscar credenciais Google do agente
                agent_id = context.get("agent_id")
                google_creds = supabase.get_agent_google_credentials(agent_id)

                if not google_creds:
                    return {
                        "sucesso": False,
                        "mensagem": "Google Calendar nao esta configurado para este agente."
                    }

                refresh_token = google_creds.get("refresh_token")
                client_id = settings.google_client_id
                client_secret = settings.google_client_secret

                if not client_id or not client_secret or not refresh_token:
                    return {
                        "sucesso": False,
                        "mensagem": "Configuracao incompleta para Google Calendar."
                    }

                # Criar cliente OAuth2
                calendar_id = google_creds.get("calendar_id", "primary")
                calendar = create_google_calendar_oauth(
                    client_id=client_id,
                    client_secret=client_secret,
                    refresh_token=refresh_token,
                    calendar_id=calendar_id,
                    timezone="America/Sao_Paulo"
                )

                # Se nao tiver event_id, tentar buscar do lead
                if not event_id:
                    remotejid = context.get("remotejid")
                    table_leads = context.get("table_leads")
                    lead = supabase.get_lead_by_remotejid(table_leads, remotejid)

                    if lead and lead.get("next_appointment_at"):
                        # Nota: Precisariamos armazenar o event_id no lead para isso funcionar
                        # Por enquanto, retornamos erro pedindo o event_id
                        return {
                            "sucesso": False,
                            "mensagem": "Nao consegui identificar qual agendamento cancelar. Pode me informar mais detalhes?"
                        }
                    else:
                        return {
                            "sucesso": False,
                            "mensagem": "Nao encontrei nenhum agendamento pendente para voce."
                        }

                # Deletar evento
                success = calendar.delete_event(event_id)

                if success:
                    # Limpar agendamento do lead
                    remotejid = context.get("remotejid")
                    table_leads = context.get("table_leads")
                    supabase.update_lead_by_remotejid(
                        table_leads,
                        remotejid,
                        {
                            "next_appointment_at": None,
                            "next_appointment_link": None,
                        }
                    )

                    logger.debug(f"[CALENDAR] Evento {event_id} cancelado")

                    return {
                        "sucesso": True,
                        "mensagem": f"Agendamento cancelado com sucesso." + (f" Motivo: {reason}" if reason else "")
                    }
                else:
                    return {
                        "sucesso": False,
                        "mensagem": "Agendamento nao encontrado ou ja foi cancelado."
                    }

            except GoogleCalendarOAuthError as e:
                logger.error(f"[Calendar] Erro OAuth ao cancelar: {e}")
                return {
                    "sucesso": False,
                    "mensagem": f"Erro ao cancelar agendamento: {str(e)}"
                }
            except Exception as e:
                logger.error(f"[Calendar] Erro ao cancelar: {e}", exc_info=True)
                return {
                    "sucesso": False,
                    "mensagem": f"Erro ao cancelar agendamento: {str(e)}"
                }

        # ====================================================================
        # HANDLER: REAGENDAR
        # ====================================================================
        async def reagendar_handler(
            event_id: str = None,
            nova_data: str = None,
            novo_horario: str = None,
            duration: int = 30,
            reason: str = None,
            **kwargs
        ):
            """
            Reagenda um evento existente para nova data/hora.
            """
            logger.debug(f"[CALENDAR] ========== REAGENDAR ==========")
            logger.debug(f"[CALENDAR] event_id={event_id}, nova_data={nova_data}, novo_horario={novo_horario}")

            try:
                if not nova_data or not novo_horario:
                    return {
                        "sucesso": False,
                        "mensagem": "Por favor, informe a nova data e horario desejados."
                    }

                # Buscar credenciais Google do agente
                agent_id = context.get("agent_id")
                google_creds = supabase.get_agent_google_credentials(agent_id)

                if not google_creds:
                    return {
                        "sucesso": False,
                        "mensagem": "Google Calendar nao esta configurado para este agente."
                    }

                refresh_token = google_creds.get("refresh_token")
                client_id = settings.google_client_id
                client_secret = settings.google_client_secret

                if not client_id or not client_secret or not refresh_token:
                    return {
                        "sucesso": False,
                        "mensagem": "Configuracao incompleta para Google Calendar."
                    }

                # Criar cliente OAuth2
                calendar_id = google_creds.get("calendar_id", "primary")
                calendar = create_google_calendar_oauth(
                    client_id=client_id,
                    client_secret=client_secret,
                    refresh_token=refresh_token,
                    calendar_id=calendar_id,
                    timezone="America/Sao_Paulo"
                )

                # Se nao tiver event_id, nao conseguimos reagendar
                if not event_id:
                    return {
                        "sucesso": False,
                        "mensagem": "Nao consegui identificar qual agendamento reagendar. Pode me informar mais detalhes?"
                    }

                # Montar nova data/hora
                new_start = f"{nova_data}T{novo_horario}:00"
                start_dt = datetime.strptime(new_start, "%Y-%m-%dT%H:%M:%S")
                end_dt = start_dt + timedelta(minutes=duration)
                new_end = end_dt.strftime("%Y-%m-%dT%H:%M:%S")

                # Atualizar evento
                updated_event = calendar.update_event(
                    event_id=event_id,
                    new_start=new_start,
                    new_end=new_end,
                    timezone="America/Sao_Paulo"
                )

                # Atualizar lead
                remotejid = context.get("remotejid")
                table_leads = context.get("table_leads")
                supabase.update_lead_by_remotejid(
                    table_leads,
                    remotejid,
                    {
                        "next_appointment_at": new_start,
                        "next_appointment_link": updated_event.get("hangoutLink", ""),
                    }
                )

                formatted_date = start_dt.strftime("%d/%m/%Y")
                formatted_time = start_dt.strftime("%H:%M")

                logger.debug(f"[CALENDAR] Evento {event_id} reagendado para {formatted_date} {formatted_time}")

                return {
                    "sucesso": True,
                    "event_id": updated_event.get("id"),
                    "link_meet": updated_event.get("hangoutLink", ""),
                    "nova_data": formatted_date,
                    "novo_horario": formatted_time,
                    "mensagem": f"Agendamento reagendado com sucesso para {formatted_date} as {formatted_time}." + (f" Motivo: {reason}" if reason else "")
                }

            except GoogleCalendarOAuthError as e:
                logger.error(f"[Calendar] Erro OAuth ao reagendar: {e}")
                return {
                    "sucesso": False,
                    "mensagem": f"Erro ao reagendar: {str(e)}"
                }
            except Exception as e:
                logger.error(f"[Calendar] Erro ao reagendar: {e}", exc_info=True)
                return {
                    "sucesso": False,
                    "mensagem": f"Erro ao reagendar: {str(e)}"
                }

        async def transferir_departamento_handler(
            departamento: str = None,
            motivo: str = None,
            observacoes: str = None,
            queue_id: int = None,
            user_id: int = None,
            **kwargs
        ):
            """
            Handler real para transferir atendimento via Leadbox.

            Aceita departamento (nome) OU queue_id/user_id direto.
            Apos transferir, marca o lead como pausado.
            """
            logger.info(f"[TRANSFER] ========== INICIANDO TRANSFERENCIA ==========")
            logger.info(f"[TRANSFER] departamento={departamento}, queue_id={queue_id}, user_id={user_id}")
            logger.info(f"[TRANSFER] motivo={motivo}")

            try:
                # ================================================================
                # PROTEÇÃO: Não transferir em contexto de cobrança para pedir pix/link
                # O Gemini às vezes ignora o prompt e tenta transferir mesmo assim
                # ================================================================
                conversation_context = context.get("conversation_context", "")
                if conversation_context in ["disparo_billing", "billing"]:
                    motivo_lower = (motivo or "").lower()
                    palavras_bloqueadas = ["pix", "link", "boleto", "código", "codigo", "qr", "pagamento", "fatura", "pagar"]
                    if any(palavra in motivo_lower for palavra in palavras_bloqueadas):
                        logger.warning(f"[TRANSFER] BLOQUEADO: contexto={conversation_context}, motivo='{motivo}' contém palavras de pagamento")
                        return {
                            "sucesso": False,
                            "mensagem": "Para enviar o link de pagamento, use a tool consultar_cliente. Não é necessário transferir.",
                            "instrucao": "USE a tool consultar_cliente para buscar o link de pagamento do cliente. NÃO transfira."
                        }

                # Converter para int (Gemini pode enviar float como 454.0)
                if queue_id is not None:
                    queue_id = int(queue_id)
                if user_id is not None:
                    user_id = int(user_id)

                handoff_config = context.get("handoff_triggers")
                logger.info(f"[TRANSFER] handoff_config enabled={handoff_config.get('enabled') if isinstance(handoff_config, dict) else 'N/A'}, has_departments={bool(handoff_config.get('departments')) if isinstance(handoff_config, dict) else False}")

                if not handoff_config:
                    logger.warning("[Leadbox] handoff_triggers nao configurado no agente")
                    return {
                        "sucesso": False,
                        "mensagem": "Transferencia nao configurada para este agente"
                    }

                if not handoff_config.get("enabled", True):
                    return {
                        "sucesso": False,
                        "mensagem": "Transferencia desabilitada para este agente"
                    }

                api_url = handoff_config.get("api_url")
                api_uuid = handoff_config.get("api_uuid")
                api_token = handoff_config.get("api_token")
                departments = handoff_config.get("departments", {})

                if not api_url or not api_uuid or not api_token:
                    logger.error("[Leadbox] Configuracao incompleta: falta api_url, api_uuid ou api_token")
                    return {
                        "sucesso": False,
                        "mensagem": "Configuracao Leadbox incompleta"
                    }

                # Determinar queue_id e user_id dinamicamente
                # Se Gemini passou departamento por nome, tentar resolver primeiro
                resolved_queue = queue_id
                if departamento and not queue_id:
                    dept_config = departments.get(departamento.lower())
                    if dept_config:
                        resolved_queue = int(dept_config.get("id") or dept_config.get("queue_id") or 0) or None

                logger.info(f"[TRANSFER] Input: queue_id={queue_id}, user_id={user_id}, departamento={departamento}, motivo='{motivo}'")

                # Resolver departamento dinamicamente (keywords, default, etc)
                final_queue_id, final_user_id, dept_name = resolve_department(
                    handoff_triggers=handoff_config,
                    queue_id=resolved_queue,
                    motivo=motivo,
                )

                logger.info(f"[TRANSFER] Final: queue_id={final_queue_id}, user_id={final_user_id}, dept={dept_name}")

                if not final_queue_id:
                    logger.debug("[TRANSFER] ERRO: Nao foi possivel resolver departamento!")
                    return {
                        "sucesso": False,
                        "mensagem": "Departamento nao configurado"
                    }

                # Criar instancia do LeadboxService
                logger.info(f"[TRANSFER] Criando LeadboxService: {api_url[:50]}...")
                leadbox = LeadboxService(
                    base_url=api_url,
                    api_uuid=api_uuid,
                    api_key=api_token
                )

                # Preparar motivo interno (NAO vai pro body da API - fica no Supabase)
                transfer_reason = motivo or "Transferindo atendimento"
                if observacoes:
                    transfer_reason += f" | {observacoes}"

                # Executar transferencia
                phone = context.get("phone")
                logger.info(f"[TRANSFER] Executando transferencia para {dept_name}: phone={phone}, queue={final_queue_id}, user={final_user_id}")

                result = await leadbox.transfer_to_department(
                    phone=phone,
                    queue_id=final_queue_id,
                    user_id=final_user_id,
                )

                logger.info(f"[TRANSFER] Resultado da API: {result}")

                if result["sucesso"]:
                    # Marcar lead como pausado (atendimento humano)
                    table_leads = context.get("table_leads")
                    remotejid = context.get("remotejid")

                    logger.info(f"[TRANSFER] Marcando lead como pausado: {table_leads} / {remotejid}")

                    # Campos que SEMPRE existem em qualquer tabela de leads
                    now = datetime.utcnow().isoformat()
                    supabase.update_lead_by_remotejid(
                        table_leads,
                        remotejid,
                        {
                            "Atendimento_Finalizado": "true",
                            "current_state": "human",
                            "paused_at": now,
                            "handoff_at": now,
                            "transfer_reason": transfer_reason,
                            "ticket_id": result.get("ticket_id"),
                            "current_queue_id": result.get("queue_id"),
                            "current_user_id": result.get("user_id"),
                        }
                    )

                    # ================================================================
                    # DETECÇÃO DE MANUTENÇÃO CORRETIVA (cliente relatou defeito)
                    # Best-effort: não impede transferência se falhar
                    # ================================================================
                    PALAVRAS_DEFEITO = [
                        "defeito", "quebrado", "quebrou", "não gela", "nao gela",
                        "pingando", "vazando", "barulho", "não liga", "nao liga",
                        "não funciona", "nao funciona", "problema", "estragou",
                        "parou", "queimou", "cheiro", "goteira", "gelo", "congelando",
                        "manutenção", "manutencao", "reparo", "conserto", "técnico", "tecnico"
                    ]
                    motivo_lower = (motivo or "").lower()
                    eh_defeito = any(palavra in motivo_lower for palavra in PALAVRAS_DEFEITO)

                    if eh_defeito:
                        try:
                            agent_id = context.get("agent_id")
                            # Buscar customer_id pelo telefone (normalizar: tentar com e sem 55)
                            phone_sem_55 = phone[2:] if phone.startswith("55") else phone
                            phone_com_55 = phone if phone.startswith("55") else f"55{phone}"

                            cliente_result = supabase.client.table("asaas_clientes").select(
                                "id"
                            ).or_(f"mobile_phone.eq.{phone_com_55},mobile_phone.eq.{phone_sem_55}").limit(1).execute()

                            if cliente_result.data:
                                customer_id = cliente_result.data[0]["id"]
                                # Buscar contrato ativo do cliente
                                contrato_result = supabase.client.table("contract_details").select(
                                    "id, maintenance_status"
                                ).eq("agent_id", agent_id).eq(
                                    "customer_id", customer_id
                                ).order("created_at", desc=True).limit(1).execute()

                                if contrato_result.data:
                                    contrato = contrato_result.data[0]
                                    # Marcar como manutenção corretiva
                                    supabase.client.table("contract_details").update({
                                        "maintenance_type": "corretiva",
                                        "maintenance_status": "scheduled",
                                        "problema_relatado": (motivo or "Problema relatado pelo cliente")[:500],
                                        "observacoes": f"Transferido pela IA. Departamento: {dept_name}",
                                        "created_by": "ia_transfer",
                                    }).eq("id", contrato["id"]).execute()
                                    logger.info(f"[MANUT CORRETIVA] Contrato {contrato['id']} marcado como corretiva. Motivo: {motivo_lower[:100]}")
                                else:
                                    logger.info(f"[MANUT CORRETIVA] Cliente {phone} sem contrato, só transferência")
                            else:
                                logger.info(f"[MANUT CORRETIVA] Cliente {phone} não encontrado em asaas_clientes")
                        except Exception as e:
                            logger.warning(f"[MANUT CORRETIVA] Erro ao registrar corretiva (best-effort): {e}")

                    # ================================================================
                    # DETECÇÃO DE MANUTENÇÃO PREVENTIVA TRANSFERIDA
                    # Se o cliente está em contexto de manutenção preventiva e foi
                    # transferido (sem ser defeito), marcar como "transferred"
                    # ================================================================
                    elif conversation_context == "manutencao_preventiva":
                        try:
                            agent_id = context.get("agent_id")
                            phone_sem_55 = phone[2:] if phone.startswith("55") else phone
                            phone_com_55 = phone if phone.startswith("55") else f"55{phone}"

                            cliente_result = supabase.client.table("asaas_clientes").select(
                                "id"
                            ).or_(f"mobile_phone.eq.{phone_com_55},mobile_phone.eq.{phone_sem_55}").limit(1).execute()

                            if cliente_result.data:
                                customer_id = cliente_result.data[0]["id"]
                                contrato_result = supabase.client.table("contract_details").select(
                                    "id, maintenance_status"
                                ).eq("agent_id", agent_id).eq(
                                    "customer_id", customer_id
                                ).eq("maintenance_status", "notified").order("created_at", desc=True).limit(1).execute()

                                if contrato_result.data:
                                    contrato = contrato_result.data[0]
                                    supabase.client.table("contract_details").update({
                                        "maintenance_status": "transferred",
                                        "transferido_at": now,
                                        "observacoes": f"Transferido pela IA. Departamento: {dept_name}. Motivo: {motivo or 'N/A'}",
                                    }).eq("id", contrato["id"]).execute()
                                    logger.info(f"[MANUT PREVENTIVA] Contrato {contrato['id']} marcado como 'transferred'")
                                else:
                                    logger.info(f"[MANUT PREVENTIVA] Cliente {phone} sem contrato notified, ignorando")
                            else:
                                logger.info(f"[MANUT PREVENTIVA] Cliente {phone} não encontrado")
                        except Exception as e:
                            logger.warning(f"[MANUT PREVENTIVA] Erro ao registrar transferência (best-effort): {e}")

                    logger.info(f"[TRANSFER] SUCESSO! dept={dept_name}, ticket_id={result.get('ticket_id')}, queue_id={result.get('queue_id')}, user_id={result.get('user_id')}")

                    return {
                        "sucesso": True,
                        "mensagem": "O departamento ideal vai falar com você.",
                        "instrucao": "IMPORTANTE: Use EXATAMENTE a mensagem acima para o usuario. NAO mencione filas, IDs ou detalhes tecnicos."
                    }
                else:
                    logger.info(f"[TRANSFER] Erro: {result.get('mensagem')}")
                    return {
                        "sucesso": False,
                        "mensagem": "Desculpe, tive um problema ao tentar te transferir. Pode tentar novamente em alguns instantes?",
                        "erro_interno": result.get('mensagem')
                    }

            except Exception as e:
                logger.info(f"[TRANSFER] EXCECAO: {e}")
                logger.error(f"[Leadbox] Erro ao transferir: {e}", exc_info=True)
                return {
                    "sucesso": False,
                    "mensagem": f"Erro ao transferir: {str(e)}"
                }

        # ====================================================================
        # HANDLER: DETECTAR FUSO HORÁRIO
        # ====================================================================
        async def detectar_fuso_horario_handler(
            cidade: str = None,
            estado: str = None,
            **kwargs
        ):
            """
            Detecta o fuso horário do lead baseado na localização.
            Salva no lead para uso futuro em agendamentos.
            """
            logger.debug(f"[TIMEZONE] ========== DETECTAR FUSO HORÁRIO ==========")
            logger.debug(f"[TIMEZONE] cidade={cidade}, estado={estado}")

            try:
                if not estado:
                    return {
                        "sucesso": False,
                        "mensagem": "Estado não informado. Preciso saber o estado (ex: SP, MT, RJ) para detectar o fuso horário."
                    }

                estado_upper = estado.upper().strip()

                # Buscar timezone no mapeamento
                timezone = TIMEZONE_MAP.get(estado_upper, DEFAULT_TIMEZONE)

                # Determinar descrição amigável
                offset_desc = TIMEZONE_DESCRIPTIONS.get(timezone, timezone)

                # Salvar no lead
                remotejid = context.get("remotejid")
                table_leads = context.get("table_leads")

                update_data = {
                    "timezone": timezone,
                    "estado": estado_upper,
                }
                if cidade:
                    update_data["cidade"] = cidade.strip()

                supabase.update_lead_by_remotejid(
                    table_leads,
                    remotejid,
                    update_data
                )

                logger.debug(f"[TIMEZONE] Timezone detectado: {timezone} ({offset_desc})")
                logger.debug(f"[TIMEZONE] Lead atualizado: {remotejid}")

                return {
                    "sucesso": True,
                    "timezone": timezone,
                    "offset": offset_desc,
                    "cidade": cidade,
                    "estado": estado_upper,
                    "mensagem": f"Fuso horário detectado: {offset_desc}. Todos os horários de agendamento serão no seu horário local."
                }

            except Exception as e:
                logger.error(f"[TIMEZONE] Erro ao detectar fuso horário: {e}", exc_info=True)
                return {
                    "sucesso": False,
                    "mensagem": f"Erro ao detectar fuso horário: {str(e)}"
                }

        # ====================================================================
        # HANDLER: IDENTIFICAR EQUIPAMENTO (MANUTENÇÃO - LÁZARO)
        # ====================================================================
        async def identificar_equipamento_handler(
            telefone: str = None,
            **kwargs
        ):
            """
            Identifica equipamento do cliente para manutenção.
            Usado pelo agente Lázaro (Alugar Ar).
            """
            from app.tools.manutencao import identificar_equipamento

            # Se não informou telefone, usar do contexto
            if not telefone:
                telefone = context.get("phone")

            agent_id = context.get("agent_id")
            return await identificar_equipamento(telefone=telefone, agent_id=agent_id)

        # ====================================================================
        # HANDLER: ANALISAR FOTO EQUIPAMENTO (MANUTENÇÃO - LÁZARO)
        # ====================================================================
        async def analisar_foto_equipamento_handler(
            foto_url: str,
            equipamentos_cliente: list = None,
            **kwargs
        ):
            """
            Analisa foto do equipamento usando Gemini Vision.
            Usado pelo agente Lázaro (Alugar Ar).
            """
            from app.tools.manutencao import analisar_foto_equipamento

            if not equipamentos_cliente:
                equipamentos_cliente = []

            return await analisar_foto_equipamento(foto_url, equipamentos_cliente)

        # ====================================================================
        # HANDLER: VERIFICAR DISPONIBILIDADE MANUTENCAO (LAZARO)
        # ====================================================================
        async def verificar_disponibilidade_manutencao_handler(
            data: str,
            periodo: str,
            **kwargs
        ):
            """
            Verifica se slot de manutencao esta disponivel.
            Usado pelo agente Lazaro (Alugar Ar).
            """
            from app.tools.manutencao import verificar_disponibilidade_manutencao

            agent_id = context.get("agent_id")
            return await verificar_disponibilidade_manutencao(
                data=data,
                periodo=periodo,
                agent_id=agent_id,
            )

        # ====================================================================
        # HANDLER: CONFIRMAR AGENDAMENTO MANUTENCAO (LAZARO)
        # ====================================================================
        async def confirmar_agendamento_manutencao_handler(
            data: str,
            periodo: str,
            contract_id: str,
            cliente_nome: str,
            telefone: str = None,
            **kwargs
        ):
            """
            Confirma e registra agendamento de manutencao no slot.
            Usado pelo agente Lazaro (Alugar Ar).
            """
            from app.tools.manutencao import confirmar_agendamento_manutencao

            agent_id = context.get("agent_id")

            # Se nao informou telefone, usar do contexto
            if not telefone:
                remotejid = context.get("remotejid", "")
                telefone = remotejid.replace("@s.whatsapp.net", "").replace("@lid", "").replace("@c.us", "")

            return await confirmar_agendamento_manutencao(
                data=data,
                periodo=periodo,
                contract_id=contract_id,
                cliente_nome=cliente_nome,
                telefone=telefone,
                agent_id=agent_id,
            )

        # ====================================================================
        # HANDLER: BUSCAR COBRANCAS
        # ====================================================================
        async def buscar_cobrancas_handler(
            cpf: str = None,
            tipo_link: str = "fatura",
            **kwargs
        ):
            """
            Busca cobrancas pendentes do cliente.

            Cenario 1 (recebeu cobranca): Usa telefone do contexto
            Cenario 2 (pediu do nada): Usa CPF informado
            """
            import re
            from supabase import create_client

            logger.info(f"[COBRANCAS] ========== BUSCANDO COBRANCAS ==========")
            logger.info(f"[COBRANCAS] cpf={cpf}, tipo_link={tipo_link}")

            try:
                # Obter contexto
                remotejid = context.get("remotejid", "")
                agent_id = context.get("agent_id")

                # Extrair telefone do remotejid
                telefone_lead = remotejid.replace("@s.whatsapp.net", "").replace("@lid", "").replace("@c.us", "")

                logger.info(f"[COBRANCAS] telefone_lead={telefone_lead}, agent_id={agent_id}")

                # Conectar ao Supabase
                supabase_client = create_client(settings.supabase_url, settings.supabase_service_key)

                # Limpar CPF se fornecido
                cpf_limpo = None
                if cpf:
                    cpf_limpo = re.sub(r'\D', '', cpf)
                    if len(cpf_limpo) not in [11, 14]:
                        return {
                            "sucesso": False,
                            "mensagem": "CPF invalido. Informe apenas os numeros (11 digitos)."
                        }

                customer_id = None
                customer_name = None

                # ================================================================
                # ESTRATEGIA DE BUSCA
                # ================================================================

                # 1. Se tem CPF, buscar em asaas_clientes
                if cpf_limpo:
                    logger.debug(f"[COBRANCAS] Buscando cliente por CPF: {cpf_limpo} (agent_id={agent_id})")
                    query = supabase_client.table("asaas_clientes").select(
                        "id, name, mobile_phone, agent_id"
                    ).eq("cpf_cnpj", cpf_limpo).is_("deleted_at", "null")
                    # Filtrar por agent_id para garantir isolamento entre contas
                    if agent_id:
                        query = query.eq("agent_id", agent_id)
                    result = query.execute()

                    if result.data:
                        clientes = result.data
                        if clientes:
                            customer_id = clientes[0]["id"]
                            customer_name = clientes[0]["name"]
                            logger.info(f"[COBRANCAS] Cliente encontrado por CPF: {customer_id} - {customer_name}")

                # 2. Se nao tem CPF, buscar em billing_notifications pelo telefone
                if not customer_id and telefone_lead:
                    # Tentar com e sem 55
                    telefones_busca = [telefone_lead]
                    if not telefone_lead.startswith("55"):
                        telefones_busca.append(f"55{telefone_lead}")
                    if telefone_lead.startswith("55"):
                        telefones_busca.append(telefone_lead[2:])

                    logger.debug(f"[COBRANCAS] Buscando cobranca enviada por telefone: {telefones_busca}")

                    for tel in telefones_busca:
                        query = supabase_client.table("billing_notifications").select(
                            "customer_id, customer_name, payment_id, valor, due_date, status"
                        ).eq("phone", tel).in_(
                            "status", ["sent", "pending"]
                        )
                        # Filtrar por agent_id para garantir que só retorna cobranças do agente correto
                        if agent_id:
                            query = query.eq("agent_id", agent_id)
                        result = query.order("sent_at", desc=True).limit(5).execute()

                        if result.data:
                            cobrancas = result.data
                            logger.info(f"[COBRANCAS] Encontradas {len(cobrancas)} cobrancas enviadas para {tel}")

                            # Formatar resposta
                            lista_cobrancas = []
                            for cob in cobrancas:
                                valor = cob.get('valor')
                                lista_cobrancas.append({
                                    "valor": f"R$ {float(valor):.2f}" if valor else "N/A",
                                    "vencimento": cob.get("due_date", "N/A"),
                                    "status": cob.get("status", "pendente"),
                                    "link": cob.get("payment_link", "")
                                })

                            # Retornar primeira cobranca com link
                            primeira = cobrancas[0]
                            link = primeira.get("payment_link", "")
                            valor = primeira.get("valor")
                            valor_fmt = f"R$ {float(valor):.2f}" if valor else ""

                            return {
                                "sucesso": True,
                                "encontrou": True,
                                "cliente": primeira.get("customer_name", "Cliente"),
                                "cobrancas": lista_cobrancas,
                                "quantidade": len(cobrancas),
                                "link_pagamento": link,
                                "tipo_link": "fatura",
                                "mensagem": f"Encontrei {len(cobrancas)} fatura(s) pendente(s) de {valor_fmt}. Link: {link}"
                            }

                # 3. Se encontrou customer_id por CPF, buscar em asaas_cobrancas
                if customer_id:
                    logger.debug(f"[COBRANCAS] Buscando cobrancas do cliente: {customer_id} (agent_id={agent_id})")

                    query = supabase_client.table("asaas_cobrancas").select(
                        "id, value, due_date, status, invoice_url, bank_slip_url"
                    ).eq("customer_id", customer_id).in_(
                        "status", ["PENDING", "OVERDUE"]
                    ).is_("deleted_at", "null")
                    # Filtrar por agent_id para garantir isolamento entre contas
                    if agent_id:
                        query = query.eq("agent_id", agent_id)
                    result = query.order("due_date", desc=False).limit(10).execute()

                    if result.data:
                        cobrancas = result.data
                        logger.info(f"[COBRANCAS] Encontradas {len(cobrancas)} cobrancas para {customer_id}")

                        # Formatar resposta
                        lista_cobrancas = []
                        for cob in cobrancas:
                            lista_cobrancas.append({
                                "id": cob["id"],
                                "valor": f"R$ {cob['value']:.2f}" if cob.get('value') else "N/A",
                                "vencimento": cob.get("due_date", "N/A"),
                                "status": "Vencida" if cob.get("status") == "OVERDUE" else "Pendente",
                                "link_fatura": cob.get("invoice_url", ""),
                                "link_boleto": cob.get("bank_slip_url", "")
                            })

                        # Sempre usar link da fatura (cliente escolhe PIX ou boleto dentro do link)
                        primeira = cobrancas[0]
                        link = primeira.get("invoice_url", primeira.get("bank_slip_url", ""))

                        # Calcular total
                        total = sum(c.get("value", 0) for c in cobrancas)
                        valor_primeira = primeira.get("value", 0)

                        # Resposta simples - sempre retorna link da fatura
                        # A IA deve explicar que dentro do link o cliente escolhe PIX ou boleto
                        resultado = {
                            "sucesso": True,
                            "encontrou": True,
                            "cliente": customer_name or "Cliente",
                            "cobrancas": lista_cobrancas,
                            "quantidade": len(cobrancas),
                            "total": f"R$ {total:.2f}",
                            "valor_primeira": f"R$ {valor_primeira:.2f}",
                            "link_pagamento": link,
                            "instrucao": "Envie o link ao cliente. Explique que ao abrir o link, ele pode escolher pagar por PIX ou boleto.",
                            "mensagem": f"Encontrei {len(cobrancas)} fatura(s) pendente(s). Valor: R$ {valor_primeira:.2f}. Link: {link}"
                        }

                        return resultado

                        return resultado
                    else:
                        return {
                            "sucesso": True,
                            "encontrou": False,
                            "cliente": customer_name,
                            "mensagem": f"Boa noticia! Nao encontrei nenhuma fatura pendente para {customer_name}."
                        }

                # Nao encontrou cliente
                if cpf_limpo:
                    return {
                        "sucesso": False,
                        "encontrou": False,
                        "mensagem": "Nao encontrei cadastro com esse CPF. Verifique se digitou corretamente ou entre em contato com o financeiro."
                    }
                else:
                    return {
                        "sucesso": False,
                        "encontrou": False,
                        "mensagem": "Para localizar suas faturas, preciso que informe seu CPF."
                    }

            except Exception as e:
                logger.error(f"[COBRANCAS] Erro ao buscar cobrancas: {e}")
                return {
                    "sucesso": False,
                    "mensagem": f"Erro ao buscar cobrancas: {str(e)}"
                }

        # ====================================================================
        # HANDLER: CONSULTAR CLIENTE (UNIFICADO - substitui buscar_cobrancas + identificar_equipamento)
        # ====================================================================
        async def consultar_cliente_handler(
            cpf: str = None,
            verificar_pagamento: bool = False,
            **kwargs
        ):
            """
            Consulta unificada do cliente: dados, financeiro, contratos, equipamentos.
            Substitui: buscar_cobrancas + identificar_equipamento

            Args:
                cpf: CPF/CNPJ do cliente
                verificar_pagamento: Se True, busca faturas pagas recentemente para
                                     confirmar pagamento quando cliente afirma que já pagou
            """
            from app.tools.cliente import consultar_cliente

            # Extrair telefone do contexto
            remotejid = context.get("remotejid", "")
            telefone = remotejid.replace("@s.whatsapp.net", "").replace("@lid", "").replace("@c.us", "")

            agent_id = context.get("agent_id")

            return await consultar_cliente(
                cpf=cpf,
                telefone=telefone,
                agent_id=agent_id,
                verificar_pagamento=verificar_pagamento
            )

        return {
            # Tools ativas (v2)
            "consultar_cliente": consultar_cliente_handler,
            "transferir_departamento": transferir_departamento_handler,
            # Tools legadas (mantidas para fallback)
            "consulta_agenda": consulta_agenda_handler,
            "agendar": agendar_handler,
            "cancelar_agendamento": cancelar_agendamento_handler,
            "reagendar": reagendar_handler,
            "detectar_fuso_horario": detectar_fuso_horario_handler,
            "identificar_equipamento": identificar_equipamento_handler,
            "analisar_foto_equipamento": analisar_foto_equipamento_handler,
            "verificar_disponibilidade_manutencao": verificar_disponibilidade_manutencao_handler,
            "confirmar_agendamento_manutencao": confirmar_agendamento_manutencao_handler,
            "buscar_cobrancas": buscar_cobrancas_handler,
        }

    # ========================================================================
    # MAIN HANDLER
    # ========================================================================

    async def handle_message(
        self,
        webhook_data: Dict[str, Any],
        background_tasks: Optional[BackgroundTasks] = None,
    ) -> Dict[str, Any]:
        """
        Processa mensagem recebida do webhook.

        Fluxo principal:
        1. Extrai dados da mensagem
        2. Valida (nao grupo, nao from_me)
        3. Identifica agente pelo instance_id
        4. Verifica comandos de controle
        5. Verifica se bot esta pausado
        6. Adiciona ao buffer e agenda processamento

        Args:
            webhook_data: Dados brutos do webhook
            background_tasks: BackgroundTasks do FastAPI (opcional)

        Returns:
            Dict com status do processamento
        """
        # Extrair dados da mensagem
        extracted = self._extract_message_data(webhook_data)

        # DEBUG: Log para identificar mensagens
        if extracted:
            print(f"[WEBHOOK] Mensagem recebida: phone={extracted.get('phone')}, instance_id={extracted.get('instance_id')}, from_me={extracted.get('from_me')}", flush=True)

        if extracted is None:
            return {"status": "ignored", "reason": "invalid_message"}

        # Ignorar mensagens de grupo
        if extracted["is_group"]:
            logger.debug(f"Mensagem de grupo ignorada: {extracted['remotejid']}")
            return {"status": "ignored", "reason": "group_message"}

        # ====================================================================
        # HUMAN TAKEOVER: Detectar quando humano responde pelo celular
        # fromMe=true + NAO enviado pela API = humano assumiu atendimento
        # (wasSentByApi ja filtrado em _extract_message_data)
        # ====================================================================
        if extracted["from_me"]:
            phone = extracted["phone"]
            remotejid = extracted["remotejid"]
            text = extracted["text"]
            instance_id = extracted["instance_id"]
            token = extracted.get("token", "")

            logger.info(f"[HUMAN TAKEOVER] Mensagem fromMe detectada para {remotejid}")
            logger.debug(f"[HUMAN TAKEOVER] Mensagem fromMe detectada: {text[:100]}...")

            # Buscar agente para identificar contexto
            supabase = self._get_supabase()
            agent = None
            if instance_id:
                agent = supabase.get_agent_by_instance_id(instance_id)
            if not agent and token:
                agent = supabase.get_agent_by_token(token)

            if not agent:
                logger.debug(f"[HUMAN TAKEOVER] Agente nao encontrado, ignorando fromMe")
                return {"status": "ignored", "reason": "from_me_no_agent"}

            agent_id = agent["id"]
            agent_name = agent.get("name", "")
            table_leads = agent.get("table_leads") or f"LeadboxCRM_{agent_id[:8]}"
            table_messages = agent.get("table_messages") or f"leadbox_messages_{agent_id[:8]}"

            # Verificar se e comando de controle do dono (/a, /p, /r)
            control_response = await self._handle_control_command(
                phone=phone,
                remotejid=remotejid,
                command=text,
                agent_id=agent_id,
                table_leads=table_leads,
                table_messages=table_messages,
            )

            if control_response:
                cmd = text.lower().strip()
                # Se /a, tambem limpar Atendimento_Finalizado
                if cmd in ["/a", "/ativar", "/activate"]:
                    supabase.update_lead_by_remotejid(
                        table_leads,
                        remotejid,
                        {"Atendimento_Finalizado": "false", "responsavel": "AI"},
                    )
                    logger.debug(f"[HUMAN TAKEOVER] IA reativada para {phone} via comando {cmd}")

                # Enviar resposta usando UAZAPI do agente
                agent_token = agent.get("uazapi_token")
                agent_base_url = agent.get("uazapi_base_url")
                if agent_token and agent_base_url:
                    uazapi = UazapiService(base_url=agent_base_url, api_key=agent_token)
                else:
                    uazapi = self._get_uazapi()
                await uazapi.send_text_message(phone, control_response)
                return {"status": "ok", "action": "control_command_owner"}

            # Verificar padroes de mensagem de bot (evitar falso positivo)
            if agent_name and text.strip().startswith(f"{agent_name}:"):
                logger.debug(f"[HUMAN TAKEOVER] Padrao de bot detectado (nome: {agent_name})")
                return {"status": "ignored", "reason": "from_me_bot_pattern"}

            if "Transferindo atendimento" in text:
                logger.debug(f"[HUMAN TAKEOVER] Padrao de transferencia detectado")
                return {"status": "ignored", "reason": "from_me_transfer_pattern"}

            if "O departamento ideal" in text:
                logger.debug(f"[HUMAN TAKEOVER] Padrao de auto-assign detectado")
                return {"status": "ignored", "reason": "from_me_auto_assign_pattern"}

            # Buscar lead para verificar estado atual
            lead = supabase.get_lead_by_remotejid(table_leads, remotejid)
            if not lead:
                # ============================================================
                # CENARIO 1: from_me=true + lead nao existe
                # ANTES de criar como humano_primeiro, aguardar um pouco
                # para dar tempo ao dispatch service criar o lead (race condition)
                # ============================================================
                logger.info(f"[HUMAN TAKEOVER] Lead nao encontrado para {remotejid} - aguardando 2s para verificar dispatch...")
                await asyncio.sleep(2)

                # Re-verificar se o lead foi criado pelo dispatch service
                lead = supabase.get_lead_by_remotejid(table_leads, remotejid)
                if lead:
                    # Lead foi criado (provavelmente pelo dispatch) - verificar se e fila de dispatch
                    handoff_check = agent.get("handoff_triggers") or {}
                    dispatch_depts_check = handoff_check.get("dispatch_departments") or {}
                    dispatch_queues_check = set()
                    for dept_key in ["billing", "manutencao"]:
                        if dispatch_depts_check.get(dept_key):
                            try:
                                dispatch_queues_check.add(int(dispatch_depts_check[dept_key]))
                            except (ValueError, TypeError):
                                pass

                    lead_queue = lead.get("current_queue_id")
                    lead_origin = lead.get("lead_origin", "")

                    # Se foi criado com origin de disparo, nao pausar
                    if lead_origin in ["disparo_cobranca", "disparo_manutencao"]:
                        logger.info(f"[HUMAN TAKEOVER] Lead {phone} criado por dispatch ({lead_origin}) - NAO pausando")
                        return {"status": "ignored", "reason": "dispatch_lead_created"}

                    # Se esta em fila de dispatch, nao pausar
                    if lead_queue and int(lead_queue) in dispatch_queues_check:
                        logger.info(f"[HUMAN TAKEOVER] Lead {phone} em fila de dispatch ({lead_queue}) - NAO pausando")
                        return {"status": "ignored", "reason": "dispatch_queue_detected"}

                    logger.info(f"[HUMAN TAKEOVER] Lead {phone} encontrado apos delay (origin={lead_origin}, queue={lead_queue}) - prosseguindo com verificacao")
                else:
                    # Lead ainda nao existe, criar como humano_primeiro
                    logger.info(f"[HUMAN TAKEOVER] Lead nao encontrado apos 2s para {remotejid} - criando PAUSADO (humano iniciou)")
                    try:
                        # NOTA: Quando from_me=True (humano enviando), push_name é do dispositivo,
                        # não do lead. Deixamos nome vazio - será preenchido quando o lead responder.
                        new_lead_data = {
                            "remotejid": remotejid,
                            "telefone": phone,
                            "nome": "",  # Nome vazio - será preenchido quando lead responder
                            "pipeline_step": "Leads",
                            "Atendimento_Finalizado": "true",
                            "responsavel": "Humano",
                            "status": "open",
                            "lead_origin": "humano_primeiro",
                            "created_date": datetime.utcnow().isoformat(),
                            "updated_date": datetime.utcnow().isoformat(),
                            "follow_count": 0,
                        }
                        supabase.client.table(table_leads).insert(new_lead_data).execute()
                        logger.info(f"[HUMAN TAKEOVER] Lead criado PAUSADO (humano primeiro) com nome vazio: {remotejid}")
                    except Exception as create_err:
                        logger.error(f"[HUMAN TAKEOVER] Erro ao criar lead pausado: {create_err}")
                    return {"status": "ok", "action": "lead_created_paused_human_first"}

            # Se ja esta pausado, apenas ignorar
            if lead.get("Atendimento_Finalizado") == "true":
                logger.debug(f"[HUMAN TAKEOVER] Lead {phone} ja pausado")
                return {"status": "ignored", "reason": "already_paused"}

            # ============================================================
            # IGNORAR HUMAN TAKEOVER EM FILAS DE DISPARO (IA COBRANCAS/MANUTENCAO)
            # Mensagens enviadas pela API de disparo chegam com fromMe=True
            # mas não devem pausar a IA - são disparos automáticos
            # ============================================================
            handoff = agent.get("handoff_triggers") or {}
            dispatch_depts = handoff.get("dispatch_departments") or {}
            dispatch_queues = set()
            if dispatch_depts.get("billing"):
                try:
                    dispatch_queues.add(int(dispatch_depts["billing"]["queueId"]))
                except (ValueError, TypeError, KeyError):
                    pass
            if dispatch_depts.get("manutencao"):
                try:
                    dispatch_queues.add(int(dispatch_depts["manutencao"]["queueId"]))
                except (ValueError, TypeError, KeyError):
                    pass

            current_queue = lead.get("current_queue_id")
            if current_queue:
                try:
                    current_queue = int(current_queue)
                except (ValueError, TypeError):
                    current_queue = None

            if current_queue and current_queue in dispatch_queues:
                logger.debug(f"[HUMAN TAKEOVER] Lead {phone} em fila de disparo {current_queue} - ignorando fromMe (disparo automatico)")
                return {"status": "ignored", "reason": "dispatch_queue_from_me"}

            # ============================================================
            # VERIFICAR LEAD_ORIGIN (fallback mais confiável - já está no banco)
            # Disparos automáticos definem lead_origin como disparo_cobranca/disparo_manutencao
            # ============================================================
            try:
                lead_data = supabase.get_lead_by_remotejid(table_leads, remotejid)
                if lead_data:
                    lead_origin = lead_data.get("lead_origin", "")
                    if lead_origin in ["disparo_cobranca", "disparo_manutencao"]:
                        logger.info(f"[HUMAN TAKEOVER] Lead {phone} com origin '{lead_origin}' - ignorando fromMe (disparo automatico)")
                        return {"status": "ignored", "reason": "dispatch_origin_from_me"}
            except Exception as e:
                logger.debug(f"[HUMAN TAKEOVER] Erro ao verificar lead_origin: {e}")

            # ============================================================
            # VERIFICAR CONTEXTO DA CONVERSA (disparo_billing, disparo_manutencao)
            # Quando a IA faz disparo, o contexto é salvo na conversa
            # Não pausar se for mensagem do próprio disparo da IA
            # ============================================================
            try:
                msg_record = supabase.get_conversation_history(table_messages, remotejid)
                if msg_record and msg_record.get("conversation_history"):
                    history = msg_record["conversation_history"]
                    messages = history.get("messages", [])
                    # Verificar últimas mensagens por contexto de disparo
                    for msg in reversed(messages[-5:]):  # Últimas 5 mensagens
                        msg_context = msg.get("context", "")
                        if msg_context in ["disparo_billing", "disparo_manutencao"]:
                            logger.info(f"[HUMAN TAKEOVER] Lead {phone} em contexto de disparo '{msg_context}' - ignorando fromMe (disparo automatico)")
                            return {"status": "ignored", "reason": "dispatch_context_from_me"}
            except Exception as e:
                logger.debug(f"[HUMAN TAKEOVER] Erro ao verificar contexto: {e}")

            # ============================================================
            # PAUSAR IA: Humano assumiu o atendimento
            # ============================================================
            logger.info(f"[HUMAN TAKEOVER] Humano assumiu atendimento de {phone} - pausando IA")
            logger.debug(f"[HUMAN TAKEOVER] IA PAUSADA para {phone} - humano assumiu atendimento")

            # Atualizar banco de dados
            supabase.update_lead_by_remotejid(
                table_leads,
                remotejid,
                {
                    "Atendimento_Finalizado": "true",
                    "responsavel": "Humano",
                    "paused_at": datetime.utcnow().isoformat(),
                },
            )

            # Pausar no Redis
            redis = await self._get_redis()
            await redis.pause_set(agent_id, phone)

            return {"status": "ok", "action": "human_takeover"}

        phone = extracted["phone"]
        remotejid = extracted["remotejid"]
        text = extracted["text"]
        instance_id = extracted["instance_id"]
        media_type = extracted.get("media_type")
        message_id = extracted.get("message_id")
        media_url = extracted.get("media_url")  # URL direta da midia (Leadbox)

        # DEBUG 1: Mensagem recebida
        logger.debug(f"[DEBUG 1/6] MENSAGEM RECEBIDA:")
        logger.debug(f"  -> Phone: {phone}")
        logger.debug(f"  -> RemoteJID: {remotejid}")
        logger.debug(f"  -> Texto: {text[:100]}...")
        logger.debug(f"  -> Instance ID: {instance_id}")
        logger.debug(f"  -> Push Name: {extracted.get('push_name', 'N/A')}")
        logger.debug(f"  -> Media Type: {media_type}")
        logger.debug(f"  -> Media URL: {media_url}")
        logger.debug(f"  -> Message ID: {message_id}")

        # Buscar agente pelo instance_id ou token
        supabase = self._get_supabase()
        token = extracted.get("token", "")

        # DEBUG 2: Identificando agente
        logger.debug(f"[DEBUG 2/6] BUSCANDO AGENTE por instance_id: {instance_id} ou token: {token[:10] if token else 'N/A'}...")

        agent = None

        # Primeiro tentar por instance_id
        if instance_id:
            agent = supabase.get_agent_by_instance_id(instance_id)

        # Fallback: tentar por token
        if not agent and token:
            logger.debug(f"[DEBUG 2/6] Tentando por token...")
            agent = supabase.get_agent_by_token(token)

        if not agent:
            logger.debug(f"[DEBUG 2/6] AGENTE NAO ENCONTRADO para instance_id: {instance_id} ou token")
            return {"status": "error", "reason": "agent_not_found"}

        # Verificar se agente esta ativo (defesa em profundidade alem do filtro no Supabase)
        if not agent.get("active", True):
            logger.info(f"[AGENT DISABLED] Agente '{agent.get('name')}' ({agent.get('id')}) esta inativo (active=false) - ignorando mensagem")
            return {"status": "ignored", "reason": "agent_inactive"}

        if agent.get("status") == "paused":
            logger.info(f"[AGENT DISABLED] Agente '{agent.get('name')}' ({agent.get('id')}) esta pausado (status=paused) - ignorando mensagem")
            return {"status": "ignored", "reason": "agent_paused"}

        logger.debug(f"[DEBUG 2/6] AGENTE ENCONTRADO:")
        logger.debug(f"  -> Agent ID: {agent.get('id', 'N/A')}")
        logger.debug(f"  -> Agent Name: {agent.get('name', 'N/A')}")

        agent_id = agent["id"]
        table_leads = agent.get("table_leads") or f"LeadboxCRM_{agent_id[:8]}"
        table_messages = agent.get("table_messages") or f"leadbox_messages_{agent_id[:8]}"

        # Obter system prompt e substituir variáveis dinâmicas
        raw_system_prompt = agent.get("system_prompt") or "Voce e um assistente virtual prestativo."
        agent_timezone = agent.get("timezone") or "America/Cuiaba"
        system_prompt = prepare_system_prompt(raw_system_prompt, agent_timezone)

        # Criar ou obter lead
        # Primeiro verificar se ja existe para detectar leads novos
        existing_lead = supabase.get_lead_by_remotejid(table_leads, remotejid)

        if not existing_lead:
            # ============================================================
            # CENARIO 2: from_me=false + lead nao existe
            # Cliente mandou mensagem primeiro - criar lead normalmente
            # mas adicionar delay para permitir sync do Leadbox webhook
            # ============================================================
            logger.info(f"[NEW LEAD] Lead novo detectado para {remotejid} - criando e aguardando sync Leadbox")

            # Criar lead normalmente via get_or_create_lead
            lead = supabase.get_or_create_lead(
                table_leads,
                remotejid,
                default_data={
                    "telefone": phone,
                    "nome": extracted["push_name"],
                }
            )

            # ============================================================
            # AUTO ASSIGN IMEDIATO PARA LEADS NOVOS
            # Não espera webhook do Leadbox - força atribuição via API PUSH
            # ============================================================
            handoff_config = agent.get("handoff_triggers") or {}
            queue_ia = handoff_config.get("queue_ia")
            queue_ia_user_id = handoff_config.get("queue_ia_user_id")

            if handoff_config.get("enabled") and queue_ia and queue_ia_user_id:
                try:
                    queue_ia_int = int(queue_ia)
                    user_id_int = int(queue_ia_user_id)

                    logger.info(
                        f"[AUTO ASSIGN NEW LEAD] Lead {phone} - forçando atribuição imediata: "
                        f"queue={queue_ia_int}, userId={user_id_int}"
                    )

                    leadbox_service = LeadboxService(
                        base_url=handoff_config.get("api_url"),
                        api_uuid=handoff_config.get("api_uuid"),
                        api_key=handoff_config.get("api_token"),
                    )

                    transfer_result = await leadbox_service.transfer_to_department(
                        phone=phone,
                        queue_id=queue_ia_int,
                        user_id=user_id_int,
                        external_key=f"new-lead-{remotejid}",
                        mensagem=None
                    )

                    if transfer_result.get("sucesso"):
                        logger.info(
                            f"[AUTO ASSIGN NEW LEAD] Lead {phone} atribuído com sucesso: "
                            f"ticket_id={transfer_result.get('ticket_id')}"
                        )
                        # Atualizar Supabase com queue e user
                        supabase.client.table(table_leads).update({
                            "current_queue_id": str(queue_ia_int),
                            "current_user_id": str(user_id_int),
                            "ticket_id": transfer_result.get("ticket_id"),
                            "updated_date": datetime.utcnow().isoformat()
                        }).eq("remotejid", remotejid).execute()

                        # Atualizar objeto local
                        lead["current_queue_id"] = str(queue_ia_int)
                        lead["current_user_id"] = str(user_id_int)
                        lead["ticket_id"] = transfer_result.get("ticket_id")
                    else:
                        logger.warning(
                            f"[AUTO ASSIGN NEW LEAD] Falha ao atribuir lead {phone}: "
                            f"{transfer_result.get('mensagem')}"
                        )
                except (ValueError, TypeError) as e:
                    logger.warning(f"[AUTO ASSIGN NEW LEAD] Erro de conversão para lead {phone}: {e}")
                except Exception as e:
                    logger.error(f"[AUTO ASSIGN NEW LEAD] Erro inesperado para lead {phone}: {e}")

            # Polling para aguardar ticket_id do Leadbox (até 10s)
            logger.info(f"[NEW LEAD] Iniciando polling para sync Leadbox: {remotejid}")
            _ticket_id_found = None
            for _poll_attempt in range(5):
                await asyncio.sleep(2)
                _fresh_lead = supabase.get_lead_by_remotejid(table_leads, remotejid)
                if _fresh_lead and _fresh_lead.get("ticket_id"):
                    _ticket_id_found = _fresh_lead["ticket_id"]
                    lead["ticket_id"] = str(_ticket_id_found)
                    # Atualizar outros campos relevantes do fresh_lead no dict lead
                    for _key in ("current_queue_id", "current_user_id"):
                        if _fresh_lead.get(_key) is not None:
                            lead[_key] = _fresh_lead[_key]
                    break
                logger.debug("[POLL TICKET] Tentativa %d/5 - ticket_id ainda não disponível para %s", _poll_attempt + 1, remotejid[:15])

            if not _ticket_id_found:
                logger.warning("[POLL TICKET] ticket_id não encontrado após 5 tentativas para %s", remotejid[:15])

            # Re-buscar lead com dados atualizados do Leadbox
            fresh_lead = supabase.get_lead_by_remotejid(table_leads, remotejid)
            if fresh_lead:
                lead = fresh_lead
                logger.info(f"[NEW LEAD] Lead re-buscado apos sync: {remotejid}")

                # ============================================================
                # ATRIBUICAO AUTOMATICA DE userId PARA LEADS NA FILA queue_ia
                # ============================================================
                handoff_config = agent.get("handoff_triggers") or {}
                queue_ia = handoff_config.get("queue_ia")
                queue_ia_user_id = handoff_config.get("queue_ia_user_id")

                current_queue_raw = lead.get("current_queue_id")
                current_user_raw = lead.get("current_user_id")

                # Se configurado queue_ia_user_id E lead está na fila queue_ia E userId NULL ou diferente
                if queue_ia_user_id and current_queue_raw and (not current_user_raw or str(current_user_raw) != str(queue_ia_user_id)):
                    try:
                        current_queue = int(current_queue_raw)
                        queue_ia_int = int(queue_ia) if queue_ia else None

                        if queue_ia_int and current_queue == queue_ia_int:
                            logger.info(
                                f"[AUTO ASSIGN] Lead {phone} na fila {queue_ia_int} sem userId - "
                                f"atribuindo automaticamente userId {queue_ia_user_id}"
                            )

                            # Instanciar LeadboxService com config do agente
                            leadbox_service = LeadboxService(
                                base_url=handoff_config.get("api_url"),
                                api_uuid=handoff_config.get("api_uuid"),
                                api_key=handoff_config.get("api_token"),
                            )

                            # Usar assign_user_silent para atribuir userId SEM enviar mensagem
                            # Usa PUT /tickets/{id} ao invés de API PUSH
                            ticket_id = lead.get("ticket_id")  # Pode ser None
                            transfer_result = await leadbox_service.assign_user_silent(
                                phone=phone,
                                queue_id=queue_ia_int,
                                user_id=int(queue_ia_user_id),
                                ticket_id=int(ticket_id) if ticket_id else None
                            )

                            if transfer_result.get("sucesso"):
                                logger.info(
                                    f"[AUTO ASSIGN] Lead {phone} atribuído com sucesso ao userId {queue_ia_user_id}"
                                )
                                # Atualizar current_user_id no banco local
                                supabase.client.table(table_leads).update({
                                    "current_user_id": str(queue_ia_user_id),
                                    "updated_date": datetime.utcnow().isoformat()
                                }).eq("remotejid", remotejid).execute()

                                # Atualizar objeto local também
                                lead["current_user_id"] = str(queue_ia_user_id)
                            else:
                                logger.warning(
                                    f"[AUTO ASSIGN] Falha ao atribuir userId {queue_ia_user_id} ao lead {phone}: "
                                    f"{transfer_result.get('mensagem')}"
                                )

                    except (ValueError, TypeError) as e:
                        logger.warning(f"[AUTO ASSIGN] Erro ao converter queue_id/user_id para lead {phone}: {e}")
                    except Exception as e:
                        logger.error(f"[AUTO ASSIGN] Erro inesperado ao atribuir userId para lead {phone}: {e}")

                # Verificar se humano assumiu durante o delay
                if lead.get("Atendimento_Finalizado") == "true":
                    logger.info(f"[NEW LEAD] Lead {phone} marcado como pausado durante sync - ignorando (humano assumiu)")
                    return {"status": "ignored", "reason": "new_lead_human_took_over"}

                # Verificar se foi para fila humana durante o delay
                handoff_check = agent.get("handoff_triggers") or {}
                queue_ia_check = int(handoff_check.get("queue_ia", 537))
                dispatch_depts_check = handoff_check.get("dispatch_departments") or {}
                ia_queues_check = {queue_ia_check}
                if dispatch_depts_check.get("billing"):
                    try:
                        ia_queues_check.add(int(dispatch_depts_check["billing"]["queueId"]))
                    except (ValueError, TypeError, KeyError):
                        pass
                if dispatch_depts_check.get("manutencao"):
                    try:
                        ia_queues_check.add(int(dispatch_depts_check["manutencao"]["queueId"]))
                    except (ValueError, TypeError, KeyError):
                        pass

                fresh_queue_raw = lead.get("current_queue_id")
                if fresh_queue_raw:
                    try:
                        fresh_queue = int(fresh_queue_raw)
                    except (ValueError, TypeError):
                        fresh_queue = None

                    if fresh_queue is not None and fresh_queue not in ia_queues_check:
                        logger.info(f"[NEW LEAD] Lead {phone} sincronizou para fila {fresh_queue} (nao e fila IA {ia_queues_check}) - ignorando")
                        return {"status": "ignored", "reason": "new_lead_synced_to_human_queue"}
            else:
                logger.warning(f"[NEW LEAD] Lead {phone} nao encontrado apos sync - prosseguindo com lead criado")
        else:
            # Lead ja existia - fluxo normal
            lead = supabase.get_or_create_lead(
                table_leads,
                remotejid,
                default_data={
                    "telefone": phone,
                    "nome": extracted["push_name"],
                }
            )

        # ============================================================
        # ATUALIZAR NOME DO LEAD SE ESTIVER VAZIO
        # Quando humano inicia contato (from_me=True), lead é criado com nome vazio.
        # Quando o lead responde (from_me=False), atualizamos o nome com push_name.
        # ============================================================
        lead_nome = lead.get("nome", "")
        push_name = extracted.get("push_name", "")

        # Atualizar nome se: está vazio, é "atendemos ligação", ou é só o telefone
        nome_invalido = (
            not lead_nome or
            lead_nome.lower() == "atendemos ligação" or
            lead_nome == phone or
            lead_nome == lead.get("telefone", "")
        )

        if nome_invalido and push_name and push_name.lower() != "atendemos ligação":
            try:
                supabase.client.table(table_leads).update({
                    "nome": push_name,
                    "updated_date": datetime.utcnow().isoformat()
                }).eq("remotejid", remotejid).execute()
                lead["nome"] = push_name  # Atualizar objeto local também
                logger.info(f"[LEAD NAME] Nome atualizado para '{push_name}' (lead {phone})")
            except Exception as name_err:
                logger.warning(f"[LEAD NAME] Erro ao atualizar nome do lead {phone}: {name_err}")

        # ============================================================
        # CONTAGEM DE SESSÕES DE ATENDIMENTO
        # Verifica/cria sessão e obtém total de atendimentos do cliente
        # ============================================================
        try:
            total_atendimentos = supabase.ensure_session(agent_id, remotejid)
            lead["total_atendimentos"] = total_atendimentos
            logger.debug(f"[SESSION] Lead {phone} tem {total_atendimentos} atendimentos")
        except Exception as session_err:
            logger.warning(f"[SESSION] Erro ao verificar sessão para {phone}: {session_err}")
            lead["total_atendimentos"] = 1

        # Resetar follow-up quando lead responde
        try:
            from app.jobs.reengajar_leads import reset_follow_up_on_lead_response
            follow_up_count = lead.get("follow_up_count") or 0
            if follow_up_count > 0:
                await reset_follow_up_on_lead_response(
                    table_leads=table_leads,
                    remotejid=remotejid,
                    agent_id=agent_id,
                )
                logger.debug(f"[FOLLOW-UP] Contadores resetados para {phone} (tinha {follow_up_count} follow-ups)")
        except Exception as fu_err:
            logger.warning(f"Erro ao resetar follow-up para {phone}: {fu_err}")

        # Verificar comandos de controle ANTES de checar pause
        # (permite /a reativar mesmo quando IA esta pausada)
        control_response = await self._handle_control_command(
            phone=phone,
            remotejid=remotejid,
            command=text,
            agent_id=agent_id,
            table_leads=table_leads,
            table_messages=table_messages,
        )

        if control_response:
            # Enviar resposta do comando
            uazapi = self._get_uazapi()
            await uazapi.send_text_message(phone, control_response)
            return {"status": "ok", "action": "control_command"}

        # ====================================================================
        # VERIFICAR FILA DO LEADBOX (dados atualizados via webhook)
        # Verificação PRÉ-agendamento: usa dados do lead já carregado
        # ====================================================================
        handoff = agent.get("handoff_triggers") or {}
        QUEUE_IA = int(handoff.get("queue_ia", 537))

        # Filas adicionais de IA (dispatch de cobranças e manutenção)
        # Essas filas também são atendidas pela IA, não por humanos
        dispatch_depts = handoff.get("dispatch_departments") or {}
        IA_QUEUES = {QUEUE_IA}
        if dispatch_depts.get("billing"):
            try:
                IA_QUEUES.add(int(dispatch_depts["billing"]["queueId"]))
            except (ValueError, TypeError, KeyError):
                pass
        if dispatch_depts.get("manutencao"):
            try:
                IA_QUEUES.add(int(dispatch_depts["manutencao"]["queueId"]))
            except (ValueError, TypeError, KeyError):
                pass

        logger.debug(f"[LEADBOX] Filas de IA configuradas: {IA_QUEUES}")

        if lead.get("current_queue_id"):
            try:
                current_queue = int(lead["current_queue_id"])
            except (ValueError, TypeError):
                current_queue = None

            if current_queue is not None and current_queue not in IA_QUEUES:
                logger.debug(f"[LEADBOX] Lead {phone} na fila {current_queue} (pré-agendamento) - aguardando 3s para recheck...")
                await asyncio.sleep(3)
                fresh_lead = supabase.get_lead_by_remotejid(table_leads, remotejid)
                if fresh_lead:
                    fresh_queue_raw = fresh_lead.get("current_queue_id")
                    try:
                        fresh_queue = int(fresh_queue_raw) if fresh_queue_raw else None
                    except (ValueError, TypeError):
                        fresh_queue = None
                    if fresh_queue is not None and fresh_queue not in IA_QUEUES:
                        logger.debug(f"[LEADBOX] Lead {phone} na fila {fresh_queue} (pré-agendamento recheck) - IGNORANDO (não é fila IA {IA_QUEUES})")
                        return {"status": "ignored", "reason": "lead_em_outra_fila"}
                    else:
                        logger.debug(f"[LEADBOX] Lead {phone} mudou para fila {fresh_queue} (pré-agendamento recheck) - OK, processando")
                        lead = fresh_lead
                else:
                    logger.debug(f"[LEADBOX] Lead {phone} não encontrado no recheck - IGNORANDO")
                    return {"status": "ignored", "reason": "lead_nao_encontrado_recheck"}
            elif current_queue in IA_QUEUES:
                logger.debug(f"[LEADBOX] Lead {phone} na fila {current_queue} (pré-agendamento) - OK, processando (filas IA: {IA_QUEUES})")
        else:
            logger.debug(f"[LEADBOX] Lead {phone} sem current_queue_id (pré-agendamento) - prosseguindo")

        # ====================================================================
        # VERIFICAR SE ATENDIMENTO FOI FINALIZADO (transferido para humano)
        # Se Atendimento_Finalizado == "true", a IA deve ficar PAUSADA
        # ====================================================================
        atendimento_finalizado = lead.get("Atendimento_Finalizado", "")
        if atendimento_finalizado == "true":
            logger.info(f"Atendimento finalizado para {phone} (transferido para humano), IA pausada")
            logger.debug(f"[DEBUG] ATENDIMENTO FINALIZADO para {phone} - IA pausada, ignorando mensagem")
            return {"status": "ignored", "reason": "atendimento_finalizado"}

        # Verificar se bot esta pausado
        redis = await self._get_redis()
        is_paused = await redis.pause_is_paused(agent_id, phone)

        # Tambem verificar no Supabase
        if not is_paused:
            is_paused = supabase.is_lead_paused(table_leads, remotejid)

        if is_paused:
            logger.info(f"Bot pausado para {phone}, mensagem ignorada")
            return {"status": "ignored", "reason": "bot_paused"}

        # DEBUG 3: Adicionando ao buffer
        logger.debug(f"[DEBUG 3/6] ADICIONANDO AO BUFFER:")
        logger.debug(f"  -> Agent ID: {agent_id}")
        logger.debug(f"  -> Phone: {phone}")
        logger.debug(f"  -> Texto: {text[:50]}...")

        # Adicionar ao buffer
        await redis.buffer_add_message(agent_id, phone, text)
        logger.debug(f"[DEBUG 3/6] MENSAGEM ADICIONADA AO BUFFER com sucesso")

        # Atualizar Msg_user (timestamp da ultima mensagem do lead)
        try:
            from datetime import datetime as dt_user
            supabase.client.table(table_messages).upsert({
                "remotejid": remotejid,
                "Msg_user": dt_user.utcnow().isoformat()
            }, on_conflict="remotejid").execute()
        except Exception as e_ts:
            logger.warning(f"Erro ao atualizar Msg_user: {e_ts}")

        # Determinar se e mensagem de audio e guardar message_id
        audio_message_id = None
        if media_type in ["audio", "ptt", "AudioMessage"] and message_id:
            audio_message_id = message_id
            logger.debug(f"[DEBUG 3/6] AUDIO DETECTADO - message_id guardado: {audio_message_id}")

        # Determinar se e mensagem de imagem e guardar message_id e/ou URL
        image_message_id = None
        image_url = None
        if media_type in ["image", "imageMessage", "document", "documentMessage"]:
            if message_id:
                image_message_id = message_id
            if media_url:
                image_url = media_url
            media_label = "DOCUMENTO" if media_type in ["document", "documentMessage"] else "IMAGEM"
            logger.debug(f"[DEBUG 3/6] {media_label} DETECTADO - message_id={image_message_id}, url={image_url[:50] if image_url else None}")

        # Criar contexto de processamento
        context: ProcessingContext = {
            "agent_id": agent_id,
            "agent_name": agent.get("name", "Assistente"),  # Nome para assinatura das mensagens
            "remotejid": remotejid,
            "phone": phone,
            "table_leads": table_leads,
            "table_messages": table_messages,
            "system_prompt": system_prompt,
            "uazapi_token": agent.get("uazapi_token"),
            "uazapi_base_url": agent.get("uazapi_base_url"),
            "handoff_triggers": agent.get("handoff_triggers"),  # Config Leadbox
            "audio_message_id": audio_message_id,  # ID da mensagem de audio
            "image_message_id": image_message_id,  # ID da mensagem de imagem
            "image_url": image_url,  # URL direta da imagem (Leadbox)
            "context_prompts": agent.get("context_prompts"),  # Prompts dinamicos (RAG simplificado)
            "total_atendimentos": lead.get("total_atendimentos", 1),  # Sessões de atendimento do cliente
            "lead_nome": lead.get("nome", ""),  # Nome do lead para contexto
        }

        # Agendar processamento
        await self._schedule_processing(
            agent_id=agent_id,
            phone=phone,
            remotejid=remotejid,
            context=context,
        )

        return {"status": "ok", "action": "buffered"}


# ============================================================================
# FASTAPI ROUTER
# ============================================================================

router = APIRouter(prefix="/webhook", tags=["webhook"])

# Instancia singleton do handler
_webhook_handler: Optional[WhatsAppWebhookHandler] = None


def get_webhook_handler() -> WhatsAppWebhookHandler:
    """Retorna instancia singleton do WhatsAppWebhookHandler."""
    global _webhook_handler
    if _webhook_handler is None:
        _webhook_handler = WhatsAppWebhookHandler()
    return _webhook_handler


@router.post("/whatsapp")
async def webhook_whatsapp_post(
    request: Request,
    background_tasks: BackgroundTasks,
) -> Dict[str, Any]:
    """
    Endpoint POST para receber webhooks do WhatsApp (UAZAPI).

    Processa a mensagem em background e retorna imediatamente.

    Args:
        request: Request do FastAPI
        background_tasks: BackgroundTasks para processamento async

    Returns:
        Dict com status do processamento
    """
    try:
        # Parsear body
        body = await request.json()

        logger.debug(f"Webhook recebido: {str(body)[:200]}...")

        # Verificar tipo de evento
        event_type = body.get("event") or body.get("type")

        # Ignorar eventos que nao sao mensagens
        if event_type and event_type not in ["messages.upsert", "message", "messages"]:
            logger.debug(f"Evento ignorado: {event_type}")
            return {"status": "ignored", "reason": f"event_type_{event_type}"}

        # Processar mensagem
        handler = get_webhook_handler()
        result = await handler.handle_message(body, background_tasks)

        return result

    except Exception as e:
        logger.error(f"Erro no webhook WhatsApp: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@router.get("/whatsapp")
async def webhook_whatsapp_get() -> Dict[str, Any]:
    """
    Endpoint GET para verificacao do webhook.

    Usado pela UAZAPI para verificar se o endpoint esta ativo.

    Returns:
        Dict com status de verificacao
    """
    return {
        "status": "ok",
        "service": "agente-ia",
        "webhook": "whatsapp",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.post("/whatsapp/test")
async def webhook_whatsapp_test(request: Request) -> Dict[str, Any]:
    """
    Endpoint de teste para simular mensagens do webhook.

    Util para desenvolvimento e debugging.

    Args:
        request: Request com payload de teste

    Returns:
        Dict com resultado do processamento
    """
    try:
        body = await request.json()

        # Validar campos minimos
        required = ["phone", "text"]
        for field in required:
            if field not in body:
                raise HTTPException(status_code=400, detail=f"Campo obrigatorio: {field}")

        # Montar payload no formato UAZAPI
        webhook_data = {
            "event": "messages.upsert",
            "instanceId": body.get("instance_id", "test-instance"),
            "data": {
                "key": {
                    "remoteJid": f"{body['phone']}@s.whatsapp.net",
                    "fromMe": False,
                    "id": f"test_{datetime.utcnow().timestamp()}",
                },
                "message": {
                    "conversation": body["text"],
                },
                "pushName": body.get("name", "Teste"),
                "messageTimestamp": datetime.utcnow().isoformat(),
            },
        }

        # Processar
        handler = get_webhook_handler()
        result = await handler.handle_message(webhook_data)

        return {"test": True, "result": result}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro no teste de webhook: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
