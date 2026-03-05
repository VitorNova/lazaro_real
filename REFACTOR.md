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

### FASE 5 — Segurança ⏳ (iniciada)
- [x] Criar core/security/injection_guard.py
- [x] Integrar injection_guard em webhooks/mensagens.py (antes do Gemini)
- [ ] Validação Pydantic nos webhooks

## PROBLEMA ABERTO
1.3 BLOQUEADO: ai/tools/ importa de tools/ — dependência invertida.
Solução necessária: inverter a dependência fazendo tools/ importar de ai/tools/ ou eliminar tools/.

## COMMITS FEITOS
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

## MAPEAMENTO: mensagens.py (4414 linhas)

### Métodos da classe WhatsAppWebhookHandler

| Método | Linhas | Tamanho | Status Domain/ |
|--------|--------|---------|----------------|
| `__init__` | 844-863 | 19 | - |
| `_extract_message_data` | 865-1013 | 148 | ⏳ Extrair → `domain/messaging/services/` |
| `_handle_control_command` | 1015-1177 | 162 | ⏳ Extrair → `domain/messaging/handlers/` |
| `_schedule_processing` | 1179-? | ~50 | ✅ Stub em `message_processor.py` |
| `_process_buffered_messages` | ?-1917 | 738 | ✅ Stub em `message_processor.py` |
| `_prepare_gemini_messages` | 1919-1955 | 36 | ✅ Stub em `message_processor.py` |
| `_save_conversation_history` | 1957-2132 | 175 | ✅ Em `conversation_manager.py` |
| `_create_function_handlers` | 2134-3492 | 1358 | ✅ INTEGRADO → `ai/tools/tool_registry.py` |
| `handle_message` | 3498-4277 | 779 | ⏳ Stub incompleto em `message_orchestrator.py` |

### Funções standalone duplicadas

| Função | Linhas | Status |
|--------|--------|--------|
| `get_context_prompt` | 65-129 | ✅ Duplicada (usar `context_detector.py`) |
| `detect_conversation_context` | 136-219 | ✅ Duplicada (usar `context_detector.py`) |
| `get_contract_data_for_maintenance` | 221-303 | ✅ Duplicada (usar `maintenance_context.py`) |
| `build_maintenance_context_prompt` | 305-384 | ✅ Duplicada (usar `maintenance_context.py`) |
| `get_billing_data_for_context` | 386-430 | ✅ Duplicada (usar `billing_context.py`) |
| `build_billing_context_prompt` | 432-503 | ✅ Duplicada (usar `billing_context.py`) |
| `prepare_system_prompt` | var | ✅ Duplicada (usar `context_detector.py`) |

### Problema principal
`_create_function_handlers` com 1358 linhas contém ALL function handlers do Gemini inline.
Deve ser movido para `ai/tools/handlers.py` como módulo independente.

### Plano de Extração (ordem de prioridade)

1. **Fase A**: ✅ COMPLETO — `_create_function_handlers` → `ai/tools/tool_registry.py`
   - Import: `from app.ai.tools.tool_registry import get_function_handlers`
   - Uso: `handlers = get_function_handlers(supabase, context)`
   - Método inline (1360 linhas) **REMOVIDO** de mensagens.py
   - Commits: f9bf97a (integração), 398632c (remoção inline)
2. **Fase B**: ✅ ALINHADO — `message_processor.py` atualizado para usar `get_function_handlers`
   - Removido parâmetro `create_handlers_callback`
   - Usa `get_function_handlers(supabase, context)` diretamente
   - Commit: e3559fb
   - Pendente: Integrar em `mensagens.py` (substituir `_process_buffered_messages`)
3. **Fase C**: Completar `message_orchestrator.py` com lógica real de `handle_message`
4. **Fase D**: Integrar módulos e testar em produção
5. **Fase E**: Remover código duplicado de `mensagens.py` (inclui `_create_function_handlers`)

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

## COMO CONTINUAR
Próxima ação: Fase 4 — Logging Unificado ou Fase 5 — Segurança
Comando de validação após cada mudança: python3 -m py_compile apps/ia/app/main.py
