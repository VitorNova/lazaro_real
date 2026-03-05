# ==============================================================================
# ASAAS PAYMENTS REPOSITORY
# Repositorio para tabela asaas_cobrancas
# ==============================================================================

from __future__ import annotations

import structlog
from datetime import datetime, date
from typing import Optional, Any, List

from supabase import Client

from ..client import get_supabase_admin
from .base import BaseRepository

logger = structlog.get_logger(__name__)


class AsaasPaymentRecord(dict):
    """TypedDict para registro de cobranca Asaas."""
    pass


class AsaasPaymentsRepository(BaseRepository[AsaasPaymentRecord]):
    """
    Repositorio para tabela asaas_cobrancas.

    Gerencia cobrancas/pagamentos sincronizados do Asaas.
    """

    table_name = "asaas_cobrancas"

    # ==========================================================================
    # UPSERT
    # ==========================================================================

    async def upsert(
        self,
        payment_id: str,
        agent_id: str,
        data: dict[str, Any],
        customer_name: str = "Desconhecido",
    ) -> AsaasPaymentRecord:
        """
        Insere ou atualiza cobranca.

        Args:
            payment_id: ID do pagamento no Asaas
            agent_id: ID do agente
            data: Dados do pagamento (formato API Asaas)
            customer_name: Nome do cliente

        Returns:
            Registro atualizado
        """
        try:
            # Calcular dias de atraso
            dias_atraso = 0
            status = data.get("status", "")
            due_date = data.get("dueDate")

            if status == "OVERDUE" and due_date:
                try:
                    hoje = date.today()
                    venc = datetime.strptime(due_date, "%Y-%m-%d").date()
                    diff = (hoje - venc).days
                    dias_atraso = diff if diff > 0 else 0
                except Exception:
                    pass

            now = datetime.utcnow().isoformat()

            record = {
                "id": payment_id,
                "agent_id": agent_id,
                "customer_id": data.get("customer"),
                "customer_name": customer_name,
                "subscription_id": data.get("subscription"),
                "value": data.get("value"),
                "net_value": data.get("netValue"),
                "status": status,
                "billing_type": data.get("billingType"),
                "due_date": due_date,
                "payment_date": data.get("paymentDate"),
                "date_created": data.get("dateCreated"),
                "description": data.get("description"),
                "invoice_url": data.get("invoiceUrl"),
                "bank_slip_url": data.get("bankSlipUrl"),
                "dias_atraso": dias_atraso,
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
                    "asaas_payment_upserted",
                    payment_id=payment_id,
                    value=data.get("value"),
                    status=status,
                    due_date=due_date,
                )
                return response.data[0]

            raise ValueError("Upsert returned no data")

        except Exception as e:
            logger.error(
                "asaas_payment_upsert_error",
                payment_id=payment_id,
                error=str(e),
            )
            raise

    # ==========================================================================
    # FIND
    # ==========================================================================

    async def find_by_payment_id(
        self,
        payment_id: str,
    ) -> Optional[AsaasPaymentRecord]:
        """
        Busca cobranca por ID.

        Args:
            payment_id: ID do pagamento no Asaas

        Returns:
            Cobranca ou None
        """
        try:
            response = (
                self.table
                .select("*")
                .eq("id", payment_id)
                .maybe_single()
                .execute()
            )
            return response.data

        except Exception as e:
            if self._is_not_found(e):
                return None
            logger.error(
                "asaas_payment_find_error",
                payment_id=payment_id,
                error=str(e),
            )
            raise

    async def find_by_customer_id(
        self,
        customer_id: str,
        agent_id: Optional[str] = None,
        status: Optional[str] = None,
        include_deleted: bool = False,
    ) -> List[AsaasPaymentRecord]:
        """
        Busca cobrancas por cliente.

        Args:
            customer_id: ID do cliente no Asaas
            agent_id: ID do agente (opcional)
            status: Filtrar por status
            include_deleted: Incluir cobrancas deletadas

        Returns:
            Lista de cobrancas
        """
        try:
            query = self.table.select("*").eq("customer_id", customer_id)

            if agent_id:
                query = query.eq("agent_id", agent_id)

            if status:
                query = query.eq("status", status)

            if not include_deleted:
                query = query.is_("deleted_at", "null")

            response = query.order("due_date", desc=True).execute()
            return response.data or []

        except Exception as e:
            logger.error(
                "asaas_payment_find_by_customer_error",
                customer_id=customer_id,
                error=str(e),
            )
            raise

    async def find_by_subscription_id(
        self,
        subscription_id: str,
        agent_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[AsaasPaymentRecord]:
        """
        Busca cobrancas por assinatura.

        Args:
            subscription_id: ID da assinatura
            agent_id: ID do agente (opcional)
            status: Filtrar por status

        Returns:
            Lista de cobrancas
        """
        try:
            query = (
                self.table
                .select("*")
                .eq("subscription_id", subscription_id)
                .is_("deleted_at", "null")
            )

            if agent_id:
                query = query.eq("agent_id", agent_id)

            if status:
                query = query.eq("status", status)

            response = query.order("due_date", desc=True).execute()
            return response.data or []

        except Exception as e:
            logger.error(
                "asaas_payment_find_by_subscription_error",
                subscription_id=subscription_id,
                error=str(e),
            )
            raise

    async def find_name_by_customer_id(
        self,
        customer_id: str,
        agent_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Busca nome do cliente em cobrancas existentes.

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
                "asaas_payment_find_name_error",
                customer_id=customer_id,
                error=str(e),
            )
            raise

    async def find_overdue_by_agent(
        self,
        agent_id: str,
        min_days_overdue: int = 1,
    ) -> List[AsaasPaymentRecord]:
        """
        Busca cobrancas vencidas de um agente.

        Args:
            agent_id: ID do agente
            min_days_overdue: Dias minimos de atraso

        Returns:
            Lista de cobrancas vencidas
        """
        try:
            response = (
                self.table
                .select("*")
                .eq("agent_id", agent_id)
                .eq("status", "OVERDUE")
                .gte("dias_atraso", min_days_overdue)
                .is_("deleted_at", "null")
                .order("dias_atraso", desc=True)
                .execute()
            )
            return response.data or []

        except Exception as e:
            logger.error(
                "asaas_payment_find_overdue_error",
                agent_id=agent_id,
                error=str(e),
            )
            raise

    async def find_pending_by_agent(
        self,
        agent_id: str,
    ) -> List[AsaasPaymentRecord]:
        """
        Busca cobrancas pendentes de um agente.

        Args:
            agent_id: ID do agente

        Returns:
            Lista de cobrancas pendentes
        """
        try:
            response = (
                self.table
                .select("*")
                .eq("agent_id", agent_id)
                .eq("status", "PENDING")
                .is_("deleted_at", "null")
                .order("due_date", desc=False)
                .execute()
            )
            return response.data or []

        except Exception as e:
            logger.error(
                "asaas_payment_find_pending_error",
                agent_id=agent_id,
                error=str(e),
            )
            raise

    # ==========================================================================
    # SOFT DELETE
    # ==========================================================================

    async def soft_delete(
        self,
        payment_id: str,
    ) -> bool:
        """
        Marca cobranca como deletada (soft delete).

        Args:
            payment_id: ID do pagamento

        Returns:
            True se deletado
        """
        try:
            now = datetime.utcnow().isoformat()

            self.table.update({
                "deleted_at": now,
                "deleted_from_asaas": True,
                "updated_at": now,
            }).eq("id", payment_id).execute()

            logger.info(
                "asaas_payment_soft_deleted",
                payment_id=payment_id,
            )
            return True

        except Exception as e:
            logger.error(
                "asaas_payment_soft_delete_error",
                payment_id=payment_id,
                error=str(e),
            )
            raise

    # ==========================================================================
    # UPDATE
    # ==========================================================================

    async def update_status(
        self,
        payment_id: str,
        status: str,
        payment_date: Optional[str] = None,
    ) -> Optional[AsaasPaymentRecord]:
        """
        Atualiza status de uma cobranca.

        Args:
            payment_id: ID do pagamento
            status: Novo status
            payment_date: Data de pagamento (se aplicavel)

        Returns:
            Registro atualizado ou None
        """
        try:
            now = datetime.utcnow().isoformat()

            data: dict[str, Any] = {
                "status": status,
                "updated_at": now,
            }

            if payment_date:
                data["payment_date"] = payment_date

            # Zerar dias_atraso se pago
            if status in ("CONFIRMED", "RECEIVED"):
                data["dias_atraso"] = 0

            response = (
                self.table
                .update(data)
                .eq("id", payment_id)
                .execute()
            )

            if response.data and len(response.data) > 0:
                logger.info(
                    "asaas_payment_status_updated",
                    payment_id=payment_id,
                    status=status,
                )
                return response.data[0]

            return None

        except Exception as e:
            logger.error(
                "asaas_payment_update_status_error",
                payment_id=payment_id,
                status=status,
                error=str(e),
            )
            raise

    async def update_customer_name(
        self,
        customer_id: str,
        customer_name: str,
        agent_id: Optional[str] = None,
    ) -> int:
        """
        Atualiza nome do cliente em todas as cobrancas.

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
                    "asaas_payment_names_updated",
                    customer_id=customer_id,
                    customer_name=customer_name,
                    count=count,
                )

            return count

        except Exception as e:
            logger.error(
                "asaas_payment_update_names_error",
                customer_id=customer_id,
                error=str(e),
            )
            raise

    async def recalculate_days_overdue(
        self,
        agent_id: str,
    ) -> int:
        """
        Recalcula dias de atraso para cobrancas vencidas.

        Args:
            agent_id: ID do agente

        Returns:
            Numero de cobrancas atualizadas
        """
        try:
            hoje = date.today()
            updated_count = 0

            # Buscar cobrancas vencidas
            response = (
                self.table
                .select("id, due_date")
                .eq("agent_id", agent_id)
                .eq("status", "OVERDUE")
                .is_("deleted_at", "null")
                .execute()
            )

            if not response.data:
                return 0

            now = datetime.utcnow().isoformat()

            for payment in response.data:
                due_date = payment.get("due_date")
                if not due_date:
                    continue

                try:
                    venc = datetime.strptime(due_date, "%Y-%m-%d").date()
                    dias_atraso = (hoje - venc).days
                    if dias_atraso < 0:
                        dias_atraso = 0

                    self.table.update({
                        "dias_atraso": dias_atraso,
                        "updated_at": now,
                    }).eq("id", payment["id"]).execute()

                    updated_count += 1

                except Exception:
                    continue

            if updated_count > 0:
                logger.info(
                    "asaas_payment_days_recalculated",
                    agent_id=agent_id,
                    count=updated_count,
                )

            return updated_count

        except Exception as e:
            logger.error(
                "asaas_payment_recalculate_error",
                agent_id=agent_id,
                error=str(e),
            )
            raise


# ==============================================================================
# SINGLETON
# ==============================================================================

asaas_payments_repository = AsaasPaymentsRepository()
