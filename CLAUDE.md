# CLAUDE.md — Metodologia de Desenvolvimento

> **Leia este arquivo inteiro antes de qualquer ação.**

---

## ⚡ TL;DR para Claude Code

Você é o par programador. **Você escreve. Eu penso.**

A ordem é sempre:
**1. Lê → 2. Entende → 3. Planeja → 4. EU APROVO → 5. Testa → 6. EU CONFIRMO → 7. Codifica**

Código é **sempre a última etapa.** Nunca a primeira.

---

## Filosofia Central

**Vibe Coding** = jogar prompt, aceitar o que vem, não ler o código, confiar na intuição.  
**Disciplina** = você pensa e planeja, a IA executa e escreve. Disciplina acima de intuição.

> "Sem teste, cada mudança é uma aposta."

O dev entrega o **esqueleto**. A IA coloca os **órgãos**.  
Se o esqueleto não existe (arquitetura, domínio, CLAUDE.md), não comece.

---

## Regras Absolutas — Nunca Quebre

1. **Sem plano aprovado = sem teste.** Proponha o plano em texto e aguarde aprovação.
2. **Sem teste falhando confirmado = sem código.** O humano confirma que o teste falhou.
3. **Sem teste = sem código.** Feature sem teste não existe.
4. **Sem testes passando = sem commit.** 100% verde ou não vai.
5. **Sem commit = sem pm2 restart.** A ordem é sempre essa.
6. **Sem ler o trecho exato = sem sed/substituição.** Confirme antes de alterar.
7. **Erro da IA = explique e peça refazer.** Nunca corrija manualmente no arquivo.
8. **Um problema por vez. Um commit por correção.** Sem commits de múltiplas correções.
9. **Todo erro novo → documentado aqui neste CLAUDE.md.**

---

## ⛔ Checkpoints Obrigatórios

Estes checkpoints bloqueiam o avanço. Não prossiga sem completá-los.

### Checkpoint 0 — Antes de qualquer teste ou código
```
[ ] Li o CLAUDE.md completo?
[ ] Entendi o problema descrito em português?
[ ] Propus o plano de solução em texto (sem tocar em código)?
[ ] Verifiquei se módulos/classes do plano JÁ EXISTEM no código? ← CRÍTICO
[ ] Se existem, validei que a interface proposta é COMPATÍVEL? ← CRÍTICO
[ ] O humano aprovou o plano? ← AGUARDE RESPOSTA
```
→ Se o humano não aprovou: **PARE. Não escreva nada.**
→ Se não validou existência/interface: **PARE. Valide primeiro.**

Formato obrigatório do plano:
```
PLANO:
Problema: [o que está acontecendo]
Causa provável: [onde e por que acontece]
Solução proposta: [o que será alterado e como]
Arquivo(s) afetado(s): [lista]
Validação de código existente: [módulos verificados e compatibilidade]
Teste que será criado: [descrição do cenário]

Aguardando aprovação para prosseguir.
```

### Checkpoint 1 — Antes de qualquer código
```
[ ] Plano foi aprovado pelo humano?
[ ] Escrevi APENAS o teste (sem implementação)?
[ ] O teste usa mock para dependências externas (Supabase, Redis, HTTP)?
[ ] Rodei: python -m pytest tests/test_arquivo.py -v
[ ] O teste FALHA? ← REPORTE O RESULTADO E AGUARDE CONFIRMAÇÃO
```
→ Se o humano não confirmou que o teste falhou: **PARE.**

Formato obrigatório do relatório de teste:
```
TESTE CRIADO: tests/test_arquivo.py::Classe::test_metodo
RESULTADO: FALHOU ✓ (esperado)
Erro: [cole a linha de erro do pytest]

Teste reproduz o problema corretamente.
Aguardando confirmação para escrever a implementação.
```

### Checkpoint 2 — Antes de qualquer commit
```
[ ] Implementação foi escrita após aprovação?
[ ] Rodei: python -m pytest tests/ -v
[ ] Todos os testes passam? (0 failed, 0 error)
[ ] O arquivo modificado tem menos de 300 linhas? (senão, quebrar)
[ ] Nenhum except Exception: pass silencioso foi introduzido?
```
→ Se qualquer item for NÃO: **PARE. Corrija antes de commitar.**

### Checkpoint 3 — Antes de qualquer pm2 restart
```
[ ] Checkpoint 2 foi concluído?
[ ] python -m py_compile app/arquivo_modificado.py retorna OK?
```
→ Se NÃO: **PARE.**

### Relatório Obrigatório ao Final de Cada Correção
Responda sempre:
1. Qual arquivo de teste cobre essa correção?
2. O plano foi aprovado pelo humano? (sim/não)
3. O teste FALHOU antes da correção? (sim/não)
4. O teste PASSA após a correção? (sim/não)
5. Todos os outros testes continuam passando? (sim/não)

**Se qualquer resposta for "não" → a correção está incompleta.**

---

## Fluxo Completo — A Ordem é Sagrada

```
VOCÊ  = pensa → planeja → revisa → aprova
IA    = entende → propõe → escreve teste → escreve código → reporta

┌─────────────────────────────────────────────────────────────┐
│  1. IA lê o CLAUDE.md                                       │
│  2. IA entende o problema descrito                          │
│  3. IA propõe PLANO em texto (sem tocar em nada)            │
│  4. ★ VOCÊ APROVA O PLANO                                   │
│  5. IA escreve APENAS o teste                               │
│  6. IA roda o teste → deve FALHAR                           │
│  7. ★ VOCÊ CONFIRMA QUE O TESTE FALHOU                      │
│  8. IA escreve a implementação mínima                       │
│  9. IA roda todos os testes → deve PASSAR                   │
│ 10. IA faz o commit com mensagem padrão                     │
│ 11. pm2 restart                                             │
└─────────────────────────────────────────────────────────────┘

★ = pontos onde a IA PARA e aguarda resposta humana
```

> Código é sempre a **última** etapa. Nunca a primeira.

### Por bug, siga exatamente esta ordem:
```
1. Leia o CLAUDE.md
2. Descreva em português o que entendeu do problema
3. Proponha o plano → AGUARDE APROVAÇÃO
4. Escreva apenas o teste que reproduz o bug
5. Rode: pytest tests/test_X.py -v → deve FALHAR → REPORTE E AGUARDE CONFIRMAÇÃO
6. Escreva a correção mínima
7. Rode: pytest tests/ -v → deve passar TUDO
8. Commit limpo
9. pm2 restart
```

### Por feature nova, siga exatamente esta ordem:
```
1. Leia o CLAUDE.md
2. Descreva em português o que entendeu da feature
3. Proponha o plano de implementação → AGUARDE APROVAÇÃO
4. Escreva apenas os testes da feature
5. Rode: pytest tests/test_X.py -v → deve FALHAR → REPORTE E AGUARDE CONFIRMAÇÃO
6. Escreva a implementação mínima para passar
7. Rode: pytest tests/ -v → deve passar TUDO
8. Refactor se necessário (sem quebrar testes)
9. Commit limpo
```

---

## Como Escrever Testes

### Estrutura Padrão de Arquivo de Teste

```python
# tests/test_nome_da_funcionalidade.py

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import fakeredis

# ─── Helpers de Mock ────────────────────────────────────────────────────────

def make_supabase_mock(table_data: dict) -> MagicMock:
    mock = MagicMock()

    def table_side_effect(table_name):
        t = MagicMock()
        data = table_data.get(table_name, [])
        resp = MagicMock()
        resp.data = data

        t.select.return_value.eq.return_value.eq.return_value \
         .limit.return_value.execute.return_value = resp
        t.select.return_value.eq.return_value \
         .limit.return_value.execute.return_value = resp
        t.select.return_value.execute.return_value = resp
        t.update.return_value.eq.return_value.execute.return_value = MagicMock()
        t.insert.return_value.execute.return_value = MagicMock()
        return t

    mock.client.table.side_effect = table_side_effect
    return mock


def make_redis_mock() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis()


def make_http_mock(status_code: int = 200, json_response: dict = None):
    if json_response is None:
        json_response = {"success": True}

    mock_response = AsyncMock()
    mock_response.status_code = status_code
    mock_response.json = lambda: json_response

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=MagicMock(
        post=AsyncMock(return_value=mock_response),
        get=AsyncMock(return_value=mock_response),
    ))
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return patch("httpx.AsyncClient", return_value=mock_client)


# ─── Classe de Teste ─────────────────────────────────────────────────────────

class TestNomeDaFuncionalidade:
    """
    TDD — [Nome do Bug ou Feature] [DATA]

    Contexto: [o que motivou esses testes]
    Causa: [o que estava errado]
    Correção: [o que foi alterado]
    """

    def test_cenario_principal_funciona(self):
        mock_db = make_supabase_mock({
            "clientes": [{"id": "abc123", "status": "ativo", "nome": "João"}]
        })
        resultado = funcao_a_testar(mock_db, parametro_valido)
        assert resultado is not None
        assert resultado["status"] == "esperado"

    def test_retorna_none_quando_sem_dados(self):
        mock_db = make_supabase_mock({"clientes": []})
        resultado = funcao_a_testar(mock_db, parametro_valido)
        assert resultado is None

    def test_nao_envia_quando_redis_pausado(self):
        redis = make_redis_mock()
        redis.set("pause:agent_id:5511999999999", "1")
        resultado = funcao_que_verifica_pausa(redis, agent_id="agent_id", phone="5511999999999")
        assert resultado is False

    @pytest.mark.asyncio
    async def test_chama_api_externa_com_sucesso(self):
        mock_db = make_supabase_mock({"mensagens": [{"id": "m1", "texto": "oi"}]})
        with make_http_mock(200, {"success": True}):
            resultado = await funcao_que_chama_uazapi(mock_db, phone="5511999999999")
        assert resultado is True

    @pytest.mark.asyncio
    async def test_trata_falha_da_api_externa(self):
        mock_db = make_supabase_mock({"mensagens": [{"id": "m1"}]})
        with make_http_mock(500, {"error": "internal server error"}):
            resultado = await funcao_que_chama_uazapi(mock_db, phone="5511999999999")
        assert resultado is False
```

### Regras ao Escrever Testes

- **Um `assert` por comportamento** — teste cobre um caso específico, não vários
- **Nome descreve o cenário** — `test_nao_envia_quando_cliente_em_manutencao`, não `test_1`
- **Docstring obrigatória** na classe e nos testes de bug real
- **Mock apenas o necessário** — não mocke o que não é dependência externa
- **Teste deve FALHAR antes da implementação** — se já passa, a implementação já existe
- **Nunca** use `time.sleep()` em testes — use fakeredis, mocks, ou monkeypatch

---

## Mocks de Referência

### Supabase — Encadeamentos Comuns

```python
mock = make_supabase_mock({"tabela": [{"id": "1", "campo": "valor"}]})
mock_table = mock.client.table("tabela")
mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock()
mock_table.update.assert_called_once_with({"campo": "novo_valor"})
mock_table.insert.assert_called_once()
```

### Redis — Cenários Comuns

```python
redis = make_redis_mock()
redis.set("pause:agent_id:5511999999999", "1")   # simular pausa
redis.setex("chave", 3600, "valor")               # com TTL
assert redis.get("chave_inexistente") is None     # ausência de chave
```

### HTTP Externo — UAZAPI / Asaas

```python
with patch("app.services.uazapi.httpx.AsyncClient") as MockClient:
    instance = MockClient.return_value.__aenter__.return_value
    instance.post = AsyncMock(return_value=AsyncMock(
        status_code=200,
        json=lambda: {"messageId": "abc123"}
    ))
    resultado = await enviar_mensagem(phone="5511999999999", texto="oi")
```

### APScheduler / Jobs Agendados

```python
def test_job_nao_executa_fora_do_horario():
    with patch("app.jobs.cobrar.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2025, 1, 1, 3, 0)
        assert verificar_se_deve_executar() is False
```

---

## Regra de Validação de Plano (CRÍTICO)

> Erro comum: criar testes baseados em especificação (docs/tst.md) sem validar se o código real existe e qual sua interface.

### Antes de criar testes para um plano:

1. **Verificar existência do módulo**
   ```bash
   # O módulo já existe?
   ls -la apps/ia/app/services/dispatch_logger.py

   # O import funciona?
   python3 -c "from app.services.dispatch_logger import DispatchLogger; print('OK')"
   ```

2. **Verificar interface real** (se módulo existe)
   ```bash
   # Ver assinatura do construtor e métodos
   python3 -c "
   from app.services.dispatch_logger import DispatchLogger
   import inspect
   print('__init__:', inspect.signature(DispatchLogger.__init__))
   print('Métodos:', [m for m in dir(DispatchLogger) if not m.startswith('_')])
   "
   ```

3. **Comparar com especificação**
   - Construtor especificado vs. real
   - Path do import especificado vs. real
   - Métodos existentes vs. novos a adicionar

### Exemplo de erro evitado:

| Especificação (tst.md) | Código Real | Correção no Teste |
|---|---|---|
| `from app.domain.billing.services.dispatch_logger` | `from app.services.dispatch_logger` | Usar path real |
| `DispatchLogger(supabase)` | `DispatchLogger()` (lazy load) | Mockar property, não construtor |
| Método `log_deferred` existe | Método não existe | Teste DEVE falhar (TDD) |

### Checklist de Validação

```
[ ] Módulo existe? Se SIM → ler código real
[ ] Import path do plano == import path real?
[ ] Construtor do plano == construtor real?
[ ] Métodos existentes no código já?
[ ] Se existem → interface compatível com plano?
[ ] Se não existem → testes usam pytest.importorskip()?
```

### Padrão para TDD com Módulos Inexistentes

```python
# No topo do arquivo de teste (NUNCA dentro de métodos)
module = pytest.importorskip(
    "app.path.to.module",
    reason="Módulo ainda não implementado"
)
FunctionToTest = module.function_to_test
```

---

## Estrutura de Commit

```
tipo(escopo): descrição curta em português

Bug: o que estava acontecendo
Causa: por que acontecia
Correção: o que foi alterado
Teste: test_arquivo.py N/N passando
```

**Tipos válidos:** `fix` `feat` `refactor` `test` `chore` `docs`

---

## Infraestrutura de Processos e Roteamento

### Arquitetura Atual (2026-03-16)

| Serviço | Tipo | Porta | Diretório | Função |
|---|---|---|---|---|
| `lazaro-ia` | PM2 | 3115 | `/var/www/lazaro-real/apps/ia` | Backend Python (API, Webhooks, Jobs, IA) |
| `agnes-agent` | PM2 | 3002 | `/var/www/phant/agnes-agent` | Fallback TS (asaas, manutencoes, athena) |
| `nginx` | systemd | 3001 | `/var/www/lazaro-real/frontend` | Frontend estático (monolito vanilla JS) |

**Traefik roteia:**
- `lazaro.fazinzz.com/*` → nginx (3001) → arquivos estáticos
- `lazaro.fazinzz.com/api/*` → lazaro-ia (3115)
- `lazaro.fazinzz.com/webhooks/*` → lazaro-ia (3115)

**Proxy interno (lazaro-ia → agnes-agent):**
- `/api/dashboard/asaas/*` → agnes-agent (3002)
- `/api/dashboard/manutencoes/*` → agnes-agent (3002)
- `/api/athena/*` → agnes-agent (3002)

> ⚠️ Para endpoints com proxy, verifique AMBOS os logs: `lazaro-ia` e `agnes-agent`

```bash
# Webhooks e API Python:
pm2 logs lazaro-ia --lines 50 --nostream

# Endpoints com proxy (asaas, manutencoes, athena):
pm2 logs agnes-agent --lines 50 --nostream

# Frontend:
tail -f /var/log/nginx/lazaro.access.log
```

---

## Referência de Logs — lazaro-ia

> Todas as strings abaixo são reais, extraídas de produção em 2026-03-12.  
> Arquivo fonte: `apps/ia/app/ai/ia_gemini.py`

### Fluxo Completo — Mensagem Simples (sem tool)

```
[BUFFER] Mensagem adicionada - phone=556697194084, agent=ANA
  ↓ (14s de delay)
[PROCESS] Iniciando processamento para 556697194084 (agente: 14e6e5ce)
[GEMINI] Inicializando com 7 tools (calendar=False)
[GEMINI] Enviando 13 msgs para phone=5566****4084
[GEMINI] Resposta recebida para phone=5566****4084 (65 chars, tools=[])
[UAZAPI] Enviando resposta para phone=5566****4084 (65 chars)
[UAZAPI] Enviado phone=5566****4084 - 1/1 chunks OK
Mensagem enviada com sucesso. ID: 556699673864:3EB0...
[BUFFER] Limpo apos sucesso para phone=5566****4084
```

### Fluxo Completo — Mensagem com Tool (ex: transferência)

```
[GEMINI] Enviando 13 msgs para phone=5566****4084
[TOOL START] transferir_departamento
  → transfer_start departamento=None motivo='...' queue_id=453.0
  → transfer_resolved dept_name=Atendimento final_queue_id=453
  → transfer_api_result result={'sucesso': True, 'ticket_id': ...}
  → transfer_success dept=Atendimento ticket_id=864480
[TOOL END] transferir_departamento duration=4.21s result=sucesso
[TOOL LOOP END] 1 iterações em 6.73s
[GEMINI] Resposta recebida ... (77 chars, tools=['transferir_departamento'])
[UAZAPI] Enviando resposta ...
Mensagem enviada com sucesso. ID: ...
[BUFFER] Limpo apos sucesso ...
```

### Mapa de Strings por Etapa

| Etapa | String no log |
|---|---|
| Mensagem entra no buffer | `[BUFFER] Mensagem adicionada` |
| Buffer liberado | `[BUFFER] Limpo apos sucesso` |
| Início do processamento | `[PROCESS] Iniciando processamento` |
| Gemini inicializado | `[GEMINI] Inicializando com X tools` |
| Enviando ao Gemini | `[GEMINI] Enviando X msgs` |
| **Tool iniciada** | **`[TOOL START] nome_da_tool`** |
| **Tool finalizada** | **`[TOOL END] nome_da_tool duration=Xs result=sucesso`** |
| **Loop de tools encerrado** | **`[TOOL LOOP END] X iterações em Ys`** |
| Resposta do Gemini | `[GEMINI] Resposta recebida ... (tools=['...'])` |
| Iniciando envio | `[UAZAPI] Enviando resposta` |
| Envio confirmado | `[UAZAPI] Enviado ... - 1/1 chunks OK` |
| Entrega confirmada | `Mensagem enviada com sucesso. ID: ...` |
| Evento Leadbox chegou | `[LEADBOX WEBHOOK] Evento recebido: UpdateOnTicket` |
| Ticket fechado | `[LEADBOX HANDLER] Ticket X FECHADO` |
| Lead ignorado (fila humana) | `[LEADBOX] Lead X IGNORADO: banco fila=453` |
| FAIL-SAFE ativado | `[FAIL-SAFE] API sem queue_id, usando fallback Supabase` |
| Contexto detectado ✅ | `[CONTEXT DEBUG] ENCONTRADO context='manutencao_preventiva'` |
| Contexto não encontrado ❌ | `[CONTEXT DEBUG] Nenhum context especial encontrado` |

### Comandos de Monitoramento

```bash
# Fluxo completo de mensagem
pm2 logs lazaro-ia | grep -iE "BUFFER|PROCESS|GEMINI|TOOL|UAZAPI|Mensagem enviada"

# Só tools (o que o agente está fazendo)
pm2 logs lazaro-ia | grep -iE "TOOL START|TOOL END|TOOL LOOP|tools=\["

# Contexto de manutenção (detectado ou não)
pm2 logs lazaro-ia | grep -i "CONTEXT DEBUG"

# Webhooks Leadbox
pm2 logs lazaro-ia | grep -iE "LEADBOX|FECHADO|IGNORADO|Evento recebido"

# Só erros
pm2 logs lazaro-ia | grep -iE "ERROR|WARNING|FAIL|IGNORADO|Pydantic"

# Monitorar telefone específico
pm2 logs lazaro-ia | grep "5566XXXXXXXX"

# Tudo — modo debug completo
pm2 logs lazaro-ia | grep -iE "BUFFER|PROCESS|GEMINI|TOOL|UAZAPI|LEADBOX|FAIL-SAFE|CONTEXT DEBUG|ERROR"
```

```bash
# Histórico — últimas 500 linhas filtradas
pm2 logs lazaro-ia --lines 500 --nostream | grep -iE "TOOL START|TOOL END|TOOL LOOP"
pm2 logs lazaro-ia --lines 500 --nostream | grep -iE "BUFFER|PROCESS|GEMINI|UAZAPI"
pm2 logs lazaro-ia --lines 500 --nostream | grep -i "CONTEXT DEBUG"
pm2 logs lazaro-ia --lines 500 --nostream | grep -iE "ERROR|WARNING|FAIL"
```

---

## Diagnóstico por Cenário de Problema

### Cenário 1 — IA disparou manutenção mas parou de responder

**O que acontece:** `maintenance_notifier` disparou mensagem D-7, cliente respondeu, IA não detectou o contexto e parou de responder (ou pediu CPF).

**Causa raiz mais comum:** mensagem foi enviada mas `context` não foi salvo no `conversation_history`.

**Diagnóstico rápido:**
```bash
# Ver se contexto foi detectado na última interação do cliente
pm2 logs lazaro-ia --lines 500 --nostream | grep -i "CONTEXT DEBUG"
```

**Sinais no log:**

| Log | Significado |
|---|---|
| `[CONTEXT DEBUG] ENCONTRADO context='manutencao_preventiva' ref_id='<id>'` | ✅ Contexto detectado, IA sabe o que fazer |
| `[CONTEXT DEBUG] Prompt carregado para 'manutencao_preventiva'!` | ✅ Prompt de contexto carregado |
| `[CONTEXT DEBUG] Nenhum context especial encontrado` | ❌ Context não foi salvo no history |
| `[CONTEXT DEBUG] context_prompts vazio ou None` | ❌ Configuração ausente no agente |
| `[CONTEXT DEBUG] Contexto 'manutencao_preventiva' NAO encontrado em context_prompts` | ❌ Contexto não cadastrado |
| `[CONTEXT DEBUG] Contexto 'manutencao_preventiva' esta INATIVO` | ❌ Contexto desativado no banco |

**Verificar no banco se o context foi salvo:**
```sql
SELECT
    remotejid,
    conversation_history->'messages'->-1 AS ultima_mensagem,
    jsonb_path_query_array(
        conversation_history->'messages',
        '$[*] ? (@.context != null)'
    ) AS mensagens_com_contexto
FROM "LeadboxCRM_Ana_14e6e5ce"
WHERE remotejid LIKE '%5511999999999%'
LIMIT 1;
```

**O campo `context` deve aparecer assim nas mensagens salvas:**
```json
{
  "role": "model",
  "context": "manutencao_preventiva",
  "contract_id": "uuid-do-contrato"
}
```
Se `mensagens_com_contexto` vier vazio → o `maintenance_notifier` não salvou o contexto → ver seção "Arquitetura de Jobs de Disparo".

---

### Cenário 2 — IA disse que ia transferir mas não transferiu

**O que acontece:** IA respondeu ao cliente dizendo que vai transferir para atendimento, mas o lead continuou na fila da IA sem ser movido.

**Diagnóstico rápido:**
```bash
# Ver sequência completa da tentativa de transferência
pm2 logs lazaro-ia --lines 500 --nostream | grep -iE "transfer_start|transfer_resolved|transfer_api|transfer_success|transfer_error|transfer_exception"

# Ver só resultado da tool
pm2 logs lazaro-ia --lines 500 --nostream | grep -E "TOOL START.*transferir|TOOL END.*transferir"
```

**Sinais no log — transferência OK:**
```
transfer_start departamento=comercial queue_id=454
transfer_resolved final_queue_id=454 dept_name=comercial
transfer_api_result result={'sucesso': True, 'ticket_id': ...}
transfer_success dept=comercial ticket_id=862709
[TOOL END] transferir_departamento duration=1.23s result=sucesso
```

**Sinais no log — transferência falhou:**

| Log | Causa |
|---|---|
| `handoff_not_configured` | `handoff_triggers` não configurado no agente |
| `transfer_blocked_billing_context` | Lead em contexto de cobrança, transferência bloqueada |
| `leadbox_incomplete_config` | Configuração do Leadbox incompleta |
| `transfer_api_error error="..."` | Erro HTTP na API do Leadbox |
| `transfer_exception error="..."` | Exceção no código durante a tool |
| `leadbox_transfer_http_error` | Timeout ou falha de rede com o Leadbox |
| `[TOOL END] transferir_departamento ... result=erro` | Tool executou mas falhou |
| `[TOOL START]` sem `[TOOL END]` | Tool travou com exceção não capturada |

**Verificar no banco se o lead foi transferido:**
```sql
SELECT
    remotejid,
    "Atendimento_Finalizado",
    current_state,
    paused_at,
    handoff_at,
    transfer_reason,
    ticket_id,
    current_queue_id,
    current_user_id
FROM "LeadboxCRM_Ana_14e6e5ce"
WHERE remotejid LIKE '%5511999999999%'
LIMIT 1;
```

**Lead transferido com sucesso deve ter:**
- `Atendimento_Finalizado = true`
- `current_state = 'human'`
- `handoff_at` = timestamp recente
- `current_queue_id` = ID da fila destino (453, 454, etc.)

---

## Diagnóstico de Webhooks Leadbox

### Referência Rápida — Tenant e Filas

| Campo | Valor |
|---|---|
| Tenant Leadbox (payload real) | `123` |
| Tenant no agente ANA (Supabase `agents`) | `123` |
| Fila IA principal (Ana) | `537` |
| Fila billing | `544` |
| Fila manutenção | `545` |
| Fila atendimento humano (Nathália) | `453` |
| Fila financeiro (Tieli) | `454` |

> ⚠️ O `tenant_id` no Supabase deve ser `"123"`, não `"124"`.
> Se errado, o filtro pula o agente silenciosamente — o log diz "FECHADO" mas o banco não muda.

### Sequência de Eventos por Cenário

**Ticket fechado:**
```
FinishedTicket               → [LEADBOX HANDLER] Ticket X FECHADO
UpdateOnTicket               → [LEADBOX HANDLER] Ticket X FECHADO (duplo, normal)
FinishedTicketHistoricMessages → ignorado (correto)
```

**Lead indo para fila humana:**
```
UpdateOnTicket (queue=453/454) → PAUSANDO → Redis pause SETADA
```

**Lead voltando para fila IA:**
```
UpdateOnTicket (queue=537) → Redis pause LIMPA → Supabase: current_state=ai
```

### Tabela de Sinais de Problema

| Log observado | Causa provável | Ação |
|---|---|---|
| `Payload sem phone ou queueId` | UpdateOnTicket com queueId=null ao fechar ticket | Verificar se FECHADO aparece logo em seguida |
| `FAIL-SAFE ... Supabase vazio` | `current_queue_id=None` no banco | Verificar estado do lead |
| `FAIL-SAFE ... fila humana` | Lead em fila humana — correto | Normal, não é bug |
| `HTTP 500 /tickets?contactId=X` | Ticket recém-criado | Normal, fallback cobre |
| FECHADO no log mas banco não muda | `tenant_id` errado | Verificar `handoff_triggers.tenant_id` |
| Nenhum evento no `lazaro-ia` | Webhook não configurado | Verificar painel do Leadbox |
| `[GEMINI] Inicializando` sem `Resposta recebida` | Timeout Gemini | Buscar `ERROR` no mesmo timestamp |
| `[TOOL START]` sem `[TOOL END]` | Tool travada | Buscar `ERROR` após o `[TOOL START]` |
| `[BUFFER] adicionada` sem `[PROCESS]` | Buffer acumulando | Verificar Redis, considerar restart |
| `CONTEXT DEBUG` Nenhum context encontrado | Job não salvou context no history | Ver seção Jobs de Disparo |
| `transfer_api_error` ou `transfer_exception` | Transferência falhou | Ver campos no banco + logs do Leadbox |

### Verificar Estado de um Lead no Banco

```bash
cd /var/www/lazaro-real/apps/ia && source venv/bin/activate && python3 -c "
from app.integrations.supabase.client import get_supabase_client
client = get_supabase_client()
r = client.table('LeadboxCRM_Ana_14e6e5ce') \
    .select('remotejid,current_queue_id,current_state,ticket_id,Atendimento_Finalizado,handoff_at') \
    .eq('remotejid', 'PHONE@s.whatsapp.net').execute()
print(r.data)
"
```
Substitua `PHONE` pelo número sem `+` (ex: `556697194084`).

### Verificar Tenant e Filas no Agente

```bash
cd /var/www/lazaro-real/apps/ia && source venv/bin/activate && python3 -c "
from app.integrations.supabase.client import get_supabase_client
client = get_supabase_client()
r = client.table('agents').select('name,handoff_triggers').eq('active', True).execute()
for a in r.data:
    ht = a['handoff_triggers'] or {}
    print(a['name'], '| tenant:', ht.get('tenant_id'), '| queue_ia:', ht.get('queue_ia'))
"
```

---

## Comandos de Validação

```bash
# Testes
python -m pytest tests/ -v
python -m pytest tests/test_arquivo.py::Classe::test_metodo -v

# Validar sintaxe antes de reiniciar
python -m py_compile app/arquivo.py && echo "OK"
```

---

## Modo Bombeiro vs Modo Normal

| | Modo Bombeiro | Modo Normal |
|---|---|---|
| Quando usar | Produção caindo agora | Padrão de desenvolvimento |
| Faz | Patch direto, resolve rápido | Planeja → testa → codifica → confirma |
| Depois | **Cria o teste assim que possível** | Teste já existe antes do código |
| Risco | Bug volta sem avisar | Bug não volta |

> O Modo Bombeiro é uma exceção. A dívida técnica gerada deve ser paga logo após.

---

## Segurança

```bash
git ls-files --error-unmatch .env 2>&1  # deve dar erro = não rastreado
ls -la .env                              # deve ser -rw------- (600)
chmod 600 .env
# Nunca hardcode chave de API — sempre os.getenv("NOME_DA_CHAVE")
```

---

## O que NÃO Fazer

- Propor código sem antes ter o plano aprovado
- Escrever teste sem antes ter o plano aprovado
- Escrever código sem antes ter o teste falhando confirmado pelo humano
- Aceitar código da IA sem ler
- Commitar sem rodar os testes
- Usar `except Exception: pass` silenciosamente
- Fazer múltiplas correções em um único commit
- Otimizar antes de ter cobertura de teste
- Ignorar warnings repetidos nos logs
- Deixar `.env` com permissão 644
- Hardcodar chave de API no código
- Rodar `pm2 restart` sem validar sintaxe antes
- **Debugar o serviço errado** — verifique qual serviço processa o endpoint (lazaro-ia vs agnes-agent)
- **Assumir que o log "FECHADO" significa que o Supabase foi atualizado — sempre verificar**
- **Assumir que `[TOOL START]` sem `[TOOL END]` é normal — sempre é um problema**
- **Assumir que a IA transferiu porque ela disse que ia transferir — verificar no banco**

---

## 🔒 Núcleo Inalterável (Martin Fowler Method)

> Baseado no artigo "Refactoring with Code Mods" de Martin Fowler.
> **Regra:** Esses módulos funcionam. Não refatore sem cobertura de teste extensiva e aprovação explícita.

### O que é Núcleo Inalterável?

Código legado que:
1. Está em produção há tempo
2. Funciona sem bugs críticos
3. Já foi debugado extensivamente
4. Tem comportamento conhecido e documentado

**Filosofia Fowler:** IA é útil para *entender* código legado, não para *alterar* diretamente. Se precisar mudar, use **code mods** (scripts que fazem alterações específicas), nunca edição direta via vibe coding.

### Módulos Protegidos

| Módulo | Arquivo(s) Principal | Motivo | Última Estabilização |
|--------|---------------------|--------|---------------------|
| **Fluxo de Mensagens** | `ia_gemini.py` | Pipeline BUFFER→PROCESS→GEMINI→TOOL→UAZAPI estável | 2026-03 |
| **Webhooks Leadbox** | `leadbox_handler.py`, `leadbox.py` | Eventos UpdateOnTicket, FinishedTicket, filas 537/453/454 | 2026-03 |
| **Webhooks Asaas** | `pagamentos.py`, `asaas_webhook_handler.py` | Pipeline de cobrança e confirmação de pagamento | 2026-03 |

### Antes de Mexer em Módulo Protegido

```
[ ] Tenho aprovação explícita do humano para alterar este módulo?
[ ] Li e entendi o fluxo completo (não só o trecho que vou mudar)?
[ ] Existe teste cobrindo o comportamento atual?
[ ] Se não existe teste, vou criar ANTES de alterar?
[ ] A alteração é cirúrgica (< 10 linhas) ou estrutural (> 10 linhas)?
[ ] Se estrutural: propus code mod ao invés de edição direta?
```

### O que Fazer vs. O que Não Fazer

| ✅ Pode | ❌ Não Pode |
|---------|-------------|
| Usar IA para *explicar* o código | Usar IA para *refatorar* direto |
| Adicionar logs de debug | Mudar estrutura de fluxo |
| Corrigir bug pontual com teste | "Melhorar" código que funciona |
| Criar code mod para alteração em massa | Aceitar sugestão de refactor da IA |

### Regra de Três (Fowler)

1. **Primeira vez:** Faz (mesmo que feio)
2. **Segunda vez:** Repete (não otimiza ainda)
3. **Terceira vez:** Refatora

> Não refatore na primeira ou segunda vez. Desapego > Perfeccionismo.

---

## Arquitetura de Jobs de Disparo (CRÍTICO)

Jobs que enviam mensagens automáticas (billing, manutenção, lembretes) DEVEM seguir este padrão completo para que o sistema de detecção de contexto funcione.

### O Problema (Bug 2026-03-11)

O `maintenance_notifier.py` enviava mensagens via UAZAPI mas **não salvava no conversation_history**. Quando o cliente respondia, `[CONTEXT DEBUG] Nenhum context especial encontrado` — a IA não sabia do que se tratava.

### Checklist Obrigatório para Jobs de Disparo

```python
result = await uazapi_client.send_text_message(phone, message)

if result.get("success"):
    await ensure_lead_exists(
        agent=agent, phone=phone,
        customer_name=customer_name,
        lead_origin="tipo_do_disparo",
    )
    await save_message_to_history(
        agent=agent, phone=phone, message=message,
        context="tipo_do_contexto",        # ← CRÍTICO: detect_conversation_context() depende disso
        reference_id=contract_or_payment_id,
    )
    await mark_notification_sent(...)
```

### Campos Obrigatórios na Mensagem Salva

```python
{
    "role": "model",
    "parts": [{"text": "texto da mensagem"}],
    "timestamp": "2026-03-11T12:00:00Z",
    "context": "manutencao_preventiva",  # ← sem isso: [CONTEXT DEBUG] Nenhum context encontrado
    "contract_id": "uuid-do-contrato",
}
```

### Teste Obrigatório para Novos Jobs

```python
def test_job_salva_mensagem_com_contexto():
    await job_de_disparo(...)
    update_args = mock_supabase.client.table.return_value.update.call_args[0][0]
    history = update_args["conversation_history"]
    assert any(m.get("context") == "tipo_esperado" for m in history["messages"])
    assert any(m.get("contract_id") is not None for m in history["messages"])
```

---

## Registro de Lições Aprendidas

> Toda vez que um bug for corrigido sem teste, documente aqui.

| Data | Commit | Problema | Teste Retroativo? |
|------|--------|----------|-------------------|
| 09/03/2026 | 75e5a27 | maintenance_status corrigido sem teste | ⬜ Pendente |
| 11/03/2026 | 0d165be | maintenance_notifier não salvava context no history | ✅ test_maintenance_context_save.py |
| 11/03/2026 | 8418f4c | maintenance_notifier não criava lead com lead_origin | ✅ test_maintenance_context_save.py |
| 12/03/2026 | — | FinishedTicket não disparava handle_ticket_closed | ✅ test_leadbox_update_ticket_null_queue.py |
| 12/03/2026 | — | current_queue_id=None ao fechar ticket (deveria ser 537) | ✅ test_leadbox_update_ticket_null_queue.py |
| 12/03/2026 | — | UpdateOnTicket com queueId=null descartado silenciosamente | ✅ test_leadbox_update_ticket_null_queue.py |
| 12/03/2026 | — | FAIL-SAFE descartava mensagens quando API retornava 500 | ✅ test_failsafe_supabase_fallback.py |
| 12/03/2026 | — | tenant_id=124 no banco (Leadbox manda 123) — filtro silencioso | ⬜ Pendente (fix via SQL direto) |