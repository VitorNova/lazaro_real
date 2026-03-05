"""
Function declarations and handlers - PONTE para ai/tools/cobranca.py

Este arquivo é uma ponte para manter compatibilidade com imports legados.
A implementação real está em: app/ai/tools/cobranca.py

Migrado na Fase 9.6 da refatoração.
"""

# Re-exportar tudo de ai/tools/cobranca para compatibilidade
from app.ai.tools.cobranca import (
    CALENDAR_TOOL_NAMES,
    DISABLED_TOOLS,
    FUNCTION_DECLARATIONS,
    FunctionHandlers,
    SALVAR_DADOS_LEAD_DECLARATION,
    TRANSFERIR_DEPARTAMENTO_DECLARATION,
    get_function_declarations,
)

__all__ = [
    "DISABLED_TOOLS",
    "CALENDAR_TOOL_NAMES",
    "SALVAR_DADOS_LEAD_DECLARATION",
    "TRANSFERIR_DEPARTAMENTO_DECLARATION",
    "FUNCTION_DECLARATIONS",
    "get_function_declarations",
    "FunctionHandlers",
]
