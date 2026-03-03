-- Migration: Add conversion tracking columns to lead tables
-- Date: 2026-03-02
-- Purpose: Enable Lead → Customer Asaas conversion tracking via CPF

-- ============================================================================
-- IMPORTANT: This migration must be run for EACH agent's lead table
-- Replace ${TABLE_NAME} with the actual table name (e.g., LeadboxCRM_xxxxxxxx)
-- ============================================================================

-- To find all lead tables, run:
-- SELECT table_leads FROM agents WHERE table_leads IS NOT NULL;

-- ============================================================================
-- MIGRATION TEMPLATE - Copy and replace ${TABLE_NAME} for each table
-- ============================================================================

/*
-- Add conversion tracking columns
ALTER TABLE "${TABLE_NAME}" ADD COLUMN IF NOT EXISTS converted_at TIMESTAMPTZ;
ALTER TABLE "${TABLE_NAME}" ADD COLUMN IF NOT EXISTS first_payment_at TIMESTAMPTZ;
ALTER TABLE "${TABLE_NAME}" ADD COLUMN IF NOT EXISTS interest_type TEXT;

-- Add indexes for efficient queries
CREATE INDEX IF NOT EXISTS "${TABLE_NAME}_cpf_cnpj_idx" ON "${TABLE_NAME}" (cpf_cnpj) WHERE cpf_cnpj IS NOT NULL;
CREATE INDEX IF NOT EXISTS "${TABLE_NAME}_converted_at_idx" ON "${TABLE_NAME}" (converted_at) WHERE converted_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS "${TABLE_NAME}_interest_type_idx" ON "${TABLE_NAME}" (interest_type) WHERE interest_type IS NOT NULL;
*/

-- ============================================================================
-- AUTOMATED MIGRATION (run this to migrate ALL lead tables at once)
-- ============================================================================

DO $$
DECLARE
    table_name TEXT;
BEGIN
    FOR table_name IN
        SELECT agents.table_leads
        FROM agents
        WHERE table_leads IS NOT NULL AND table_leads != ''
    LOOP
        -- Add converted_at column
        EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS converted_at TIMESTAMPTZ', table_name);

        -- Add first_payment_at column
        EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS first_payment_at TIMESTAMPTZ', table_name);

        -- Add interest_type column
        EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS interest_type TEXT', table_name);

        -- Add CPF index (if not exists)
        BEGIN
            EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON %I (cpf_cnpj) WHERE cpf_cnpj IS NOT NULL',
                table_name || '_cpf_cnpj_idx', table_name);
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'Index cpf_cnpj already exists for %', table_name;
        END;

        -- Add converted_at index
        BEGIN
            EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON %I (converted_at) WHERE converted_at IS NOT NULL',
                table_name || '_converted_at_idx', table_name);
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'Index converted_at already exists for %', table_name;
        END;

        -- Add interest_type index
        BEGIN
            EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON %I (interest_type) WHERE interest_type IS NOT NULL',
                table_name || '_interest_type_idx', table_name);
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'Index interest_type already exists for %', table_name;
        END;

        RAISE NOTICE 'Migrated table: %', table_name;
    END LOOP;
END $$;

-- ============================================================================
-- VERIFICATION QUERY
-- After running, verify columns were added:
-- ============================================================================
/*
SELECT
    a.name as agent_name,
    a.table_leads,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = a.table_leads AND column_name = 'converted_at'
    ) as has_converted_at,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = a.table_leads AND column_name = 'first_payment_at'
    ) as has_first_payment_at,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = a.table_leads AND column_name = 'interest_type'
    ) as has_interest_type
FROM agents a
WHERE a.table_leads IS NOT NULL;
*/
