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

### FASE 2 — Quebrar Monolitos ✅ (parcial)
- [x] mensagens.py agora chama domain/messaging/context/ em vez de funções locais
- [ ] Remover funções locais duplicadas de mensagens.py (aguarda testes em produção)
- [ ] Quebrar pagamentos.py → domain/billing/
- [ ] Quebrar athena.py → domain/analytics/

### FASE 3 — Jobs Thin ⏳
- [ ] cobrar_clientes.py → lógica para domain/billing/ (já existe estrutura)
- [ ] reengajar_leads.py → lógica para domain/leads/ (já existe estrutura)
- [ ] CLASSIFIER_PROMPT → prompts/leads/classifier.txt

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
- 3b65c9b refactor(fase-2): integrar domain/messaging em mensagens.py
- 67f99f6 refactor(fase-1.5): unificar utils em core/utils
- 118fbba refactor(fase-1.4): remover stubs de api/
- e21ac84 refactor(fase-1.1): marcar services/supabase.py como DEPRECATED
- c57667d refactor(fase-1.1): adicionar metodos faltantes nos repositories

## COMO CONTINUAR
Próxima ação: Fase 2 — quebrar pagamentos.py
Comando de validação após cada mudança: python3 -m py_compile apps/ia/app/main.py
