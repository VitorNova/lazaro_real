"""
Application lifespan management.

This module handles startup and shutdown logic for the FastAPI application.
"""

from contextlib import asynccontextmanager
from datetime import datetime

import structlog
from fastapi import FastAPI

from app.config import settings
from app.core.config import app_state
from app.services import get_redis_service, close_redis_service, get_gemini_service
from app.tools.cobranca import FUNCTION_DECLARATIONS
from app.domain.messaging import recover_orphan_buffers, recover_failed_sends
from app.jobs.scheduler import create_scheduler, start_scheduler, stop_scheduler

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Handles:
    - Redis connection and recovery
    - Gemini service initialization
    - Scheduler startup
    - Graceful shutdown
    """
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
