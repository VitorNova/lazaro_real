"""
Main application entry point for Agente IA.

This module provides:
- FastAPI application with lifespan management
- Service initialization on startup
- Graceful shutdown handling
- Route registration
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.core.config import app_state
from app.services import get_redis_service, close_redis_service, get_gemini_service
from app.tools.cobranca import FUNCTION_DECLARATIONS
from app.domain.messaging import recover_orphan_buffers, recover_failed_sends
from app.jobs.scheduler import create_scheduler, start_scheduler, stop_scheduler

# Configure standard Python logging
logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    force=True
)

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger.info("Starting Agente IA", app_name=settings.app_name, environment=settings.app_env)
    app_state.startup_time = datetime.utcnow()

    # 1. Connect to Redis
    try:
        await get_redis_service(settings.redis_url)
        app_state.redis_connected = True
        logger.info("Redis connected successfully")
        await recover_orphan_buffers()
        await recover_failed_sends()
    except Exception as e:
        logger.error("Failed to connect to Redis", error=str(e))
        app_state.redis_connected = False

    # 2. Initialize Gemini service
    try:
        gemini_service = get_gemini_service()
        gemini_service.initialize(function_declarations=FUNCTION_DECLARATIONS, system_instruction=None)
        app_state.gemini_initialized = True
        logger.info("Gemini service initialized", model=gemini_service.model_name)
    except Exception as e:
        logger.error("Failed to initialize Gemini service", error=str(e))
        app_state.gemini_initialized = False

    # 3. Start scheduler
    scheduler = create_scheduler()
    if scheduler and start_scheduler(scheduler):
        app_state.scheduler = scheduler

    logger.info("Agente IA startup complete")
    yield

    # Shutdown
    logger.info("Shutting down Agente IA")
    stop_scheduler(app_state.scheduler)
    try:
        await close_redis_service()
        app_state.redis_connected = False
        logger.info("Redis disconnected")
    except Exception as e:
        logger.error("Error disconnecting from Redis", error=str(e))
    logger.info("Agente IA shutdown complete")


# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    description="AI-powered WhatsApp agent orchestrator",
    version="1.0.0",
    docs_url="/docs" if settings.is_development else None,
    redoc_url="/redoc" if settings.is_development else None,
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# ROUTES
# =============================================================================

# Legacy WhatsApp webhook
from app.webhooks.mensagens import router as whatsapp_router
app.include_router(whatsapp_router, prefix="/api", tags=["webhooks"])

# Dashboard API
from app.api.dashboard import router as dashboard_router
app.include_router(dashboard_router, tags=["dashboard"])

# Google OAuth
from app.api.google_oauth import router as google_oauth_router
app.include_router(google_oauth_router, prefix="/api/google/oauth", tags=["google-oauth"])

# Auth
from app.api.auth import router as auth_router
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])

# Agents CRUD
from app.api.agentes import agents_router
app.include_router(agents_router, prefix="/api", tags=["agents"])

# Dynamic webhook (new)
from app.api.routes import webhooks_router
app.include_router(webhooks_router)

# Asaas payment webhook
from app.webhooks.pagamentos import router as asaas_webhook_router
app.include_router(asaas_webhook_router, prefix="/webhooks", tags=["webhooks"])

# Leadbox webhook (extracted)
from app.api.routes import leadbox_router
app.include_router(leadbox_router)

# Diana v2 - Prospecao ativa
from app.api.diana import router as diana_router
app.include_router(diana_router, prefix="/api/diana", tags=["diana"])

# Athena Oraculo - Analytics
from app.api.athena import router as athena_router
app.include_router(athena_router, prefix="/api/athena", tags=["athena"])

# Extracted routes
from app.api.routes import (
    uploads_router,
    jobs_control_router,
    maintenance_slots_router,
    leads_analysis_router,
    health_router,
)
app.include_router(uploads_router)
app.include_router(jobs_control_router)
app.include_router(maintenance_slots_router)
app.include_router(leads_analysis_router)
app.include_router(health_router)


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
