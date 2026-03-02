"""
Athena Business Intelligence Service.

Transforma a Athena em consultora de negocios para locacao de AR.
Fornece:
- Score de saude do negocio (0-100)
- Indicadores financeiros (ROI, payback, inadimplencia)
- Alertas e recomendacoes acionaveis
- Comparativos entre periodos

Componentes:
- metrics.py: Calculos de metricas de negocio
- tools.py: Function calling tools para Gemini
- prompts.py: System prompts enriquecidos com benchmarks
"""

from .metrics import (
    calculate_business_metrics,
    calculate_health_score,
    get_cached_metrics,
    BusinessMetrics,
)
from .tools import (
    get_business_health,
    ATHENA_BUSINESS_TOOLS,
)
from .prompts import (
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
