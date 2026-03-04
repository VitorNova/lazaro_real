-- Migration: Atomic billing notification claim
-- Cria stored procedure para registrar notificação atomicamente
-- Previne race condition entre verificar e inserir

CREATE OR REPLACE FUNCTION claim_billing_notification(
  p_agent_id TEXT,
  p_payment_id TEXT,
  p_notification_type TEXT,
  p_scheduled_date TEXT,
  p_customer_id TEXT DEFAULT NULL,
  p_phone TEXT DEFAULT NULL,
  p_days_from_due INTEGER DEFAULT NULL
)
RETURNS TABLE(claimed BOOLEAN, notification_id BIGINT) AS $$
DECLARE
  v_notification_id BIGINT;
BEGIN
  -- Tenta inserir com ON CONFLICT DO NOTHING (atomico)
  INSERT INTO billing_notifications (
    agent_id,
    payment_id,
    notification_type,
    scheduled_date,
    customer_id,
    phone,
    days_from_due,
    status,
    created_at
  )
  VALUES (
    p_agent_id,
    p_payment_id,
    p_notification_type,
    p_scheduled_date,
    p_customer_id,
    p_phone,
    p_days_from_due,
    'pending',
    NOW()
  )
  ON CONFLICT (agent_id, payment_id, notification_type, scheduled_date) 
  DO NOTHING
  RETURNING id INTO v_notification_id;

  -- Se conseguiu inserir, retorna claimed=true
  IF v_notification_id IS NOT NULL THEN
    RETURN QUERY SELECT TRUE, v_notification_id;
  ELSE
    -- Ja existia, retorna claimed=false
    RETURN QUERY SELECT FALSE, NULL::BIGINT;
  END IF;
END;
$$ LANGUAGE plpgsql;

-- Cria constraint UNIQUE se não existir
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint 
    WHERE conname = 'billing_notifications_unique_claim'
  ) THEN
    ALTER TABLE billing_notifications
    ADD CONSTRAINT billing_notifications_unique_claim
    UNIQUE (agent_id, payment_id, notification_type, scheduled_date);
  END IF;
END $$;

COMMENT ON FUNCTION claim_billing_notification IS 
'Tenta registrar notificação atomicamente. Retorna claimed=true se conseguiu, false se já existia.';
