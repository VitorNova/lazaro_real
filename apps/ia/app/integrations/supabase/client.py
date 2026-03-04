# ==============================================================================
# SUPABASE CLIENT
# Cliente singleton para Supabase
# Baseado na implementacao TypeScript (apps/api/src/services/supabase/client.ts)
# ==============================================================================

from __future__ import annotations

import structlog
from typing import Optional, Any
from functools import lru_cache

from supabase import create_client, Client

from app.config import settings

logger = structlog.get_logger(__name__)


# ==============================================================================
# CLIENT SINGLETON
# ==============================================================================

class SupabaseClient:
    """
    Cliente Supabase com acesso administrativo (service key).

    Este cliente bypassa RLS e tem acesso completo ao banco.
    Use para operacoes de backend/webhooks/jobs.
    """

    _instance: Optional[SupabaseClient] = None
    _client: Optional[Client] = None

    def __new__(cls) -> SupabaseClient:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._client is None:
            self._initialize()

    def _initialize(self) -> None:
        """Inicializa o cliente Supabase."""
        url = settings.supabase_url
        key = settings.supabase_service_key

        if not url or not key:
            logger.error(
                "supabase_client_missing_config",
                has_url=bool(url),
                has_key=bool(key),
            )
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY are required")

        self._client = create_client(url, key)
        logger.info("supabase_client_initialized", url=url[:30] + "...")

    @property
    def client(self) -> Client:
        """Retorna o cliente Supabase."""
        if self._client is None:
            self._initialize()
        return self._client

    def table(self, name: str):
        """Atalho para acessar uma tabela."""
        return self.client.table(name)

    def rpc(self, fn: str, params: Optional[dict] = None):
        """Atalho para chamar uma funcao RPC."""
        return self.client.rpc(fn, params or {})

    def storage(self):
        """Atalho para acessar storage."""
        return self.client.storage

    async def health_check(self) -> bool:
        """
        Verifica se a conexao com Supabase esta funcionando.

        Returns:
            True se conexao OK, False caso contrario
        """
        try:
            response = self.client.table("agents").select("id").limit(1).execute()
            return True
        except Exception as e:
            logger.error("supabase_health_check_failed", error=str(e))
            return False


# ==============================================================================
# FACTORY FUNCTIONS
# ==============================================================================

@lru_cache(maxsize=1)
def get_supabase_client() -> SupabaseClient:
    """
    Retorna o cliente Supabase singleton.

    Returns:
        SupabaseClient configurado
    """
    return SupabaseClient()


def get_supabase_admin() -> Client:
    """
    Retorna o cliente Supabase raw (para operacoes diretas).

    Returns:
        Cliente supabase-py
    """
    return get_supabase_client().client


# ==============================================================================
# DIRECT ACCESS HELPERS
# ==============================================================================

def table(name: str):
    """
    Atalho para acessar uma tabela diretamente.

    Exemplo:
        from app.integrations.supabase import table
        result = table("agents").select("*").eq("id", agent_id).single().execute()
    """
    return get_supabase_client().table(name)


def rpc(fn: str, params: Optional[dict] = None):
    """
    Atalho para chamar uma funcao RPC diretamente.

    Exemplo:
        from app.integrations.supabase import rpc
        result = rpc("my_function", {"param1": "value"}).execute()
    """
    return get_supabase_client().rpc(fn, params)


# ==============================================================================
# QUERY HELPERS
# ==============================================================================

def handle_query_result(response: Any, operation: str = "query") -> Optional[dict]:
    """
    Processa resultado de query e retorna o primeiro registro.

    Args:
        response: Resposta do Supabase
        operation: Nome da operacao para logging

    Returns:
        Primeiro registro ou None
    """
    if response.data and len(response.data) > 0:
        return response.data[0]

    logger.debug(f"supabase_{operation}_no_results")
    return None


def handle_query_list(response: Any, operation: str = "query") -> list[dict]:
    """
    Processa resultado de query e retorna lista de registros.

    Args:
        response: Resposta do Supabase
        operation: Nome da operacao para logging

    Returns:
        Lista de registros (pode ser vazia)
    """
    return response.data or []


def is_not_found_error(error: Any) -> bool:
    """
    Verifica se o erro e de registro nao encontrado (PGRST116).

    Args:
        error: Erro do Supabase

    Returns:
        True se for erro de nao encontrado
    """
    if hasattr(error, "code"):
        return error.code == "PGRST116"
    if isinstance(error, dict):
        return error.get("code") == "PGRST116"
    return False


def is_unique_violation(error: Any) -> bool:
    """
    Verifica se o erro e de violacao de unique constraint.

    Args:
        error: Erro do Supabase

    Returns:
        True se for violacao de unique
    """
    if hasattr(error, "code"):
        return error.code == "23505"
    if isinstance(error, dict):
        return error.get("code") == "23505"
    return False
