# Lazaro-Real — Contexto do Sistema

## O que é este projeto
Plataforma de automação WhatsApp para Aluga Ar (locação de ar-condicionado em Rondonópolis/MT).
Composto por:
- **Painel web** (`apps/web/`) — gestão em lazaro.fazinzz.com
- **API TypeScript** (`apps/api/`) — backend do painel
- **Agente IA Ana** (`apps/ia/`) — agente WhatsApp da Ana, em produção na porta 3115

## Produção
```
PM2: lazaro-ia          → apps/ia/  porta 3115
PM2: lazaro-painel      → apps/web/
Traefik: lazaro.fazinzz.com → lazaro-ia (porta 3115)
PM2: agente-ia          → /var/www/phant/agente-ia/ porta 3005 (LEGADO — outros agentes)
```

## Agente Ana
- **Agent ID:** `14e6e5ce-4627-4e38-aac8-f0191669ff53`
- **WhatsApp:** via UAZAPI
- **Pagamentos:** Asaas
- **Google Calendar:** DESABILITADO (`google_calendar_enabled = false`)
- **Filas Leadbox:**
  - 537 → IA genérica
  - 544 → Billing (injeta prompt de cobrança)
  - 545 → Manutenção (injeta prompt de manutenção preventiva)

## Jobs Ativos (apps/ia/)
| Job | Arquivo | Horário | Timezone |
|-----|---------|---------|---------|
| billing_reconciliation | jobs/reconciliar_pagamentos.py | 06:00 seg-sex | São Paulo |
| billing_v2 | jobs/billing_job_v2.py | 09:00 seg-sex | São Paulo |
| maintenance_notifier | jobs/notificar_manutencoes.py | 09:00 seg-sex | Cuiabá |
| calendar_confirmation | jobs/confirmar_agendamentos.py | cada 30min | — |

## Scheduler
- Arquivo: `apps/ia/app/jobs/scheduler.py`
- **misfire_grace_time: 3600** — job executa mesmo se app reiniciar até 1h depois do horário
- Configurado em: `AsyncIOScheduler(job_defaults={'misfire_grace_time': 3600})`

## Billing Pipeline (apps/ia/app/billing/)
```
billing_job_v2.py
  → collector.py       — busca pagamentos PENDING/OVERDUE do Asaas
  → eligibility.py     — 6 checks de elegibilidade
  → ruler.py           — determina fase: "reminder" | "due_date" | "overdue"
  → dispatcher.py      — envia mensagem via UAZAPI/Leadbox
  → agent_processor.py — orquestra por agente
```

### Valores válidos de notification_type
**CORRETO:** `"reminder"`, `"due_date"`, `"overdue"`
**ERRADO (antigo):** `"pre"`, `"due"`, `"post"` — causa constraint violation no banco

### Bugs já corrigidos (não reverter)
1. `eligibility.py` — `.eq("active", "true")` — boolean Python causava HTTP 406
2. `eligibility.py` — `.or_()` com `@` no remotejid causava HTTP 406 — separado em duas queries
3. `ruler.py` — notification_type alinhado com constraint do banco
4. `scheduler.py` — misfire_grace_time: 3600

## Prompt Injection (apps/ia/app/domain/messaging/)
Quando lead responde, `message_processor.py`:
1. Consulta fila atual do lead via Leadbox API → `realtime_queue`
2. Mapeia fila → contexto via `queue_to_context`:
   - fila 544 → `"billing"`
   - fila 545 → `"manutencao"`
3. Injeta `context_prompt` correspondente do campo `context_prompts` (JSONB) na tabela `agents`
4. Fallback: `detect_conversation_context()` escaneia histórico

## Tabelas Supabase (Ana)
- `LeadboxCRM_Ana_14e6e5ce` — leads
- `leadbox_messages_Ana_14e6e5ce` — mensagens
- `agents` — config do agente
- `asaas_clientes`, `asaas_contratos`, `asaas_cobrancas` — dados Asaas
- `billing_notifications` — controle de notificações (constraint: notification_type IN ('reminder','due_date','overdue','sent','failed'))
- `billing_exceptions` — opt-out/pausa de cobrança
- `agent_audit_logs` — **audit trail de tool calls** (novo)
- `dispatch_log` — log de dispatches de notificações

## Audit Logging (Tool Execution Tracing)
Toda execução de tool do Gemini é logada em `agent_audit_logs`:

```sql
-- Ver últimas execuções de tools
SELECT * FROM v_recent_tool_executions LIMIT 50;

-- Execuções de um lead específico (última hora)
SELECT tool_name, success, duration_ms, error_message, created_at
FROM agent_audit_logs
WHERE lead_id LIKE '5566%'
  AND created_at > now() - interval '1 hour'
ORDER BY created_at DESC;

-- Tools que falharam hoje
SELECT tool_name, error_message, tool_input, created_at
FROM agent_audit_logs
WHERE success = false
  AND created_at > now() - interval '1 day'
ORDER BY created_at DESC;

-- Tempo médio por tool
SELECT tool_name,
       COUNT(*) as calls,
       AVG(duration_ms)::int as avg_ms,
       MAX(duration_ms) as max_ms
FROM agent_audit_logs
WHERE created_at > now() - interval '7 days'
GROUP BY tool_name
ORDER BY calls DESC;
```

**Implementação:** `app/core/audit_logger.py` + integração em `services/ia_gemini.py`

## Regras para o Claude Code
- NUNCA editar `/var/www/phant/agente-ia/` sem instrução explícita
- SEMPRE fazer py_compile antes de commit
- NUNCA reverter os bugs corrigidos listados acima
- Um fix por commit
- Antes de qualquer deploy, verificar divergências entre lazaro-real e phant

## Debugging
Ao diagnosticar qualquer problema, consulte SEMPRE primeiro:
`/var/www/lazaro-real/TROUBLESHOOTING.md`

Nunca tente adivinhar comandos de log ou queries SQL — o guia já tem tudo mapeado.

---

## Arquitetura de Produção

- **lazaro-real** (`/var/www/lazaro-real/`) — PRODUÇÃO. É o que está rodando agora.
- **lazaro-v2** (`/var/www/lazaro-v2/`) — refatoração em progresso. NÃO está em produção.
- **phant** (`/var/www/phant/agente-ia/`) — LEGADO. Outros agentes (Agnes, Salvador, Diana). NUNCA editar sem instrução explícita.

### Como Roda em Produção
O lazaro-ia roda via **PM2** (não Docker):
```
PM2: lazaro-ia
  script: /var/www/phant/agente-ia/venv/bin/uvicorn
  args: app.main:app --host 0.0.0.0 --port 3115
  cwd: /var/www/lazaro-real/apps/ia
```

O **Docker Swarm** (`lazaro` stack) é usado APENAS para Traefik routing labels:
- Stack name: `lazaro`
- Service: `lazaro_lazaro-router` (imagem: traefik/whoami — placeholder para labels)
- O serviço Swarm NÃO roda a aplicação — só fornece labels de roteamento ao Traefik

## Deploy Procedure

NUNCA faça deploy sem seguir estes passos:
```bash
# 1. Verificar que está no branch main e sem mudanças pendentes
cd /var/www/lazaro-real
git status
git log --oneline -3

# 2. Validar Python antes de tudo
find apps/ia -name "*.py" | xargs -I{} python3 -m py_compile {} && echo "✓ Syntax OK"

# 3. Reiniciar o PM2 para carregar as mudanças
pm2 restart lazaro-ia

# 4. Verificar que subiu
sleep 5
pm2 show lazaro-ia | grep -E "status|uptime|restarts"
curl -s https://lazaro.fazinzz.com/health && echo " ✓ UP" || echo " ✗ DOWN"
```

Se o health check falhar após o deploy, execute o rollback imediatamente.

## Rollback Procedure
```bash
# Rollback via git para versão anterior
cd /var/www/lazaro-real
git log --oneline -5          # identificar commit anterior
git checkout <commit-anterior>
pm2 restart lazaro-ia

# Verificar
sleep 5
curl -s https://lazaro.fazinzz.com/health && echo " ✓ Rollback OK" || echo " ✗ Ainda com problema"

# Se precisar voltar para main após rollback
git checkout main
```

## Atualizar Variáveis de Ambiente (.env)
```bash
# 1. Editar o .env
nano /var/www/lazaro-real/.env

# 2. Reiniciar para carregar as novas envs
pm2 restart lazaro-ia

# 3. Verificar que subiu com as novas envs
pm2 show lazaro-ia | grep -E "status|uptime"
curl -s https://lazaro.fazinzz.com/health && echo " ✓ UP"
```

## PM2 vs Docker Swarm — Arquitetura Atual

| Componente | Gerenciado por | Função |
|------------|----------------|--------|
| lazaro-ia (app Python) | PM2 | Roda a aplicação na porta 3115 |
| lazaro_lazaro-router (Swarm) | Docker Swarm | Apenas labels de roteamento Traefik |
| Traefik | Docker Swarm | Proxy reverso, SSL, roteamento |

### Comandos PM2 (uso diário)
| Ação | Comando |
|------|---------|
| Ver logs | `pm2 logs lazaro-ia` |
| Logs sem stream | `pm2 logs lazaro-ia --lines 200 --nostream` |
| Reiniciar | `pm2 restart lazaro-ia` |
| Status | `pm2 show lazaro-ia` |
| Listar todos | `pm2 list` |

### Comandos Swarm (só para debug de roteamento)
| Ação | Comando |
|------|---------|
| Ver serviço de routing | `docker service inspect lazaro_lazaro-router --pretty` |
| Ver labels Traefik | `docker service inspect lazaro_lazaro-router --pretty \| grep traefik` |

## Variáveis de Ambiente Disponíveis
```
API_BASE_URL, APP_ENV, DEFAULT_AGENT_SHORT_ID, DEFAULT_AGENT_UUID,
FRONTEND_URL, GEMINI_MAX_TOKENS, GEMINI_MODEL, GEMINI_TEMPERATURE,
GOOGLE_API_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, HOST,
JWT_SECRET, LEADBOX_API_KEY, LEADBOX_API_UUID, LEADBOX_BASE_URL,
LOG_FORMAT, LOG_LEVEL, MESSAGE_BUFFER_DELAY_SECONDS,
MESSAGE_BUFFER_TTL_SECONDS, PORT, REDIS_URL, SUPABASE_ANON_KEY,
SUPABASE_SERVICE_KEY, SUPABASE_URL, UAZAPI_API_KEY, UAZAPI_BASE_URL
```
