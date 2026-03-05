"""
AI Tools Package

Este pacote contém as ferramentas (function declarations e handlers)
para integração com Gemini AI.

Módulos:
- cliente: consultar_cliente (dados unificados do cliente)
- cobranca: declarations e handlers de cobrança
- maintenance_tools: ferramentas de manutenção
- billing_tools: ferramentas de billing
- customer_tools: ferramentas de cliente/lead
- transfer_tools: ferramentas de transferência
- scheduling_tools: ferramentas de agendamento
- tool_registry: registro central de tools
"""

from .cliente import CONSULTAR_CLIENTE_DECLARATION, consultar_cliente
from .cobranca import (
    FUNCTION_DECLARATIONS,
    FunctionHandlers,
    get_function_declarations,
)

__all__ = [
    "CONSULTAR_CLIENTE_DECLARATION",
    "consultar_cliente",
    "FUNCTION_DECLARATIONS",
    "FunctionHandlers",
    "get_function_declarations",
]
