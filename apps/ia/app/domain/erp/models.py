# apps/ia/app/domain/erp/models.py
"""
Pydantic Models para ERP MVP.

Baseado em:
- Purple-Stock (UX moderna)
- djangoSIGE (regras BR)

Entidades:
- Customer: cliente/fornecedor
- Product: produto/serviço
- Order: venda/OS
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, field_validator, ConfigDict


# ==============================================================================
# CUSTOMER MODELS
# ==============================================================================

class CustomerBase(BaseModel):
    """Campos comuns de Cliente."""
    tenant_id: str
    tipo: Literal["cliente", "fornecedor", "ambos"]
    nome: str = Field(..., min_length=1, max_length=200)
    nome_fantasia: Optional[str] = None
    cpf_cnpj: Optional[str] = None
    ie: Optional[str] = None
    im: Optional[str] = None
    email: Optional[str] = None
    telefone: Optional[str] = None
    celular: Optional[str] = None
    cep: Optional[str] = None
    logradouro: Optional[str] = None
    numero: Optional[str] = None
    complemento: Optional[str] = None
    bairro: Optional[str] = None
    cidade: Optional[str] = None
    uf: Optional[str] = Field(None, max_length=2)
    observacoes: Optional[str] = None


class CustomerCreate(CustomerBase):
    """Dados para criar cliente."""
    pass


class CustomerUpdate(BaseModel):
    """Dados para atualizar cliente (todos opcionais)."""
    tipo: Optional[Literal["cliente", "fornecedor", "ambos"]] = None
    nome: Optional[str] = Field(None, min_length=1, max_length=200)
    nome_fantasia: Optional[str] = None
    cpf_cnpj: Optional[str] = None
    ie: Optional[str] = None
    im: Optional[str] = None
    email: Optional[str] = None
    telefone: Optional[str] = None
    celular: Optional[str] = None
    cep: Optional[str] = None
    logradouro: Optional[str] = None
    numero: Optional[str] = None
    complemento: Optional[str] = None
    bairro: Optional[str] = None
    cidade: Optional[str] = None
    uf: Optional[str] = Field(None, max_length=2)
    observacoes: Optional[str] = None
    ativo: Optional[bool] = None


class CustomerResponse(CustomerBase):
    """Resposta com dados do cliente."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    ativo: bool = True
    created_at: datetime
    updated_at: Optional[datetime] = None


# ==============================================================================
# PRODUCT MODELS
# ==============================================================================

class ProductBase(BaseModel):
    """Campos comuns de Produto."""
    tenant_id: str
    sku: str = Field(..., min_length=1, max_length=50)
    nome: str = Field(..., min_length=1, max_length=200)
    descricao: Optional[str] = None
    tipo: Literal["produto", "servico", "kit"]
    categoria: Optional[str] = None
    marca: Optional[str] = None
    preco_venda: Decimal = Field(..., ge=0)
    preco_custo: Optional[Decimal] = Field(None, ge=0)
    codigo_barras: Optional[str] = None
    ncm: Optional[str] = None
    unidade: str = "UN"
    estoque_minimo: Decimal = Decimal("0")

    @field_validator("preco_venda", "preco_custo", "estoque_minimo", mode="before")
    @classmethod
    def convert_to_decimal(cls, v):
        if v is None:
            return v
        return Decimal(str(v))


class ProductCreate(ProductBase):
    """Dados para criar produto."""
    pass


class ProductUpdate(BaseModel):
    """Dados para atualizar produto (todos opcionais)."""
    sku: Optional[str] = Field(None, min_length=1, max_length=50)
    nome: Optional[str] = Field(None, min_length=1, max_length=200)
    descricao: Optional[str] = None
    tipo: Optional[Literal["produto", "servico", "kit"]] = None
    categoria: Optional[str] = None
    marca: Optional[str] = None
    preco_venda: Optional[Decimal] = Field(None, ge=0)
    preco_custo: Optional[Decimal] = Field(None, ge=0)
    codigo_barras: Optional[str] = None
    ncm: Optional[str] = None
    unidade: Optional[str] = None
    estoque_minimo: Optional[Decimal] = None
    ativo: Optional[bool] = None


class ProductResponse(ProductBase):
    """Resposta com dados do produto."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    ativo: bool = True
    created_at: datetime
    updated_at: Optional[datetime] = None


# ==============================================================================
# ORDER MODELS
# ==============================================================================

class OrderItem(BaseModel):
    """Item de um pedido."""
    model_config = ConfigDict(
        json_schema_extra={"properties": {"subtotal": {"type": "number"}}}
    )

    product_id: int
    sku: str
    nome: str
    quantidade: int = Field(..., ge=1)
    preco_unitario: Decimal = Field(..., ge=0)
    desconto: Decimal = Decimal("0")

    @property
    def subtotal(self) -> Decimal:
        """Calcula subtotal: (quantidade * preco) - desconto."""
        return (self.quantidade * self.preco_unitario) - self.desconto

    @field_validator("preco_unitario", "desconto", mode="before")
    @classmethod
    def convert_to_decimal(cls, v):
        if v is None:
            return Decimal("0")
        return Decimal(str(v))


class OrderBase(BaseModel):
    """Campos comuns de Pedido."""
    tenant_id: str
    customer_id: Optional[int] = None
    tipo: Literal["venda", "os"]
    items: List[OrderItem] = []
    observacoes: Optional[str] = None


class OrderCreate(OrderBase):
    """Dados para criar pedido."""
    pass


class OrderUpdate(BaseModel):
    """Dados para atualizar pedido."""
    status: Optional[Literal["aberto", "fechado", "cancelado"]] = None
    items: Optional[List[OrderItem]] = None
    desconto: Optional[Decimal] = None
    valor_pago: Optional[Decimal] = None
    forma_pagamento: Optional[str] = None
    observacoes: Optional[str] = None


class OrderResponse(OrderBase):
    """Resposta com dados do pedido."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: Literal["aberto", "fechado", "cancelado"] = "aberto"
    subtotal: Decimal = Decimal("0")
    desconto: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    valor_pago: Decimal = Decimal("0")
    forma_pagamento: Optional[str] = None
    fechado_em: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
