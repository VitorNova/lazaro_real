# apps/ia/app/domain/erp/repository.py
"""
Repository para queries Supabase das tabelas ERP.

Todas as queries filtram por tenant_id (multi-tenant).
"""

from typing import Optional, List, Dict, Any


class CustomerRepository:
    """Repository para erp_customers."""

    def __init__(self, supabase_client):
        self.db = supabase_client
        self.table_name = "erp_customers"

    async def list_customers(
        self,
        tenant_id: str,
        tipo: Optional[str] = None,
        ativo: bool = True,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Lista clientes do tenant."""
        query = self.db.table(self.table_name).select("*").eq("tenant_id", tenant_id)

        if tipo:
            query = query.eq("tipo", tipo)

        query = query.eq("ativo", ativo).limit(limit)
        result = query.execute()
        return result.data

    async def get_customer(
        self, tenant_id: str, customer_id: int
    ) -> Optional[Dict[str, Any]]:
        """Busca cliente por ID."""
        result = (
            self.db.table(self.table_name)
            .select("*")
            .eq("tenant_id", tenant_id)
            .eq("id", customer_id)
            .execute()
        )
        return result.data[0] if result.data else None

    async def get_customer_by_phone(
        self, tenant_id: str, phone: str
    ) -> Optional[Dict[str, Any]]:
        """Busca cliente por telefone/celular."""
        result = (
            self.db.table(self.table_name)
            .select("*")
            .eq("tenant_id", tenant_id)
            .eq("celular", phone)
            .execute()
        )
        return result.data[0] if result.data else None

    async def create_customer(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Cria novo cliente."""
        result = self.db.table(self.table_name).insert(data).execute()
        return result.data[0]

    async def update_customer(
        self, tenant_id: str, customer_id: int, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Atualiza cliente existente."""
        result = (
            self.db.table(self.table_name)
            .update(data)
            .eq("id", customer_id)
            .execute()
        )
        return result.data[0]

    async def delete_customer(self, tenant_id: str, customer_id: int) -> bool:
        """Remove cliente (soft delete via ativo=False ou hard delete)."""
        self.db.table(self.table_name).delete().eq("id", customer_id).execute()
        return True


class ProductRepository:
    """Repository para erp_products."""

    def __init__(self, supabase_client):
        self.db = supabase_client
        self.table_name = "erp_products"

    async def list_products(
        self,
        tenant_id: str,
        tipo: Optional[str] = None,
        categoria: Optional[str] = None,
        ativo: bool = True,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Lista produtos do tenant."""
        query = self.db.table(self.table_name).select("*").eq("tenant_id", tenant_id)

        if tipo:
            query = query.eq("tipo", tipo)
        if categoria:
            query = query.eq("categoria", categoria)

        query = query.eq("ativo", ativo).limit(limit)
        result = query.execute()
        return result.data

    async def get_product(
        self, tenant_id: str, product_id: int
    ) -> Optional[Dict[str, Any]]:
        """Busca produto por ID."""
        result = (
            self.db.table(self.table_name)
            .select("*")
            .eq("tenant_id", tenant_id)
            .eq("id", product_id)
            .execute()
        )
        return result.data[0] if result.data else None

    async def get_product_by_sku(
        self, tenant_id: str, sku: str
    ) -> Optional[Dict[str, Any]]:
        """Busca produto por SKU."""
        result = (
            self.db.table(self.table_name)
            .select("*")
            .eq("tenant_id", tenant_id)
            .eq("sku", sku)
            .execute()
        )
        return result.data[0] if result.data else None

    async def create_product(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Cria novo produto."""
        result = self.db.table(self.table_name).insert(data).execute()
        return result.data[0]

    async def update_product(
        self, tenant_id: str, product_id: int, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Atualiza produto existente."""
        result = (
            self.db.table(self.table_name)
            .update(data)
            .eq("id", product_id)
            .execute()
        )
        return result.data[0]

    async def delete_product(self, tenant_id: str, product_id: int) -> bool:
        """Remove produto."""
        self.db.table(self.table_name).delete().eq("id", product_id).execute()
        return True


class OrderRepository:
    """Repository para erp_orders."""

    def __init__(self, supabase_client):
        self.db = supabase_client
        self.table_name = "erp_orders"

    async def list_orders(
        self,
        tenant_id: str,
        status: Optional[str] = None,
        tipo: Optional[str] = None,
        customer_id: Optional[int] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Lista pedidos do tenant."""
        query = self.db.table(self.table_name).select("*").eq("tenant_id", tenant_id)

        if status:
            query = query.eq("status", status)
        if tipo:
            query = query.eq("tipo", tipo)
        if customer_id:
            query = query.eq("customer_id", customer_id)

        query = query.limit(limit)
        result = query.execute()
        return result.data

    async def get_order(
        self, tenant_id: str, order_id: int
    ) -> Optional[Dict[str, Any]]:
        """Busca pedido por ID."""
        result = (
            self.db.table(self.table_name)
            .select("*")
            .eq("tenant_id", tenant_id)
            .eq("id", order_id)
            .execute()
        )
        return result.data[0] if result.data else None

    async def create_order(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Cria novo pedido."""
        result = self.db.table(self.table_name).insert(data).execute()
        return result.data[0]

    async def update_order(
        self, tenant_id: str, order_id: int, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Atualiza pedido existente."""
        result = (
            self.db.table(self.table_name)
            .update(data)
            .eq("id", order_id)
            .execute()
        )
        return result.data[0]

    async def delete_order(self, tenant_id: str, order_id: int) -> bool:
        """Remove pedido."""
        self.db.table(self.table_name).delete().eq("id", order_id).execute()
        return True

    async def get_orders_by_customer(
        self, tenant_id: str, customer_id: int
    ) -> List[Dict[str, Any]]:
        """Lista pedidos de um cliente."""
        return await self.list_orders(tenant_id, customer_id=customer_id)

    async def get_open_orders(self, tenant_id: str) -> List[Dict[str, Any]]:
        """Lista pedidos em aberto."""
        return await self.list_orders(tenant_id, status="aberto")
