-- migrations/002_erp_base_schema.sql
-- Schema base do ERP multi-tenant
-- Tabelas: customers, products, inventory, financial

-- ==============================================================================
-- TABELA erp_customers — Clientes e Fornecedores
-- ==============================================================================

CREATE TABLE IF NOT EXISTS erp_customers (
    id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenant_config(tenant_id),

    -- Tipo: cliente ou fornecedor
    tipo TEXT NOT NULL CHECK (tipo IN ('cliente', 'fornecedor', 'ambos')),

    -- Dados básicos
    nome TEXT NOT NULL,
    nome_fantasia TEXT,
    cpf_cnpj TEXT,  -- CPF (11 dígitos) ou CNPJ (14 dígitos)
    ie TEXT,        -- Inscrição Estadual
    im TEXT,        -- Inscrição Municipal

    -- Contato
    email TEXT,
    telefone TEXT,
    celular TEXT,

    -- Endereço
    cep TEXT,
    logradouro TEXT,
    numero TEXT,
    complemento TEXT,
    bairro TEXT,
    cidade TEXT,
    uf TEXT,

    -- Observações
    observacoes TEXT,

    -- Status
    ativo BOOLEAN DEFAULT TRUE,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Índices
CREATE INDEX IF NOT EXISTS idx_erp_customers_tenant ON erp_customers(tenant_id);
CREATE INDEX IF NOT EXISTS idx_erp_customers_cpf_cnpj ON erp_customers(tenant_id, cpf_cnpj);
CREATE INDEX IF NOT EXISTS idx_erp_customers_nome ON erp_customers(tenant_id, nome);
CREATE INDEX IF NOT EXISTS idx_erp_customers_tipo ON erp_customers(tenant_id, tipo);

-- ==============================================================================
-- TABELA erp_products — Produtos e Serviços
-- ==============================================================================

CREATE TABLE IF NOT EXISTS erp_products (
    id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenant_config(tenant_id),

    -- Identificação
    sku TEXT NOT NULL,  -- Código interno único por tenant
    codigo_barras TEXT, -- EAN/GTIN

    -- Descrição
    nome TEXT NOT NULL,
    descricao TEXT,

    -- Classificação
    tipo TEXT NOT NULL DEFAULT 'produto' CHECK (tipo IN ('produto', 'servico', 'kit')),
    categoria TEXT,
    marca TEXT,

    -- Preços
    preco_venda DECIMAL(15,2) NOT NULL DEFAULT 0,
    preco_custo DECIMAL(15,2) DEFAULT 0,
    margem_lucro DECIMAL(5,2),  -- Percentual

    -- Fiscal
    ncm TEXT,           -- Nomenclatura Comum do Mercosul
    cest TEXT,          -- Código Especificador da Substituição Tributária
    origem TEXT,        -- 0=Nacional, 1=Estrangeira importação direta, etc

    -- Unidade
    unidade TEXT DEFAULT 'UN',  -- UN, KG, LT, M, M2, M3, etc

    -- Estoque mínimo
    estoque_minimo DECIMAL(15,3) DEFAULT 0,

    -- Status
    ativo BOOLEAN DEFAULT TRUE,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- SKU único por tenant
    UNIQUE(tenant_id, sku)
);

-- Índices
CREATE INDEX IF NOT EXISTS idx_erp_products_tenant ON erp_products(tenant_id);
CREATE INDEX IF NOT EXISTS idx_erp_products_sku ON erp_products(tenant_id, sku);
CREATE INDEX IF NOT EXISTS idx_erp_products_nome ON erp_products(tenant_id, nome);
CREATE INDEX IF NOT EXISTS idx_erp_products_categoria ON erp_products(tenant_id, categoria);
CREATE INDEX IF NOT EXISTS idx_erp_products_codigo_barras ON erp_products(codigo_barras);

-- ==============================================================================
-- TABELA erp_inventory — Estoque
-- ==============================================================================

CREATE TABLE IF NOT EXISTS erp_inventory (
    id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenant_config(tenant_id),
    product_id BIGINT NOT NULL REFERENCES erp_products(id) ON DELETE CASCADE,

    -- Localização
    deposito TEXT NOT NULL DEFAULT 'principal',
    localizacao TEXT,  -- Corredor/Prateleira/Posição

    -- Quantidades
    quantidade DECIMAL(15,3) NOT NULL DEFAULT 0,
    reservado DECIMAL(15,3) DEFAULT 0,  -- Quantidade reservada para pedidos

    -- Custo
    custo_medio DECIMAL(15,4) DEFAULT 0,
    custo_ultimo DECIMAL(15,4) DEFAULT 0,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Um registro por produto/depósito
    UNIQUE(tenant_id, product_id, deposito)
);

-- Índices
CREATE INDEX IF NOT EXISTS idx_erp_inventory_tenant ON erp_inventory(tenant_id);
CREATE INDEX IF NOT EXISTS idx_erp_inventory_product ON erp_inventory(product_id);
CREATE INDEX IF NOT EXISTS idx_erp_inventory_deposito ON erp_inventory(tenant_id, deposito);

-- ==============================================================================
-- TABELA erp_financial — Contas a Pagar e Receber
-- ==============================================================================

CREATE TABLE IF NOT EXISTS erp_financial (
    id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenant_config(tenant_id),

    -- Tipo
    tipo TEXT NOT NULL CHECK (tipo IN ('pagar', 'receber')),

    -- Vínculo
    customer_id BIGINT REFERENCES erp_customers(id),
    descricao TEXT NOT NULL,

    -- Valores
    valor DECIMAL(15,2) NOT NULL,
    valor_pago DECIMAL(15,2) DEFAULT 0,
    desconto DECIMAL(15,2) DEFAULT 0,
    juros DECIMAL(15,2) DEFAULT 0,
    multa DECIMAL(15,2) DEFAULT 0,

    -- Datas
    data_emissao DATE DEFAULT CURRENT_DATE,
    data_vencimento DATE NOT NULL,
    data_pagamento DATE,

    -- Categorização
    categoria TEXT,
    centro_custo TEXT,

    -- Status
    status TEXT NOT NULL DEFAULT 'pendente'
        CHECK (status IN ('pendente', 'pago', 'parcial', 'cancelado', 'atrasado')),

    -- Forma de pagamento
    forma_pagamento TEXT,  -- dinheiro, pix, cartao_credito, cartao_debito, boleto, transferencia

    -- Recorrência
    recorrente BOOLEAN DEFAULT FALSE,
    frequencia TEXT,  -- mensal, semanal, anual
    parcela_atual INTEGER,
    total_parcelas INTEGER,

    -- Integração externa
    external_id TEXT,  -- ID no Asaas, banco, etc
    external_source TEXT,  -- asaas, banco_x, manual

    -- Observações
    observacoes TEXT,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Índices
CREATE INDEX IF NOT EXISTS idx_erp_financial_tenant ON erp_financial(tenant_id);
CREATE INDEX IF NOT EXISTS idx_erp_financial_tipo ON erp_financial(tenant_id, tipo);
CREATE INDEX IF NOT EXISTS idx_erp_financial_status ON erp_financial(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_erp_financial_vencimento ON erp_financial(tenant_id, data_vencimento);
CREATE INDEX IF NOT EXISTS idx_erp_financial_customer ON erp_financial(customer_id);
CREATE INDEX IF NOT EXISTS idx_erp_financial_external ON erp_financial(tenant_id, external_source, external_id);

-- ==============================================================================
-- TRIGGERS para updated_at
-- ==============================================================================

CREATE OR REPLACE FUNCTION update_erp_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Customers
DROP TRIGGER IF EXISTS trigger_erp_customers_updated_at ON erp_customers;
CREATE TRIGGER trigger_erp_customers_updated_at
    BEFORE UPDATE ON erp_customers
    FOR EACH ROW EXECUTE FUNCTION update_erp_updated_at();

-- Products
DROP TRIGGER IF EXISTS trigger_erp_products_updated_at ON erp_products;
CREATE TRIGGER trigger_erp_products_updated_at
    BEFORE UPDATE ON erp_products
    FOR EACH ROW EXECUTE FUNCTION update_erp_updated_at();

-- Inventory
DROP TRIGGER IF EXISTS trigger_erp_inventory_updated_at ON erp_inventory;
CREATE TRIGGER trigger_erp_inventory_updated_at
    BEFORE UPDATE ON erp_inventory
    FOR EACH ROW EXECUTE FUNCTION update_erp_updated_at();

-- Financial
DROP TRIGGER IF EXISTS trigger_erp_financial_updated_at ON erp_financial;
CREATE TRIGGER trigger_erp_financial_updated_at
    BEFORE UPDATE ON erp_financial
    FOR EACH ROW EXECUTE FUNCTION update_erp_updated_at();

-- ==============================================================================
-- RLS (Row Level Security) — Isolamento por tenant
-- ==============================================================================

-- Habilitar RLS
ALTER TABLE erp_customers ENABLE ROW LEVEL SECURITY;
ALTER TABLE erp_products ENABLE ROW LEVEL SECURITY;
ALTER TABLE erp_inventory ENABLE ROW LEVEL SECURITY;
ALTER TABLE erp_financial ENABLE ROW LEVEL SECURITY;

-- Policies para service_role (bypass)
CREATE POLICY erp_customers_service_policy ON erp_customers
    FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY erp_products_service_policy ON erp_products
    FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY erp_inventory_service_policy ON erp_inventory
    FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY erp_financial_service_policy ON erp_financial
    FOR ALL TO service_role USING (true) WITH CHECK (true);

-- ==============================================================================
-- COMENTÁRIOS
-- ==============================================================================

COMMENT ON TABLE erp_customers IS 'Clientes e fornecedores do ERP multi-tenant';
COMMENT ON TABLE erp_products IS 'Produtos e serviços do ERP multi-tenant';
COMMENT ON TABLE erp_inventory IS 'Estoque por produto e depósito';
COMMENT ON TABLE erp_financial IS 'Contas a pagar e receber';

COMMENT ON COLUMN erp_customers.tenant_id IS 'ID do tenant para isolamento';
COMMENT ON COLUMN erp_customers.tipo IS 'cliente, fornecedor ou ambos';
COMMENT ON COLUMN erp_products.ncm IS 'Nomenclatura Comum do Mercosul (fiscal)';
COMMENT ON COLUMN erp_inventory.reservado IS 'Quantidade reservada para pedidos pendentes';
COMMENT ON COLUMN erp_financial.external_id IS 'ID no sistema externo (Asaas, banco, etc)';
