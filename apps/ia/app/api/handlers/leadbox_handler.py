"""
Leadbox webhook handler for CRM integration.

This module handles:
- Processing NewMessage events (routing to human/lead handlers)
- Handling ticket closed events (reset lead state)
- Handling queue change events (pause/reactivate AI)
- IA queue management (auto-assign, context injection)
"""

from datetime import datetime
from typing import Any, Dict

import structlog

logger = structlog.get_logger(__name__)

# AGNES agent ID - special handling for "12" message injection
AGNES_AGENT_ID = "b3f217f4-5112-4d7a-b597-edac2ccfe6b5"


async def handle_new_message(body: Dict[str, Any], background_tasks) -> None:
    """
    Process NewMessage event from Leadbox.

    Routes to either human message capture or lead message processing
    based on the fromMe flag and message characteristics.
    """
    from app.api.services.lead_intake_service import (
        capture_human_message,
        process_lead_message,
    )

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
        logger.info("[LEADBOX HANDLER] Áudio detectado - messageId=%s", message_id)

    # Se for imagem, usar placeholder [image recebido]
    media_url = message_data.get("mediaUrl", "")
    if media_type in ["image", "imageMessage"] and not msg_body:
        msg_body = "[image recebido]"
        logger.info("[LEADBOX HANDLER] Imagem detectada - messageId=%s, mediaUrl=%s",
                   message_id, media_url[:100] if media_url else "None")

    # Capturar mensagens do humano no histórico
    send_type = message_data.get("sendType", "")
    is_api_message = send_type == "API"

    if from_me and msg_body and ticket_id and not is_api_message:
        await capture_human_message(body, ticket_id, tenant_id, msg_body)

    # Processar mensagens do lead com IA
    elif not from_me and msg_body and ticket_id:
        await process_lead_message(
            body, background_tasks, ticket_id, tenant_id,
            msg_body, message_data, media_type
        )


async def handle_ticket_closed(
    phone: str,
    ticket_id: str,
    ticket_status: str,
    closed_at: str,
    payload_tenant_id: str
) -> Dict[str, Any]:
    """
    Handle ticket closed event - reset lead state.

    Clears ticket_id, queue_id, user_id and reactivates AI
    when a ticket is closed in Leadbox.
    """
    from app.services.supabase import get_supabase_service
    from app.services.redis import get_redis_service

    logger.info("[LEADBOX HANDLER] Ticket %s FECHADO (status=%s, closedAt=%s) - limpando ticket_id do lead %s",
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
                        logger.info("[LEADBOX HANDLER] Pausa Redis removida para %s (agent=%s)",
                                   phone, agent_id[:8])
                except Exception as redis_err:
                    logger.warning("[LEADBOX HANDLER] Erro ao remover pausa Redis: %s", redis_err)

                logger.info("[LEADBOX HANDLER] Ticket fechado - lead %s resetado para IA em %s",
                           phone, table_leads)
            except Exception as e:
                logger.debug("[LEADBOX HANDLER] Erro ao limpar ticket_id em %s: %s", table_leads, e)

    except Exception as e:
        logger.warning("[LEADBOX HANDLER] Erro ao processar ticket fechado: %s", e)

    return {"status": "ok", "event": "ticket_closed", "ticket_id": ticket_id}


async def handle_queue_change(
    phone: str,
    queue_id: int,
    user_id: int,
    ticket_id: str,
    payload_tenant_id: str,
    event_type: str
) -> Dict[str, Any]:
    """
    Handle queue change events - pause/reactivate AI based on queue.

    Core orchestration function that:
    - Creates lead if missing (race condition handling)
    - Pauses AI when lead goes to human queue
    - Reactivates AI when lead returns to IA queue
    - Injects context when returning from human queues
    """
    from app.services.supabase import get_supabase_service
    from app.services.redis import get_redis_service
    from app.api.services.lead_intake_service import create_lead_if_missing

    logger.info("[LEADBOX HANDLER] Lead %s | ticket=%s | queue=%s | user=%s | tenant=%s",
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
                logger.debug("[LEADBOX HANDLER] Agente %s com enabled=false, pulando", agent_name)
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
                    await create_lead_if_missing(
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
                logger.debug("[LEADBOX HANDLER] Filas de IA configuradas: %s", IA_QUEUES)

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
                    logger.warning("[LEADBOX HANDLER] Tabela %s sem coluna current_queue_id: %s",
                                  table_leads, qe)

                logger.info("[LEADBOX HANDLER] Agente: %s | tenant: %s | queue_anterior: %s",
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
                    logger.info("[LEADBOX HANDLER] Lead %s na fila %s (NAO esta em filas IA %s) - PAUSANDO",
                               phone, queue_id, IA_QUEUES)
                    try:
                        redis_svc = await get_redis_service()
                        await redis_svc.pause_set(agent_id, clean_phone)
                        logger.info("[LEADBOX HANDLER] Redis pause SETADA para agent=%s phone=%s",
                                   agent_id[:8], clean_phone)
                    except Exception as re:
                        logger.warning("[LEADBOX HANDLER] Erro ao setar Redis pause: %s", re)

                # UPDATE em duas etapas para evitar falha por colunas inexistentes
                core_update = {k: v for k, v in update_data.items()
                               if k not in ("current_queue_id", "current_user_id", "ticket_id")}
                if core_update:
                    supabase_svc.client.table(table_leads) \
                        .update(core_update) \
                        .eq("remotejid", remotejid) \
                        .execute()
                    logger.info("[LEADBOX HANDLER] Core update OK: %s | dados=%s",
                               table_leads, list(core_update.keys()))

                queue_update = {k: v for k, v in update_data.items()
                                if k in ("current_queue_id", "current_user_id", "ticket_id")}
                if queue_update:
                    try:
                        supabase_svc.client.table(table_leads) \
                            .update(queue_update) \
                            .eq("remotejid", remotejid) \
                            .execute()
                        logger.info("[LEADBOX HANDLER] Queue update OK: %s | queue=%s | user=%s",
                                   table_leads, queue_id, user_id)
                    except Exception as qu:
                        logger.warning("[LEADBOX HANDLER] Queue update falhou em %s: %s",
                                      table_leads, qu)

                logger.info("[LEADBOX HANDLER] Supabase atualizado: %s | queue=%s | user=%s",
                           table_leads, queue_id, user_id)
                break  # Lead encontrado e processado

            except Exception as e:
                logger.error("[LEADBOX HANDLER] Erro ao buscar/atualizar lead em %s: %s",
                            table_leads, e)

        if not lead_found:
            logger.warning("[LEADBOX HANDLER] Lead %s (%s) NAO encontrado em nenhuma tabela",
                          phone, remotejid)

    except Exception as e:
        logger.debug("[LEADBOX HANDLER] Erro geral: %s", e)

    return {"status": "ok", "event": event_type}


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
    """
    Handle lead entering IA queue - reactivate AI and inject context if needed.

    Sub-orchestrator that:
    - Forces correct userId assignment
    - Clears Redis pause
    - Injects AGNES "12" message or generic context
    """
    from app.services.redis import get_redis_service
    from app.api.services.lead_intake_service import (
        inject_agnes_message,
        inject_return_context,
    )

    queue_ia_user_id = ht.get("queue_ia_user_id")
    current_user_str = str(user_id) if user_id else None
    target_user_str = str(queue_ia_user_id) if queue_ia_user_id else None

    logger.info(
        "[LEADBOX HANDLER] Fila IA detectada: queue=%s | userId_atual=%s | userId_alvo=%s | phone=%s",
        queue_id, current_user_str, target_user_str, phone
    )

    if not queue_ia_user_id:
        logger.warning("[LEADBOX HANDLER] queue_ia_user_id NAO configurado para agente %s!", agent_name)
    else:
        # Anti-loop: Se userId já é o correto, apenas atualiza e sai
        if current_user_str == target_user_str:
            logger.debug(
                "[LEADBOX HANDLER] Anti-loop: userId já é %s, apenas reativando IA",
                target_user_str
            )
            update_data["Atendimento_Finalizado"] = "false"
            update_data["current_user_id"] = target_user_str
            try:
                redis_svc = await get_redis_service()
                await redis_svc.pause_clear(agent_id, clean_phone)
            except Exception as re:
                logger.warning("[LEADBOX HANDLER] Erro ao limpar Redis pause: %s", re)
        else:
            # Forçar auto-assign
            logger.info(
                "[LEADBOX HANDLER] Forçando userId: %s -> %s para lead %s",
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
                logger.info("[LEADBOX HANDLER] Redis pause LIMPA para agent=%s", agent_id[:8])
            except Exception as re:
                logger.warning("[LEADBOX HANDLER] Erro ao limpar Redis pause: %s", re)

        # AGNES LEADBOX: Inserir mensagem "12" quando vem de fila != 472
        if agent_id == AGNES_AGENT_ID:
            if previous_queue_id is None or int(previous_queue_id) != 472:
                if table_messages:
                    await inject_agnes_message(
                        supabase_svc, table_messages, remotejid, phone, previous_queue_id
                    )

        # Injeção de contexto para outros agentes
        elif previous_queue_id is not None:
            await inject_return_context(
                supabase_svc, ht, table_messages, remotejid,
                previous_queue_id, phone, agent_name
            )
