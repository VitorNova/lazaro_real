"""
Observer Service - Agente observador de conversas.

Funcionalidades:
- Analisa conversas entre lead, IA e humanos
- Extrai URLs de anuncios e origem do lead
- Identifica quem esta falando (lead/IA/humano)
- Gera resumos automaticos
- Sugere ou move cards no pipeline (modo hibrido)

Este agente NAO responde - apenas observa e atualiza dados.
"""

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

import google.generativeai as genai
from google.generativeai.types import GenerationConfig, HarmBlockThreshold, HarmCategory

from app.config import settings
from app.services.supabase import get_supabase_service


logger = logging.getLogger(__name__)


# ============================================================================
# CONSTANTES
# ============================================================================

# Tools que indicam alta confianca para mover card automaticamente
# Nomes de etapas com maiuscula inicial para match com pipeline do Lazaro
HIGH_CONFIDENCE_TOOLS: Dict[str, str] = {
    "schedule_meeting": "Agendado",
    "agendar_reuniao": "Agendado",
    "create_schedule": "Agendado",
    "generate_payment_link": "Proposta",
    "criar_link_pagamento": "Proposta",
    "send_payment_link": "Proposta",
}

# Palavras-chave para deteccao de fechamento
CLOSING_KEYWORDS_POSITIVE = [
    "fechado", "vamos fechar", "pode faturar", "quero contratar",
    "vou assinar", "aceito", "fechamos", "trato feito", "negocio fechado",
]

CLOSING_KEYWORDS_NEGATIVE = [
    "nao quero", "nao tenho interesse", "para de mandar",
    "nao me ligue", "sai dessa lista", "bloqueado", "spam",
    "desisto", "cancela", "nao preciso",
]

# Padroes de URL de anuncios
AD_URL_PATTERNS = [
    r"fb\.me/[a-zA-Z0-9]+",
    r"facebook\.com/ads",
    r"instagram\.com/[a-zA-Z0-9_.]+",
    r"ig\.me/[a-zA-Z0-9]+",
    r"gclid=[a-zA-Z0-9_-]+",
    r"utm_source=[a-zA-Z0-9_-]+",
    r"google\.com/ads",
]


# ============================================================================
# OBSERVER SERVICE
# ============================================================================

class ObserverService:
    """
    Servico de observacao de conversas.

    Analisa conversas e extrai insights sem responder ao lead.
    Usa modo hibrido: alta confianca = move auto, baixa = sugere.
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Inicializa o observer.

        Args:
            api_key: Chave da API do Gemini (usa settings se nao fornecido)
        """
        self._api_key = api_key or settings.google_api_key
        self._model_name = "gemini-2.0-flash"
        self._supabase = get_supabase_service()

        # Configurar Gemini
        genai.configure(api_key=self._api_key)

        self._safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }

        logger.info("ObserverService inicializado")

    async def analyze(
        self,
        table_leads: str,
        table_messages: str,
        lead_id: int,
        remotejid: str,
        tools_used: Optional[List[str]] = None,
        force: bool = False,
        agent_id: Optional[str] = None,
        queue_ia: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Analisa conversa de um lead e atualiza insights.

        Args:
            table_leads: Nome da tabela de leads
            table_messages: Nome da tabela de mensagens
            lead_id: ID do lead
            remotejid: WhatsApp ID do lead
            tools_used: Lista de tools usadas na ultima resposta
            force: Se True, ignora throttle de tempo
            agent_id: ID do agente (para buscar observer_prompt customizado)
            queue_ia: ID da fila da IA. Se fornecido, Observer so atua se lead
                      estiver nesta fila (current_queue_id == queue_ia)

        Returns:
            Dict com insights extraidos. Se queue_ia fornecido e lead nao
            esta na fila da IA, retorna {"skipped": True, "reason": "..."}
        """
        try:
            # 1. Buscar lead atual
            lead = self._supabase.get_lead_by_id(table_leads, lead_id)
            if not lead:
                logger.warning(f"Lead {lead_id} nao encontrado")
                return {}

            # 1.1 Validar fila se queue_ia fornecido
            if queue_ia is not None:
                current_queue_raw = lead.get("current_queue_id")
                if current_queue_raw:
                    try:
                        current_queue = int(current_queue_raw)
                    except (ValueError, TypeError):
                        current_queue = None

                    if current_queue is not None and current_queue != queue_ia:
                        logger.debug(
                            f"[Observer] Lead {lead_id} na fila {current_queue}, "
                            f"ignorando (fila IA = {queue_ia})"
                        )
                        return {
                            "skipped": True,
                            "reason": f"Lead na fila {current_queue}, fila IA e {queue_ia}",
                        }

            # 2. Verificar throttle (5 min entre analises)
            if not force:
                current_insights = lead.get("insights") or {}
                last_update = current_insights.get("updated_at")
                if last_update:
                    try:
                        last_dt = datetime.fromisoformat(last_update.replace("Z", "+00:00"))
                        now = datetime.utcnow()
                        diff_minutes = (now - last_dt.replace(tzinfo=None)).total_seconds() / 60
                        if diff_minutes < 5:
                            logger.debug(f"Throttle ativo, ultima analise ha {diff_minutes:.1f} min")
                            return current_insights
                    except Exception:
                        pass

            # 3. Buscar historico de conversas
            history = self._supabase.get_conversation_history(table_messages, remotejid)
            if not history or not history.get("messages"):
                logger.debug(f"Sem historico para {remotejid}")
                return {}

            messages = history.get("messages", [])
            if len(messages) < 2:
                logger.debug(f"Historico muito curto para analise")
                return {}

            # 4. Buscar observer_prompt customizado do agente
            observer_prompt = None
            if agent_id:
                try:
                    agent = self._supabase.get_agent_by_id(agent_id)
                    if agent:
                        observer_prompt = agent.get("observer_prompt")
                        if observer_prompt:
                            logger.debug(f"[Observer] Usando prompt customizado do agente {agent_id}")
                except Exception as e:
                    logger.warning(f"[Observer] Erro ao buscar agente {agent_id}: {e}")

            # 5. Verificar alta confianca (tools usadas)
            insights = await self._check_high_confidence(
                lead=lead,
                table_leads=table_leads,
                tools_used=tools_used or [],
                messages=messages,
            )

            # 6. Se nao teve alta confianca, analisar com IA
            if not insights.get("auto_moved"):
                ai_insights = await self._analyze_with_ai(
                    lead=lead,
                    messages=messages[-20:],  # Ultimas 20 mensagens
                    observer_prompt=observer_prompt,
                )
                insights.update(ai_insights)

            # 7. Extrair URLs de anuncios e determinar origem
            ad_urls = self._extract_ad_urls(messages)
            if ad_urls:
                insights["ad_urls"] = list(ad_urls)
                insights["origin"] = self._infer_origin(ad_urls)
            elif insights.get("inferred_origin"):
                # Se nao tem URLs mas a IA inferiu origem da conversa (prompt padrao)
                insights["origin"] = insights["inferred_origin"]
            elif insights.get("origem"):
                # Se nao tem URLs mas a IA inferiu origem (prompt customizado em portugues)
                insights["origin"] = insights["origem"]

            # 8. Atualizar timestamp
            insights["updated_at"] = datetime.utcnow().isoformat()

            # 9. Salvar insights no lead
            update_data: Dict[str, Any] = {"insights": insights}

            # Se identificou origem, atualizar lead_origin para o front-end
            # So atualiza se: origem atual e null/whatsapp E nova origem e diferente de whatsapp
            new_origin = insights.get("origin")
            current_origin = lead.get("lead_origin")
            if new_origin and new_origin != "whatsapp":
                if not current_origin or current_origin == "whatsapp":
                    update_data["lead_origin"] = new_origin
                    logger.info(f"[Observer] Atualizando lead_origin: {current_origin} -> {new_origin}")

            # Se moveu automaticamente, atualizar pipeline_step
            if insights.get("auto_moved") and insights.get("new_stage"):
                update_data["pipeline_step"] = insights["new_stage"]
                logger.info(
                    f"[Observer] Movendo lead {lead_id} para '{insights['new_stage']}' "
                    f"(razao: {insights.get('moved_reason', 'N/A')})"
                )

            # Se identificou nome do humano, atualizar responsavel
            human_info = insights.get("speakers", {}).get("human")
            if human_info and human_info.get("name"):
                current_responsavel = lead.get("responsavel", "").lower()
                # So atualiza se for generico
                if current_responsavel in ["ai", "humano", "human", "atendente", ""]:
                    human_name = human_info["name"]
                    if human_info.get("role"):
                        human_name += f" ({human_info['role']})"
                    update_data["responsavel"] = human_name
                    logger.info(f"[Observer] Identificado responsavel: {human_name}")

            # Se tem resumo, salvar em campo separado para exibicao no CRM
            # Coluna correta na tabela e 'resumo' (nao 'resumo_conversa')
            summary = insights.get("summary")
            if summary:
                update_data["resumo"] = summary

            self._supabase.update_lead(table_leads, lead_id, update_data)

            logger.info(
                f"[Observer] Lead {lead_id} analisado",
                extra={
                    "auto_moved": insights.get("auto_moved"),
                    "suggested_stage": insights.get("suggested_stage"),
                    "sentiment": insights.get("sentiment"),
                },
            )

            return insights

        except Exception as e:
            logger.error(f"[Observer] Erro ao analisar lead {lead_id}: {e}", exc_info=True)
            return {}

    async def _check_high_confidence(
        self,
        lead: Dict[str, Any],
        table_leads: str,
        tools_used: List[str],
        messages: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Verifica se ha alta confianca para mover card automaticamente.

        Retorna insights com auto_moved=True se detectar:
        - Tool de agendamento usada
        - Tool de pagamento usada
        - Palavras-chave de fechamento
        """
        insights: Dict[str, Any] = {"auto_moved": False}

        # 1. Verificar tools usadas
        for tool_name in tools_used:
            tool_lower = tool_name.lower()
            for pattern, stage in HIGH_CONFIDENCE_TOOLS.items():
                if pattern in tool_lower:
                    insights["auto_moved"] = True
                    insights["new_stage"] = stage
                    insights["moved_reason"] = f"Tool '{tool_name}' executada"
                    return insights

        # 2. Verificar palavras-chave de fechamento nas ultimas mensagens
        last_messages_text = self._get_last_messages_text(messages, count=5)

        for keyword in CLOSING_KEYWORDS_POSITIVE:
            if keyword in last_messages_text.lower():
                insights["auto_moved"] = True
                insights["new_stage"] = "Ganho"
                insights["moved_reason"] = f"Detectada intencao de fechamento: '{keyword}'"
                return insights

        for keyword in CLOSING_KEYWORDS_NEGATIVE:
            if keyword in last_messages_text.lower():
                insights["auto_moved"] = True
                insights["new_stage"] = "Perdido"
                insights["moved_reason"] = f"Detectada desistencia: '{keyword}'"
                return insights

        return insights

    async def _analyze_with_ai(
        self,
        lead: Dict[str, Any],
        messages: List[Dict[str, Any]],
        observer_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Analisa conversa com IA para extrair insights.

        Args:
            lead: Dados do lead
            messages: Lista de mensagens da conversa
            observer_prompt: Prompt customizado do agente (se houver)
        """
        try:
            lead_name = lead.get("nome") or "Desconhecido"
            ai_paused = lead.get("Atendimento_Finalizado") == "true"

            # Formatar mensagens para o prompt
            formatted_messages = self._format_messages_for_prompt(messages)

            # Usar prompt customizado ou prompt padrao
            if observer_prompt:
                # Prompt customizado: adicionar contexto do lead e mensagens
                prompt = f"""{observer_prompt}

CONTEXTO DA CONVERSA:
LEAD: {lead_name}
IA PAUSADA: {ai_paused}

MENSAGENS:
{formatted_messages}

RESPONDA EM JSON EXATO:
{{
  "summary": "resumo aqui",
  "speakers": {{
    "lead": "nome do lead ou null",
    "human": {{"name": "nome do atendente ou null", "role": "cargo/setor ou null"}}
  }},
  "sentiment": "positivo|neutro|negativo",
  "suggested_stage": "estagio ou null",
  "current_handler": "ai|human",
  "last_speaker": "lead|ai|human"
}}

Responda APENAS o JSON, nada mais."""
            else:
                # Prompt padrao
                prompt = f"""Voce e um observador de conversas. Analise e extraia informacoes.
NUNCA gere uma resposta para o lead.

LEAD: {lead_name}
IA PAUSADA: {ai_paused}

MENSAGENS:
{formatted_messages}

EXTRAIA AS SEGUINTES INFORMACOES:

1. RESUMO: Faca um resumo de 2-3 frases focando em: interesse principal, objecoes, proximos passos.

2. SPEAKERS: Identifique quem falou:
   - Nome do lead (se mencionado)
   - Se humano atendeu, identifique nome e cargo/setor do ATENDENTE (nao confunda com o lead)
   - Padroes de apresentacao: "sou o/a X", "aqui e X", "X aqui", "meu nome e X"

3. SENTIMENTO: positivo, neutro ou negativo

4. SUGESTAO DE ESTAGIO: Se a conversa indica que o lead deveria mudar de estagio, sugira:
   - "qualificado" - mostrou interesse real
   - "agendado" - marcou reuniao/visita
   - "proposta" - pediu orcamento/proposta
   - "vendido" - fechou negocio
   - "perdido" - desistiu/bloqueou
   - null - manter estagio atual

5. ORIGEM DO LEAD:
   ATENÇÃO CRÍTICA: Analise APENAS as mensagens marcadas como [LEAD - ANALISAR] para identificar origem.
   - Mensagens marcadas como [RESPOSTA - APENAS CONTEXTO] NÃO são evidência de origem
   - Se o LEAD menciona Instagram, Facebook, etc → use como evidência
   - Se a RESPOSTA menciona Instagram → IGNORE para fins de origem

   Origens válidas (baseadas APENAS em evidências do lead):
   - "facebook_ads" - LEAD menciona Facebook, FB, anuncio do Facebook, vi no Face
   - "instagram" - LEAD menciona Instagram, Insta, vi no Insta, perfil do IG
   - "google_ads" - LEAD menciona Google, pesquisa no Google, anuncio do Google
   - "indicacao" - LEAD menciona indicacao, recomendacao, fulano indicou
   - "site" - LEAD menciona site, pagina, formulario
   - "whatsapp" - veio direto pelo WhatsApp sem mencionar origem
   - "telefone" - LEAD menciona ligacao, telefonema
   - "evento" - LEAD menciona evento, feira, palestra
   - "linkedin" - LEAD menciona LinkedIn
   - "tiktok" - LEAD menciona TikTok
   - null - nao foi possivel identificar nas mensagens do lead

RESPONDA EM JSON EXATO:
{{
  "summary": "resumo aqui",
  "speakers": {{
    "lead": "nome do lead ou null",
    "human": {{"name": "nome do atendente ou null", "role": "cargo/setor ou null"}}
  }},
  "sentiment": "positivo|neutro|negativo",
  "suggested_stage": "estagio ou null",
  "current_handler": "ai|human",
  "last_speaker": "lead|ai|human",
  "inferred_origin": "origem identificada ou null"
}}

Responda APENAS o JSON, nada mais."""

            # Chamar Gemini
            model = genai.GenerativeModel(
                model_name=self._model_name,
                generation_config=GenerationConfig(
                    temperature=0.2,
                    max_output_tokens=500,
                ),
                safety_settings=self._safety_settings,
            )

            response = await model.generate_content_async(prompt)
            response_text = response.text.strip()

            # Extrair JSON da resposta
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                insights = json.loads(json_match.group())
                return insights

            logger.warning(f"[Observer] Resposta nao contem JSON valido: {response_text[:100]}")
            return {}

        except Exception as e:
            logger.error(f"[Observer] Erro na analise com IA: {e}")
            return {}

    def _format_messages_for_prompt(self, messages: List[Dict[str, Any]]) -> str:
        """
        Formata mensagens para o prompt da IA.

        Marca mensagens do lead como [LEAD - ANALISAR] para indicar que são fontes
        válidas de evidência de origem. Mensagens do assistente são marcadas como
        [RESPOSTA - APENAS CONTEXTO] para indicar que NÃO devem ser usadas como
        evidência de origem do lead.
        """
        lines = []
        for msg in messages:
            role = msg.get("role", "user")
            parts = msg.get("parts", [])
            text = ""
            for part in parts:
                if isinstance(part, dict) and part.get("text"):
                    text += part["text"]
                elif isinstance(part, str):
                    text += part

            if role == "user":
                lines.append(f"[LEAD - ANALISAR]: {text}")
            else:
                lines.append(f"[RESPOSTA - APENAS CONTEXTO]: {text}")

        return "\n".join(lines)

    def _get_last_messages_text(self, messages: List[Dict[str, Any]], count: int = 5) -> str:
        """Retorna texto das ultimas N mensagens."""
        texts = []
        for msg in messages[-count:]:
            parts = msg.get("parts", [])
            for part in parts:
                if isinstance(part, dict) and part.get("text"):
                    texts.append(part["text"])
                elif isinstance(part, str):
                    texts.append(part)
        return " ".join(texts)

    def _extract_ad_urls(self, messages: List[Dict[str, Any]]) -> Set[str]:
        """Extrai URLs de anuncios das mensagens."""
        urls = set()

        for msg in messages:
            # So procurar em mensagens do lead (user)
            if msg.get("role") != "user":
                continue

            parts = msg.get("parts", [])
            for part in parts:
                text = ""
                if isinstance(part, dict):
                    text = part.get("text", "")
                elif isinstance(part, str):
                    text = part

                for pattern in AD_URL_PATTERNS:
                    matches = re.findall(pattern, text, re.IGNORECASE)
                    urls.update(matches)

        return urls

    def _infer_origin(self, urls: Set[str]) -> str:
        """Infere origem baseado nas URLs encontradas."""
        url_text = " ".join(urls).lower()

        if "fb.me" in url_text or "facebook" in url_text:
            return "facebook_ads"
        elif "instagram" in url_text or "ig.me" in url_text:
            return "instagram"
        elif "gclid" in url_text or "google" in url_text:
            return "google_ads"
        elif "utm_source" in url_text:
            return "campaign"

        return "unknown"


# ============================================================================
# SINGLETON
# ============================================================================

_observer_service: Optional[ObserverService] = None


def get_observer_service() -> ObserverService:
    """Retorna instancia singleton do ObserverService."""
    global _observer_service
    if _observer_service is None:
        _observer_service = ObserverService()
    return _observer_service


async def analyze_conversation(
    table_leads: str,
    table_messages: str,
    lead_id: int,
    remotejid: str,
    tools_used: Optional[List[str]] = None,
    agent_id: Optional[str] = None,
    queue_ia: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Wrapper para analisar conversa.

    Chamada simplificada para uso no webhook.

    Args:
        table_leads: Nome da tabela de leads
        table_messages: Nome da tabela de mensagens
        lead_id: ID do lead
        remotejid: WhatsApp ID do lead
        tools_used: Lista de tools usadas na ultima resposta
        agent_id: ID do agente (para buscar observer_prompt customizado)
        queue_ia: ID da fila da IA. Se fornecido, Observer so atua se lead
                  estiver nesta fila
    """
    service = get_observer_service()
    return await service.analyze(
        table_leads=table_leads,
        table_messages=table_messages,
        lead_id=lead_id,
        remotejid=remotejid,
        tools_used=tools_used,
        agent_id=agent_id,
        queue_ia=queue_ia,
    )
