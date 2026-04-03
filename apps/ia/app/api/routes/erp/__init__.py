# apps/ia/app/api/routes/erp/__init__.py
"""
ERP Router — agrega sub-routers de customers, products, orders,
professionals e stock (inventory).

Uso:
    from app.api.routes.erp import router as erp_router
    app.include_router(erp_router, prefix="/api/erp", tags=["erp"])
"""

from fastapi import APIRouter

from app.api.routes.erp.customers import router as customers_router
from app.api.routes.erp.products import router as products_router
from app.api.routes.erp.orders import router as orders_router
from app.api.routes.erp.professionals import router as professionals_router
from app.api.routes.erp.stock import router as stock_router

router = APIRouter(tags=["erp"])

router.include_router(customers_router)
router.include_router(products_router)
router.include_router(orders_router)
router.include_router(professionals_router)
router.include_router(stock_router)
