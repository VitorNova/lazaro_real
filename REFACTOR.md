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
- [x] notificar_manutencoes.py → domain/maintenance/services/notification_service.py
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

### FASE 4 — Logging Unificado ⏳
- [ ] Substituir todos os print() por logger
- [ ] Remover wrappers _log, _log_warn, _log_error
- [ ] Padrão: from core.logging import get_logger; logger = get_logger(__name__)

### FASE 5 — Segurança ⏳
- [ ] Criar core/security/injection_guard.py
- [ ] Validação Pydantic nos webhooks
- [ ] Integrar injection_guard antes de qualquer chamada ao Gemini

## PROBLEMA ABERTO
1.3 BLOQUEADO: ai/tools/ importa de tools/ — dependência invertida.
Solução necessária: inverter a dependência fazendo tools/ importar de ai/tools/ ou eliminar tools/.

## COMMITS FEITOS
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

## COMO CONTINUAR
Próxima ação: Fase 4 — Logging Unificado ou Fase 5 — Segurança
Comando de validação após cada mudança: python3 -m py_compile apps/ia/app/main.py
