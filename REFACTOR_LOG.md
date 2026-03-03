# Lazaro-v2 Refactor Log

## Status Atual
**Fase**: 2 - Quebrar mensagens.py (EM PROGRESSO)
**Última Atualização**: 2026-03-03
**Responsável**: Claude Code
**Próximo Passo**: 2.8 - Extrair outgoing_message_handler.py

---

## Fase 2: Quebrar mensagens.py (EM PROGRESSO)

### Objetivo
- **mensagens.py original**: 4438 linhas
- **Meta**: Módulos de 200-400 linhas

### Checklist
- [x] 2.1 domain/messaging/models/message.py <- ExtractedMessage, ProcessingContext (42L)
- [x] 2.2 domain/messaging/context/context_detector.py <- get_context_prompt, detect_conversation_context, prepare_system_prompt (236L)
- [x] 2.3 domain/messaging/context/maintenance_context.py <- get_contract_data_for_maintenance, build_maintenance_context_prompt (177L)
- [x] 2.4 domain/messaging/context/billing_context.py <- get_billing_data_for_context, build_billing_context_prompt (328L)
- [x] 2.5 domain/messaging/handlers/incoming_message_handler.py <- extract_message_data, handle_control_command (231L)
- [x] 2.6 domain/messaging/services/message_processor.py <- schedule_processing, process_buffered_messages, prepare_gemini_messages (881L - NEEDS DECOMPOSITION)
- [x] 2.7 domain/messaging/services/conversation_manager.py <- _save_conversation_history (245L)
- [ ] 2.8 domain/messaging/handlers/outgoing_message_handler.py
- [ ] 2.9-2.14 ai/tools/* (scheduling, transfer, maintenance, billing, customer, registry)
- [ ] 2.15 domain/messaging/message_orchestrator.py (<200 linhas)
- [ ] 2.16 api/routes/webhook_whatsapp.py

### Módulos Extraídos
| Módulo | Linhas | Descrição |
|--------|--------|-----------|
| domain/messaging/models/message.py | 42 | ExtractedMessage, ProcessingContext |
| domain/messaging/context/context_detector.py | 236 | get_context_prompt, detect_conversation_context, prepare_system_prompt |
| domain/messaging/context/maintenance_context.py | 177 | get_contract_data_for_maintenance, build_maintenance_context_prompt |
| domain/messaging/context/billing_context.py | 328 | get_billing_data_for_context, build_billing_context_prompt |
| domain/messaging/handlers/incoming_message_handler.py | 231 | extract_message_data, handle_control_command |
| domain/messaging/services/message_processor.py | 881 | schedule_processing, process_buffered_messages, prepare_gemini_messages (NEEDS DECOMPOSITION) |
| domain/messaging/services/conversation_manager.py | 245 | ConversationManager, save_conversation_history |

---

## Fase 1: Quebrar main.py ✅ COMPLETA

### Resultado Final
- **main.py original**: 2068 linhas
- **main_refactored.py**: 51 linhas (97.5% redução) ✅ Meta 50-80 atingida

### Checklist
- [x] 1.1 core/config/app_state.py <- AppState
- [x] 1.2 domain/messaging/recovery.py <- recover_orphan_buffers, recover_failed_sends
- [x] 1.3 jobs/scheduler.py <- APScheduler config e jobs
- [x] 1.4 api/routes/webhooks.py <- webhooks dinâmicos
- [x] 1.5 api/routes/leadbox.py <- webhook Leadbox
- [x] 1.6 api/routes/uploads.py <- upload/list/delete
- [x] 1.7 api/routes/jobs_control.py <- endpoints jobs
- [x] 1.8 api/routes/maintenance_slots.py <- slots manutencao
- [x] 1.9 api/routes/leads_analysis.py <- reanalyze Observer
- [x] 1.10 api/routes/health.py <- health endpoints
- [x] 1.11 main_refactored.py <- main limpo
- [x] 1.12 api/services/lead_intake_service.py <- processamento leads (445L)
- [x] 1.13 api/handlers/leadbox_handler.py <- handlers leadbox (438L)
- [x] 1.14 api/routes/leadbox.py <- reduzido para 130L
- [x] 1.15 core/logging.py + core/lifespan.py + register_routes()

### Notas
- main_refactored.py criado mas NÃO substitui main.py ainda
- Precisa deploy/teste em produção antes da troca
- Todos os módulos passaram verificação de sintaxe
- leadbox.py quebrado em 3 módulos (handler + service + rota)

---

## Fase 0: Preparação ✅ COMPLETA

### Checklist
- [x] Criar REFACTOR_LOG.md
- [x] Remover arquivos .bak
- [x] Mover scripts one-time para scripts/
- [x] Criar estrutura de pastas vazia
- [x] Criar __init__.py em todas as pastas Python

---

## Histórico de Commits

| Data | Commit | Descrição |
|------|--------|-----------|
| 2026-03-03 | b092bb5 | refactor(fase-0.1): criar REFACTOR_LOG.md |
| 2026-03-03 | 75c0ae6 | refactor(fase-0.2): remover arquivos .bak |
| 2026-03-03 | d3d9262 | refactor(fase-0.3): mover scripts one-time |
| 2026-03-03 | 9071c8d | refactor(fase-0.4): criar estrutura pastas |
| 2026-03-03 | a54de0f | refactor(fase-0.5): marcar Fase 0 completa |
| 2026-03-03 | ec0bd05 | refactor(fase-1.1): AppState |
| 2026-03-03 | cd94d2d | refactor(fase-1.2): recovery |
| 2026-03-03 | c9c2900 | refactor(fase-1.3): scheduler |
| 2026-03-03 | e1b3da2 | refactor(fase-1.4): webhooks |
| 2026-03-03 | 928c823 | refactor(fase-1.5): leadbox (~760L) |
| 2026-03-03 | f2bb43d | refactor(fase-1.6-1.10): rotas restantes |
| 2026-03-03 | a126c4c | refactor(fase-1.11): main_refactored |
| 2026-03-03 | 38d5cfb | refactor(fase-1.12): lead_intake_service.py |
| 2026-03-03 | 033a2bd | refactor(fase-1.13): leadbox_handler.py |
| 2026-03-03 | afa7941 | refactor(fase-1.14): leadbox.py reduzido 130L |
| 2026-03-03 | 3409138 | refactor(fase-1.15): main_refactored.py 51L |
| 2026-03-03 | 3268430 | refactor(fase-2.1): ExtractedMessage, ProcessingContext |
| 2026-03-03 | feb1ce3 | refactor(fase-2.2): context_detector.py (236L) |
| 2026-03-03 | e3c3d6a | refactor(fase-2.3): maintenance_context.py (177L) |
| 2026-03-03 | 2ccf11a | refactor(fase-2.4): billing_context.py (328L) |
| 2026-03-03 | 8c38249 | refactor(fase-2.5): incoming_message_handler.py (231L) |
| 2026-03-03 | d78e8b3 | refactor(fase-2.6): message_processor.py (881L) |
| 2026-03-03 | 78d9b33 | refactor(fase-2.7): conversation_manager.py (245L) |

---

## Arquivos Críticos (Linhas Atuais)

| Arquivo | Linhas | Status |
|---------|--------|--------|
| main.py | 2068 → 51 | ✅ Fase 1 (97.5% redução) |
| mensagens.py | 4438 | Pendente (Fase 2) |
| pagamentos.py | 2983 | Pendente (Fase 3) |
| cobrar_clientes.py | 1839 | Pendente (Fase 4) |
| reengajar_leads.py | 1465 | Pendente (Fase 5) |
| asaas.handler.ts | 2401 | Pendente (Fase 6) |

---

## Módulos Extraídos na Fase 1

| Módulo | Linhas | Descrição |
|--------|--------|-----------|
| core/config/app_state.py | 25 | Classe AppState singleton |
| core/logging.py | 47 | Configuração de logging |
| core/lifespan.py | 75 | Startup/shutdown lifecycle |
| domain/messaging/recovery.py | 243 | Recovery de buffers e envios |
| jobs/scheduler.py | 137 | APScheduler configuração |
| api/routes/__init__.py | 79 | register_routes() centralizado |
| api/routes/webhooks.py | 73 | Webhooks dinâmicos |
| api/routes/leadbox.py | 130 | Rota Leadbox (orquestrador) |
| api/routes/uploads.py | 90 | Upload de arquivos |
| api/routes/jobs_control.py | 200 | Controle de jobs |
| api/routes/maintenance_slots.py | 90 | Slots manutenção |
| api/routes/leads_analysis.py | 190 | Observer batch |
| api/routes/health.py | 100 | Health checks |
| api/handlers/leadbox_handler.py | 438 | Handlers Leadbox |
| api/services/lead_intake_service.py | 445 | Processamento de leads |

**Total extraído**: ~2362 linhas em 15 módulos

---

## Próximos Passos
1. Testar main_refactored.py em staging/produção
2. Substituir main.py por main_refactored.py
3. Iniciar Fase 2 (Quebrar mensagens.py - 4438 linhas)
