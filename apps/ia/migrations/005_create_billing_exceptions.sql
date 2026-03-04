-- Migration: 005_create_billing_exceptions.sql
-- Description: Cria tabela de excecoes de cobranca (opt-out, pausas, excecoes manuais)
-- Date: 2026-03-03
-- Bug Fix #6: Permite opt-out e pausas de cobranca

-- ============================================================================
-- TABELA: billing_exceptions
-- ============================================================================

CREATE TABLE IF NOT EXISTS billing_exceptions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,

    -- Referencia ao agente
    agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,

    -- Identificadores do alvo da excecao (pelo menos um deve ser preenchido)
    remotejid TEXT,                    -- WhatsApp ID do cliente
    payment_id TEXT,                   -- ID do pagamento especifico

    -- Detalhes da excecao
    reason TEXT NOT NULL,              -- Motivo: 'opt_out', 'pause', 'manual', 'dispute', etc
    note TEXT,                         -- Observacao livre

    -- Status
    active BOOLEAN DEFAULT TRUE,       -- Se a excecao esta ativa
    expires_at TIMESTAMPTZ,            -- Data de expiracao (NULL = permanente)

    -- Auditoria
    created_by TEXT,                   -- Quem criou (email, sistema, etc)
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Constraint: pelo menos um identificador deve ser preenchido
    CONSTRAINT chk_has_identifier CHECK (remotejid IS NOT NULL OR payment_id IS NOT NULL)
);

-- ============================================================================
-- INDICES
-- ============================================================================

-- Indice para buscar excecoes ativas por agente
CREATE INDEX IF NOT EXISTS idx_billing_exceptions_active
    ON billing_exceptions(agent_id, active)
    WHERE active = TRUE;

-- Indice para buscar por remotejid
CREATE INDEX IF NOT EXISTS idx_billing_exceptions_remotejid
    ON billing_exceptions(agent_id, remotejid)
    WHERE active = TRUE AND remotejid IS NOT NULL;

-- Indice para buscar por payment_id
CREATE INDEX IF NOT EXISTS idx_billing_exceptions_payment
    ON billing_exceptions(agent_id, payment_id)
    WHERE active = TRUE AND payment_id IS NOT NULL;

-- Indice para limpeza de excecoes expiradas
CREATE INDEX IF NOT EXISTS idx_billing_exceptions_expires
    ON billing_exceptions(expires_at)
    WHERE active = TRUE AND expires_at IS NOT NULL;

-- ============================================================================
-- TRIGGER: Atualizar updated_at automaticamente
-- ============================================================================

CREATE OR REPLACE FUNCTION update_billing_exceptions_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_billing_exceptions_updated_at ON billing_exceptions;

CREATE TRIGGER trg_billing_exceptions_updated_at
    BEFORE UPDATE ON billing_exceptions
    FOR EACH ROW
    EXECUTE FUNCTION update_billing_exceptions_updated_at();

-- ============================================================================
-- RLS (Row Level Security)
-- ============================================================================

ALTER TABLE billing_exceptions ENABLE ROW LEVEL SECURITY;

-- Policy: Agentes so veem suas proprias excecoes
CREATE POLICY billing_exceptions_agent_policy ON billing_exceptions
    FOR ALL
    USING (agent_id = current_setting('app.current_agent_id', true)::uuid)
    WITH CHECK (agent_id = current_setting('app.current_agent_id', true)::uuid);

-- Policy: Service role tem acesso total
CREATE POLICY billing_exceptions_service_policy ON billing_exceptions
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- ============================================================================
-- COMENTARIOS
-- ============================================================================

COMMENT ON TABLE billing_exceptions IS 'Excecoes de cobranca: opt-out, pausas, disputas';
COMMENT ON COLUMN billing_exceptions.remotejid IS 'WhatsApp ID do cliente (formato: 5511999999999@s.whatsapp.net)';
COMMENT ON COLUMN billing_exceptions.payment_id IS 'ID do pagamento Asaas (para excecao especifica)';
COMMENT ON COLUMN billing_exceptions.reason IS 'Motivo: opt_out, pause, manual, dispute, death, bankrupt';
COMMENT ON COLUMN billing_exceptions.expires_at IS 'Data de expiracao (NULL = permanente)';
