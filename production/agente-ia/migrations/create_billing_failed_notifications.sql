-- Migration: Dead Letter Queue for failed billing notifications
-- Armazena notificações que falharam após todas as tentativas
-- Permite reprocessamento manual ou automático posterior

CREATE TABLE IF NOT EXISTS billing_failed_notifications (
  id BIGSERIAL PRIMARY KEY,
  agent_id TEXT NOT NULL,
  payment_id TEXT NOT NULL,
  customer_id TEXT,
  customer_name TEXT,
  phone TEXT NOT NULL,
  message_text TEXT NOT NULL,
  notification_type TEXT NOT NULL, -- reminder, due_date, overdue
  dispatch_method TEXT, -- leadbox_push, uazapi
  
  -- Detalhes do erro
  error_message TEXT NOT NULL,
  error_code TEXT,
  failure_reason TEXT, -- timeout, api_error, network_error, rate_limit, etc
  
  -- Tentativas
  attempts_count INTEGER DEFAULT 1,
  last_attempt_at TIMESTAMPTZ DEFAULT NOW(),
  
  -- Status de reprocessamento
  status TEXT DEFAULT 'pending', -- pending, retrying, success, abandoned
  reprocessed_at TIMESTAMPTZ,
  
  -- Metadados
  scheduled_date TEXT NOT NULL,
  days_from_due INTEGER,
  payment_value NUMERIC,
  due_date TEXT,
  
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Índices para performance
CREATE INDEX IF NOT EXISTS idx_billing_failed_agent_status 
  ON billing_failed_notifications(agent_id, status);

CREATE INDEX IF NOT EXISTS idx_billing_failed_payment 
  ON billing_failed_notifications(payment_id);

CREATE INDEX IF NOT EXISTS idx_billing_failed_created 
  ON billing_failed_notifications(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_billing_failed_phone 
  ON billing_failed_notifications(phone);

COMMENT ON TABLE billing_failed_notifications IS 
'Dead Letter Queue - Notificações de cobrança que falharam após tentativas. Permite reprocessamento.';

COMMENT ON COLUMN billing_failed_notifications.failure_reason IS 
'Classificação do erro: timeout, api_error, network_error, rate_limit, invalid_phone, etc.';

COMMENT ON COLUMN billing_failed_notifications.status IS 
'pending: aguardando reprocessamento | retrying: em tentativa | success: recuperado | abandoned: desistido';
