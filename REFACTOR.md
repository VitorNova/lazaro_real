# REFATORAÇÃO — lazaro-real
Leia este arquivo no início de CADA sessão antes de qualquer ação.

## OBJETIVO
Reorganizar o codebase sem quebrar funcionalidade.
Regra absoluta: leia antes de agir. Uma fase por vez. Compile após cada mudança.

## STATUS DAS FASES

### FASE 1 — Eliminar Duplicações ✅
- [x] 1.1 Supabase: repositories melhorados, services/supabase.py marcado DEPRECATED
- [x] 1.4 Stubs de api/ removidos
- [x] 1.5 Utils unificado em core/utils/
- [⏭️] 1.2 WhatsApp: pulado (risco sync/async)
- [🔒] 1.3 Tools: bloqueado (dependência invertida — ai/tools/ importa de tools/)

### FASE 2 — Quebrar Monolitos ✅
- [x] mensagens.py agora chama domain/messaging/context/ em vez de funções locais
- [x] pagamentos.py agora chama domain/billing/services/ em vez de funções locais
- [ ] Remover funções locais duplicadas de mensagens.py (aguarda testes em produção)
- [ ] Remover funções locais duplicadas de pagamentos.py (aguarda testes em produção)
- [🗑️] athena.py DELETADO (api/routes/athena.py, domain/analytics/, services/athena/)

### FASE 3 — Jobs Thin ✅
- [x] notificar_manutencoes.py (868→115 linhas) → domain/maintenance/services/notification_service.py
- [x] Template de mensagem → prompts/maintenance/reminder_7d.txt
- [x] cobrar_clientes.py (1839→163 linhas) → domain/billing/services/:
  - billing_orchestrator.py: process_agent_billing
  - billing_job_lock.py: lock distribuído
  - customer_phone.py: normalização de telefone
- [x] reengajar_leads.py (1466→203 linhas) → domain/leads/services/:
  - follow_up_orchestrator.py: process_agent_follow_up
  - follow_up_eligibility.py: busca de leads elegíveis
  - lead_classifier.py: classificação IA (CLASSIFIER_PROMPT)
  - follow_up_message_generator.py: geração via Gemini
  - follow_up_throttle.py: rate limiting Redis
  - follow_up_recorder.py: registro de envios

### FASE 4 — Logging Unificado ✅
- [x] Substituir print() por logger em: inspect_image, reclassify_origins, reprocess_asaas_payments
- [x] Remover wrappers _log, _log_warn, _log_error em 10 jobs:
  - billing_job, cobrar_clientes, confirmar_agendamentos, follow_up_job
  - reconciliar_pagamentos, reengajar_leads, reprocess_asaas_payments, sync_billing
- [x] Padrão: logger = logging.getLogger(__name__)

### FASE 5 — Segurança ✅
- [x] Criar core/security/injection_guard.py
- [x] Integrar injection_guard em webhooks/mensagens.py (antes do Gemini)
- [x] Validação Pydantic nos webhooks (api/models/webhook_models.py)

## PROBLEMA ABERTO
1.3 BLOQUEADO: ai/tools/ importa de tools/ — dependência invertida.
Solução necessária: inverter a dependência fazendo tools/ importar de ai/tools/ ou eliminar tools/.

## COMMITS FEITOS
- 3f97696 refactor(fase-E.2): integrar _extract_message_data e _handle_control_command (-157 linhas)
- 1b0fb6d refactor(pagamentos): extrair webhook_handler para domain/billing/handlers (-138 linhas)
- 442bc51 refactor(fase-E): remover funções dead code de mensagens.py (-760 linhas)
- ebf002f refactor(fase-B): integrar message_processor em mensagens.py (-698 linhas)
- 27e2db3 refactor(fase-5): validação Pydantic nos webhooks
- 398632c refactor(fase-A): remover _create_function_handlers inline (1360 linhas)
- 60810dc refactor(fase-4): logging unificado em jobs
- e3559fb refactor(fase-B): alinhar message_processor.py com Fase A
- f9bf97a refactor(fase-A): integrar ai/tools/tool_registry em mensagens.py
- 640d1f0 docs: mapear mensagens.py e auditar leadbox_handler
- d4151f9 refactor(fase-3): notificar_manutencoes.py thin (868→115 linhas)
- 7537dbf refactor(fase-3): reengajar_leads.py como thin dispatcher
- 7264b7c refactor(fase-3): atualizar __init__.py de leads/services
- da8e8af refactor(fase-3): extrair follow_up_orchestrator para domain/leads/services
- 178ca10 refactor(fase-3): cobrar_clientes.py como thin dispatcher
- 2565892 refactor(fase-3): atualizar __init__.py de billing/services
- 4e0a8da refactor(fase-3): extrair billing_orchestrator para domain/billing/services
- 015ade1 refactor(fase-3): extrair billing_job_lock para domain/billing/services
- f1e215b refactor(fase-3): extrair customer_phone para domain/billing/services
- d569fc4 refactor(fase-2): integrar domain/billing em pagamentos.py
- 3b65c9b refactor(fase-2): integrar domain/messaging em mensagens.py
- 67f99f6 refactor(fase-1.5): unificar utils em core/utils
- 118fbba refactor(fase-1.4): remover stubs de api/
- e21ac84 refactor(fase-1.1): marcar services/supabase.py como DEPRECATED
- c57667d refactor(fase-1.1): adicionar metodos faltantes nos repositories

## MAPEAMENTO: mensagens.py (1458 linhas — era 4414, redução de 67%)

### Métodos da classe WhatsAppWebhookHandler

| Método | Linhas | Tamanho | Status Domain/ |
|--------|--------|---------|----------------|
| `__init__` | 844-863 | 19 | - |
| `_extract_message_data` | 156-170 | 14 | ✅ INTEGRADO → `incoming_message_handler.py` (Fase E.2) |
| `_handle_control_command` | 171-212 | 41 | ✅ INTEGRADO → `incoming_message_handler.py` (Fase E.2) |
| `_schedule_processing` | 1179-? | ~50 | ✅ Stub em `message_processor.py` |
| `_process_buffered_messages` | 1196-1250 | 54 | ✅ INTEGRADO → `message_processor.py` (Fase B) |
| `_prepare_gemini_messages` | 1919-1955 | 36 | ✅ Stub em `message_processor.py` |
| `_save_conversation_history` | 1957-2132 | 175 | ✅ Em `conversation_manager.py` |
| `_create_function_handlers` | — | — | ✅ REMOVIDO (Fase A) → `ai/tools/tool_registry.py` |
| `handle_message` | 705-1490 | 785 | ⏸️ BLOQUEADO — complexidade alta (ver Fase C) |

### Funções standalone duplicadas — ✅ REMOVIDAS (Fase E)

| Função | Status |
|--------|--------|
| `get_context_prompt` | ✅ REMOVIDA (usar `context_detector.py`) |
| `detect_conversation_context` | ✅ REMOVIDA (usar `context_detector.py`) |
| `get_contract_data_for_maintenance` | ✅ REMOVIDA (usar `maintenance_context.py`) |
| `build_maintenance_context_prompt` | ✅ REMOVIDA (usar `maintenance_context.py`) |
| `get_billing_data_for_context` | ✅ REMOVIDA (usar `billing_context.py`) |
| `build_billing_context_prompt` | ✅ REMOVIDA (usar `billing_context.py`) |
| `prepare_system_prompt` | ✅ REMOVIDA (usar `context_detector.py`) |
| `TIMEZONE_MAP`, `DEFAULT_TIMEZONE` | ✅ REMOVIDAS (constantes duplicadas) |

### Problema principal — ✅ RESOLVIDO
`_create_function_handlers` (1358 linhas) foi REMOVIDO (Fase A).
Agora usa `ai/tools/tool_registry.py` com handlers modulares.

### Plano de Extração (ordem de prioridade)

1. **Fase A**: ✅ COMPLETO — `_create_function_handlers` → `ai/tools/tool_registry.py`
   - Import: `from app.ai.tools.tool_registry import get_function_handlers`
   - Uso: `handlers = get_function_handlers(supabase, context)`
   - Método inline (1360 linhas) **REMOVIDO** de mensagens.py
   - Commits: f9bf97a (integração), 398632c (remoção inline)
2. **Fase B**: ✅ COMPLETO — `_process_buffered_messages` → `message_processor.py`
   - Import: `from app.domain.messaging.services.message_processor import process_buffered_messages`
   - Método inline (750 linhas) **REMOVIDO** de mensagens.py
   - mensagens.py: 3073 → 2375 linhas (-698 linhas, 23%)
   - Commits: e3559fb (alinhamento), ebf002f (integração)
3. **Fase C**: ⏸️ BLOQUEADA — `handle_message` não compatível com orchestrator
   - `handle_message` tem 785 linhas com lógica complexa de produção
   - Inclui: human takeover, race conditions, dispatch integration, pattern detection
   - Orchestrator (`message_orchestrator.py`) tem placeholders incompatíveis
   - Handler usa estado de instância (_scheduled_tasks, _processing_keys, buffer_delay)
   - **Alternativa futura**: extrair sub-serviços (HumanTakeoverService, DispatchCheckService)
   - **Status**: Manter inline até refatoração mais profunda
4. **Fase D**: Testar módulos em produção (Fases A, B, E prontas)
5. **Fase E**: ✅ COMPLETO — Funções dead code removidas (-760 linhas)
   - 7 funções duplicadas removidas (usam context modules)
   - Constantes TIMEZONE_* duplicadas removidas
   - mensagens.py: 2375 → 1615 linhas
   - Commit: 442bc51

---

## AUDITORIA: Leadbox Handler (2024-03-04)

### Arquivos auditados
- `api/handlers/leadbox_handler.py` (439 linhas)
- `api/services/lead_intake_service.py` (446 linhas)

### Funções mapeadas

| Função | Arquivo | Linhas | Responsabilidade |
|--------|---------|--------|------------------|
| `handle_new_message` | leadbox_handler | 22-67 | Roteia mensagens humano/lead |
| `handle_ticket_closed` | leadbox_handler | 69-145 | Reseta lead para IA |
| `handle_queue_change` | leadbox_handler | 148-323 | Orquestração de roteamento de filas |
| `_handle_ia_queue` | leadbox_handler | 326-438 | Reativação IA + injeção contexto |
| `capture_human_message` | lead_intake_service | 23-106 | Salva msg humano no histórico |
| `process_lead_message` | lead_intake_service | 109-219 | Converte payload e chama handler |
| `create_lead_if_missing` | lead_intake_service | 222-278 | Cria lead (race condition) |
| `inject_agnes_message` | lead_intake_service | 280-336 | Injeta "12" para AGNES |
| `inject_return_context` | lead_intake_service | 339-446 | Injeta contexto retorno fila humana |

### Conclusão
- Lógica de devolução para IA **FUNCIONAL** em `handle_ticket_closed`
- Roteamento de filas **completo** em `handle_queue_change`
- **NÃO precisa** criar `domain/leads/services/queue_routing.py`
- Candidato futuro para extração: `_handle_ia_queue` → `domain/leads/services/ia_queue_handler.py`

---

## MAPEAMENTO: pagamentos.py (2892 linhas — era 3030, redução de 5%)

### Fase F: ✅ COMPLETO — Webhook handler centralizado

**Arquivo criado:** `domain/billing/handlers/webhook_handler.py` (290 linhas)

| Evento Asaas | Service | Função |
|---|---|---|
| CUSTOMER_CREATED | customer_sync_service | sincronizar_cliente + bg |
| CUSTOMER_UPDATED | customer_sync_service | sincronizar_cliente |
| CUSTOMER_DELETED | customer_deletion_service | processar_cliente_deletado |
| SUBSCRIPTION_CREATED | contract_sync_service | sincronizar_contrato + bg |
| SUBSCRIPTION_UPDATED | contract_sync_service | sincronizar_contrato |
| SUBSCRIPTION_DELETED | contract_sync_service | processar_contrato_deletado |
| PAYMENT_CREATED | payment_sync_service | sincronizar_cobranca |
| PAYMENT_CONFIRMED | payment_confirmed_service | processar_pagamento_confirmado |
| PAYMENT_RECEIVED | payment_confirmed_service | processar_pagamento_recebido |
| PAYMENT_OVERDUE | payment_events_service | processar_pagamento_vencido |
| PAYMENT_REFUNDED | payment_events_service | processar_pagamento_estornado |
| ... (20+ eventos) | payment_events_service | ... |

**Manutenibilidade:** 8/10
- Roteamento centralizado em um único arquivo
- Logs consistentes com prefixo [WEBHOOK_HANDLER]
- Fácil de adicionar novos eventos

**Próximos passos para pagamentos.py:**
1. Remover funções duplicadas locais (aguarda testes em produção)
2. Extrair funções auxiliares (PDF extraction, etc.) ainda inline

---

## COMO CONTINUAR
Próxima ação: Testar webhook_handler em produção
Após validação: Remover funções locais duplicadas de pagamentos.py
Comando de validação: python3 -m py_compile apps/ia/app/webhooks/pagamentos.py

---

## INFRAESTRUTURA — Docker Swarm

### Arquitetura
- Manager-01 (5.161.179.122) — CPX31 160GB — Orquestrador + Traefik
- Worker-01 (178.156.166.133) — CPX11 40GB — Réplica lazaro-ia
- Worker-02 (178.156.182.255) — CPX11 40GB — Réplica lazaro-ia
- Worker-03 (178.156.183.235) — CPX11 40GB — Réplica lazaro-ia

### Serviços no Swarm
- lazaro_lazaro-ia: 3 réplicas distribuídas nos Workers
- Image: vitorzx/lazaro-ia:latest (Docker Hub)
- Porta: 3115 (ingress mode — load balancing automático)
- Redes: traefik-net, lazaro-net, network_public (overlay)

### Redis no Swarm
- Serviço: redis_redis (stack separado)
- Localização: Worker-03 (constraint)
- Persistência: AOF (--appendonly yes)
- Volume: redis_data
- Conexão: redis://redis_redis:6379/0 (via network_public)
- REDIS_URL sobrescrito no docker-stack.yml (não usar .env)
- Keys atuais: pausas de conversas (pause:{agent_id}:{phone})

### Como fazer deploy de nova versão
```bash
cd /var/www/lazaro-real
docker compose build lazaro-ia
docker tag lazaro-docker-lazaro-ia:latest vitorzx/lazaro-ia:latest
docker push vitorzx/lazaro-ia:latest
docker service update --image vitorzx/lazaro-ia:latest lazaro_lazaro-ia
docker service ps lazaro_lazaro-ia
```

### Como verificar saúde do Swarm
```bash
docker node ls
docker stack ps lazaro
curl http://localhost:3115/health
```

### SSH nos Workers
```bash
ssh -i ~/.ssh/id_swarm root@178.156.166.133  # Worker-01
ssh -i ~/.ssh/id_swarm root@178.156.182.255  # Worker-02
ssh -i ~/.ssh/id_swarm root@178.156.183.235  # Worker-03
```

### Arquivos importantes
- /var/www/lazaro-real/docker-stack.yml — configuração do Swarm
- /var/www/lazaro-real/docker-compose.traefik.yml — roteamento externo
- /var/www/lazaro-real/.env — variáveis de ambiente
