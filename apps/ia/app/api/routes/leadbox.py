"""
Leadbox webhook endpoint for CRM integration.

This module provides:
- POST /webhooks/leadbox: Process Leadbox events
- Queue management (pause/reactivate AI based on queue)
- Context injection when leads return from human queues
- Human message capture for AI awareness
"""

from datetime import datetime
from typing import Any, Dict
import json as _json

import structlog
from fastapi import APIRouter, BackgroundTasks, Request

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["webhooks"])

# Events that don't need processing
IGNORED_EVENTS = {"AckMessage", "FinishedTicketHistoricMessages"}


@router.post("/webhooks/leadbox")
async def leadbox_webhook(request: Request, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """
    Webhook endpoint para receber eventos do Leadbox.
    Atualiza current_queue_id e pausa/reativa IA baseado na fila.

    REGRA: Se queue != queue_ia do agente, PAUSA imediatamente.
    """
    from app.services.supabase import get_supabase_service
    from app.services.redis import get_redis_service
    from app.webhooks.mensagens import get_webhook_handler

    body = await request.json()

    event_type = body.get("event") or body.get("type") or "unknown"
    logger.info("[LEADBOX WEBHOOK] Evento recebido: %s", event_type)

    # ==========================================================================
    # FILTRAR EVENTOS DESNECESSÁRIOS
    # ==========================================================================
    if event_type in IGNORED_EVENTS:
        logger.debug("[LEADBOX WEBHOOK] Evento ignorado: %s", event_type)
        return {"status": "ignored", "reason": f"event_{event_type}"}

    # Log payload para diagnóstico (primeiros 800 chars)
    logger.info("[LEADBOX WEBHOOK] Payload: %s", _json.dumps(body, default=str)[:800])

    # ==========================================================================
    # PROCESSAR MENSAGEM DO LEAD (substitui webhook UAZAPI)
    # ==========================================================================
    if event_type == "NewMessage":
        await _handle_new_message(body, background_tasks)

    # Extrair dados do ticket/mensagem
    message = body.get("message") or body.get("data", {}).get("message") or {}
    ticket = message.get("ticket") or body.get("ticket") or body.get("data", {}).get("ticket") or {}
    contact = ticket.get("contact") or message.get("contact") or body.get("contact") or {}

    queue_id = ticket.get("queueId") or message.get("queueId")
    user_id = ticket.get("userId") or message.get("userId")
    ticket_id = ticket.get("id") or message.get("ticketId")
    phone = contact.get("number", "").replace("+", "").strip()

    # DEBUG: Log raw user_id extraction
    logger.debug(
        "[LEADBOX DEBUG RAW] ticket.userId=%r | message.userId=%r | final user_id=%r (type=%s)",
        ticket.get("userId"), message.get("userId"), user_id, type(user_id).__name__ if user_id else "None"
    )

    # Extrair tenant_id do payload
    payload_tenant_id = body.get("tenantId") or body.get("tenant_id")
    if not payload_tenant_id:
        payload_tenant_id = ticket.get("tenantId") or ticket.get("tenant_id")

    # ==========================================================================
    # VERIFICAR SE TICKET FOI FECHADO
    # ==========================================================================
    ticket_status = ticket.get("status", "")
    closed_at = ticket.get("closedAt")

    if phone and (ticket_status == "closed" or closed_at is not None):
        return await _handle_ticket_closed(phone, ticket_id, ticket_status, closed_at, payload_tenant_id)

    if phone and queue_id:
        return await _handle_queue_change(
            phone, queue_id, user_id, ticket_id, payload_tenant_id, event_type
        )
    else:
        logger.warning("[LEADBOX WEBHOOK] Payload sem phone ou queueId: phone=%s, queue=%s", phone, queue_id)
        logger.warning("[LEADBOX WEBHOOK] Keys no payload: %s", list(body.keys())[:10])

    return {"status": "ok", "event": event_type}


async def _handle_new_message(body: Dict[str, Any], background_tasks: BackgroundTasks) -> None:
    """Process NewMessage event from Leadbox."""
    from app.services.supabase import get_supabase_service
    from app.webhooks.mensagens import get_webhook_handler
    import httpx

    message_data = body.get("message") or {}
    from_me = message_data.get("fromMe", False)
    msg_body = message_data.get("body", "").strip()
    ticket_id = message_data.get("ticketId")
    tenant_id = message_data.get("tenantId") or body.get("tenantId")
    media_type = message_data.get("mediaType", "")
    message_id = message_data.get("messageId", "")

    # Se for áudio, usar placeholder [AUDIO]
    if media_type in ["audio", "ptt", "voice"] and not msg_body:
        msg_body = "[AUDIO]"
        logger.info("[LEADBOX MESSAGE] Áudio detectado - messageId=%s", message_id)

    # Se for imagem, usar placeholder [image recebido]
    media_url = message_data.get("mediaUrl", "")
    if media_type in ["image", "imageMessage"] and not msg_body:
        msg_body = "[image recebido]"
        logger.info("[LEADBOX MESSAGE] Imagem detectada - messageId=%s, mediaUrl=%s", message_id, media_url[:100] if media_url else "None")

    # =======================================================================
    # CAPTURAR MENSAGENS DO HUMANO NO HISTÓRICO
    # =======================================================================
    send_type = message_data.get("sendType", "")
    is_api_message = send_type == "API"

    if from_me and msg_body and ticket_id and not is_api_message:
        await _capture_human_message(body, ticket_id, tenant_id, msg_body)

    # =======================================================================
    # PROCESSAR MENSAGENS DO LEAD COM IA
    # =======================================================================
    elif not from_me and msg_body and ticket_id:
        await _process_lead_message(body, background_tasks, ticket_id, tenant_id, msg_body, message_data, media_type)


async def _capture_human_message(body: Dict[str, Any], ticket_id: str, tenant_id: str, msg_body: str) -> None:
    """Capture human operator messages into conversation history."""
    from app.services.supabase import get_supabase_service
    import httpx

    logger.info("[LEADBOX MESSAGE] Mensagem do HUMANO detectada - ticketId=%s", ticket_id)

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
                async with httpx.AsyncClient(timeout=10.0) as client:
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
                                "[LEADBOX MESSAGE] Mensagem do HUMANO salva no histórico | lead=%s | msg=%s",
                                lead_phone, msg_body[:50]
                            )
                        else:
                            logger.warning("[LEADBOX MESSAGE] Ticket %s sem telefone", ticket_id)
                    else:
                        logger.warning("[LEADBOX MESSAGE] Erro ao buscar ticket: %s", resp.status_code)
            else:
                logger.warning("[LEADBOX MESSAGE] Agente sem table_messages ou credenciais Leadbox")
        else:
            logger.debug("[LEADBOX MESSAGE] Mensagem do humano - agente não encontrado para tenant=%s", tenant_id)

    except Exception as e:
        logger.error("[LEADBOX MESSAGE] Erro ao salvar mensagem do humano: %s", e, exc_info=True)


async def _process_lead_message(
    body: Dict[str, Any],
    background_tasks: BackgroundTasks,
    ticket_id: str,
    tenant_id: str,
    msg_body: str,
    message_data: Dict[str, Any],
    media_type: str
) -> None:
    """Process incoming lead messages with AI."""
    from app.services.supabase import get_supabase_service
    from app.webhooks.mensagens import get_webhook_handler
    import httpx

    logger.info("[LEADBOX MESSAGE] Nova mensagem recebida - ticketId=%s, tenant=%s", ticket_id, tenant_id)

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
            logger.warning("[LEADBOX MESSAGE] Nenhum agente encontrado para tenant_id=%s", tenant_id)
            return

        # Extrair credenciais Leadbox do leadbox_config
        leadbox_config = target_agent.get("leadbox_config") or {}
        lb_api_url = leadbox_config.get("api_url", "")
        lb_api_token = leadbox_config.get("api_token", "")

        if not lb_api_url or not lb_api_token:
            logger.warning("[LEADBOX MESSAGE] Agente %s sem credenciais Leadbox configuradas", target_agent.get("name"))
            return

        # Buscar dados do ticket via API para obter telefone do contato
        async with httpx.AsyncClient(timeout=10.0) as client:
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
                    logger.info("[LEADBOX MESSAGE] Processando mensagem do lead %s: %s", lead_phone, msg_body[:50])

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
                    logger.info("[LEADBOX MESSAGE] Resultado do processamento: %s", result)
                else:
                    logger.warning("[LEADBOX MESSAGE] Ticket %s sem telefone no contato", ticket_id)
            else:
                logger.warning("[LEADBOX MESSAGE] Erro ao buscar ticket %s: status=%s", ticket_id, resp.status_code)

    except Exception as e:
        logger.error("[LEADBOX MESSAGE] Erro ao processar mensagem: %s", e, exc_info=True)


async def _handle_ticket_closed(
    phone: str,
    ticket_id: str,
    ticket_status: str,
    closed_at: str,
    payload_tenant_id: str
) -> Dict[str, Any]:
    """Handle ticket closed event - reset lead state."""
    from app.services.supabase import get_supabase_service
    from app.services.redis import get_redis_service

    logger.info("[LEADBOX WEBHOOK] Ticket %s FECHADO (status=%s, closedAt=%s) - limpando ticket_id do lead %s",
                ticket_id, ticket_status, closed_at, phone)

    try:
        supabase_svc = get_supabase_service()
        agents = supabase_svc.client.table("agents") \
            .select("id,name,table_leads,handoff_triggers") \
            .eq("active", True) \
            .execute()

        clean_phone = "".join(filter(str.isdigit, phone))
        remotejid = f"{clean_phone}@s.whatsapp.net"

        for ag in (agents.data or []):
            table_leads = ag.get("table_leads")
            if not table_leads:
                continue

            ht = ag.get("handoff_triggers") or {}
            agent_tenant_id = ht.get("tenant_id")

            # Filtrar por tenant_id se presente
            if payload_tenant_id:
                if not agent_tenant_id or int(payload_tenant_id) != int(agent_tenant_id):
                    continue

            try:
                supabase_svc.client.table(table_leads) \
                    .update({
                        "ticket_id": None,
                        "current_queue_id": None,
                        "current_user_id": None,
                        "Atendimento_Finalizado": "false",
                        "current_state": "ai",
                        "paused_at": None,
                        "paused_by": None,
                        "responsavel": "AI",
                    }) \
                    .eq("remotejid", remotejid) \
                    .execute()

                # Também remover pausa do Redis
                try:
                    redis_svc = await get_redis_service()
                    agent_id = ag.get("id")
                    if agent_id:
                        await redis_svc.pause_clear(agent_id, clean_phone)
                        logger.info("[LEADBOX WEBHOOK] Pausa Redis removida para %s (agent=%s)", phone, agent_id[:8])
                except Exception as redis_err:
                    logger.warning("[LEADBOX WEBHOOK] Erro ao remover pausa Redis: %s", redis_err)

                logger.info("[LEADBOX WEBHOOK] Ticket fechado - lead %s resetado para IA em %s", phone, table_leads)
            except Exception as e:
                logger.debug("[LEADBOX WEBHOOK] Erro ao limpar ticket_id em %s: %s", table_leads, e)

    except Exception as e:
        logger.warning("[LEADBOX WEBHOOK] Erro ao processar ticket fechado: %s", e)

    return {"status": "ok", "event": "ticket_closed", "ticket_id": ticket_id}


async def _handle_queue_change(
    phone: str,
    queue_id: int,
    user_id: int,
    ticket_id: str,
    payload_tenant_id: str,
    event_type: str
) -> Dict[str, Any]:
    """Handle queue change events - pause/reactivate AI based on queue."""
    from app.services.supabase import get_supabase_service
    from app.services.redis import get_redis_service

    logger.info("[LEADBOX WEBHOOK] Lead %s | ticket=%s | queue=%s | user=%s | tenant=%s",
                phone, ticket_id, queue_id, user_id, payload_tenant_id)

    try:
        supabase_svc = get_supabase_service()

        # Buscar TODOS os agentes ativos com table_leads
        agents = supabase_svc.client.table("agents") \
            .select("id,name,table_leads,table_messages,handoff_triggers") \
            .eq("active", True) \
            .execute()

        clean_phone = "".join(filter(str.isdigit, phone))
        remotejid = f"{clean_phone}@s.whatsapp.net"
        lead_found = False

        for ag in (agents.data or []):
            table_leads = ag.get("table_leads")
            if not table_leads:
                continue

            ht = ag.get("handoff_triggers") or {}
            agent_name = ag.get("name", "unknown")

            # FILTRO 1: tenant_id
            agent_tenant_id = ht.get("tenant_id")
            if payload_tenant_id:
                if not agent_tenant_id or int(payload_tenant_id) != int(agent_tenant_id):
                    continue

            # FILTRO 2: enabled
            if not ht.get("enabled"):
                logger.debug("[LEADBOX WEBHOOK] Agente %s com enabled=false, pulando", agent_name)
                continue

            try:
                # SELECT defensivo: busca apenas id e remotejid primeiro
                result = supabase_svc.client.table(table_leads) \
                    .select("id,remotejid") \
                    .eq("remotejid", remotejid) \
                    .limit(1) \
                    .execute()

                if not result.data:
                    # Race condition: criar lead automaticamente
                    await _create_lead_if_missing(
                        supabase_svc, table_leads, phone, remotejid,
                        queue_id, user_id, ticket_id, payload_tenant_id, agent_name
                    )

                lead_found = True
                agent_id = ag.get("id", "")
                QUEUE_IA = int(ht.get("queue_ia", 537))
                table_messages = ag.get("table_messages")

                # Construir set de todas as filas de IA
                IA_QUEUES = {QUEUE_IA}
                dispatch_depts = ht.get("dispatch_departments") or {}
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
                logger.debug("[LEADBOX WEBHOOK] Filas de IA configuradas: %s", IA_QUEUES)

                # Buscar current_queue_id separadamente com fallback seguro
                previous_queue_id = None
                try:
                    queue_result = supabase_svc.client.table(table_leads) \
                        .select("current_queue_id") \
                        .eq("remotejid", remotejid) \
                        .limit(1) \
                        .execute()
                    if queue_result.data:
                        previous_queue_id = queue_result.data[0].get("current_queue_id")
                except Exception as qe:
                    logger.warning("[LEADBOX WEBHOOK] Tabela %s sem coluna current_queue_id: %s", table_leads, qe)

                logger.info("[LEADBOX WEBHOOK] Agente: %s | tenant: %s | queue_anterior: %s",
                           agent_name, agent_tenant_id, previous_queue_id)

                update_data = {
                    "current_queue_id": queue_id,
                    "current_user_id": user_id,
                    "ticket_id": ticket_id,
                }

                if int(queue_id) in IA_QUEUES:
                    # Fila de IA: reativar atendimento
                    await _handle_ia_queue(
                        supabase_svc, ag, ht, phone, clean_phone, queue_id, user_id,
                        ticket_id, remotejid, table_leads, table_messages,
                        previous_queue_id, agent_id, agent_name, update_data
                    )
                else:
                    # Fila humana: pausar IA
                    update_data["Atendimento_Finalizado"] = "true"
                    update_data["paused_at"] = datetime.utcnow().isoformat()
                    logger.info("[LEADBOX WEBHOOK] Lead %s na fila %s (NAO esta em filas IA %s) - PAUSANDO IMEDIATAMENTE",
                               phone, queue_id, IA_QUEUES)
                    try:
                        redis_svc = await get_redis_service()
                        await redis_svc.pause_set(agent_id, clean_phone)
                        logger.info("[LEADBOX WEBHOOK] Redis pause SETADA para agent=%s phone=%s", agent_id[:8], clean_phone)
                    except Exception as re:
                        logger.warning("[LEADBOX WEBHOOK] Erro ao setar Redis pause: %s", re)

                # UPDATE em duas etapas para evitar falha por colunas inexistentes
                core_update = {k: v for k, v in update_data.items()
                               if k not in ("current_queue_id", "current_user_id", "ticket_id")}
                if core_update:
                    supabase_svc.client.table(table_leads) \
                        .update(core_update) \
                        .eq("remotejid", remotejid) \
                        .execute()
                    logger.info("[LEADBOX WEBHOOK] Core update OK: %s | dados=%s", table_leads, list(core_update.keys()))

                queue_update = {k: v for k, v in update_data.items()
                                if k in ("current_queue_id", "current_user_id", "ticket_id")}
                if queue_update:
                    try:
                        supabase_svc.client.table(table_leads) \
                            .update(queue_update) \
                            .eq("remotejid", remotejid) \
                            .execute()
                        logger.info("[LEADBOX WEBHOOK] Queue update OK: %s | queue=%s | user=%s", table_leads, queue_id, user_id)
                    except Exception as qu:
                        logger.warning("[LEADBOX WEBHOOK] Queue update falhou em %s: %s", table_leads, qu)

                logger.info("[LEADBOX WEBHOOK] Supabase atualizado: %s | queue=%s | user=%s", table_leads, queue_id, user_id)
                break  # Lead encontrado e processado

            except Exception as e:
                logger.error("[LEADBOX WEBHOOK] Erro ao buscar/atualizar lead em %s: %s", table_leads, e)

        if not lead_found:
            logger.warning("[LEADBOX WEBHOOK] Lead %s (%s) NAO encontrado em nenhuma tabela de agentes", phone, remotejid)

    except Exception as e:
        logger.debug("[LEADBOX WEBHOOK] Erro geral: %s", e)

    return {"status": "ok", "event": event_type}


async def _create_lead_if_missing(
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
    """Create lead automatically when Leadbox webhook arrives before WhatsApp webhook."""
    contact_name = f"Lead {phone}"

    logger.info(
        "[LEADBOX WEBHOOK] Lead %s nao existe - CRIANDO automaticamente (race condition detectada) | tenant=%s | agent=%s",
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
                "[LEADBOX WEBHOOK] Lead %s criado com sucesso | id=%s | queue=%s | ticket=%s",
                phone, create_result.data[0].get("id"), queue_id, ticket_id
            )
        else:
            logger.error("[LEADBOX WEBHOOK] Falha ao criar lead %s - resultado vazio", phone)

    except Exception as create_err:
        logger.error("[LEADBOX WEBHOOK] Erro ao criar lead %s: %s", phone, create_err)


async def _handle_ia_queue(
    supabase_svc,
    agent: Dict[str, Any],
    ht: Dict[str, Any],
    phone: str,
    clean_phone: str,
    queue_id: int,
    user_id: int,
    ticket_id: str,
    remotejid: str,
    table_leads: str,
    table_messages: str,
    previous_queue_id: int,
    agent_id: str,
    agent_name: str,
    update_data: Dict[str, Any]
) -> None:
    """Handle lead entering IA queue - reactivate AI and inject context if needed."""
    from app.services.redis import get_redis_service

    queue_ia_user_id = ht.get("queue_ia_user_id")
    current_user_str = str(user_id) if user_id else None
    target_user_str = str(queue_ia_user_id) if queue_ia_user_id else None

    logger.info(
        "[LEADBOX WEBHOOK] Fila IA detectada: queue=%s | userId_atual=%s | userId_alvo=%s | phone=%s",
        queue_id, current_user_str, target_user_str, phone
    )

    if not queue_ia_user_id:
        logger.warning("[LEADBOX WEBHOOK] queue_ia_user_id NAO configurado para agente %s!", agent_name)
    else:
        # Anti-loop: Se userId já é o correto, apenas atualiza e sai
        if current_user_str == target_user_str:
            logger.debug(
                "[LEADBOX WEBHOOK] Anti-loop: userId já é %s, apenas reativando IA",
                target_user_str
            )
            update_data["Atendimento_Finalizado"] = "false"
            update_data["current_user_id"] = target_user_str
            try:
                redis_svc = await get_redis_service()
                await redis_svc.pause_clear(agent_id, clean_phone)
            except Exception as re:
                logger.warning("[LEADBOX WEBHOOK] Erro ao limpar Redis pause: %s", re)
        else:
            # Forçar auto-assign
            logger.info(
                "[LEADBOX WEBHOOK] Forçando userId: %s -> %s para lead %s",
                current_user_str, target_user_str, phone
            )

            try:
                from app.services.leadbox import LeadboxService
                leadbox_service = LeadboxService(
                    base_url=ht.get("api_url"),
                    api_uuid=ht.get("api_uuid"),
                    api_key=ht.get("api_token"),
                )
                transfer_result = await leadbox_service.assign_user_silent(
                    phone=phone,
                    queue_id=int(queue_id),
                    user_id=int(queue_ia_user_id),
                    ticket_id=int(ticket_id) if ticket_id else None
                )
                if transfer_result.get("sucesso"):
                    logger.info(
                        "[AUTO ASSIGN] Lead %s forçado para userId=%s com sucesso",
                        phone, queue_ia_user_id
                    )
                    update_data["current_user_id"] = target_user_str
                else:
                    logger.warning(
                        "[AUTO ASSIGN] Falha ao forçar userId para %s: %s",
                        phone, transfer_result.get("mensagem")
                    )
            except Exception as aa_err:
                logger.error("[AUTO ASSIGN] Erro: %s", aa_err)

            # SEMPRE reativar IA quando na fila de IA
            update_data["Atendimento_Finalizado"] = "false"
            try:
                redis_svc = await get_redis_service()
                await redis_svc.pause_clear(agent_id, clean_phone)
                logger.info("[LEADBOX WEBHOOK] Redis pause LIMPA para agent=%s", agent_id[:8])
            except Exception as re:
                logger.warning("[LEADBOX WEBHOOK] Erro ao limpar Redis pause: %s", re)

        # AGNES LEADBOX: Inserir mensagem "12" quando vem de fila != 472
        if agent_id == "b3f217f4-5112-4d7a-b597-edac2ccfe6b5":
            if previous_queue_id is None or int(previous_queue_id) != 472:
                if table_messages:
                    await _inject_agnes_message(supabase_svc, table_messages, remotejid, phone, previous_queue_id)

        # Injeção de contexto para outros agentes
        elif previous_queue_id is not None:
            await _inject_return_context(
                supabase_svc, ht, table_messages, remotejid,
                previous_queue_id, phone, agent_name
            )


async def _inject_agnes_message(
    supabase_svc,
    table_messages: str,
    remotejid: str,
    phone: str,
    previous_queue_id: int
) -> None:
    """Inject automatic '12' message for AGNES agent."""
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

            logger.info("[LEADBOX WEBHOOK] AGNES LEADBOX: Mensagem '12' inserida | lead=%s | queue_anterior=%s",
                       phone, previous_queue_id)
        else:
            logger.warning("[LEADBOX WEBHOOK] AGNES LEADBOX: Mensagem '12' ja existe, ignorando duplicata | lead=%s", phone)
    except Exception as msg_err:
        logger.error("[LEADBOX WEBHOOK] Erro ao inserir mensagem '12': %s", msg_err)


async def _inject_return_context(
    supabase_svc,
    ht: Dict[str, Any],
    table_messages: str,
    remotejid: str,
    previous_queue_id: int,
    phone: str,
    agent_name: str
) -> None:
    """Inject context message when lead returns from human queue."""
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
                    "[LEADBOX WEBHOOK] Contexto injetado | agente=%s | lead=%s | fila_anterior=%s (%s)",
                    agent_name, phone, prev_queue, dept_name
                )
            else:
                logger.info(
                    "[LEADBOX WEBHOOK] Contexto já existe, ignorando duplicata | lead=%s", phone
                )
        except Exception as ctx_err:
            logger.error("[LEADBOX WEBHOOK] Erro ao injetar contexto: %s", ctx_err)
