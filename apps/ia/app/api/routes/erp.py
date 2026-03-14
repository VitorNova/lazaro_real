# apps/ia/app/api/routes/erp.py
"""
API Routes para ERP.

Endpoints REST para clientes, produtos e pedidos.
Autenticação via header X-Tenant-ID.
"""

from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, Header, HTTPException, status

from apps.ia.app.domain.erp.services import CustomerService, ProductService, OrderService
from apps.ia.app.domain.erp.repository import CustomerRepository, ProductRepository, OrderRepository

router = APIRouter(tags=["erp"])


# ==============================================================================
# DEPENDENCY INJECTION
# ==============================================================================

def get_tenant_id(x_tenant_id: Optional[str] = Header(None)) -> str:
    """Extrai tenant_id do header."""
    if not x_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Header X-Tenant-ID é obrigatório",
        )
    return x_tenant_id


def get_supabase_client():
    """Retorna cliente Supabase."""
    from apps.ia.app.integrations.supabase import get_supabase_service
    return get_supabase_service().client


def get_customer_service() -> CustomerService:
    """Retorna CustomerService com repository."""
    db = get_supabase_client()
    repo = CustomerRepository(db)
    return CustomerService(repo)


def get_product_service() -> ProductService:
    """Retorna ProductService com repository."""
    db = get_supabase_client()
    repo = ProductRepository(db)
    return ProductService(repo)


def get_order_service() -> OrderService:
    """Retorna OrderService com repository."""
    db = get_supabase_client()
    repo = OrderRepository(db)
    return OrderService(repo)


# ==============================================================================
# CUSTOMERS
# ==============================================================================

@router.get("/customers", response_model=List[Dict[str, Any]])
async def list_customers(
    tenant_id: str = Depends(get_tenant_id),
    service: CustomerService = Depends(get_customer_service),
):
    """Lista clientes do tenant."""
    return await service.list_customers(tenant_id)


@router.get("/customers/{customer_id}")
async def get_customer(
    customer_id: int,
    tenant_id: str = Depends(get_tenant_id),
    service: CustomerService = Depends(get_customer_service),
):
    """Busca cliente por ID."""
    customer = await service.get_customer(tenant_id, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")
    return customer


@router.post("/customers", status_code=status.HTTP_201_CREATED)
async def create_customer(
    data: Dict[str, Any],
    tenant_id: str = Depends(get_tenant_id),
    service: CustomerService = Depends(get_customer_service),
):
    """Cria novo cliente."""
    return await service.create_customer(tenant_id, data)


@router.put("/customers/{customer_id}")
async def update_customer(
    customer_id: int,
    data: Dict[str, Any],
    tenant_id: str = Depends(get_tenant_id),
    service: CustomerService = Depends(get_customer_service),
):
    """Atualiza cliente existente."""
    return await service.update_customer(tenant_id, customer_id, data)


@router.delete("/customers/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer(
    customer_id: int,
    tenant_id: str = Depends(get_tenant_id),
    service: CustomerService = Depends(get_customer_service),
):
    """Remove cliente."""
    await service.delete_customer(tenant_id, customer_id)
    return None


# ==============================================================================
# PRODUCTS
# ==============================================================================

@router.get("/products", response_model=List[Dict[str, Any]])
async def list_products(
    tenant_id: str = Depends(get_tenant_id),
    service: ProductService = Depends(get_product_service),
):
    """Lista produtos do tenant."""
    return await service.list_products(tenant_id)


@router.get("/products/{product_id}")
async def get_product(
    product_id: int,
    tenant_id: str = Depends(get_tenant_id),
    service: ProductService = Depends(get_product_service),
):
    """Busca produto por ID."""
    product = await service.get_product(tenant_id, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    return product


@router.post("/products", status_code=status.HTTP_201_CREATED)
async def create_product(
    data: Dict[str, Any],
    tenant_id: str = Depends(get_tenant_id),
    service: ProductService = Depends(get_product_service),
):
    """Cria novo produto."""
    return await service.create_product(tenant_id, data)


@router.put("/products/{product_id}")
async def update_product(
    product_id: int,
    data: Dict[str, Any],
    tenant_id: str = Depends(get_tenant_id),
    service: ProductService = Depends(get_product_service),
):
    """Atualiza produto existente."""
    return await service.update_product(tenant_id, product_id, data)


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: int,
    tenant_id: str = Depends(get_tenant_id),
    service: ProductService = Depends(get_product_service),
):
    """Remove produto."""
    await service.delete_product(tenant_id, product_id)
    return None


# ==============================================================================
# ORDERS
# ==============================================================================

@router.get("/orders", response_model=List[Dict[str, Any]])
async def list_orders(
    tenant_id: str = Depends(get_tenant_id),
    service: OrderService = Depends(get_order_service),
    status_filter: Optional[str] = None,
):
    """Lista pedidos do tenant."""
    return await service.list_orders(tenant_id, status=status_filter)


@router.get("/orders/{order_id}")
async def get_order(
    order_id: int,
    tenant_id: str = Depends(get_tenant_id),
    service: OrderService = Depends(get_order_service),
):
    """Busca pedido por ID."""
    order = await service.get_order(tenant_id, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    return order


@router.post("/orders", status_code=status.HTTP_201_CREATED)
async def create_order(
    data: Dict[str, Any],
    tenant_id: str = Depends(get_tenant_id),
    service: OrderService = Depends(get_order_service),
):
    """Cria novo pedido."""
    return await service.create_order(tenant_id, data)


@router.put("/orders/{order_id}")
async def update_order(
    order_id: int,
    data: Dict[str, Any],
    tenant_id: str = Depends(get_tenant_id),
    service: OrderService = Depends(get_order_service),
):
    """Atualiza pedido existente."""
    return await service.update_order(tenant_id, order_id, data)


@router.post("/orders/{order_id}/close")
async def close_order(
    order_id: int,
    data: Dict[str, Any],
    tenant_id: str = Depends(get_tenant_id),
    service: OrderService = Depends(get_order_service),
):
    """Fecha pedido com pagamento."""
    return await service.close_order(tenant_id, order_id, data)


# ==============================================================================
# DASHBOARD
# ==============================================================================

@router.get("/dashboard")
async def get_dashboard(
    tenant_id: str = Depends(get_tenant_id),
    order_service: OrderService = Depends(get_order_service),
    customer_service: CustomerService = Depends(get_customer_service),
):
    """Retorna totais do dashboard."""
    orders = await order_service.list_orders(tenant_id)
    customers = await customer_service.list_customers(tenant_id)

    vendas_hoje = sum(1 for o in orders if o.get("tipo") == "venda")
    total_vendas = sum(o.get("total", 0) for o in orders if o.get("tipo") == "venda")

    return {
        "vendas_hoje": vendas_hoje,
        "total_vendas": total_vendas,
        "total_clientes": len(customers),
        "pedidos_abertos": sum(1 for o in orders if o.get("status") == "aberto"),
    }
