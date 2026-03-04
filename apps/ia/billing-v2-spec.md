# SPEC: Refatoração do Job de Cobrança v2

> **Este arquivo é a fonte da verdade.** Todo subagent deve ler este arquivo antes de começar qualquer trabalho.

---

## Contexto

O arquivo `cobrar_clientes.py` tem 1839 linhas monolíticas com 6 bugs conhecidos. Vamos substituí-lo por um pipeline modular de 5 etapas + 1 job orquestrador.

### Localização atual
- **Monolito:** `apps/ia/app/jobs/cobrar_clientes.py` (1839 linhas)
- **Extração parcial existente:** `apps/ia/app/jobs/billing_job.py` (614 linhas) — NÃO ALTERAR
- **Utils existente:** `apps/ia/app/utils/dias_uteis.py` (157 linhas) — funções de dias úteis BR
- **Services existentes:**
  - `apps/ia/app/services/gateway_pagamento.py` (AsaasService)
  - `apps/ia/app/services/whatsapp_api.py` (UazapiService, sign_message)
  - `apps/ia/app/services/supabase.py` (get_supabase_service)
  - `apps/ia/app/services/leadbox_push.py` (leadbox_push_silent, QUEUE_BILLING)
  - `apps/ia/app/services/dispatch_logger.py` (get_dispatch_logger)
  - `apps/ia/app/services/redis.py` (get_redis_service)

### Funções existentes em dias_uteis.py (NÃO recriar)
- `is_business_day`, `add_business_days`, `subtract_business_days`
- `anticipate_to_friday`, `get_today_brasilia`, `get_now_brasilia`
- `format_date`, `format_date_br`, `parse_date`, `is_business_hours`
- **FALTA (criar):** `count_business_days(start: date, end: date) -> int`

### Tabelas Supabase existentes
- `asaas_cobrancas` — cache de faturas (com campos ia_cobrou, ia_total_notificacoes, etc)
- `asaas_clientes` — cache de clientes (mobile_phone, phone, deleted_from_asaas)
- `asaas_contratos` — cache de assinaturas (status: ACTIVE/INACTIVE)
- `billing_notifications` — controle de envio (claim atômico via stored procedure)
- `contract_details` — detalhes parseados dos contratos

### Tabela NOVA a criar
- `billing_exceptions` — opt-out, pausas, exceções manuais

---

## Arquitetura Alvo

apps/ia/app/
├── jobs/
│   ├── cobrar_clientes.py          ← monolito atual (NÃO ALTERAR)
│   ├── billing_job.py              ← extração parcial existente (NÃO ALTERAR)
│   └── billing_job_v2.py           ← NOVO: entry point do cron (~80 linhas)
│
├── billing/                         ← NOVO: domínio de cobrança
│   ├── __init__.py
│   ├── models.py                   ← dataclasses tipadas (~50 linhas)
│   ├── collector.py                ← ETAPA 1: busca faturas (~120 linhas)
│   ├── normalizer.py               ← ETAPA 2: padroniza campos (~60 linhas)
│   ├── eligibility.py              ← ETAPA 3: funil de eliminação (~150 linhas)
│   ├── ruler.py                    ← ETAPA 4: régua dias úteis (~80 linhas)
│   ├── dispatcher.py               ← ETAPA 5: envio + registro (~120 linhas)
│   └── templates.py                ← templates de mensagem (~60 linhas)
│
├── shared/                          ← NOVO: utilitários reutilizáveis
│   ├── __init__.py
│   ├── phone.py                    ← extrair do monolito (~40 linhas)
│   └── formatters.py               ← format_brl, format_date_br (~30 linhas)
│
├── utils/
│   └── dias_uteis.py               ← EXISTENTE: adicionar count_business_days
│
└── services/                        ← EXISTENTE (não alterar)
    ├── gateway_pagamento.py         ← AsaasService
    ├── whatsapp_api.py              ← UazapiService, sign_message
    ├── supabase.py                  ← get_supabase_service
    ├── leadbox_push.py              ← leadbox_push_silent, QUEUE_BILLING
    ├── dispatch_logger.py           ← get_dispatch_logger
    └── redis.py                     ← get_redis_service

---

## 6 Bugs que DEVEM ser corrigidos

| # | Bug | Onde corrige | Como verificar |
|---|-----|-------------|----------------|
| 1 | Cobra contrato cancelado | eligibility.py → check has_active_contract | Query: asaas_contratos.status = 'ACTIVE' |
| 2 | Dias corridos no pós-vencimento | ruler.py → calculate_offset() | Fatura vence sexta → D+1 deve ser segunda |
| 3 | Busca clientes deletados | eligibility.py → check is_customer_valid | Query: asaas_clientes.deleted_from_asaas = False |
| 4 | Fallback silencioso | collector.py → retorna degraded=True | Se cache > 6h, job NÃO cobra |
| 5 | should_skip_payment vazia | eligibility.py → cadeia de 6 checks | Cada check retorna motivo |
| 6 | Sem opt-out/pausa | billing_exceptions + check has_exception | Tabela nova + query |

---

## Regras Invioláveis

1. **NÃO ALTERAR cobrar_clientes.py nem billing_job.py** — criar tudo novo, os antigos continuam rodando
2. **Cada arquivo < 150 linhas** — se passar, quebrar em dois
3. **Dias úteis SEMPRE** — usar count_business_days() de app.utils.dias_uteis
4. **Logging estruturado** — todo log como dict: { event, payment_id, agent_id, ... }
5. **Imports dos services existentes** — NÃO reescrever AsaasService, UazapiService, etc
6. **Manter compatibilidade** — billing_notifications, asaas_cobrancas usam os mesmos campos
7. **Zero hardcode de agente** — tudo via config do agente no Supabase
8. **Job novo = billing_job_v2.py** — coexiste com o antigo até validação
9. **Utils = app.utils.dias_uteis** — não criar business_days.py novo

---

## Models (dataclasses)

@dataclass
class Payment:
    id: str
    customer_id: str
    customer_name: str
    value: float
    due_date: date              # sempre date, nunca string
    status: str                 # "PENDING" | "OVERDUE"
    billing_type: str
    invoice_url: str | None
    bank_slip_url: str | None
    subscription_id: str | None
    source: str                 # "api" | "cache"

@dataclass
class CollectorResult:
    payments: list[Payment]
    source: str                 # "api" | "cache"
    cache_age_hours: float
    degraded: bool

@dataclass
class EligiblePayment:
    payment: Payment
    phone: str                  # normalizado, com 55
    customer_name: str

@dataclass
class RejectedPayment:
    payment: Payment
    reason: str                 # "contract_cancelled", "customer_deleted", etc
    check_name: str

@dataclass
class EligibilityResult:
    eligible: list[EligiblePayment]
    rejected: list[RejectedPayment]

@dataclass
class RulerDecision:
    should_send: bool
    offset: int                 # D-1, D0, D+3...
    template_key: str
    phase: str                  # "pre" | "due" | "post"

@dataclass
class DispatchResult:
    status: str                 # "sent" | "duplicate" | "error" | "retry_failed"
    payment_id: str
    template_used: str
    offset: int
    error: str | None

---

## Eligibility — Cadeia de Checks (ORDEM IMPORTA)

1. is_card_pending      → Cartão PENDING = pula
2. has_active_contract   → JOIN asaas_contratos WHERE status = 'ACTIVE'
3. is_customer_valid     → asaas_clientes WHERE deleted_from_asaas = False
4. has_valid_phone       → telefone normalizado, 12-13 dígitos
5. is_within_max_attempts → billing_notifications count < max
6. has_exception         → billing_exceptions WHERE active = True

Cada check é uma função separada que retorna (passed: bool, reason: str | None).

---

## Ruler — Schedule Padrão

DEFAULT_SCHEDULE = [-1, 0, 1, 3, 5, 7, 10, 12, 15]

Offset calculado SEMPRE com count_business_days(), nunca (today - due_date).days.

---

## Tabela Nova: billing_exceptions

CREATE TABLE billing_exceptions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    agent_id UUID NOT NULL,
    remotejid TEXT,
    payment_id TEXT,
    reason TEXT NOT NULL,
    note TEXT,
    active BOOLEAN DEFAULT TRUE,
    expires_at TIMESTAMPTZ,
    created_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_exceptions_active
    ON billing_exceptions(agent_id, active)
    WHERE active = TRUE;

---

## Collector — Regra de Fallback

API Asaas OK       → usa dados, source = "api"
API falhou         → usa cache Supabase
  cache < 6h       → usa, source = "cache", degraded = False
  cache >= 6h      → NÃO COBRA, degraded = True

---

## Dispatcher — Retry vs Duplicata

claim_notification retorna:
  "claimed"     → envia mensagem
  "duplicate"   → pula (log "already_claimed")
  "error"       → retry até 2x, depois log "retry_failed"

---

## Ordem de Implementação (para os subagents)

FASE 1 — Fundação (sem dependências)
  1. billing/models.py
  2. shared/phone.py
  3. shared/formatters.py
  4. billing/templates.py

FASE 2 — Pipeline Core (depende da Fase 1)
  5. billing/normalizer.py
  6. billing/collector.py
  7. billing/eligibility.py
  8. billing/ruler.py
  + count_business_days em dias_uteis.py

FASE 3 — Envio + Orquestração (depende da Fase 2)
  9. billing/dispatcher.py
  10. jobs/billing_job_v2.py
  11. CREATE TABLE billing_exceptions

FASE 4 — Validação
  12. Testes dos cenários críticos
  13. Comparar output do pipeline novo vs monolito antigo
