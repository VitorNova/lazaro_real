# Lazaro-v2 Plataforma IA para Atendimento WhatsApp

## Stack
- IA Service (apps/ia/): Python 3.11 + FastAPI + APScheduler + Gemini (via LangChain)
- API (apps/api/): TypeScript + Fastify
- Frontend (apps/web/): React + Vite
- DB: Supabase (PostgreSQL) + Redis (cache/sessoes)
- Integracoes: UAZAPI (WhatsApp), Asaas (pagamentos), Google Calendar
- Deploy: Hetzner VPS, PM2, Docker

## Comandos Essenciais

pm2 logs agente-ia --lines 200 --nostream
pm2 restart agente-ia
pm2 restart lazaro-api
pm2 restart lazaro-web
cd /var/www/lazaro-v2/apps/ia && python -c "from app.webhooks.mensagens import *; print('OK')"
grep -rn "from.*import" --include="*.py" apps/ia/
grep -rn "require\|import" --include="*.ts" apps/api/

## Arquivos Criticos (NAO edite sem ler inteiro)

mensagens.py       4438L  apps/ia/app/webhooks/  Webhook+IA+Envio+Estado
pagamentos.py      2983L  apps/ia/app/webhooks/  Webhooks Asaas+processamento
main.py            2068L  apps/ia/app/           FastAPI+Scheduler+Rotas
cobrar_clientes.py 1839L  apps/ia/app/jobs/      Job cobranca automatica
reengajar_leads.py 1465L  apps/ia/app/jobs/      Job follow-up
asaas.handler.ts   2401L  apps/api/src/handlers/ Handler TS pagamentos

## Regras Obrigatorias

IMPORTANT: NUNCA edite arquivos monoliticos sem ler o arquivo INTEIRO primeiro.
IMPORTANT: NUNCA mova dois arquivos ao mesmo tempo durante refatoracao.
IMPORTANT: Apos qualquer mudanca de import, teste: python -c "from modulo import *"
YOU MUST deixar arquivo-ponte com re-export ao mover modulos.
YOU MUST commitar a cada micro-mudanca: refactor(fase-X.Y): descricao

## Servicos Duplicados (Python e TypeScript)
Asaas, UAZAPI, Gemini, Google Calendar, Supabase, Redis existem em ambas.
Ao corrigir bug numa integracao, VERIFIQUE se precisa corrigir na outra.

## Agentes: Agnes (SDR), Salvador (follow-up), Diana (campanhas), Athena (analytics)

## Refatoracao
Consulte REFACTOR_LOG.md para status. Skill lazaro-refactor tem plano de 9 fases.
NUNCA pule fases. Um passo por vez. Valide antes de seguir.

## Verificacao Critica
LEIA o codigo real antes de afirmar. Classifique certeza:
VERIFICADO | ALTA CONFIANCA | SUPOSICAO | ESPECULACAO

## MCPs Obrigatorios

YOU MUST usar sequential thinking (mcp sequentialthinking) ANTES de qualquer tarefa com mais de 1 passo. Isso inclui: refatoracao, debugging, criar novo arquivo, mover codigo. Pense em etapas ANTES de agir.

YOU MUST usar context7 para consultar documentacao atualizada ANTES de usar APIs de: FastAPI, LangChain, Supabase, Redis, APScheduler, Gemini. Nunca assuma a API de memoria - consulte primeiro.

## Git
IMPORTANT: NUNCA use git add -A durante refatoracao. Sempre adicione apenas os arquivos que voce modificou naquele passo. Use git add <arquivo> explicitamente.

## Ambiente Python
O Python da aplicacao roda via PM2. Para testar imports use:
cd /var/www/lazaro-v2/apps/ia && python3 -m py_compile app/<arquivo>.py
NAO existe virtualenv separado. O python3 do sistema tem as dependencias.

## Regras de Contexto
IMPORTANT: Para arquivos com mais de 500 linhas, use o subagente explorer-lazaro (context: fork) para mapear funcoes e dependencias. NUNCA leia arquivos grandes direto no contexto principal.
IMPORTANT: NUNCA agrupe multiplos passos num unico commit. Um passo = um commit. Se a skill diz 1.6, 1.7, 1.8 sao passos separados, commite cada um separadamente.
IMPORTANT: Se a skill define meta de linhas para um modulo (ex: 200-400 linhas) e o resultado passou, quebre mais antes de seguir.

## Estado do Refactoring
ALWAYS leia REFACTOR_LOG.md ANTES de qualquer tarefa de refatoracao. Ele contem: fase atual, checklist do que ja foi feito, hashes dos commits, e proximos passos. NUNCA assuma o estado - consulte o log.

## Estrategia de Extracao (CRITICO)
NUNCA edite o arquivo monolito (mensagens.py, pagamentos.py, cobrar_clientes.py, reengajar_leads.py) durante a extracao. A estrategia e:
1. Criar o modulo novo com o codigo copiado do monolito
2. py_compile no modulo novo
3. Commitar SOMENTE o modulo novo
4. NAO adicione imports no monolito. NAO remova codigo do monolito. NAO toque no monolito.
5. A integracao (imports + remocao do codigo duplicado) sera feita em uma fase separada APOS teste em producao.

Se voce sentir vontade de editar o monolito durante uma extracao, PARE e releia esta regra.

## Validacao de Sintaxe
Use SOMENTE py_compile para validar sintaxe. NUNCA use "python3 -c import" porque o ambiente do Claude Code NAO tem as dependencias instaladas (fastapi, structlog, etc). Se py_compile passar, esta OK. Se um import falhar por ModuleNotFoundError, isso NAO e um bug - e limitacao do ambiente.

NUNCA altere imports de producao (ex: trocar structlog por logging) para "corrigir" erros que so existem no ambiente de teste.

## Escopo por Sessao
Cada comando do usuario = UMA sub-fase (ex: 2.2, NAO 2.2+2.3+2.4). Se o usuario pedir "faca a fase 2.2", faca SOMENTE 2.2. Crie o modulo, valide sintaxe, commite, atualize REFACTOR_LOG.md. PARE e reporte.

Se o usuario pedir "faca as fases 2.2 a 2.4", faca uma por vez com commit separado entre cada uma. NUNCA comece 2.3 sem ter commitado 2.2.

## Infraestrutura de Producao
IMPORTANTE: O codigo em producao NAO e /var/www/lazaro-v2/. Producao roda em /var/www/phant/.
- agente-ia (Python/FastAPI porta 3005): /var/www/phant/agente-ia/
- agnes-agent (TypeScript/Fastify porta 3000): /var/www/phant/agnes-agent/

## Logs e Debugging
- Todos os logs: pm2 logs agente-ia --lines 200 --nostream
- Webhook UAZAPI: pm2 logs agnes-agent --lines 200 --nostream | grep -i "uazapi\|webhook"
- Webhook Leadbox: pm2 logs agnes-agent --lines 200 --nostream | grep -i "leadbox\|NewMessage\|QueueChange"
- Webhook Asaas (pagamentos): pm2 logs agente-ia --lines 200 --nostream | grep -i "asaas\|payment\|webhook"
- Job Cobranca: pm2 logs agente-ia --lines 200 --nostream | grep -i "billing\|cobran\|charge"
- Job Manutencao: pm2 logs agente-ia --lines 200 --nostream | grep -i "maintenance\|manut\|preventiva"
- Job Follow-up: pm2 logs agente-ia --lines 200 --nostream | grep -i "follow.up\|salvador"
- Arquivos de log: /root/.pm2/logs/agente-ia-out.log e /root/.pm2/logs/agente-ia-error.log

SEMPRE consulte os logs ANTES de propor solucao para bugs. Nunca assuma a causa.
