# CONTEXT.md - Agente IA (Python/FastAPI)

## 1. Status Atual ✅ FUNCIONANDO

| Etapa | Status | Descrição |
|-------|--------|-----------|
| Webhook recebendo | ✅ | POST /webhooks/dynamic |
| Agente identificado | ✅ | Por instance_id ou token |
| Buffer Redis 14s | ✅ | Agrupa mensagens sequenciais |
| Gemini processando | ✅ | gemini-2.0-flash-exp |
| Envio UAZAPI | ✅ | Token do agente específico |
| Transferência Leadbox | ✅ | API PUSH para humanos |

**Último teste bem-sucedido:** 2026-01-27 00:57:56

### Agentes Testados
| Agente | Status | Última Mensagem | Leadbox |
|--------|--------|-----------------|---------|
| AGNES LEADBOX | ✅ | 2026-01-26 23:34:25 | ✅ Configurado |
| ANA (Aluga Ar) | ✅ | 2026-01-27 00:57:56 | ✅ Testado |

### Transferência Leadbox Testada
- **Mensagem:** "quero falar com financeiro"
- **Ação:** Gemini chamou `transferir_departamento(queue_id=454)`
- **Resultado:** "Atendimento transferido para a fila 454"
- **Lead pausado:** `Atendimento_Finalizado = "true"`

---

## 2. Changelog - Sessão 2026-01-27

### 2.1 Correções de Endpoints UAZAPI
**Arquivo:** `app/services/uazapi.py`

| Problema | Solução |
|----------|---------|
| Header `Authorization: Bearer` | Corrigido para `token: {api_key}` |
| Endpoint `/messages/send` | Corrigido para `POST /send/text` |
| Endpoint `/messages/typing` | Corrigido para `POST /message/presence` |
| Payload typing errado | Corrigido: `{"number": X, "presence": "composing", "delay": 3000}` |

### 2.2 Correção Supabase Response None
**Arquivo:** `app/services/supabase.py`

**Problema:** Método `get_agent_by_instance_id` retornava `None` mesmo quando encontrava o agente.

**Solução:** Adicionado tratamento defensivo:
```python
response = self.client.table("agents").select("*").eq("uazapi_instance_id", instance_id).execute()
if response and response.data and len(response.data) > 0:
    return response.data[0]
return None
```

### 2.3 Implementação Completa do transferir_departamento
**Arquivo:** `app/webhooks/whatsapp.py`

**Antes:** Handler era placeholder que retornava "Funcionalidade em desenvolvimento"

**Depois:** Handler real que:
1. Lê `handoff_triggers` do contexto do agente
2. Cria instância do `LeadboxService` com credenciais
3. Chama API PUSH do Leadbox: `POST /v1/api/external/{api_uuid}`
4. Marca lead como pausado: `Atendimento_Finalizado = "true"`

```python
async def transferir_departamento_handler(
    departamento: str = None,
    motivo: str = None,
    observacoes: str = None,
    queue_id: int = None,
    user_id: int = None,
    **kwargs
):
    # Converter para int (Gemini pode enviar float como 454.0)
    if queue_id is not None:
        queue_id = int(queue_id)

    # Ler config do agente
    handoff_config = context.get("handoff_triggers")

    # Criar LeadboxService
    leadbox = LeadboxService(
        base_url=handoff_config["api_url"],
        api_uuid=handoff_config["api_uuid"],
        api_key=handoff_config["api_token"]
    )

    # Executar transferência
    result = await leadbox.transfer_to_department(
        phone=context["phone"],
        queue_id=final_queue_id,
        user_id=final_user_id,
        notes=transfer_notes,
    )

    # Marcar lead como pausado
    if result["sucesso"]:
        supabase.update_lead_by_remotejid(
            table_leads, remotejid,
            {"Atendimento_Finalizado": "true", "paused_at": datetime.utcnow().isoformat()}
        )
```

### 2.4 Correção de Colunas Inexistentes
**Problema:** Código tentava salvar campos que não existem na tabela de leads:
- `status`
- `responsavel`
- `transfer_reason`
- `transferred_at`

**Solução:** Removidos campos inexistentes. Agora salva apenas:
```python
{
    "Atendimento_Finalizado": "true",
    "paused_at": datetime.utcnow().isoformat(),
}
```

### 2.5 Correção Gemini "list index out of range"
**Arquivo:** `app/services/gemini.py`

**Problema:** Após executar function call e enviar resultado de volta ao Gemini, `response.candidates` vinha vazio, causando `IndexError`.

**Solução:** Adicionado tratamento defensivo em `_process_response`:
```python
# Processa candidatos - verifica de forma defensiva
if not response.candidates or len(response.candidates) == 0:
    logger.warning("Resposta sem candidatos (pode ser normal após function call)")
    return result

try:
    candidate = response.candidates[0]
except (IndexError, TypeError) as e:
    logger.warning(f"Erro ao acessar candidato: {e}")
    return result
```

### 2.6 Correção Fallback Após Function Call
**Arquivo:** `app/services/gemini.py`

**Problema:** Quando Gemini retornava vazio após function call, não havia resposta para o usuário.

**Solução:** Adicionado fallback que usa o resultado da function:
```python
# Envia function responses
try:
    response = await chat.send_message_async(parts)
    result = self._process_response(response)
except Exception as e:
    logger.warning(f"Erro ao enviar function response ao Gemini: {e}")
    result = {"text": "", "function_calls": [], "usage": {}}

# Se resposta vazia após function call, usa resultado da function como fallback
if not result.get("text") and function_responses:
    last_response = function_responses[-1].get("response", {})
    if isinstance(last_response, dict):
        fallback_msg = last_response.get("mensagem") or last_response.get("message", "")
        if last_response.get("sucesso") or last_response.get("success"):
            result["text"] = fallback_msg or "Operação realizada com sucesso!"
        else:
            result["text"] = fallback_msg or "Houve um problema ao executar a operação."
    result["function_calls"] = []  # Sair do loop
```

### 2.7 Limpeza de Histórico Contaminado
**Problema:** Histórico de conversa continha mensagens com "@transferir_departamento" que confundiam o Gemini.

**Solução:** Limpo manualmente via Supabase. Para limpar no futuro:
```sql
-- Verificar histórico
SELECT id, remotejid, conversation_history
FROM "LeadboxCRM_XXX"
WHERE remotejid = '556697194084@s.whatsapp.net';

-- Limpar histórico
UPDATE "LeadboxCRM_XXX"
SET conversation_history = '[]'::jsonb
WHERE remotejid = '556697194084@s.whatsapp.net';
```

### 2.8 Conversão queue_id Float para Int
**Problema:** Gemini enviava `queue_id=454.0` (float) em vez de `454` (int), resultando em mensagem "fila 454.0".

**Solução:** Conversão explícita no handler:
```python
if queue_id is not None:
    queue_id = int(queue_id)
if user_id is not None:
    user_id = int(user_id)
```

---

## 3. Correções Anteriores (sessões passadas)

### Token UAZAPI por Agente
- **Problema:** Código usava API key global do `.env` para UAZAPI
- **Solução:** Cada agente usa seu próprio `uazapi_token` e `uazapi_base_url` do banco
- **Arquivo:** `app/webhooks/whatsapp.py`

```python
# Criar instancia do UazapiService com o token do agente
agent_uazapi_token = context.get("uazapi_token")
agent_uazapi_base_url = context.get("uazapi_base_url")

if agent_uazapi_token and agent_uazapi_base_url:
    uazapi = UazapiService(base_url=agent_uazapi_base_url, api_key=agent_uazapi_token)
else:
    uazapi = self._get_uazapi()  # fallback global
```

### Logs de DEBUG (6 etapas)
- `[DEBUG 1/6]` - Mensagem recebida (phone, remotejid, texto, instance_id)
- `[DEBUG 2/6]` - Busca do agente no Supabase
- `[DEBUG 3/6]` - Adição ao buffer Redis + agendamento
- `[DEBUG 4/6]` - Processamento após buffer (typing, histórico)
- `[DEBUG 5/6]` - Chamada ao Gemini e resposta
- `[DEBUG 6/6]` - Envio via UAZAPI e confirmação

### Logs de TRANSFER (novos)
- `[TRANSFER]` - Logs detalhados da transferência Leadbox

---

## 4. Integração Leadbox

### Configuração no Banco (campo `handoff_triggers`)
```json
{
    "type": "leadbox_api",
    "enabled": true,
    "api_url": "https://enterprise-135api.leadbox.app.br",
    "api_uuid": "cdb38332-5820-4f60-962d-6a1da38a78a5",
    "api_token": "eyJhbGciOiJIUzI1NiIs...",
    "departments": {
        "financeiro": {"id": 454, "userId": 814},
        "vendas": {"id": 123, "userId": 456}
    }
}
```

### Uso pela IA (Tool `transferir_departamento`)
```python
# Por nome do departamento
transferir_departamento(departamento="financeiro", motivo="Cliente quer falar de pagamento")

# Ou por IDs diretos (preferido - Gemini usa isso)
transferir_departamento(queue_id=454, user_id=814, motivo="Solicitação do cliente")
```

### Fluxo de Transferência
1. Gemini detecta intenção de transferência
2. Chama `transferir_departamento(queue_id=454, motivo="...")`
3. Handler lê `handoff_triggers` do contexto
4. Cria `LeadboxService` com credenciais
5. Chama `POST /v1/api/external/{api_uuid}` com payload:
   ```json
   {
     "number": "5566971940XX",
     "body": "motivo...",
     "forceTicketToDepartment": true,
     "queueId": 454,
     "forceTicketToUser": true,
     "userId": 814
   }
   ```
6. Marca lead: `Atendimento_Finalizado = "true"`
7. Retorna mensagem de sucesso para o Gemini
8. Gemini responde ao usuário

---

## 5. Estrutura dos Arquivos

```
/var/www/phant/agente-ia/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app, webhook /webhooks/dynamic
│   ├── config.py                  # Settings (env vars via Pydantic)
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── redis.py               # Buffer de mensagens, pause/resume, locks
│   │   ├── gemini.py              # Cliente Gemini AI com function calling
│   │   ├── supabase.py            # Cliente Supabase (agents, leads, messages)
│   │   ├── uazapi.py              # Cliente UAZAPI (send text, media, typing)
│   │   └── leadbox.py             # Cliente Leadbox (transferência de atendimento)
│   │
│   ├── webhooks/
│   │   ├── __init__.py
│   │   └── whatsapp.py            # WhatsAppWebhookHandler (fluxo principal)
│   │
│   └── tools/
│       ├── __init__.py
│       └── functions.py           # Function declarations para Gemini
│
├── requirements.txt
├── .env
└── CONTEXT.md                     # Este arquivo
```

---

## 6. Fluxo de Processamento

```
1. UAZAPI envia webhook para /webhooks/dynamic
2. WhatsAppWebhookHandler extrai dados (EventType: messages)
3. Busca agente por instance_id ou token no Supabase
4. Verifica comandos de controle (/p, /a, /r)
5. Verifica se bot está pausado
6. Adiciona mensagem ao buffer Redis
7. Aguarda 14 segundos (agrupa mensagens sequenciais)
8. Busca histórico de conversa no Supabase
9. Envia para Gemini processar (com function calling)
10. Se function call: executa handler, retorna resultado ao Gemini
11. Envia resposta via UAZAPI usando token do agente
12. Salva histórico atualizado no Supabase
```

---

## 7. Formato do Payload UAZAPI

```json
{
  "BaseUrl": "https://agoravai.uazapi.com",
  "EventType": "messages",
  "chat": {
    "id": "rd4a838f5a0ab2b",
    "name": "Fornecedor",
    "phone": "+55 66 9719-4084",
    "wa_chatid": "556697194084@s.whatsapp.net",
    "wa_name": "Vitor Hugo"
  },
  "message": {
    "chatid": "556697194084@s.whatsapp.net",
    "content": { "text": "oi" },
    "fromMe": false,
    "isGroup": false,
    "messageType": "ExtendedTextMessage",
    "messageid": "3EB037586786C404AB37F9",
    "senderName": "Vitor Hugo",
    "text": "oi",
    "wasSentByApi": false
  },
  "instanceName": "Agent_14e6e5ce",
  "token": "a2d9bb9c-c939-4c22-a656-7f80495681d9"
}
```

---

## 8. Tabela agents (campos relevantes)

| Campo | Tipo | Descrição |
|-------|------|-----------|
| id | uuid | ID único do agente |
| name | string | Nome do agente |
| status | string | active, inactive |
| whatsapp_provider | string | uazapi, evolution |
| uazapi_instance_id | string | ID da instância UAZAPI (ex: Agent_14e6e5ce) |
| uazapi_token | string | Token de autenticação UAZAPI |
| uazapi_base_url | string | URL base da UAZAPI |
| table_leads | string | Nome da tabela de leads |
| table_messages | string | Nome da tabela de mensagens |
| system_prompt | text | Prompt do agente |
| handoff_triggers | jsonb | Config do Leadbox (api_url, api_uuid, api_token, departments) |

---

## 9. Comandos Úteis

```bash
# Reiniciar serviço
pm2 restart agente-ia

# Ver logs em tempo real
pm2 logs agente-ia --lines 100

# Filtrar logs de debug
pm2 logs agente-ia | grep -E "DEBUG|TRANSFER|GEMINI|UAZAPI"

# Ver payload salvo (debug)
cat /tmp/uazapi_message_payload.json | jq

# Testar endpoint
curl -X GET https://ia.phant.com.br/webhooks/dynamic

# Configurar webhook UAZAPI para um agente
curl -X POST "https://agoravai.uazapi.com/webhook" \
  -H "Content-Type: application/json" \
  -H "token: TOKEN_DO_AGENTE" \
  -d '{"webhookUrl": "https://ia.phant.com.br/webhooks/dynamic"}'

# Limpar histórico de um lead
# (usar Supabase dashboard ou API)
```

---

## 10. Variáveis de Ambiente (.env)

```env
# Servidor
PORT=3005
APP_ENV=production

# Google AI (Gemini)
GOOGLE_API_KEY=...
GEMINI_MODEL=gemini-2.0-flash-exp

# Supabase
SUPABASE_URL=...
SUPABASE_SERVICE_KEY=...

# Redis
REDIS_URL=redis://localhost:6379/0

# UAZAPI (fallback global - cada agente tem seu próprio token)
UAZAPI_BASE_URL=https://agoravai.uazapi.com
UAZAPI_API_KEY=...
```

---

## 11. Próximos Passos (opcionais)

- [ ] Implementar transcrição de áudio (Whisper)
- [ ] Implementar análise de imagem (Gemini Vision)
- [x] ~~Implementar handler para transferência~~ ✅ Leadbox integrado
- [ ] Implementar handler para agenda (Google Calendar)
- [ ] Remover logs de debug em produção
- [ ] Atualizar biblioteca `google.generativeai` para `google.genai`
- [ ] Melhorar tratamento de erros do Gemini após function calls

---

## 12. Problemas Conhecidos

### Gemini retorna vazio após function call
- **Status:** Mitigado com fallback
- **Causa:** Biblioteca `google.generativeai` retorna `candidates=[]` após enviar function response
- **Workaround:** Usar mensagem do resultado da function como resposta

### Aviso de deprecação da biblioteca
```
FutureWarning: All support for the `google.generativeai` package has ended.
Please switch to the `google.genai` package as soon as possible.
```
- **Ação futura:** Migrar para `google.genai`

---

*Última atualização: 2026-01-27 01:10*
