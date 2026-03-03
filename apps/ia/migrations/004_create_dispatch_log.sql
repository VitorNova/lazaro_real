-- Migration: Create unified dispatch_log table
-- Consolidates logging for all notification jobs (billing, maintenance, calendar, follow_up)

CREATE TABLE IF NOT EXISTS dispatch_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  -- Job identification
  job_type TEXT NOT NULL,           -- 'billing', 'maintenance', 'follow_up', 'calendar'
  agent_id UUID NOT NULL,

  -- Reference (related record ID)
  reference_id TEXT NOT NULL,       -- payment_id, contract_id, lead_id, event_id
  reference_table TEXT,             -- 'asaas_cobrancas', 'contract_details', etc.

  -- Recipient data
  customer_id TEXT,
  customer_name TEXT,
  phone TEXT NOT NULL,

  -- Notification type
  notification_type TEXT NOT NULL,  -- 'reminder', 'due_date', 'overdue', 'reminder_7d', etc.
  days_from_due INTEGER,            -- D-7, D-2, D0, D+1, etc.

  -- Content
  message_text TEXT,

  -- Job-specific data (flexible)
  metadata JSONB DEFAULT '{}',      -- valor, due_date, maintenance_type, etc.

  -- Dispatch method
  dispatch_method TEXT DEFAULT 'whatsapp',  -- 'whatsapp', 'sms', 'email'

  -- Status and result
  status TEXT NOT NULL DEFAULT 'pending',   -- 'pending', 'sent', 'failed', 'skipped'
  error_message TEXT,
  failure_reason TEXT,              -- 'timeout', 'rate_limit', 'invalid_phone', etc.

  -- Retry control
  attempts_count INTEGER DEFAULT 0,
  last_attempt_at TIMESTAMPTZ,

  -- Timestamps
  scheduled_date DATE,              -- date for deduplication (extracted from scheduled_at)
  scheduled_at TIMESTAMPTZ,         -- when it was scheduled
  sent_at TIMESTAMPTZ,              -- when it was sent
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_dispatch_log_job_type ON dispatch_log(job_type);
CREATE INDEX IF NOT EXISTS idx_dispatch_log_agent_id ON dispatch_log(agent_id);
CREATE INDEX IF NOT EXISTS idx_dispatch_log_status ON dispatch_log(status);
CREATE INDEX IF NOT EXISTS idx_dispatch_log_created_at ON dispatch_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_dispatch_log_phone ON dispatch_log(phone);
CREATE INDEX IF NOT EXISTS idx_dispatch_log_reference ON dispatch_log(reference_id);

-- Composite unique index to prevent duplicates
-- Only applies to non-failed records (allows retry of failed ones)
CREATE UNIQUE INDEX IF NOT EXISTS idx_dispatch_log_unique_dispatch
  ON dispatch_log(agent_id, job_type, reference_id, notification_type, scheduled_date)
  WHERE status != 'failed';

-- Comment for documentation
COMMENT ON TABLE dispatch_log IS 'Unified log table for all notification dispatches (billing, maintenance, calendar, follow_up)';
COMMENT ON COLUMN dispatch_log.job_type IS 'Type of job: billing, maintenance, follow_up, calendar';
COMMENT ON COLUMN dispatch_log.reference_id IS 'ID of related record (payment_id, contract_id, lead_id, event_id)';
COMMENT ON COLUMN dispatch_log.reference_table IS 'Source table name (asaas_cobrancas, contract_details, etc)';
COMMENT ON COLUMN dispatch_log.days_from_due IS 'Days relative to due date: negative = before, positive = after (D-7, D-2, D0, D+1)';
COMMENT ON COLUMN dispatch_log.metadata IS 'Job-specific data in JSON format (valor, due_date, maintenance_type, etc)';
COMMENT ON COLUMN dispatch_log.failure_reason IS 'Classified failure reason: timeout, rate_limit, invalid_phone, auth_error, network_error, api_error';
