"""
Global application state for tracking service status.

This module provides centralized state management for:
- Service connection status (Redis, Gemini)
- Scheduler instance
- Startup time tracking
"""

from datetime import datetime
from typing import Any, Optional


class AppState:
    """Global application state for tracking service status."""

    redis_connected: bool = False
    gemini_initialized: bool = False
    startup_time: Optional[datetime] = None
    scheduler: Optional[Any] = None


# Singleton instance
app_state = AppState()
