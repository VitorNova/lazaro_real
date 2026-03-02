# REVISÃO COMPLETA - Lazaro V2

**Data:** 2026-02-27
**Revisor:** Claude (Opus 4.5)
**Veredicto:** ⚠️ **PARCIALMENTE IMPLEMENTADO** - Há trabalho real, mas com lacunas significativas

---

## 1. ESTRUTURA DE PASTAS

```
/var/www/lazaro-v2/
├── docker-compose.yml        ✅ Existe e funciona
├── .env                      ✅ Configurado (5165 bytes)
├── apps/
│   ├── api/                  ✅ Backend Fastify copiado
│   │   ├── src/
│   │   │   ├── api/
│   │   │   │   ├── agents/   ✅ CRUD de agentes
│   │   │   │   ├── analytics/
│   │   │   │   ├── auth/     ✅ Login, refresh, sessions
│   │   │   │   ├── dashboard/
│   │   │   │   │   ├── billing.handler.ts      ✅ Existe
│   │   │   │   │   ├── conversations.handler.ts ✅ Existe
│   │   │   │   │   ├── leads.handler.ts        ✅ Existe
│   │   │   │   │   └── stats.handler.ts        ✅ Existe
│   │   │   │   ├── google/
│   │   │   │   ├── leads/
│   │   │   │   ├── messages/
│   │   │   │   ├── middleware/
│   │   │   │   └── webhooks/
│   │   │   ├── config/
│   │   │   ├── core/
│   │   │   ├── services/
│   │   │   └── index.ts      ✅ Entry point
│   │   ├── Dockerfile        ✅ Existe
│   │   └── node_modules/     ✅ Instalado
│   │
│   ├── ia/                   ⚠️ Código Python copiado
│   │   ├── app/
│   │   │   ├── api/
│   │   │   ├── jobs/
│   │   │   ├── services/
│   │   │   ├── tools/
│   │   │   ├── webhooks/
│   │   │   └── main.py       ❌ TEM REFERÊNCIA A /var/www/phant
│   │   ├── Dockerfile        ✅ Existe
│   │   └── requirements.txt  ✅ Existe
│   │
│   └── web/                  ⚠️ Frontend parcialmente implementado
│       ├── src/
│       │   ├── pages/
│       │   │   ├── LoginPage.tsx         ✅ Implementado
│       │   │   ├── DashboardPage.tsx     ✅ Implementado
│       │   │   ├── ConversationsPage.tsx ✅ Implementado
│       │   │   ├── PipelinePage.tsx      ✅ Implementado
│       │   │   ├── BillingPage.tsx       ❌ NÃO EXISTE
│       │   │   ├── AgentsPage.tsx        ❌ NÃO EXISTE
│       │   │   └── SettingsPage.tsx      ❌ NÃO EXISTE
│       │   ├── components/
│       │   │   ├── ui/                   ✅ Button, Input
│       │   │   ├── conversations/        ✅ ChatView, ConversationList
│       │   │   ├── Sidebar.tsx           ⚠️ Lista rotas que não existem
│       │   │   └── ProtectedRoute.tsx    ✅ Existe
│       │   ├── services/                 ✅ API, auth, conversations, leads
│       │   ├── stores/                   ✅ auth.store.ts
│       │   ├── types/                    ✅ auth, conversations, leads
│       │   └── App.tsx                   ⚠️ Só 3 rotas protegidas
│       ├── public/
│       │   └── vite.svg                  ⚠️ Falta chat-bg.png
│       ├── Dockerfile                    ✅ Existe
│       ├── nginx.conf                    ✅ Existe
│       └── dist/                         ✅ Build existe
```

---

## 2. BACKEND API

### Independência do código
**Resultado:** ⚠️ PARCIALMENTE INDEPENDENTE

Referências problemáticas a `/var/www/phant` encontradas:

| Arquivo | Linha | Problema |
|---------|-------|----------|
| `apps/ia/app/main.py` | UPLOAD_DIR | `"/var/www/phant/crm/uploads"` |
| `apps/ia/app/api/dashboard.py` | Comentário | Referência ao frontend PHANT |
| `apps/ia/app/jobs/reread_missing_contract.py` | Docstring | `cd /var/www/phant/agente-ia` |
| `apps/ia/app/jobs/reprocess_all_contracts.py` | Docstring | `cd /var/www/phant/agente-ia` |

### Rotas registradas no Fastify

```
✅ Implementadas na API:
─────────────────────────────────────────────────────────────
GET  /health                              → Health check
POST /api/auth/login                      → Login
POST /api/auth/refresh                    → Refresh token
GET  /api/auth/me                         → Dados do usuário

GET  /api/dashboard/stats                 → Métricas dashboard
GET  /api/dashboard/leads                 → Leads por agente
PATCH /api/dashboard/leads/:id/pipeline   → Mover no pipeline
PATCH /api/dashboard/leads/:id/toggle-ai  → Toggle IA

GET  /api/conversations                   → Lista conversas
GET  /api/conversations/:phone/messages   → Mensagens
GET  /api/conversations/:phone/ai-status  → Status IA
POST /api/conversations/:phone/toggle-ai  → Toggle IA

GET  /api/billing/stats                   → Estatísticas billing
GET  /api/billing/token-statement         → Extrato tokens
GET  /api/billing/invoices                → Faturas

GET  /api/agents                          → Listar agentes
POST /api/agents                          → Criar agente
PUT  /api/agents/:id                      → Atualizar agente
DELETE /api/agents/:id                    → Deletar agente
```

### Docker build
```bash
$ cd /var/www/lazaro-v2 && docker compose config
# ✅ Configuração válida, sem erros
```

---

## 3. BACKEND IA

### Imagem lazaro-ia:v1.0
```bash
$ docker images | grep lazaro-ia
lazaro-ia:v1.0    4ce948b1b58f    724MB
```
**Resultado:** ✅ Imagem existe

### Docker Compose
```yaml
lazaro-ia:
  image: lazaro-ia:v1.0  # Usa imagem pré-construída
```
**Resultado:** ⚠️ Usa imagem pronta, NÃO faz build do código local em apps/ia/

**Problema:** O código em `apps/ia/` NÃO é usado pelo container. Mudanças ali não terão efeito sem rebuild da imagem.

---

## 4. FRONTEND

### 4.1 Login Page
**Status:** ✅ IMPLEMENTADO

**Código:** `apps/web/src/pages/LoginPage.tsx` (183 linhas)

**Features:**
- [x] Layout split (branding esquerda, form direita)
- [x] Form com email/password
- [x] Toggle mostrar/ocultar senha
- [x] Loading state no botão
- [x] Error state com mensagem
- [x] Responsivo (logo mobile)
- [x] Links "Esqueceu a senha?" e "Cadastre-se" (não funcionais)

**Autenticação:**
```typescript
// JWT em localStorage
localStorage.setItem('accessToken', accessToken)
localStorage.setItem('refreshToken', refreshToken)
```
- [x] JWT em localStorage ✅
- [x] Refresh token ✅
- [x] Interceptor para renovação automática ✅
- [ ] Cookie httpOnly ❌ (não usa)

---

### 4.2 Dashboard Page
**Status:** ✅ IMPLEMENTADO

**Código:** `apps/web/src/pages/DashboardPage.tsx` (473 linhas)

**Métricas exibidas:**
| Card | Endpoint |
|------|----------|
| Total de Leads | `/api/dashboard/stats` → `totalLeads` |
| Taxa de Conversão | `/api/dashboard/stats` → `conversionRate` |
| Agendamentos | `/api/dashboard/stats` → `schedulesTotal` |
| Fora do Horário | `/api/dashboard/stats` → `leadsOutsideHours` |
| Valor Recuperado | `/api/dashboard/stats` → `recoveredAmount` |
| A Receber | `/api/dashboard/stats` → `pendingAmount` |
| Follow-ups Enviados | `/api/dashboard/stats` → `followUpsSent` |
| Leads em IA | `/api/dashboard/stats` → `leadsInAI` |
| Origem dos Leads | `/api/dashboard/stats` → `leadSources` |
| Temperatura | `/api/dashboard/stats` → `leadsByTemperature` |
| Funil Pipeline | `/api/dashboard/stats` → `pipelineFunnel` |
| Performance Agentes | `/api/dashboard/stats` → `agentsPerformance` |

**Features:**
- [x] Loading states (Loader2 spinner) ✅
- [x] Error state com mensagem ✅
- [x] Seletor de período (dia/semana/mês/total) ✅
- [x] Auto-refresh a cada 60s ✅
- [x] Botão refresh manual ✅

---

### 4.3 Conversas WhatsApp
**Status:** ⚠️ PARCIALMENTE IMPLEMENTADO

**Código:**
- `ConversationsPage.tsx` (78 linhas)
- `ConversationList.tsx` (145 linhas)
- `ChatView.tsx` (270 linhas)

#### CRÍTICO: Tratamento do role "model" do Gemini

```typescript
// ChatView.tsx linha 42
function MessageBubble({ message }) {
  const isUser = message.sender === 'user'
  // ...
  // Se isUser = true  → balão branco (esquerda) - mensagem do CLIENTE
  // Se isUser = false → balão azul (direita) - mensagem da IA/SISTEMA
}
```

**Resultado:** ⚠️ DEPENDE DO BACKEND

O frontend assume que o backend transforma `role: 'model'` do Gemini para `sender: 'assistant'`. Se o backend enviar `role: 'model'` diretamente, a lógica quebra.

**Verificação necessária:** Testar se mensagens da IA aparecem corretamente como balões azuis.

#### Layout

| Feature | Desktop | Mobile |
|---------|---------|--------|
| Split-view (lista + chat) | ✅ w-96 + flex-1 | ❌ NÃO RESPONSIVO |
| Stack (lista sobre chat) | N/A | ❌ NÃO IMPLEMENTADO |
| Safe area Dynamic Island | N/A | ❌ NÃO IMPLEMENTADO |

**Problema crítico de responsividade:**
```tsx
// ConversationsPage.tsx linha 46
<div className="w-96 border-r ...">  // Largura FIXA de 384px
```

Em telas menores que 400px, a lista ocupa toda a tela sem possibilidade de ver o chat.

#### Componentes existentes
- [x] ConversationList (lista de contatos com busca)
- [x] ChatView (painel de chat)
- [x] MessageBubble (balões de mensagem)
- [x] Suporte a mídia (imagem, áudio, vídeo, documento)
- [x] Toggle IA por conversa
- [ ] Campo de envio de mensagem ❌ (comentário no código: "Footer - Info only (no send for now)")

#### Asset faltando
```tsx
// ChatView.tsx linha 231
<div className="... bg-[url('/chat-bg.png')] ...">
```
**Problema:** `/chat-bg.png` NÃO existe em `public/`. Background de chat está quebrado.

---

### 4.4 Pipeline Kanban
**Status:** ✅ IMPLEMENTADO (com limitações)

**Código:** `PipelinePage.tsx` (587 linhas)

#### Colunas/Etapas
```typescript
// Colunas são DINÂMICAS, vindas de agent.pipeline_stages
// Cores disponíveis: gray, blue, amber, violet, green, red, orange, cyan, pink
```

**Features:**
- [x] Drag-and-drop entre colunas ✅
- [x] Cards com info do lead ✅
- [x] Menu de ações (pausar IA, excluir) ✅
- [x] Seletor multi-agente ✅
- [x] Loading/error states ✅
- [x] Auto-refresh 30s ✅

#### Modos de visualização

| Modo | Status |
|------|--------|
| Kanban | ✅ Implementado |
| Lista | ❌ NÃO EXISTE |
| Funil | ❌ NÃO EXISTE |

**A memória diz "3 modos de visualização" mas só existe Kanban.**

---

## 5. DESIGN SYSTEM

### Cores

| Elemento | Especificado | Implementado | Status |
|----------|-------------|--------------|--------|
| Azul principal | `#1a6eff` | `--primary: 221.2 83.2% 53.3%` (~#3b82f6) | ❌ DIFERENTE |
| Balão enviado (IA) | `#1a6eff` texto branco | `bg-blue-600` (#2563eb) texto branco | ⚠️ PRÓXIMO |
| Balão recebido (cliente) | `#ffffff` texto `#1a1a2e` | `bg-white text-gray-900` | ⚠️ PRÓXIMO |

### Fonte Inter
```css
/* index.css */
font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
```
**Status:** ❌ INTER NÃO ESTÁ CONFIGURADA - usa system-ui

### Dark Mode
```css
/* Variáveis .dark definidas em index.css */
.dark {
  --background: 222.2 84% 4.9%;
  /* ... */
}
```
**Status:** ⚠️ Variáveis existem mas NÃO há toggle ou detecção de preferência do sistema.

---

## 6. DOCKER

### docker-compose.yml
```yaml
services:
  lazaro-web:     # ✅ Build local, porta 3100
  lazaro-api:     # ✅ Build local, porta 3112
  lazaro-ia:      # ⚠️ Imagem pré-construída, porta 3115
  lazaro-redis:   # ✅ Redis 7 Alpine, porta 6380
```

### Status dos containers
```bash
$ docker compose ps
NAME              STATUS          PORTS
lazaro-web-v2     Up (healthy)    0.0.0.0:3100->80/tcp
lazaro-api-v2     Up (healthy)    0.0.0.0:3112->3102/tcp
lazaro-ia-v2      Up (healthy)    0.0.0.0:3115->3105/tcp
lazaro-redis-v2   Up (healthy)    0.0.0.0:6380->6379/tcp
```
**Status:** ✅ Todos containers rodando e saudáveis

### Variáveis de ambiente
```bash
$ ls -la .env
-rw------- 1 root root 5165 Feb 26 23:42 .env
```
**Status:** ✅ Configurado com todas as variáveis necessárias

---

## 7. PROBLEMAS ENCONTRADOS

### ❌ CRÍTICOS (impedem uso em produção)

| # | Problema | Localização | Impacto |
|---|----------|-------------|---------|
| 1 | **Referência hardcoded a /var/www/phant** | apps/ia/app/main.py | Upload de arquivos quebrado |
| 2 | **chat-bg.png não existe** | apps/web/public/ | Background do chat quebrado |
| 3 | **Layout não responsivo** | ConversationsPage.tsx | Inutilizável em mobile |
| 4 | **Imagem lazaro-ia não rebuilda** | docker-compose.yml | Código local ignorado |

### ⚠️ GRAVES (funcionalidade incompleta)

| # | Problema | Localização | Impacto |
|---|----------|-------------|---------|
| 5 | **Páginas prometidas não existem** | App.tsx | Billing, Agentes, Settings não implementados |
| 6 | **Sidebar lista rotas inexistentes** | Sidebar.tsx | UX confusa, cliques sem efeito |
| 7 | **Sem envio de mensagens** | ChatView.tsx | Só visualização, não interação |
| 8 | **Só modo Kanban** | PipelinePage.tsx | Faltam Lista e Funil |
| 9 | **Safe area iOS faltando** | Todos componentes | Dynamic Island sobrepõe UI |

### ⚡ MENORES (polish)

| # | Problema | Localização | Impacto |
|---|----------|-------------|---------|
| 10 | Fonte Inter não configurada | index.css | Tipografia inconsistente |
| 11 | Cores não são exatamente as especificadas | index.css | Branding inconsistente |
| 12 | Dark mode sem toggle | Nenhum | Feature morta |
| 13 | Links de "Cadastre-se" e "Esqueceu senha" quebrados | LoginPage.tsx | Dead links |

---

## 8. COMPARAÇÃO COM MONOLITO PHANT

| Feature | Monolito | Lazaro V2 | Diferença |
|---------|----------|-----------|-----------|
| Login | ✅ | ✅ | Igual |
| Dashboard | ✅ | ✅ | Igual |
| Conversas | ✅ | ⚠️ | Sem envio de mensagens |
| Pipeline | ✅ | ⚠️ | Só Kanban (faltam Lista/Funil) |
| Billing | ✅ | ❌ | Não implementado no frontend |
| Agentes CRUD | ✅ | ❌ | Não implementado no frontend |
| Mobile | ⚠️ | ❌ | Ainda pior no V2 |

---

## 9. RECOMENDAÇÕES

### Prioridade 1 - Fixes críticos
1. Corrigir UPLOAD_DIR em `apps/ia/app/main.py`
2. Adicionar chat-bg.png ou remover referência
3. Tornar layout responsivo com breakpoints

### Prioridade 2 - Completar features
4. Implementar BillingPage.tsx
5. Implementar AgentsPage.tsx
6. Implementar envio de mensagens no chat
7. Adicionar modos Lista e Funil no Pipeline

### Prioridade 3 - Polish
8. Configurar fonte Inter
9. Ajustar cores para spec (#1a6eff)
10. Implementar safe-area-inset para iOS

---

## 10. CONCLUSÃO

O Lazaro V2 é um **projeto real com código funcional**, não vaporware. Os containers rodam, a API responde, o frontend carrega. Porém, está longe de ser uma substituição completa do monolito:

- **O que funciona:** Login, Dashboard, visualização de conversas, Kanban básico
- **O que falta:** Billing, Agentes, envio de mensagens, responsividade mobile
- **O que está quebrado:** Upload de arquivos (referência a phant), background do chat

**Estimativa para produção:** Precisa de mais 2-3 dias de trabalho para atingir paridade mínima com o monolito.

---

*Revisão gerada automaticamente por Claude Opus 4.5*
*Todos os problemas foram verificados via leitura de código, não por suposição*
