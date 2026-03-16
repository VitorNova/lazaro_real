# TROUBLESHOOTING — Lazaro-Real

> **Última atualização:** 2026-03-16
> **Serviços:** `lazaro-ia` (PM2, porta 3115), `agnes-agent` (PM2, porta 3002), `nginx` (systemd, porta 3001)
> **Logs:** `pm2 logs lazaro-ia --lines 200 --nostream`

---

## 0. Health Check Rápido

```bash
# Status dos serviços
pm2 list

# Health check da API
curl -s https://lazaro.fazinzz.com/health && echo " ✓ API UP" || echo " ✗ API DOWN"

# Últimas 10 linhas de log
pm2 logs lazaro-ia --lines 10 --nostream
```

---

## 1. Logs em Tempo Real

```bash
# Stream contínuo
pm2 logs lazaro-ia

# Últimas N linhas (sem stream)
pm2 logs lazaro-ia --lines 200 --nostream

# Só erros
pm2 logs lazaro-ia --lines 500 --nostream | grep -iE "error|exception|traceback"

# Por integração
pm2 logs lazaro-ia --lines 500 --nostream | grep -iE "uazapi"
pm2 logs lazaro-ia --lines 500 --nostream | grep -iE "asaas|pagamento"
pm2 logs lazaro-ia --lines 500 --nostream | grep -iE "leadbox|transfer"
pm2 logs lazaro-ia --lines 500 --nostream | grep -iE "\[BILLING"

# Exportar logs de hoje
pm2 logs lazaro-ia --lines 10000 --nostream | grep "$(date '+%Y-%m-%d')" > /tmp/logs-$(date '+%Y%m%d').txt
```

---

## 2. Logs por Integração

### UAZAPI (WhatsApp)

**Eventos structlog:** `uazapi_*`

```bash
pm2 logs lazaro-ia --lines 500 --nostream | grep -iE "uazapi_"
```

| Evento | Significado |
|--------|-------------|
| `uazapi_client_initialized` | Cliente UAZAPI inicializado |
| `uazapi_send_text_failed` | Falha ao enviar texto |
| `uazapi_send_media_failed` | Falha ao enviar mídia |
| `uazapi_send_audio_failed` | Falha ao enviar áudio |
| `uazapi_request_retry` | Retry automático em andamento |
| `uazapi_request_failed` | Requisição falhou após retries |
| `uazapi_get_status_failed` | Não conseguiu obter status da instância |

### Asaas (Pagamentos)

**Eventos structlog:** `asaas_*`
**Prefixo legado:** `[ASAAS WEBHOOK]`

```bash
pm2 logs lazaro-ia --lines 500 --nostream | grep -iE "asaas_|\[ASAAS"
```

| Evento | Significado |
|--------|-------------|
| `asaas_payment_created` | Cobrança criada com sucesso |
| `asaas_rate_limited` | Rate limit atingido (429), aguardando |
| `asaas_request_failed` | Requisição falhou |
| `[ASAAS WEBHOOK]` | Processamento de webhook Asaas |

### Leadbox (CRM)

**Eventos structlog:** `leadbox_*`
**Prefixos legados:** `[LEADBOX WEBHOOK]`, `[LEADBOX HANDLER]`, `[LEADBOX]`

```bash
# Todos os logs Leadbox
pm2 logs lazaro-ia --lines 500 --nostream | grep -iE "leadbox_|\[LEADBOX"

# Só webhooks recebidos
pm2 logs lazaro-ia --lines 500 --nostream | grep -iE "\[LEADBOX WEBHOOK\]"

# Mudanças de fila e pausa
pm2 logs lazaro-ia --lines 500 --nostream | grep -iE "PAUSANDO|pause|IGNORADO|Fila IA"

# Tickets fechados
pm2 logs lazaro-ia --lines 500 --nostream | grep -iE "FECHADO|resetado"
```

| Log | Significado |
|-----|-------------|
| `[LEADBOX WEBHOOK] Evento recebido: UpdateOnTicket` | Webhook de mudança de ticket |
| `[LEADBOX WEBHOOK] Evento recebido: FinishedTicket` | Webhook de ticket fechado |
| `[LEADBOX WEBHOOK] Evento recebido: NewMessage` | Nova mensagem do lead |
| `[LEADBOX HANDLER] Lead X \| ticket=Y \| queue=Z` | Dados extraídos do webhook |
| `[LEADBOX HANDLER] Fila IA detectada: queue=537` | Lead está em fila IA (ativo) |
| `[LEADBOX HANDLER] Lead X na fila 454 ... PAUSANDO` | Lead em fila humana → pausar IA |
| `[LEADBOX HANDLER] Redis pause SETADA` | IA pausada no Redis |
| `Pausa removida para pause:...` | IA reativada no Redis |
| `[LEADBOX HANDLER] Ticket X FECHADO` | Ticket fechado, resetando lead |
| `[LEADBOX HANDLER] Ticket fechado - lead X resetado` | Lead pronto para próximo atendimento |
| `[LEADBOX] Lead X IGNORADO: banco fila=454` | Mensagem ignorada (lead com humano) |
| `[LEADBOX HANDLER] Core update OK` | Atualização de estado no Supabase |
| `[LEADBOX HANDLER] Queue update OK` | Atualização de fila no Supabase |
| `leadbox_transfer_success` | Transferência via tool bem-sucedida |
| `leadbox_transfer_error` | Erro na transferência para fila |

**Filas importantes:**
| ID | Nome | Tipo |
|----|------|------|
| 537 | IA Genérica | IA processa |
| 544 | Billing | IA processa (prompt cobrança) |
| 545 | Manutenção | IA processa (prompt manutenção) |
| 453 | Atendimento | Humano (IA pausa) |
| 454 | Financeiro | Humano (IA pausa) |

---

## 3. Logs por Funcionalidade

### Billing Pipeline

**Prefixo:** `[BILLING JOB]`

```bash
pm2 logs lazaro-ia --lines 1000 --nostream | grep -iE "\[BILLING JOB\]"
```

### Webhooks

**Prefixos:** `[WEBHOOK]`, `[ASAAS WEBHOOK]`, `[LEADBOX HANDLER]`

```bash
pm2 logs lazaro-ia --lines 500 --nostream | grep -iE "\[WEBHOOK\]|\[ASAAS WEBHOOK\]|\[LEADBOX HANDLER\]"
```

### AI Tools

```bash
pm2 logs lazaro-ia --lines 500 --nostream | grep -iE "buscar_cobrancas_error|transfer_exception|manut_corretiva_error"
```

| Evento | Significado |
|--------|-------------|
| `buscar_cobrancas_error` | Erro ao buscar cobranças |
| `transfer_exception` | Exceção na transferência |
| `manut_corretiva_error` | Erro em manutenção corretiva |

### Jobs Agendados

```bash
pm2 logs lazaro-ia --lines 500 --nostream | grep -iE "Adding job|Scheduler"
```

| Job | Horário | ID no Scheduler |
|-----|---------|-----------------|
| billing_reconciliation | 06:00 seg-sex (São Paulo) | `billing_reconciliation` |
| billing_charge | 09:00 seg-sex (São Paulo) | `billing_charge` |
| maintenance_notifier | 09:00 seg-sex (Cuiabá) | `maintenance_notifier` |
| follow_up | cada 5 minutos | `follow_up` |

> **Nota:** Job `calendar_confirmation` está registrado mas inativo (nenhum agente com `google_calendar_enabled = true`).

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

### Mensagem não chegou para o cliente

```bash
pm2 logs lazaro-ia --lines 1000 --nostream | grep -iE "uazapi_send|send_text"
```

- [ ] Log mostra tentativa de envio?
- [ ] Número no formato `55DDD9XXXXXXXX`?
- [ ] Query `dispatch_log` tem registro?
- [ ] `UAZAPI_API_KEY` e `UAZAPI_BASE_URL` no .env?
- [ ] Instância UAZAPI conectada?

### Billing não disparou hoje

```bash
pm2 logs lazaro-ia --lines 2000 --nostream | grep -iE "\[BILLING JOB\]"
```

- [ ] Job aparece nos logs às 9h BRT?
- [ ] `billing_notifications` tem registros de hoje?
- [ ] É dia útil (seg–sex)?
- [ ] Contrato não está cancelado/deletado?

### Ana não está respondendo

```bash
pm2 list
curl -s https://lazaro.fazinzz.com/health
pm2 logs lazaro-ia --lines 100 --nostream | grep -iE "error|traceback"
```

- [ ] Serviço `lazaro-ia` está `online`?
- [ ] Health check retorna OK?
- [ ] Tem Traceback nos logs?
- [ ] Webhook chegando? `grep -i "WEBHOOK.*recebida"`
- [ ] `GOOGLE_API_KEY` (Gemini) no .env?

### Tool falhou silenciosamente

```bash
pm2 logs lazaro-ia --lines 1000 --nostream | grep -iE "buscar_cobrancas_error|transfer_exception"
```

- [ ] Query `agent_audit_logs WHERE success = false`
- [ ] Retorno da tool foi `None` ou string vazia?
- [ ] API externa (Asaas/Leadbox) estava fora?

### Lead não transferido para humano

```bash
pm2 logs lazaro-ia --lines 1000 --nostream | grep -iE "leadbox_transfer|transfer_"
```

- [ ] Queue ID correto? (537=IA, 453=Atendimento, 454=Financeiro)
- [ ] `leadbox_transfer_error` no log?
- [ ] Leadbox habilitado no agente? `leadbox_enabled = true`
- [ ] `handoff_triggers` configurado no agente?

### IA não pausa quando lead vai para fila humana

```bash
pm2 logs lazaro-ia --lines 500 --nostream | grep -iE "PAUSANDO|pause|IGNORADO|queue="
```

- [ ] Webhook `UpdateOnTicket` chegou? `grep "UpdateOnTicket"`
- [ ] `queueId` extraído corretamente? `grep "queue="`
- [ ] Log mostra `PAUSANDO`?
- [ ] Redis pause foi setada? `grep "Redis pause SETADA"`
- [ ] Próxima mensagem mostra `IGNORADO`?

### IA não reativa quando lead volta para fila IA

```bash
pm2 logs lazaro-ia --lines 500 --nostream | grep -iE "Fila IA detectada|Pausa removida|resetado"
```

- [ ] Webhook `UpdateOnTicket` com `queueId=537` chegou?
- [ ] Log mostra `Fila IA detectada`?
- [ ] Log mostra `Pausa removida`?
- [ ] `current_state` voltou para `'ai'` no banco?

### Ticket fechado mas lead não resetou

```bash
pm2 logs lazaro-ia --lines 500 --nostream | grep -iE "FECHADO|FinishedTicket|closedAt|resetado"
```

- [ ] Webhook `FinishedTicket` ou `UpdateOnTicket` com `closedAt` chegou?
- [ ] Log mostra `Ticket X FECHADO`?
- [ ] Log mostra `lead X resetado para IA`?
- [ ] `ticket_id` foi limpo no banco?
- [ ] `tenant_id` no agente bate com payload? (ex: 123)

### Lead novo não criou ticket no Leadbox

```bash
pm2 logs lazaro-ia --lines 500 --nostream | grep -iE "dispatch|POST PUSH|ticket_id"
```

- [ ] Lead é novo (não tem `ticket_id` no banco)?
- [ ] Dispatch foi chamado? `grep "leadbox_dispatch"`
- [ ] POST PUSH retornou sucesso? `grep "dispatch_success"`
- [ ] `handoff_triggers` habilitado no agente?
- [ ] API Leadbox respondeu OK? `grep -iE "leadbox.*error|leadbox.*failed"`

### Job de billing/manutenção não criou ticket

```bash
pm2 logs lazaro-ia --lines 1000 --nostream | grep -iE "\[BILLING JOB\]|maintenance_notifier|dispatch"
```

- [ ] Job executou? `grep "[BILLING JOB]"` ou `grep "maintenance_notifier"`
- [ ] Dispatch foi chamado para o lead?
- [ ] Lead já tinha ticket aberto? (dispatch reutiliza ticket existente)
- [ ] Erro de API? `grep -iE "leadbox.*error|dispatch.*failed"`
- [ ] `queue_billing` (544) ou `queue_maintenance` (545) configurados?

### Erro de API do Leadbox (timeout, 500)

```bash
pm2 logs lazaro-ia --lines 500 --nostream | grep -iE "leadbox.*error|leadbox.*failed|leadbox.*timeout|HTTP.*500"
```

- [ ] Qual endpoint falhou? (POST PUSH, PUT, GET)
- [ ] Retry automático funcionou?
- [ ] API Leadbox fora do ar? Verificar painel deles
- [ ] Token expirado? Verificar `handoff_triggers.api_token`
- [ ] Rate limit? (muitas requisições em sequência)

---

## 6. Comandos de Emergência

```bash
# Reiniciar serviço IA
pm2 restart lazaro-ia

# Reiniciar todos os serviços
pm2 restart all

# Ver top 30 erros das últimas 24h
pm2 logs lazaro-ia --lines 5000 --nostream | \
  grep "$(date '+%Y-%m-%d')" | \
  grep -iE "error|exception|traceback" | tail -30

# Checar memória e CPU
pm2 monit

# Status detalhado
pm2 describe lazaro-ia

# Validar sintaxe Python antes de restart
python3 -m py_compile apps/ia/app/main.py && echo "OK" || echo "ERRO DE SINTAXE"
```

---

## 7. Variáveis de Ambiente Críticas

```bash
# Verificar se todas estão presentes (sem mostrar valores)
cat /var/www/lazaro-real/apps/ia/.env | grep -oP '^[A-Z_]+' | sort
```

**Obrigatórias por integração:**

| Integração | Variáveis |
|------------|-----------|
| UAZAPI | `UAZAPI_BASE_URL`, `UAZAPI_API_KEY` |
| Supabase | `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` |
| Gemini | `GOOGLE_API_KEY` |
| Redis | `REDIS_URL` |

> **Nota:** Configurações do Leadbox vêm do banco de dados (tabela `agents`, campo `handoff_triggers`), não de variáveis de ambiente.

---

## 8. Referência de Eventos Structlog

### UAZAPI (WhatsApp)
| Evento | Nível | Campos |
|--------|-------|--------|
| `uazapi_client_initialized` | info | `integration`, `base_url` |
| `uazapi_send_text_failed` | error | `integration`, `phone`, `error` |
| `uazapi_send_media_failed` | error | `integration`, `phone`, `media_type`, `error` |
| `uazapi_send_audio_failed` | error | `integration`, `phone`, `ptt`, `error` |
| `uazapi_request_retry` | warning | `integration`, `method`, `endpoint`, `status_code`, `attempt` |
| `uazapi_request_failed` | error | `integration`, `method`, `endpoint`, `status_code` |
| `uazapi_get_status_failed` | error | `integration`, `error` |

### Asaas (Pagamentos)
| Evento | Nível | Campos |
|--------|-------|--------|
| `asaas_payment_created` | info | `integration`, `payment_id`, `customer_id`, `value` |
| `asaas_rate_limited` | warning | `integration`, `wait_time_seconds`, `endpoint` |
| `asaas_request_failed` | error | `integration`, `method`, `endpoint`, `status_code` |

### Leadbox (CRM)
| Evento | Nível | Campos |
|--------|-------|--------|
| `leadbox_transfer_success` | info | `ticket_id`, `queue_id`, `user_id` |
| `leadbox_transfer_error` | error | `error` |
| `leadbox_assign_error` | error | `error` |

**Logs legados (prefixo):**
| Prefixo | Nível | Contexto |
|---------|-------|----------|
| `[LEADBOX WEBHOOK] Evento recebido` | info | Webhook chegou |
| `[LEADBOX HANDLER] Lead X \| ticket=Y` | info | Dados do webhook extraídos |
| `[LEADBOX HANDLER] Fila IA detectada` | info | Lead em fila IA (537/544/545) |
| `[LEADBOX HANDLER] ... PAUSANDO` | info | Lead movido para fila humana |
| `[LEADBOX HANDLER] Redis pause SETADA` | info | Pausa ativada no Redis |
| `[LEADBOX HANDLER] Pausa Redis removida` | info | Pausa desativada no Redis |
| `[LEADBOX HANDLER] Ticket X FECHADO` | info | Ticket fechado no Leadbox |
| `[LEADBOX HANDLER] ... resetado para IA` | info | Lead pronto para próximo atendimento |
| `[LEADBOX] Lead X IGNORADO` | warning | Mensagem ignorada (lead com humano) |
| `[LEADBOX HANDLER] Core update OK` | info | Supabase: estado atualizado |
| `[LEADBOX HANDLER] Queue update OK` | info | Supabase: fila atualizada |

### AI Tools
| Evento | Nível | Campos |
|--------|-------|--------|
| `buscar_cobrancas_error` | error | `error`, `exc_info` |
| `transfer_exception` | error | `error`, `exc_info` |
| `manut_corretiva_error` | warning | `error` |

---

## 9. Prefixos de Log Legados (em uso)

| Prefixo | Contexto |
|---------|----------|
| `[BILLING JOB]` | Job principal de cobrança |
| `[ASAAS WEBHOOK]` | Processamento de webhooks Asaas |
| `[LEADBOX WEBHOOK]` | Webhook Leadbox recebido |
| `[LEADBOX HANDLER]` | Processamento de eventos Leadbox |
| `[LEADBOX]` | Decisões de roteamento (IGNORADO, etc) |
| `[MSG RECEBIDA]` | Mensagem do WhatsApp recebida |
| `[BUFFER]` | Buffer de mensagens (agregação) |
| `[PROCESS]` | Processamento de mensagem pela IA |
| `[GEMINI]` | Interação com API Gemini |
| `[UAZAPI]` | Envio de mensagem via UAZAPI |
| `[TOOL START]` / `[TOOL END]` | Execução de tools da IA |

---

## 10. Arquitetura de Serviços

| Serviço | Tipo | Porta | Diretório | Função |
|---------|------|-------|-----------|--------|
| `lazaro-ia` | PM2 | 3115 | `/var/www/lazaro-real/apps/ia` | Backend Python: Webhooks, IA, Jobs, API |
| `agnes-agent` | PM2 | 3002 | `/var/www/phant/agnes-agent` | Fallback TypeScript (asaas, manutencoes, athena) |
| `nginx` | systemd | 3001 | `/var/www/lazaro-real/apps/web/dist` | Frontend estático |

**Traefik roteia:**
- `lazaro.fazinzz.com/*` → nginx (porta 3001) → arquivos estáticos
- `lazaro.fazinzz.com/api/*` → lazaro-ia (porta 3115) → Python
- `lazaro.fazinzz.com/webhooks/*` → lazaro-ia (porta 3115)

**Proxy interno (lazaro-ia → agnes-agent):**
- `/api/dashboard/asaas/*` → proxy → agnes-agent (3002)
- `/api/dashboard/manutencoes/*` → proxy → agnes-agent (3002)
- `/api/athena/*` → proxy → agnes-agent (3002)

> Ao debugar, verifique qual serviço está processando:
> - Webhooks/API Python: `pm2 logs lazaro-ia`
> - Asaas/Manutencoes/Athena: `pm2 logs agnes-agent`
> - Frontend: `tail -f /var/log/nginx/lazaro.access.log`
