# ==============================================================================
# ASAAS CUSTOMERS REPOSITORY
# Repositorio para tabela asaas_clientes
# ==============================================================================

from __future__ import annotations

import structlog
from datetime import datetime, timezone
from typing import Optional, Any

from supabase import Client

from ..client import get_supabase_admin
from .base import BaseRepository

logger = structlog.get_logger(__name__)

# Cache TTL em minutos
CUSTOMER_CACHE_TTL_MINUTES = 5


class AsaasCustomerRecord(dict):
    """TypedDict para registro de cliente Asaas."""
    pass


class AsaasCustomersRepository(BaseRepository[AsaasCustomerRecord]):
    """
    Repositorio para tabela asaas_clientes.

    Gerencia cache local de clientes do Asaas com TTL.
    """

    table_name = "asaas_clientes"

    # ==========================================================================
    # UPSERT
    # ==========================================================================

    async def upsert(
        self,
        customer_id: str,
        agent_id: str,
        data: dict[str, Any],
    ) -> AsaasCustomerRecord:
        """
        Insere ou atualiza cliente.

        Args:
            customer_id: ID do cliente no Asaas
            agent_id: ID do agente
            data: Dados do cliente

        Returns:
            Registro atualizado
        """
        try:
            now = datetime.utcnow().isoformat()

            record = {
                "id": customer_id,
                "agent_id": agent_id,
                "name": data.get("name"),
                "cpf_cnpj": data.get("cpfCnpj"),
                "email": data.get("email"),
                "phone": data.get("phone"),
                "mobile_phone": data.get("mobilePhone"),
                "address": data.get("address"),
                "address_number": data.get("addressNumber"),
                "complement": data.get("complement"),
                "province": data.get("province"),
                "city": data.get("city"),
                "state": data.get("state"),
                "postal_code": data.get("postalCode"),
                "date_created": data.get("dateCreated"),
                "external_reference": data.get("externalReference"),
                "observations": data.get("observations"),
                "updated_at": now,
                "deleted_at": None,
                "deleted_from_asaas": False,
            }

            response = self.table.upsert(
                record,
                on_conflict="id,agent_id"
            ).execute()

            if response.data and len(response.data) > 0:
                logger.info(
                    "asaas_customer_upserted",
                    customer_id=customer_id,
                    name=data.get("name"),
                )
                return response.data[0]

            raise ValueError("Upsert returned no data")

        except Exception as e:
            logger.error(
                "asaas_customer_upsert_error",
                customer_id=customer_id,
                error=str(e),
            )
            raise

    # ==========================================================================
    # FIND
    # ==========================================================================

    async def find_by_customer_id(
        self,
        customer_id: str,
        agent_id: Optional[str] = None,
    ) -> Optional[AsaasCustomerRecord]:
        """
        Busca cliente por ID.

        Args:
            customer_id: ID do cliente no Asaas
            agent_id: ID do agente (opcional)

        Returns:
            Cliente ou None
        """
        try:
            query = self.table.select("*").eq("id", customer_id)

            if agent_id:
                query = query.eq("agent_id", agent_id)

            response = query.maybe_single().execute()
            return response.data

        except Exception as e:
            if self._is_not_found(e):
                return None
            logger.error(
                "asaas_customer_find_error",
                customer_id=customer_id,
                error=str(e),
            )
            raise

    async def find_cached(
        self,
        customer_id: str,
        agent_id: str,
        ttl_minutes: int = CUSTOMER_CACHE_TTL_MINUTES,
    ) -> Optional[AsaasCustomerRecord]:
        """
        Busca cliente no cache se estiver fresco.

        Args:
            customer_id: ID do cliente
            agent_id: ID do agente
            ttl_minutes: TTL em minutos

        Returns:
            Cliente se cacheado e fresco, None caso contrario
        """
        if not customer_id:
            return None

        try:
            response = (
                self.table
                .select("*")
                .eq("id", customer_id)
                .eq("agent_id", agent_id)
                .maybe_single()
                .execute()
            )

            if not response.data:
                return None

            # Verificar TTL
            updated_at = response.data.get("updated_at")
            if updated_at:
                try:
                    if isinstance(updated_at, str):
                        last_update = datetime.fromisoformat(
                            updated_at.replace("Z", "+00:00")
                        )
                    else:
                        last_update = updated_at

                    now = datetime.now(timezone.utc)
                    if last_update.tzinfo is None:
                        last_update = last_update.replace(tzinfo=timezone.utc)

                    age_minutes = (now - last_update).total_seconds() / 60

                    if age_minutes <= ttl_minutes:
                        name = response.data.get("name")
                        if name and not self._is_invalid_name(name):
                            logger.debug(
                                "asaas_customer_cache_hit",
                                customer_id=customer_id,
                                age_minutes=round(age_minutes, 1),
                            )
                            return response.data
                    else:
                        logger.debug(
                            "asaas_customer_cache_stale",
                            customer_id=customer_id,
                            age_minutes=round(age_minutes, 1),
                            ttl_minutes=ttl_minutes,
                        )
                except Exception as e:
                    logger.debug(
                        "asaas_customer_cache_parse_error",
                        error=str(e),
                    )

            return None

        except Exception as e:
            logger.debug(
                "asaas_customer_cache_error",
                customer_id=customer_id,
                error=str(e),
            )
            return None

    async def find_name(
        self,
        customer_id: str,
        agent_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Busca apenas o nome do cliente.

        Args:
            customer_id: ID do cliente
            agent_id: ID do agente (opcional)

        Returns:
            Nome ou None
        """
        try:
            query = self.table.select("name").eq("id", customer_id)

            if agent_id:
                query = query.eq("agent_id", agent_id)

            response = query.maybe_single().execute()

            if response.data and response.data.get("name"):
                name = response.data["name"]
                if not self._is_invalid_name(name):
                    return name

            return None

        except Exception as e:
            if self._is_not_found(e):
                return None
            logger.error(
                "asaas_customer_find_name_error",
                customer_id=customer_id,
                error=str(e),
            )
            raise

    # ==========================================================================
    # SOFT DELETE
    # ==========================================================================

    async def soft_delete(
        self,
        customer_id: str,
        agent_id: Optional[str] = None,
    ) -> bool:
        """
        Marca cliente como deletado (soft delete).

        Args:
            customer_id: ID do cliente
            agent_id: ID do agente (opcional)

        Returns:
            True se deletado
        """
        try:
            now = datetime.utcnow().isoformat()

            query = self.table.update({
                "deleted_at": now,
                "deleted_from_asaas": True,
                "updated_at": now,
            }).eq("id", customer_id)

            if agent_id:
                query = query.eq("agent_id", agent_id)

            query.execute()

            logger.info(
                "asaas_customer_soft_deleted",
                customer_id=customer_id,
            )
            return True

        except Exception as e:
            logger.error(
                "asaas_customer_soft_delete_error",
                customer_id=customer_id,
                error=str(e),
            )
            raise

    # ==========================================================================
    # HELPERS
    # ==========================================================================

    def _is_invalid_name(self, name: Any) -> bool:
        """Verifica se o nome e invalido/fallback."""
        import re

        if not name or not str(name).strip():
            return True

        lower = str(name).lower().strip()

        if lower in ("desconhecido", "sem nome", "cliente", "?"):
            return True

        if lower.startswith("cliente #"):
            return True

        # Padrao "Cliente abc123" (6 caracteres hex)
        if re.match(r"^cliente [a-f0-9]{6}$", lower):
            return True

        return False


# ==============================================================================
# SINGLETON
# ==============================================================================

asaas_customers_repository = AsaasCustomersRepository()
