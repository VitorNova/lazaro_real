# CLAUDE.md — Metodologia Anti-Vibe Coding (Akita Way)

> **Leia este arquivo inteiro antes de qualquer ação.**
> Baseado no artigo "Do Zero à Produção em Uma Semana" — Fábio Akita.

---

## ⚡ TL;DR para Claude Code

Você é o par programador. **Você escreve. Eu penso.**

A ordem é sempre:
**1. Lê → 2. Entende → 3. Planeja → 4. EU APROVO → 5. Testa → 6. EU CONFIRMO → 7. Codifica**

Código é **sempre a última etapa.** Nunca a primeira.

---

## Filosofia Central

**Vibe Coding** = jogar prompt, aceitar o que vem, não ler o código, confiar na intuição.  
**Akita Way** = você pensa e planeja, a IA executa e escreve. Disciplina acima de intuição.

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
[ ] O humano aprovou o plano? ← AGUARDE RESPOSTA
```
→ Se o humano não aprovou: **PARE. Não escreva nada.**

Formato obrigatório do plano:
```
PLANO:
Problema: [o que está acontecendo]
Causa provável: [onde e por que acontece]
Solução proposta: [o que será alterado e como]
Arquivo(s) afetado(s): [lista]
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
    Cria um mock do Supabase configurado com dados por tabela.

    Uso:
        mock = make_supabase_mock({
            "clientes": [{"id": "abc", "nome": "João"}],
            "contratos": [{"id": "x1", "cliente_id": "abc"}],
        })
    """
    mock = MagicMock()

    def table_side_effect(table_name):
        t = MagicMock()
        data = table_data.get(table_name, [])

        resp = MagicMock()
        resp.data = data

        # SELECT encadeado padrão
        t.select.return_value.eq.return_value.eq.return_value \
         .limit.return_value.execute.return_value = resp

        t.select.return_value.eq.return_value \
         .limit.return_value.execute.return_value = resp

        t.select.return_value \
         .execute.return_value = resp

        # UPDATE / INSERT
        t.update.return_value.eq.return_value \
         .execute.return_value = MagicMock()

        t.insert.return_value \
         .execute.return_value = MagicMock()

        return t

    mock.client.table.side_effect = table_side_effect
    return mock


def make_redis_mock() -> fakeredis.FakeRedis:
    """
    Cria um Redis em memória para testes. Comportamento idêntico ao Redis real.

    Uso:
        redis = make_redis_mock()
        redis.set("chave", "valor")
        assert redis.get("chave") == b"valor"
    """
    return fakeredis.FakeRedis()


def make_http_mock(status_code: int = 200, json_response: dict = None):
    """
    Cria um mock de cliente HTTP (httpx.AsyncClient) para mockar UAZAPI,
    Asaas, ou qualquer API HTTP externa.

    Uso:
        with make_http_mock(200, {"success": True}) as mock_http:
            resultado = await funcao_que_chama_api(...)
    """
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

    Contexto:
        Descreva aqui em português o que motivou esses testes.
        Ex: "Clientes em manutenção estavam recebendo cobranças indevidamente."

    Causa:
        O que estava errado no código.

    Correção:
        O que foi alterado para resolver.
    """

    def test_cenario_principal_funciona(self):
        """O comportamento esperado no caminho feliz."""
        mock_db = make_supabase_mock({
            "clientes": [{"id": "abc123", "status": "ativo", "nome": "João"}]
        })

        resultado = funcao_a_testar(mock_db, parametro_valido)

        assert resultado is not None
        assert resultado["status"] == "esperado"

    def test_retorna_none_quando_sem_dados(self):
        """Deve retornar None/[] quando a tabela está vazia."""
        mock_db = make_supabase_mock({"clientes": []})

        resultado = funcao_a_testar(mock_db, parametro_valido)

        assert resultado is None

    def test_bug_real_DESCRICAO_DATA(self):
        """
        Bug real: [descreva o que acontecia em produção]
        Ex: cobrança sendo enviada para cliente com status 'manutencao'

        Causa: campo maintenance_status não era verificado antes do envio
        Correção: adicionado check antes do disparo
        """
        mock_db = make_supabase_mock({
            "clientes": [{"id": "abc123", "status": "manutencao", "nome": "João"}]
        })

        resultado = funcao_a_testar(mock_db, parametro_bug)

        # O comportamento correto é NÃO enviar cobrança
        assert resultado is None

    def test_nao_envia_quando_redis_pausado(self):
        """Se a chave de pausa existe no Redis, não deve processar."""
        redis = make_redis_mock()
        redis.set("pause:agent_id:5511999999999", "1")

        resultado = funcao_que_verifica_pausa(redis, agent_id="agent_id", phone="5511999999999")

        assert resultado is False

    @pytest.mark.asyncio
    async def test_chama_api_externa_com_sucesso(self):
        """Verifica integração com API HTTP externa (ex: UAZAPI)."""
        mock_db = make_supabase_mock({"mensagens": [{"id": "m1", "texto": "oi"}]})

        with make_http_mock(200, {"success": True}):
            resultado = await funcao_que_chama_uazapi(mock_db, phone="5511999999999")

        assert resultado is True

    @pytest.mark.asyncio
    async def test_trata_falha_da_api_externa(self):
        """Quando a API retorna erro, deve logar e não estourar exceção."""
        mock_db = make_supabase_mock({"mensagens": [{"id": "m1"}]})

        with make_http_mock(500, {"error": "internal server error"}):
            resultado = await funcao_que_chama_uazapi(mock_db, phone="5511999999999")

        assert resultado is False  # falhou mas não levantou exceção
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
# SELECT com filtro simples
mock = make_supabase_mock({"tabela": [{"id": "1", "campo": "valor"}]})

# UPDATE que precisa verificar se foi chamado
mock_table = mock.client.table("tabela")
mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock()

# Verificar se update foi chamado com os dados certos
mock_table.update.assert_called_once_with({"campo": "novo_valor"})

# INSERT e verificar
mock_table.insert.assert_called_once()
```

### Redis — Cenários Comuns

```python
redis = make_redis_mock()

# Simular chave de pausa
redis.set("pause:agent_id:5511999999999", "1")

# Simular TTL
redis.setex("chave", 3600, "valor")  # expira em 1h

# Simular ausência de chave
assert redis.get("chave_inexistente") is None

# Simular contexto de conversa
redis.set("context:phone:5511999999999", '{"historico": []}')
```

### HTTP Externo — UAZAPI / Asaas / Qualquer API

```python
# Mock de POST com sucesso
with patch("app.services.uazapi.httpx.AsyncClient") as MockClient:
    instance = MockClient.return_value.__aenter__.return_value
    instance.post = AsyncMock(return_value=AsyncMock(
        status_code=200,
        json=lambda: {"messageId": "abc123"}
    ))
    resultado = await enviar_mensagem(phone="5511999999999", texto="oi")

# Mock de falha HTTP
with patch("app.services.uazapi.httpx.AsyncClient") as MockClient:
    instance = MockClient.return_value.__aenter__.return_value
    instance.post = AsyncMock(return_value=AsyncMock(
        status_code=500,
        json=lambda: {"error": "server error"}
    ))
    resultado = await enviar_mensagem(phone="5511999999999", texto="oi")
    assert resultado is False
```

### APScheduler / Jobs Agendados

```python
from unittest.mock import patch, MagicMock

def test_job_nao_executa_fora_do_horario():
    with patch("app.jobs.cobrar.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2025, 1, 1, 3, 0)  # 3h da manhã
        resultado = verificar_se_deve_executar()
        assert resultado is False

def test_job_executa_no_horario_correto():
    with patch("app.jobs.cobrar.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2025, 1, 1, 9, 0)  # 9h BRT
        resultado = verificar_se_deve_executar()
        assert resultado is True
```

---

## Estrutura de Commit

```
tipo(escopo): descrição curta em português

Bug: o que estava acontecendo (ex: cobrança enviada a cliente em manutenção)
Causa: por que acontecia (ex: status não era verificado antes do envio)
Correção: o que foi alterado (ex: adicionado check maintenance_status em cobrar_cliente())
Teste: test_cobranca.py 5/5 passando
```

**Tipos válidos:** `fix` `feat` `refactor` `test` `chore` `docs`

---

## Modo Bombeiro vs Modo Akita

| | Modo Bombeiro | Modo Akita |
|---|---|---|
| Quando usar | Produção caindo agora | Padrão de desenvolvimento |
| Faz | Patch direto, resolve rápido | Planeja → testa → codifica → confirma |
| Depois | **Cria o teste assim que possível** | Teste já existe antes do código |
| Risco | Bug volta sem avisar | Bug não volta |

> O Modo Bombeiro é uma exceção. A dívida técnica gerada deve ser paga logo após.

---

## Comandos de Validação

```bash
# Rodar todos os testes
python -m pytest tests/ -v

# Rodar teste específico
python -m pytest tests/test_arquivo.py::Classe::test_metodo -v

# Validar sintaxe antes de reiniciar
python -m py_compile app/arquivo.py && echo "OK"

# Logs em tempo real
pm2 logs agente-ia | grep -iE "ERROR|WARNING|PROCESS|WEBHOOK"

# Últimas 200 linhas
pm2 logs agente-ia --lines 200 --nostream
```

---

## Segurança

```bash
# .env nunca no git
git ls-files --error-unmatch .env 2>&1  # deve dar erro = não rastreado

# .env com permissão restrita
ls -la .env  # deve ser -rw------- (600)
chmod 600 .env

# Nunca hardcode chave de API no código
# Sempre via variável de ambiente: os.getenv("NOME_DA_CHAVE")
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

---

## Arquitetura de Jobs de Disparo (CRÍTICO)

Jobs que enviam mensagens automáticas (billing, manutenção, lembretes) DEVEM seguir este padrão completo para que o sistema de detecção de contexto funcione.

### O Problema (Bug 2026-03-11)

O `maintenance_notifier.py` foi criado incompleto. Enviava mensagens via UAZAPI mas **não salvava no conversation_history**. Quando o cliente respondia, a IA não detectava o contexto e pedia CPF em vez de já ter os dados.

**Sintoma:** Cliente recebe mensagem D-7, responde, IA age sem contexto.
**Causa:** Mensagem enviada mas não registrada no histórico com `context` e `contract_id`.

### Fluxo de Detecção de Contexto

```
Cliente responde
    ↓
Webhook WhatsApp recebe
    ↓
detect_conversation_context(conversation_history)
    ↓
Procura mensagem com campo `context` (ex: 'manutencao_preventiva', 'cobranca')
    ↓
SE ENCONTRAR: retorna (context, contract_id) → IA tem dados completos
SE NÃO ENCONTRAR: retorna (None, None) → IA pergunta CPF
```

### Checklist Obrigatório para Jobs de Disparo

Todo job que envia mensagem automática DEVE implementar:

```python
# 1. Enviar mensagem via UAZAPI
result = await uazapi_client.send_text_message(phone, message)

if result.get("success"):
    # 2. OBRIGATÓRIO: Criar/garantir lead existe
    await ensure_lead_exists(
        agent=agent,
        phone=phone,
        customer_name=customer_name,
        lead_origin="tipo_do_disparo",  # ex: "manutencao_preventiva", "billing_system"
    )

    # 3. OBRIGATÓRIO: Salvar no conversation_history com contexto
    await save_message_to_history(
        agent=agent,
        phone=phone,
        message=message,
        context="tipo_do_contexto",      # ex: "manutencao_preventiva", "cobranca"
        reference_id=contract_or_payment_id,
    )

    # 4. Atualizar status no banco
    await mark_notification_sent(...)
```

### Campos Obrigatórios na Mensagem Salva

```python
{
    "role": "model",
    "parts": [{"text": "texto da mensagem enviada"}],
    "timestamp": "2026-03-11T12:00:00Z",
    "context": "manutencao_preventiva",  # ← CRÍTICO para detect_conversation_context()
    "contract_id": "uuid-do-contrato",   # ← OU reference_id para pagamentos
}
```

### Comparação: Certo vs Errado

| Aspecto | billing_charge.py (CERTO) | maintenance_notifier.py (ERRADO - antes do fix) |
|---------|---------------------------|------------------------------------------------|
| Envia UAZAPI | ✅ | ✅ |
| ensure_lead_exists() | ✅ | ❌ Não existia |
| save_to_conversation_history() | ✅ com context='cobranca' | ❌ Não existia |
| Detecção de contexto funciona | ✅ | ❌ |

### Teste Obrigatório para Novos Jobs

Ao criar um novo job de disparo, o teste DEVE verificar:

```python
def test_job_salva_mensagem_com_contexto():
    """Garante que a mensagem é salva com context para detect_conversation_context()."""
    # ... mock setup ...

    await job_de_disparo(...)

    # CRÍTICO: Verificar que save_to_history foi chamado com context
    update_args = mock_supabase.client.table.return_value.update.call_args[0][0]
    history = update_args["conversation_history"]

    assert any(m.get("context") == "tipo_esperado" for m in history["messages"])
    assert any(m.get("contract_id") is not None for m in history["messages"])
```

---

## Registro de Lições Aprendidas

> Toda vez que um bug for corrigido em Modo Bombeiro (sem teste), documente aqui.
> O objetivo é zerar essa lista com testes retroativos.

| Data | Commit | Problema | Teste Retroativo? |
|------|--------|----------|-------------------|
| 09/03/2026 | 75e5a27 | maintenance_status corrigido sem teste | ⬜ Pendente |
| 11/03/2026 | 0d165be | maintenance_notifier não salvava context no history | ✅ test_maintenance_context_save.py |
| 11/03/2026 | 8418f4c | maintenance_notifier não criava lead com lead_origin | ✅ test_maintenance_context_save.py |

---

> "Depois que você passa por essa imersão desapegado do código,
> você nunca mais vê vibe coding da mesma forma." — Akita