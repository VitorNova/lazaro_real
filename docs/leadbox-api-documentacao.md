# Documentacao Leadbox API — Lazaro Producao

**Ultima atualizacao:** 2026-03-06
**Agente:** Ana (14e6e5ce-4627-4e38-aac8-f0191669ff53)
**Status:** Testado e validado em producao

---

## Resumo de Limitacoes da API (IMPORTANTE!)

| Limitacao | Impacto | Workaround |
|-----------|---------|------------|
| GET /tickets nao funciona | Nao da pra consultar tickets pela API | Salvar ticket_id via webhook |
| PUT /tickets nao atribui usuario | userId no PUT nao aparece na interface | Usar POST PUSH com forceTicketToUser |
| POST PUSH sempre envia mensagem | Nao existe PUSH silencioso | Usar PUT para operacoes silenciosas |
| closingReasonId nao funciona | Nao da pra fechar com motivo via API | Fechar sem motivo |
| GET /closing-reasons nao existe | Nao da pra listar motivos de fechamento | N/A |

---

## Credenciais de Producao

| Parametro | Valor |
|-----------|-------|
| **Base URL** | `https://enterprise-135api.leadbox.app.br` |
| **API UUID** | `be475918-cc86-4721-bfb4-6a9b287f92e3` |
| **API Token** | JWT (armazenado em `agents.leadbox_config`) |
| **Tenant ID** | `123` |
| **Queue IA** | `537` |
| **User IA** | `1095` |

### Como Extrair Credenciais da URL Leadbox

Se voce receber uma URL completa do Leadbox, extraia assim:

```
https://enterprise-135api.leadbox.app.br/v1/api/external/be475918-cc86-4721-bfb4-6a9b287f92e3/?token=eyJhbGci...
|___________________________________|                    |____________________________________|        |____________|
           api_url                                                  api_uuid                            api_token
```

| Campo | Como extrair | Exemplo |
|-------|--------------|---------|
| `api_url` | Tudo **antes** de `/v1/api/external` | `https://enterprise-135api.leadbox.app.br` |
| `api_uuid` | **Entre** `/v1/api/external/` e `/?token=` | `be475918-cc86-4721-bfb4-6a9b287f92e3` |
| `api_token` | Tudo **depois** de `?token=` | `eyJhbGciOiJIUzI1NiIs...` (JWT completo) |

### Onde Configurar

Tabela `agents`, coluna `leadbox_config` (JSONB):

```json
{
  "api_url": "https://enterprise-135api.leadbox.app.br",
  "api_uuid": "be475918-cc86-4721-bfb4-6a9b287f92e3",
  "api_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**SQL para atualizar:**
```sql
UPDATE agents
SET leadbox_config = '{
  "api_url": "https://enterprise-135api.leadbox.app.br",
  "api_uuid": "SEU-UUID-AQUI",
  "api_token": "SEU-TOKEN-JWT-AQUI"
}'::jsonb
WHERE id = 'ID-DO-AGENTE';
```

---

## Endpoints da API Leadbox

### 1. API PUSH — Criar/Transferir Ticket (METODO CORRETO)

**Endpoint:**
```
POST /v1/api/external/{api_uuid}
```

**URL completa:**
```
https://enterprise-135api.leadbox.app.br/v1/api/external/be475918-cc86-4721-bfb4-6a9b287f92e3
```

**Headers:**
```json
{
  "Authorization": "Bearer {api_token}",
  "Content-Type": "application/json",
  "Accept": "application/json"
}
```

### ⚠️ CRITICO: Campo `body` SEMPRE ENVIA MENSAGEM!

| Campo `body` | Comportamento | Testado |
|--------------|---------------|---------|
| `"body": "Texto"` | **ENVIA MENSAGEM** para o cliente no WhatsApp | ✅ 2026-03-06 |
| `"body": ""` | **ENVIA MENSAGEM VAZIA** (aparece no chat) | ✅ 2026-03-06 |
| Omitir `body` | **⚠️ TAMBEM ENVIA VAZIO** - usuario confirmou | ✅ 2026-03-06 |

> **DESCOBERTA CRITICA (2026-03-06):** Mesmo omitindo o campo `body`, uma mensagem vazia aparece no WhatsApp do cliente! Nao existe forma 100% silenciosa via API PUSH para criar/transferir ticket.

---

**Payload para TRANSFERIR + ATRIBUIR (COM mensagem para cliente):**
```json
{
  "number": "5566999887766",
  "body": "O departamento ideal vai falar com voce.",  // <-- ENVIA ESTA MSG PRO CLIENTE!
  "externalKey": "transfer-5566999887766-544",
  "forceTicketToDepartment": true,
  "queueId": 544,
  "forceTicketToUser": true,
  "userId": 1095
}
```

**Payload para TRANSFERIR + ATRIBUIR (SEM campo body):**
```json
{
  "number": "5566999887766",
  "externalKey": "transfer-5566999887766-544",
  "forceTicketToDepartment": true,
  "queueId": 544,
  "forceTicketToUser": true,
  "userId": 1095
}
```
> **⚠️ ATENCAO:** Mesmo SEM o campo `body`, uma mensagem vazia pode aparecer no WhatsApp do cliente! Testado em 2026-03-06.

---

**Payload para CRIAR TICKET NOVO (COM mensagem):**
```json
{
  "number": "5566999887766",
  "body": "Ola! Como posso ajudar?",  // <-- ENVIA ESTA MSG PRO CLIENTE!
  "externalKey": "new-ticket-001",
  "queueId": 537
}
```

**Payload para CRIAR TICKET NOVO (SEM campo body):**
```json
{
  "number": "5566999887766",
  "externalKey": "new-ticket-001",
  "queueId": 537
}
```
> **⚠️ ATENCAO:** Mesmo SEM o campo `body`, uma mensagem vazia pode aparecer no WhatsApp do cliente!

---

> **IMPORTANTE:** Este e o UNICO metodo que atribui usuario de verdade na interface do Leadbox. O `PUT /tickets/{id}` com userId NAO funciona para atribuir usuario.

**Resposta de sucesso:**
```json
{
  "message": {
    "ticketId": 123456
  },
  "ticket": {
    "id": 123456,
    "queueId": 544,
    "userId": 1095,
    "variables": {
      "extrasAPI": {
        "isForceTicketToDepartment": true,
        "isForceTicketToUser": true,
        "queueId": 544,
        "userId": 1095
      }
    }
  }
}
```

**Evidencia no codigo:** `apps/ia/app/services/leadbox.py:264-293`

### Teste Real (2026-03-06)

Transferencia do lead Vitor Hugo (556697194084) para Financeiro (454) com usuario TIELI (814):

```bash
curl -X POST "https://enterprise-135api.leadbox.app.br/v1/api/external/be475918-cc86-4721-bfb4-6a9b287f92e3" \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{
    "number": "556697194084",
    "externalKey": "test-transfer-financeiro",
    "forceTicketToDepartment": true,
    "queueId": 454,
    "forceTicketToUser": true,
    "userId": 814
  }'
```

**Resultado:** Ticket transferido para fila FINANCEIRO (454) E atribuido a TIELI (814) na interface.

---

### 2. PUT Ticket — Atualizar Fila (Silencioso, SEM atribuir usuario)

**Endpoint:**
```
PUT /tickets/{ticket_id}
```

**URL completa:**
```
https://enterprise-135api.leadbox.app.br/tickets/{ticket_id}
```

**Payload para TRANSFERIR FILA:**
```json
{
  "queueId": 544
}
```

**Payload para FECHAR TICKET:**
```json
{
  "status": "closed"
}
```

**Resposta de sucesso:**
```json
{
  "id": 852562,
  "status": "closed",
  "queueId": 454,
  "userId": 814,
  "closedAt": "1772807193358",
  "closingReasonId": null
}
```

**Evidencia no codigo:** `apps/ia/app/integrations/leadbox/client.py:536-576`

> **IMPORTANTE:** Este endpoint NAO envia mensagem para o cliente. Apenas atualiza metadados do ticket.

> **ATENCAO:** O campo `userId` no PUT **NAO ATRIBUI** o atendente na interface do Leadbox! Apenas atualiza o campo no banco. Para atribuir usuario de verdade, use a **API PUSH** com `forceTicketToUser: true`.

> **LIMITACAO (testado 2026-03-06):** O campo `closingReasonId` NAO funciona via API. Mesmo enviando um valor, retorna `null`. O endpoint `/closing-reasons` nao existe na API.

### Teste Real - Fechar Ticket (2026-03-06)

Fechamento do ticket 852562 (Vitor Hugo):

```bash
curl -X PUT "https://enterprise-135api.leadbox.app.br/tickets/852562" \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{"status": "closed"}'
```

**Resultado:** Ticket fechado com sucesso. Campo `closedAt` preenchido com timestamp.

---

### 3. GET Contacts — Buscar Contato por Telefone

**Endpoint:**
```
GET /contacts?searchParam={phone}&limit=1
```

**URL completa:**
```
https://enterprise-135api.leadbox.app.br/contacts?searchParam=5566999887766&limit=1
```

**Resposta de sucesso:**
```json
{
  "contacts": [
    {
      "id": 641492,
      "number": "5566999887766",
      "name": "Joao Silva",
      "email": null
    }
  ]
}
```

**Evidencia no codigo:** `apps/ia/app/services/leadbox.py:660-672`

---

### 4. GET Tickets — Buscar Tickets do Contato

**Endpoint:**
```
GET /tickets?contactId={contact_id}&status=open,pending&limit=10
```

**URL completa:**
```
https://enterprise-135api.leadbox.app.br/tickets?contactId=641492&status=open,pending&limit=10
```

**Resposta de sucesso:**
```json
{
  "tickets": [
    {
      "id": 841898,
      "status": "open",
      "queueId": 537,
      "userId": 1095,
      "contactId": 641492
    }
  ]
}
```

> **BUG CONHECIDO:** Este endpoint pode retornar erro 500 `"userId undefined"` quando chamado via token de API externa. O sistema trata isso como fail-open.

**Evidencia no codigo:** `apps/ia/app/services/leadbox.py:703-779`

---

### 5. Health Check

**Endpoint:**
```
GET /health
```

**URL completa:**
```
https://enterprise-135api.leadbox.app.br/health
```

**Resposta de sucesso (testado 2026-03-06):**
```json
{
  "postgres": "ok",
  "redis": "ok"
}
```

**Status:** HTTP 200 = OK

**Evidencia no codigo:** `apps/ia/app/services/leadbox.py:530-550`

---

## Bug Critico: GET /tickets NAO FUNCIONA

### Problema

O endpoint `GET /tickets` retorna erro 500 quando chamado via token de API externa:

```bash
GET /tickets?contactId=777295&status=open
```

**Resposta de erro:**
```json
{
  "error": "Internal server error: Error: WHERE parameter \"userId\" has invalid \"undefined\" value"
}
```

### Teste Real (2026-03-06)

```bash
# Passo 1: Buscar contato - FUNCIONA
curl -X GET "https://enterprise-135api.leadbox.app.br/contacts?searchParam=556697194084&limit=1"
# Resposta: {"contacts": [{"id": 777295, "name": "Vitor Hugo", ...}]}

# Passo 2: Buscar tickets do contato - FALHA
curl -X GET "https://enterprise-135api.leadbox.app.br/tickets?contactId=777295&status=open"
# Resposta: {"error": "Internal server error: Error: WHERE parameter \"userId\" has invalid \"undefined\" value"}

# Passo 3: Consultar ticket direto (se souber o ID) - FUNCIONA
curl -X PUT "https://enterprise-135api.leadbox.app.br/tickets/852562" -d '{}'
# Resposta: {"id": 852562, "queueId": 537, "userId": 1095, "status": "pending", ...}
```

### Resumo de Endpoints

| Endpoint | Funciona? | Uso |
|----------|-----------|-----|
| `GET /contacts?searchParam={phone}` | ✅ Sim | Buscar contact_id pelo telefone |
| `GET /tickets?contactId={id}` | ❌ NAO | Bug da API - erro 500 |
| `PUT /tickets/{ticket_id}` | ⚠️ Parcial | Consultar ticket, mudar fila, fechar. **NAO atribui usuario!** |
| `POST /v1/api/external/{uuid}` | ✅ Sim | Criar ticket, enviar mensagem, **transferir fila E atribuir usuario** |

### Diferenca entre PUT e POST PUSH

| Acao | PUT /tickets/{id} | POST /v1/api/external |
|------|-------------------|----------------------|
| Consultar ticket | ✅ | ❌ |
| Mudar fila (queueId) | ✅ | ✅ com `forceTicketToDepartment: true` |
| Atribuir usuario (userId) | ❌ **NAO FUNCIONA** | ✅ com `forceTicketToUser: true` |
| Fechar ticket | ✅ **TESTADO** | ❌ |
| Reabrir ticket | ✅ **TESTADO** | ❌ |
| Criar ticket novo | ❌ | ✅ (se nao tem ticket aberto) |
| Enviar msg pro cliente | ❌ **NUNCA** | ⚠️ **SEMPRE envia (mesmo sem body)** |
| Silencioso (sem msg) | ✅ **SEMPRE** | ❌ **NAO EXISTE** |

### ⚠️ ALERTA: POST PUSH SEMPRE ENVIA MENSAGEM!

```
POST PUSH (qualquer payload)
    |
    v
SEMPRE ENVIA ALGUMA MENSAGEM NO WHATSAPP DO CLIENTE!
(mesmo omitindo o campo body, aparece mensagem vazia)
```

**Para operacoes verdadeiramente SILENCIOSAS, use PUT /tickets/{id}:**
```json
PUT /tickets/852562
{
  "queueId": 544
}
```
> **PUT nao envia mensagem** mas **tambem NAO atribui usuario**

**Se precisar atribuir usuario, nao tem como evitar a mensagem:**
```json
POST PUSH
{
  "number": "5566999887766",
  "forceTicketToDepartment": true,
  "queueId": 544,
  "forceTicketToUser": true,
  "userId": 1095
}
```
> Mesmo sem `body`, vai aparecer mensagem vazia no WhatsApp

### Testes Realizados (2026-03-06)

| Teste | Endpoint | Resultado |
|-------|----------|-----------|
| Consultar contato | GET /contacts?searchParam=556697194084 | ✅ Retornou contact_id 777295 |
| Buscar tickets | GET /tickets?contactId=777295 | ❌ Bug erro 500 |
| Consultar ticket | PUT /tickets/852562 (body vazio) | ✅ Retornou dados completos |
| Transferir fila (PUT) | PUT /tickets/852562 {"queueId": 454} | ⚠️ Fila mudou, usuario NAO atribuido |
| Transferir + atribuir | POST PUSH com forceTicketToUser | ✅ Fila E usuario atribuidos |
| Fechar ticket | PUT /tickets/852562 {"status": "closed"} | ✅ Ticket fechado |
| Reabrir ticket | PUT /tickets/852562 {"status": "open"} | ✅ Ticket reaberto |
| PUSH com ticket aberto | POST PUSH | ⚠️ Usa ticket existente, NAO cria novo |
| PUSH com ticket fechado | POST PUSH | ✅ Cria ticket NOVO (854488) |
| Health check | GET /health | ✅ HTTP 200, postgres/redis ok |
| PUSH sem body | POST PUSH (omitir body) | ⚠️ **ENVIA msg vazia no WhatsApp!** |
| Fechar com motivo | PUT {"status":"closed","closingReasonId":1} | ❌ closingReasonId ignorado (null) |
| Endpoint motivos | GET /closing-reasons | ❌ Endpoint nao existe |

### Comportamento do Campo `body` no PUSH

| Cenario | Payload | Resultado | Testado |
|---------|---------|-----------|---------|
| Com body | `{"body": "Teste"}` | **ENVIA "Teste" para o cliente no WhatsApp** | ✅ |
| Body vazio | `{"body": ""}` | **ENVIA mensagem VAZIA** (aparece no chat) | ✅ |
| Sem body | `{}` (omitir campo) | **⚠️ TAMBEM ENVIA VAZIO** no WhatsApp | ✅ |

> **⚠️ DESCOBERTA CRITICA (2026-03-06):** Nao existe forma de usar a API PUSH sem que alguma mensagem (mesmo vazia) apareca no WhatsApp do cliente! Para operacoes verdadeiramente silenciosas, use `PUT /tickets/{id}` (mas lembre que PUT nao atribui usuario).

### Como o Sistema Resolve

**Problema:** Sem `GET /tickets`, nao da pra descobrir o ticket_id de um lead apenas pelo telefone.

**Solucao:** O sistema salva o `ticket_id` no Supabase quando recebe webhooks do Leadbox.

```
1. Lead envia mensagem
2. Leadbox envia webhook com ticket_id no payload
3. Sistema salva ticket_id na tabela do lead (Supabase)
4. Quando precisa consultar, usa o ticket_id salvo
5. PUT /tickets/{ticket_id} retorna dados atualizados
```

**Fluxo de consulta real:**

```
Consultar fila do lead 556697194084
    |
    v
GET /contacts?searchParam=556697194084
    |
    v
contact_id = 777295
    |
    v
GET /tickets?contactId=777295  ❌ FALHA (bug)
    |
    v
Consultar Supabase: SELECT ticket_id FROM leads WHERE phone = '556697194084'
    |
    v
ticket_id = 852562
    |
    v
PUT /tickets/852562  ✅ FUNCIONA
    |
    v
Retorna: queueId=537, userId=1095, status=pending
```

**Evidencia no codigo:** `apps/ia/app/services/leadbox.py:703-779` (tratamento fail-open)

---

## Webhooks do Leadbox

### Endpoints que RECEBEM webhooks (nosso servidor):

```
POST https://lazaro.fazinzz.com/api/webhook
POST https://lazaro.fazinzz.com/webhooks/leadbox
```

### Eventos Processados

| Evento | Acao | Evidencia |
|--------|------|-----------|
| `NewMessage` | Processa mensagem com IA ou salva no historico | `leadbox_handler.py:22-66` |
| `UpdateOnTicket` | Atualiza queue_id, user_id, ticket_id | `leadbox.py:117-125` |
| `TransferOfTicket` | Mesmo tratamento de UpdateOnTicket | `leadbox.py:117-125` |
| `TicketClosed` (status=closed) | Limpa ticket_id, reativa IA | `leadbox_handler.py:69-180` |
| `QueueChange` | Pausa ou reativa IA | `leadbox_handler.py:183-358` |

### Eventos Ignorados

- `AckMessage` — Confirmacao de leitura
- `FinishedTicketHistoricMessages` — Historico carregado

**Evidencia no codigo:** `apps/ia/app/api/routes/leadbox.py:34`

---

## Filas Configuradas

| Queue ID | Nome | Funcao |
|----------|------|--------|
| **537** | Fila IA | Fila principal onde IA responde |
| **544** | Billing | Cobranca (injeta prompt de billing) |
| **545** | Manutencao | Manutencao preventiva |
| **517** | Cobrancas | Departamento humano |
| **454** | Financeiro | Departamento humano |
| **453** | Atendimento | Departamento humano (DEFAULT) |

**Evidencia no codigo:** `apps/ia/app/integrations/leadbox/types.py:17-20`

---

## Funcoes Principais no Codigo

### Transferir para Departamento

```python
# apps/ia/app/services/leadbox.py:223-359
await service.transfer_to_department(
    phone="5566999887766",
    queue_id=544,           # Fila destino
    user_id=1095,           # Usuario (opcional)
    mensagem="Transferindo" # None=default, ""=silencioso
)
```

### Atribuir Usuario Silencioso (sem mensagem)

```python
# apps/ia/app/services/leadbox.py:415-528
await service.assign_user_silent(
    phone="5566999887766",
    queue_id=537,
    user_id=1095,
    ticket_id=123456
)
```

### Dispatch Inteligente (Billing)

```python
# apps/ia/app/integrations/leadbox/dispatch.py:29-243
result = await leadbox_push_silent(
    phone="5566999887766",
    queue_id=544,
    agent_id="14e6e5ce-...",
    message="Sua fatura vence amanha"
)
# result.ticket_existed = True se ticket ja existia
# result.message_sent_via_push = True se PUSH enviou a mensagem
```

---

## Logica de Decisao: Ticket Existe ou Nao?

```
leadbox_push_silent() chamado
    |
    v
Buscar contato: GET /contacts?searchParam={phone}
    |
    v
Contato encontrado?
    |-- NAO --> PUSH cria ticket novo + envia mensagem
    |
    v
Buscar tickets: GET /tickets?contactId={id}&status=open
    |
    v
Ticket aberto existe?
    |-- SIM --> PUT /tickets/{id} (move fila, SEM mensagem)
    |           Caller envia mensagem via UAZAPI
    |
    |-- NAO --> PUSH cria ticket novo + envia mensagem
```

---

## Payload do Webhook Leadbox (Exemplo)

```json
{
  "event": "NewMessage",
  "tenantId": 123,
  "message": {
    "messageId": "3EB0...",
    "ticketId": 841898,
    "contactId": 641492,
    "tenantId": 123,
    "msgCreatedAt": "2026-03-06T10:00:00.000Z",
    "body": "Ola, preciso de ajuda",
    "fromMe": false,
    "sendType": "WEBHOOK",
    "mediaType": "text",
    "mediaUrl": null,
    "ticket": {
      "id": 841898,
      "status": "open",
      "queueId": 537,
      "userId": 1095,
      "closedAt": null,
      "closingReasonId": null,
      "contact": {
        "id": 641492,
        "number": "5566999887766",
        "name": "Cliente Teste"
      }
    }
  }
}
```

---

## Ciclo de Vida do Ticket

| # | Cenario | Cobertura | Arquivo |
|---|---------|-----------|---------|
| 1 | Ticket criado | Parcial | `leadbox_handler.py:249-252` |
| 2 | Ticket atribuido a fila | Coberto | `leadbox_handler.py:183-358` |
| 3 | Ticket transferido entre filas | Coberto | `leadbox_handler.py:297-316` |
| 4 | Ticket atribuido a atendente | Coberto | `leadbox_handler.py:361-473` |
| 5 | Mensagem recebida | Coberto | `leadbox_handler.py:22-66` |
| 6 | Mensagem enviada (humano) | Coberto | `leadbox_handler.py:54-59` |
| 7 | Ticket fechado | Coberto | `leadbox_handler.py:69-180` |

---

## Testes Manuais

### Teste 1: Consultar contato
```bash
curl -X GET "https://enterprise-135api.leadbox.app.br/contacts?searchParam=5566999887766&limit=1" \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json"
```

### Teste 2: Buscar tickets abertos
```bash
curl -X GET "https://enterprise-135api.leadbox.app.br/tickets?contactId=641492&status=open" \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json"
```

### Teste 3: Consultar dados do ticket
```bash
curl -X PUT "https://enterprise-135api.leadbox.app.br/tickets/841898" \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{}'
```

### Teste 4: Transferir para fila (CUIDADO - ALTERA ESTADO)
```bash
curl -X PUT "https://enterprise-135api.leadbox.app.br/tickets/841898" \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{"queueId": 544, "userId": 1095}'
```

### Teste 5: Fechar ticket (CUIDADO - ALTERA ESTADO)
```bash
curl -X PUT "https://enterprise-135api.leadbox.app.br/tickets/841898" \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{"status": "closed"}'
```

---

## Arquivos de Referencia

| Arquivo | Descricao |
|---------|-----------|
| `apps/ia/app/services/leadbox.py` | LeadboxService principal |
| `apps/ia/app/integrations/leadbox/client.py` | LeadboxClient refatorado |
| `apps/ia/app/integrations/leadbox/dispatch.py` | Dispatch inteligente para billing |
| `apps/ia/app/integrations/leadbox/types.py` | Tipos e constantes |
| `apps/ia/app/api/routes/leadbox.py` | Rotas de webhook |
| `apps/ia/app/api/handlers/leadbox_handler.py` | Handlers de eventos |
| `apps/ia/app/ai/tools/transfer_tools.py` | Tools de transferencia para Gemini |

---

## Tags

#leadbox #api #webhook #integracao #lazaro #producao
