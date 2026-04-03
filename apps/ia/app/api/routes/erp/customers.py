# apps/ia/app/api/routes/erp/customers.py
"""ERP — Customer CRUD endpoints."""

from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.domain.erp.services import (
    CustomerService,
    ProductService,
    OrderService,
    ProfessionalService,
)

from app.api.routes.erp._shared import (
    get_tenant_id,
    get_customer_service,
    get_order_service,
    get_professional_service,
    get_product_service,
    map_customer_to_db,
    map_customer_from_db,
    map_order_from_db,
)

router = APIRouter()


@router.get("/customers", response_model=List[Dict[str, Any]])
async def list_customers(
    tenant_id: str = Depends(get_tenant_id),
    service: CustomerService = Depends(get_customer_service),
):
    """Lista clientes do tenant."""
    customers = await service.list_customers(tenant_id)
    return [map_customer_from_db(c) for c in customers]


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
    return map_customer_from_db(customer)


@router.post("/customers", status_code=status.HTTP_201_CREATED)
async def create_customer(
    data: Dict[str, Any],
    tenant_id: str = Depends(get_tenant_id),
    service: CustomerService = Depends(get_customer_service),
):
    """Cria novo cliente."""
    db_data = map_customer_to_db(data)
    result = await service.create_customer(tenant_id, db_data)
    return map_customer_from_db(result)


@router.put("/customers/{customer_id}")
async def update_customer(
    customer_id: int,
    data: Dict[str, Any],
    tenant_id: str = Depends(get_tenant_id),
    service: CustomerService = Depends(get_customer_service),
):
    """Atualiza cliente existente."""
    db_data = map_customer_to_db(data)
    result = await service.update_customer(tenant_id, customer_id, db_data)
    return map_customer_from_db(result)


@router.delete("/customers/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer(
    customer_id: int,
    tenant_id: str = Depends(get_tenant_id),
    service: CustomerService = Depends(get_customer_service),
):
    """Remove cliente."""
    await service.delete_customer(tenant_id, customer_id)
    return None


@router.get("/customers/{customer_id}/orders")
async def get_customer_history(
    customer_id: int,
    tenant_id: str = Depends(get_tenant_id),
    customer_service: CustomerService = Depends(get_customer_service),
    order_service: OrderService = Depends(get_order_service),
    professional_service: ProfessionalService = Depends(get_professional_service),
    product_service: ProductService = Depends(get_product_service),
    month: Optional[int] = None,
    year: Optional[int] = None,
):
    """Retorna historico de ordens do cliente com estatisticas."""
    from datetime import datetime
    import calendar

    # Buscar cliente
    customer = await customer_service.get_customer(tenant_id, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    # Buscar profissionais e produtos para enriquecer dados
    all_professionals = await professional_service.list_professionals(tenant_id)
    all_products = await product_service.list_products(tenant_id)

    # Criar mapas de lookup
    prof_map = {str(p.get("id")): p.get("nome") or p.get("name") for p in all_professionals}
    prod_map = {str(p.get("id")): p.get("nome") or p.get("name") for p in all_products}

    # Buscar todas as ordens
    all_orders = await order_service.list_orders(tenant_id)

    # Filtrar ordens do cliente (customer_id pode ser string ou int)
    customer_orders = [o for o in all_orders if str(o.get("customer_id") or o.get("cliente_id")) == str(customer_id)]

    # Filtrar por mês/ano se fornecido
    if month and year:
        def parse_date(date_str):
            if not date_str:
                return None
            try:
                return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except:
                return None

        _, last_day = calendar.monthrange(year, month)
        start_date = datetime(year, month, 1)
        end_date = datetime(year, month, last_day, 23, 59, 59)

        customer_orders = [
            o for o in customer_orders
            if parse_date(o.get("created_at")) and
               start_date <= parse_date(o.get("created_at")).replace(tzinfo=None) <= end_date
        ]

    # Enriquecer ordens com nomes
    def enrich_order(order):
        enriched = map_order_from_db(order)
        # Adicionar nome do profissional
        prof_id = str(order.get("professional_id") or order.get("profissional_id") or "")
        enriched["professional_name"] = prof_map.get(prof_id)
        # Adicionar nomes dos produtos/servicos nos items
        if enriched.get("items"):
            for item in enriched["items"]:
                prod_id = str(item.get("product_id") or "")
                item["product_name"] = prod_map.get(prod_id)
        return enriched

    # Calcular estatisticas (usando todas as ordens, não filtradas)
    all_customer_orders = [o for o in all_orders if str(o.get("customer_id") or o.get("cliente_id")) == str(customer_id)]
    total_orders = len(all_customer_orders)
    total_spent = sum(o.get("total", 0) or 0 for o in all_customer_orders)
    orders_completed = len([o for o in all_customer_orders if o.get("status") == "fechado"])
    orders_cancelled = len([o for o in all_customer_orders if o.get("status") == "cancelado"])

    return {
        "customer": map_customer_from_db(customer),
        "orders": [enrich_order(o) for o in customer_orders],
        "stats": {
            "total_orders": total_orders,
            "total_spent": total_spent,
            "orders_completed": orders_completed,
            "orders_cancelled": orders_cancelled,
        }
    }
