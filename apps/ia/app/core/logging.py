"""
Logging configuration for the application.

This module configures both standard Python logging and structlog
for consistent, structured logging throughout the application.
"""

import logging

import structlog

from app.config import settings


def configure_logging() -> None:
    """
    Configure logging for the application.

    Sets up:
    - Standard Python logging with configurable level
    - structlog with JSON or console output based on settings
    """
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
