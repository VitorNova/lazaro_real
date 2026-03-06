# TROUBLESHOOTING — Aluga Ar / Lazaro-Real

> **Última atualização:** 2026-03-06
> **Serviço:** PM2 `lazaro-ia` (porta 3115)
> **Logs:** `/root/.pm2/logs/lazaro-ia-*.log`

---

## 0. Health Check Rápido

```bash
# Status do serviço
pm2 status lazaro-ia

# Health check da API
curl -s https://lazaro.fazinzz.com/health && echo " ✓ API UP" || echo " ✗ API DOWN"

# Últimas 5 linhas de log
pm2 logs lazaro-ia --lines 5 --nostream
```

---

## 1. Logs em Tempo Real

```bash
# Todos os logs (stream)
pm2 logs lazaro-ia

# Últimas N linhas (sem stream)
pm2 logs lazaro-ia --lines 200 --nostream

# Só erros
pm2 logs lazaro-ia --lines 500 --nostream 2>&1 | grep -iE "error|exception|traceback"

# Por integração
pm2 logs lazaro-ia --lines 500 --nostream 2>&1 | grep -iE "uazapi"
pm2 logs lazaro-ia --lines 500 --nostream 2>&1 | grep -iE "asaas|pagamento"
pm2 logs lazaro-ia --lines 500 --nostream 2>&1 | grep -iE "calendar|agendamento|oauth"
pm2 logs lazaro-ia --lines 500 --nostream 2>&1 | grep -iE "leadbox|transfer"
pm2 logs lazaro-ia --lines 500 --nostream 2>&1 | grep -iE "\[BILLING"
pm2 logs lazaro-ia --lines 500 --nostream 2>&1 | grep -iE "_error|_failed"

# Exportar logs de hoje
pm2 logs lazaro-ia --lines 10000 --nostream 2>&1 | grep "$(date '+%Y-%m-%d')" > /tmp/logs-$(date '+%Y%m%d').txt
```

---

## 2. Logs por Integração

### UAZAPI (WhatsApp)

**Eventos structlog:** `uazapi_*`

```bash
pm2 logs lazaro-ia --lines 500 --nostream 2>&1 | grep -iE "uazapi_"
```

| Evento | Significado |
|--------|-------------|
| `uazapi_client_initialized` | Cliente UAZAPI inicializado |
| `uazapi_send_text_failed` | Falha ao enviar texto (número inválido ou sessão expirada) |
| `uazapi_send_media_failed` | Falha ao enviar mídia |
| `uazapi_send_audio_failed` | Falha ao enviar áudio |
| `uazapi_request_retry` | Retry automático em andamento |
| `uazapi_request_failed` | Requisição falhou após retries |
| `uazapi_get_status_failed` | Não conseguiu obter status da instância |

### Asaas (Pagamentos)

**Eventos structlog:** `asaas_*`
**Prefixo legado:** `[ASAAS WEBHOOK]`

```bash
pm2 logs lazaro-ia --lines 500 --nostream 2>&1 | grep -iE "asaas_|\[ASAAS"
```

| Evento | Significado |
|--------|-------------|
| `asaas_client_initialized` | Cliente Asaas inicializado |
| `asaas_payment_created` | Cobrança criada com sucesso |
| `asaas_payment_retrieved` | Cobrança consultada |
| `asaas_payment_cancelled` | Cobrança cancelada |
| `asaas_rate_limited` | Rate limit atingido (429), aguardando |
| `asaas_request_failed` | Requisição falhou |
| `[ASAAS WEBHOOK]` | Processamento de webhook Asaas |

### Google Calendar

**Eventos structlog:** `calendar_*`
**Prefixo legado:** `[GoogleOAuth]`, `[CONFIRMAR AGENDAMENTOS]`

```bash
pm2 logs lazaro-ia --lines 500 --nostream 2>&1 | grep -iE "calendar_|GoogleOAuth|\[CONFIRMAR"
```

| Evento | Significado |
|--------|-------------|
| `calendar_create_event_error` | Erro ao criar evento |
| `calendar_oauth_error` | Token OAuth expirado, refazer autenticação |
| `calendar_list_events_error` | Erro ao listar eventos |
| `calendar_get_availability_error` | Erro ao verificar disponibilidade |
| `[CONFIRMAR AGENDAMENTOS]` | Job de confirmação de agendamentos |

### Leadbox (CRM)

**Eventos structlog:** `leadbox_*`
**Prefixo legado:** `[LEADBOX HANDLER]`, `[LEADBOX DISPATCH]`

```bash
pm2 logs lazaro-ia --lines 500 --nostream 2>&1 | grep -iE "leadbox_|\[LEADBOX"
```

| Evento | Significado |
|--------|-------------|
| `leadbox_transfer_error` | Erro na transferência para fila |
| `leadbox_transfer_success` | Transferência bem-sucedida |
| `leadbox_assign_error` | Erro ao atribuir ticket |
| `leadbox_get_queue_error` | Erro ao obter fila atual |
| `leadbox_send_message_error` | Erro ao enviar mensagem via Leadbox |

**Filas importantes:**
- 537 → IA genérica
- 544 → Billing (injeta prompt de cobrança)
- 545 → Manutenção

---

## 3. Logs por Funcionalidade

### Billing Pipeline

**Prefixos:** `[BILLING JOB]`, `[BILLING CONTEXT]`, `[SYNC BILLING]`

```bash
pm2 logs lazaro-ia --lines 1000 --nostream 2>&1 | grep -iE "\[BILLING"
```

| Prefixo | Significado |
|---------|-------------|
| `[BILLING JOB]` | Job principal de cobrança (9h seg-sex) |
| `[BILLING CONTEXT]` | Injeção de contexto de cobrança |
| `[SYNC BILLING]` | Sincronização de dados Asaas |
| `[RECONCILIAR PAGAMENTOS]` | Job de reconciliação (6h seg-sex) |

### Webhooks

**Prefixos:** `[WEBHOOK]`, `[ASAAS WEBHOOK]`

```bash
pm2 logs lazaro-ia --lines 500 --nostream 2>&1 | grep -iE "\[WEBHOOK\]"
```

| Prefixo | Significado |
|---------|-------------|
| `[WEBHOOK] Mensagem recebida` | Webhook UAZAPI processado |
| `[ASAAS WEBHOOK]` | Webhook Asaas processado |
| `[LEADBOX HANDLER]` | Webhook Leadbox processado |

### AI Tools

```bash
pm2 logs lazaro-ia --lines 500 --nostream 2>&1 | grep -iE "_error|tool_|TOOL"
```

| Evento | Significado |
|--------|-------------|
| `buscar_cobrancas_error` | Erro ao buscar cobranças |
| `transfer_exception` | Exceção na transferência |
| `manut_corretiva_error` | Erro em manutenção corretiva |
| `timezone_fetch_error` | Erro ao detectar fuso horário |
| `[AUDIT] Timeout logging tool` | Audit log demorou mais de 2s |

### Jobs Agendados

```bash
pm2 logs lazaro-ia --lines 500 --nostream 2>&1 | grep -iE "Adding job|Scheduler|JOB\]"
```

| Job | Horário | Prefixo |
|-----|---------|---------|
| billing_reconciliation | 06:00 seg-sex | `[RECONCILIAR PAGAMENTOS]` |
| billing_v2 | 09:00 seg-sex | `[BILLING JOB]` |
| maintenance_notifier | 09:00 seg-sex (Cuiabá) | `[MAINTENANCE JOB]` |
| calendar_confirmation | cada 30min | `[CONFIRMAR AGENDAMENTOS]` |

---

## 4. Queries SQL por Problema

### Últimas cobranças (billing_notifications)

```sql
-- Últimas 20
SELECT id, customer_name, phone, notification_type, status,
       valor, due_date, sent_at, error_message, created_at
FROM billing_notifications
ORDER BY created_at DESC LIMIT 20;

-- Cobranças com erro hoje
SELECT * FROM billing_notifications
WHERE DATE(created_at) = CURRENT_DATE
  AND (status = 'failed' OR error_message IS NOT NULL);

-- Resumo por tipo de notificação
SELECT notification_type, status, COUNT(*) as total
FROM billing_notifications
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY notification_type, status
ORDER BY total DESC;
```

### Dispatch de mensagens (dispatch_log)

```sql
-- Últimos despachos
SELECT id, job_type, customer_name, phone, notification_type,
       status, dispatch_method, sent_at, error_message
FROM dispatch_log
ORDER BY created_at DESC LIMIT 20;

-- Falhas recentes
SELECT job_type, failure_reason, COUNT(*) as total
FROM dispatch_log
WHERE status = 'failed'
  AND created_at > NOW() - INTERVAL '7 days'
GROUP BY job_type, failure_reason
ORDER BY total DESC;

-- Taxa de sucesso por método
SELECT dispatch_method,
       COUNT(*) as total,
       SUM(CASE WHEN status = 'sent' THEN 1 ELSE 0 END) as enviados,
       ROUND(100.0 * SUM(CASE WHEN status = 'sent' THEN 1 ELSE 0 END) / COUNT(*), 2) as taxa_sucesso
FROM dispatch_log
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY dispatch_method;
```

### Auditoria de tools (agent_audit_logs)

```sql
-- Últimas execuções de tools
SELECT tool_name, success, duration_ms, error_message, created_at
FROM agent_audit_logs
ORDER BY created_at DESC LIMIT 50;

-- Tools que falharam
SELECT tool_name, error_message, COUNT(*) as falhas
FROM agent_audit_logs
WHERE success = false
  AND created_at > NOW() - INTERVAL '7 days'
GROUP BY tool_name, error_message
ORDER BY falhas DESC;

-- Tempo médio por tool
SELECT tool_name,
       COUNT(*) as chamadas,
       AVG(duration_ms)::int as media_ms,
       MAX(duration_ms) as max_ms
FROM agent_audit_logs
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY tool_name
ORDER BY chamadas DESC;

-- Execuções de um lead específico
SELECT tool_name, success, duration_ms, error_message, created_at
FROM agent_audit_logs
WHERE lead_id LIKE '5566%'  -- prefixo do telefone
  AND created_at > NOW() - INTERVAL '1 day'
ORDER BY created_at DESC;
```

### Follow-up history

```sql
-- Últimos follow-ups
SELECT id, lead_name, remotejid, follow_up_type, step_number,
       lead_responded, sent_at
FROM follow_up_history
ORDER BY created_at DESC LIMIT 20;

-- Taxa de resposta
SELECT follow_up_type,
       COUNT(*) as total,
       SUM(CASE WHEN lead_responded THEN 1 ELSE 0 END) as responderam,
       ROUND(100.0 * SUM(CASE WHEN lead_responded THEN 1 ELSE 0 END) / COUNT(*), 2) as taxa_resposta
FROM follow_up_history
WHERE created_at > NOW() - INTERVAL '30 days'
GROUP BY follow_up_type;
```

### Rastreamento end-to-end

```sql
-- Cobrança → Dispatch
SELECT
  bn.id,
  bn.customer_name,
  bn.phone,
  bn.notification_type,
  bn.status as bn_status,
  bn.sent_at as bn_sent,
  dl.status as dl_status,
  dl.sent_at as dl_sent,
  dl.error_message
FROM billing_notifications bn
LEFT JOIN dispatch_log dl ON dl.reference_id = bn.id::text
WHERE bn.created_at > NOW() - INTERVAL '7 days'
ORDER BY bn.created_at DESC;
```

---

## 5. Checklist por Sintoma

### ❌ Mensagem não chegou para o cliente

```bash
pm2 logs lazaro-ia --lines 1000 --nostream 2>&1 | grep -iE "uazapi_send|send_text"
```

- [ ] Log mostra tentativa de envio?
- [ ] Número no formato `55DDD9XXXXXXXX`?
- [ ] Query `dispatch_log` tem registro?
- [ ] `UAZAPI_API_KEY` e `UAZAPI_BASE_URL` no .env?
- [ ] Instância UAZAPI conectada?

### ❌ Billing não disparou hoje

```bash
pm2 logs lazaro-ia --lines 2000 --nostream 2>&1 | grep -iE "\[BILLING JOB\]"
```

- [ ] Job aparece nos logs às 9h BRT?
- [ ] `billing_notifications` tem registros de hoje?
- [ ] É dia útil (seg–sex)?
- [ ] Contrato não está cancelado/deletado?
- [ ] `misfire_grace_time: 3600` configurado no scheduler?

### ❌ Ana não está respondendo

```bash
pm2 status lazaro-ia
curl -s https://lazaro.fazinzz.com/health
pm2 logs lazaro-ia --lines 100 --nostream 2>&1 | grep -iE "error|traceback"
```

- [ ] Serviço está `online`?
- [ ] Health check retorna OK?
- [ ] Tem Traceback nos logs?
- [ ] Webhook chegando? `grep -i "WEBHOOK.*recebida"`
- [ ] `GOOGLE_API_KEY` (Gemini) no .env?

### ❌ Tool falhou silenciosamente

```bash
pm2 logs lazaro-ia --lines 1000 --nostream 2>&1 | grep -iE "_error|_failed|tool.*fail"
```

- [ ] Query `agent_audit_logs WHERE success = false`
- [ ] Retorno da tool foi `None` ou string vazia?
- [ ] API externa (Asaas/Calendar) estava fora?
- [ ] Timeout de 2s do audit foi atingido?

### ❌ Prompt não injetado / agente sem contexto

```bash
pm2 logs lazaro-ia --lines 500 --nostream 2>&1 | grep -iE "\[BILLING CONTEXT\]|\[CONTEXT\]"
```

- [ ] Webhook Asaas chegou com `payment_id` válido?
- [ ] Log mostra `[BILLING CONTEXT] Dados carregados`?
- [ ] Lead está na fila 544 (billing) ou 545 (manutenção)?
- [ ] Campo `context_prompts` na tabela `agents` preenchido?

### ❌ Lead não transferido para humano

```bash
pm2 logs lazaro-ia --lines 1000 --nostream 2>&1 | grep -iE "transfer|leadbox_transfer"
```

- [ ] Queue ID correto? (verificar `[LEADBOX DISPATCH] PUT confirmacao`)
- [ ] Query `dispatch_log WHERE notification_type = 'transfer'`
- [ ] `LEADBOX_API_KEY` e `LEADBOX_BASE_URL` no .env?
- [ ] Leadbox habilitado no agente? `leadbox_enabled = true`

---

## 6. Comandos de Emergência

```bash
# Reiniciar sem perder histórico
pm2 restart lazaro-ia

# Reiniciar com atualização de ambiente
pm2 restart lazaro-ia --update-env

# Ver top 30 erros das últimas 24h
pm2 logs lazaro-ia --lines 5000 --nostream 2>&1 | \
  grep "$(date '+%Y-%m-%d')" | \
  grep -iE "error|exception|traceback" | tail -30

# Checar memória e CPU
pm2 monit

# Status detalhado
pm2 describe lazaro-ia

# Forçar rebuild se código mudou
cd /var/www/lazaro-real && pm2 restart lazaro-ia
```

---

## 7. Variáveis de Ambiente Críticas

```bash
# Verificar se todas estão presentes (sem mostrar valores)
cat /var/www/lazaro-real/.env | grep -oP '^[A-Z_]+' | sort
```

**Obrigatórias por integração:**

| Integração | Variáveis |
|------------|-----------|
| UAZAPI | `UAZAPI_BASE_URL`, `UAZAPI_API_KEY` |
| Supabase | `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` |
| Gemini | `GOOGLE_API_KEY` |
| Calendar | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` |
| Leadbox | `LEADBOX_BASE_URL`, `LEADBOX_API_KEY`, `LEADBOX_API_UUID` |
| Redis | `REDIS_URL` |

---

## 8. Referência de Eventos Structlog

### UAZAPI (WhatsApp)
| Evento | Nível | Campos |
|--------|-------|--------|
| `uazapi_client_initialized` | info | `integration`, `base_url` |
| `uazapi_send_text_failed` | error | `integration`, `phone`, `error` |
| `uazapi_send_media_failed` | error | `integration`, `phone`, `media_type`, `error` |
| `uazapi_request_retry` | warning | `integration`, `method`, `endpoint`, `status_code`, `attempt` |
| `uazapi_request_failed` | error | `integration`, `method`, `endpoint`, `status_code` |

### Asaas (Pagamentos)
| Evento | Nível | Campos |
|--------|-------|--------|
| `asaas_client_initialized` | info | `integration`, `base_url` |
| `asaas_payment_created` | info | `integration`, `payment_id`, `customer_id`, `value` |
| `asaas_payment_cancelled` | info | `integration`, `payment_id` |
| `asaas_rate_limited` | warning | `integration`, `wait_time_seconds`, `endpoint` |
| `asaas_request_failed` | error | `integration`, `method`, `endpoint`, `status_code` |

### Leadbox (CRM)
| Evento | Nível | Campos |
|--------|-------|--------|
| `leadbox_transfer_success` | info | `ticket_id`, `queue_id`, `user_id` |
| `leadbox_transfer_error` | error | `error` |
| `leadbox_assign_error` | error | `error` |
| `leadbox_get_queue_error` | error | `error` |

### Calendar
| Evento | Nível | Campos |
|--------|-------|--------|
| `calendar_create_event_error` | error | `error` |
| `calendar_oauth_error` | error | `error` |
| `calendar_list_events_error` | error | `error` |

### AI Tools
| Evento | Nível | Campos |
|--------|-------|--------|
| `buscar_cobrancas_error` | error | `error`, `exc_info` |
| `transfer_exception` | error | `error`, `exc_info` |
| `manut_corretiva_error` | warning | `error` |
| `timezone_fetch_error` | warning | `error` |

---

## 9. Prefixos Legados (ainda em uso)

| Prefixo | Quantidade | Contexto |
|---------|------------|----------|
| `[BILLING JOB]` | 65 | Job principal de cobrança |
| `[ASAAS WEBHOOK]` | 49 | Processamento de webhooks Asaas |
| `[CONFIRMAR AGENDAMENTOS]` | 39 | Job de confirmação de agenda |
| `[MAINTENANCE]` | 23 | Jobs de manutenção |
| `[LEADBOX HANDLER]` | 23 | Processamento de webhooks Leadbox |
| `[FOLLOW UP JOB]` | 21 | Job de follow-up de leads |
| `[BILLING CONTEXT]` | 8 | Injeção de contexto de cobrança |
| `[HUMAN TAKEOVER]` | 11 | Transferência para humano |
