# Lazaro-v2 Refactor Log

## Status Atual
**Fase**: 4 - Quebrar cobrar_clientes.py ✅ COMPLETA
**Última Atualização**: 2026-03-03
**Responsável**: Claude Code
**Próximo Passo**: Fase 5 - Quebrar reengajar_leads.py

---

## Fase 4: Quebrar cobrar_clientes.py ✅ COMPLETA

### Objetivo
- **cobrar_clientes.py original**: 1840 linhas
- **Meta**: Módulos de 200-400 linhas

### Checklist
- [x] 4.1 domain/billing/models/billing_config.py <- constantes, templates, config (96L)
- [x] 4.2 domain/billing/services/payment_fetcher.py <- fetch_*, enrich_*, sync_cache (541L)
- [x] 4.3 domain/billing/services/billing_formatter.py <- format_*, get_*_template (155L)
- [x] 4.4 domain/billing/services/billing_notifier.py <- claim, save, update, DLQ (268L)
- [x] 4.5 domain/billing/services/lead_ensurer.py <- ensure_lead, ensure_message, save_history (299L)
- [x] 4.6 domain/billing/services/billing_rules.py <- should_skip, get_agents_with_asaas (103L)
- [x] 4.7 core/utils/phone.py <- mask_*, get_customer_phone, phone_to_remotejid (134L)
- [x] 4.8 jobs/billing_job.py <- process_agent_billing, entry points (614L)

### Módulos Extraídos
| Módulo | Linhas | Descrição |
|--------|--------|-----------|
| domain/billing/models/billing_config.py | 96 | BILLING_JOB_LOCK_*, PAID_STATUSES, DEFAULT_MESSAGES |
| domain/billing/services/payment_fetcher.py | 541 | fetch_payments_from_asaas, fallback, sync_cache, enrich |
| domain/billing/services/billing_formatter.py | 155 | format_brl, format_message, get_overdue_template |
| domain/billing/services/billing_notifier.py | 268 | claim_notification, save_cobranca, DLQ, get_sent_count |
| domain/billing/services/lead_ensurer.py | 299 | ensure_lead_exists, ensure_message, save_conversation_history |
| domain/billing/services/billing_rules.py | 103 | should_skip_payment, get_agents_with_asaas |
| core/utils/phone.py | 134 | mask_phone, mask_customer_name, get_customer_phone |
| jobs/billing_job.py | 614 | process_agent_billing (3 fases), entry points |

### Resumo Fase 4
- **Total de módulos extraídos**: 8
- **Total de linhas extraídas**: ~2210 linhas
- **cobrar_clientes.py original**: 1840 linhas (não modificado - estratégia de extração)
- **Próximo**: Integração futura após testes em produção

---

## Fase 3: Quebrar pagamentos.py ✅ COMPLETA

### Objetivo
- **pagamentos.py original**: 2984 linhas
- **Meta**: Módulos de 200-400 linhas

### Checklist
- [x] 3.1 domain/billing/models/payment.py <- constantes, TypedDicts (57L)
- [x] 3.2 core/utils/retry.py <- async_retry decorator (52L)
- [x] 3.3 domain/billing/services/customer_sync_service.py <- sincronizar_cliente, match_lead, cache, resolve_name (412L)
- [x] 3.4 domain/billing/services/contract_sync_service.py <- sincronizar_contrato, processar_contrato_deletado (233L)
- [x] 3.5 domain/billing/services/customer_deletion_service.py <- processar_cliente_deletado (79L)
- [x] 3.6 domain/billing/services/payment_sync_service.py <- sincronizar_cobranca, processar_cobranca_deletada (269L)
- [x] 3.7 domain/billing/services/contract_extraction_service.py <- PDF/Gemini extraction (798L)
- [x] 3.8 domain/billing/services/payment_confirmed_service.py <- CONFIRMED, RECEIVED, lead update (380L)
- [x] 3.9 domain/billing/services/payment_events_service.py <- OVERDUE, estornos, chargebacks (308L)
- [x] 3.10 api/routes/webhook_asaas.py <- rotas FastAPI + roteador de eventos (425L)

### Módulos Extraídos
| Módulo | Linhas | Descrição |
|--------|--------|-----------|
| domain/billing/models/payment.py | 57 | LAZARO_AGENT_ID, SUPPORTED_EXTENSIONS, MIME_TYPES, TypedDicts |
| core/utils/retry.py | 52 | async_retry com backoff exponencial |
| domain/billing/services/customer_sync_service.py | 412 | sincronizar_cliente, match_lead_to_customer, get_cached_customer, resolve_customer_name |
| domain/billing/services/contract_sync_service.py | 233 | sincronizar_contrato, processar_contrato_deletado |
| domain/billing/services/customer_deletion_service.py | 79 | processar_cliente_deletado (soft delete em cascata) |
| domain/billing/services/payment_sync_service.py | 269 | sincronizar_cobranca, processar_cobranca_deletada |
| domain/billing/services/contract_extraction_service.py | 798 | processar_customer/subscription_created_background, extract PDF/image, Gemini |
| domain/billing/services/payment_confirmed_service.py | 380 | processar_pagamento_confirmado/recebido, atualizar_lead_pagamento |
| domain/billing/services/payment_events_service.py | 308 | processar_pagamento_vencido/estornado/chargeback/restaurado/etc |
| api/routes/webhook_asaas.py | 425 | asaas_webhook, reprocess_contract, _processar_evento |

### Resumo Fase 3
- **Total de módulos extraídos**: 10
- **Total de linhas extraídas**: ~3013 linhas
- **pagamentos.py original**: 2984 linhas (não modificado - estratégia de extração)
- **Próximo**: Integração futura após testes em produção

---

## Fase 2: Quebrar mensagens.py ✅ COMPLETA

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
- [x] 2.8 domain/messaging/handlers/outgoing_message_handler.py <- _split_response, _queue_failed_send (251L)
- [x] 2.9 ai/tools/scheduling_tools.py <- consulta_agenda, agendar, cancelar, reagendar (589L)
- [x] 2.10 ai/tools/transfer_tools.py <- transferir_departamento, detectar_fuso (603L)
- [x] 2.11 ai/tools/maintenance_tools.py <- identificar_equip, analisar_foto, verificar_disp, confirmar_agend (230L)
- [x] 2.12 ai/tools/billing_tools.py <- buscar_cobrancas, consultar_cliente (380L)
- [x] 2.13 ai/tools/customer_tools.py <- salvar_dados_lead (195L)
- [x] 2.14 ai/tools/tool_registry.py <- ToolRegistry, get_function_handlers (159L)
- [x] 2.15 domain/messaging/message_orchestrator.py <- MessageOrchestrator (362L)
- [x] 2.16 api/routes/webhook_whatsapp.py <- rotas FastAPI webhook (157L)

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
| domain/messaging/handlers/outgoing_message_handler.py | 251 | OutgoingMessageHandler, split_response, queue_failed_send |
| ai/tools/scheduling_tools.py | 589 | SchedulingTools: consulta_agenda, agendar, cancelar, reagendar |
| ai/tools/transfer_tools.py | 603 | TransferTools: transferir_departamento, detectar_fuso_horario |
| ai/tools/maintenance_tools.py | 230 | MaintenanceTools: identificar_equip, analisar_foto, verificar_disp, confirmar_agend |
| ai/tools/billing_tools.py | 380 | BillingTools: buscar_cobrancas, consultar_cliente |
| ai/tools/customer_tools.py | 195 | CustomerTools: salvar_dados_lead |
| ai/tools/tool_registry.py | 159 | ToolRegistry: factory centralizada de tools |
| domain/messaging/message_orchestrator.py | 362 | MessageOrchestrator: orquestrador principal |
| api/routes/webhook_whatsapp.py | 157 | Rotas FastAPI webhook WhatsApp |

### Resumo Fase 2
- **Total de módulos extraídos**: 16
- **Total de linhas extraídas**: ~5066 linhas
- **mensagens.py original**: 4438 linhas (não modificado - estratégia de extração)
- **Próximo**: Integração futura após testes em produção

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
| 2026-03-03 | dfbcc29 | refactor(fase-2.8): outgoing_message_handler.py (251L) |
| 2026-03-03 | 6a93a81 | refactor(fase-2.9): scheduling_tools.py (589L) |
| 2026-03-03 | 8520195 | refactor(fase-2.10): transfer_tools.py (603L) |
| 2026-03-03 | 9361810 | refactor(fase-2.11): maintenance_tools.py (230L) |
| 2026-03-03 | c46c5d0 | refactor(fase-2.12): billing_tools.py (380L) |
| 2026-03-03 | a365afc | refactor(fase-2.13): customer_tools.py (195L) |
| 2026-03-03 | aa4cd73 | refactor(fase-2.14): tool_registry.py (159L) |
| 2026-03-03 | 90bc86b | refactor(fase-2.15): message_orchestrator.py (362L) |
| 2026-03-03 | 4637a6c | refactor(fase-2.16): webhook_whatsapp.py (157L) |
| 2026-03-03 | 3553d31 | refactor(fase-3.1): payment.py (57L) |
| 2026-03-03 | ae889d5 | refactor(fase-3.2): retry.py (52L) |
| 2026-03-03 | 67b18de | refactor(fase-3.3): customer_sync_service.py (412L) |
| 2026-03-03 | e9d603b | refactor(fase-3.4): contract_sync_service.py (233L) |
| 2026-03-03 | 4ae1f09 | refactor(fase-3.5): customer_deletion_service.py (79L) |
| 2026-03-03 | 8e4e1f1 | refactor(fase-3.6): payment_sync_service.py (269L) |
| 2026-03-03 | f5195a7 | refactor(fase-3.7): contract_extraction_service.py (798L) |
| 2026-03-03 | c94cf99 | refactor(fase-3.8): payment_confirmed_service.py (380L) |
| 2026-03-03 | 2015085 | refactor(fase-3.9): payment_events_service.py (308L) |
| 2026-03-03 | 658f79b | refactor(fase-3.10): webhook_asaas.py (425L) |
| 2026-03-03 | 9f99454 | refactor(fase-4.1): billing_config.py (96L) |
| 2026-03-03 | d606542 | refactor(fase-4.2): payment_fetcher.py (541L) |
| 2026-03-03 | 579d7a1 | refactor(fase-4.3): billing_formatter.py (155L) |
| 2026-03-03 | e482c6a | refactor(fase-4.4): billing_notifier.py (268L) |
| 2026-03-03 | 6f5347e | refactor(fase-4.5): lead_ensurer.py (299L) |
| 2026-03-03 | 7d75411 | refactor(fase-4.6): billing_rules.py (103L) |
| 2026-03-03 | 3597cfb | refactor(fase-4.7): phone.py (134L) |
| 2026-03-03 | 128d95d | refactor(fase-4.8): billing_job.py (614L) |

---

## Arquivos Críticos (Linhas Atuais)

| Arquivo | Linhas | Status |
|---------|--------|--------|
| main.py | 2068 → 51 | ✅ Fase 1 (97.5% redução) |
| mensagens.py | 4438 | ✅ Fase 2 (16 módulos extraídos, integração pendente) |
| pagamentos.py | 2984 | ✅ Fase 3 (10 módulos extraídos, integração pendente) |
| cobrar_clientes.py | 1840 | ✅ Fase 4 (8 módulos extraídos, integração pendente) |
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
3. ✅ Fase 2 completa - 16 módulos extraídos de mensagens.py
4. ✅ Fase 3 completa - 10 módulos extraídos de pagamentos.py
5. ✅ Fase 4 completa - 8 módulos extraídos de cobrar_clientes.py
6. Integrar módulos extraídos nos monolitos (após testes em produção)
7. Iniciar Fase 5 (Quebrar reengajar_leads.py - 1465 linhas)
