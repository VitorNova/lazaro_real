"""
Main application entry point for Agente IA.

This module provides:
- FastAPI application with lifespan management
- Service initialization (Redis, Gemini)
- APScheduler with jobs for Ana
- Webhook routers registration
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Optional

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings

# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================

# Configure Python logging BEFORE structlog
logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    force=True,
)

# Configure structlog
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S %z"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)


# =============================================================================
# APPLICATION STATE
# =============================================================================

class AppState:
    """Global application state."""
    redis_connected: bool = False
    gemini_initialized: bool = False
    startup_time: Optional[datetime] = None
    scheduler: Optional[Any] = None


app_state = AppState()


# =============================================================================
# LIFESPAN
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown."""
    logger.info("Starting Agente IA", app_name=settings.app_name)
    app_state.startup_time = datetime.utcnow()

    # 1. Connect to Redis
    try:
        from app.services import get_redis_service, close_redis_service
        await get_redis_service(settings.redis_url)
        app_state.redis_connected = True
        logger.info("Redis connected")
    except Exception as e:
        logger.error("Redis connection failed", error=str(e))
        app_state.redis_connected = False

    # 2. Initialize Gemini
    try:
        from app.services import get_gemini_service
        from app.tools.cobranca import FUNCTION_DECLARATIONS
        gemini = get_gemini_service()
        gemini.initialize(function_declarations=FUNCTION_DECLARATIONS, system_instruction=None)
        app_state.gemini_initialized = True
        logger.info("Gemini initialized", model=gemini.model_name)
    except Exception as e:
        logger.error("Gemini initialization failed", error=str(e))
        app_state.gemini_initialized = False

    # 3. Start APScheduler
    try:
        from app.jobs.scheduler import create_scheduler, start_scheduler
        scheduler = create_scheduler()
        if scheduler and start_scheduler(scheduler):
            app_state.scheduler = scheduler
            logger.info("APScheduler started")
    except Exception as e:
        logger.error("APScheduler startup failed", error=str(e))

    logger.info("Agente IA startup complete")
    yield

    # Shutdown
    logger.info("Shutting down Agente IA")
    if app_state.scheduler:
        try:
            app_state.scheduler.shutdown(wait=False)
            logger.info("APScheduler stopped")
        except Exception as e:
            logger.error("APScheduler shutdown error", error=str(e))

    try:
        from app.services import close_redis_service
        await close_redis_service()
        logger.info("Redis disconnected")
    except Exception as e:
        logger.error("Redis disconnect error", error=str(e))

    logger.info("Agente IA shutdown complete")


# =============================================================================
# FASTAPI APP
# =============================================================================

app = FastAPI(
    title=settings.app_name,
    description="AI-powered WhatsApp agent for Ana (Alugar Ar)",
    version="2.0.0",
    docs_url="/docs" if settings.is_development else None,
    redoc_url="/redoc" if settings.is_development else None,
    lifespan=lifespan,
)

# CORS middleware - SECURITY: Restrito a domínios específicos
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://lazaro.fazinzz.com",
        "https://www.lazaro.fazinzz.com",
        "http://localhost:3001",  # Dev local
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Tenant-ID"],
)


# =============================================================================
# ROUTES
# =============================================================================

# Health check
@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "agente-ia",
        "version": "2.0.0",
        "redis": app_state.redis_connected,
        "gemini": app_state.gemini_initialized,
        "scheduler": app_state.scheduler is not None,
    }


# Register all routes
from app.api.routes import register_routes
register_routes(app)

# Alias para compatibilidade com UAZAPI (manda para /webhook/whatsapp)
# O router já tem prefix="/webhook" então não precisa de prefix adicional
from app.webhooks.mensagens import router as mensagens_router
app.include_router(mensagens_router, tags=["webhook-compat"])


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.is_development,
        workers=1,
        log_level=settings.log_level.lower(),
    )
