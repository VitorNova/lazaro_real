# Lazaro Web - Dockerfile
# Frontend React + Vite

FROM node:20-alpine AS base

WORKDIR /app

# ============================================================================
# Stage: Dependencies
# ============================================================================
FROM base AS deps

COPY package*.json ./
RUN npm ci

# ============================================================================
# Stage: Build
# ============================================================================
FROM base AS builder

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Build args para environment
ARG VITE_API_URL=/api
ENV VITE_API_URL=$VITE_API_URL

RUN npm run build

# ============================================================================
# Stage: Production (nginx)
# ============================================================================
FROM nginx:alpine AS runner

# Copiar configuracao nginx
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copiar build
COPY --from=builder /app/dist /usr/share/nginx/html

# Criar usuario nao-root
RUN addgroup -g 1001 -S lazaro && \
    adduser -S -D -H -u 1001 -h /var/cache/nginx -s /sbin/nologin -G lazaro lazaro && \
    chown -R lazaro:lazaro /var/cache/nginx /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
