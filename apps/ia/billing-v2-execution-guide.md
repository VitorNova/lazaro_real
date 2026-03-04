# Billing V2 — Guia de Execução para Claude Code

> **Regra:** Fazer /clear antes de cada fase para garantir contexto limpo.
> **Referências:** billing-v2-spec.md e billing-v2-plan.md no servidor.

---

## FASE 3: Envio + Orquestração ⬜ PRÓXIMA

### Comando (após /clear)

Leia estes 2 arquivos ANTES de qualquer ação:
1. cat billing-v2-spec.md
2. cat billing-v2-plan.md

Fases 1 e 2 já foram implementadas. Verifique que existem:
- app/billing/models.py, templates.py, normalizer.py, collector.py, eligibility.py, ruler.py
- app/shared/formatters.py

Agora implemente a FASE 3 (Envio + Orquestração) conforme billing-v2-plan.md:

1. app/billing/dispatcher.py → dispatch_single com claim atômico, formato, envio via Leadbox/UAZAPI, histórico, log
2. app/billing/agent_processor.py → process_agent com lógica COMPLETA de PENDING + OVERDUE (sem "..." nem "pass")
3. app/jobs/billing_job_v2.py → APENAS entry point (~50L), importa process_agent de agent_processor.py
4. Migração SQL: salvar em migrations/20260303_create_billing_exceptions.sql

ATENÇÃO:
- billing_job_v2.py NÃO deve ter process_agent dentro dele. Isso fica em agent_processor.py
- agent_processor.py deve ter lógica COMPLETA: loop de reminderDays, onDueDate, OVERDUE com agrupamento por cliente
- dispatcher.py usa sign_message, leadbox_push_silent, UazapiService conforme o plan
- Nenhum trecho com "# ..." ou "pass" como placeholder

Rode py_compile em cada .py após criar.
Pare e mostre resultado.

### Verificação Fase 3

echo "=== ESTRUTURA COMPLETA ==="
find app/billing app/shared app/jobs -type f -name "*.py" 2>/dev/null | sort | xargs wc -l

echo -e "\n=== PY_COMPILE FASE 3 ==="
for f in app/billing/dispatcher.py app/billing/agent_processor.py app/jobs/billing_job_v2.py; do
  python3 -m py_compile "$f" && echo "✓ $f" || echo "✗ $f FALHOU"
done

echo -e "\n=== BILLING_JOB: NÃO deve ter process_agent definido ==="
grep "def process_agent" app/jobs/billing_job_v2.py && echo "❌ ERRADO" || echo "✓ OK"

echo -e "\n=== BILLING_JOB: importa de agent_processor? ==="
grep "agent_processor" app/jobs/billing_job_v2.py

echo -e "\n=== AGENT_PROCESSOR: tem process_agent? ==="
grep "def process_agent" app/billing/agent_processor.py

echo -e "\n=== AGENT_PROCESSOR: sem placeholders? ==="
grep -n "# \.\.\.\|pass$" app/billing/agent_processor.py && echo "❌ TEM PLACEHOLDERS!" || echo "✓ Sem placeholders"

echo -e "\n=== AGENT_PROCESSOR: tem PENDING + OVERDUE? ==="
grep -c "PENDING\|OVERDUE" app/billing/agent_processor.py

echo -e "\n=== DISPATCHER: usa sign_message + leadbox + claim? ==="
grep -c "sign_message\|leadbox_push_silent\|claim_notification" app/billing/dispatcher.py

echo -e "\n=== SQL MIGRATION ==="
cat migrations/20260303_create_billing_exceptions.sql 2>/dev/null | head -5 || echo "❌ Migration não encontrada"

echo -e "\n=== LINHAS ==="
wc -l app/jobs/billing_job_v2.py app/billing/agent_processor.py

---

## FASE 4: Revisão Final ⬜

### Verificação Final Completa

echo "========================================="
echo "  BILLING V2 — VERIFICAÇÃO FINAL"
echo "========================================="

echo -e "\n=== ESTRUTURA ==="
find app/billing app/shared app/jobs -type f -name "*.py" 2>/dev/null | sort | xargs wc -l

echo -e "\n=== PY_COMPILE TODOS ==="
for f in $(find app/billing -name "*.py" | sort) app/shared/formatters.py app/jobs/billing_job_v2.py; do
  python3 -m py_compile "$f" && echo "✓ $f" || echo "✗ $f FALHOU"
done

echo -e "\n=== 6 BUG FIXES ==="
echo "BUG #1:" && grep "def check_active_contract" app/billing/eligibility.py && echo "✓" || echo "✗"
echo "BUG #2:" && grep "count_business_days" app/billing/ruler.py && echo "✓" || echo "✗"
echo "BUG #3:" && grep "deleted_from_asaas" app/billing/eligibility.py | head -1 && echo "✓" || echo "✗"
echo "BUG #4: degraded refs:" && grep -c "degraded" app/billing/collector.py
echo "BUG #5: checks:" && grep -c "def check_" app/billing/eligibility.py
echo "BUG #6:" && grep "billing_exceptions" app/billing/eligibility.py | head -1 && echo "✓" || echo "✗"

echo -e "\n=== ANTI-PATTERNS ==="
echo "payments_dict:" && grep -rc "payments_dict" app/billing/
echo "placeholders:" && grep -rn "# \.\.\.\|pass$" app/billing/agent_processor.py app/jobs/billing_job_v2.py 2>/dev/null || echo "✓ nenhum"
echo "__init__ imports:" && grep -c "^from\|^import" app/billing/__init__.py
