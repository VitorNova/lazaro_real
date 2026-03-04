# ==============================================================================
# BASE REPOSITORY
# Classe base com padroes comuns para repositorios
# ==============================================================================

from __future__ import annotations

import structlog
from typing import Optional, Any, TypeVar, Generic
from abc import ABC

from supabase import Client

from ..client import get_supabase_admin

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=dict)


class BaseRepository(ABC, Generic[T]):
    """
    Classe base para repositorios.

    Fornece metodos comuns de CRUD e tratamento de erros.
    """

    # Nome da tabela (deve ser definido nas subclasses)
    table_name: str = ""

    def __init__(self, client: Optional[Client] = None):
        """
        Inicializa o repositorio.

        Args:
            client: Cliente Supabase opcional (default: admin client)
        """
        self._client = client or get_supabase_admin()

    @property
    def client(self) -> Client:
        """Retorna o cliente Supabase."""
        return self._client

    @property
    def table(self):
        """Retorna a tabela do repositorio."""
        if not self.table_name:
            raise ValueError("table_name must be defined in subclass")
        return self._client.table(self.table_name)

    # ==========================================================================
    # CRUD OPERATIONS
    # ==========================================================================

    async def find_by_id(self, id: str) -> Optional[T]:
        """
        Busca registro por ID.

        Args:
            id: ID do registro

        Returns:
            Registro ou None se nao encontrado
        """
        try:
            response = self.table.select("*").eq("id", id).single().execute()
            return response.data
        except Exception as e:
            if self._is_not_found(e):
                return None
            logger.error(
                "repository_find_by_id_error",
                table=self.table_name,
                id=id,
                error=str(e),
            )
            raise

    async def find_all(
        self,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "created_at",
        ascending: bool = False,
    ) -> list[T]:
        """
        Lista todos os registros com paginacao.

        Args:
            limit: Limite de registros
            offset: Offset para paginacao
            order_by: Campo para ordenacao
            ascending: Ordem ascendente ou descendente

        Returns:
            Lista de registros
        """
        try:
            query = self.table.select("*")
            query = query.order(order_by, desc=not ascending)
            query = query.range(offset, offset + limit - 1)
            response = query.execute()
            return response.data or []
        except Exception as e:
            logger.error(
                "repository_find_all_error",
                table=self.table_name,
                error=str(e),
            )
            raise

    async def create(self, data: dict[str, Any]) -> T:
        """
        Cria novo registro.

        Args:
            data: Dados do registro

        Returns:
            Registro criado
        """
        try:
            response = self.table.insert(data).execute()
            if response.data and len(response.data) > 0:
                return response.data[0]
            raise ValueError("Insert returned no data")
        except Exception as e:
            logger.error(
                "repository_create_error",
                table=self.table_name,
                error=str(e),
            )
            raise

    async def update(self, id: str, data: dict[str, Any]) -> Optional[T]:
        """
        Atualiza registro existente.

        Args:
            id: ID do registro
            data: Dados para atualizar

        Returns:
            Registro atualizado ou None
        """
        try:
            response = self.table.update(data).eq("id", id).execute()
            if response.data and len(response.data) > 0:
                return response.data[0]
            return None
        except Exception as e:
            logger.error(
                "repository_update_error",
                table=self.table_name,
                id=id,
                error=str(e),
            )
            raise

    async def delete(self, id: str) -> bool:
        """
        Deleta registro.

        Args:
            id: ID do registro

        Returns:
            True se deletado, False caso contrario
        """
        try:
            response = self.table.delete().eq("id", id).execute()
            return True
        except Exception as e:
            if self._is_not_found(e):
                return False
            logger.error(
                "repository_delete_error",
                table=self.table_name,
                id=id,
                error=str(e),
            )
            raise

    async def count(self, filters: Optional[dict[str, Any]] = None) -> int:
        """
        Conta registros.

        Args:
            filters: Filtros opcionais

        Returns:
            Quantidade de registros
        """
        try:
            query = self.table.select("*", count="exact", head=True)
            if filters:
                for key, value in filters.items():
                    query = query.eq(key, value)
            response = query.execute()
            return response.count or 0
        except Exception as e:
            logger.error(
                "repository_count_error",
                table=self.table_name,
                error=str(e),
            )
            raise

    async def exists(self, id: str) -> bool:
        """
        Verifica se registro existe.

        Args:
            id: ID do registro

        Returns:
            True se existe, False caso contrario
        """
        try:
            response = self.table.select("id").eq("id", id).single().execute()
            return response.data is not None
        except Exception as e:
            if self._is_not_found(e):
                return False
            raise

    # ==========================================================================
    # HELPERS
    # ==========================================================================

    def _is_not_found(self, error: Any) -> bool:
        """Verifica se o erro e de registro nao encontrado."""
        if hasattr(error, "code"):
            return error.code == "PGRST116"
        error_str = str(error)
        return "PGRST116" in error_str or "no rows" in error_str.lower()

    def _is_unique_violation(self, error: Any) -> bool:
        """Verifica se o erro e de violacao de unique constraint."""
        if hasattr(error, "code"):
            return error.code == "23505"
        return "23505" in str(error) or "unique" in str(error).lower()
