# apps/ia/app/api/routes/erp/_shared.py
"""
Shared utilities for ERP routes: dependency injection, field mappers.
"""

from typing import Optional, Dict, Any

from fastapi import Header, HTTPException, status

from app.domain.erp.services import (
    CustomerService,
    ProductService,
    OrderService,
    ProfessionalService,
    InventoryService,
)
from app.domain.erp.repository import (
    CustomerRepository,
    ProductRepository,
    OrderRepository,
    ProfessionalRepository,
    InventoryRepository,
)


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


def get_supabase_db():
    """Retorna cliente Supabase."""
    from app.integrations.supabase import get_supabase_client
    return get_supabase_client()


def get_customer_service() -> CustomerService:
    """Retorna CustomerService com repository."""
    db = get_supabase_db()
    repo = CustomerRepository(db)
    return CustomerService(repo)


def get_product_service() -> ProductService:
    """Retorna ProductService com repository."""
    db = get_supabase_db()
    repo = ProductRepository(db)
    return ProductService(repo)


def get_order_service() -> OrderService:
    """Retorna OrderService com repository e inventory_repository para baixa de estoque."""
    db = get_supabase_db()
    order_repo = OrderRepository(db)
    inventory_repo = InventoryRepository(db)
    return OrderService(order_repo, inventory_repo)


def get_professional_service() -> ProfessionalService:
    """Retorna ProfessionalService com repository."""
    db = get_supabase_db()
    repo = ProfessionalRepository(db)
    return ProfessionalService(repo)


def get_inventory_service() -> InventoryService:
    """Retorna InventoryService com repository."""
    db = get_supabase_db()
    repo = InventoryRepository(db)
    return InventoryService(repo)


# ==============================================================================
# FIELD MAPPERS — Customers
# ==============================================================================

def map_customer_to_db(data: Dict[str, Any]) -> Dict[str, Any]:
    """Mapeia campos do frontend (EN) para o banco (PT)."""
    mapping = {
        "name": "nome",
        "document": "cpf_cnpj",
        "document_type": None,  # ignorar
        "phone": "telefone",
        "address": "logradouro",
        "city": "cidade",
        "state": "uf",
        "notes": "observacoes",
    }
    result = {}
    for key, value in data.items():
        if key in mapping:
            db_key = mapping[key]
            if db_key:  # ignorar campos mapeados para None
                result[db_key] = value
        else:
            result[key] = value
    # Adicionar tipo padrão se não existir
    if "tipo" not in result:
        result["tipo"] = "cliente"
    return result


def map_customer_from_db(data: Dict[str, Any]) -> Dict[str, Any]:
    """Mapeia campos do banco (PT) para o frontend (EN)."""
    if not data:
        return data
    return {
        "id": str(data.get("id", "")),
        "tenant_id": data.get("tenant_id", ""),
        "name": data.get("nome", ""),
        "document": data.get("cpf_cnpj"),
        "document_type": "cpf" if data.get("cpf_cnpj") and len(data.get("cpf_cnpj", "").replace(".", "").replace("-", "").replace("/", "")) <= 11 else "cnpj",
        "email": data.get("email"),
        "phone": data.get("telefone"),
        "address": data.get("logradouro"),
        "city": data.get("cidade"),
        "state": data.get("uf"),
        "notes": data.get("observacoes"),
        "created_at": str(data.get("created_at", "")),
        "updated_at": str(data.get("updated_at", "")),
    }


# ==============================================================================
# FIELD MAPPERS — Products
# ==============================================================================

def map_product_to_db(data: Dict[str, Any]) -> Dict[str, Any]:
    """Mapeia campos do frontend (EN) para o banco (PT)."""
    import uuid
    mapping = {
        "name": "nome",
        "description": "descricao",
        "category": "categoria",
        "cost_price": "preco_custo",
        "sale_price": "preco_venda",
        "unit": "unidade",
        "active": "ativo",
    }
    result = {}
    for key, value in data.items():
        if key in mapping:
            result[mapping[key]] = value
        else:
            result[key] = value
    # Mapear type do frontend (en) para banco (pt)
    if "type" in result:
        tipo_map = {"product": "produto", "service": "servico", "kit": "kit"}
        result["tipo"] = tipo_map.get(result.pop("type"), "produto")
    if "tipo" not in result:
        result["tipo"] = "produto"
    # Gerar SKU automatico se nao fornecido
    if not result.get("sku"):
        prefix = "SVC" if result.get("tipo") == "servico" else "PRD"
        result["sku"] = f"{prefix}-{uuid.uuid4().hex[:8].upper()}"
    return result


def map_product_from_db(data: Dict[str, Any]) -> Dict[str, Any]:
    """Mapeia campos do banco (PT) para o frontend (EN)."""
    if not data:
        return data
    # Mapear tipo do banco (pt) para frontend (en)
    tipo_map = {"produto": "product", "servico": "service", "kit": "kit"}
    tipo_db = data.get("tipo", "produto")
    tipo_en = tipo_map.get(tipo_db, tipo_db)
    return {
        "id": str(data.get("id", "")),
        "tenant_id": data.get("tenant_id", ""),
        "name": data.get("nome", ""),
        "sku": data.get("sku"),
        "description": data.get("descricao"),
        "category": data.get("categoria"),
        "type": tipo_en,
        "unit": data.get("unidade", "UN"),
        "cost_price": float(data.get("preco_custo", 0) or 0),
        "sale_price": float(data.get("preco_venda", 0) or 0),
        "ncm": data.get("ncm"),
        "active": data.get("ativo", True),
        "created_at": str(data.get("created_at", "")),
        "updated_at": str(data.get("updated_at", "")),
    }


# ==============================================================================
# FIELD MAPPERS — Orders
# ==============================================================================

def map_order_item_to_db(item: Dict[str, Any]) -> Dict[str, Any]:
    """Mapeia campos do item do frontend (EN) para o banco (PT)."""
    return {
        "produto_id": item.get("product_id"),
        "nome_produto": item.get("product_name"),
        "item_type": item.get("item_type"),  # product ou service
        "quantidade": item.get("quantity", 1),
        "preco_unitario": item.get("unit_price", 0),
        "desconto": item.get("discount", 0),
        "total": item.get("total", 0),
    }


def map_order_to_db(data: Dict[str, Any]) -> Dict[str, Any]:
    """Mapeia campos do frontend (EN) para o banco (PT)."""
    mapping = {
        "type": "tipo",
        "discount": "desconto",
        "payment_method": "forma_pagamento",
        "notes": "observacoes",
    }
    result = {}
    for key, value in data.items():
        # Ignorar campos que nao existem na tabela
        if key in ("customer_name", "professional_name"):
            continue
        if key in mapping:
            result[mapping[key]] = value
        else:
            result[key] = value
    # Converter professional_id para int se for string
    if "professional_id" in result and result["professional_id"]:
        try:
            result["professional_id"] = int(result["professional_id"])
        except (ValueError, TypeError):
            result["professional_id"] = None
    # Mapear tipo de venda
    if result.get("tipo") == "sale":
        result["tipo"] = "venda"
    elif result.get("tipo") == "service_order":
        result["tipo"] = "os"
    # Mapear status
    if result.get("status") == "open":
        result["status"] = "aberto"
    elif result.get("status") == "closed":
        result["status"] = "fechado"
    elif result.get("status") == "cancelled":
        result["status"] = "cancelado"
    # Mapear items
    if "items" in result and isinstance(result["items"], list):
        result["items"] = [map_order_item_to_db(item) for item in result["items"]]
    # Converter customer_id para int se for string
    if "customer_id" in result and result["customer_id"]:
        try:
            result["customer_id"] = int(result["customer_id"])
        except (ValueError, TypeError):
            result["customer_id"] = None
    return result


def map_order_item_from_db(item: Dict[str, Any]) -> Dict[str, Any]:
    """Mapeia campos do item do banco (PT) para o frontend (EN)."""
    return {
        "product_id": str(item.get("produto_id", "")),
        "product_name": item.get("nome_produto", ""),
        "item_type": item.get("item_type"),  # product ou service
        "quantity": item.get("quantidade", 1),
        "unit_price": float(item.get("preco_unitario", 0) or 0),
        "discount": float(item.get("desconto", 0) or 0),
        "total": float(item.get("total", 0) or 0),
    }


def map_order_from_db(data: Dict[str, Any]) -> Dict[str, Any]:
    """Mapeia campos do banco (PT) para o frontend (EN)."""
    if not data:
        return data
    tipo_map = {"venda": "sale", "os": "service_order"}
    status_map = {"aberto": "open", "fechado": "closed", "cancelado": "cancelled"}
    raw_items = data.get("items", [])
    items = [map_order_item_from_db(item) for item in raw_items] if raw_items else []
    return {
        "id": str(data.get("id", "")),
        "tenant_id": data.get("tenant_id", ""),
        "customer_id": str(data.get("customer_id", "")) if data.get("customer_id") else None,
        "customer_name": None,  # Seria preenchido com JOIN
        "professional_id": str(data.get("professional_id", "")) if data.get("professional_id") else None,
        "professional_name": data.get("professional_name"),
        "type": tipo_map.get(data.get("tipo", ""), data.get("tipo", "")),
        "status": status_map.get(data.get("status", ""), data.get("status", "")),
        "scheduled_date": str(data.get("scheduled_date", "")) if data.get("scheduled_date") else None,
        "description": data.get("description"),
        "items": items,
        "subtotal": float(data.get("subtotal", 0) or 0),
        "discount": float(data.get("desconto", 0) or 0),
        "total": float(data.get("total", 0) or 0),
        "payment_method": data.get("forma_pagamento"),
        "notes": data.get("observacoes"),
        "created_at": str(data.get("created_at", "")),
        "updated_at": str(data.get("updated_at", "")),
        "closed_at": str(data.get("fechado_em", "")) if data.get("fechado_em") else None,
    }


# ==============================================================================
# FIELD MAPPERS — Professionals
# ==============================================================================

def map_professional_to_db(data: Dict[str, Any]) -> Dict[str, Any]:
    """Mapeia campos do frontend (EN) para o banco (PT)."""
    mapping = {
        "name": "nome",
        "phone": "telefone",
        "specialty": "especialidade",
        "active": "ativo",
    }
    result = {}
    for key, value in data.items():
        if key in mapping:
            result[mapping[key]] = value
        else:
            result[key] = value
    return result


def map_professional_from_db(data: Dict[str, Any]) -> Dict[str, Any]:
    """Mapeia campos do banco (PT) para o frontend (EN)."""
    if not data:
        return data
    return {
        "id": str(data.get("id", "")),
        "tenant_id": data.get("tenant_id", ""),
        "name": data.get("nome", ""),
        "email": data.get("email"),
        "phone": data.get("telefone"),
        "specialty": data.get("especialidade"),
        "active": data.get("ativo", True),
        "created_at": str(data.get("created_at", "")),
        "updated_at": str(data.get("updated_at", "")),
    }


# ==============================================================================
# FIELD MAPPERS — Inventory
# ==============================================================================

def map_inventory_to_db(data: Dict[str, Any]) -> Dict[str, Any]:
    """Mapeia campos do frontend (EN) para o banco (PT)."""
    mapping = {
        "warehouse": "deposito",
        "quantity": "quantidade",
    }
    result = {}
    for key, value in data.items():
        if key in mapping:
            result[mapping[key]] = value
        else:
            result[key] = value
    return result


def map_inventory_from_db(data: Dict[str, Any]) -> Dict[str, Any]:
    """Mapeia campos do banco (PT) para o frontend (EN)."""
    if not data:
        return data
    return {
        "id": str(data.get("id", "")),
        "tenant_id": data.get("tenant_id", ""),
        "product_id": str(data.get("product_id", "")),
        "warehouse": data.get("deposito", "principal"),
        "quantity": float(data.get("quantidade", 0) or 0),
        "reserved": float(data.get("reservado", 0) or 0),
        "average_cost": float(data.get("custo_medio", 0) or 0),
        "last_cost": float(data.get("custo_ultimo", 0) or 0),
        "created_at": str(data.get("created_at", "")),
        "updated_at": str(data.get("updated_at", "")),
    }
