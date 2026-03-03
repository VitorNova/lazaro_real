"""
Lead intake service for Leadbox webhook processing.

This module handles:
- Capturing human operator messages into conversation history
- Processing incoming lead messages with AI
- Creating leads when webhook arrives before WhatsApp webhook (race condition)
- Injecting context messages when leads return from human queues
"""

from datetime import datetime
from typing import Any, Dict, Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)

# HTTP timeout for Leadbox API calls
HTTP_TIMEOUT_SECS = 10.0


async def capture_human_message(
    body: Dict[str, Any],
    ticket_id: str,
    tenant_id: str,
    msg_body: str
) -> None:
    """
    Capture human operator messages into conversation history.

    When a human operator sends a message (fromMe=true, not API-generated),
    we save it to the conversation history as role="model" so the AI
    is aware of what the human said.
    """
    from app.services.supabase import get_supabase_service

    logger.info("[LEAD INTAKE] Mensagem do HUMANO detectada - ticketId=%s", ticket_id)

    try:
        supabase_svc = get_supabase_service()

        # Buscar agente pelo tenant_id
        agents = supabase_svc.client.table("agents") \
            .select("id,name,table_messages,handoff_triggers,leadbox_config") \
            .eq("active", True) \
            .execute()

        target_agent = None
        for ag in (agents.data or []):
            ht = ag.get("handoff_triggers") or {}
            agent_tenant = ht.get("tenant_id")
            if tenant_id and agent_tenant and int(tenant_id) == int(agent_tenant):
                target_agent = ag
                break

        if target_agent:
            table_messages = target_agent.get("table_messages")
            leadbox_config = target_agent.get("leadbox_config") or {}
            lb_api_url = leadbox_config.get("api_url", "")
            lb_api_token = leadbox_config.get("api_token", "")

            if table_messages and lb_api_url and lb_api_token:
                # Buscar telefone do lead via API do ticket
                async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECS) as client:
                    headers = {
                        "Authorization": f"Bearer {lb_api_token}",
                        "Content-Type": "application/json",
                    }
                    resp = await client.put(
                        f"{lb_api_url}/tickets/{ticket_id}",
                        headers=headers,
                        json={},
                    )

                    if resp.status_code == 200:
                        ticket_data = resp.json()
                        contact_data = ticket_data.get("contact") or {}
                        lead_phone = contact_data.get("number", "").replace("+", "").strip()

                        if lead_phone:
                            remotejid = f"{lead_phone}@s.whatsapp.net"

                            # Salvar mensagem do humano no histórico como "model"
                            supabase_svc.add_message_to_history(
                                table_name=table_messages,
                                remotejid=remotejid,
                                role="model",  # Humano = model (resposta)
                                text=msg_body
                            )

                            logger.info(
                                "[LEAD INTAKE] Mensagem do HUMANO salva no histórico | lead=%s | msg=%s",
                                lead_phone, msg_body[:50]
                            )
                        else:
                            logger.warning("[LEAD INTAKE] Ticket %s sem telefone", ticket_id)
                    else:
                        logger.warning("[LEAD INTAKE] Erro ao buscar ticket: %s", resp.status_code)
            else:
                logger.warning("[LEAD INTAKE] Agente sem table_messages ou credenciais Leadbox")
        else:
            logger.debug("[LEAD INTAKE] Mensagem do humano - agente não encontrado para tenant=%s", tenant_id)

    except Exception as e:
        logger.error("[LEAD INTAKE] Erro ao salvar mensagem do humano: %s", e, exc_info=True)


async def process_lead_message(
    body: Dict[str, Any],
    background_tasks,
    ticket_id: str,
    tenant_id: str,
    msg_body: str,
    message_data: Dict[str, Any],
    media_type: str
) -> None:
    """
    Process incoming lead messages with AI.

    Converts Leadbox webhook payload to UAZAPI format and dispatches
    to the message handler for AI processing.
    """
    from app.services.supabase import get_supabase_service
    from app.webhooks.mensagens import get_webhook_handler

    logger.info("[LEAD INTAKE] Nova mensagem recebida - ticketId=%s, tenant=%s", ticket_id, tenant_id)

    try:
        supabase_svc = get_supabase_service()

        agents = supabase_svc.client.table("agents") \
            .select("id,name,uazapi_base_url,uazapi_token,handoff_triggers,leadbox_config") \
            .eq("active", True) \
            .execute()

        target_agent = None
        for ag in (agents.data or []):
            ht = ag.get("handoff_triggers") or {}
            agent_tenant = ht.get("tenant_id")
            if tenant_id and agent_tenant and int(tenant_id) == int(agent_tenant):
                target_agent = ag
                break

        if not target_agent:
            logger.warning("[LEAD INTAKE] Nenhum agente encontrado para tenant_id=%s", tenant_id)
            return

        # Extrair credenciais Leadbox do leadbox_config
        leadbox_config = target_agent.get("leadbox_config") or {}
        lb_api_url = leadbox_config.get("api_url", "")
        lb_api_token = leadbox_config.get("api_token", "")

        if not lb_api_url or not lb_api_token:
            logger.warning("[LEAD INTAKE] Agente %s sem credenciais Leadbox configuradas", target_agent.get("name"))
            return

        # Buscar dados do ticket via API para obter telefone do contato
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECS) as client:
            headers = {
                "Authorization": f"Bearer {lb_api_token}",
                "Content-Type": "application/json",
            }
            resp = await client.put(
                f"{lb_api_url}/tickets/{ticket_id}",
                headers=headers,
                json={},
            )

            if resp.status_code == 200:
                ticket_data = resp.json()
                contact_data = ticket_data.get("contact") or {}
                lead_phone = contact_data.get("number", "").replace("+", "").strip()
                lead_name = contact_data.get("name", "")

                if lead_phone:
                    logger.info("[LEAD INTAKE] Processando mensagem do lead %s: %s", lead_phone, msg_body[:50])

                    # Construir payload no formato UAZAPI para o handler
                    uazapi_payload = {
                        "EventType": "messages",
                        "instanceName": target_agent.get("name", ""),
                        "token": target_agent.get("uazapi_token", ""),
                        "message": {
                            "chatid": f"{lead_phone}@s.whatsapp.net",
                            "text": msg_body,
                            "fromMe": False,
                            "wasSentByApi": False,
                            "isGroup": False,
                            "messageid": message_data.get("messageId", ""),
                            "messageTimestamp": message_data.get("msgCreatedAt", ""),
                            "senderName": lead_name,
                            "mediaType": media_type or "text",
                            "mediaUrl": message_data.get("mediaUrl", ""),
                        },
                        "chat": {
                            "wa_isGroup": False,
                        },
                        # Metadados extras do Leadbox
                        "_leadbox": {
                            "ticketId": ticket_id,
                            "contactId": message_data.get("contactId"),
                            "tenantId": tenant_id,
                            "queueId": ticket_data.get("queueId"),
                            "userId": ticket_data.get("userId"),
                        }
                    }

                    # Chamar o handler de mensagens
                    handler = get_webhook_handler()
                    result = await handler.handle_message(uazapi_payload, background_tasks)
                    logger.info("[LEAD INTAKE] Resultado do processamento: %s", result)
                else:
                    logger.warning("[LEAD INTAKE] Ticket %s sem telefone no contato", ticket_id)
            else:
                logger.warning("[LEAD INTAKE] Erro ao buscar ticket %s: status=%s", ticket_id, resp.status_code)

    except Exception as e:
        logger.error("[LEAD INTAKE] Erro ao processar mensagem: %s", e, exc_info=True)


async def create_lead_if_missing(
    supabase_svc,
    table_leads: str,
    phone: str,
    remotejid: str,
    queue_id: int,
    user_id: int,
    ticket_id: str,
    tenant_id: str,
    agent_name: str
) -> None:
    """
    Create lead automatically when Leadbox webhook arrives before WhatsApp webhook.

    This handles the race condition where Leadbox webhook may arrive
    before the UAZAPI/WhatsApp webhook that normally creates the lead.
    """
    contact_name = f"Lead {phone}"

    logger.info(
        "[LEAD INTAKE] Lead %s nao existe - CRIANDO automaticamente (race condition detectada) | tenant=%s | agent=%s",
        phone, tenant_id, agent_name
    )

    try:
        now = datetime.utcnow().isoformat()

        new_lead = {
            "remotejid": remotejid,
            "telefone": phone,
            "nome": contact_name,
            "current_queue_id": queue_id,
            "current_user_id": user_id,
            "ticket_id": ticket_id,
            "pipeline_step": "Leads",
            "Atendimento_Finalizado": "false",
            "responsavel": "IA",
            "status": "open",
            "lead_origin": "leadbox_webhook_auto",
            "created_date": now,
            "updated_date": now,
            "follow_count": 0,
        }

        create_result = supabase_svc.client.table(table_leads).insert(new_lead).execute()

        if create_result.data:
            logger.info(
                "[LEAD INTAKE] Lead %s criado com sucesso | id=%s | queue=%s | ticket=%s",
                phone, create_result.data[0].get("id"), queue_id, ticket_id
            )
        else:
            logger.error("[LEAD INTAKE] Falha ao criar lead %s - resultado vazio", phone)

    except Exception as create_err:
        logger.error("[LEAD INTAKE] Erro ao criar lead %s: %s", phone, create_err)


async def inject_agnes_message(
    supabase_svc,
    table_messages: str,
    remotejid: str,
    phone: str,
    previous_queue_id: Optional[int]
) -> None:
    """
    Inject automatic '12' message for AGNES agent.

    When a lead returns to AGNES from a queue other than 472,
    we inject the message "12" to trigger specific behavior.
    """
    try:
        msg_result = supabase_svc.client.table(table_messages) \
            .select("conversation_history") \
            .eq("remotejid", remotejid) \
            .limit(1) \
            .execute()

        current_history = {"messages": []}
        if msg_result.data and msg_result.data[0].get("conversation_history"):
            current_history = msg_result.data[0]["conversation_history"]

        messages = current_history.get("messages", [])

        # Verificar se última mensagem já é "12"
        last_msg = messages[-1] if messages else None
        is_already_12 = False
        if last_msg:
            parts = last_msg.get("parts", [])
            if last_msg.get("role") == "user" and parts and parts[0].get("text") == "12":
                is_already_12 = True

        if not is_already_12:
            auto_message = {
                "role": "user",
                "parts": [{"text": "12"}],
                "timestamp": datetime.utcnow().isoformat()
            }
            messages.append(auto_message)
            current_history["messages"] = messages

            supabase_svc.client.table(table_messages) \
                .upsert({
                    "remotejid": remotejid,
                    "conversation_history": current_history,
                    "Msg_user": datetime.utcnow().isoformat()
                }, on_conflict="remotejid") \
                .execute()

            logger.info("[LEAD INTAKE] AGNES: Mensagem '12' inserida | lead=%s | queue_anterior=%s",
                       phone, previous_queue_id)
        else:
            logger.warning("[LEAD INTAKE] AGNES: Mensagem '12' ja existe, ignorando duplicata | lead=%s", phone)
    except Exception as msg_err:
        logger.error("[LEAD INTAKE] Erro ao inserir mensagem '12': %s", msg_err)


async def inject_return_context(
    supabase_svc,
    ht: Dict[str, Any],
    table_messages: str,
    remotejid: str,
    previous_queue_id: int,
    phone: str,
    agent_name: str
) -> None:
    """
    Inject context message when lead returns from human queue.

    Based on the department configuration, injects an automatic context
    message so the AI understands what happened while the lead was
    with a human operator.
    """
    departments = ht.get("departments") or {}

    # Construir mapa de filas humanas dinamicamente
    human_queue_contexts = {}
    for dept_key, dept_data in departments.items():
        dept_id = dept_data.get("id")
        dept_name = dept_data.get("name", dept_key)
        context_injection = dept_data.get("context_injection") or {}

        if dept_id:
            if context_injection.get("enabled") and context_injection.get("message"):
                human_queue_contexts[int(dept_id)] = (
                    dept_name,
                    f"[CONTEXTO AUTOMÁTICO] {context_injection['message']}"
                )
            elif dept_key == "cobrancas":
                human_queue_contexts[int(dept_id)] = (
                    dept_name,
                    f"[CONTEXTO AUTOMÁTICO] Cliente retornou do setor de {dept_name}. "
                    "O link de pagamento provavelmente já foi enviado pelo atendente humano. "
                    "Verifique no histórico acima se há mensagens do humano sobre pagamento. "
                    "Continue a cobrança de forma natural, pergunte se conseguiu efetuar o pagamento."
                )
            elif dept_key == "financeiro":
                human_queue_contexts[int(dept_id)] = (
                    dept_name,
                    f"[CONTEXTO AUTOMÁTICO] Cliente retornou do setor {dept_name}. "
                    "Possivelmente enviou comprovante ou tratou questões de pagamento. "
                    "Verifique no histórico acima o que foi discutido. "
                    "Pergunte se a questão foi resolvida."
                )
            else:
                human_queue_contexts[int(dept_id)] = (
                    dept_name,
                    f"[CONTEXTO AUTOMÁTICO] Cliente retornou do setor de {dept_name}. "
                    "Verifique no histórico acima o que foi discutido com o atendente. "
                    "Pergunte se a questão foi resolvida ou se precisa de mais ajuda."
                )

    prev_queue = int(previous_queue_id)
    if prev_queue in human_queue_contexts and table_messages:
        dept_name, context_msg = human_queue_contexts[prev_queue]
        try:
            msg_result = supabase_svc.client.table(table_messages) \
                .select("conversation_history") \
                .eq("remotejid", remotejid) \
                .limit(1) \
                .execute()

            current_history = {"messages": []}
            if msg_result.data and msg_result.data[0].get("conversation_history"):
                current_history = msg_result.data[0]["conversation_history"]

            messages = current_history.get("messages", [])

            # Verificar se última mensagem já é contexto
            last_msg = messages[-1] if messages else None
            is_already_context = False
            if last_msg:
                parts = last_msg.get("parts", [])
                if parts and "[CONTEXTO AUTOMÁTICO]" in str(parts[0].get("text", "")):
                    is_already_context = True

            if not is_already_context:
                context_message = {
                    "role": "user",
                    "parts": [{"text": context_msg}],
                    "timestamp": datetime.utcnow().isoformat(),
                    "is_context_injection": True
                }
                messages.append(context_message)
                current_history["messages"] = messages

                supabase_svc.client.table(table_messages) \
                    .upsert({
                        "remotejid": remotejid,
                        "conversation_history": current_history,
                        "Msg_user": datetime.utcnow().isoformat()
                    }, on_conflict="remotejid") \
                    .execute()

                logger.info(
                    "[LEAD INTAKE] Contexto injetado | agente=%s | lead=%s | fila_anterior=%s (%s)",
                    agent_name, phone, prev_queue, dept_name
                )
            else:
                logger.info(
                    "[LEAD INTAKE] Contexto já existe, ignorando duplicata | lead=%s", phone
                )
        except Exception as ctx_err:
            logger.error("[LEAD INTAKE] Erro ao injetar contexto: %s", ctx_err)
