# Lazaro IA - Dockerfile
# Agente Python com FastAPI

FROM python:3.11-slim AS base

WORKDIR /app

# Instalar dependências do sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ============================================================================
# Stage: Dependencies
# ============================================================================
FROM base AS deps

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ============================================================================
# Stage: Production
# ============================================================================
FROM base AS runner

# Copiar dependências instaladas
COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Criar usuário não-root
RUN groupadd --gid 1001 lazaro && \
    useradd --uid 1001 --gid lazaro --shell /bin/bash lazaro

# Criar diretório de uploads
RUN mkdir -p /app/uploads && chown lazaro:lazaro /app/uploads

# Copiar código da aplicação
COPY app ./app

USER lazaro

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 3105

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3105"]
