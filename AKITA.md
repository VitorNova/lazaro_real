# AKITA.md — Metodologia Anti-Vibe Coding

> Baseado no artigo "Do Zero à Produção em Uma Semana" e live do Fábio Akita.
> Este arquivo define como Claude Code deve se comportar neste projeto.
> **Leia este arquivo antes de qualquer ação.**

## Princípio Central

O Akita não odeia IA. Ele odeia **mediocridade vendida como produtividade**.

Vibe Coding = intuição. Jogar prompt, aceitar o que vem, não ler o código.
Akita Way = **disciplina**. Você pensa, a IA pilota. Você é o engenheiro, ela é o par.

> "Sem teste, cada mudança é uma aposta."

## Regras Absolutas para Claude Code

1. Nunca escreva uma feature sem ter o teste primeiro.
2. Nunca aceite código que não passa nos testes existentes.
3. Nunca edite diretamente arquivos críticos sem validação.
4. Nunca use sed ou substituição direta sem confirmar o trecho exato antes.
5. Sempre documente erros e correções no CLAUDE.md.
6. Se a IA errou, não corrija manualmente — explique o erro e peça para refazer.
7. Um problema por vez. Um commit por correção.

## Fluxo Correto

VOCÊ = quem pensa, planeja, revisa
IA   = quem pilota, escreve código, executa

Ciclo: Planejamento → Design → TESTE → Código → Otimização → Deploy
                                 ↑
                    (sempre antes do código)

## Fase 1 — Planejamento

Antes de qualquer código:
- Defina a stack completa
- Escreva as histórias do projeto
- Decida a estrutura de diretórios
- Documente variáveis de ambiente
- Documente tudo no CLAUDE.md

Nunca peça à IA para "criar um SaaS". Peça para implementar uma feature específica com arquitetura já definida.

## Fase 2 — Testes Primeiro (TDD Obrigatório)

Regra de ouro: Sem teste = sem código.

Como escrever o teste antes:
1. Descreva o comportamento esperado em português claro
2. Peça para a IA escrever apenas o teste, sem implementação
3. O teste deve usar mocks para dependências externas
4. Exija que o teste falhe primeiro
5. Só depois peça a implementação

### Mock padrão Supabase:
```python
from unittest.mock import MagicMock

def _make_supabase_mock(table_data: dict):
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
        t.update.return_value.eq.return_value \
         .execute.return_value = MagicMock()
        t.insert.return_value.execute.return_value = MagicMock()
        return t
    mock.client.table.side_effect = table_side_effect
    return mock
```

### Mock Redis:
```python
import fakeredis
redis_mock = fakeredis.FakeRedis()
```

### Mock HTTP externo (UAZAPI):
```python
from unittest.mock import patch, AsyncMock
with patch("app.services.uazapi.httpx.AsyncClient") as mock_http:
    mock_http.return_value.__aenter__.return_value.post.return_value = AsyncMock(
        status_code=200,
        json=lambda: {"success": True}
    )
```

### Estrutura de teste padrão:
```python
class TestNomeDaFuncionalidade:
    """
    TDD — Bug/Feature [DATA]:
    Descrição do problema real que motivou esse teste.
    """

    def test_cenario_feliz(self):
        mock = _make_supabase_mock({"tabela": [{"id": "123"}]})
        resultado = funcao_testada(mock, dados_validos)
        assert resultado == esperado

    def test_cenario_de_borda(self):
        mock = _make_supabase_mock({"tabela": []})
        resultado = funcao_testada(mock, dados_invalidos)
        assert resultado is None

    def test_bug_real_NOME_CLIENTE_data(self):
        """
        Bug real: descreva o que aconteceu em produção
        Causa: descreva a causa raiz
        Correção: descreva o que foi corrigido
        """
        mock = _make_supabase_mock({"tabela": [estado_que_causou_bug]})
        resultado = funcao_testada(mock, dados_do_bug)
        assert resultado == comportamento_correto
```

## Fase 3 — Código

Só começa aqui depois que os testes existem e falham.

- Implemente apenas o suficiente para o teste passar
- Arquivo com mais de 300 linhas = precisa ser quebrado
- Nenhum except Exception: pass — sempre logue o erro

Ciclo por feature:
1. Teste escrito e falhando
2. Implementação mínima
3. pytest -v → todos passando
4. Refactor se necessário
5. pytest -v → ainda passando
6. Commit

## Fase 4 — Otimização

Só depois que o código passa em todos os testes:
- Identifique gargalos reais
- Quebre arquivos grandes em módulos focados
- Elimine código duplicado
- Nunca otimize sem ter teste cobrindo o comportamento

## Fase 5 — Deploy
```bash
# 1. Todos os testes passando?
python -m pytest tests/ -v

# 2. Sintaxe válida?
python -m py_compile app/arquivo_modificado.py

# 3. Commit limpo
git add -A
git commit -m "tipo(escopo): o que foi feito

Bug: descrição
Causa: causa raiz
Correção: o que foi alterado
Teste: nome_do_teste.py N/N"

# 4. Reiniciar
pm2 restart nome-do-servico

# 5. Verificar logs
pm2 logs nome-do-servico --lines 50
```

## Mensagem de Commit Padrão
```
tipo(escopo): descrição curta

Bug: o que estava acontecendo
Causa: por que acontecia
Correção: o que foi alterado
Teste: arquivo.py X/X passando
```

Tipos: fix, feat, refactor, test, chore, docs

## Modo Bombeiro vs Modo Akita

Modo Bombeiro (emergência): corrija rápido, aceite patches diretos.
Modo Akita (padrão): entenda → teste → corrija → confirme → commit.

A diferença não é a urgência — é o que você faz DEPOIS.
Bug sem teste = bug que vai voltar.

## Desapego do Código

Quando a IA errar:
- Não corrija manualmente no arquivo
- Explique o erro em linguagem clara
- Peça que ela refaça
- Documente o padrão de erro no CLAUDE.md

## Segurança

- Nunca commite .env
- Arquivos .env com chmod 600
- Chaves de API nunca hardcoded
```bash
ls -la .env                              # deve ser -rw------- (600)
git ls-files --error-unmatch .env 2>&1  # deve dar erro = não está no git
```

## Comandos Úteis
```bash
python -m pytest tests/ -v
python -m pytest tests/test_arquivo.py::Classe::test_metodo -v
pm2 logs lazaro-ia | grep -iE "ERROR|WARNING|WEBHOOK"
pm2 logs lazaro-ia --lines 200 --nostream
python -m py_compile app/arquivo.py && echo "OK"
```

## O que NÃO fazer

- Aceitar código da IA sem ler
- Commitar sem rodar os testes
- Escrever feature antes do teste
- Usar except Exception: pass silenciosamente
- Fazer múltiplas correções no mesmo commit
- Otimizar antes de ter cobertura de teste
- Ignorar warnings repetidos nos logs
- Deixar .env com permissão 644
- Hardcodar chave de API

"Depois que você passa por essa imersão desapegado do código, você nunca mais vê vibe coding da mesma forma." — Akita
