# apps/ia/app/api/routes/erp/professionals.py
"""ERP — Professional CRUD endpoints."""

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
    get_product_service,
    get_order_service,
    get_professional_service,
    map_professional_to_db,
    map_professional_from_db,
    map_order_from_db,
)

router = APIRouter()


@router.get("/professionals", response_model=List[Dict[str, Any]])
async def list_professionals(
    tenant_id: str = Depends(get_tenant_id),
    service: ProfessionalService = Depends(get_professional_service),
):
    """Lista profissionais do tenant."""
    professionals = await service.list_professionals(tenant_id)
    return [map_professional_from_db(p) for p in professionals]


@router.get("/professionals/{professional_id}")
async def get_professional(
    professional_id: int,
    tenant_id: str = Depends(get_tenant_id),
    service: ProfessionalService = Depends(get_professional_service),
):
    """Busca profissional por ID."""
    professional = await service.get_professional(tenant_id, professional_id)
    if not professional:
        raise HTTPException(status_code=404, detail="Profissional nao encontrado")
    return map_professional_from_db(professional)


@router.post("/professionals", status_code=status.HTTP_201_CREATED)
async def create_professional(
    data: Dict[str, Any],
    tenant_id: str = Depends(get_tenant_id),
    service: ProfessionalService = Depends(get_professional_service),
):
    """Cria novo profissional."""
    db_data = map_professional_to_db(data)
    result = await service.create_professional(tenant_id, db_data)
    return map_professional_from_db(result)


@router.put("/professionals/{professional_id}")
async def update_professional(
    professional_id: int,
    data: Dict[str, Any],
    tenant_id: str = Depends(get_tenant_id),
    service: ProfessionalService = Depends(get_professional_service),
):
    """Atualiza profissional existente."""
    db_data = map_professional_to_db(data)
    result = await service.update_professional(tenant_id, professional_id, db_data)
    return map_professional_from_db(result)


@router.delete("/professionals/{professional_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_professional(
    professional_id: int,
    tenant_id: str = Depends(get_tenant_id),
    service: ProfessionalService = Depends(get_professional_service),
):
    """Remove profissional."""
    await service.delete_professional(tenant_id, professional_id)
    return None


@router.get("/professionals/{professional_id}/orders")
async def get_professional_history(
    professional_id: int,
    tenant_id: str = Depends(get_tenant_id),
    professional_service: ProfessionalService = Depends(get_professional_service),
    order_service: OrderService = Depends(get_order_service),
    customer_service: CustomerService = Depends(get_customer_service),
    product_service: ProductService = Depends(get_product_service),
    month: Optional[int] = None,
    year: Optional[int] = None,
):
    """Retorna historico de ordens do profissional com estatisticas."""
    from datetime import datetime
    import calendar

    # Buscar profissional
    professional = await professional_service.get_professional(tenant_id, professional_id)
    if not professional:
        raise HTTPException(status_code=404, detail="Profissional não encontrado")

    # Buscar clientes e produtos para enriquecer dados
    all_customers = await customer_service.list_customers(tenant_id)
    all_products = await product_service.list_products(tenant_id)

    # Criar mapas de lookup
    cust_map = {str(c.get("id")): c.get("nome") or c.get("name") for c in all_customers}
    prod_map = {str(p.get("id")): p.get("nome") or p.get("name") for p in all_products}

    # Buscar todas as ordens
    all_orders = await order_service.list_orders(tenant_id)

    # Filtrar ordens do profissional (professional_id pode ser string ou int)
    professional_orders = [o for o in all_orders if str(o.get("professional_id") or o.get("profissional_id")) == str(professional_id)]

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

        professional_orders = [
            o for o in professional_orders
            if parse_date(o.get("created_at")) and
               start_date <= parse_date(o.get("created_at")).replace(tzinfo=None) <= end_date
        ]

    # Enriquecer ordens com nomes
    def enrich_order(order):
        enriched = map_order_from_db(order)
        # Adicionar nome do cliente
        cust_id = str(order.get("customer_id") or order.get("cliente_id") or "")
        enriched["customer_name"] = cust_map.get(cust_id)
        # Adicionar nomes dos produtos/servicos nos items
        if enriched.get("items"):
            for item in enriched["items"]:
                prod_id = str(item.get("product_id") or "")
                item["product_name"] = prod_map.get(prod_id)
        return enriched

    # Calcular estatisticas (usando todas as ordens, não filtradas)
    all_professional_orders = [o for o in all_orders if str(o.get("professional_id") or o.get("profissional_id")) == str(professional_id)]
    total_orders = len(all_professional_orders)
    total_revenue = sum(o.get("total", 0) or 0 for o in all_professional_orders)
    orders_completed = len([o for o in all_professional_orders if o.get("status") == "fechado"])
    orders_cancelled = len([o for o in all_professional_orders if o.get("status") == "cancelado"])

    return {
        "professional": map_professional_from_db(professional),
        "orders": [enrich_order(o) for o in professional_orders],
        "stats": {
            "total_orders": total_orders,
            "total_revenue": total_revenue,
            "orders_completed": orders_completed,
            "orders_cancelled": orders_cancelled,
        }
    }
