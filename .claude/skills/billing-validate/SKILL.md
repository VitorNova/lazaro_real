---
name: billing-validate
description: Valida o pipeline de billing antes de deploy ou quando billing não dispara.
  Analisa código, testa execução e verifica banco. Use antes de qualquer mudança no billing.
---

# Billing Validate — Lazaro-Real

## Pipeline esperado
```
billing_job_v2.py → collector → eligibility (6 checks) → ruler → dispatcher
```

## Checklist de código (leia cada arquivo)

### ruler.py
- `determine_phase()` retorna `"reminder"` (offset<0), `"due_date"` (offset=0), `"overdue"` (resto)?
- Nenhuma ocorrência de `"pre"`, `"due"`, `"post"`?

### eligibility.py  
- `check_no_exception()` usa `.eq("active", "true")` (string, não boolean)?
- A query está separada em duas (por remotejid e por payment_id) sem `.or_()`?
- Resultado verificado com `if result and result.data` antes de acessar `.data`?

### scheduler.py
- `AsyncIOScheduler(job_defaults={'misfire_grace_time': 3600})`?

### billing_job_v2.py
- Entry point é `run_billing_v2()`?
- O job está registrado como "Billing Charge Job V2" no scheduler?

## Teste de execução
```bash
cd /var/www/lazaro-real/apps/ia
source /var/www/phant/agente-ia/venv/bin/activate
python -c "
import asyncio
from app.jobs.billing_job_v2 import run_billing_v2
asyncio.run(run_billing_v2())
" 2>&1 | grep -iE "sent|skip|erro|complete|eligible"
```
Esperado: `billing_v2_complete` com `errors: 0`
- `sent > 0` → pagamentos enviados hoje
- `skipped > 0, sent = 0` → já notificados ou fora da régua (normal)
- `errors > 0` → há bug, investigar

## Verificar constraint do banco
Se houver erro de constraint, verifique os valores aceitos:
```sql
SELECT pg_get_constraintdef(oid) 
FROM pg_constraint 
WHERE conname = 'billing_notifications_notification_type_check';
```

## Relatório
```
VERIFICAÇÃO              RESULTADO
──────────────────────────────────
ruler.py (tipos)         ✅/❌
eligibility.py (boolean) ✅/❌
eligibility.py (or_)     ✅/❌
scheduler misfire        ✅/❌
Execução manual          sent=X skipped=Y errors=Z
```
