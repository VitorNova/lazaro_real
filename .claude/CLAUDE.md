# CLAUDE.md — Lazaro Real
# Plataforma SaaS de Atendimento WhatsApp com IA

---

## Stack

- **IA** (`apps/ia/`): Python 3.11 + FastAPI + APScheduler + Gemini
- **API** (`apps/api/`): TypeScript + Fastify
- **Frontend** (`apps/web/`): React + Vite + Tailwind CSS v4
- **DB**: Supabase (PostgreSQL) + Redis (cache/sessões)
- **Integrações**: UAZAPI (WhatsApp), Asaas (pagamentos)
- **Deploy**: Hetzner VPS, Docker, PM2

---

## Estrutura de Pastas

```
lazaro-real/
├── apps/
│   ├── ia/                          # Agente Python IA (foco principal)
│   │   └── app/
│   │       ├── main.py              → entry point limpo (NÃO editar — usar main_refactored.py)
│   │       ├── config.py            → Pydantic settings, todas as envs
│   │       ├── api/                 → rotas FastAPI (webhooks, jobs_control, health)
│   │       │   ├── routes/
│   │       │   ├── handlers/
│   │       │   └── services/
│   │       ├── domain/              → DDD — regras de negócio por contexto
│   │       │   ├── messaging/       → processamento de mensagens WhatsApp
│   │       │   │   ├── context/
│   │       │   │   ├── handlers/
│   │       │   │   ├── services/
│   │       │   │   └── models/
│   │       │   ├── billing/         → cobrança e pagamentos Asaas
│   │       │   │   ├── services/
│   │       │   │   └── models/
│   │       │   ├── leads/           → gestão de leads
│   │       │   │   └── services/
│   │       │   ├── analytics/       → métricas e insights
│   │       │   └── monitoring/      → análise de conversas
│   │       ├── ai/
│   │       │   └── tools/           → function declarations para Gemini
│   │       ├── integrations/        → clientes HTTP externos isolados
│   │       │   ├── asaas/
│   │       │   ├── uazapi/
│   │       │   ├── supabase/
│   │       │   ├── leadbox/
│   │       │   └── redis/
│   │       ├── jobs/                → APScheduler jobs (só disparam, sem lógica)
│   │       │   ├── scheduler.py
│   │       │   └── billing_job.py
│   │       ├── core/                → infraestrutura compartilhada
│   │       │   ├── config/
│   │       │   ├── utils/
│   │       │   ├── logging.py
│   │       │   └── lifespan.py
│   │       └── middleware/
│   │
│   ├── api/                         # Backend TypeScript
│   │   └── src/
│   │       ├── index.ts             → entry point Fastify
│   │       ├── config/
│   │       ├── api/
│   │       │   ├── agents/
│   │       │   ├── auth/
│   │       │   ├── dashboard/
│   │       │   ├── messages/
│   │       │   ├── leads/
│   │       │   ├── webhooks/
│   │       │   ├── analytics/
│   │       │   └── middleware/
│   │       ├── services/
│   │       │   ├── ai/
│   │       │   ├── asaas/
│   │       │   ├── uazapi/
│   │       │   ├── supabase/
│   │       │   └── redis/
│   │       ├── core/
│   │       └── utils/
│   │
│   └── web/                         # Frontend React
│       └── src/
│           ├── pages/
│           ├── components/
│           │   ├── ui/
│           │   └── conversations/
│           ├── services/
│           ├── stores/
│           ├── types/
│           └── lib/
│
├── docs/
├── scripts/
├── REFACTOR_LOG.md                  → ler SEMPRE antes de qualquer tarefa
└── README.md
```

---

## ⚠️ Arquivos Críticos — MONOLITOS

| Arquivo | Linhas | Regra |
|---|---|---|
| `apps/ia/app/webhooks/mensagens.py` | 4438 | NÃO editar diretamente |
| `apps/ia/app/webhooks/pagamentos.py` | 2984 | NÃO editar diretamente |
| `apps/ia/app/main.py` | 2068 | NÃO editar — usar `main_refactored.py` |
| `apps/api/src/api/agents/index.ts` | 1782 | NÃO editar — quebrar em route groups |

---

## Ordem de Leitura Antes de Qualquer Tarefa

1. Leia `REFACTOR_LOG.md` para entender o estado atual
2. Leia `apps/ia/app/config.py` para variáveis de ambiente
3. Para billing → leia `apps/ia/app/domain/billing/` primeiro
4. Para messaging → leia `apps/ia/app/domain/messaging/` primeiro
5. Para leads → leia `apps/ia/app/domain/leads/` primeiro
6. Para TypeScript → verifique se há versão equivalente em Python antes de criar

---

## Regras SEMPRE

- Usar módulos extraídos em `domain/` ao invés de editar monolitos
- Ler o arquivo existente antes de modificar qualquer coisa
- Commitar cada micro-mudança separadamente: `refactor(fase-X.Y): descrição`
- Adicionar arquivos específicos no git — NUNCA `git add -A` ou `git add .`
- Validar sintaxe antes de commitar: `python3 -m py_compile apps/ia/app/<arquivo>.py`
- Ao corrigir bug numa integração, verificar se precisa corrigir na versão TS também

---

## Regras NUNCA

- NUNCA editar `mensagens.py`, `pagamentos.py` ou `main.py` diretamente
- NUNCA criar arquivo com mais de 300 linhas — dividir em módulos
- NUNCA colocar prompt como string dentro de arquivo `.py`
- NUNCA colocar lógica de negócio dentro de `routers/` ou `jobs/`
- NUNCA mover dois arquivos ao mesmo tempo
- NUNCA assumir estado sem consultar `REFACTOR_LOG.md`
- NUNCA fazer force push para main/master
- NUNCA agrupar múltiplos passos num único commit

---

## Estratégia de Extração de Monolitos (CRÍTICO)

```
1. Criar módulo novo com código copiado do monolito
2. Validar: python3 -m py_compile apps/ia/app/<novo_modulo>.py
3. Commitar SOMENTE o módulo novo
4. NÃO editar o monolito ainda
5. Integração feita em fase separada após teste em produção
```

---

## Integrações Duplicadas Python ↔ TypeScript

| Integração | Python | TypeScript |
|---|---|---|
| Asaas | `integrations/asaas/` | `services/asaas/` |
| UAZAPI | `integrations/uazapi/` | `services/uazapi/` |
| Supabase | `integrations/supabase/` | `services/supabase/` |
| Redis | `integrations/redis/` | `services/redis/` |

> Ao corrigir bug em uma, verificar se precisa corrigir na outra.

---

## ⚠️ Tabelas Dinâmicas por Agente (CRÍTICO)

Cada agente tem tabelas próprias com nomes dinâmicos:

| Campo no Agent | Exemplo | Uso |
|---|---|---|
| `table_leads` | `LeadboxCRM_Ana_14e6e5ce` | Dados do lead |
| `table_messages` | `leadbox_messages_Ana_14e6e5ce` | Histórico de conversas |

**NUNCA construir nome de tabela manualmente:**
```python
# ERRADO
table = f"leadbox_messages_{agent_id.replace('-', '_')}"

# CORRETO
table = agent.get("table_messages")
```

> Ver documentação completa: `apps/ia/app/integrations/supabase/README.md`

---

## Convenções de Nomenclatura

**Python (`apps/ia`)**
- Arquivos: `snake_case` → `message_processor.py`
- Classes: `PascalCase` → `MessageProcessor`
- Funções: `snake_case` → `process_message()`
- Constantes: `UPPER_SNAKE` → `DEFAULT_TIMEOUT`

**TypeScript (`apps/api`)**
- Arquivos: `kebab-case` → `message-processor.ts`
- Classes: `PascalCase` → `MessageProcessor`
- Funções: `camelCase` → `processMessage()`
- Handlers: `*.handler.ts`
- Types: `*.types.ts`

**Estrutura de imports Python (ordem obrigatória)**
```python
# 1. Standard library
import os
from datetime import datetime

# 2. Third-party
from fastapi import FastAPI

# 3. Local — domain
from app.domain.messaging.services import MessageProcessor

# 4. Local — integrations
from app.integrations.uazapi import UazapiClient

# 5. Local — config
from app.config import settings
```

---

## Comandos Essenciais

```bash
# Logs em tempo real
pm2 logs agente-ia | grep -iE "PROCESS|WEBHOOK|LEADBOX"

# Últimas 200 linhas
pm2 logs agente-ia --lines 200 --nostream
pm2 logs lazaro-api --lines 200 --nostream

# Restart
pm2 restart agente-ia
pm2 restart lazaro-api

# Validar sintaxe Python
python3 -m py_compile apps/ia/app/<arquivo>.py

# Logs por domínio
pm2 logs agente-ia --lines 200 --nostream | grep -i "billing\|charge"
pm2 logs agente-ia --lines 200 --nostream | grep -i "webhook\|uazapi"
```

---

## Infraestrutura de Produção

| Path | Serviço | Porta |
|---|---|---|
| `/var/www/lazaro-v2/` | Código fonte (este repo) | — |
| `/var/www/phant/agente-ia/` | Produção Python | 3005 |
| `/var/www/phant/agnes-agent/` | Produção TypeScript | 3000 |

---

## Estado da Refatoração

**Fase atual: 8 (completa) → Próxima: Fase 9 — Limpeza Final**

Fase 9 pendente:
1. Substituir `main.py` por `main_refactored.py`
2. Atualizar imports nos monolitos para usar módulos extraídos
3. Deletar código duplicado dos monolitos
4. Quebrar `apps/api/src/api/agents/index.ts` em route groups
5. Remover pasta `production/` (cópia desnecessária)

> Ver `REFACTOR_LOG.md` para histórico completo.
