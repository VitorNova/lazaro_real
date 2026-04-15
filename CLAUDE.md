# CLAUDE.md — Metodologia

## Fluxo
**Lê → Planeja → EU APROVO → Testa (falha) → EU CONFIRMO → Codifica → Testa (passa) → Commit.**
Código é a última etapa.

## Regras Absolutas
1. Sem plano aprovado → sem teste.
2. Sem teste falhando confirmado → sem código.
3. Sem testes 100% verdes → sem commit.
4. Sem commit → sem `pm2 restart`.
5. Sem ler o trecho exato → sem substituição.
6. Um problema por vez. Um commit por correção.
7. Nunca `git add -A`. Nunca arquivo > 300 linhas. Nunca `except Exception: pass`.

## CP0 — Plano (antes de teste/código)
```
Problema / Causa / Solução / Arquivos / Módulos verificados / Teste a criar
```
Verificar que módulos/interfaces JÁ EXISTEM antes de propor. PARE se não aprovado.

## Infraestrutura

| Serviço | Porta | Função |
|---|---|---|
| `lazaro-ia` (PM2) | 3115 | Backend Python (API, webhooks, jobs) |
| `ana-langgraph` (PM2) | 3202 | Agente Ana ativo — **`/var/www/ana-langgraph`** |
| `ana-billing-job` (cron) | — | Cobrança seg-sex 9h |
| `ana-manutencao-job` (cron) | — | Manutenção seg-sex 9h |
| `agnes-agent` (PM2) | 3002 | Fallback TS |
| `nginx` | 3001 | Frontend estático |

- **Agente Ana ativo:** `/var/www/ana-langgraph` (NÃO `apps/ia/`). UUID `14e6e5ce-4627-4e38-aac8-f0191669ff53`. Mesmo Supabase.
- **Roteamento:** Leadbox → ana-langgraph | Asaas → lazaro-real | UAZAPI → lazaro-real
- **Traefik:** `lazaro.fazinzz.com` → `/` nginx, `/api/*` e `/webhooks/*` lazaro-ia

## Módulos Protegidos (não editar sem aprovação + teste)
`ia_gemini.py`, `leadbox_handler.py`, `leadbox.py`, `pagamentos.py`, `asaas_webhook_handler.py`, `mensagens.py`, `main.py`

## Jobs de Disparo — Padrão
UAZAPI → `ensure_lead_exists` → `save_message_to_history` (com `context` + `reference_id`) → `mark_notification_sent`.
Sem `context` salvo → IA perde contexto no follow-up.

## Filas Leadbox (tenant `123`)
IA `537` · Billing `544` · Manutenção `545` · Atendimento `453` · Financeiro `454`
Tabelas dinâmicas: sempre `agent.get("table_leads")` / `agent.get("table_messages")`.

## Testes
Fixtures: `tests/fixtures.py` (Faker pt_BR). Mocks: `make_supabase_mock[_with_capture]`, `fakeredis.FakeRedis`, `patch("httpx.AsyncClient")`. Nunca `time.sleep()`.

## Commit
```
tipo(escopo): descrição em pt-br
Bug / Causa / Correção / Teste
```
Tipos: `fix` `feat` `refactor` `test` `chore` `docs`.

## UAZAPI Webhook (não alterar)
Token `a2d9bb9c-c939-4c22-a656-7f80495681d9` · Instance `Agent_14e6e5ce` · URL `https://lazaro.fazinzz.com/webhooks/dynamic` · Events: `messages, connection`. Webhook 2 (`atendimento.fazinzz.com`) também não mexer.

## Modo Bombeiro
Produção caindo → patch direto, teste depois. Exceção, não regra.

## Referências
- `docs/DIAGNOSTICO.md` · `docs/apis/leadbox-referencia-completa.md` · `docs/apis/uazapi.md` (`readmessages: true`)
- Asaas: consultar MCP, nunca inventar endpoints
- `REFACTOR_LOG.md` — estado da refatoração
