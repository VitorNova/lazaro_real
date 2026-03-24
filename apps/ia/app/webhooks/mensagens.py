# ╔════════════════════════════════════════════════════════════╗
# ║  WEBHOOK MENSAGENS — Recebe msgs do WhatsApp (NUCLEO)      ║
# ╚════════════════════════════════════════════════════════════╝
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

# Models extraídos (Fase 2.1)
from app.domain.messaging.models import ExtractedMessage, ProcessingContext

# Context modules extraídos (Fase 2.2, 2.3, 2.4) - usados em vez das funções locais
from app.domain.messaging.context import context_detector
from app.domain.messaging.context import billing_context
from app.domain.messaging.context import maintenance_context

# Tool handlers extraídos (Fase A) - substitui _create_function_handlers inline
from app.ai.tools.tool_registry import get_function_handlers

# Message processor extraído (Fase B) - substitui _process_buffered_messages inline
from app.domain.messaging.services.message_processor import (
    process_buffered_messages as extracted_process_buffered_messages,
)

# Security (Fase 5)
from app.core.security.injection_guard import validate_user_input

# Handlers extraídos (Fase E.2) - substitui _extract_message_data e _handle_control_command
from app.domain.messaging.handlers.incoming_message_handler import (
    extract_message_data as extracted_extract_message_data,
    handle_control_command as extracted_handle_control_command,
)

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
        # Fase E.2: Delegar ao módulo extraído
        return extracted_extract_message_data(webhook_data)

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
        # Fase E.2: Delegar ao módulo extraído
        supabase = self._get_supabase()
        redis = await self._get_redis()
        return await extracted_handle_control_command(
            supabase=supabase,
            redis=redis,
            phone=phone,
            remotejid=remotejid,
            command=command,
            agent_id=agent_id,
            table_leads=table_leads,
            table_messages=table_messages,
        )

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

        Fase B: Wrapper thin que delega ao módulo extraído
        domain/messaging/services/message_processor.py

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

        # Fase B: Delegar ao módulo extraído
        await extracted_process_buffered_messages(
            agent_id=agent_id,
            phone=phone,
            remotejid=remotejid,
            context=context,
            redis=redis,
            supabase=supabase,
            gemini=gemini,
            uazapi=uazapi,
            save_history_callback=self._save_conversation_history,
            queue_failed_send_callback=self._queue_failed_send,
        )

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

            # ============================================================
            # CONSTRUIR SET DE FILAS IA (principal + dispatch)
            # Usado para verificações de race condition
            # ============================================================
            handoff = agent.get("handoff_triggers") or {}
            queue_ia_local = int(handoff.get("queue_ia", 537))
            dispatch_depts = handoff.get("dispatch_departments") or {}
            ia_queues_local = {queue_ia_local}
            if dispatch_depts.get("billing"):
                try:
                    ia_queues_local.add(int(dispatch_depts["billing"]["queueId"]))
                except (ValueError, TypeError, KeyError):
                    pass
            if dispatch_depts.get("manutencao"):
                try:
                    ia_queues_local.add(int(dispatch_depts["manutencao"]["queueId"]))
                except (ValueError, TypeError, KeyError):
                    pass

            # Se ja esta pausado, verificar se deve ignorar
            # FIX 14/03/2026: Race condition - verificar fila antes de ignorar
            if lead.get("Atendimento_Finalizado") == "true":
                try:
                    queue_check = int(lead.get("current_queue_id")) if lead.get("current_queue_id") else None
                except (ValueError, TypeError):
                    queue_check = None

                if queue_check is not None and queue_check in ia_queues_local:
                    logger.debug(f"[HUMAN TAKEOVER] Atendimento_Finalizado ignorado para {phone} - fila IA {queue_check} (race condition fix)")
                    # NÃO retorna - continua processamento
                else:
                    logger.debug(f"[HUMAN TAKEOVER] Lead {phone} ja pausado")
                    return {"status": "ignored", "reason": "already_paused"}

            # ============================================================
            # IGNORAR HUMAN TAKEOVER EM FILAS DE DISPARO (IA COBRANCAS/MANUTENCAO)
            # Mensagens enviadas pela API de disparo chegam com fromMe=True
            # mas não devem pausar a IA - são disparos automáticos
            # ============================================================
            dispatch_queues = ia_queues_local - {queue_ia_local}  # Apenas filas de dispatch (sem a principal)

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

        # LOG INFO: Mensagem recebida (visível em produção)
        media_info = f", media={media_type}" if media_type else ""
        logger.info(f"[MSG RECEBIDA] phone={phone}, texto='{text[:50]}...'{media_info}")

        # DEBUG detalhado (só em desenvolvimento)
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
            logger.warning(f"[MSG RECEBIDA] AGENTE NAO ENCONTRADO - instance_id={instance_id}, phone={phone}")
            logger.debug(f"[DEBUG 2/6] AGENTE NAO ENCONTRADO para instance_id: {instance_id} ou token")
            return {"status": "error", "reason": "agent_not_found"}

        # Verificar se agente esta ativo (defesa em profundidade alem do filtro no Supabase)
        if not agent.get("active", True):
            logger.info(f"[AGENT DISABLED] Agente '{agent.get('name')}' ({agent.get('id')}) esta inativo (active=false) - ignorando mensagem")
            return {"status": "ignored", "reason": "agent_inactive"}

        if agent.get("status") == "paused":
            logger.info(f"[AGENT DISABLED] Agente '{agent.get('name')}' ({agent.get('id')}) esta pausado (status=paused) - ignorando mensagem")
            return {"status": "ignored", "reason": "agent_paused"}

        # LOG INFO: Agente encontrado
        logger.info(f"[MSG RECEBIDA] Agente '{agent.get('name')}' encontrado para phone={phone}")

        logger.debug(f"[DEBUG 2/6] AGENTE ENCONTRADO:")
        logger.debug(f"  -> Agent ID: {agent.get('id', 'N/A')}")
        logger.debug(f"  -> Agent Name: {agent.get('name', 'N/A')}")

        agent_id = agent["id"]
        table_leads = agent.get("table_leads") or f"LeadboxCRM_{agent_id[:8]}"
        table_messages = agent.get("table_messages") or f"leadbox_messages_{agent_id[:8]}"

        # Obter system prompt e substituir variáveis dinâmicas
        raw_system_prompt = agent.get("system_prompt") or "Voce e um assistente virtual prestativo."
        agent_timezone = agent.get("timezone") or "America/Cuiaba"
        system_prompt = context_detector.prepare_system_prompt(raw_system_prompt, agent_timezone)

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

            # ============================================================
            # PROTEÇÃO: Não reatribuir se lead já está em fila de dispatch
            # Fix: billing routing - leads de cobrança devem permanecer na fila 544
            # ============================================================
            dispatch_queues = set()
            dispatch_depts = handoff_config.get("dispatch_departments") or {}
            for dept_config in dispatch_depts.values():
                q = dept_config.get("queueId")
                if q:
                    try:
                        dispatch_queues.add(int(q))
                    except (ValueError, TypeError):
                        pass

            existing_queue = lead.get("current_queue_id")
            skip_auto_assign = False
            if existing_queue:
                try:
                    if int(existing_queue) in dispatch_queues:
                        logger.info(f"[AUTO ASSIGN] Lead {phone} já em fila dispatch {existing_queue}, mantendo")
                        skip_auto_assign = True
                except (ValueError, TypeError):
                    pass

            if handoff_config.get("enabled") and queue_ia and queue_ia_user_id and not skip_auto_assign:
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

                # Construir set de filas IA para verificações
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

                # Verificar se humano assumiu durante o delay
                # FIX 14/03/2026: Race condition - verificar fila antes de ignorar
                if lead.get("Atendimento_Finalizado") == "true":
                    try:
                        queue_check = int(lead.get("current_queue_id")) if lead.get("current_queue_id") else None
                    except (ValueError, TypeError):
                        queue_check = None

                    if queue_check is not None and queue_check in ia_queues_check:
                        logger.info(f"[NEW LEAD] Atendimento_Finalizado ignorado para {phone} - fila IA {queue_check} (race condition fix)")
                        # NÃO retorna - continua processamento
                    else:
                        logger.info(f"[NEW LEAD] Lead {phone} marcado como pausado durante sync - ignorando (humano assumiu)")
                        return {"status": "ignored", "reason": "new_lead_human_took_over"}

                # Verificar se foi para fila humana durante o delay

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
                logger.info(f"[FILA CHECK] Lead {phone[-4:]} — banco diz queue={current_queue}, aguardando 3s para re-check")
                await asyncio.sleep(3)
                fresh_lead = supabase.get_lead_by_remotejid(table_leads, remotejid)
                if fresh_lead:
                    fresh_queue_raw = fresh_lead.get("current_queue_id")
                    try:
                        fresh_queue = int(fresh_queue_raw) if fresh_queue_raw else None
                    except (ValueError, TypeError):
                        fresh_queue = None
                    logger.info(f"[FILA RECHECK] Lead {phone[-4:]} — após 3s: queue={fresh_queue} (mudou={current_queue != fresh_queue})")
                    if fresh_queue is not None and fresh_queue not in IA_QUEUES:
                        # ================================================================
                        # FAIL-SAFE: Consultar API do Leadbox antes de ignorar
                        # O banco pode estar desatualizado se webhook não chegou
                        # ================================================================
                        lb_api_url = handoff.get("api_url")
                        lb_api_token = handoff.get("api_token")

                        if lb_api_url and lb_api_token:
                            logger.info(f"[FILA API] Lead {phone[-4:]} — consultando Leadbox (banco inconsistente após 3s)")
                            try:
                                ticket_id_for_check = fresh_lead.get("ticket_id")
                                try:
                                    ticket_id_int = int(ticket_id_for_check) if ticket_id_for_check else None
                                except (ValueError, TypeError):
                                    ticket_id_int = None

                                realtime_result = await get_current_queue(
                                    api_url=lb_api_url,
                                    api_token=lb_api_token,
                                    phone=phone,
                                    ticket_id=ticket_id_int,
                                    ia_queue_id=QUEUE_IA,
                                )

                                if realtime_result:
                                    realtime_queue = realtime_result.get("queue_id")
                                    if realtime_queue and int(realtime_queue) in IA_QUEUES:
                                        # API diz que está em fila IA! Banco desatualizado.
                                        logger.warning(
                                            f"[FILA CORRIGIDA] Lead {phone[-4:]} — banco dizia queue={fresh_queue}, API diz queue={realtime_queue} — CORRIGINDO e processando"
                                        )
                                        # Atualizar banco com dados reais da API
                                        new_ticket_id = realtime_result.get("ticket_id")
                                        supabase.update_lead_by_remotejid(table_leads, remotejid, {
                                            "current_queue_id": str(realtime_queue),
                                            "ticket_id": str(new_ticket_id) if new_ticket_id else fresh_lead.get("ticket_id"),
                                            "Atendimento_Finalizado": "false",
                                            "current_state": "ai",
                                        })
                                        # Atualizar lead local para continuar processamento
                                        fresh_lead["current_queue_id"] = realtime_queue
                                        lead = fresh_lead
                                        # NÃO retorna - continua processamento normal
                                    else:
                                        # API confirma que está em fila não-IA - ignorar
                                        logger.warning(
                                            f"[FILA CONFIRMADA HUMANA] Lead {phone[-4:]} — API confirma queue={realtime_queue} — IGNORANDO"
                                        )
                                        return {"status": "ignored", "reason": "lead_em_outra_fila_confirmado_api"}
                                else:
                                    # API não retornou dados - usar comportamento anterior (ignorar)
                                    logger.warning(
                                        "[LEADBOX] Lead %s na fila %s - API Leadbox sem dados, IGNORANDO",
                                        phone, fresh_queue
                                    )
                                    return {"status": "ignored", "reason": "lead_em_outra_fila"}
                            except Exception as api_err:
                                # Erro na API - comportamento fail-safe: ignorar
                                logger.warning(
                                    f"[FILA API ERRO] Lead {phone[-4:]} — API Leadbox falhou: {api_err} — IGNORANDO por segurança"
                                )
                                return {"status": "ignored", "reason": "lead_em_outra_fila"}
                        else:
                            # Sem credenciais Leadbox - comportamento anterior
                            logger.warning(
                                "[LEADBOX] Lead %s na fila %s - sem credenciais Leadbox, IGNORANDO",
                                phone, fresh_queue
                            )
                            return {"status": "ignored", "reason": "lead_em_outra_fila"}
                    else:
                        logger.debug(f"[LEADBOX] Lead {phone} mudou para fila {fresh_queue} (pré-agendamento recheck) - OK, processando")
                        lead = fresh_lead
                else:
                    logger.warning(f"[LEADBOX] Lead {phone} não encontrado no recheck - IGNORANDO")
                    return {"status": "ignored", "reason": "lead_nao_encontrado_recheck"}
            elif current_queue in IA_QUEUES:
                logger.debug(f"[LEADBOX] Lead {phone} na fila {current_queue} (pré-agendamento) - OK, processando (filas IA: {IA_QUEUES})")
        else:
            logger.debug(f"[LEADBOX] Lead {phone} sem current_queue_id (pré-agendamento) - prosseguindo")

        # ====================================================================
        # VERIFICAR SE ATENDIMENTO FOI FINALIZADO (transferido para humano)
        # Se Atendimento_Finalizado == "true", a IA deve ficar PAUSADA
        # FIX 14/03/2026: Race condition - verificar fila antes de ignorar
        # ====================================================================
        atendimento_finalizado = lead.get("Atendimento_Finalizado", "")
        if atendimento_finalizado == "true":
            # FIX: race condition - se lead está em fila IA, ignorar Atendimento_Finalizado stale
            try:
                queue_check = int(lead.get("current_queue_id")) if lead.get("current_queue_id") else None
            except (ValueError, TypeError):
                queue_check = None

            if queue_check is not None and queue_check in IA_QUEUES:
                logger.info(f"Atendimento_Finalizado ignorado para {phone} - lead em fila IA {queue_check} (race condition fix)")
                # NÃO retorna - continua processamento
            else:
                logger.info(f"Atendimento finalizado para {phone} (transferido para humano), IA pausada")
                logger.debug(f"[DEBUG] ATENDIMENTO FINALIZADO para {phone} - IA pausada, ignorando mensagem")
                return {"status": "ignored", "reason": "atendimento_finalizado"}

        # Verificar se bot esta pausado
        redis = await self._get_redis()
        is_paused = await redis.pause_is_paused(agent_id, phone)

        # Tambem verificar no Supabase
        if not is_paused:
            is_paused = supabase.is_lead_paused(table_leads, remotejid)

        # FIX 09/03/2026 - Bug Batistella: race condition com leadbox_handler
        # Se lead está em fila de IA, ignorar pausa (pode ser estado stale)
        # A fila de IA é a "fonte de verdade" sobre quem deve atender
        if is_paused:
            # current_queue já foi definida na verificação de fila (linha ~1220)
            try:
                queue_check = int(lead.get("current_queue_id")) if lead.get("current_queue_id") else None
            except (ValueError, TypeError):
                queue_check = None

            if queue_check is not None and queue_check in IA_QUEUES:
                logger.info(f"[RACE FIX] Lead {phone[-4:]} — pausa ignorada pois banco mostra fila IA queue={queue_check}")
                is_paused = False

        if is_paused:
            logger.info(f"Bot pausado para {phone}, mensagem ignorada")
            return {"status": "ignored", "reason": "bot_paused"}

        # ====================================================================
        # VERIFICAÇÃO EXTRA: Ticket ativo com atendente humano em fila não-IA
        # Defesa em profundidade: mesmo que is_lead_paused tenha passado,
        # verificar se ticket está em fila de atendimento humano
        # ====================================================================
        ticket_id = lead.get("ticket_id")
        current_user_id = lead.get("current_user_id")
        if ticket_id and current_user_id:
            lead_queue_id = lead.get("current_queue_id")
            # IA_QUEUES já foi definido na verificação de fila do Leadbox (linha ~1196)
            if lead_queue_id:
                try:
                    lead_queue_int = int(lead_queue_id)
                    if lead_queue_int not in IA_QUEUES:
                        logger.info(
                            f"[TICKET CHECK] Lead {phone} tem ticket ativo "
                            f"(ticket_id={ticket_id}, queue={lead_queue_id}) "
                            f"fora das filas IA {IA_QUEUES} - ignorando"
                        )
                        return {"status": "ignored", "reason": "ticket_active_human"}
                except (ValueError, TypeError):
                    # Se não conseguir converter queue_id, assume que está com humano
                    logger.warning(
                        f"[TICKET CHECK] Lead {phone} tem ticket ativo "
                        f"(ticket_id={ticket_id}) com queue_id inválido ({lead_queue_id}) - ignorando"
                    )
                    return {"status": "ignored", "reason": "ticket_active_invalid_queue"}

        # DEBUG 3: Adicionando ao buffer
        logger.debug(f"[DEBUG 3/6] ADICIONANDO AO BUFFER:")
        logger.debug(f"  -> Agent ID: {agent_id}")
        logger.debug(f"  -> Phone: {phone}")
        logger.debug(f"  -> Texto: {text[:50]}...")

        # Log de diagnóstico: estado exato do lead ao entrar no processamento
        logger.info(
            f"[IA PROCESSANDO] Lead {phone[-4:]} — queue={lead.get('current_queue_id')} "
            f"| state={lead.get('current_state')} | ticket={lead.get('ticket_id')} "
            f"| user={lead.get('current_user_id')} — aprovado para Gemini"
        )

        # Adicionar ao buffer
        await redis.buffer_add_message(agent_id, phone, text)
        logger.info(f"[BUFFER] Mensagem adicionada - phone={phone}, agent={agent.get('name')}")
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
        if media_type and (media_type.lower().startswith("image") or media_type.lower().startswith("document") or media_type in ["image", "imageMessage", "document", "documentMessage"]):
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
