"""
DEPRECATED: Use app.domain.analytics instead.

Este modulo e uma ponte de compatibilidade.
Todos os imports sao redirecionados para domain/analytics/.
"""

from app.domain.analytics import (
    # Metrics
    calculate_business_metrics,
    calculate_health_score,
    get_cached_metrics,
    BusinessMetrics,
    # Tools
    get_business_health,
    ATHENA_BUSINESS_TOOLS,
    # Prompts
    build_business_system_prompt,
    BUSINESS_GLOSSARY,
    SECTOR_BENCHMARKS,
)

__all__ = [
    # Metrics
    "calculate_business_metrics",
    "calculate_health_score",
    "get_cached_metrics",
    "BusinessMetrics",
    # Tools
    "get_business_health",
    "ATHENA_BUSINESS_TOOLS",
    # Prompts
    "build_business_system_prompt",
    "BUSINESS_GLOSSARY",
    "SECTOR_BENCHMARKS",
]
