"""
Core Security - Validação e proteção contra ataques.

Módulos:
- injection_guard: Proteção contra prompt injection
"""

from .injection_guard import validate_user_input

__all__ = ["validate_user_input"]
