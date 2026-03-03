-- Migration: Add billing_context column to lead tables
-- Date: 2026-03-02
-- Purpose: Store billing context data directly on lead to avoid repeated queries

-- ============================================================================
-- DESCRIPTION
-- ============================================================================
-- This column stores billing-related context when a lead receives a billing
-- notification. This allows the AI to have immediate access to customer data
-- without needing to query billing_notifications every time.
--
-- Structure:
-- {
--   "customer_id": "cus_xxx",           -- Asaas customer ID
--   "customer_name": "Nome do Cliente", -- Customer name
--   "last_billing_at": "2026-03-02",    -- Last billing dispatch date
--   "pending_amount": 150.00,           -- Total pending amount
--   "has_overdue": true,                -- Has overdue payments
--   "last_payment_id": "pay_xxx"        -- Last payment ID sent
-- }
-- ============================================================================

-- ============================================================================
-- AUTOMATED MIGRATION (run this to migrate ALL lead tables at once)
-- ============================================================================

DO $$
DECLARE
    tbl_name TEXT;
BEGIN
    FOR tbl_name IN
        SELECT agents.table_leads
        FROM agents
        WHERE table_leads IS NOT NULL AND table_leads != ''
    LOOP
        -- Add billing_context JSONB column
        EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS billing_context JSONB', tbl_name);

        -- Add index for customer_id inside JSONB (for quick lookups)
        BEGIN
            EXECUTE format(
                'CREATE INDEX IF NOT EXISTS %I ON %I ((billing_context->>''customer_id'')) WHERE billing_context IS NOT NULL',
                tbl_name || '_billing_ctx_customer_idx', tbl_name
            );
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'Index billing_context customer_id already exists for %', tbl_name;
        END;

        -- Add index for has_overdue flag (for dashboard queries)
        BEGIN
            EXECUTE format(
                'CREATE INDEX IF NOT EXISTS %I ON %I ((billing_context->>''has_overdue'')) WHERE billing_context IS NOT NULL',
                tbl_name || '_billing_ctx_overdue_idx', tbl_name
            );
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'Index billing_context has_overdue already exists for %', tbl_name;
        END;

        RAISE NOTICE 'Added billing_context to table: %', tbl_name;
    END LOOP;
END $$;

-- ============================================================================
-- VERIFICATION QUERY
-- After running, verify column was added:
-- ============================================================================
/*
SELECT
    a.name as agent_name,
    a.table_leads,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = a.table_leads AND column_name = 'billing_context'
    ) as has_billing_context
FROM agents a
WHERE a.table_leads IS NOT NULL;
*/

-- ============================================================================
-- ROLLBACK (if needed)
-- ============================================================================
/*
DO $$
DECLARE
    tbl_name TEXT;
BEGIN
    FOR tbl_name IN
        SELECT agents.table_leads
        FROM agents
        WHERE table_leads IS NOT NULL AND table_leads != ''
    LOOP
        EXECUTE format('ALTER TABLE %I DROP COLUMN IF EXISTS billing_context', tbl_name);
        RAISE NOTICE 'Removed billing_context from table: %', tbl_name;
    END LOOP;
END $$;
*/
