# apps/ia/app/api/routes/erp/orders.py
"""ERP — Order CRUD endpoints + Dashboard."""

from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.domain.erp.services import (
    CustomerService,
    ProductService,
    OrderService,
)

from app.api.routes.erp._shared import (
    get_tenant_id,
    get_customer_service,
    get_product_service,
    get_order_service,
    map_order_to_db,
    map_order_from_db,
)

router = APIRouter()


@router.get("/orders", response_model=List[Dict[str, Any]])
async def list_orders(
    tenant_id: str = Depends(get_tenant_id),
    service: OrderService = Depends(get_order_service),
    status_filter: Optional[str] = None,
    month: Optional[int] = None,
    year: Optional[int] = None,
):
    """Lista pedidos do tenant com filtro opcional por mês/ano."""
    from datetime import datetime
    import calendar

    orders = await service.list_orders(tenant_id, status=status_filter)

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

        orders = [
            o for o in orders
            if parse_date(o.get("created_at")) and
               start_date <= parse_date(o.get("created_at")).replace(tzinfo=None) <= end_date
        ]

    return [map_order_from_db(o) for o in orders]


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
    return map_order_from_db(order)


@router.post("/orders", status_code=status.HTTP_201_CREATED)
async def create_order(
    data: Dict[str, Any],
    tenant_id: str = Depends(get_tenant_id),
    service: OrderService = Depends(get_order_service),
):
    """Cria novo pedido."""
    db_data = map_order_to_db(data)
    result = await service.create_order(tenant_id, db_data)
    return map_order_from_db(result)


@router.put("/orders/{order_id}")
async def update_order(
    order_id: int,
    data: Dict[str, Any],
    tenant_id: str = Depends(get_tenant_id),
    service: OrderService = Depends(get_order_service),
):
    """Atualiza pedido existente."""
    db_data = map_order_to_db(data)
    result = await service.update_order(tenant_id, order_id, db_data)
    return map_order_from_db(result)


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
    product_service: ProductService = Depends(get_product_service),
    month: Optional[int] = None,
    year: Optional[int] = None,
):
    """Retorna totais do dashboard com filtro opcional por mês/ano."""
    from datetime import datetime, timedelta
    import calendar

    orders = await order_service.list_orders(tenant_id)
    customers = await customer_service.list_customers(tenant_id)
    products = await product_service.list_products(tenant_id)

    now = datetime.now()
    today = now.date()

    def parse_date(date_str):
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
        except:
            return None

    # Se mês/ano fornecido, filtra pelo período selecionado
    if month and year:
        _, last_day = calendar.monthrange(year, month)
        start_date = datetime(year, month, 1).date()
        end_date = datetime(year, month, last_day).date()

        # Filtrar ordens do mês selecionado
        orders_in_period = [
            o for o in orders
            if parse_date(o.get("created_at")) and
               start_date <= parse_date(o.get("created_at")) <= end_date
        ]

        # Se é o mês atual, mantém estatísticas de hoje/semana
        is_current_month = month == now.month and year == now.year

        if is_current_month:
            week_ago = today - timedelta(days=7)
            orders_today = [o for o in orders if parse_date(o.get("created_at")) == today]
            orders_week = [o for o in orders if parse_date(o.get("created_at")) and parse_date(o.get("created_at")) >= week_ago]
        else:
            # Para meses passados, "today" mostra total do período
            orders_today = orders_in_period
            orders_week = orders_in_period

        orders_month = orders_in_period
    else:
        # Comportamento padrão (mês atual)
        week_ago = today - timedelta(days=7)
        month_ago = today - timedelta(days=30)

        orders_today = [o for o in orders if parse_date(o.get("created_at")) == today]
        orders_week = [o for o in orders if parse_date(o.get("created_at")) and parse_date(o.get("created_at")) >= week_ago]
        orders_month = [o for o in orders if parse_date(o.get("created_at")) and parse_date(o.get("created_at")) >= month_ago]

    return {
        "customers_count": len(customers),
        "products_count": len(products),
        "orders_today": len(orders_today),
        "revenue_today": sum(float(o.get("total", 0) or 0) for o in orders_today),
        "orders_week": len(orders_week),
        "revenue_week": sum(float(o.get("total", 0) or 0) for o in orders_week),
        "orders_month": len(orders_month),
        "revenue_month": sum(float(o.get("total", 0) or 0) for o in orders_month),
    }
