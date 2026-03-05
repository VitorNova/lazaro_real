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
        asaas_customers_repository,
        asaas_contracts_repository,
        asaas_payments_repository,
    )

    # Buscar agente
    agent = await agents_repository.find_by_id(agent_id)

    # Buscar lead em tabela dinamica
    lead = await dynamic_repository.find_lead_by_remotejid(
        table_name="LeadboxCRM_abc123",
        remotejid="5511999999999@s.whatsapp.net",
    )

    # Buscar cliente Asaas
    customer = await asaas_customers_repository.find_by_customer_id(customer_id)

    # Buscar contratos de um cliente
    contracts = await asaas_contracts_repository.find_by_customer_id(customer_id)

    # Buscar cobrancas vencidas
    overdue = await asaas_payments_repository.find_overdue_by_agent(agent_id)
"""

from .base import BaseRepository
from .agents import AgentsRepository, agents_repository
from .dynamic import DynamicRepository, dynamic_repository
from .asaas_customers import AsaasCustomersRepository, asaas_customers_repository
from .asaas_contracts import AsaasContractsRepository, asaas_contracts_repository
from .asaas_payments import AsaasPaymentsRepository, asaas_payments_repository

__all__ = [
    # Base
    "BaseRepository",
    # Agents
    "AgentsRepository",
    "agents_repository",
    # Dynamic (leads, messages, controle)
    "DynamicRepository",
    "dynamic_repository",
    # Asaas Customers
    "AsaasCustomersRepository",
    "asaas_customers_repository",
    # Asaas Contracts
    "AsaasContractsRepository",
    "asaas_contracts_repository",
    # Asaas Payments
    "AsaasPaymentsRepository",
    "asaas_payments_repository",
]
