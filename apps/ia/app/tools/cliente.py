"""
Tool consultar_cliente - PONTE para ai/tools/cliente.py

Este arquivo é uma ponte para manter compatibilidade com imports legados.
A implementação real está em: app/ai/tools/cliente.py

Migrado na Fase 9.6 da refatoração.
"""

# Re-exportar tudo de ai/tools/cliente para compatibilidade
from app.ai.tools.cliente import (
    CONSULTAR_CLIENTE_DECLARATION,
    consultar_cliente,
)

__all__ = [
    "CONSULTAR_CLIENTE_DECLARATION",
    "consultar_cliente",
]
