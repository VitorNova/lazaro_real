# app/webhooks/whatsapp.py - Backup Completo
## Gerado em: 2026-01-27

```python
"""
WhatsApp Webhook Handler - Processamento de mensagens do WhatsApp via UAZAPI.

Fluxo de processamento:
1. Webhook recebe mensagem do UAZAPI
2. Valida (nao grupo, nao from_me)
3. Verifica comandos de controle (/p, /a, /r)
4. Verifica se bot esta pausado para o lead
5. Adiciona mensagem ao buffer Redis
6. Agenda processamento apos 14 segundos
7. Busca historico de conversa no Supabase
8. Envia para Gemini processar
9. Envia resposta via UAZAPI
10. Salva historico atualizado no Supabase
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, TypedDict

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response

from app.config import settings
from app.services.gemini import GeminiService, get_gemini_service
from app.services.redis import BUFFER_DELAY_SECONDS, RedisService, get_redis_service
from app.services.supabase import SupabaseService, get_supabase_service, ConversationHistory
from app.services.uazapi import UazapiService, get_uazapi_service
from app.tools.functions import FUNCTION_DECLARATIONS, FunctionHandlers

logger = logging.getLogger(__name__)


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
    token: Optional[str]


class ProcessingContext(TypedDict):
    """Contexto para processamento de mensagens."""
    agent_id: str
    remotejid: str
    phone: str
    table_leads: str
    table_messages: str
    system_prompt: str
    uazapi_token: Optional[str]
    uazapi_base_url: Optional[str]
    handoff_triggers: Optional[Dict[str, Any]]


class WhatsAppWebhookHandler:
    """Handler para processamento de mensagens do webhook WhatsApp."""

    buffer_delay: int = BUFFER_DELAY_SECONDS
    _scheduled_tasks: Dict[str, asyncio.Task] = {}

    def __init__(
        self,
        redis_service: Optional[RedisService] = None,
        supabase_service: Optional[SupabaseService] = None,
        gemini_service: Optional[GeminiService] = None,
        uazapi_service: Optional[UazapiService] = None,
    ):
        self._redis = redis_service
        self._supabase = supabase_service
        self._gemini = gemini_service
        self._uazapi = uazapi_service

    async def _get_redis(self) -> RedisService:
        if self._redis is None:
            self._redis = await get_redis_service(settings.redis_url)
        return self._redis

    def _get_supabase(self) -> SupabaseService:
        if self._supabase is None:
            self._supabase = get_supabase_service()
        return self._supabase

    def _get_gemini(self) -> GeminiService:
        if self._gemini is None:
            self._gemini = get_gemini_service()
        return self._gemini

    def _get_uazapi(self) -> UazapiService:
        if self._uazapi is None:
            self._uazapi = get_uazapi_service()
        return self._uazapi

    def _extract_message_data(self, webhook_data: Dict[str, Any]) -> Optional[ExtractedMessage]:
        """Extrai dados relevantes da mensagem do webhook."""
        try:
            # FORMATO UAZAPI (EventType: messages)
            if webhook_data.get("EventType") == "messages" and webhook_data.get("message"):
                msg = webhook_data.get("message", {})

                if msg.get("wasSentByApi", False):
                    return None

                remotejid = msg.get("chatid", "") or msg.get("sender_pn", "")
                if not remotejid:
                    return None

                is_group = msg.get("isGroup", False) or "@g.us" in remotejid
                from_me = msg.get("fromMe", False)
                phone = remotejid.replace("@s.whatsapp.net", "").replace("@lid", "").replace("@c.us", "")
                text = msg.get("text", "") or msg.get("content", "")

                if not text:
                    media_type = msg.get("mediaType") or msg.get("messageType", "")
                    if media_type:
                        text = f"[{media_type} recebido]"
                    else:
                        return None

                message_id = msg.get("messageid", "")
                timestamp = msg.get("messageTimestamp", datetime.utcnow().timestamp() * 1000)
                push_name = msg.get("senderName", "")
                instance_id = webhook_data.get("instanceName", "")
                token = webhook_data.get("token", "")

                if isinstance(timestamp, (int, float)):
                    if timestamp > 9999999999:
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
                )

            # FORMATO EVOLUTION API
            data = webhook_data.get("data", webhook_data)
            message = data.get("message", {})
            key = data.get("key", message.get("key", {}))
            remotejid = key.get("remoteJid", "")
            is_group = "@g.us" in remotejid
            from_me = key.get("fromMe", False)
            phone = remotejid.replace("@s.whatsapp.net", "").replace("@lid", "")
            text = self._extract_text_from_message(message)

            if not text:
                return None

            return ExtractedMessage(
                phone=phone,
                remotejid=remotejid,
                text=text.strip(),
                is_group=is_group,
                from_me=from_me,
                message_id=key.get("id"),
                timestamp=data.get("messageTimestamp", datetime.utcnow().isoformat()),
                push_name=data.get("pushName"),
                instance_id=webhook_data.get("instanceId"),
            )

        except Exception as e:
            logger.error(f"Erro ao extrair dados da mensagem: {e}")
            return None

    def _extract_text_from_message(self, message: Dict[str, Any]) -> str:
        """Extrai texto de diferentes tipos de mensagem."""
        if "conversation" in message:
            return message["conversation"]
        if "extendedTextMessage" in message:
            return message["extendedTextMessage"].get("text", "")
        if "imageMessage" in message:
            return message["imageMessage"].get("caption", "[Imagem recebida]")
        if "videoMessage" in message:
            return message["videoMessage"].get("caption", "[Video recebido]")
        if "documentMessage" in message:
            return message["documentMessage"].get("caption", "[Documento recebido]")
        if "audioMessage" in message:
            return "[Audio recebido]"
        if "stickerMessage" in message:
            return "[Sticker recebido]"
        if "message" in message:
            return self._extract_text_from_message(message["message"])
        return ""

    async def _handle_control_command(
        self,
        phone: str,
        remotejid: str,
        command: str,
        agent_id: str,
        table_leads: str,
        table_messages: str,
    ) -> Optional[str]:
        """Processa comandos de controle (/p, /a, /r)."""
        cmd = command.lower().strip()
        supabase = self._get_supabase()
        redis = await self._get_redis()

        if cmd in ["/p", "/pausar", "/pause"]:
            supabase.set_lead_paused(table_leads, remotejid, paused=True, reason="Comando /p")
            await redis.pause_set(agent_id, phone)
            return "Bot pausado. Envie /a para reativar."

        if cmd in ["/a", "/ativar", "/activate"]:
            supabase.set_lead_paused(table_leads, remotejid, paused=False)
            await redis.pause_clear(agent_id, phone)
            return "Bot reativado!"

        if cmd in ["/r", "/reset", "/reiniciar", "/restart", "/rr"]:
            supabase.clear_conversation_history(table_messages, remotejid)
            await redis.buffer_clear(agent_id, phone)
            return "Historico limpo. Podemos comecar uma nova conversa!"

        return None

    async def _schedule_processing(
        self,
        agent_id: str,
        phone: str,
        remotejid: str,
        context: ProcessingContext,
    ) -> None:
        """Agenda processamento das mensagens apos o delay do buffer."""
        task_key = f"{agent_id}:{phone}"

        if task_key in self._scheduled_tasks:
            old_task = self._scheduled_tasks[task_key]
            if not old_task.done():
                old_task.cancel()

        async def delayed_process():
            try:
                await asyncio.sleep(self.buffer_delay)
                await self._process_buffered_messages(agent_id, phone, remotejid, context)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"Erro no processamento: {e}")
            finally:
                if task_key in self._scheduled_tasks:
                    del self._scheduled_tasks[task_key]

        task = asyncio.create_task(delayed_process())
        self._scheduled_tasks[task_key] = task

    async def _process_buffered_messages(
        self,
        agent_id: str,
        phone: str,
        remotejid: str,
        context: ProcessingContext,
    ) -> None:
        """Processa todas as mensagens acumuladas no buffer."""
        redis = await self._get_redis()
        supabase = self._get_supabase()
        gemini = self._get_gemini()

        agent_uazapi_token = context.get("uazapi_token")
        agent_uazapi_base_url = context.get("uazapi_base_url")

        if agent_uazapi_token and agent_uazapi_base_url:
            uazapi = UazapiService(base_url=agent_uazapi_base_url, api_key=agent_uazapi_token)
        else:
            uazapi = self._get_uazapi()

        lock_acquired = await redis.lock_acquire(agent_id, phone)
        if not lock_acquired:
            return

        try:
            is_paused = await redis.pause_is_paused(agent_id, phone)
            if is_paused:
                await redis.buffer_clear(agent_id, phone)
                return

            messages = await redis.buffer_get_and_clear(agent_id, phone)
            if not messages:
                return

            combined_text = "\n".join(messages)
            await uazapi.send_typing(phone, duration=5000)

            history = supabase.get_conversation_history(context["table_messages"], remotejid)
            gemini_messages = self._prepare_gemini_messages(history, combined_text)

            if not gemini.is_initialized:
                gemini.initialize(
                    function_declarations=FUNCTION_DECLARATIONS,
                    system_instruction=context["system_prompt"],
                )

            handlers = self._create_function_handlers(context)
            gemini.register_tool_handlers(handlers)

            response = await gemini.send_message(
                messages=gemini_messages,
                system_prompt=context["system_prompt"],
            )

            response_text = response.get("text", "") or "Desculpe, nao consegui processar."
            response_parts = self._split_response(response_text)

            for i, part in enumerate(response_parts):
                if i > 0:
                    await asyncio.sleep(1)
                    await uazapi.send_typing(phone, duration=2000)
                await uazapi.send_text_message(phone, part)

            self._save_conversation_history(
                supabase, context["table_messages"], remotejid,
                combined_text, response_text, history
            )

            supabase.update_lead_by_remotejid(
                context["table_leads"], remotejid,
                {"ultimo_intent": combined_text[:200]}
            )

        except Exception as e:
            logger.error(f"Erro ao processar: {e}", exc_info=True)
            try:
                await uazapi.send_text_message(phone, "Desculpe, ocorreu um erro.")
            except Exception:
                pass

        finally:
            await redis.lock_release(agent_id, phone)

    def _prepare_gemini_messages(self, history: Optional[ConversationHistory], new_message: str) -> List[Dict[str, Any]]:
        messages = []
        if history and history.get("messages"):
            max_history = settings.max_conversation_history
            limited = history["messages"][-max_history:]
            for msg in limited:
                messages.append({"role": msg.get("role", "user"), "parts": msg.get("parts", [{"text": ""}])})
        messages.append({"role": "user", "parts": [{"text": new_message}]})
        return messages

    def _save_conversation_history(self, supabase, table_messages, remotejid, user_message, assistant_message, history):
        now = datetime.utcnow().isoformat()
        if history is None:
            history = {"messages": []}
        history["messages"].append({"role": "user", "parts": [{"text": user_message}], "timestamp": now})
        history["messages"].append({"role": "model", "parts": [{"text": assistant_message}], "timestamp": now})
        supabase.upsert_conversation_history(table_messages, remotejid, history, last_message_role="model")

    def _split_response(self, text: str, max_length: int = 4000) -> List[str]:
        if len(text) <= max_length:
            return [text]
        parts = []
        remaining = text
        while remaining:
            if len(remaining) <= max_length:
                parts.append(remaining)
                break
            chunk = remaining[:max_length]
            break_point = chunk.rfind("\n\n")
            if break_point == -1:
                break_point = chunk.rfind("\n")
            if break_point == -1:
                break_point = chunk.rfind(". ")
            if break_point == -1:
                break_point = max_length
            parts.append(remaining[:break_point + 1].strip())
            remaining = remaining[break_point + 1:].strip()
        return parts

    def _create_function_handlers(self, context: ProcessingContext) -> Dict[str, Any]:
        """Cria dicionario de handlers para as tools."""
        from app.services.leadbox import LeadboxService
        supabase = self._get_supabase()

        async def placeholder_handler(**kwargs):
            return {"sucesso": False, "mensagem": "Funcionalidade em desenvolvimento"}

        async def transferir_departamento_handler(
            departamento: str = None,
            motivo: str = None,
            observacoes: str = None,
            queue_id: int = None,
            user_id: int = None,
            **kwargs
        ):
            try:
                if queue_id is not None:
                    queue_id = int(queue_id)
                if user_id is not None:
                    user_id = int(user_id)

                handoff_config = context.get("handoff_triggers")
                if not handoff_config or not handoff_config.get("enabled", True):
                    return {"sucesso": False, "mensagem": "Transferencia nao configurada"}

                api_url = handoff_config.get("api_url")
                api_uuid = handoff_config.get("api_uuid")
                api_token = handoff_config.get("api_token")
                departments = handoff_config.get("departments", {})

                if not api_url or not api_uuid or not api_token:
                    return {"sucesso": False, "mensagem": "Configuracao Leadbox incompleta"}

                final_queue_id = queue_id
                final_user_id = user_id

                if departamento and not queue_id:
                    dept_config = departments.get(departamento.lower())
                    if dept_config:
                        final_queue_id = int(dept_config.get("id") or dept_config.get("queue_id") or 0) or None
                        final_user_id = int(dept_config.get("userId") or dept_config.get("user_id") or 0) or None
                    else:
                        return {"sucesso": False, "mensagem": f"Departamento '{departamento}' nao configurado"}

                if final_queue_id and not final_user_id:
                    for dept_name, dept_config in departments.items():
                        if int(dept_config.get("id") or dept_config.get("queue_id") or 0) == final_queue_id:
                            final_user_id = int(dept_config.get("userId") or dept_config.get("user_id") or 0) or None
                            break

                if not final_queue_id:
                    return {"sucesso": False, "mensagem": "queue_id nao informado"}

                leadbox = LeadboxService(base_url=api_url, api_uuid=api_uuid, api_key=api_token)
                transfer_notes = motivo or "Transferindo atendimento..."
                if observacoes:
                    transfer_notes += f"\n\nObservacoes: {observacoes}"

                phone = context.get("phone")
                result = await leadbox.transfer_to_department(
                    phone=phone, queue_id=final_queue_id, user_id=final_user_id, notes=transfer_notes
                )

                if result["sucesso"]:
                    table_leads = context.get("table_leads")
                    remotejid = context.get("remotejid")
                    supabase.update_lead_by_remotejid(
                        table_leads, remotejid,
                        {"Atendimento_Finalizado": "true", "paused_at": datetime.utcnow().isoformat()}
                    )
                    return {
                        "sucesso": True,
                        "mensagem": "Entendi! Vou te transferir agora para um dos nossos especialistas. So um momento!"
                    }
                else:
                    return {"sucesso": False, "mensagem": "Erro ao transferir."}

            except Exception as e:
                logger.error(f"Erro ao transferir: {e}", exc_info=True)
                return {"sucesso": False, "mensagem": str(e)}

        return {
            "consulta_agenda": placeholder_handler,
            "agendar": placeholder_handler,
            "cancelar_agendamento": placeholder_handler,
            "reagendar": placeholder_handler,
            "transferir_departamento": transferir_departamento_handler,
        }

    async def handle_message(
        self,
        webhook_data: Dict[str, Any],
        background_tasks: Optional[BackgroundTasks] = None,
    ) -> Dict[str, Any]:
        """Processa mensagem recebida do webhook."""
        extracted = self._extract_message_data(webhook_data)

        if extracted is None:
            return {"status": "ignored", "reason": "invalid_message"}

        if extracted["is_group"]:
            return {"status": "ignored", "reason": "group_message"}

        if extracted["from_me"]:
            return {"status": "ignored", "reason": "from_me"}

        phone = extracted["phone"]
        remotejid = extracted["remotejid"]
        text = extracted["text"]
        instance_id = extracted["instance_id"]

        supabase = self._get_supabase()
        token = extracted.get("token", "")

        agent = None
        if instance_id:
            agent = supabase.get_agent_by_instance_id(instance_id)
        if not agent and token:
            agent = supabase.get_agent_by_token(token)

        if not agent:
            return {"status": "error", "reason": "agent_not_found"}

        agent_id = agent["id"]
        table_leads = agent.get("table_leads") or f"LeadboxCRM_{agent_id[:8]}"
        table_messages = agent.get("table_messages") or f"leadbox_messages_{agent_id[:8]}"
        system_prompt = agent.get("system_prompt") or "Voce e um assistente virtual."

        supabase.get_or_create_lead(
            table_leads, remotejid,
            default_data={"telefone": phone, "nome": extracted["push_name"]}
        )

        control_response = await self._handle_control_command(
            phone, remotejid, text, agent_id, table_leads, table_messages
        )

        if control_response:
            uazapi = self._get_uazapi()
            await uazapi.send_text_message(phone, control_response)
            return {"status": "ok", "action": "control_command"}

        redis = await self._get_redis()
        is_paused = await redis.pause_is_paused(agent_id, phone)
        if not is_paused:
            is_paused = supabase.is_lead_paused(table_leads, remotejid)

        if is_paused:
            return {"status": "ignored", "reason": "bot_paused"}

        await redis.buffer_add_message(agent_id, phone, text)

        context: ProcessingContext = {
            "agent_id": agent_id,
            "remotejid": remotejid,
            "phone": phone,
            "table_leads": table_leads,
            "table_messages": table_messages,
            "system_prompt": system_prompt,
            "uazapi_token": agent.get("uazapi_token"),
            "uazapi_base_url": agent.get("uazapi_base_url"),
            "handoff_triggers": agent.get("handoff_triggers"),
        }

        await self._schedule_processing(agent_id, phone, remotejid, context)
        return {"status": "ok", "action": "buffered"}


# FASTAPI ROUTER
router = APIRouter(prefix="/webhook", tags=["webhook"])
_webhook_handler: Optional[WhatsAppWebhookHandler] = None


def get_webhook_handler() -> WhatsAppWebhookHandler:
    global _webhook_handler
    if _webhook_handler is None:
        _webhook_handler = WhatsAppWebhookHandler()
    return _webhook_handler


@router.post("/whatsapp")
async def webhook_whatsapp_post(request: Request, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    try:
        body = await request.json()
        event_type = body.get("event") or body.get("type")
        if event_type and event_type not in ["messages.upsert", "message", "messages"]:
            return {"status": "ignored", "reason": f"event_type_{event_type}"}
        handler = get_webhook_handler()
        return await handler.handle_message(body, background_tasks)
    except Exception as e:
        logger.error(f"Erro no webhook: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@router.get("/whatsapp")
async def webhook_whatsapp_get() -> Dict[str, Any]:
    return {"status": "ok", "service": "agente-ia", "webhook": "whatsapp", "timestamp": datetime.utcnow().isoformat()}
```
