-- migrations/003_erp_orders.sql
-- Tabela de Vendas e Ordens de Serviço
-- Complementa o schema ERP base (002_erp_base_schema.sql)

-- ==============================================================================
-- TABELA erp_orders — Vendas e Ordens de Serviço
-- ==============================================================================

CREATE TABLE IF NOT EXISTS erp_orders (
    id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenant_config(tenant_id),
    customer_id BIGINT REFERENCES erp_customers(id),

    -- Tipo: venda ou ordem de serviço
    tipo TEXT NOT NULL DEFAULT 'venda' CHECK (tipo IN ('venda', 'os')),

    -- Status
    status TEXT NOT NULL DEFAULT 'aberto' CHECK (status IN ('aberto', 'fechado', 'cancelado')),

    -- Items (JSONB array)
    -- Cada item: {product_id, sku, nome, quantidade, preco_unitario, desconto, subtotal}
    items JSONB NOT NULL DEFAULT '[]',

    -- Valores
    subtotal DECIMAL(15,2) NOT NULL DEFAULT 0,
    desconto DECIMAL(15,2) DEFAULT 0,
    total DECIMAL(15,2) NOT NULL DEFAULT 0,
    valor_pago DECIMAL(15,2) DEFAULT 0,

    -- Pagamento
    forma_pagamento TEXT,  -- dinheiro, pix, cartao_credito, cartao_debito, boleto

    -- Observações
    observacoes TEXT,

    -- Data de fechamento
    fechado_em TIMESTAMPTZ,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Índices
CREATE INDEX IF NOT EXISTS idx_erp_orders_tenant ON erp_orders(tenant_id);
CREATE INDEX IF NOT EXISTS idx_erp_orders_customer ON erp_orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_erp_orders_tipo ON erp_orders(tenant_id, tipo);
CREATE INDEX IF NOT EXISTS idx_erp_orders_status ON erp_orders(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_erp_orders_created ON erp_orders(tenant_id, created_at DESC);

-- ==============================================================================
-- TRIGGER para updated_at
-- ==============================================================================

DROP TRIGGER IF EXISTS trigger_erp_orders_updated_at ON erp_orders;
CREATE TRIGGER trigger_erp_orders_updated_at
    BEFORE UPDATE ON erp_orders
    FOR EACH ROW EXECUTE FUNCTION update_erp_updated_at();

-- ==============================================================================
-- RLS (Row Level Security)
-- ==============================================================================

ALTER TABLE erp_orders ENABLE ROW LEVEL SECURITY;

CREATE POLICY erp_orders_service_policy ON erp_orders
    FOR ALL TO service_role USING (true) WITH CHECK (true);

-- ==============================================================================
-- COMENTÁRIOS
-- ==============================================================================

COMMENT ON TABLE erp_orders IS 'Vendas e Ordens de Serviço do ERP multi-tenant';
COMMENT ON COLUMN erp_orders.tipo IS 'venda = venda direta, os = ordem de serviço';
COMMENT ON COLUMN erp_orders.status IS 'aberto = em andamento, fechado = concluído, cancelado = cancelado';
COMMENT ON COLUMN erp_orders.items IS 'Array JSON com itens do pedido';
COMMENT ON COLUMN erp_orders.fechado_em IS 'Data/hora em que o pedido foi fechado';
