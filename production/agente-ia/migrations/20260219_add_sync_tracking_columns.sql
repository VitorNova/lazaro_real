-- Migration: add_sync_tracking_columns.sql
-- Autor: Executor
-- Data: 2026-02-19
-- Objetivo: Adicionar colunas de rastreabilidade para sincronizacao com API Asaas

-- 1. Adicionar coluna para rastrear ultima sincronizacao com API Asaas
ALTER TABLE asaas_cobrancas
ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMPTZ;

-- 2. Adicionar coluna para indicar origem do dado
-- Valores possiveis:
--   'webhook'         = veio de webhook Asaas (atualizacao automatica)
--   'api_sync'        = veio de sincronizacao via API (job de cobranca)
--   'reconciliation'  = veio do job de reconciliacao diaria
--   'fallback'        = veio do cache (API Asaas indisponivel)
ALTER TABLE asaas_cobrancas
ADD COLUMN IF NOT EXISTS sync_source TEXT DEFAULT 'webhook';

-- 3. Adicionar colunas similares para asaas_clientes
ALTER TABLE asaas_clientes
ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMPTZ;

ALTER TABLE asaas_clientes
ADD COLUMN IF NOT EXISTS sync_source TEXT DEFAULT 'webhook';

-- 4. Indices para otimizar queries de reconciliacao
CREATE INDEX IF NOT EXISTS idx_asaas_cobrancas_last_synced
ON asaas_cobrancas(agent_id, last_synced_at);

CREATE INDEX IF NOT EXISTS idx_asaas_cobrancas_sync_source
ON asaas_cobrancas(agent_id, sync_source);

CREATE INDEX IF NOT EXISTS idx_asaas_clientes_last_synced
ON asaas_clientes(agent_id, last_synced_at);

-- 5. Comentarios explicativos
COMMENT ON COLUMN asaas_cobrancas.last_synced_at IS
'Ultima vez que o registro foi sincronizado com API Asaas. NULL = nunca sincronizado pela API.';

COMMENT ON COLUMN asaas_cobrancas.sync_source IS
'Origem do dado: webhook (automatico), api_sync (job cobranca), reconciliation (job diario), fallback (cache quando API falha).';

COMMENT ON COLUMN asaas_clientes.last_synced_at IS
'Ultima vez que o registro foi sincronizado com API Asaas. NULL = nunca sincronizado pela API.';

COMMENT ON COLUMN asaas_clientes.sync_source IS
'Origem do dado: webhook (automatico), api_sync (busca API), reconciliation (job diario), fallback (cache quando API falha).';

-- 6. Verificar se as colunas foram criadas com sucesso
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'asaas_cobrancas'
        AND column_name = 'last_synced_at'
    ) THEN
        RAISE NOTICE 'Migration concluida: Colunas de tracking adicionadas com sucesso.';
    ELSE
        RAISE EXCEPTION 'Falha na migration: Coluna last_synced_at nao foi criada.';
    END IF;
END $$;
