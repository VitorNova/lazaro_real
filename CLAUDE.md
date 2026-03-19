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
    """
    Mock BASICO do Supabase - para testes que so verificam SELECT.

    Args:
        table_data: Dict com nome_tabela -> lista de registros
                    Ex: {"clientes": [{"id": "1", "nome": "Joao"}]}

    Uso:
        mock = make_supabase_mock({"clientes": [{"id": "1"}]})
        # Simula: supabase.client.table("clientes").select().execute()
    """
    mock = MagicMock()

    def table_side_effect(table_name):
        t = MagicMock()
        data = table_data.get(table_name, [])
        resp = MagicMock()
        resp.data = data

        # SELECT chains
        t.select.return_value.eq.return_value.eq.return_value \
         .limit.return_value.execute.return_value = resp
        t.select.return_value.eq.return_value \
         .limit.return_value.execute.return_value = resp
        t.select.return_value.or_.return_value \
         .limit.return_value.execute.return_value = resp
        t.select.return_value.execute.return_value = resp
        t.update.return_value.eq.return_value.execute.return_value = MagicMock()
        t.insert.return_value.execute.return_value = MagicMock()
        return t

    mock.client.table.side_effect = table_side_effect
    return mock


def make_supabase_mock_with_capture(table_data: dict) -> MagicMock:
    """
    Mock AVANCADO do Supabase - captura chamadas INSERT/UPDATE para assertions.

    Args:
        table_data: Dict com nome_tabela -> lista de registros

    Uso:
        mock = make_supabase_mock_with_capture({"leads": []})
        # ... executa codigo ...

        # Verificar INSERT:
        insert_calls = mock._insert_calls.get("leads", [])
        assert len(insert_calls) == 1
        assert insert_calls[0]["campo"] == "valor_esperado"

        # Verificar UPDATE:
        update_calls = mock._update_calls.get("leads", [])
        assert len(update_calls) == 1
        assert update_calls[0]["status"] == "novo_status"
    """
    mock = MagicMock()
    mock._insert_calls = {}  # {table_name: [dados_inseridos, ...]}
    mock._update_calls = {}  # {table_name: [dados_atualizados, ...]}

    def table_side_effect(table_name):
        t = MagicMock()
        data = table_data.get(table_name, [])
        resp = MagicMock()
        resp.data = data

        # SELECT chains
        t.select.return_value.eq.return_value.eq.return_value \
         .limit.return_value.execute.return_value = resp
        t.select.return_value.eq.return_value \
         .limit.return_value.execute.return_value = resp
        t.select.return_value.or_.return_value \
         .limit.return_value.execute.return_value = resp
        t.select.return_value.execute.return_value = resp

        # INSERT - captura argumentos
        def capture_insert(insert_data):
            if table_name not in mock._insert_calls:
                mock._insert_calls[table_name] = []
            mock._insert_calls[table_name].append(insert_data)
            insert_result = MagicMock()
            insert_result.execute.return_value = MagicMock(data=[{"id": "new-id"}])
            return insert_result

        t.insert.side_effect = capture_insert

        # UPDATE - captura argumentos
        def capture_update(update_data):
            if table_name not in mock._update_calls:
                mock._update_calls[table_name] = []
            mock._update_calls[table_name].append(update_data)
            update_chain = MagicMock()
            update_chain.eq.return_value.execute.return_value = MagicMock(data=[{"id": "updated-id"}])
            return update_chain

        t.update.side_effect = capture_update

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
            "clientes": [{"id": "abc123", "status": "ativo", "nome": "Joao"}]
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

### Supabase — Quando usar cada mock

| Cenário | Mock a usar |
|---------|-------------|
| Testar leitura (SELECT) | `make_supabase_mock` |
| Verificar se INSERT foi chamado com dados corretos | `make_supabase_mock_with_capture` |
| Verificar se UPDATE foi chamado com dados corretos | `make_supabase_mock_with_capture` |
| Testar fluxos que criam ou atualizam registros | `make_supabase_mock_with_capture` |

### Supabase — Mock basico (SELECT)

```python
# Simular tabela com dados
mock = make_supabase_mock({
    "clientes": [{"id": "1", "nome": "Joao", "status": "ativo"}]
})
# Simular tabela vazia
mock = make_supabase_mock({"clientes": []})
```

### Supabase — Mock com captura (INSERT/UPDATE)

```python
# Arrange - mock que captura chamadas
mock = make_supabase_mock_with_capture({"leads": []})

# Act - executa codigo que faz INSERT ou UPDATE
await funcao_que_insere_ou_atualiza(mock)

# Assert - verificar INSERT
insert_calls = mock._insert_calls.get("leads", [])
assert len(insert_calls) == 1, "Deveria ter inserido um registro"
assert insert_calls[0]["nome"] == "Novo Lead"
assert insert_calls[0]["status"] == "ativo"

# Assert - verificar UPDATE
update_calls = mock._update_calls.get("leads", [])
assert len(update_calls) == 1, "Deveria ter atualizado um registro"
assert update_calls[0]["status"] == "convertido"
```

### Supabase — Verificar estrutura complexa (ex: conversation_history)

```python
mock = make_supabase_mock_with_capture({"mensagens": []})
await funcao_que_salva_historico(mock)

insert_calls = mock._insert_calls.get("mensagens", [])
insert_data = insert_calls[0]

# Verificar estrutura do JSONB
history = insert_data["conversation_history"]
messages = history.get("messages", [])
assert len(messages) == 2
assert messages[0]["role"] == "user"
assert messages[1]["role"] == "model"
assert messages[1].get("context") == "manutencao_preventiva"
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

### Cenário 3 — Cliente não recebeu cobrança

**O que acontece:** Um cliente específico não recebeu a mensagem de cobrança esperada (D-2, D-1, D0, ou D+N para vencidos).

**Causas raiz mais comuns:**
1. Job de billing não executou (lock, dia não útil, fora do horário)
2. Cobrança não existe no Asaas ou já está paga
3. Cliente sem telefone válido cadastrado
4. Notificação já enviada (duplicata bloqueada)
5. Falha no envio via UAZAPI/Leadbox

**Diagnóstico rápido:**
```bash
# Ver se job de billing executou hoje
pm2 logs lazaro-ia --lines 500 --nostream | grep -iE "billing_v2_start|billing_v2_complete|billing_v2_skipped"

# Ver notificações enviadas para telefone específico
pm2 logs lazaro-ia --lines 500 --nostream | grep "5566XXXXXXXX" | grep -i billing

# Ver erros de billing
pm2 logs lazaro-ia --lines 500 --nostream | grep -iE "BILLING JOB.*ERROR|DISPATCH_LOG.*FAILED"
```

**Sinais no log:**

| Log | Significado |
|---|---|
| `billing_v2_start agents_count=N` | ✅ Job iniciou, processando N agentes |
| `billing_v2_complete sent=X skipped=Y errors=Z` | ✅ Job finalizou com estatísticas |
| `billing_v2_skipped reason=already_running` | ❌ Outra instância já estava rodando |
| `billing_v2_skipped reason=not_business_day` | ❌ Fim de semana ou feriado |
| `billing_v2_skipped reason=outside_hours` | ❌ Fora do horário comercial (8h-20h) |
| `[BILLING JOB] Notificacao enviada: pay_XXX` | ✅ Cobrança enviada com sucesso |
| `[BILLING JOB] Notificacao ja enviada para pay_XXX` | ⚠️ Duplicata bloqueada (normal) |
| `[BILLING JOB] Cliente *** sem telefone valido` | ❌ Telefone ausente ou inválido no Asaas |
| `[BILLING JOB] Erro ao enviar notificacao pay_XXX` | ❌ Falha no envio |
| `[DISPATCH_LOG] billing/overdue FAILED: pay_XXX` | ❌ Falha registrada no dispatch_log |
| `[LEADBOX PUSH] ticket_check_failed` | ❌ Não conseguiu verificar ticket no Leadbox |

**Onde buscar o token do Asaas:**

O token **não é global** — cada agente tem seu próprio token no banco:

| Local | Campo | Uso |
|---|---|---|
| Tabela `agents` | `asaas_api_key` | **Fonte primária** (multi-tenant) |
| Variável de ambiente | `ASAAS_API_KEY` | Fallback legado |

```bash
# Buscar token do agente no banco
cd /var/www/lazaro-real/apps/ia && source venv/bin/activate && python3 -c "
from app.integrations.supabase.client import get_supabase_client
client = get_supabase_client()
r = client.table('agents').select('name,asaas_api_key').eq('active', True).execute()
for a in r.data:
    key = a.get('asaas_api_key', '')
    masked = f'{key[:10]}...{key[-4:]}' if key and len(key) > 14 else 'NAO CONFIGURADO'
    print(f\"{a['name']}: {masked}\")
"
```

**Status possíveis no Asaas (usar na query):**

| Status | Significado |
|---|---|
| `PENDING` | Aguardando pagamento |
| `OVERDUE` | Vencido (não pago após due_date) |
| `RECEIVED` | Pago (saldo disponível) |
| `CONFIRMED` | Pago (aguardando compensação bancária) |
| `CANCELLED` | Cancelado |

**Verificar se cobrança existe no Asaas:**
```bash
cd /var/www/lazaro-real/apps/ia && source venv/bin/activate && python3 -c "
import httpx
from app.integrations.supabase.client import get_supabase_client

# Buscar token do agente Ana
client = get_supabase_client()
agent = client.table('agents').select('asaas_api_key').eq('name', 'Ana').limit(1).execute().data[0]
api_key = agent['asaas_api_key']

# Buscar cobrança por customer_id
customer_id = 'cus_XXXXXXXX'  # substituir

resp = httpx.get(
    f'https://api.asaas.com/v3/payments?customer={customer_id}&status=PENDING,OVERDUE,RECEIVED',
    headers={'access_token': api_key, 'User-Agent': 'lazaro-ia'}
)
print(resp.json())
"
```

> ⚠️ **Asaas é a fonte da verdade** — se o status no Asaas é `RECEIVED` mas o `asaas_cobrancas` local ainda mostra `PENDING`, o webhook não foi processado corretamente.

**Verificar no banco se disparo foi registrado:**
```sql
-- dispatch_log: registros de disparo
SELECT
    id, job_type, notification_type, phone, status,
    error_message, failure_reason, created_at
FROM dispatch_log
WHERE phone LIKE '%5566XXXXXXXX%'
  AND job_type = 'billing'
ORDER BY created_at DESC
LIMIT 10;

-- billing_notifications: controle de duplicatas
SELECT
    payment_id, notification_type, scheduled_date, status,
    error_message, sent_at
FROM billing_notifications
WHERE phone LIKE '%5566XXXXXXXX%'
ORDER BY scheduled_date DESC
LIMIT 10;
```

**Verificar se context foi salvo no conversation_history:**
```sql
SELECT
    remotejid,
    jsonb_path_query_array(
        conversation_history->'messages',
        '$[*] ? (@.context == "billing")'
    ) AS mensagens_billing
FROM "leadbox_messages_Ana_14e6e5ce"
WHERE remotejid LIKE '%5566XXXXXXXX%'
LIMIT 1;
```

**O campo `context` deve aparecer assim:**
```json
{
  "role": "model",
  "parts": [{"text": "mensagem de cobrança..."}],
  "context": "billing",
  "reference_id": "pay_XXXXXXXX"
}
```

---

### Cenário 4 — Lead no departamento errado após disparo de cobrança

**O que acontece:** Após disparo de cobrança, o lead aparece em uma fila errada (ex: fila 537 quando deveria estar na 544, ou fila humana 453 quando deveria estar na 544).

**Causas raiz mais comuns:**
1. `leadbox_push_silent` não conseguiu mover o ticket para a fila correta
2. PUT de confirmação de fila falhou após PUSH
3. Webhook do Leadbox moveu o lead de volta para outra fila
4. `dispatch_departments` não configurado corretamente para billing

**Diagnóstico rápido:**
```bash
# Ver em qual fila o lead está agora (log)
pm2 logs lazaro-ia --lines 500 --nostream | grep "5566XXXXXXXX" | grep -iE "queue|fila|push"

# Ver se PUSH funcionou
pm2 logs lazaro-ia --lines 500 --nostream | grep -iE "LEADBOX PUSH.*PUT ok|LEADBOX PUSH.*PUSH ok|queue_confirmation_failed"

# Ver eventos de mudança de fila
pm2 logs lazaro-ia --lines 500 --nostream | grep "5566XXXXXXXX" | grep -iE "UpdateOnTicket|queueId"
```

**Sinais no log:**

| Log | Significado |
|---|---|
| `[LEADBOX PUSH] PUT ok (ticket existia): ticketId=X -> queueId=544` | ✅ Ticket movido para fila billing |
| `[LEADBOX PUSH] PUSH ok (ticket novo): queueId=544, ticketId=X` | ✅ Ticket criado na fila billing |
| `[LEADBOX PUSH] PUT confirmação: ticketId=X -> queueId=544` | ✅ Confirmação de fila executada |
| `[LEADBOX PUSH] PUT confirmação falhou` | ❌ Ticket pode estar na fila errada |
| `[LEADBOX PUSH] ticket_check_failed` | ❌ Não verificou ticket, pode ter duplicado |
| `[LEADBOX PUSH] Config incompleta` | ❌ `handoff_triggers` não configurado |
| `UpdateOnTicket (queue=453)` | ⚠️ Lead foi para fila humana (atendente pegou?) |
| `UpdateOnTicket (queue=537)` | ⚠️ Lead voltou para fila genérica |

**Verificar em qual fila o lead está no banco:**
```bash
cd /var/www/lazaro-real/apps/ia && source venv/bin/activate && python3 -c "
from app.integrations.supabase.client import get_supabase_client
client = get_supabase_client()
r = client.table('LeadboxCRM_Ana_14e6e5ce') \
    .select('remotejid,current_queue_id,current_state,ticket_id,billing_context') \
    .eq('remotejid', 'PHONE@s.whatsapp.net').execute()
print(r.data)
"
```
Substitua `PHONE` pelo número sem `+` (ex: `556697194084`).

**Referência de filas:**

| Fila | ID | Descrição |
|---|---|---|
| Fila IA principal (Ana) | `537` | Onde leads novos caem |
| **Fila billing** | **`544`** | Contexto de cobrança |
| Fila manutenção | `545` | Contexto de manutenção |
| Fila atendimento humano | `453` | Nathália |
| Fila financeiro | `454` | Tieli |

**Verificar configuração de dispatch_departments:**
```bash
cd /var/www/lazaro-real/apps/ia && source venv/bin/activate && python3 -c "
from app.integrations.supabase.client import get_supabase_client
client = get_supabase_client()
r = client.table('agents').select('name,handoff_triggers').eq('active', True).execute()
for a in r.data:
    ht = a['handoff_triggers'] or {}
    dispatch = ht.get('dispatch_departments', {})
    print(a['name'])
    print('  billing:', dispatch.get('billing', 'NAO CONFIGURADO'))
    print('  maintenance:', dispatch.get('maintenance', 'NAO CONFIGURADO'))
"
```

**Estrutura esperada de dispatch_departments:**
```json
{
  "dispatch_departments": {
    "billing": {
      "queueId": 544,
      "userId": 1095,
      "name": "Cobrança"
    },
    "maintenance": {
      "queueId": 545,
      "userId": 1095,
      "name": "Manutenção"
    }
  }
}
```

**Corrigir manualmente a fila de um lead:**

```bash
# Via API Leadbox (recomendado)
cd /var/www/lazaro-real/apps/ia && source venv/bin/activate && python3 -c "
import httpx
from app.integrations.supabase.client import get_supabase_client

# Buscar config do agente
client = get_supabase_client()
agent = client.table('agents').select('handoff_triggers').eq('active', True).limit(1).execute().data[0]
ht = agent['handoff_triggers']

# PUT no ticket
ticket_id = 123456  # substituir pelo ID real do ticket
queue_id = 544      # fila destino (544=billing, 545=manutenção, 537=IA)
user_id = 1095      # usuário que assumirá

resp = httpx.put(
    f\"{ht['api_url']}/tickets/{ticket_id}\",
    json={'queueId': queue_id, 'userId': user_id},
    headers={'Authorization': f\"Bearer {ht['api_token']}\"}
)
print(resp.status_code, resp.text)
"
```

```sql
-- Corrigir fila no Supabase (apenas emergência - não sincroniza com Leadbox)
UPDATE "LeadboxCRM_Ana_14e6e5ce"
SET current_queue_id = 544,
    current_state = 'active'
WHERE remotejid = 'PHONE@s.whatsapp.net';
```

> ⚠️ A correção via Supabase NÃO move o ticket no Leadbox. O lead pode voltar para a fila errada no próximo evento de webhook. Use sempre a API do Leadbox para garantir sincronia.

---

### Cenário 5 — IA perdeu contexto após pagamento confirmado

**O que acontece:** Cliente pagou, recebeu mensagem de confirmação ("Confirmamos o recebimento do seu pagamento..."), respondeu essa mensagem, mas a IA continua enviando link de pagamento como se ainda não tivesse pago.

**Exemplo real (lead 556699133755, 2026-03-19):**
```
[model] ctx=billing "Sua mensalidade vence amanhã..."  ← Cobrança D-1
[user]  ctx=VAZIO  "[sticker]"                         ← Cliente respondeu
[model] ctx=VAZIO  "É só abrir o link que enviei..."   ← IA ignorou que já pagou
```

**Causa raiz:** A mensagem de confirmação de pagamento foi **enviada via WhatsApp** mas **não foi salva** no `conversation_history`. Quando o cliente responde, a IA não tem contexto de que o pagamento foi recebido.

**Por que não salvou?** `payment_message_service.py:salvar_no_historico()` faz busca **exata** por telefone:
```python
phone_jid = f"{phone}@s.whatsapp.net"
.eq("remotejid", phone_jid)  # ← Busca exata, sem variantes
```
Se o telefone no Asaas é `5566991337555` (com 9 extra) mas o lead está cadastrado como `556699133755` (sem 9 extra), a busca **não encontra o lead** e retorna silenciosamente.

**Diagnóstico rápido:**
```bash
# Ver se mensagem de confirmação foi salva
pm2 logs lazaro-ia --lines 500 --nostream | grep -i "PAYMENT MSG"

# Ver se webhook PAYMENT_RECEIVED foi processado
pm2 logs lazaro-ia --lines 500 --nostream | grep -iE "PAYMENT_RECEIVED|PAYMENT_CONFIRMED"
```

**Sinais no log:**

| Log | Significado |
|---|---|
| `[PAYMENT MSG] Confirmação enviada: payment_id=X` | ✅ Mensagem enviada |
| `[PAYMENT MSG] Mensagem salva no conversation_history` | ✅ Contexto salvo |
| `[PAYMENT MSG] Lead não encontrado para XXX` | ❌ **Bug!** Telefone não bateu |
| `[PAYMENT MSG] Confirmação já enviada anteriormente` | ⚠️ Duplicata (normal) |
| `[ASAAS WEBHOOK] Pagamento recebido: pay_XXX` | ✅ Webhook processado |

**Verificar no banco se mensagem de confirmação foi salva:**
```bash
cd /var/www/lazaro-real/apps/ia && source venv/bin/activate && python3 -c "
from app.integrations.supabase.client import get_supabase_client
client = get_supabase_client()

phone = '5566XXXXXXXX'  # substituir
r = client.table('leadbox_messages_Ana_14e6e5ce') \
    .select('conversation_history') \
    .eq('remotejid', f'{phone}@s.whatsapp.net').execute()

if r.data and r.data[0].get('conversation_history'):
    msgs = r.data[0]['conversation_history'].get('messages', [])
    confirmacoes = [m for m in msgs if m.get('context') == 'pagamento_confirmado']
    print(f'Total msgs: {len(msgs)}')
    print(f'Confirmações de pagamento: {len(confirmacoes)}')
    for c in confirmacoes:
        print(f\"  payment_id: {c.get('payment_id')}, timestamp: {c.get('timestamp')}\")
    if not confirmacoes:
        print('⚠️ NENHUMA mensagem com context=pagamento_confirmado!')
        print('Últimas 5 mensagens:')
        for m in msgs[-5:]:
            print(f\"  [{m.get('role')}] ctx={m.get('context','')} | {str(m.get('parts',[{}])[0].get('text',''))[:50]}...\")
"
```

**Verificar se pagamento foi recebido no Asaas mas não refletiu no sistema:**
```sql
-- Comparar status no cache local vs. Asaas
SELECT
    id, customer_id, status, value, due_date,
    ia_cobrou, ia_recebeu, updated_at
FROM asaas_cobrancas
WHERE customer_id IN (
    SELECT asaas_customer_id FROM "LeadboxCRM_Ana_14e6e5ce"
    WHERE remotejid LIKE '%5566XXXXXXXX%'
)
ORDER BY due_date DESC
LIMIT 5;
```

**Correção manual — forçar contexto de pagamento:**
```bash
cd /var/www/lazaro-real/apps/ia && source venv/bin/activate && python3 -c "
from app.integrations.supabase.client import get_supabase_client
from datetime import datetime
client = get_supabase_client()

phone = '5566XXXXXXXX'  # substituir
payment_id = 'pay_XXXXXXXX'  # substituir

# Buscar lead
r = client.table('leadbox_messages_Ana_14e6e5ce') \
    .select('id, conversation_history') \
    .eq('remotejid', f'{phone}@s.whatsapp.net').execute()

if r.data:
    lead = r.data[0]
    history = lead.get('conversation_history') or {'messages': []}
    msgs = history.get('messages', [])

    # Adicionar mensagem de confirmação
    msgs.append({
        'role': 'model',
        'parts': [{'text': 'Confirmamos o recebimento do seu pagamento. Obrigada!'}],
        'timestamp': datetime.utcnow().isoformat(),
        'context': 'pagamento_confirmado',
        'payment_id': payment_id,
    })

    client.table('leadbox_messages_Ana_14e6e5ce').update({
        'conversation_history': {'messages': msgs}
    }).eq('id', lead['id']).execute()

    print(f'Contexto de pagamento adicionado ao lead {lead[\"id\"]}')
"
```

> ⚠️ **Bug conhecido:** `payment_message_service.py` não usa `generate_phone_variants()` para buscar o lead. Se o telefone no Asaas difere do cadastro (9 extra), a busca falha silenciosamente. Correção pendente.

---

### Cenário 6 — Cobrança parou antes do tempo configurado

**O que acontece:** Lead recebeu cobrança no D-1 ou D-2, mas parou de receber nos dias seguintes (D+1, D+2, etc.) antes de atingir o máximo configurado na régua.

**Causas raiz mais comuns:**
1. `maxAttempts` atingido (padrão: 15)
2. Pagamento mudou de status no Asaas (RECEIVED, CANCELLED)
3. Lead em fila humana (pausa ativa no Redis)
4. `overdueDays` não inclui o dia atual na configuração
5. Erro silencioso no job de billing

**Diagnóstico rápido — ver configuração da régua:**
```bash
cd /var/www/lazaro-real/apps/ia && source venv/bin/activate && python3 -c "
from app.integrations.supabase.client import get_supabase_client
import json
client = get_supabase_client()
r = client.table('agents').select('name,asaas_config').eq('name', 'Ana').execute()
if r.data:
    config = r.data[0].get('asaas_config', {}).get('autoCollection', {})
    print('=== Configuração da Régua ===')
    print(f\"reminderDays: {config.get('reminderDays', [2, 1])}\")
    print(f\"onDueDate: {config.get('onDueDate', True)}\")
    after = config.get('afterDue', {})
    print(f\"afterDue.enabled: {after.get('enabled', True)}\")
    print(f\"afterDue.maxAttempts: {after.get('maxAttempts', 15)}\")
    print(f\"afterDue.overdueDays: {after.get('overdueDays', list(range(1,16)))}\")
"
```

**Ver histórico de cobranças do lead (por telefone):**
```bash
cd /var/www/lazaro-real/apps/ia && source venv/bin/activate && python3 -c "
from app.integrations.supabase.client import get_supabase_client
client = get_supabase_client()

phone = '5566XXXXXXXX'  # substituir

r = client.table('billing_notifications') \
    .select('payment_id,notification_type,days_from_due,scheduled_date,status,sent_at') \
    .ilike('phone', f'%{phone}%') \
    .order('scheduled_date', desc=True) \
    .limit(20) \
    .execute()

print(f'=== Notificações para {phone} ({len(r.data)} encontradas) ===')
print()
print(f'{\"DATA\":<12} | {\"TIPO\":<10} | {\"DIAS\":<5} | {\"STATUS\":<8} | PAYMENT_ID')
print('-' * 70)
for n in r.data:
    dias = f\"D{n['days_from_due']:+d}\" if n.get('days_from_due') is not None else '?'
    print(f\"{n['scheduled_date']:<12} | {n['notification_type']:<10} | {dias:<5} | {n['status']:<8} | {n['payment_id']}\")
"
```

**Ver dispatch_log com falhas e motivos:**
```bash
cd /var/www/lazaro-real/apps/ia && source venv/bin/activate && python3 -c "
from app.integrations.supabase.client import get_supabase_client
client = get_supabase_client()

phone = '5566XXXXXXXX'  # substituir

r = client.table('dispatch_log') \
    .select('reference_id,notification_type,days_from_due,status,failure_reason,deferred_reason,created_at') \
    .ilike('phone', f'%{phone}%') \
    .eq('job_type', 'billing') \
    .order('created_at', desc=True) \
    .limit(20) \
    .execute()

print(f'=== Dispatch Log para {phone} ({len(r.data)} encontrados) ===')
print()
for d in r.data:
    reason = d.get('failure_reason') or d.get('deferred_reason') or ''
    dias = f\"D{d['days_from_due']:+d}\" if d.get('days_from_due') is not None else '?'
    print(f\"{d['created_at'][:10]} | {d['notification_type']:<10} | {dias:<5} | {d['status']:<8} | {reason:<20} | {d['reference_id']}\")
"
```

**Verificar se lead está pausado (fila humana):**
```bash
cd /var/www/lazaro-real/apps/ia && source venv/bin/activate && python3 -c "
from app.integrations.redis.client import get_redis_client
import asyncio

async def check():
    redis = await get_redis_client()
    phone = '5566XXXXXXXX'  # substituir
    agent_id = '14e6e5ce-4627-4e38-aac8-f0191669ff53'  # Ana

    key = f'pause:{agent_id}:{phone}'
    value = await redis.get(key)

    if value:
        print(f'⚠️ LEAD PAUSADO: {key} = {value}')
        print('Lead está em fila humana, billing não envia.')
    else:
        print(f'✅ Lead NÃO está pausado (key {key} não existe)')

asyncio.run(check())
"
```

**Verificar status atual do pagamento no Asaas:**
```bash
cd /var/www/lazaro-real/apps/ia && source venv/bin/activate && python3 -c "
import httpx
from app.integrations.supabase.client import get_supabase_client
client = get_supabase_client()

payment_id = 'pay_XXXXXXXX'  # substituir

# Buscar token
agent = client.table('agents').select('asaas_api_key').eq('name', 'Ana').limit(1).execute().data[0]

resp = httpx.get(
    f'https://api.asaas.com/v3/payments/{payment_id}',
    headers={'access_token': agent['asaas_api_key'], 'User-Agent': 'lazaro-ia'}
)
data = resp.json()
print(f\"Payment: {data.get('id')}\")
print(f\"Status: {data.get('status')}\")
print(f\"Value: R$ {data.get('value')}\")
print(f\"DueDate: {data.get('dueDate')}\")
print(f\"PaymentDate: {data.get('paymentDate')}\")
"
```

**Tabela de sinais:**

| Sinal | Causa | Ação |
|---|---|---|
| Total enviadas >= `maxAttempts` | Atingiu limite configurado | Normal, aumentar `maxAttempts` se necessário |
| Status `RECEIVED` ou `CONFIRMED` no Asaas | Cliente já pagou | Normal, billing para automaticamente |
| Status `CANCELLED` no Asaas | Cobrança cancelada | Verificar por que foi cancelada |
| `pause:agent_id:phone` existe no Redis | Lead em fila humana | Aguardar ou remover pausa manualmente |
| Dia atual não está em `overdueDays` | Configuração incompleta | Ajustar `overdueDays` no agente |
| `deferred_reason` = `human_queue_*` | Disparo adiado | Ver `/api/jobs/retry-deferred` |
| Nenhuma notificação após D0 | `afterDue.enabled = false` | Verificar configuração |

**Resumo por lead — quantas cobranças por tipo:**
```sql
SELECT
    notification_type,
    status,
    COUNT(*) as total,
    MIN(scheduled_date) as primeira,
    MAX(scheduled_date) as ultima
FROM billing_notifications
WHERE phone LIKE '%5566XXXXXXXX%'
GROUP BY notification_type, status
ORDER BY notification_type, status;
```

---

## Diagnóstico de Webhooks Leadbox

### Conceito Fundamental: Ticket = Conversa Ativa

> **Regras de ouro do Leadbox — entenda antes de debugar:**

1. **Não existe lead com conversa ativa sem ticket** — Se está conversando, TEM ticket
2. **Ticket fechado = Sem conversa** — Lead aguarda próximo contato, `ticket_id` deve ser null
3. **Abertura automática** — Qualquer mensagem (cliente OU empresa) cria ticket automaticamente
4. **userId vem null** — Ticket novo chega sem atendente, sistema força via `PUT /tickets/{id}`

**Fluxo típico:**
```
FECHAMENTO: FinishedTicket → status=closed → ticket_id limpo do lead

REABERTURA: Mensagem enviada → Leadbox cria ticket NOVO (ID diferente!)
            → UpdateOnTicket com userId=null, queueId=537
            → Sistema força: PUT /tickets/{id} com userId=1095
```

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
| 18/03/2026 | e2afcc8 | salvar_dados_lead retornava texto literal da tool — IA parava o fluxo após salvar CPF | ✅ test_customer_tools_salvar_cpf.py |

---

## Fixtures Centralizadas

> Dados de teste ficam em `tests/fixtures.py`. Nunca redefina inline o que já existe aqui.
> Usa Faker com locale pt_BR — dados brasileiros reais gerados automaticamente.

### Instalar
```bash
cd /var/www/lazaro-real/apps/ia
source venv/bin/activate
pip install faker
```

### Uso básico
```python
from tests.fixtures import make_pessoa, make_lead, make_webhook, LEAD_SEM_NOME

# Gerar dados dinâmicos
pessoa = make_pessoa()
lead   = make_lead(queue_id=537, tenant_id=123)
webhook = make_webhook(event="FinishedTicket", queue_id=537, tenant_id=123)

# Edge cases prontos
LEAD_SEM_NOME       # nome=None — bug que já quebrou
LEAD_HUMANO         # lead em fila humana
WEBHOOK_SEM_QUEUE   # queue=None — bug que já quebrou
WEBHOOK_TENANT_ERRADO # tenant errado — filtro silencioso
```

### Nos testes
```python
from tests.fixtures import make_lead, LEAD_SEM_NOME

def test_sistema_nao_quebra_com_lead_sem_nome():
    mock = make_supabase_mock({"leads": [LEAD_SEM_NOME]})
    resultado = processar_lead(mock, LEAD_SEM_NOME["remotejid"])
    assert resultado is not None

def test_lead_normal_processado():
    lead = make_lead(queue_id=537, tenant_id=123)
    mock = make_supabase_mock({"leads": [lead]})
    resultado = processar_lead(mock, lead["remotejid"])
    assert resultado["status"] == "processado"
```

### Regra

Cada bug que quebrou em produção → vira um edge case em `tests/fixtures.py`.
Nunca mais o mesmo bug volta sem o teste falhar primeiro.