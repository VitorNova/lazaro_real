# ==============================================================================
# ASAAS CONTRACTS REPOSITORY
# Repositorio para tabela asaas_contratos
# ==============================================================================

from __future__ import annotations

import structlog
from datetime import datetime
from typing import Optional, Any, List

from supabase import Client

from ..client import get_supabase_admin
from .base import BaseRepository

logger = structlog.get_logger(__name__)


class AsaasContractRecord(dict):
    """TypedDict para registro de contrato Asaas."""
    pass


class AsaasContractsRepository(BaseRepository[AsaasContractRecord]):
    """
    Repositorio para tabela asaas_contratos.

    Gerencia contratos/assinaturas sincronizados do Asaas.
    """

    table_name = "asaas_contratos"

    # ==========================================================================
    # UPSERT
    # ==========================================================================

    async def upsert(
        self,
        subscription_id: str,
        agent_id: str,
        data: dict[str, Any],
        customer_name: str = "Desconhecido",
    ) -> AsaasContractRecord:
        """
        Insere ou atualiza contrato.

        Args:
            subscription_id: ID da assinatura no Asaas
            agent_id: ID do agente
            data: Dados da assinatura (formato API Asaas)
            customer_name: Nome do cliente

        Returns:
            Registro atualizado
        """
        try:
            now = datetime.utcnow().isoformat()

            record = {
                "id": subscription_id,
                "agent_id": agent_id,
                "customer_id": data.get("customer"),
                "customer_name": customer_name,
                "value": data.get("value"),
                "status": data.get("status"),
                "cycle": data.get("cycle"),
                "next_due_date": data.get("nextDueDate"),
                "description": data.get("description"),
                "billing_type": data.get("billingType"),
                "updated_at": now,
                "deleted_at": None,
                "deleted_from_asaas": False,
            }

            response = self.table.upsert(
                record,
                on_conflict="id"
            ).execute()

            if response.data and len(response.data) > 0:
                logger.info(
                    "asaas_contract_upserted",
                    subscription_id=subscription_id,
                    value=data.get("value"),
                    status=data.get("status"),
                )
                return response.data[0]

            raise ValueError("Upsert returned no data")

        except Exception as e:
            logger.error(
                "asaas_contract_upsert_error",
                subscription_id=subscription_id,
                error=str(e),
            )
            raise

    # ==========================================================================
    # FIND
    # ==========================================================================

    async def find_by_subscription_id(
        self,
        subscription_id: str,
    ) -> Optional[AsaasContractRecord]:
        """
        Busca contrato por ID.

        Args:
            subscription_id: ID da assinatura no Asaas

        Returns:
            Contrato ou None
        """
        try:
            response = (
                self.table
                .select("*")
                .eq("id", subscription_id)
                .maybe_single()
                .execute()
            )
            return response.data

        except Exception as e:
            if self._is_not_found(e):
                return None
            logger.error(
                "asaas_contract_find_error",
                subscription_id=subscription_id,
                error=str(e),
            )
            raise

    async def find_by_customer_id(
        self,
        customer_id: str,
        agent_id: Optional[str] = None,
        include_deleted: bool = False,
    ) -> List[AsaasContractRecord]:
        """
        Busca contratos por cliente.

        Args:
            customer_id: ID do cliente no Asaas
            agent_id: ID do agente (opcional)
            include_deleted: Incluir contratos deletados

        Returns:
            Lista de contratos
        """
        try:
            query = self.table.select("*").eq("customer_id", customer_id)

            if agent_id:
                query = query.eq("agent_id", agent_id)

            if not include_deleted:
                query = query.is_("deleted_at", "null")

            response = query.execute()
            return response.data or []

        except Exception as e:
            logger.error(
                "asaas_contract_find_by_customer_error",
                customer_id=customer_id,
                error=str(e),
            )
            raise

    async def find_name_by_customer_id(
        self,
        customer_id: str,
        agent_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Busca nome do cliente em contratos existentes.

        Util como fallback quando o nome nao esta em asaas_clientes.

        Args:
            customer_id: ID do cliente
            agent_id: ID do agente (opcional)

        Returns:
            Nome ou None
        """
        try:
            query = (
                self.table
                .select("customer_name")
                .eq("customer_id", customer_id)
                .neq("customer_name", "Desconhecido")
                .neq("customer_name", "Sem nome")
                .neq("customer_name", "")
                .limit(1)
            )

            if agent_id:
                query = query.eq("agent_id", agent_id)

            response = query.maybe_single().execute()

            if response.data and response.data.get("customer_name"):
                return response.data["customer_name"]

            return None

        except Exception as e:
            if self._is_not_found(e):
                return None
            logger.error(
                "asaas_contract_find_name_error",
                customer_id=customer_id,
                error=str(e),
            )
            raise

    async def find_active_by_agent(
        self,
        agent_id: str,
        status: Optional[str] = None,
    ) -> List[AsaasContractRecord]:
        """
        Busca contratos ativos de um agente.

        Args:
            agent_id: ID do agente
            status: Filtrar por status (ACTIVE, EXPIRED, etc)

        Returns:
            Lista de contratos
        """
        try:
            query = (
                self.table
                .select("*")
                .eq("agent_id", agent_id)
                .is_("deleted_at", "null")
            )

            if status:
                query = query.eq("status", status)
            else:
                query = query.neq("status", "INACTIVE")

            response = query.execute()
            return response.data or []

        except Exception as e:
            logger.error(
                "asaas_contract_find_active_error",
                agent_id=agent_id,
                error=str(e),
            )
            raise

    # ==========================================================================
    # SOFT DELETE
    # ==========================================================================

    async def soft_delete(
        self,
        subscription_id: str,
    ) -> bool:
        """
        Marca contrato como deletado (soft delete).

        Args:
            subscription_id: ID da assinatura

        Returns:
            True se deletado
        """
        try:
            now = datetime.utcnow().isoformat()

            self.table.update({
                "status": "INACTIVE",
                "deleted_at": now,
                "deleted_from_asaas": True,
                "updated_at": now,
            }).eq("id", subscription_id).execute()

            logger.info(
                "asaas_contract_soft_deleted",
                subscription_id=subscription_id,
            )
            return True

        except Exception as e:
            logger.error(
                "asaas_contract_soft_delete_error",
                subscription_id=subscription_id,
                error=str(e),
            )
            raise

    # ==========================================================================
    # UPDATE
    # ==========================================================================

    async def update_customer_name(
        self,
        customer_id: str,
        customer_name: str,
        agent_id: Optional[str] = None,
    ) -> int:
        """
        Atualiza nome do cliente em todos os contratos.

        Args:
            customer_id: ID do cliente
            customer_name: Novo nome
            agent_id: ID do agente (opcional)

        Returns:
            Numero de registros atualizados
        """
        try:
            now = datetime.utcnow().isoformat()

            query = self.table.update({
                "customer_name": customer_name,
                "updated_at": now,
            }).eq("customer_id", customer_id)

            if agent_id:
                query = query.eq("agent_id", agent_id)

            response = query.execute()

            count = len(response.data) if response.data else 0

            if count > 0:
                logger.info(
                    "asaas_contract_names_updated",
                    customer_id=customer_id,
                    customer_name=customer_name,
                    count=count,
                )

            return count

        except Exception as e:
            logger.error(
                "asaas_contract_update_names_error",
                customer_id=customer_id,
                error=str(e),
            )
            raise


# ==============================================================================
# SINGLETON
# ==============================================================================

asaas_contracts_repository = AsaasContractsRepository()
