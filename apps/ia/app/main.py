"""
Main application entry point for Agente IA.

This module provides the FastAPI application instance.
All configuration, lifespan, and routes are handled by dedicated modules.
"""

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.core.logging import configure_logging
from app.core.lifespan import lifespan
from app.api.routes import register_routes

# Configure logging
configure_logging()

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

# Register all routes
register_routes(app)


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.is_development,
        workers=settings.workers if not settings.is_development else 1,
        log_level=settings.log_level.lower(),
    )
