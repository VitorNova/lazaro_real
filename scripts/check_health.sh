#!/bin/bash
# Script de diagnóstico de saúde do Lazaro Swarm
# Uso: ./scripts/check_health.sh

set -e

echo "=== SWARM ==="
docker stack ps lazaro --filter "desired-state=running"

echo ""
echo "=== REDIS ==="
REDIS_CONTAINER=$(docker ps --filter "name=redis_redis" --format "{{.ID}}" | head -1)
if [ -n "$REDIS_CONTAINER" ]; then
  docker exec $REDIS_CONTAINER redis-cli INFO keyspace 2>/dev/null || echo "Redis inacessível"
else
  echo "Container Redis não encontrado no Manager (está no Worker-03)"
  # Tentar via réplica lazaro-ia
  LAZARO_CONTAINER=$(docker ps --filter "name=lazaro_lazaro-ia" --format "{{.ID}}" | head -1)
  if [ -n "$LAZARO_CONTAINER" ]; then
    docker exec $LAZARO_CONTAINER python3 -c "
import redis
r = redis.Redis(host='redis_redis', port=6379, db=0)
print(f'Keys: {r.dbsize()}')
print(f'Pausas: {len(r.keys(\"pause:*\"))}')
" 2>/dev/null || echo "Não foi possível conectar via lazaro-ia"
  fi
fi

echo ""
echo "=== WEBHOOKS ==="
curl -s -o /dev/null -w "WhatsApp: %{http_code}\n" \
  https://lazaro.fazinzz.com/api/webhook/whatsapp 2>/dev/null || echo "WhatsApp: FALHOU"
curl -s -o /dev/null -w "Asaas: %{http_code}\n" \
  https://lazaro.fazinzz.com/webhooks/asaas 2>/dev/null || echo "Asaas: FALHOU"
curl -s -o /dev/null -w "Leadbox: %{http_code}\n" \
  https://lazaro.fazinzz.com/webhooks/leadbox 2>/dev/null || echo "Leadbox: FALHOU"

echo ""
echo "=== HEALTH ==="
curl -s https://lazaro.fazinzz.com/health 2>/dev/null || echo "Health: FALHOU"

echo ""
echo "=== LOGS ERROS RECENTES (últimos 5min) ==="
docker service logs lazaro_lazaro-ia --since 5m 2>&1 | \
  grep -iE "error|exception|refused|failed" | tail -20 || echo "Sem erros recentes"

echo ""
echo "=== RESUMO ==="
RUNNING=$(docker service ps lazaro_lazaro-ia --filter "desired-state=running" -q | wc -l)
echo "Réplicas rodando: $RUNNING/3"
