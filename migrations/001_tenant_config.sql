-- migrations/001_tenant_config.sql
-- Criação da tabela tenant_config para multi-tenancy
-- Migra configurações hardcoded da Aluga Ar para o banco

-- ==============================================================================
-- TABELA tenant_config
-- ==============================================================================

CREATE TABLE IF NOT EXISTS tenant_config (
    -- Identificador único do tenant
    tenant_id TEXT PRIMARY KEY,

    -- Nome do tenant (para exibição)
    name TEXT NOT NULL,

    -- Credenciais UAZAPI (WhatsApp)
    uazapi_instance TEXT NOT NULL,
    uazapi_token TEXT NOT NULL,

    -- Credenciais Asaas (Pagamentos)
    asaas_api_key TEXT,
    asaas_api_url TEXT DEFAULT 'https://api.asaas.com/v3',

    -- Filas Leadbox padrão
    default_queue_ia INTEGER NOT NULL DEFAULT 537,
    default_queue_billing INTEGER NOT NULL DEFAULT 544,
    default_queue_maintenance INTEGER NOT NULL DEFAULT 545,
    default_queue_financeiro INTEGER NOT NULL DEFAULT 454,
    default_queue_atendimento INTEGER NOT NULL DEFAULT 453,

    -- Leadbox tenant_id (para filtro de webhooks)
    leadbox_tenant_id INTEGER,

    -- Configuração de billing
    billing_schedule TEXT DEFAULT '0 9 * * 1-5',
    billing_days TEXT[] DEFAULT ARRAY['monday', 'tuesday', 'wednesday', 'thursday', 'friday'],

    -- Prompts dos agentes (referência a arquivos .md ou conteúdo direto)
    agent_prompt_sdr TEXT,
    agent_prompt_billing TEXT,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ==============================================================================
-- ÍNDICES
-- ==============================================================================

CREATE INDEX IF NOT EXISTS idx_tenant_config_leadbox_tenant
    ON tenant_config(leadbox_tenant_id);

-- ==============================================================================
-- TRIGGER para updated_at
-- ==============================================================================

CREATE OR REPLACE FUNCTION update_tenant_config_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_tenant_config_updated_at ON tenant_config;
CREATE TRIGGER trigger_tenant_config_updated_at
    BEFORE UPDATE ON tenant_config
    FOR EACH ROW
    EXECUTE FUNCTION update_tenant_config_updated_at();

-- ==============================================================================
-- INSERT INICIAL: Aluga Ar (valores atuais hardcoded)
-- ==============================================================================

INSERT INTO tenant_config (
    tenant_id,
    name,
    uazapi_instance,
    uazapi_token,
    asaas_api_key,
    asaas_api_url,
    default_queue_ia,
    default_queue_billing,
    default_queue_maintenance,
    default_queue_financeiro,
    default_queue_atendimento,
    leadbox_tenant_id,
    billing_schedule,
    billing_days,
    agent_prompt_sdr,
    agent_prompt_billing
) VALUES (
    'aluga_ar',
    'Aluga Ar',
    -- UAZAPI: valores serão lidos do .env na primeira execução
    -- Aqui usamos placeholders que devem ser atualizados manualmente
    '${UAZAPI_BASE_URL}',
    '${UAZAPI_API_KEY}',
    -- Asaas: valores serão lidos do .env na primeira execução
    '${ASAAS_API_KEY}',
    'https://api.asaas.com/v3',
    -- Filas Leadbox (valores reais mapeados do código)
    537,   -- queue_ia (fila genérica/IA)
    544,   -- queue_billing (cobrança)
    545,   -- queue_maintenance (manutenção)
    454,   -- queue_financeiro (Tieli)
    453,   -- queue_atendimento (Nathália)
    -- Leadbox tenant_id
    123,
    -- Billing schedule (seg-sex às 9h)
    '0 9 * * 1-5',
    ARRAY['monday', 'tuesday', 'wednesday', 'thursday', 'friday'],
    -- Prompts (referência a arquivos)
    NULL,
    NULL
) ON CONFLICT (tenant_id) DO NOTHING;

-- ==============================================================================
-- COMENTÁRIOS
-- ==============================================================================

COMMENT ON TABLE tenant_config IS 'Configurações específicas por tenant para multi-tenancy';
COMMENT ON COLUMN tenant_config.tenant_id IS 'Identificador único do tenant (slug)';
COMMENT ON COLUMN tenant_config.leadbox_tenant_id IS 'ID do tenant no Leadbox (usado para filtrar webhooks)';
COMMENT ON COLUMN tenant_config.default_queue_ia IS 'Fila padrão onde a IA atende (537 = genérica)';
COMMENT ON COLUMN tenant_config.default_queue_billing IS 'Fila para leads em processo de cobrança (544)';
COMMENT ON COLUMN tenant_config.default_queue_maintenance IS 'Fila para leads em manutenção preventiva (545)';
COMMENT ON COLUMN tenant_config.default_queue_financeiro IS 'Fila do financeiro humano - Tieli (454)';
COMMENT ON COLUMN tenant_config.default_queue_atendimento IS 'Fila de atendimento humano - Nathália (453)';
