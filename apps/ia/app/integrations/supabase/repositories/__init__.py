# ==============================================================================
# SUPABASE REPOSITORIES
# Repositorios para acesso ao banco de dados
# ==============================================================================

"""
Repositorios Supabase para Lazaro-v2.

Uso:
    from app.integrations.supabase.repositories import (
        agents_repository,
        dynamic_repository,
    )

    # Buscar agente
    agent = await agents_repository.find_by_id(agent_id)

    # Buscar lead em tabela dinamica
    lead = await dynamic_repository.find_lead_by_remotejid(
        table_name="LeadboxCRM_abc123",
        remotejid="5511999999999@s.whatsapp.net",
    )
"""

from .base import BaseRepository
from .agents import AgentsRepository, agents_repository
from .dynamic import DynamicRepository, dynamic_repository

__all__ = [
    # Base
    "BaseRepository",
    # Agents
    "AgentsRepository",
    "agents_repository",
    # Dynamic
    "DynamicRepository",
    "dynamic_repository",
]
