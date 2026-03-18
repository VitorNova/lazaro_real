"""
Health check endpoints for application monitoring.

This module provides:
- GET /: Root endpoint with application info
- GET /health: Basic health check
- GET /health/detailed: Detailed health check with service status
"""

from datetime import datetime
from typing import Any, Dict

import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import settings
from app.core.config import app_state

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["health"])


@router.get("/", tags=["root"])
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


@router.get("/health")
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


@router.get("/health/detailed")
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
    from app.services import get_redis_service, get_gemini_service

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
    # SECURITY: Removed sensitive internal info (model name, tools list)
    services = {
        "redis": {
            "status": "healthy" if redis_healthy else "unhealthy",
            "connected": app_state.redis_connected,
        },
        "gemini": {
            "status": "healthy" if gemini_healthy else "unhealthy",
            "initialized": app_state.gemini_initialized,
            # SECURITY: model and tools_registered removed (internal info)
        },
        "calendar": {
            "status": "configured",
        },
    }

    # Determine overall status
    critical_services_healthy = redis_healthy and gemini_healthy
    overall_status = "healthy" if critical_services_healthy else "degraded"

    # SECURITY: Removed environment from response (internal info)
    response_data = {
        "status": overall_status,
        "timestamp": datetime.utcnow().isoformat(),
        "uptime_seconds": uptime_seconds,
        "version": "1.0.0",
        "services": services,
    }

    status_code = 200 if critical_services_healthy else 503

    return JSONResponse(
        content=response_data,
        status_code=status_code,
    )
