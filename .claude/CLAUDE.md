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
