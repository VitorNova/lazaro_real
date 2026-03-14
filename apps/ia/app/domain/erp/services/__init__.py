# apps/ia/app/domain/erp/services/__init__.py
"""ERP Services."""

from .crud import CustomerService, ProductService, OrderService

__all__ = ["CustomerService", "ProductService", "OrderService"]
