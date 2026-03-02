# Lazaro API - Dockerfile
# Backend independente em TypeScript/Fastify

FROM node:20-alpine AS base

WORKDIR /app

# Instalar dependências de build
RUN apk add --no-cache python3 make g++

# ============================================================================
# Stage: Dependencies
# ============================================================================
FROM base AS deps

COPY package*.json ./
RUN npm ci --only=production

# ============================================================================
# Stage: Build
# ============================================================================
FROM base AS builder

COPY package*.json ./
RUN npm ci

COPY tsconfig.json ./
COPY src ./src

RUN npm run build

# ============================================================================
# Stage: Production
# ============================================================================
FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production

# Instalar wget para healthcheck e criar usuário não-root
RUN apk add --no-cache wget && \
    addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 lazaro

# Copiar apenas o necessário
COPY --from=deps /app/node_modules ./node_modules
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/package.json ./

USER lazaro

EXPOSE 3102

CMD ["node", "dist/index.js"]
