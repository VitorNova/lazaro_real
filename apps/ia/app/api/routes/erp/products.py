# apps/ia/app/api/routes/erp/products.py
"""ERP — Product CRUD endpoints."""

from typing import List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.domain.erp.services import ProductService

from app.api.routes.erp._shared import (
    get_tenant_id,
    get_product_service,
    map_product_to_db,
    map_product_from_db,
)

router = APIRouter()


@router.get("/products", response_model=List[Dict[str, Any]])
async def list_products(
    tenant_id: str = Depends(get_tenant_id),
    service: ProductService = Depends(get_product_service),
):
    """Lista produtos do tenant."""
    products = await service.list_products(tenant_id)
    return [map_product_from_db(p) for p in products]


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
    return map_product_from_db(product)


@router.post("/products", status_code=status.HTTP_201_CREATED)
async def create_product(
    data: Dict[str, Any],
    tenant_id: str = Depends(get_tenant_id),
    service: ProductService = Depends(get_product_service),
):
    """Cria novo produto."""
    db_data = map_product_to_db(data)
    result = await service.create_product(tenant_id, db_data)
    return map_product_from_db(result)


@router.put("/products/{product_id}")
async def update_product(
    product_id: int,
    data: Dict[str, Any],
    tenant_id: str = Depends(get_tenant_id),
    service: ProductService = Depends(get_product_service),
):
    """Atualiza produto existente."""
    db_data = map_product_to_db(data)
    result = await service.update_product(tenant_id, product_id, db_data)
    return map_product_from_db(result)


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: int,
    tenant_id: str = Depends(get_tenant_id),
    service: ProductService = Depends(get_product_service),
):
    """Remove produto."""
    await service.delete_product(tenant_id, product_id)
    return None
