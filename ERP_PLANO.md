# ERP MVP — Plano Executável

> **Leia uma vez por sessão.** Fonte da verdade do projeto.
> Última atualização: 2026-03-14 | Versão: MVP-v1

---

## O que é

ERP SaaS multi-tenant brasileiro com IA nativa (WhatsApp).
Substituto do TGA Sistemas. Stack: FastAPI + Supabase + Redis + Gemini.

**Diferencial único:** Agente IA integrado ao ERP — nenhum concorrente tem.

---

## MVP Scope (APENAS ISSO)

| Entra | Não entra (pós-MVP) |
|-------|---------------------|
| Login/senha | Multi-usuário/permissões |
| CRUD Clientes | NF-e / NFC-e |
| CRUD Produtos/Serviços | TEF / maquininha |
| Criar Venda | PDV offline |
| Criar OS | Estoque automático |
| Pagamento manual | Contas a pagar |
| Dashboard básico | Relatórios avançados |
| Agente IA WhatsApp | Importação CSV |

**Regra:** Se não está na coluna "Entra", não implementar.

---

## Schema Aplicado (5 tabelas)

> Migrations em `migrations/001_tenant_config.sql`, `002_erp_base_schema.sql`, `003_erp_orders.sql`

| Tabela | Descrição | RLS |
|--------|-----------|-----|
| `tenant_config` | Configurações por tenant | - |
| `erp_customers` | Clientes e fornecedores | ✅ |
| `erp_products` | Produtos e serviços (com SKU, NCM) | ✅ |
| `erp_inventory` | Estoque por depósito | ✅ |
| `erp_financial` | Contas a pagar/receber | ✅ |
| `erp_orders` | Vendas e OS (items JSONB) | ✅ |

Ver arquivos em `migrations/` para schema completo.

---

## Checklist de Implementação

### Fase 0 — Schema [COMPLETA]
```
[x] Criar migrations (001_tenant_config, 002_erp_base_schema, 003_erp_orders)
[x] Aplicar no Supabase
[x] Criar RLS policies para tenant_id
[x] Testar: SELECT * FROM erp_customers funciona
```

### Fase 1 — Backend CRUD [COMPLETA]
```
[x] POST/GET/PUT/DELETE /api/erp/customers
[x] POST/GET/PUT/DELETE /api/erp/products
[x] POST/GET/PUT /api/erp/orders
[x] POST /api/erp/orders/{id}/close
[x] GET /api/erp/dashboard (totais dia/semana/mês)

Arquivos criados:
- apps/ia/app/domain/erp/models.py (Pydantic models)
- apps/ia/app/domain/erp/repository.py (Repository Supabase)
- apps/ia/app/domain/erp/services/crud.py (Services CRUD)
- apps/ia/app/api/routes/erp.py (FastAPI endpoints)

Testes:
- tests/test_erp_models.py (16 passando)
- tests/test_erp_repository.py (12 passando)
- tests/test_erp_services.py (14 passando)
- tests/test_erp_routes.py (17 passando)
```

### Fase 2 — Frontend
```
[ ] Tela Login (usa Supabase Auth)
[ ] Tela Dashboard
[ ] Tela Clientes (lista + form)
[ ] Tela Produtos (lista + form)
[ ] Tela Vendas/OS (lista + criar + fechar)
```

### Fase 3 — Agente IA
```
[ ] Tool: consultar_cliente(phone) → dados do cliente
[ ] Tool: consultar_pedido(phone) → pedidos abertos
[ ] Tool: consultar_saldo(phone) → valor pendente
[ ] Testar via WhatsApp
```

---

## Estrutura de Arquivos MVP

```
apps/ia/app/
├── api/routes/
│   └── erp.py              # Rotas do ERP
├── domain/erp/
│   ├── models.py           # Pydantic models
│   ├── services/
│   │   ├── customer_service.py
│   │   ├── product_service.py
│   │   └── order_service.py
│   └── repository.py       # Queries Supabase
└── ai/tools/
    └── erp_tools.py        # Tools para o agente

apps/web/src/
├── pages/
│   ├── erp/
│   │   ├── customers.tsx
│   │   ├── products.tsx
│   │   ├── orders.tsx
│   │   └── dashboard.tsx
└── components/erp/
    ├── CustomerForm.tsx
    ├── ProductForm.tsx
    └── OrderForm.tsx
```

---

## Regras de Implementação

1. **Máximo 200 linhas por arquivo** — dividir se passar
2. **Um endpoint por função** — sem god functions
3. **Testes antes do código** — ver CLAUDE.md
4. **tenant_id obrigatório** — nunca query sem filtro
5. **Validação com Pydantic** — nunca dict solto

---

## Comandos Úteis

```bash
# Validar sintaxe
python -m py_compile apps/ia/app/domain/erp/services/customer_service.py

# Rodar testes ERP
python -m pytest tests/test_erp_*.py -v

# Logs do backend
pm2 logs lazaro-ia --lines 100 --nostream | grep -i "ERP\|erp"
```

---

## Fluxos de Uso

### Venda Simples
```
Cliente → Seleciona/cria cliente → Adiciona itens → Fecha venda → Registra pagamento
```

### Ordem de Serviço
```
Cliente → Cria OS (status=open) → Trabalha → Fecha OS → Registra pagamento
```

### Agente IA
```
WhatsApp: "Meu pedido tá pronto?"
→ Tool consultar_pedido(phone)
→ Responde com status real do ERP
```

---

## Decisões Tomadas

| Decisão | Escolha | Motivo |
|---------|---------|--------|
| NF-e | Pós-MVP | Complexidade alta, cliente emite manual |
| TEF | Pós-MVP | Maquininha standalone resolve |
| Offline | Pós-MVP | Exige internet no MVP |
| Estoque | Manual | Botão "baixar estoque" |
| Multi-user | Pós-MVP | 1 login por empresa no início |
| Permissões | Pós-MVP | Owner faz tudo |

---

## Próximos Passos (ordem)

1. ✅ Plano aprovado
2. ✅ Criar migration SQL
3. ✅ Aplicar no Supabase
4. ✅ Criar services backend
5. ✅ Criar rotas API
6. ⏳ **Criar telas frontend** ← PRÓXIMO
7. ⏳ Integrar tools do agente
8. ⏳ Testar fluxo completo

---

## Anti-patterns (NUNCA)

- ❌ Implementar feature fora do scope MVP
- ❌ Criar arquivo > 200 linhas
- ❌ Query sem tenant_id
- ❌ Endpoint sem validação Pydantic
- ❌ Código sem teste
- ❌ Commit de múltiplas features

---

## Docs Relacionadas

- Para auth existente: `apps/ia/app/api/routes/auth.py`
- Para padrão de services: `apps/ia/app/domain/billing/services/`
- Para padrão de tools IA: `apps/ia/app/ai/tools/`
- Para config tenant: `apps/ia/app/core/tenant.py`
