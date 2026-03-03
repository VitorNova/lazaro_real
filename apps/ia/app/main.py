"""
Main application entry point for Agente IA.

This module provides:
- FastAPI application with lifespan management
- Service initialization on startup
- Graceful shutdown handling
- Health check endpoints
- CORS middleware configuration
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional
import json as _json
import logging
import os
import uuid

import structlog
import uvicorn
from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings

# Configurar logging padrao do Python ANTES do structlog
# Isso e necessario porque alguns modulos (whatsapp.py) usam logging.getLogger()
logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    force=True  # Sobrescreve configuracoes anteriores
)
from app.services import (
    get_redis_service,
    close_redis_service,
    get_gemini_service,
)
from app.tools.cobranca import FUNCTION_DECLARATIONS
from app.jobs.cobrar_clientes import run_billing_charge_job, is_billing_charge_running, _force_run_billing_charge
from app.jobs.reconciliar_pagamentos import run_billing_reconciliation_job, is_billing_reconciliation_running, _force_run_billing_reconciliation
from app.jobs.confirmar_agendamentos import run_calendar_confirmation_job, is_calendar_confirmation_running, _force_run_calendar_confirmation
from app.jobs.reengajar_leads import run_follow_up_job, is_follow_up_running, _force_run_follow_up
from app.jobs.notificar_manutencoes import run_maintenance_notifier_job, is_maintenance_notifier_running, _force_run_maintenance_notifier

# Configure structlog
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer() if settings.log_format == "json" else structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)


# =============================================================================
# SERVICE STATE
# =============================================================================

class AppState:
    """Global application state for tracking service status."""

    redis_connected: bool = False
    gemini_initialized: bool = False
    startup_time: Optional[datetime] = None
    scheduler: Optional[Any] = None


app_state = AppState()


# =============================================================================
# ORPHAN BUFFER RECOVERY
# =============================================================================

async def recover_orphan_buffers():
    """
    Recupera buffers órfãos após restart do PM2.

    Quando o PM2 reinicia, tasks em memória são perdidas mas os buffers
    permanecem no Redis. Esta função identifica buffers sem lock ativo
    e agenda seu processamento.
    """
    from app.services.redis import get_redis_service
    from app.services.supabase import SupabaseService

    try:
        redis = await get_redis_service()
        orphan_buffers = await redis.list_orphan_buffers()

        if not orphan_buffers:
            logger.info("[STARTUP RECOVERY] Nenhum buffer órfão encontrado")
            return

        logger.warning(
            f"[STARTUP RECOVERY] Encontrados {len(orphan_buffers)} buffers órfãos",
            extra={"count": len(orphan_buffers)},
        )

        supabase = SupabaseService()
        recovered = 0
        failed = 0

        for buffer in orphan_buffers:
            agent_id = buffer["agent_id"]
            phone = buffer["phone"]
            message_count = buffer["message_count"]

            logger.info(
                f"[STARTUP RECOVERY] Processando buffer órfão: agent={agent_id[:8]}... phone={phone} msgs={message_count}"
            )

            try:
                # Buscar agente
                agent = supabase.get_agent_by_id(agent_id)
                if not agent:
                    logger.warning(f"[STARTUP RECOVERY] Agente {agent_id[:8]} não encontrado - limpando buffer")
                    await redis.buffer_clear(agent_id, phone)
                    failed += 1
                    continue

                # Verificar se agente está ativo
                if not agent.get("enabled"):
                    logger.warning(f"[STARTUP RECOVERY] Agente {agent_id[:8]} desativado - limpando buffer")
                    await redis.buffer_clear(agent_id, phone)
                    failed += 1
                    continue

                # Importar handler e processar
                from app.webhooks.mensagens import WhatsAppWebhookHandler

                # Construir contexto mínimo
                handoff_triggers = agent.get("handoff_triggers") or {}
                context = {
                    "agent_id": agent_id,
                    "system_prompt": agent.get("system_prompt", ""),
                    "table_messages": agent.get("table_messages", ""),
                    "table_leads": agent.get("table_leads", ""),
                    "handoff_triggers": handoff_triggers,
                    "uazapi_token": agent.get("uazapi_token", ""),
                    "uazapi_base_url": agent.get("uazapi_base_url", ""),
                    "context_prompts": agent.get("context_prompts"),
                }

                # Construir remotejid
                clean_phone = phone.replace("+", "").replace("-", "").replace(" ", "")
                remotejid = f"{clean_phone}@s.whatsapp.net"

                # Processar em background (não bloqueia startup)
                async def process_orphan():
                    handler = WhatsAppWebhookHandler()
                    try:
                        await handler._process_buffered_messages(
                            agent_id=agent_id,
                            phone=phone,
                            remotejid=remotejid,
                            context=context,
                        )
                        logger.info(f"[STARTUP RECOVERY] Buffer processado: {phone}")
                    except Exception as proc_err:
                        logger.error(f"[STARTUP RECOVERY] Erro ao processar {phone}: {proc_err}")

                # Agendar processamento com pequeno delay para não sobrecarregar
                asyncio.create_task(process_orphan())
                await asyncio.sleep(0.5)  # 500ms entre cada para não sobrecarregar

                recovered += 1

            except Exception as e:
                logger.error(f"[STARTUP RECOVERY] Erro ao recuperar buffer {phone}: {e}")
                failed += 1

        logger.info(
            f"[STARTUP RECOVERY] Concluído: {recovered} agendados, {failed} falhas",
            extra={"recovered": recovered, "failed": failed},
        )

    except Exception as e:
        logger.error(f"[STARTUP RECOVERY] Erro geral: {e}")


# =============================================================================
# FAILED SEND RECOVERY
# =============================================================================

async def recover_failed_sends():
    """
    Recupera e reenvia mensagens que falharam ao ser enviadas.

    Quando a UAZAPI falha (timeout, 500, etc), a mensagem é salva na fila
    failed_send:{agent_id}:{phone}. Esta função tenta reenviar essas mensagens.
    """
    from app.services.redis import get_redis_service
    from app.services.whatsapp_api import UazapiService

    try:
        redis = await get_redis_service()

        # Buscar todas as chaves de mensagens pendentes
        failed_keys = []
        async for key in redis.client.scan_iter(match="failed_send:*", count=100):
            failed_keys.append(key)

        if not failed_keys:
            logger.info("[FAILED SEND RECOVERY] Nenhuma mensagem pendente encontrada")
            return

        logger.warning(
            f"[FAILED SEND RECOVERY] Encontradas {len(failed_keys)} mensagens pendentes",
            extra={"count": len(failed_keys)},
        )

        recovered = 0
        failed = 0
        max_attempts = 5  # Máximo de tentativas antes de desistir

        for key in failed_keys:
            try:
                # Extrair agent_id e phone da chave
                # Formato: failed_send:{agent_id}:{phone}
                parts = key.split(":")
                if len(parts) != 3:
                    logger.warning(f"[FAILED SEND RECOVERY] Chave com formato inesperado: {key}")
                    continue

                agent_id = parts[1]
                phone = parts[2]

                # Buscar payload da mensagem
                payload = await redis.cache_get(key)
                if not payload or not isinstance(payload, dict):
                    logger.warning(f"[FAILED SEND RECOVERY] Payload inválido para {key}")
                    await redis.cache_delete(key)
                    continue

                attempts = payload.get("attempts", 0)
                text = payload.get("text", "")

                # Se já tentou demais, desistir
                if attempts >= max_attempts:
                    logger.error(
                        f"[FAILED SEND RECOVERY] Desistindo de {phone} após {attempts} tentativas"
                    )
                    await redis.cache_delete(key)
                    failed += 1
                    continue

                # Buscar agente para pegar credenciais UAZAPI
                from app.services.supabase import SupabaseService
                supabase = SupabaseService()
                agent = supabase.get_agent_by_id(agent_id)

                if not agent:
                    logger.warning(f"[FAILED SEND RECOVERY] Agente {agent_id[:8]} não encontrado")
                    await redis.cache_delete(key)
                    failed += 1
                    continue

                # Criar serviço UAZAPI com credenciais do agente
                uazapi = UazapiService(
                    base_url=agent.get("uazapi_base_url", ""),
                    api_key=agent.get("uazapi_token", ""),
                )

                agent_name = agent.get("name", "Assistente")
                logger.info(
                    f"[FAILED SEND RECOVERY] Tentando reenviar para {phone} "
                    f"(tentativa {attempts + 1}/{max_attempts}, agente={agent_name})"
                )

                # Tentar reenviar com assinatura do agente
                send_result = await uazapi.send_ai_response(phone, text, agent_name, delay=2.0)

                if send_result["all_success"]:
                    # Sucesso! Remover da fila
                    await redis.cache_delete(key)
                    recovered += 1
                    logger.info(f"[FAILED SEND RECOVERY] Mensagem reenviada com sucesso para {phone}")
                else:
                    # Falhou novamente - atualizar contador
                    payload["attempts"] = attempts + 1
                    payload["last_error"] = send_result.get("first_error")
                    await redis.cache_set(key, payload, ttl=86400)
                    logger.warning(
                        f"[FAILED SEND RECOVERY] Falha ao reenviar para {phone}. "
                        f"Tentativas: {attempts + 1}/{max_attempts}"
                    )
                    failed += 1

                # Delay entre tentativas para não sobrecarregar
                await asyncio.sleep(1.0)

            except Exception as e:
                logger.error(f"[FAILED SEND RECOVERY] Erro ao processar {key}: {e}")
                failed += 1

        logger.info(
            f"[FAILED SEND RECOVERY] Concluído: {recovered} reenviados, {failed} falhas",
            extra={"recovered": recovered, "failed": failed},
        )

    except Exception as e:
        logger.error(f"[FAILED SEND RECOVERY] Erro geral: {e}")


# =============================================================================
# LIFESPAN MANAGEMENT
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Startup:
        - Connect to Redis
        - Initialize Gemini service with function declarations
        - Calendar tools are registered per-agent via OAuth (in webhook handler)

    Shutdown:
        - Disconnect from Redis
        - Cleanup resources
    """
    logger.info(
        "Starting Agente IA",
        app_name=settings.app_name,
        environment=settings.app_env,
        port=settings.port,
    )

    app_state.startup_time = datetime.utcnow()

    # =========================================================================
    # STARTUP
    # =========================================================================

    # 1. Connect to Redis
    try:
        redis_service = await get_redis_service(settings.redis_url)
        app_state.redis_connected = True
        logger.info("Redis connected successfully", redis_url=settings.redis_url[:30] + "...")

        # 1.1 Recover orphan buffers from previous restart
        await recover_orphan_buffers()

        # 1.2 Recover failed sends from previous failures
        await recover_failed_sends()

    except Exception as e:
        logger.error("Failed to connect to Redis", error=str(e))
        app_state.redis_connected = False

    # 2. Initialize Gemini service with function declarations
    try:
        gemini_service = get_gemini_service()
        gemini_service.initialize(
            function_declarations=FUNCTION_DECLARATIONS,
            system_instruction=None,  # Will be set per-agent in webhook
        )
        app_state.gemini_initialized = True
        logger.info(
            "Gemini service initialized",
            model=gemini_service.model_name,
            tools_count=len(FUNCTION_DECLARATIONS),
        )
    except Exception as e:
        logger.error("Failed to initialize Gemini service", error=str(e))
        app_state.gemini_initialized = False

    # Note: Calendar/timezone/transfer tool handlers are created dynamically
    # per-request in whatsapp.py with per-agent OAuth credentials.
    # No startup registration needed.

    # 3. Start APScheduler for billing charge job
    scheduler = None
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = AsyncIOScheduler()
        # Reconciliacao: 6h horario de Brasilia, seg-sex (ANTES do billing charge)
        scheduler.add_job(
            run_billing_reconciliation_job,
            CronTrigger(hour=6, minute=0, day_of_week="mon-fri", timezone="America/Sao_Paulo"),
            id="billing_reconciliation",
            name="Billing Reconciliation Job",
            replace_existing=True,
        )
        # Cobranca: 9h horario de Brasilia, seg-sex (DEPOIS da reconciliacao)
        scheduler.add_job(
            run_billing_charge_job,
            CronTrigger(hour=9, minute=0, day_of_week="mon-fri", timezone="America/Sao_Paulo"),
            id="billing_charge",
            name="Billing Charge Job",
            replace_existing=True,
        )
        # Calendar confirmation: a cada 30 minutos
        from apscheduler.triggers.interval import IntervalTrigger
        scheduler.add_job(
            run_calendar_confirmation_job,
            IntervalTrigger(minutes=30),
            id="calendar_confirmation",
            name="Calendar Confirmation Job",
            replace_existing=True,
        )
        # Follow-up (Salvador): a cada 5 minutos
        scheduler.add_job(
            run_follow_up_job,
            IntervalTrigger(minutes=5),
            id="follow_up",
            name="Follow Up Job (Salvador)",
            replace_existing=True,
        )
        # Manutencao preventiva (ANA/Lazaro): 09:00 dias uteis, timezone Cuiaba
        scheduler.add_job(
            run_maintenance_notifier_job,
            CronTrigger(hour=9, minute=0, day_of_week="mon-fri", timezone="America/Cuiaba"),
            id="maintenance_notifier",
            name="Maintenance Notifier Job (ANA)",
            replace_existing=True,
        )
        scheduler.start()
        app_state.scheduler = scheduler
        logger.info("APScheduler started: billing_reconciliation (6h seg-sex), billing_charge (9h seg-sex), calendar_confirmation (30min), follow_up (5min), maintenance_notifier (9h seg-sex Cuiaba)")
    except ImportError:
        logger.warning("APScheduler not installed, billing charge job will not run automatically")
    except Exception as e:
        logger.error("Failed to start APScheduler", error=str(e))

    logger.info("Agente IA startup complete")

    # =========================================================================
    # YIELD - Application runs here
    # =========================================================================
    yield

    # =========================================================================
    # SHUTDOWN
    # =========================================================================

    logger.info("Shutting down Agente IA")

    # 0. Stop APScheduler
    if scheduler:
        try:
            scheduler.shutdown(wait=False)
            logger.info("APScheduler stopped")
        except Exception as e:
            logger.error("Error stopping APScheduler", error=str(e))

    # 1. Disconnect from Redis
    try:
        await close_redis_service()
        app_state.redis_connected = False
        logger.info("Redis disconnected successfully")
    except Exception as e:
        logger.error("Error disconnecting from Redis", error=str(e))

    logger.info("Agente IA shutdown complete")


# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

app = FastAPI(
    title=settings.app_name,
    description="AI-powered WhatsApp agent orchestrator",
    version="1.0.0",
    docs_url="/docs" if settings.is_development else None,
    redoc_url="/redoc" if settings.is_development else None,
    lifespan=lifespan,
)


# =============================================================================
# MIDDLEWARES
# =============================================================================

# CORS - Allow all origins for development, restrict in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# ROUTES - Include routers
# =============================================================================

# WhatsApp webhook router (legacy path: /api/webhook/whatsapp)
from app.webhooks.mensagens import router as whatsapp_router
app.include_router(whatsapp_router, prefix="/api", tags=["webhooks"])

# Dashboard API router
from app.api.dashboard import router as dashboard_router
app.include_router(dashboard_router, tags=["dashboard"])

# Google OAuth router
from app.api.google_oauth import router as google_oauth_router
app.include_router(google_oauth_router, prefix="/api/google/oauth", tags=["google-oauth"])

# Auth router
from app.api.auth import router as auth_router
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])

# Agents CRUD router
from app.api.agentes import agents_router
app.include_router(agents_router, prefix="/api", tags=["agents"])

# Dynamic webhook router (main path: /webhooks/dynamic)
from app.webhooks.mensagens import router as whatsapp_router_dynamic, get_webhook_handler
from fastapi import APIRouter, BackgroundTasks, Request

webhooks_router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@webhooks_router.post("/dynamic")
async def webhooks_dynamic_post(
    request: Request,
    background_tasks: BackgroundTasks,
) -> Dict[str, Any]:
    """
    Main webhook endpoint for WhatsApp messages (UAZAPI).

    This is the primary endpoint that matches the agnes-agent URL pattern.
    Processes messages and routes them to the appropriate handler.
    """
    try:
        body = await request.json()

        # DEBUG: Ver o que está chegando
        event_type = body.get("event") or body.get("type") or body.get("EventType")
        logger.debug("[WEBHOOK DEBUG] Event: %s, Payload preview: %s", event_type, str(body)[:300])

        # Check event type

        # Ignore non-message events
        if event_type and event_type not in ["messages.upsert", "message", "messages"]:
            logger.debug("Event ignored", event_type=event_type)
            return {"status": "ignored", "reason": f"event_type_{event_type}"}

        # Process message
        handler = get_webhook_handler()
        result = await handler.handle_message(body, background_tasks)

        return result

    except Exception as e:
        logger.error("Error in /webhooks/dynamic", error=str(e), exc_info=True)
        return {"status": "error", "message": str(e)}


@webhooks_router.get("/dynamic")
async def webhooks_dynamic_get() -> Dict[str, Any]:
    """
    Webhook verification endpoint.

    Used by UAZAPI to verify the webhook is active.
    """
    return {
        "status": "ok",
        "service": "agente-ia",
        "webhook": "dynamic",
        "timestamp": datetime.utcnow().isoformat(),
    }


app.include_router(webhooks_router)

# Asaas payment webhook router
from app.webhooks.pagamentos import router as asaas_webhook_router
app.include_router(asaas_webhook_router, prefix="/webhooks", tags=["webhooks"])

# Diana v2 - Prospecao ativa
from app.api.diana import router as diana_router
app.include_router(diana_router, prefix="/api/diana", tags=["diana"])

# Athena Oraculo - Analytics com linguagem natural
from app.api.athena import router as athena_router
app.include_router(athena_router, prefix="/api/athena", tags=["athena"])


# =============================================================================
# LEADBOX WEBHOOK
# =============================================================================

@app.post("/webhooks/leadbox", tags=["webhooks"])
async def leadbox_webhook(request: Request, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """
    Webhook endpoint para receber eventos do Leadbox.
    Atualiza current_queue_id e pausa/reativa IA baseado na fila.

    REGRA: Se queue != queue_ia do agente, PAUSA imediatamente.
    """
    from app.services.supabase import get_supabase_service

    body = await request.json()

    event_type = body.get("event") or body.get("type") or "unknown"
    logger.info("[LEADBOX WEBHOOK] Evento recebido: %s", event_type)

    # ==========================================================================
    # FILTRAR EVENTOS DESNECESSÁRIOS
    # Esses eventos não precisam de processamento - ignorar logo no início
    # ==========================================================================
    IGNORED_EVENTS = {"AckMessage", "FinishedTicketHistoricMessages"}
    if event_type in IGNORED_EVENTS:
        logger.debug("[LEADBOX WEBHOOK] Evento ignorado: %s", event_type)
        return {"status": "ignored", "reason": f"event_{event_type}"}

    # Log payload para diagnóstico (primeiros 800 chars) - só para eventos relevantes
    logger.info("[LEADBOX WEBHOOK] Payload: %s", _json.dumps(body, default=str)[:800])

    # ==========================================================================
    # PROCESSAR MENSAGEM DO LEAD (substitui webhook UAZAPI)
    # Quando evento é NewMessage e fromMe=false, processar com IA
    # ==========================================================================
    if event_type == "NewMessage":
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

        # Se for imagem, usar placeholder [image recebido] (mesmo formato do whatsapp.py)
        media_url = message_data.get("mediaUrl", "")
        if media_type in ["image", "imageMessage"] and not msg_body:
            msg_body = "[image recebido]"
            logger.info("[LEADBOX MESSAGE] Imagem detectada - messageId=%s, mediaUrl=%s", message_id, media_url[:100] if media_url else "None")

        # =======================================================================
        # CAPTURAR MENSAGENS DO HUMANO NO HISTÓRICO
        # Quando humano responde (fromMe=True), salvar no histórico como "model"
        # Assim a IA fica "consciente" do que o humano conversou
        # IMPORTANTE: Ignorar mensagens enviadas pela API (sendType=API) pois são
        # respostas da própria IA e já foram salvas pelo whatsapp.py
        # =======================================================================
        send_type = message_data.get("sendType", "")
        is_api_message = send_type == "API"

        if from_me and msg_body and ticket_id and not is_api_message:
            logger.info("[LEADBOX MESSAGE] Mensagem do HUMANO detectada - ticketId=%s", ticket_id)

            try:
                from app.services.supabase import get_supabase_service
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
                        import httpx
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

        # =======================================================================
        # PROCESSAR MENSAGENS DO LEAD COM IA
        # Quando lead envia (fromMe=False), processar com Gemini
        # =======================================================================
        elif not from_me and msg_body and ticket_id:
            logger.info("[LEADBOX MESSAGE] Nova mensagem recebida - ticketId=%s, tenant=%s", ticket_id, tenant_id)

            try:
                # Buscar agente pelo tenant_id para obter credenciais API
                from app.services.supabase import get_supabase_service
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
                else:
                    # Extrair credenciais Leadbox do leadbox_config
                    leadbox_config = target_agent.get("leadbox_config") or {}
                    lb_api_url = leadbox_config.get("api_url", "")
                    lb_api_token = leadbox_config.get("api_token", "")

                    if not lb_api_url or not lb_api_token:
                        logger.warning("[LEADBOX MESSAGE] Agente %s sem credenciais Leadbox configuradas", target_agent.get("name"))
                    else:
                        # Buscar dados do ticket via API para obter telefone do contato
                        import httpx
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
    # Se status="closed" ou closedAt não é null, limpar ticket_id do lead
    # ==========================================================================
    ticket_status = ticket.get("status", "")
    closed_at = ticket.get("closedAt")

    if phone and (ticket_status == "closed" or closed_at is not None):
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
                    from app.services.redis import get_redis_service
                    try:
                        redis_svc = await get_redis_service()
                        agent_id = ag.get("id")
                        if agent_id:
                            await redis_svc.pause_remove(agent_id, clean_phone)
                            logger.debug("[LEADBOX WEBHOOK] Pausa Redis removida para %s", phone)
                    except Exception as redis_err:
                        logger.debug("[LEADBOX WEBHOOK] Erro ao remover pausa Redis: %s", redis_err)

                    logger.info("[LEADBOX WEBHOOK] Ticket fechado - lead %s resetado para IA em %s", phone, table_leads)
                except Exception as e:
                    logger.debug("[LEADBOX WEBHOOK] Erro ao limpar ticket_id em %s: %s", table_leads, e)

        except Exception as e:
            logger.warning("[LEADBOX WEBHOOK] Erro ao processar ticket fechado: %s", e)

        return {"status": "ok", "event": "ticket_closed", "ticket_id": ticket_id}

    if phone and queue_id:
        logger.info("[LEADBOX WEBHOOK] Lead %s | ticket=%s | queue=%s | user=%s | tenant=%s", phone, ticket_id, queue_id, user_id, payload_tenant_id)

        try:
            supabase_svc = get_supabase_service()

            # Buscar TODOS os agentes ativos com table_leads
            # NAO filtrar por handoff_triggers.enabled - qualquer agente pode ter o lead
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
                # Se o payload tem tenant_id, APENAS agentes com o mesmo tenant_id devem ser atualizados.
                # Agentes sem tenant_id (null) sao ignorados quando o payload tem tenant_id.
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
                    # current_queue_id pode nao existir em tabelas antigas (bug de schema)
                    # Isso evita que uma coluna faltando silencia todo o webhook
                    result = supabase_svc.client.table(table_leads) \
                        .select("id,remotejid") \
                        .eq("remotejid", remotejid) \
                        .limit(1) \
                        .execute()

                    if not result.data:
                        # Race condition: webhook Leadbox chegou ANTES do webhook WhatsApp criar o lead
                        # Criar lead automaticamente com dados do Leadbox
                        contact_name = contact.get("name", "").strip()
                        if not contact_name:
                            contact_name = f"Lead {phone}"

                        logger.info(
                            "[LEADBOX WEBHOOK] Lead %s nao existe - CRIANDO automaticamente (race condition detectada) | tenant=%s | agent=%s",
                            phone, payload_tenant_id, agent_name
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
                                "Atendimento_Finalizado": "false",  # IA ativa
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
                                # Lead criado, prosseguir normalmente (não continue)
                            else:
                                logger.error("[LEADBOX WEBHOOK] Falha ao criar lead %s - resultado vazio", phone)
                                continue

                        except Exception as create_err:
                            logger.error("[LEADBOX WEBHOOK] Erro ao criar lead %s: %s", phone, create_err)
                            continue

                    lead_found = True
                    agent_id = ag.get("id", "")
                    QUEUE_IA = int(ht.get("queue_ia", 537))
                    table_messages = ag.get("table_messages")

                    # Construir set de todas as filas de IA (principal + dispatch departments)
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
                    # Tabelas criadas antes da migration podem nao ter essa coluna
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

                    logger.info("[LEADBOX WEBHOOK] Agente: %s | tenant: %s | queue_anterior: %s", agent_name, agent_tenant_id, previous_queue_id)

                    update_data = {
                        "current_queue_id": queue_id,
                        "current_user_id": user_id,
                        "ticket_id": ticket_id,
                    }

                    if int(queue_id) in IA_QUEUES:
                        # =============================================================
                        # FILA DE IA: SEMPRE forçar userId da IA e reativar atendimento
                        # =============================================================
                        # REGRA DE NEGÓCIO: Na fila de IA, quem manda é a IA.
                        # Não importa qual userId veio no webhook (813, 1090, null, etc.)
                        # O userId DEVE ser forçado para queue_ia_user_id (ex: 1095)
                        # =============================================================

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
                            # =========================================================
                            # ANTI-LOOP: Se userId já é o correto, apenas atualiza e sai
                            # =========================================================
                            # Quando assign_user_silent atribui userId=1095, Leadbox
                            # dispara webhook de volta. Sem esse check, processaríamos
                            # desnecessariamente todo o webhook novamente.
                            # =========================================================
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
                                # Salva e continua para próximo agente (não processa mais)
                            else:
                                # =====================================================
                                # FORÇAR AUTO-ASSIGN: userId diferente do esperado
                                # =====================================================
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
                            # Se previous_queue_id e None (lead novo) ou != 472, inserir mensagem
                            if agent_id == "b3f217f4-5112-4d7a-b597-edac2ccfe6b5":
                                if previous_queue_id is None or int(previous_queue_id) != 472:
                                    if table_messages:
                                        try:
                                            # Buscar conversation_history atual
                                            msg_result = supabase_svc.client.table(table_messages) \
                                                .select("conversation_history") \
                                                .eq("remotejid", remotejid) \
                                                .limit(1) \
                                                .execute()

                                            current_history = {"messages": []}
                                            if msg_result.data and msg_result.data[0].get("conversation_history"):
                                                current_history = msg_result.data[0]["conversation_history"]

                                            messages = current_history.get("messages", [])

                                            # Verificar se ultima mensagem ja e "12" (evitar duplicatas)
                                            last_msg = messages[-1] if messages else None
                                            is_already_12 = False
                                            if last_msg:
                                                parts = last_msg.get("parts", [])
                                                if last_msg.get("role") == "user" and parts and parts[0].get("text") == "12":
                                                    is_already_12 = True

                                            if not is_already_12:
                                                # Adicionar mensagem automatica
                                                auto_message = {
                                                    "role": "user",
                                                    "parts": [{"text": "12"}],
                                                    "timestamp": datetime.utcnow().isoformat()
                                                }
                                                messages.append(auto_message)
                                                current_history["messages"] = messages

                                                # Salvar conversation_history atualizado
                                                supabase_svc.client.table(table_messages) \
                                                    .upsert({
                                                        "remotejid": remotejid,
                                                        "conversation_history": current_history,
                                                        "Msg_user": datetime.utcnow().isoformat()
                                                    }, on_conflict="remotejid") \
                                                    .execute()

                                                logger.info("[LEADBOX WEBHOOK] AGNES LEADBOX: Mensagem '12' inserida | lead=%s | queue_anterior=%s", phone, previous_queue_id)
                                            else:
                                                logger.warning("[LEADBOX WEBHOOK] AGNES LEADBOX: Mensagem '12' ja existe, ignorando duplicata | lead=%s", phone)
                                        except Exception as msg_err:
                                            logger.error("[LEADBOX WEBHOOK] Erro ao inserir mensagem '12': %s", msg_err)

                            # ================================================================
                            # INJEÇÃO DE CONTEXTO PARA OUTROS AGENTES (ANA/LAZARO)
                            # Quando lead retorna de fila humana para fila IA,
                            # injetamos contexto informando o que provavelmente aconteceu
                            # A mensagem vem da config: departments.X.context_injection.message
                            # ================================================================
                            elif previous_queue_id is not None:
                                # Mapear filas humanas para seus contextos
                                # Estrutura: {queue_id: (nome_fila, contexto_para_ia)}
                                # NOTA: 'ht' já contém handoff_triggers (definido na linha 614)
                                departments = ht.get("departments") or {}

                                # Construir mapa de filas humanas dinamicamente
                                # Lê context_injection de cada departamento se configurado
                                human_queue_contexts = {}
                                for dept_key, dept_data in departments.items():
                                    dept_id = dept_data.get("id")
                                    dept_name = dept_data.get("name", dept_key)
                                    context_injection = dept_data.get("context_injection") or {}

                                    if dept_id:
                                        # Se context_injection está configurado e habilitado, usa a mensagem customizada
                                        if context_injection.get("enabled") and context_injection.get("message"):
                                            human_queue_contexts[int(dept_id)] = (
                                                dept_name,
                                                f"[CONTEXTO AUTOMÁTICO] {context_injection['message']}"
                                            )
                                        # Fallback: mensagens padrão se não houver config
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
                                        # Buscar conversation_history atual
                                        msg_result = supabase_svc.client.table(table_messages) \
                                            .select("conversation_history") \
                                            .eq("remotejid", remotejid) \
                                            .limit(1) \
                                            .execute()

                                        current_history = {"messages": []}
                                        if msg_result.data and msg_result.data[0].get("conversation_history"):
                                            current_history = msg_result.data[0]["conversation_history"]

                                        messages = current_history.get("messages", [])

                                        # Verificar se última mensagem já é contexto (evitar duplicatas)
                                        last_msg = messages[-1] if messages else None
                                        is_already_context = False
                                        if last_msg:
                                            parts = last_msg.get("parts", [])
                                            if parts and "[CONTEXTO AUTOMÁTICO]" in str(parts[0].get("text", "")):
                                                is_already_context = True

                                        if not is_already_context:
                                            # Adicionar mensagem de contexto como "system" (role especial para contexto)
                                            # Usamos "user" para Gemini entender, mas marcamos claramente como contexto
                                            context_message = {
                                                "role": "user",
                                                "parts": [{"text": context_msg}],
                                                "timestamp": datetime.utcnow().isoformat(),
                                                "is_context_injection": True
                                            }
                                            messages.append(context_message)
                                            current_history["messages"] = messages

                                            # Salvar conversation_history atualizado
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
                    else:
                        update_data["Atendimento_Finalizado"] = "true"
                        update_data["paused_at"] = datetime.utcnow().isoformat()
                        logger.info("[LEADBOX WEBHOOK] Lead %s na fila %s (NAO esta em filas IA %s) - PAUSANDO IMEDIATAMENTE", phone, queue_id, IA_QUEUES)
                        try:
                            redis_svc = await get_redis_service()
                            await redis_svc.pause_set(agent_id, clean_phone)
                            logger.info("[LEADBOX WEBHOOK] Redis pause SETADA para agent=%s phone=%s", agent_id[:8], clean_phone)
                        except Exception as re:
                            logger.warning("[LEADBOX WEBHOOK] Erro ao setar Redis pause: %s", re)

                    # UPDATE em duas etapas para evitar falha por colunas inexistentes:
                    # 1. Atualiza colunas criticas de pausa/reativacao (sempre existem)
                    core_update = {k: v for k, v in update_data.items()
                                   if k not in ("current_queue_id", "current_user_id", "ticket_id")}
                    if core_update:
                        supabase_svc.client.table(table_leads) \
                            .update(core_update) \
                            .eq("remotejid", remotejid) \
                            .execute()
                        logger.info("[LEADBOX WEBHOOK] Core update OK: %s | dados=%s", table_leads, list(core_update.keys()))

                    # 2. Atualiza colunas de fila (current_queue_id, etc.) com fallback seguro
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
                            logger.warning("[LEADBOX WEBHOOK] Queue update falhou em %s (colunas podem estar faltando): %s", table_leads, qu)

                    logger.info("[LEADBOX WEBHOOK] Supabase atualizado: %s | queue=%s | user=%s", table_leads, queue_id, user_id)
                    break  # Lead encontrado e processado, sair do loop

                except Exception as e:
                    logger.error("[LEADBOX WEBHOOK] Erro ao buscar/atualizar lead em %s: %s", table_leads, e)

            if not lead_found:
                logger.warning("[LEADBOX WEBHOOK] Lead %s (%s) NAO encontrado em nenhuma tabela de agentes", phone, remotejid)

        except Exception as e:
            logger.debug("[LEADBOX WEBHOOK] Erro geral: %s", e)
    else:
        logger.warning("[LEADBOX WEBHOOK] Payload sem phone ou queueId: phone=%s, queue=%s", phone, queue_id)
        logger.warning("[LEADBOX WEBHOOK] Keys no payload: %s", list(body.keys())[:10])

    return {"status": "ok", "event": event_type}


# =============================================================================
# FILE UPLOAD ENDPOINTS
# =============================================================================

UPLOAD_DIR = "/var/www/phant/crm/uploads"
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".pdf", ".txt", ".csv", ".json"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


@app.post("/api/upload", tags=["uploads"])
async def upload_file(file: UploadFile = File(...)) -> Dict[str, Any]:
    """Upload a file to the CRM uploads directory."""
    try:
        if not file.filename:
            return {"success": False, "error": "Nome do arquivo ausente"}

        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            return {"success": False, "error": f"Tipo de arquivo nao permitido: {ext}"}

        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            return {"success": False, "error": "Arquivo muito grande. Max 5MB."}

        # Gerar nome unico para evitar colisoes
        safe_name = f"{uuid.uuid4().hex[:8]}_{file.filename.replace(' ', '_')}"
        filepath = os.path.join(UPLOAD_DIR, safe_name)

        os.makedirs(UPLOAD_DIR, exist_ok=True)

        with open(filepath, "wb") as f:
            f.write(content)

        logger.debug("[UPLOAD] Arquivo salvo: %s (%s bytes)", safe_name, len(content))
        return {"success": True, "filename": safe_name, "url": f"/uploads/{safe_name}"}

    except Exception as e:
        logger.debug("[UPLOAD] Erro: %s", e)
        return {"success": False, "error": str(e)}


@app.get("/api/uploads", tags=["uploads"])
async def list_uploads() -> List[Dict[str, str]]:
    """List all uploaded files."""
    try:
        if not os.path.exists(UPLOAD_DIR):
            return []

        files = []
        for filename in sorted(os.listdir(UPLOAD_DIR)):
            filepath = os.path.join(UPLOAD_DIR, filename)
            if os.path.isfile(filepath):
                files.append({
                    "filename": filename,
                    "url": f"/uploads/{filename}",
                })
        return files

    except Exception as e:
        logger.debug("[UPLOAD] Erro ao listar: %s", e)
        return []


@app.delete("/api/upload/{filename}", tags=["uploads"])
async def delete_upload(filename: str) -> Dict[str, Any]:
    """Delete an uploaded file."""
    try:
        filepath = os.path.join(UPLOAD_DIR, filename)

        # Prevenir path traversal
        if not os.path.abspath(filepath).startswith(os.path.abspath(UPLOAD_DIR)):
            return {"success": False, "error": "Caminho invalido"}

        if not os.path.exists(filepath):
            return {"success": False, "error": "Arquivo nao encontrado"}

        os.remove(filepath)
        logger.debug("[UPLOAD] Arquivo removido: %s", filename)
        return {"success": True}

    except Exception as e:
        logger.debug("[UPLOAD] Erro ao remover: %s", e)
        return {"success": False, "error": str(e)}


# =============================================================================
# JOBS ENDPOINTS
# =============================================================================

@app.post("/api/jobs/billing-charge/run", tags=["jobs"])
async def run_billing_charge_manually(background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """
    Executa o job de cobranca manualmente.
    Roda em background para nao bloquear a request.
    """
    if await is_billing_charge_running():
        return {"status": "error", "message": "Job ja esta em execucao"}

    background_tasks.add_task(run_billing_charge_job)
    return {"status": "started", "message": "Billing charge job iniciado em background"}


@app.post("/api/jobs/billing-charge/run-force", tags=["jobs"])
async def run_billing_charge_force(background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """
    Executa o job de cobranca FORCANDO execucao (ignora verificacoes de horario/dia util).
    APENAS PARA DEBUG/TESTES.
    """
    if await is_billing_charge_running():
        return {"status": "error", "message": "Job ja esta em execucao"}

    background_tasks.add_task(_force_run_billing_charge)
    return {"status": "started", "message": "Billing charge job FORCADO iniciado em background"}


@app.get("/api/jobs/billing-charge/status", tags=["jobs"])
async def billing_charge_status() -> Dict[str, Any]:
    """Retorna o status do job de cobranca."""
    return {
        "running": await is_billing_charge_running(),
        "scheduler_active": app_state.scheduler is not None,
    }


# --- Calendar Confirmation Job Endpoints ---

@app.post("/api/jobs/calendar-confirmation/run", tags=["jobs"])
async def run_calendar_confirmation_manually(background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Executa o job de confirmacao de agenda manualmente."""
    if is_calendar_confirmation_running():
        return {"status": "error", "message": "Job ja esta em execucao"}

    background_tasks.add_task(run_calendar_confirmation_job)
    return {"status": "started", "message": "Calendar confirmation job iniciado em background"}


@app.post("/api/jobs/calendar-confirmation/run-force", tags=["jobs"])
async def run_calendar_confirmation_force(background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """
    Executa o job de confirmacao de agenda FORCANDO execucao.
    APENAS PARA DEBUG/TESTES.
    """
    if is_calendar_confirmation_running():
        return {"status": "error", "message": "Job ja esta em execucao"}

    background_tasks.add_task(_force_run_calendar_confirmation)
    return {"status": "started", "message": "Calendar confirmation job FORCADO iniciado em background"}


@app.get("/api/jobs/calendar-confirmation/status", tags=["jobs"])
async def calendar_confirmation_status() -> Dict[str, Any]:
    """Retorna o status do job de confirmacao de agenda."""
    return {
        "running": is_calendar_confirmation_running(),
        "scheduler_active": app_state.scheduler is not None,
    }


# --- Follow-Up Job Endpoints ---

@app.post("/api/jobs/follow-up/run", tags=["jobs"])
async def run_follow_up_manually(background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Executa o job de follow-up manualmente (respeita horario comercial)."""
    if is_follow_up_running():
        return {"status": "error", "message": "Job ja esta em execucao"}

    background_tasks.add_task(run_follow_up_job)
    return {"status": "started", "message": "Follow-up job iniciado em background"}


@app.post("/api/jobs/follow-up/run-force", tags=["jobs"])
async def run_follow_up_force(background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """
    Executa o job de follow-up FORCANDO execucao (ignora verificacoes de horario/dia util).
    APENAS PARA DEBUG/TESTES.
    """
    if is_follow_up_running():
        return {"status": "error", "message": "Job ja esta em execucao"}

    background_tasks.add_task(_force_run_follow_up)
    return {"status": "started", "message": "Follow-up job FORCADO iniciado em background"}


@app.get("/api/jobs/follow-up/status", tags=["jobs"])
async def follow_up_status() -> Dict[str, Any]:
    """Retorna o status do job de follow-up."""
    return {
        "running": is_follow_up_running(),
        "scheduler_active": app_state.scheduler is not None,
    }


# --- Billing Reconciliation Job Endpoints ---

@app.post("/api/jobs/billing-reconciliation/run", tags=["jobs"])
async def run_billing_reconciliation_manually(background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """
    Executa o job de reconciliacao de cobrancas manualmente.
    Sincroniza asaas_cobrancas com API Asaas (fonte da verdade).
    """
    if await is_billing_reconciliation_running():
        return {"status": "error", "message": "Job ja esta em execucao"}

    background_tasks.add_task(run_billing_reconciliation_job)
    return {"status": "started", "message": "Billing reconciliation job iniciado em background"}


@app.post("/api/jobs/billing-reconciliation/run-force", tags=["jobs"])
async def run_billing_reconciliation_force(background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """
    Executa o job de reconciliacao FORCANDO execucao.
    APENAS PARA DEBUG/TESTES.
    """
    if await is_billing_reconciliation_running():
        return {"status": "error", "message": "Job ja esta em execucao"}

    background_tasks.add_task(_force_run_billing_reconciliation)
    return {"status": "started", "message": "Billing reconciliation job FORCADO iniciado em background"}


@app.get("/api/jobs/billing-reconciliation/status", tags=["jobs"])
async def billing_reconciliation_status() -> Dict[str, Any]:
    """Retorna o status do job de reconciliacao."""
    return {
        "running": await is_billing_reconciliation_running(),
        "scheduler_active": app_state.scheduler is not None,
    }


# --- Maintenance Notifier Job Endpoints ---

@app.post("/api/jobs/maintenance-notifier/run", tags=["jobs"])
async def run_maintenance_notifier_manually(background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """
    Executa o job de notificacao de manutencao preventiva manualmente.
    Respeita verificacoes de dia util e horario comercial.
    """
    if is_maintenance_notifier_running():
        return {"status": "error", "message": "Job ja esta em execucao"}

    background_tasks.add_task(run_maintenance_notifier_job)
    return {"status": "started", "message": "Maintenance notifier job iniciado em background"}


@app.post("/api/jobs/maintenance-notifier/run-force", tags=["jobs"])
async def run_maintenance_notifier_force(background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """
    Executa o job de notificacao de manutencao FORCANDO execucao.
    Ignora verificacoes de horario/dia util. APENAS PARA DEBUG/TESTES.
    """
    if is_maintenance_notifier_running():
        return {"status": "error", "message": "Job ja esta em execucao"}

    background_tasks.add_task(_force_run_maintenance_notifier)
    return {"status": "started", "message": "Maintenance notifier job FORCADO iniciado em background"}


@app.get("/api/jobs/maintenance-notifier/status", tags=["jobs"])
async def maintenance_notifier_status() -> Dict[str, Any]:
    """Retorna o status do job de manutencao preventiva."""
    return {
        "running": is_maintenance_notifier_running(),
        "scheduler_active": app_state.scheduler is not None,
    }


# =============================================================================
# MANUTENCAO SLOTS - Consulta de disponibilidade
# =============================================================================

@app.get("/api/manutencao/slots", tags=["manutencao"])
async def get_slots_manutencao(
    data: str,
    agent_id: str = "14e6e5ce-4627-4e38-aac8-f0191669ff53"
) -> Dict[str, Any]:
    """
    Retorna a disponibilidade de slots de manutencao em uma data.

    Query params:
        data: Data no formato YYYY-MM-DD (ex: 2026-02-20)
        agent_id: ID do agente (default: Lazaro)

    Response 200:
        {
            "success": true,
            "data": {
                "data": "2026-02-20",
                "manha": true,
                "tarde": false,
                "algum_disponivel": true
            }
        }

    Response 400:
        { "success": false, "error": "mensagem", "statusCode": 400 }
    """
    from datetime import date as date_type
    from app.services.manutencao_slots import listar_slots_disponiveis

    try:
        data_obj = date_type.fromisoformat(data)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": f"Data invalida: '{data}'. Use o formato YYYY-MM-DD.",
                "statusCode": 400,
            }
        )

    slots = listar_slots_disponiveis(data_obj, agent_id)
    return {
        "success": True,
        "data": slots,
    }


@app.get("/api/manutencao/slots/semana", tags=["manutencao"])
async def get_slots_semana(
    data_inicio: str,
    agent_id: str = "14e6e5ce-4627-4e38-aac8-f0191669ff53"
) -> Dict[str, Any]:
    """
    Retorna a disponibilidade de slots de manutencao para os proximos 7 dias.

    Query params:
        data_inicio: Data inicial no formato YYYY-MM-DD
        agent_id: ID do agente (default: Lazaro)

    Response 200:
        {
            "success": true,
            "data": {
                "dias": [
                    { "data": "2026-02-20", "manha": true, "tarde": false, "algum_disponivel": true },
                    ...
                ]
            }
        }
    """
    from datetime import date as date_type, timedelta
    from app.services.manutencao_slots import listar_slots_disponiveis

    try:
        data_obj = date_type.fromisoformat(data_inicio)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": f"Data invalida: '{data_inicio}'. Use o formato YYYY-MM-DD.",
                "statusCode": 400,
            }
        )

    dias = []
    for i in range(7):
        d = data_obj + timedelta(days=i)
        slots = listar_slots_disponiveis(d, agent_id)
        dias.append(slots)

    return {
        "success": True,
        "data": {"dias": dias},
    }


# =============================================================================
# REANALYZE LEADS (OBSERVER BATCH)
# =============================================================================

_reanalyze_running: bool = False
_reanalyze_progress: Dict[str, Any] = {}


async def _run_reanalyze_leads(agent_id: str, batch_size: int = 50) -> Dict[str, Any]:
    """
    Processa todos os leads de um agente com o Observer Service.

    Extrai insights de todas as conversas:
    - origin (facebook_ads, instagram, google_ads, etc)
    - speakers (quem falou na conversa)
    - sentiment (positivo, neutro, negativo)
    - summary (resumo da conversa)

    Args:
        agent_id: ID do agente
        batch_size: Numero de leads por batch

    Returns:
        Estatisticas do processamento
    """
    global _reanalyze_running, _reanalyze_progress

    from app.services.supabase import get_supabase_service
    from app.services.observer.observer import get_observer_service

    _reanalyze_running = True
    _reanalyze_progress = {
        "agent_id": agent_id,
        "status": "running",
        "total": 0,
        "processed": 0,
        "success": 0,
        "errors": 0,
        "skipped": 0,
        "started_at": datetime.utcnow().isoformat(),
        "finished_at": None,
    }

    try:
        supabase = get_supabase_service()
        observer = get_observer_service()

        # Buscar agente
        agent = supabase.get_agent_by_id(agent_id)
        if not agent:
            _reanalyze_progress["status"] = "error"
            _reanalyze_progress["error"] = f"Agente {agent_id} nao encontrado"
            return _reanalyze_progress

        table_leads = agent.get("table_leads")
        table_messages = agent.get("table_messages")

        if not table_leads or not table_messages:
            _reanalyze_progress["status"] = "error"
            _reanalyze_progress["error"] = "Agente sem table_leads ou table_messages configurado"
            return _reanalyze_progress

        # Contar total de leads
        total_leads = supabase.count_leads(table_leads)
        _reanalyze_progress["total"] = total_leads

        logger.info(
            f"[REANALYZE] Iniciando processamento de {total_leads} leads para agente {agent.get('name', agent_id)}"
        )

        offset = 0
        while offset < total_leads:
            # Buscar batch de leads
            leads = supabase.get_all_leads(table_leads, limit=batch_size, offset=offset)

            for lead in leads:
                lead_id = lead.get("id")
                remotejid = lead.get("remotejid")
                lead_name = lead.get("nome", "Desconhecido")

                _reanalyze_progress["processed"] += 1
                _reanalyze_progress["current_lead"] = lead_name

                if not remotejid:
                    logger.debug(f"[REANALYZE] Lead {lead_id} sem remotejid, pulando")
                    _reanalyze_progress["skipped"] += 1
                    continue

                try:
                    # Verificar se tem historico
                    history = supabase.get_conversation_history(table_messages, remotejid)
                    if not history or not history.get("messages") or len(history.get("messages", [])) < 2:
                        logger.debug(f"[REANALYZE] Lead {lead_id} sem historico suficiente, pulando")
                        _reanalyze_progress["skipped"] += 1
                        continue

                    # Executar Observer
                    insights = await observer.analyze(
                        table_leads=table_leads,
                        table_messages=table_messages,
                        lead_id=lead_id,
                        remotejid=remotejid,
                        tools_used=None,
                        force=True,  # Ignora throttle
                        agent_id=agent_id,
                    )

                    if insights:
                        _reanalyze_progress["success"] += 1
                        origin = insights.get("origin", "unknown")
                        logger.debug(f"[REANALYZE] Lead {lead_id} ({lead_name}): origin={origin}")
                    else:
                        _reanalyze_progress["skipped"] += 1

                except Exception as e:
                    logger.error(f"[REANALYZE] Erro ao processar lead {lead_id}: {e}")
                    _reanalyze_progress["errors"] += 1

            offset += batch_size

            # Log de progresso a cada batch
            logger.info(
                f"[REANALYZE] Progresso: {_reanalyze_progress['processed']}/{total_leads} "
                f"(success={_reanalyze_progress['success']}, errors={_reanalyze_progress['errors']}, skipped={_reanalyze_progress['skipped']})"
            )

        _reanalyze_progress["status"] = "completed"
        _reanalyze_progress["finished_at"] = datetime.utcnow().isoformat()
        _reanalyze_progress.pop("current_lead", None)

        logger.info(
            f"[REANALYZE] Concluido! Total={total_leads}, Success={_reanalyze_progress['success']}, "
            f"Errors={_reanalyze_progress['errors']}, Skipped={_reanalyze_progress['skipped']}"
        )

        return _reanalyze_progress

    except Exception as e:
        logger.error(f"[REANALYZE] Erro fatal: {e}", exc_info=True)
        _reanalyze_progress["status"] = "error"
        _reanalyze_progress["error"] = str(e)
        _reanalyze_progress["finished_at"] = datetime.utcnow().isoformat()
        return _reanalyze_progress

    finally:
        _reanalyze_running = False


@app.post("/api/reanalyze-leads/{agent_id}", tags=["observer"])
async def reanalyze_leads(
    agent_id: str,
    background_tasks: BackgroundTasks,
    batch_size: int = 50,
) -> Dict[str, Any]:
    """
    Executa o Observer Service em batch para reler todas as conversas de um agente.

    Extrai e atualiza insights de origem (facebook_ads, instagram, google_ads, etc),
    speakers, sentiment e summary para todos os leads.

    Args:
        agent_id: ID do agente (tenant)
        batch_size: Numero de leads por batch (default: 50)

    Returns:
        Status do job iniciado
    """
    global _reanalyze_running

    if _reanalyze_running:
        return {
            "status": "error",
            "message": "Job de reanalise ja esta em execucao",
            "progress": _reanalyze_progress,
        }

    background_tasks.add_task(_run_reanalyze_leads, agent_id, batch_size)

    return {
        "status": "started",
        "message": f"Reanalise de leads iniciada para agente {agent_id}",
        "batch_size": batch_size,
    }


@app.get("/api/reanalyze-leads/status", tags=["observer"])
async def reanalyze_leads_status() -> Dict[str, Any]:
    """
    Retorna o status atual do job de reanalise de leads.

    Returns:
        Progresso do job (total, processed, success, errors, skipped)
    """
    return {
        "running": _reanalyze_running,
        "progress": _reanalyze_progress,
    }


# =============================================================================
# HEALTH ENDPOINTS
# =============================================================================

@app.get("/", tags=["root"])
async def root() -> Dict[str, Any]:
    """
    Root endpoint with application info.

    Returns:
        Basic application information
    """
    return {
        "name": settings.app_name,
        "version": "1.0.0",
        "environment": settings.app_env,
        "status": "running",
        "docs": "/docs" if settings.is_development else None,
    }


@app.get("/health", tags=["health"])
async def health_check() -> Dict[str, Any]:
    """
    Basic health check endpoint.

    Returns:
        Simple health status
    """
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/health/detailed", tags=["health"])
async def health_check_detailed() -> JSONResponse:
    """
    Detailed health check with status of all services.

    Returns:
        Comprehensive health status including:
        - Redis connection status
        - Gemini service status
        - Calendar service status
        - Uptime information
    """
    # Calculate uptime
    uptime_seconds = None
    if app_state.startup_time:
        uptime_seconds = (datetime.utcnow() - app_state.startup_time).total_seconds()

    # Check Redis health
    redis_healthy = False
    try:
        if app_state.redis_connected:
            redis_service = await get_redis_service(settings.redis_url)
            redis_healthy = await redis_service.health_check()
    except Exception:
        redis_healthy = False

    # Check Gemini health
    gemini_healthy = False
    try:
        if app_state.gemini_initialized:
            gemini_service = get_gemini_service()
            gemini_healthy = gemini_service.is_initialized
    except Exception:
        gemini_healthy = False

    # Build detailed status
    services = {
        "redis": {
            "status": "healthy" if redis_healthy else "unhealthy",
            "connected": app_state.redis_connected,
        },
        "gemini": {
            "status": "healthy" if gemini_healthy else "unhealthy",
            "initialized": app_state.gemini_initialized,
            "model": settings.gemini_model if gemini_healthy else None,
            "tools_registered": get_gemini_service().registered_tools if gemini_healthy else [],
        },
        "calendar": {
            "status": "per_agent_oauth",
            "note": "Calendar is configured per-agent via Google OAuth",
        },
    }

    # Determine overall status
    critical_services_healthy = redis_healthy and gemini_healthy
    overall_status = "healthy" if critical_services_healthy else "degraded"

    response_data = {
        "status": overall_status,
        "timestamp": datetime.utcnow().isoformat(),
        "uptime_seconds": uptime_seconds,
        "environment": settings.app_env,
        "version": "1.0.0",
        "services": services,
    }

    status_code = 200 if critical_services_healthy else 503

    return JSONResponse(
        content=response_data,
        status_code=status_code,
    )


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.is_development,
        workers=settings.workers if not settings.is_development else 1,
        log_level=settings.log_level.lower(),
    )
