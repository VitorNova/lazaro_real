#!/bin/bash
PROTECTED=(
  "apps/ia/app/webhooks/mensagens.py"
  "apps/ia/app/webhooks/pagamentos.py"
  "apps/ia/app/main.py"
  "apps/ia/app/jobs/cobrar_clientes.py"
  "apps/ia/app/jobs/reengajar_leads.py"
)
INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | grep -o '"path"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"path"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')
for P in "${PROTECTED[@]}"; do
  if echo "$FILE_PATH" | grep -q "$P"; then
    echo '{"permissionDecision": "ask"}'
    exit 0
  fi
done
echo '{"permissionDecision": "allow"}'
exit 0
