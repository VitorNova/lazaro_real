# Lazaro V2

Painel independente para gestão de leads e atendimento via WhatsApp com IA.

## Stack

| Camada | Tecnologia |
|--------|------------|
| Frontend | React 19 + Vite + Tailwind CSS v4 |
| Estado | Zustand + TanStack Query |
| Backend API | Fastify + TypeScript |
| Backend IA | FastAPI + Python + Gemini |
| Cache | Redis 7 |
| Banco | Supabase (PostgreSQL) |

## Containers

| Container | Porta | Descrição |
|-----------|-------|-----------|
| lazaro-web-v2 | 3100 | Frontend React (nginx) |
| lazaro-api-v2 | 3112 | Backend Fastify |
| lazaro-ia-v2 | 3115 | Agente Python IA |
| lazaro-redis-v2 | 6380 | Cache Redis |

## Rodando o projeto

```bash
cd /var/www/lazaro-v2

# Subir todos os containers
docker compose up -d

# Ver logs
docker compose logs -f

# Ver status
docker compose ps
```

## URLs

- **Frontend:** http://localhost:3100
- **API:** http://localhost:3112
- **IA:** http://localhost:3115
- **Health:** http://localhost:3112/health

## Rebuild da imagem IA

⚠️ **IMPORTANTE:** O container `lazaro-ia` usa uma imagem pré-construída (`lazaro-ia:v1.0`).
Se você fizer alterações no código em `apps/ia/`, precisa rebuildar a imagem manualmente:

```bash
cd /var/www/lazaro-v2

# Rebuildar a imagem
docker build -t lazaro-ia:v1.0 -f apps/ia/Dockerfile apps/ia/

# Reiniciar o container
docker compose restart lazaro-ia
```

## Rebuild do frontend

```bash
cd /var/www/lazaro-v2

# Rebuildar e reiniciar
docker compose build lazaro-web
docker compose up -d lazaro-web
```

## Rebuild da API

```bash
cd /var/www/lazaro-v2

# Rebuildar e reiniciar
docker compose build lazaro-api
docker compose up -d lazaro-api
```

## Estrutura de pastas

```
/var/www/lazaro-v2/
├── docker-compose.yml
├── .env
├── apps/
│   ├── web/          # Frontend React
│   ├── api/          # Backend Fastify
│   └── ia/           # Agente Python
└── README.md
```

## Desenvolvimento

Para desenvolvimento local sem Docker:

```bash
# Frontend
cd apps/web
npm install
npm run dev

# API
cd apps/api
npm install
npm run dev
```

## Variáveis de ambiente

Copie o `.env.example` para `.env` e preencha as variáveis:

```bash
cp .env.example .env
```

Variáveis principais:
- `SUPABASE_URL` - URL do Supabase
- `SUPABASE_SERVICE_KEY` - Chave de serviço
- `GEMINI_API_KEY` - Chave da API Gemini
- `UAZAPI_BASE_URL` - URL do UAZAPI
- `UAZAPI_API_KEY` - Chave do UAZAPI
