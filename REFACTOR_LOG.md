# Lazaro-v2 Refactor Log

## Status Atual
**Fase**: 9 - Limpeza Final 🔄 EM ANDAMENTO
**Última Atualização**: 2026-03-05
**Responsável**: Claude Code
**Próximo Passo**: 9.6 - Inverter dependência tools/ ← ai/tools/

---

## Fase 9: Limpeza Final 🔄 EM ANDAMENTO

### Objetivo
Remover código duplicado, substituir monolitos pelos módulos refatorados, limpar pastas legadas.

### Checklist
- [x] 9.1 Substituir main.py por main_refactored.py (2068L → 51L)
- [x] 9.2 Converter services/athena/ em ponte → domain/analytics/
- [x] 9.3 Converter services/diana/ em ponte → domain/campaigns/
- [x] 9.4 Converter services/observer/ em ponte → domain/monitoring/
- [x] 9.5 Remover pasta production/ (cópia desnecessária)
- [ ] 9.6 Remover tools/ (usar ai/tools/) ⚠️ ADIADO - dependência invertida
- [x] 9.7 Mover utils/dias_uteis.py → core/utils/ + ponte
- [x] 9.8 Remover shared/ (não usada)
- [x] 9.9 Mover api/*.py → api/routes/ + pontes
- [ ] 9.10 Atualizar imports nos monolitos ⚠️ ADIADO (aguardando testes em produção)
- [x] 9.11 Quebrar api/agents/index.ts em route groups ✅ COMPLETO
- [x] 9.12 Criar repositórios Asaas (asaas_customers, asaas_contracts, asaas_payments)

### Concluído - 9.1 main.py substituído
| Arquivo | Antes | Depois |
|---------|-------|--------|
| main.py | 2068 linhas | 51 linhas (97.5% redução) |
| main_refactored.py | 51 linhas | removido (consolidado em main.py) |

### Concluído - 9.2, 9.3, 9.4 Pastas legadas convertidas em pontes
| Pasta Legada | Ponte Para | Arquivos Removidos |
|--------------|------------|-------------------|
| services/athena/ | domain/analytics/ | metrics.py, prompts.py, tools.py |
| services/diana/ | domain/campaigns/ | campaign_service.py, message_service.py, phone_formatter.py, types.py |
| services/observer/ | domain/monitoring/ | observer.py |

> As pastas legadas agora contêm apenas `__init__.py` com re-exports para compatibilidade.

### Concluído - 9.5 pasta production/ removida
- Removida pasta `/production/agente-ia/` com código duplicado e documentação antiga

### Adiado - 9.6 tools/ não pode ser removido
- `ai/tools/*.py` IMPORTA de `tools/*.py` (dependência invertida)
- Requer refatoração dos imports em ai/tools/ primeiro

### Concluído - 9.7 utils/dias_uteis.py movido
| Antes | Depois |
|-------|--------|
| utils/dias_uteis.py | core/utils/dias_uteis.py |
| — | utils/dias_uteis.py (ponte) |

### Concluído - 9.8 shared/ removido
- Pasta `shared/` removida (não era usada por nenhum módulo)
- `format_brl` já existe em `domain/billing/services/billing_formatter.py`

### Concluído - 9.9 api/*.py movidos para api/routes/
| Arquivo | Linhas | Novo Local |
|---------|--------|------------|
| api/athena.py | 1860 | api/routes/athena.py + ponte |
| api/agentes.py | 905 | api/routes/agentes.py + ponte |
| api/auth.py | 700 | api/routes/auth.py + ponte |
| api/dashboard.py | 679 | api/routes/dashboard.py + ponte |
| api/google_oauth.py | 550 | api/routes/google_oauth.py + ponte |
| api/diana.py | 228 | api/routes/diana.py + ponte |

> Pontes criadas em api/*.py para compatibilidade com imports existentes

### Concluído - 9.11 api/agents/index.ts quebrado ✅ COMPLETO
| Arquivo | Linhas | Descrição |
|---------|--------|-----------|
| index.ts | 92 | Orquestrador - importa e registra 9 route groups em paralelo |
| crud.routes.ts | 191 | CRUD de agentes (create, get, update, delete, list, statuses) |
| connection.routes.ts | 198 | QR Code, webhook config, Evolution, UAZAPI |
| dashboard.routes.ts | 175 | Dashboard stats, Asaas, Maintenance, Agent Metrics |
| leads.routes.ts | 260 | Leads API, Conversations, Toggle AI, Special Agents |
| user-settings.routes.ts | 195 | User configuration (logo, company name) |
| google-calendar.routes.ts | 90 | Google Calendar OAuth |
| billing-audit.routes.ts | 240 | Billing, Audit Logs, Interventions, Integrations |
| learning.routes.ts | 145 | Learning Entries (AI curation) |
| messages-media.routes.ts | 105 | Messages, Media, Avatar |
| index.legacy.ts | 190 | Rotas restantes (status, stats, schedules) |

**Resultado**: 1790 linhas → 11 arquivos modulares (~1880 linhas total, mas organizados)
**Redução do monolito**: index.legacy.ts de 1790L para 190L (89% redução)

### Concluído - 9.12 Repositórios Asaas criados
| Repositório | Linhas | Descrição |
|-------------|--------|-----------|
| asaas_customers.py | ~270 | AsaasCustomersRepository (upsert, find, cache, soft delete) |
| asaas_contracts.py | ~280 | AsaasContractsRepository (upsert, find by customer/agent, soft delete) |
| asaas_payments.py | ~420 | AsaasPaymentsRepository (upsert, find overdue/pending, recalculate days) |

> Centraliza queries Asaas em repositories seguindo o padrão existente (BaseRepository).
> Substituem queries inline em domain/billing/services/*.py.

### Adiado - 9.10 Integração nos monolitos
**Decisão**: Manter código duplicado até testes em produção

**Código duplicado identificado em mensagens.py (~700 linhas)**:
- `get_context_prompt` → `domain/messaging/context/context_detector.py`
- `detect_conversation_context` → `domain/messaging/context/context_detector.py`
- `prepare_system_prompt` → `domain/messaging/context/context_detector.py`
- `get_contract_data_for_maintenance` → `domain/messaging/context/maintenance_context.py`
- `build_maintenance_context_prompt` → `domain/messaging/context/maintenance_context.py`
- `get_billing_data_for_context` → `domain/messaging/context/billing_context.py`
- `build_billing_context_prompt` → `domain/messaging/context/billing_context.py`

**Próximos passos para integração (quando for seguro)**:
1. Adicionar imports de `app.domain.messaging.context` no topo de mensagens.py
2. Remover implementações locais duplicadas
3. Testar em staging antes de produção

---

## Fase 8: Organizar Domínios Restantes ✅ COMPLETA

### Objetivo
Mover módulos existentes de services/ para domain/ seguindo DDD.
Organizar Athena, Diana, Observer, Scheduling e Maintenance.

### Checklist
- [x] 8.1 domain/analytics/services/ <- services/athena/ (1328L)
- [x] 8.2 domain/campaigns/services/ <- services/diana/ (1761L)
- [x] 8.3 domain/monitoring/services/ <- services/observer/ (619L)
- [x] 8.4 domain/scheduling/services/ <- ai/tools/scheduling_tools.py (607L)
- [x] 8.5 domain/maintenance/services/ <- tools/manutencao.py + services/manutencao_slots.py (1114L)

### Módulos Extraídos - Fase 8.1 (Athena → domain/analytics)
| Módulo | Linhas | Descrição |
|--------|--------|-----------|
| domain/analytics/services/metrics.py | 631 | BusinessMetrics, calculate_business_metrics, cache |
| domain/analytics/services/prompts.py | 306 | SECTOR_BENCHMARKS, BUSINESS_GLOSSARY, build_system_prompt |
| domain/analytics/services/tools.py | 296 | get_business_health, ATHENA_BUSINESS_TOOLS |
| domain/analytics/services/__init__.py | 49 | Re-exports |
| domain/analytics/__init__.py | 46 | Barrel file |

### Módulos Extraídos - Fase 8.2 (Diana → domain/campaigns)
| Módulo | Linhas | Descrição |
|--------|--------|-----------|
| domain/campaigns/services/campaign_service.py | 849 | DianaCampaignService (CSV, disparo, stats) |
| domain/campaigns/services/message_service.py | 435 | DianaMessageService (UAZAPI + Gemini) |
| domain/campaigns/services/types.py | 208 | DianaStatus, DianaProspect, DianaCampanha |
| domain/campaigns/services/phone_formatter.py | 184 | format_phone, format_to_remotejid |
| domain/campaigns/services/__init__.py | 43 | Re-exports |
| domain/campaigns/__init__.py | 42 | Barrel file |

### Módulos Extraídos - Fase 8.3 (Observer → domain/monitoring)
| Módulo | Linhas | Descrição |
|--------|--------|-----------|
| domain/monitoring/services/observer.py | 593 | ObserverService, analyze_conversation, constantes |
| domain/monitoring/services/__init__.py | 26 | Re-exports |
| domain/monitoring/__init__.py | 26 | Barrel file |

### Módulos Extraídos - Fase 8.4 (SchedulingTools → domain/scheduling)
| Módulo | Linhas | Descrição |
|--------|--------|-----------|
| domain/scheduling/services/scheduling_tools.py | 589 | SchedulingTools (consulta_agenda, agendar, cancelar, reagendar) |
| domain/scheduling/services/__init__.py | 18 | Re-exports |
| domain/scheduling/__init__.py | 18 | Barrel file |

### Módulos Extraídos - Fase 8.5 (Maintenance → domain/maintenance)
| Módulo | Linhas | Descrição |
|--------|--------|-----------|
| domain/maintenance/services/slots_service.py | 293 | verificar_slot, listar_slots, registrar_agendamento |
| domain/maintenance/services/equipment_tools.py | 771 | identificar_equipamento, analisar_foto, verificar/confirmar |
| domain/maintenance/services/__init__.py | 50 | Re-exports |
| domain/maintenance/__init__.py | 40 | Barrel file |

### Resumo Fase 8
- **Total de domínios organizados**: 5
- **Total de linhas extraídas**: ~5429 linhas
- **Arquitetura**: DDD com domain/services/ + barrel files
- **Padrão**: Copy-first (originais preservados para integração futura)

---

## Fase 7: Extrair Integrações Compartilhadas ✅ COMPLETA

### Objetivo
Extrair integrações duplicadas (Python + TypeScript) para módulos reutilizáveis.
Usar a implementação mais madura como base.

### Checklist
- [x] 7.1 integrations/asaas/ <- AsaasClient + types + rate_limiter (1271L)
- [x] 7.2 integrations/uazapi/ <- UazapiClient + types (1660L)
- [x] 7.3 integrations/calendar/ <- GoogleCalendarClient + MultiCalendarClient (2026L)
- [x] 7.4 integrations/supabase/ <- SupabaseClient + repositories (2445L)
- [x] 7.5 integrations/leadbox/ <- LeadboxClient + Dispatcher + types (1599L)
- [x] 7.6 integrations/redis/ <- RedisClient + Buffer + Lock + Pause + Cache (1716L)

### Módulos Extraídos - Fase 7.1 (Asaas)
| Módulo | Linhas | Descrição |
|--------|--------|-----------|
| integrations/asaas/types.py | 471 | Enums, TypedDicts, constantes (baseado no TS) |
| integrations/asaas/rate_limiter.py | 122 | Rate limiter 30 req/min (portado do TS) |
| integrations/asaas/client.py | 527 | AsaasClient com rate limiting + retry |
| integrations/asaas/__init__.py | 139 | Barrel file com re-exports |

### Módulos Extraídos - Fase 7.2 (UAZAPI)
| Módulo | Linhas | Descrição |
|--------|--------|-----------|
| integrations/uazapi/types.py | 506 | Enums, TypedDicts (webhook, campanhas, payloads) |
| integrations/uazapi/client.py | 999 | UazapiClient com retry + chunking + typing indicator |
| integrations/uazapi/__init__.py | 155 | Barrel file com re-exports |

### Módulos Extraídos - Fase 7.3 (Google Calendar)
| Módulo | Linhas | Descrição |
|--------|--------|-----------|
| integrations/calendar/types.py | 583 | Tipos, enums, dataclasses, helpers (baseado no TS) |
| integrations/calendar/client.py | 631 | GoogleCalendarClient OAuth2 + disponibilidade + Meet |
| integrations/calendar/multi_calendar.py | 592 | MultiCalendarClient com prioridade e cenários |
| integrations/calendar/__init__.py | 220 | Barrel file com re-exports |

### Módulos Extraídos - Fase 7.4 (Supabase)
| Módulo | Linhas | Descrição |
|--------|--------|-----------|
| integrations/supabase/types.py | 615 | Enums, TypedDicts (Agent, Lead, Message, etc) |
| integrations/supabase/client.py | 212 | SupabaseClient singleton + helpers |
| integrations/supabase/repositories/base.py | 243 | BaseRepository com CRUD genérico |
| integrations/supabase/repositories/agents.py | 388 | AgentsRepository (tabela agents) |
| integrations/supabase/repositories/dynamic.py | 730 | DynamicRepository (tabelas dinâmicas) |
| integrations/supabase/repositories/__init__.py | 38 | Re-exports |
| integrations/supabase/__init__.py | 219 | Barrel file principal |

### Módulos Extraídos - Fase 7.5 (Leadbox)
| Módulo | Linhas | Descrição |
|--------|--------|-----------|
| integrations/leadbox/types.py | 334 | Enums (TicketStatus, WebhookEvent), TypedDicts, helpers |
| integrations/leadbox/client.py | 656 | LeadboxClient HTTP completo (transfer, message, query) |
| integrations/leadbox/dispatch.py | 440 | LeadboxDispatcher (dispatch inteligente ticket) |
| integrations/leadbox/__init__.py | 169 | Barrel file com re-exports |

### Módulos Extraídos - Fase 7.6 (Redis)
| Módulo | Linhas | Descrição |
|--------|--------|-----------|
| integrations/redis/types.py | 162 | Constantes, TypedDicts, RedisConfig, key generators |
| integrations/redis/client.py | 255 | RedisClient conexão + health check + low-level ops |
| integrations/redis/buffer.py | 271 | BufferService (add, get, clear, get_and_clear, orphans) |
| integrations/redis/lock.py | 226 | LockService distribuído (acquire, release, with_lock) |
| integrations/redis/pause.py | 176 | PauseService controle de pausa do bot |
| integrations/redis/cache.py | 239 | CacheService genérico com JSON auto-serialize |
| integrations/redis/__init__.py | 387 | RedisService facade + re-exports |

### Resumo Fase 7
- **Total de integrações extraídas**: 6
- **Total de linhas extraídas**: ~12717 linhas
- **Arquitetura**: Cada integração com types + client + services + barrel
- **Padrão**: Factory functions + singleton + facade para compatibilidade

### Análise de Maturidade
| Integração | Python | TypeScript | Vencedor | Motivo |
|------------|--------|------------|----------|--------|
| **Asaas** | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | **TS** | Rate limiter robusto + retry exponencial |
| **UAZAPI** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | **EMPATE** | Ambos completos |
| **Calendar** | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | **TS** | Multi-calendar support |
| **Supabase** | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | **TS** | Repository pattern |
| **Leadbox** | ⭐⭐⭐⭐ | ⭐⭐ | **Python** | Só Python tem cliente HTTP |
| **Redis** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | **TS** | Separação de concerns |

---

## Fase 6: Quebrar asaas.handler.ts ✅ COMPLETA

### Objetivo
- **asaas.handler.ts original**: 2401 linhas
- **Meta**: Módulos TypeScript por domínio

### Checklist
- [x] 6.1 api/dashboard/asaas/dashboard.handler.ts <- getAsaasDashboardHandler (629L)
- [x] 6.2 api/dashboard/asaas/contract-parser.handler.ts <- parseContractHandler, parseAllContractsHandler, mergeContractData, extractWithGemini, parseContractInternal (857L)
- [x] 6.3 api/dashboard/asaas/sync.handler.ts <- syncAllAsaasHandler, calcDiasAtraso, upsertInBatches, markDeletedRecords (637L)
- [x] 6.4 api/dashboard/asaas/customers.handler.ts <- getAsaasCustomersHandler, getAsaasParcelamentosHandler, getAsaasAvailableMonthsHandler (288L)
- [x] 6.5 api/dashboard/asaas/index.ts <- barrel file re-exports (33L)

### Módulos Extraídos
| Módulo | Linhas | Descrição |
|--------|--------|-----------|
| api/dashboard/asaas/dashboard.handler.ts | 629 | getAsaasDashboardHandler (dashboard principal) |
| api/dashboard/asaas/contract-parser.handler.ts | 857 | Parsing de PDFs + Gemini extraction |
| api/dashboard/asaas/sync.handler.ts | 637 | syncAllAsaasHandler + helpers |
| api/dashboard/asaas/customers.handler.ts | 288 | Handlers de clientes e parcelamentos |
| api/dashboard/asaas/index.ts | 33 | Barrel file (re-exports) |

### Resumo Fase 6
- **Total de módulos extraídos**: 5
- **Total de linhas extraídas**: ~2444 linhas
- **asaas.handler.ts original**: 2401 linhas (não modificado - estratégia de extração)
- **Próximo**: Atualizar imports em agents/index.ts para usar os novos módulos

---

## Fase 5: Quebrar reengajar_leads.py ✅ COMPLETA

### Objetivo
- **reengajar_leads.py original**: 1466 linhas
- **Meta**: Módulos de 200-400 linhas

### Checklist
- [x] 5.1 domain/leads/services/opt_out_detector.py <- OPT_OUT_PATTERNS, detect_opt_out (49L)
- [x] 5.2 domain/leads/services/salvador_config.py <- FALLBACK_*, DEFAULT_*, get_salvador_config, is_within_schedule (209L)
- [x] 5.3 domain/leads/services/follow_up_eligibility.py <- get_agents_with_follow_up, get_eligible_leads (282L)
- [x] 5.4 domain/leads/services/follow_up_throttle.py <- can_send_follow_up, record_follow_up, clear_lead_cooldown (125L)
- [x] 5.5 domain/leads/services/lead_classifier.py <- load_conversation_history, classify_lead_for_follow_up (231L)
- [x] 5.6 domain/leads/services/follow_up_message_generator.py <- generate_follow_up_message (136L)
- [x] 5.7 domain/leads/services/follow_up_recorder.py <- record_*, log_*, update_*, save_* (213L)
- [x] 5.8 domain/leads/services/follow_up_reset.py <- reset_follow_up_on_lead_response (112L)
- [x] 5.9 jobs/follow_up_job.py <- run_follow_up_job, force_run_follow_up (386L)

### Módulos Extraídos
| Módulo | Linhas | Descrição |
|--------|--------|-----------|
| domain/leads/services/opt_out_detector.py | 49 | OPT_OUT_PATTERNS, detect_opt_out |
| domain/leads/services/salvador_config.py | 209 | FALLBACK_MESSAGES, DEFAULT_*, get_salvador_config, is_within_schedule |
| domain/leads/services/follow_up_eligibility.py | 282 | resolve_shared_whatsapp, get_agents_with_follow_up, get_eligible_leads |
| domain/leads/services/follow_up_throttle.py | 125 | Redis rate limiting: can_send_follow_up, record_follow_up |
| domain/leads/services/lead_classifier.py | 231 | load_conversation_history, classify_lead_for_follow_up (Gemini) |
| domain/leads/services/follow_up_message_generator.py | 136 | generate_follow_up_message (Gemini) |
| domain/leads/services/follow_up_recorder.py | 213 | record_follow_up_notification, log_follow_up_history, update_lead_follow_up |
| domain/leads/services/follow_up_reset.py | 112 | reset_follow_up_on_lead_response (importado por mensagens.py) |
| jobs/follow_up_job.py | 386 | run_follow_up_job, is_follow_up_running, force_run_follow_up |

### Resumo Fase 5
- **Total de módulos extraídos**: 9
- **Total de linhas extraídas**: ~1743 linhas
- **reengajar_leads.py original**: 1466 linhas (não modificado - estratégia de extração)
- **Próximo**: Integração futura após testes em produção

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
| 2026-03-03 | b106582 | refactor(fase-5.1): opt_out_detector.py (49L) |
| 2026-03-03 | 1997a22 | refactor(fase-5.2): salvador_config.py (209L) |
| 2026-03-03 | 10b5184 | refactor(fase-5.3): follow_up_eligibility.py (282L) |
| 2026-03-03 | b390fda | refactor(fase-5.4): follow_up_throttle.py (125L) |
| 2026-03-03 | 582a844 | refactor(fase-5.5): lead_classifier.py (231L) |
| 2026-03-03 | 4db9b4f | refactor(fase-5.6): follow_up_message_generator.py (136L) |
| 2026-03-03 | cbf4e1c | refactor(fase-5.7): follow_up_recorder.py (213L) |
| 2026-03-03 | 167b0eb | refactor(fase-5.8): follow_up_reset.py (112L) |
| 2026-03-03 | c3ca41a | refactor(fase-5.9): follow_up_job.py (386L) |
| 2026-03-03 | d58350a | refactor(fase-6.1): dashboard.handler.ts (629L) |
| 2026-03-03 | 25cdd9e | refactor(fase-6.2): contract-parser.handler.ts (857L) |
| 2026-03-03 | 0b2c3aa | refactor(fase-6.3): sync.handler.ts (637L) |
| 2026-03-03 | c81c960 | refactor(fase-6.4): customers.handler.ts (288L) |
| 2026-03-03 | c2bbdba | refactor(fase-6.5): index.ts (barrel file) |
| 2026-03-03 | 88d58a3 | refactor(fase-7.1): integrations/asaas/ (1271L) |
| 2026-03-03 | 57c012c | refactor(fase-7.2): integrations/uazapi/ (1660L) |
| 2026-03-03 | d3b93a5 | refactor(fase-7.3): integrations/calendar/ (2026L) |
| 2026-03-03 | 6f1c1c0 | refactor(fase-7.4): integrations/supabase/ (2445L) |
| 2026-03-03 | 24b3e64 | refactor(fase-7.5): integrations/leadbox/ (1599L) |
| 2026-03-03 | caff4e3 | refactor(fase-7.6): integrations/redis/ (1716L) |
| 2026-03-03 | fde7cb0 | refactor(fase-8.1): domain/analytics/services/ (1328L) |
| 2026-03-03 | 9143eb8 | refactor(fase-8.2): domain/campaigns/services/ (1761L) |
| 2026-03-03 | 064dce3 | refactor(fase-8.3): domain/monitoring/services/ (619L) |
| 2026-03-03 | 33a525f | refactor(fase-8.4): domain/scheduling/services/ (607L) |
| 2026-03-03 | d69e79f | refactor(fase-8.5): domain/maintenance/services/ (1114L) |

---

## Arquivos Críticos (Linhas Atuais)

| Arquivo | Linhas | Status |
|---------|--------|--------|
| main.py | 2068 → 51 | ✅ Fase 1 (97.5% redução) |
| mensagens.py | 4438 | ✅ Fase 2 (16 módulos extraídos, integração pendente) |
| pagamentos.py | 2984 | ✅ Fase 3 (10 módulos extraídos, integração pendente) |
| cobrar_clientes.py | 1840 | ✅ Fase 4 (8 módulos extraídos, integração pendente) |
| reengajar_leads.py | 1466 | ✅ Fase 5 (9 módulos extraídos, integração pendente) |
| asaas.handler.ts | 2401 → 5 módulos | ✅ Fase 6 (5 módulos extraídos, integração pendente) |

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
6. ✅ Fase 5 completa - 9 módulos extraídos de reengajar_leads.py
7. Integrar módulos extraídos nos monolitos (após testes em produção)
8. ✅ Fase 6 completa - 5 módulos extraídos de asaas.handler.ts
9. Atualizar imports em agents/index.ts para usar novos módulos
10. Iniciar Fase 7 (Extrair integrações compartilhadas)
