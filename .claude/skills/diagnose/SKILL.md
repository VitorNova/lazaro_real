---
name: diagnose
description: Diagnostica o sistema lazaro-real. Use quando: jobs não disparam, 
  Ana não responde, billing falha, manutenção não envia, contexto perdido, 
  ou antes de qualquer deploy. Analisa código e logs sem precisar de explicação.
---

# Diagnóstico Lazaro-Real

Você conhece toda a arquitetura pelo CLAUDE.md. Execute este diagnóstico completo:

## 1. Verificar se lazaro-ia está rodando
```bash
pm2 show lazaro-ia | grep -iE "status|uptime|restart|memory"
```
Esperado: status=online, restarts baixo, memory < 500mb

## 2. Verificar logs recentes de jobs
```bash
pm2 logs lazaro-ia --lines 200 --nostream | grep -iE \
  "billing_v2_complete|maintenance|calendar|error|exception" \
  | grep -v "FutureWarning" | tail -30
```
Esperado: billing_v2_complete com sent≥0 errors=0, jobs registrados

## 3. Verificar saúde do scheduler
```bash
pm2 logs lazaro-ia --lines 100 --nostream | grep -iE "APScheduler|Added job|misfire"
```
Esperado: 4 jobs registrados, misfire_grace_time presente

## 4. Verificar billing pipeline — código
Leia e valide:
- `apps/ia/app/billing/ruler.py` — notification_type retorna "reminder"/"due_date"/"overdue"?
- `apps/ia/app/billing/eligibility.py` — .eq("active", "true") com string?
- `apps/ia/app/jobs/scheduler.py` — AsyncIOScheduler tem job_defaults misfire_grace_time=3600?

## 5. Verificar prompt injection — código
Leia `apps/ia/app/domain/messaging/services/message_processor.py`:
- Existe mapeamento queue_to_context?
- Fila 544 → "billing"?
- Fila 545 → "manutencao"?

## 6. Verificar webhook
```bash
curl -s -X POST http://127.0.0.1:3115/api/webhook/whatsapp \
  -H "Content-Type: application/json" \
  -d '{"type":"test"}' -w "\nHTTP: %{http_code}"
```
Esperado: HTTP 200

## 7. Relatório final
Apresente um resumo assim:
```
COMPONENTE          STATUS    OBSERVAÇÃO
─────────────────────────────────────────
lazaro-ia PM2       ✅/❌     
Scheduler (4 jobs)  ✅/❌     
misfire_grace_time  ✅/❌     
Billing pipeline    ✅/❌     
Prompt injection    ✅/❌     
Webhook WhatsApp    ✅/❌     
Últimos erros       ✅/❌     
```
Se encontrar ❌, descreva o problema e proponha o fix antes de aplicar.
