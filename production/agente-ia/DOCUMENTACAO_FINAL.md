# Documentação Final - Agente IA (Python/FastAPI)

**Versão:** 1.0.0
**Última atualização:** 2026-01-27
**Status:** Funcionando em produção

---

## 1. Estrutura de Arquivos

```
/var/www/phant/agente-ia/
├── app/
│   ├── __init__.py              # Package init
│   ├── main.py                  # FastAPI app, lifespan, endpoints de health
│   ├── config.py                # Configuração via Pydantic Settings (.env)
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   └── dashboard.py         # Endpoints do dashboard (métricas, status)
│   │
│   ├── services/
│   │   ├── __init__.py          # Exports dos services
│   │   ├── redis.py             # Buffer de mensagens, locks, pausa (14s delay)
│   │   ├── gemini.py            # Cliente Gemini AI com function calling
│   │   ├── supabase.py          # Cliente Supabase (agents, leads, messages)
│   │   ├── uazapi.py            # Cliente UAZAPI (send text, typing)
│   │   ├── leadbox.py           # Cliente Leadbox (transferência de atendimento)
│   │   └── calendar.py          # Cliente Google Calendar (em desenvolvimento)
│   │
│   ├── webhooks/
│   │   ├── __init__.py
│   │   └── whatsapp.py          # WhatsAppWebhookHandler - fluxo principal
│   │
│   └── tools/
│       ├── __init__.py
│       └── functions.py         # FUNCTION_DECLARATIONS + FunctionHandlers
│
├── requirements.txt             # Dependências Python
├── .env                         # Variáveis de ambiente (não versionado)
├── CONTEXT.md                   # Contexto para IA (Claude/Gemini)
└── DOCUMENTACAO_FINAL.md        # Este arquivo
```

### Descrição dos Arquivos

| Arquivo | Descrição |
|---------|-----------|
| `main.py` | Entry point FastAPI. Gerencia lifespan (startup/shutdown), inicializa Redis e Gemini, configura CORS e rotas. |
| `config.py` | Carrega variáveis de ambiente com Pydantic Settings. Valida tipos e valores obrigatórios. |
| `services/redis.py` | Gerencia buffer de mensagens com RPUSH/LRANGE, locks distribuídos (SET NX EX), controle de pausa. |
| `services/gemini.py` | Integração com Google Generative AI. Envia mensagens, processa function calls em loop. |
| `services/supabase.py` | CRUD de agents, leads (tabelas dinâmicas), histórico de conversa em JSONB. |
| `services/uazapi.py` | Envia mensagens e typing via UAZAPI. Header `token: {api_key}`, endpoint `/send/text`. |
| `services/leadbox.py` | Transfere atendimentos via API PUSH do Leadbox. POST `/v1/api/external/{api_uuid}`. |
| `webhooks/whatsapp.py` | Handler principal. Recebe webhook, identifica agente, bufferiza, processa com Gemini, responde. |
| `tools/functions.py` | Declarações de tools (consulta_agenda, agendar, transferir_departamento) e handlers. |

---

## 2. Fluxo Completo de Mensagem

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          FLUXO DE PROCESSAMENTO                              │
└─────────────────────────────────────────────────────────────────────────────┘

1. UAZAPI envia webhook POST /webhooks/dynamic
   │
   ▼
2. main.py recebe, extrai EventType
   │
   ├── Se EventType != "messages" → ignora
   │
   ▼
3. WhatsAppWebhookHandler.handle_message()
   │
   ├── Extrai: phone, remotejid, texto, instance_id
   │
   ▼
4. Busca agente no Supabase
   │
   ├── Por uazapi_instance_id (ex: Agent_14e6e5ce)
   ├── Ou por uazapi_token
   │
   ▼
5. Verifica comandos de controle
   │
   ├── /p → Pausa bot (Redis pause:*)
   ├── /a → Ativa bot (remove pausa)
   ├── /r ou /rr → Reset histórico
   │
   ▼
6. Verifica se bot está pausado
   │
   ├── Se pausado → ignora mensagem
   │
   ▼
7. Adiciona mensagem ao buffer Redis
   │
   ├── Key: buffer:msg:{agent_id}:{phone}
   ├── RPUSH + EXPIRE 300s
   │
   ▼
8. Agenda processamento (BackgroundTasks)
   │
   ├── Aguarda 14 segundos (BUFFER_DELAY)
   ├── Lock: lock:msg:{agent_id}:{phone}
   │
   ▼
9. Processa mensagens do buffer
   │
   ├── LRANGE + DELETE (atômico)
   ├── Concatena mensagens
   │
   ▼
10. Envia typing via UAZAPI
    │
    ├── POST /message/presence {presence: "composing"}
    │
    ▼
11. Busca histórico de conversa (Supabase)
    │
    ├── Tabela: leadbox_messages_{shortId}
    ├── Campo: conversation_history (JSONB)
    │
    ▼
12. Envia para Gemini processar
    │
    ├── Model: gemini-2.0-flash-exp
    ├── System prompt do agente
    ├── Histórico + mensagem atual
    │
    ▼
13. Se function call → executa handler
    │
    ├── transferir_departamento → LeadboxService
    ├── consulta_agenda → CalendarService (placeholder)
    ├── Retorna resultado ao Gemini
    │
    ▼
14. Envia resposta via UAZAPI
    │
    ├── POST /send/text
    ├── Token do agente específico
    │
    ▼
15. Salva histórico atualizado (Supabase)
    │
    ├── Adiciona mensagem user + model
    │
    ▼
16. Retorna {"status": "processed"}
```

---

## 3. Function Calling

### 3.1 Tools Existentes

| Tool | Descrição | Status |
|------|-----------|--------|
| `consulta_agenda` | Consulta horários disponíveis na agenda | Placeholder |
| `agendar` | Cria novo agendamento com Google Meet | Placeholder |
| `cancelar_agendamento` | Cancela agendamento existente | Placeholder |
| `reagendar` | Altera data/hora de agendamento | Placeholder |
| `transferir_departamento` | Transfere para humano via Leadbox | **Funcionando** |

### 3.2 Declarações (tools/functions.py)

```python
FUNCTION_DECLARATIONS = [
    {
        "name": "transferir_departamento",
        "description": "Transfere o atendimento para outro departamento...",
        "parameters": {
            "type": "object",
            "properties": {
                "departamento": {"type": "string", "description": "Nome do departamento"},
                "queue_id": {"type": "integer", "description": "ID da fila no Leadbox"},
                "user_id": {"type": "integer", "description": "ID do usuário no Leadbox"},
                "motivo": {"type": "string", "description": "Motivo da transferência"},
                "observacoes": {"type": "string", "description": "Observações adicionais"}
            },
            "required": ["motivo"]
        }
    },
    # ... outras tools
]
```

### 3.3 Execução de Function Calls

**Arquivo:** `services/gemini.py` → `_handle_function_calls()`

```python
async def _handle_function_calls(self, chat, function_calls, max_iterations=10):
    while function_calls and iteration < max_iterations:
        for fc in function_calls:
            handler = self._tool_handlers.get(fc["name"])
            result = await handler(**fc["args"])
            function_responses.append({"name": fc["name"], "response": result})

        # Envia resultados de volta ao Gemini
        response = await chat.send_message_async(parts)
        result = self._process_response(response)

        # Se resposta vazia, usa fallback da function
        if not result.get("text") and function_responses:
            result["text"] = function_responses[-1]["response"]["mensagem"]
```

### 3.4 Handlers (webhooks/whatsapp.py)

Os handlers reais ficam em `webhooks/whatsapp.py` dentro de `_create_tool_handlers()`:

```python
def _create_tool_handlers(self, context: Dict[str, Any]):
    async def transferir_departamento_handler(
        departamento=None, motivo=None, queue_id=None, user_id=None, **kwargs
    ):
        # Lê handoff_triggers do contexto
        # Cria LeadboxService
        # Chama leadbox.transfer_to_department()
        # Marca lead como pausado
        return {"sucesso": True, "mensagem": "Entendi! Vou te transferir..."}

    return {
        "transferir_departamento": transferir_departamento_handler,
        "consulta_agenda": placeholder_handler,
        # ...
    }
```

---

## 4. Transferência Leadbox

### 4.1 Configuração no Banco (campo `handoff_triggers`)

```json
{
    "type": "leadbox_api",
    "enabled": true,
    "api_url": "https://enterprise-135api.leadbox.app.br",
    "api_uuid": "be475918-cc86-4721-bfb4-6a9b287f92e3",
    "api_token": "eyJhbGciOiJIUzI1NiIs...",
    "departments": {
        "financeiro": {"id": 454, "userId": 814},
        "vendas": {"id": 123, "userId": 456}
    }
}
```

### 4.2 Payload Enviado para API

**Endpoint:** `POST /v1/api/external/{api_uuid}`

**Headers:**
```
Authorization: Bearer {api_token}
Content-Type: application/json
```

**Body:**
```json
{
    "number": "556697194084",
    "body": "Cliente quer falar com financeiro",
    "externalKey": "transfer-556697194084-454",
    "forceTicketToDepartment": true,
    "queueId": 454,
    "forceTicketToUser": true,
    "userId": 814
}
```

### 4.3 Formatação do Número (services/leadbox.py)

```python
def _format_phone(self, phone: str) -> str:
    # Remove sufixos do WhatsApp
    clean = phone.replace("@s.whatsapp.net", "")
    clean = clean.replace("@c.us", "")
    clean = clean.replace("@lid", "")

    # Remove caracteres não-numéricos
    clean = "".join(filter(str.isdigit, clean))

    # Adiciona código do Brasil se necessário
    if len(clean) == 10 or len(clean) == 11:
        clean = f"55{clean}"

    return clean  # Ex: "556697194084" (12 dígitos)
```

### 4.4 Retorno do Handler

**Sucesso:**
```python
{
    "sucesso": True,
    "mensagem": "Entendi! Vou te transferir agora para um dos nossos especialistas. Só um momento! 😊",
    "instrucao": "IMPORTANTE: Use EXATAMENTE a mensagem acima..."
}
```

**Erro:**
```python
{
    "sucesso": False,
    "mensagem": "Desculpe, tive um problema ao tentar te transferir...",
    "erro_interno": "HTTP 404: Not Found"
}
```

---

## 5. Buffer Redis

### 5.1 Como Funciona

1. Cada mensagem recebida é adicionada ao buffer
2. Aguarda 14 segundos para agrupar mensagens sequenciais
3. Lock evita processamento duplicado
4. Ao processar, consome todas as mensagens do buffer

### 5.2 Tempo de Espera

```python
BUFFER_DELAY_SECONDS = 14  # Constante em redis.py
DEFAULT_TTL_SECONDS = 300  # TTL das keys
LOCK_TTL_SECONDS = 30      # TTL do lock
```

### 5.3 Estrutura das Keys

| Key Pattern | Descrição | TTL |
|-------------|-----------|-----|
| `buffer:msg:{agent_id}:{phone}` | Lista de mensagens pendentes | 300s |
| `lock:msg:{agent_id}:{phone}` | Lock de processamento | 30s |
| `pause:{agent_id}:{phone}` | Flag de pausa do bot | Indefinido |

### 5.4 Operações Redis

```python
# Adicionar mensagem
await redis.rpush(buffer_key, message)
await redis.expire(buffer_key, 300)

# Adquirir lock
acquired = await redis.set(lock_key, "1", nx=True, ex=30)

# Consumir buffer (atômico)
async with redis.pipeline(transaction=True) as pipe:
    pipe.lrange(buffer_key, 0, -1)
    pipe.delete(buffer_key)
    results = await pipe.execute()
```

---

## 6. Banco de Dados

### 6.1 Tabelas Usadas

| Tabela | Descrição |
|--------|-----------|
| `agents` | Configuração dos agentes (prompts, tokens, etc) |
| `LeadboxCRM_{shortId}` | Leads de cada agente (dinâmica) |
| `leadbox_messages_{shortId}` | Histórico de conversas (dinâmica) |

### 6.2 Campos Importantes - Tabela `agents`

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `id` | uuid | ID único do agente |
| `name` | string | Nome do agente |
| `status` | string | active, inactive |
| `uazapi_instance_id` | string | ID da instância UAZAPI (ex: Agent_14e6e5ce) |
| `uazapi_token` | string | Token de autenticação UAZAPI |
| `uazapi_base_url` | string | URL base da UAZAPI |
| `table_leads` | string | Nome da tabela de leads |
| `table_messages` | string | Nome da tabela de mensagens |
| `system_prompt` | text | Prompt do agente |
| `handoff_triggers` | jsonb | Config do Leadbox |

### 6.3 Campos Importantes - Tabela `LeadboxCRM_*`

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `id` | int | ID do lead |
| `remotejid` | string | WhatsApp ID (556699...@s.whatsapp.net) |
| `telefone` | string | Telefone limpo |
| `nome` | string | Nome do contato |
| `pipeline_step` | string | Etapa do funil |
| `Atendimento_Finalizado` | string | "true" = bot pausado |
| `paused_at` | timestamp | Quando foi pausado |
| `pausar_ia` | boolean | Flag de pausa manual |

### 6.4 Campos Importantes - Tabela `leadbox_messages_*`

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `remotejid` | string | WhatsApp ID |
| `conversation_history` | jsonb | Histórico no formato Gemini |
| `Msg_user` | timestamp | Última mensagem do usuário |
| `Msg_model` | timestamp | Última mensagem do bot |
| `creat` | timestamp | Última atualização |

### 6.5 Formato do Histórico (JSONB)

```json
{
    "messages": [
        {
            "role": "user",
            "parts": [{"text": "oi"}],
            "timestamp": "2026-01-27T04:00:00Z"
        },
        {
            "role": "model",
            "parts": [{"text": "Olá! Como posso ajudar?"}],
            "timestamp": "2026-01-27T04:00:15Z"
        }
    ]
}
```

### 6.6 Queries Principais

```python
# Buscar agente por instance_id
supabase.table("agents").select("*").eq("uazapi_instance_id", instance_id).execute()

# Buscar lead por remotejid
supabase.table(table_leads).select("*").eq("remotejid", remotejid).execute()

# Buscar histórico
supabase.table(table_messages).select("conversation_history").eq("remotejid", remotejid).execute()

# Atualizar lead (marcar pausado)
supabase.table(table_leads).update({
    "Atendimento_Finalizado": "true",
    "paused_at": datetime.utcnow().isoformat()
}).eq("remotejid", remotejid).execute()

# Salvar histórico
supabase.table(table_messages).upsert({
    "remotejid": remotejid,
    "conversation_history": history,
    "creat": datetime.utcnow().isoformat()
}).execute()
```

---

## 7. Endpoints da API

### 7.1 POST /webhooks/dynamic

**Descrição:** Recebe webhooks do UAZAPI (mensagens WhatsApp)

**Request:**
```json
{
    "EventType": "messages",
    "instanceName": "Agent_14e6e5ce",
    "token": "a2d9bb9c-...",
    "chat": {
        "phone": "+55 66 9719-4084",
        "wa_chatid": "556697194084@s.whatsapp.net"
    },
    "message": {
        "text": "oi",
        "fromMe": false
    }
}
```

**Response:**
```json
{
    "status": "processed",
    "agent_id": "14e6e5ce-...",
    "remotejid": "556697194084@s.whatsapp.net"
}
```

### 7.2 GET /webhooks/dynamic

**Descrição:** Verificação do webhook (usado pelo UAZAPI)

**Response:**
```json
{
    "status": "ok",
    "service": "agente-ia",
    "webhook": "dynamic",
    "timestamp": "2026-01-27T04:00:00Z"
}
```

### 7.3 GET /health

**Descrição:** Health check básico

**Response:**
```json
{
    "status": "healthy",
    "timestamp": "2026-01-27T04:00:00Z"
}
```

### 7.4 GET /health/detailed

**Descrição:** Health check detalhado com status dos serviços

**Response:**
```json
{
    "status": "healthy",
    "timestamp": "2026-01-27T04:00:00Z",
    "uptime_seconds": 3600,
    "environment": "production",
    "services": {
        "redis": {"status": "healthy", "connected": true},
        "gemini": {"status": "healthy", "initialized": true, "model": "gemini-2.0-flash-exp"},
        "calendar": {"status": "not_configured", "initialized": false}
    }
}
```

---

## 8. Variáveis de Ambiente

```env
# ========================
# OBRIGATÓRIAS
# ========================

# Servidor
PORT=3005
APP_ENV=production

# Google AI (Gemini)
GOOGLE_API_KEY=AIza...

# Supabase
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGci...

# UAZAPI (fallback global)
UAZAPI_BASE_URL=https://agoravai.uazapi.com
UAZAPI_API_KEY=xxx

# Redis
REDIS_URL=redis://localhost:6379/0

# ========================
# OPCIONAIS
# ========================

# Gemini
GEMINI_MODEL=gemini-2.0-flash-exp
GEMINI_TEMPERATURE=0.7
GEMINI_MAX_TOKENS=4096

# Buffer
MESSAGE_BUFFER_DELAY_MS=9000
MAX_CONVERSATION_HISTORY=50

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json

# Asaas (pagamentos)
ASAAS_API_KEY=xxx
ASAAS_API_URL=https://api.asaas.com/v3

# Google Calendar
GOOGLE_CALENDAR_CREDENTIALS={"type": "service_account", ...}
```

---

## 9. Problemas Conhecidos e Soluções Aplicadas

### 9.1 UAZAPI - Headers e Endpoints

| Problema | Solução |
|----------|---------|
| Header `Authorization: Bearer` não funcionava | Corrigido para `token: {api_key}` |
| Endpoint `/messages/send` não existe | Corrigido para `POST /send/text` |
| Endpoint `/messages/typing` não existe | Corrigido para `POST /message/presence` |
| Payload typing errado | Corrigido: `{"number": X, "presence": "composing", "delay": 3000}` |

### 9.2 Supabase - Response None

**Problema:** `get_agent_by_instance_id` retornava `None` mesmo encontrando o agente.

**Solução:** Tratamento defensivo:
```python
if response and response.data and len(response.data) > 0:
    return response.data[0]
return None
```

### 9.3 Gemini - "list index out of range"

**Problema:** Após function call, `response.candidates` vinha vazio.

**Solução:** Tratamento defensivo + fallback:
```python
if not response.candidates or len(response.candidates) == 0:
    return result  # Usa resultado da function como fallback
```

### 9.4 Gemini - Float em vez de Int

**Problema:** Gemini enviava `queue_id=454.0` (float).

**Solução:** Conversão explícita:
```python
if queue_id is not None:
    queue_id = int(queue_id)
```

### 9.5 Leadbox - userId não enviado

**Problema:** Quando Gemini passava `queue_id` direto (sem `departamento`), o `user_id` ficava `None`.

**Solução:** Busca automática no mapeamento:
```python
if final_queue_id and not final_user_id:
    for dept_name, dept_config in departments.items():
        dept_queue = int(dept_config.get("id") or 0)
        if dept_queue == final_queue_id:
            final_user_id = int(dept_config.get("userId") or 0)
            break
```

### 9.6 Leadbox - Número com 13 dígitos

**Problema:** API retornava 404 para números com 13 dígitos (ex: `5566971940842`).

**Solução:** Função `_format_phone()` já estava correta (retorna 12 dígitos). Verificar origem do número.

### 9.7 Mensagem técnica após transferência

**Problema:** Bot respondia "Atendimento transferido para fila 454" ao usuário.

**Solução:** Retorno amigável no handler:
```python
return {
    "sucesso": True,
    "mensagem": "Entendi! Vou te transferir agora para um dos nossos especialistas. Só um momento! 😊"
}
```

---

## 10. Comandos Úteis para Debug

### 10.1 PM2 (Process Manager)

```bash
# Ver status dos processos
pm2 list

# Ver logs em tempo real
pm2 logs agente-ia --lines 100

# Filtrar logs específicos
pm2 logs agente-ia | grep -E "DEBUG|TRANSFER|GEMINI|LEADBOX API"

# Reiniciar após alteração
pm2 restart agente-ia

# Ver detalhes do processo
pm2 show agente-ia
```

### 10.2 Debug de Payload

```bash
# Ver último payload recebido
cat /tmp/uazapi_message_payload.json | jq

# Monitorar arquivo em tempo real
tail -f /tmp/uazapi_message_payload.json
```

### 10.3 Testar Endpoints

```bash
# Health check
curl -s https://ia.phant.com.br/health | jq

# Health detalhado
curl -s https://ia.phant.com.br/health/detailed | jq

# Webhook (verificação)
curl -s https://ia.phant.com.br/webhooks/dynamic | jq
```

### 10.4 Testar API Leadbox

```bash
curl -s -X POST "https://enterprise-135api.leadbox.app.br/v1/api/external/{api_uuid}" \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{"number":"556697194084","body":"Teste","externalKey":"test-001","queueId":454}'
```

### 10.5 Supabase (via API)

```bash
# Buscar agente
curl -s "https://xxx.supabase.co/rest/v1/agents?name=ilike.*ana*" \
  -H "apikey: {service_key}" \
  -H "Authorization: Bearer {service_key}" | jq

# Atualizar handoff_triggers
curl -s -X PATCH "https://xxx.supabase.co/rest/v1/agents?id=eq.{agent_id}" \
  -H "apikey: {service_key}" \
  -H "Authorization: Bearer {service_key}" \
  -H "Content-Type: application/json" \
  -d '{"handoff_triggers": {...}}'
```

### 10.6 Redis

```bash
# Conectar ao Redis CLI
redis-cli

# Ver todas as keys do agente-ia
KEYS buffer:msg:*
KEYS lock:msg:*
KEYS pause:*

# Ver conteúdo do buffer
LRANGE buffer:msg:{agent_id}:{phone} 0 -1

# Limpar buffer manualmente
DEL buffer:msg:{agent_id}:{phone}

# Ver TTL de uma key
TTL buffer:msg:{agent_id}:{phone}
```

### 10.7 Limpar Histórico de Conversa

```sql
-- Via Supabase SQL Editor
UPDATE "leadbox_messages_xxx"
SET conversation_history = '{"messages": []}'::jsonb
WHERE remotejid = '556697194084@s.whatsapp.net';
```

---

## Anexo: Logs de Debug

O sistema gera logs com prefixos para facilitar o debug:

| Prefixo | Descrição |
|---------|-----------|
| `[DEBUG 1/6]` | Mensagem recebida |
| `[DEBUG 2/6]` | Busca do agente |
| `[DEBUG 3/6]` | Buffer Redis |
| `[DEBUG 4/6]` | Processamento |
| `[DEBUG 5/6]` | Chamada Gemini |
| `[DEBUG 6/6]` | Envio UAZAPI |
| `[TRANSFER]` | Transferência Leadbox |
| `[LEADBOX API]` | Chamada HTTP ao Leadbox |
| `[WEBHOOK DEBUG]` | Payload recebido |

---

*Documentação gerada em 2026-01-27*
