"""
Domain Analytics Services - Business Intelligence.

Modulos:
- metrics: Calculos de metricas de negocio
- prompts: System prompts enriquecidos
- tools: Function calling tools para Gemini
"""

from .metrics import (
    calculate_business_metrics,
    calculate_health_score,
    get_cached_metrics,
    save_metrics_to_cache,
    generate_alerts,
    BusinessMetrics,
)
from .tools import (
    get_business_health,
    execute_athena_tool,
    ATHENA_BUSINESS_TOOLS,
)
from .prompts import (
    build_business_system_prompt,
    format_metrics_context,
    BUSINESS_GLOSSARY,
    SECTOR_BENCHMARKS,
    STANDARD_RECOMMENDATIONS,
)

__all__ = [
    # Metrics
    "calculate_business_metrics",
    "calculate_health_score",
    "get_cached_metrics",
    "save_metrics_to_cache",
    "generate_alerts",
    "BusinessMetrics",
    # Tools
    "get_business_health",
    "execute_athena_tool",
    "ATHENA_BUSINESS_TOOLS",
    # Prompts
    "build_business_system_prompt",
    "format_metrics_context",
    "BUSINESS_GLOSSARY",
    "SECTOR_BENCHMARKS",
    "STANDARD_RECOMMENDATIONS",
]
