# Migrations do Sistema de Cobrança

## Como Aplicar as Migrations

### 1. Via Supabase MCP (Recomendado)

Se você tem o Supabase MCP configurado:

```bash
# Aplicar stored procedure atômica
cat create_claim_billing_notification.sql | supabase db execute

# Aplicar tabela de Dead Letter Queue
cat create_billing_failed_notifications.sql | supabase db execute
```

### 2. Via psql (Alternativo)

```bash
# Conectar ao banco
psql postgresql://postgres:[SUA_SENHA]@db.xxxxx.supabase.co:5432/postgres

# Executar migrations
\i create_claim_billing_notification.sql
\i create_billing_failed_notifications.sql
```

### 3. Via Supabase Dashboard

1. Acesse o Dashboard do Supabase
2. Vá em SQL Editor
3. Cole o conteúdo de cada arquivo .sql
4. Execute

---

## Migration: `create_claim_billing_notification.sql`

### O que faz
Cria uma stored procedure `claim_billing_notification()` que registra notificações de cobrança atomicamente, prevenindo duplicatas via race condition.

### Por que é necessário
**Problema:** Se duas instâncias do job rodarem simultaneamente, ambas podem verificar que a notificação não existe e ambas tentarem inserir, resultando em mensagens duplicadas para o cliente.

**Solução:** A stored procedure usa `INSERT ... ON CONFLICT DO NOTHING` com constraint UNIQUE, garantindo que apenas UMA instância consegue "clamar" a notificação.

### Como funciona
```sql
-- Tenta inserir
INSERT INTO billing_notifications (...)
ON CONFLICT (agent_id, payment_id, notification_type, scheduled_date)
DO NOTHING
RETURNING id;

-- Se conseguiu inserir (claimed=true), retorna o ID
-- Se já existia (claimed=false), retorna NULL
```

### Uso no código Python
```python
claimed = await claim_notification(
    agent_id="...",
    payment_id="...",
    notification_type="overdue",
    scheduled_date="2026-02-19",
    customer_id="...",
    phone="5566...",
    days_from_due=-3,
)

if claimed:
    # Conseguiu clamar, pode enviar mensagem
    await send_message(...)
else:
    # Outra instância já clamou/enviou
    skip()
```

---

## Migration: `create_billing_failed_notifications.sql`

### O que faz
Cria a tabela `billing_failed_notifications` (Dead Letter Queue) para armazenar notificações que falharam após todas as tentativas de envio.

### Por que é necessário
**Problema:** Se a API do Leadbox E o UAZAPI falharem, a notificação é perdida silenciosamente. O cliente não recebe a cobrança, empresa perde dinheiro.

**Solução:** Salvar falhas em uma tabela separada, classificando o tipo de erro (timeout, rate_limit, auth_error, etc.) para facilitar:
- Reprocessamento automático (retry job)
- Análise de falhas recorrentes
- Alertas quando taxa de falha é alta
- Auditoria de mensagens não entregues

### Estrutura da Tabela
```sql
CREATE TABLE billing_failed_notifications (
  id BIGSERIAL PRIMARY KEY,
  agent_id TEXT NOT NULL,
  payment_id TEXT NOT NULL,
  customer_name TEXT,
  phone TEXT NOT NULL,
  message_text TEXT NOT NULL,
  notification_type TEXT NOT NULL, -- reminder, due_date, overdue
  dispatch_method TEXT, -- leadbox_push, uazapi

  -- Detalhes do erro
  error_message TEXT NOT NULL,
  failure_reason TEXT, -- timeout, api_error, rate_limit, etc

  -- Controle de reprocessamento
  status TEXT DEFAULT 'pending', -- pending, retrying, success, abandoned
  attempts_count INTEGER DEFAULT 1,
  last_attempt_at TIMESTAMPTZ DEFAULT NOW(),

  created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Classificação de Erros
| failure_reason | Descrição | Retry? |
|---|---|---|
| `timeout` | Timeout na chamada de API | Sim (backoff) |
| `rate_limit` | Rate limit atingido (429) | Sim (esperar) |
| `network_error` | Erro de rede/conexão | Sim |
| `auth_error` | API key inválida (401/403) | Não (precisa correção) |
| `not_found` | Recurso não encontrado (404) | Não |
| `invalid_data` | Dados inválidos (telefone, etc) | Não |
| `api_error` | Erro genérico da API | Sim (limitado) |

### Uso no código Python
```python
try:
    result = await uazapi.send_text_message(phone, message)
    if not result["success"]:
        raise ValueError(result.get("error"))
except Exception as e:
    # Salvar no DLQ
    await save_to_dead_letter_queue(
        agent_id=agent["id"],
        payment=payment,
        phone=phone,
        message=message,
        notification_type="overdue",
        scheduled_date=today_str,
        days_from_due=-3,
        error_message=str(e),
        dispatch_method="uazapi",
    )
```

### Reprocessamento (futuro)
Criar job `retry_failed_notifications.py` que:
1. Busca registros com `status='pending'` e `attempts_count < 3`
2. Filtra por `failure_reason` retriável (timeout, rate_limit, network_error)
3. Tenta reenviar com backoff exponencial
4. Atualiza `status` para `success` ou `abandoned`

---

## Verificar Aplicação

### Stored Procedure
```sql
-- Verificar se a função existe
SELECT proname, prosrc
FROM pg_proc
WHERE proname = 'claim_billing_notification';

-- Testar a função
SELECT * FROM claim_billing_notification(
  'test_agent',
  'test_payment',
  'overdue',
  '2026-02-19',
  'test_customer',
  '5566991234567',
  -3
);
```

### Tabela DLQ
```sql
-- Verificar se a tabela existe
\d billing_failed_notifications

-- Ver falhas recentes
SELECT
  id,
  agent_id,
  payment_id,
  failure_reason,
  error_message,
  attempts_count,
  status,
  created_at
FROM billing_failed_notifications
ORDER BY created_at DESC
LIMIT 10;

-- Estatísticas de falhas por motivo
SELECT
  failure_reason,
  COUNT(*) as total,
  COUNT(CASE WHEN status = 'pending' THEN 1 END) as pending,
  COUNT(CASE WHEN status = 'success' THEN 1 END) as recovered
FROM billing_failed_notifications
GROUP BY failure_reason
ORDER BY total DESC;
```

---

## Rollback (se necessário)

### Remover stored procedure
```sql
DROP FUNCTION IF EXISTS claim_billing_notification;
ALTER TABLE billing_notifications DROP CONSTRAINT IF EXISTS billing_notifications_unique_claim;
```

### Remover tabela DLQ
```sql
DROP TABLE IF EXISTS billing_failed_notifications;
```

**⚠️ ATENÇÃO:** Rollback da stored procedure fará o código voltar a verificar duplicatas com race condition. Rollback da tabela DLQ descartará falhas pendentes.
