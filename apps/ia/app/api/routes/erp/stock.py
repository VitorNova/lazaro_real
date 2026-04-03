# apps/ia/app/api/routes/erp/stock.py
"""ERP — Inventory/Stock CRUD endpoints."""

from typing import List, Dict, Any

from fastapi import APIRouter, Depends, status

from app.domain.erp.services import InventoryService

from app.api.routes.erp._shared import (
    get_tenant_id,
    get_inventory_service,
    map_inventory_to_db,
    map_inventory_from_db,
)

router = APIRouter()


@router.get("/inventory", response_model=List[Dict[str, Any]])
async def list_inventory(
    tenant_id: str = Depends(get_tenant_id),
    service: InventoryService = Depends(get_inventory_service),
):
    """Lista estoque do tenant."""
    inventory = await service.list_inventory(tenant_id)
    return [map_inventory_from_db(i) for i in inventory]


@router.get("/inventory/product/{product_id}")
async def get_inventory_by_product(
    product_id: int,
    tenant_id: str = Depends(get_tenant_id),
    service: InventoryService = Depends(get_inventory_service),
):
    """Busca estoque de um produto."""
    inventory = await service.get_inventory_by_product(tenant_id, product_id)
    return [map_inventory_from_db(i) for i in inventory]


@router.post("/inventory", status_code=status.HTTP_201_CREATED)
async def add_inventory(
    data: Dict[str, Any],
    tenant_id: str = Depends(get_tenant_id),
    service: InventoryService = Depends(get_inventory_service),
):
    """Adiciona registro de estoque."""
    db_data = map_inventory_to_db(data)
    result = await service.add_inventory(tenant_id, db_data)
    return map_inventory_from_db(result)


@router.put("/inventory/{inventory_id}")
async def update_inventory(
    inventory_id: int,
    data: Dict[str, Any],
    tenant_id: str = Depends(get_tenant_id),
    service: InventoryService = Depends(get_inventory_service),
):
    """Atualiza registro de estoque."""
    db_data = map_inventory_to_db(data)
    result = await service.update_inventory(tenant_id, inventory_id, db_data)
    return map_inventory_from_db(result)
