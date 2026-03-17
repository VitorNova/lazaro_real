# DOMAIN.md — Vocabulário e Regras de Negócio

> Última atualização: 2026-03-17
> Este arquivo documenta o domínio do negócio. Para processo de desenvolvimento → `CLAUDE.md`.

---

## Clientes (Tenants)

| Tenant ID | Empresa | Ramo | Cidade |
|-----------|---------|------|--------|
| `123` | Aluga Ar | Locação de ar-condicionado | Rondonópolis/MT |

---

## Agentes

### Ana (SDR Principal)

| Campo | Valor |
|-------|-------|
| **Nome** | Ana |
| **UUID** | `14e6e5ce` (prefixo) |
| **Tenant** | 123 (Aluga Ar) |
| **Fila IA** | 537 |
| **User ID Leadbox** | 1095 |
| **Tabela Leads** | `LeadboxCRM_Ana_14e6e5ce` |
| **Tabela Mensagens** | `leadbox_messages_Ana_14e6e5ce` |
| **Porta** | 3115 (lazaro-ia) |

---

## Filas Leadbox

| ID | Nome | Tipo | Responsável | Comportamento |
|----|------|------|-------------|---------------|
| `537` | IA Genérica | IA | Ana (Gemini) | Processa mensagens |
| `544` | Billing | IA | Ana (prompt cobrança) | Processa com contexto de cobrança |
| `545` | Manutenção | IA | Ana (prompt manutenção) | Processa com contexto de manutenção |
| `453` | Atendimento | Humano | Nathália | IA pausa, aguarda humano |
| `454` | Financeiro | Humano | Tieli | IA pausa, aguarda humano |

**Regra de pausa:**
- Lead em fila 453 ou 454 → IA **pausada** (Redis flag)
- Lead em fila 537, 544 ou 545 → IA **ativa**

---

## Fluxo de Entrada: Quando um Lead Envia Mensagem

Este é o fluxo **INBOUND** — o que acontece quando um lead envia uma mensagem no WhatsApp e o webhook do Leadbox chega no sistema.

### Regra Principal

> **Lead NOVO → userId=null → Sistema atribui userId=1095 automaticamente**
>
> Quando um lead envia a primeira mensagem, o Leadbox cria o ticket SEM atendente (`userId=null`).
> O sistema detecta isso e faz auto-assign para Ana (`userId=1095`) via `PUT /tickets/{id}`.

| Cenário | userId no webhook | Sistema faz auto-assign? |
|---------|------------------|--------------------------|
| Lead NOVO (1ª mensagem) | `null` | ✅ Sim → 1095 |
| Lead transferido por humano | `1095` | ❌ Não (anti-loop) |
| Lead volta de fila humana | `null` ou `1095` | Depende do valor |

### Passo a Passo Completo

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. LEAD ENVIA MENSAGEM NO WHATSAPP                                          │
│    → Ex: "Olá, quero saber sobre locação de ar-condicionado"                │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 2. LEADBOX CRIA TICKET AUTOMATICAMENTE                                       │
│    → Ticket novo com userId=null (sem atendente)                            │
│    → queueId=537 (fila padrão de entrada)                                   │
│    → status=pending                                                         │
│    → Leadbox dispara webhook UpdateOnTicket                                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 3. WEBHOOK CHEGA NO SISTEMA                                                  │
│    → POST /webhooks/leadbox                                                 │
│    → Arquivo: apps/ia/app/api/routes/leadbox.py:30                          │
│    → Event: UpdateOnTicket                                                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 4. EXTRAÇÃO DE DADOS DO PAYLOAD                                              │
│    → ticket_id = ticket.id                                                  │
│    → queue_id = ticket.queueId (537)                                        │
│    → user_id = ticket.userId (null!)                                        │
│    → phone = contact.number ("556697194084")                                │
│    → tenant_id = ticket.tenantId (123)                                      │
│    → Arquivo: apps/ia/app/api/routes/leadbox.py:84-104                      │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 5. ROTEAMENTO PARA handle_queue_change()                                     │
│    → Condição: phone && queue_id presentes                                  │
│    → Arquivo: apps/ia/app/api/routes/leadbox.py:130-135                     │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 6. BUSCA AGENTE POR TENANT                                                   │
│    → SELECT FROM agents WHERE active=true                                   │
│    → Filtra por handoff_triggers.tenant_id = 123                            │
│    → Encontra: Ana (agent_id=14e6e5ce...)                                   │
│    → Arquivo: apps/ia/app/api/handlers/leadbox_handler.py:214-235           │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 7. VERIFICA/CRIA LEAD NO SUPABASE                                            │
│    → SELECT FROM LeadboxCRM_Ana_14e6e5ce WHERE remotejid LIKE '%phone%'     │
│    → Se não existe: create_lead_if_missing()                                │
│    → Arquivo: apps/ia/app/api/handlers/leadbox_handler.py:244-255           │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 8. DETECTA QUE É FILA IA                                                     │
│    → queue_id (537) está em IA_QUEUES {537, 544, 545}? SIM                  │
│    → Chama _handle_ia_queue()                                               │
│    → Arquivo: apps/ia/app/api/handlers/leadbox_handler.py:304-310           │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 9. AUTO-ASSIGN userId 1095                                                   │
│    → Compara: userId atual (null) ≠ userId alvo (1095)                      │
│    → Log: "[LEADBOX HANDLER] Forçando userId: None -> 1095"                 │
│    → Chama assign_user_silent(phone, queue_id=537, user_id=1095)            │
│    → PUT /tickets/{ticket_id} com {"queueId": 537, "userId": 1095}          │
│    → ⚠️ LIMITAÇÃO: PUT não mostra userId na interface Leadbox!              │
│    → Arquivo: apps/ia/app/api/handlers/leadbox_handler.py:428-460           │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 10. ATUALIZA ESTADO LOCAL                                                    │
│    → Supabase UPDATE:                                                       │
│      • current_queue_id = 537                                               │
│      • current_user_id = 1095                                               │
│      • ticket_id = {novo_ticket_id}                                         │
│      • current_state = "ai"                                                 │
│      • Atendimento_Finalizado = "false"                                     │
│    → Redis: pause CLEAR (IA ativa)                                          │
│    → Arquivo: apps/ia/app/api/handlers/leadbox_handler.py:462-472           │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 11. LEAD PRONTO PARA PROCESSAMENTO IA                                        │
│    → Próxima mensagem será processada pelo Gemini                           │
│    → Buffer de 14s → GEMINI → UAZAPI                                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Payload Real de UpdateOnTicket

```json
{
  "event": "UpdateOnTicket",
  "ticket": {
    "id": 869025,
    "status": "pending",
    "queueId": 537,
    "userId": null,          // ← SEM ATENDENTE ATRIBUÍDO!
    "tenantId": 123,
    "contactId": 777295,
    "lastMessage": "oi",
    "origem": "C"            // C = cliente iniciou
  },
  "contact": {
    "id": 777295,
    "name": "Vitor Hugo",
    "number": "556697194084"
  }
}
```

### Logs Esperados (pm2 logs lazaro-ia)

```
[LEADBOX HANDLER] Lead 556697194084 | ticket=869025 | queue=537 | user=None | tenant=123
[LEADBOX HANDLER] Agente: Ana | tenant: 123 | queue_anterior: None
[LEADBOX HANDLER] Fila IA detectada: queue=537 | userId_atual=None | userId_alvo=1095 | phone=556697194084
[LEADBOX HANDLER] Forçando userId: None -> 1095 para lead 556697194084
[ASSIGN SILENT] Atribuindo userId=1095 ao ticket=869025 sem enviar mensagem
[AUTO ASSIGN] Lead 556697194084 forçado para userId=1095 com sucesso
[LEADBOX HANDLER] Redis pause LIMPA para agent=14e6e5ce
[LEADBOX HANDLER] Core update OK: LeadboxCRM_Ana_14e6e5ce | dados=['Atendimento_Finalizado', 'current_state', 'paused_at', 'paused_by']
[LEADBOX HANDLER] Queue update OK: LeadboxCRM_Ana_14e6e5ce | queue=537 | user=1095
```

### Limitação Conhecida: PUT vs Interface Leadbox

| Campo | PUT atualiza no ticket? | Aparece na interface Leadbox? |
|-------|------------------------|------------------------------|
| `queueId` | ✅ Sim | ✅ Sim |
| `userId` | ✅ Sim (backend) | ❌ **NÃO** |
| `status` | ✅ Sim | ✅ Sim |

**Por que isso importa?**
- O userId é salvo no Supabase (`current_user_id = 1095`)
- Mas o painel do Leadbox ainda mostra "Sem atendente"
- Para o SISTEMA funciona corretamente
- Para o VISUAL do Leadbox, não aparece

**Workaround:** Quando o sistema faz POST PUSH (billing/manutenção), o userId **aparece** na interface.

---

## Auto-Assign de Usuário IA (userId 1095)

Quando um lead entra na fila IA, o sistema força a atribuição do userId configurado (`queue_ia_user_id`).

### Fluxo de Atribuição

```
┌─────────────────────────────────────────────────────────────────────────┐
│ 1. LEAD ENVIA MENSAGEM (ou sistema dispara billing/manutenção)          │
│    → Leadbox CRIA ticket automaticamente                                │
│    → Webhook UpdateOnTicket chega com userId=null, queueId=537          │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 2. HANDLER DETECTA FILA IA                                              │
│    → queue_id (537) está em IA_QUEUES? SIM                              │
│    → Compara: userId atual (null) ≠ userId alvo (1095)                  │
│    → Log: "[LEADBOX HANDLER] Forçando userId: None -> 1095"             │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 3. TENTATIVA DE ATRIBUIÇÃO SILENCIOSA                                   │
│    → Chama assign_user_silent(phone, queue_id=537, user_id=1095)        │
│    → Faz PUT /tickets/{id} com {"queueId": 537, "userId": 1095}         │
│    → ⚠️ LIMITAÇÃO: PUT não atribui userId na interface Leadbox!         │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 4. ATUALIZAÇÃO LOCAL                                                    │
│    → Supabase: current_user_id = "1095"                                 │
│    → Redis: pause CLEAR (IA reativada)                                  │
│    → Log: "[AUTO ASSIGN] Lead X forçado para userId=1095 com sucesso"   │
└─────────────────────────────────────────────────────────────────────────┘
```

### Diferença entre PUT e PUSH

| Operação | Atribui userId na interface? | Envia mensagem? | Quando usar |
|----------|------------------------------|-----------------|-------------|
| **PUT** /tickets/{id} | ❌ **NÃO** (bug/limitação API) | ❌ Não | Auto-assign silencioso |
| **POST PUSH** com `forceTicketToUser` | ✅ **SIM** | ✅ Sempre | Disparo billing/manutenção |

### Cenários de Atribuição

| Cenário | Método | userId aparece no Leadbox? |
|---------|--------|---------------------------|
| Lead envia mensagem | PUT | ❌ Não (apenas no Supabase) |
| Job billing dispara | PUSH | ✅ Sim |
| Job manutenção dispara | PUSH | ✅ Sim |
| Lead volta de fila humana | PUT | ❌ Não (apenas no Supabase) |

### Anti-Loop

Se o userId já é o correto (1095), o sistema apenas reativa a IA sem fazer nova chamada:

```
[LEADBOX HANDLER] Anti-loop: userId já é 1095, apenas reativando IA
```

### Configuração no Agente

```json
{
  "handoff_triggers": {
    "queue_ia": 537,
    "queue_ia_user_id": 1095,
    "dispatch_departments": {
      "billing": {"queueId": 544, "userId": 1095},
      "manutencao": {"queueId": 545, "userId": 1095}
    }
  }
}
```

---

## Dispatch Inteligente (POST PUSH vs PUT)

O sistema usa uma lógica híbrida para enviar mensagens automáticas (billing/manutenção):

### Fluxo de Decisão

```
┌─────────────────────────────────────────────────────────────────────────┐
│ JOB DISPARA (billing_charge ou maintenance_notifier)                    │
│   → Precisa enviar mensagem para o lead                                 │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ PASSO 1: VERIFICAR SE TICKET JÁ EXISTE                                  │
│   → GET /contacts?searchParam={phone}                                   │
│   → Se encontrou contact_id: GET /tickets?contactId={id}&status=open    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
              ┌─────────────────────┴─────────────────────┐
              ▼                                           ▼
┌──────────────────────────────┐           ┌──────────────────────────────┐
│ TICKET EXISTE                │           │ TICKET NÃO EXISTE            │
│ (lead já está conversando)   │           │ (lead sem conversa ativa)    │
└──────────────────────────────┘           └──────────────────────────────┘
              │                                           │
              ▼                                           ▼
┌──────────────────────────────┐           ┌──────────────────────────────┐
│ CENÁRIO 1: PUT               │           │ CENÁRIO 2: POST PUSH         │
│   → PUT /tickets/{id}        │           │   → POST /v1/api/external/   │
│   → Move ticket para fila    │           │   → CRIA ticket novo         │
│   → NÃO envia mensagem       │           │   → ENVIA mensagem (body)    │
│   → Caller envia via UAZAPI  │           │   → ATRIBUI userId           │
│                              │           │   → Caller NÃO envia UAZAPI  │
│ message_sent_via_push=false  │           │ message_sent_via_push=true   │
└──────────────────────────────┘           └──────────────────────────────┘
              │                                           │
              ▼                                           ▼
┌──────────────────────────────┐           ┌──────────────────────────────┐
│ UAZAPI envia a mensagem      │           │ PUT de confirmação           │
│   → send_text_message()      │           │   → Aguarda 2 segundos       │
│                              │           │   → PUT /tickets/{id}        │
│                              │           │   → Garante fila correta     │
└──────────────────────────────┘           └──────────────────────────────┘
```

### Payload do POST PUSH

```json
{
  "number": "5566999887766",
  "body": "Olá! Sua fatura vence amanhã...",
  "externalKey": "push-1710680400",
  "forceTicketToDepartment": true,
  "queueId": 544,
  "forceTicketToUser": true,
  "userId": 1095
}
```

| Campo | Obrigatório | Descrição |
|-------|-------------|-----------|
| `number` | ✅ | Telefone (apenas dígitos, ex: 5566999887766) |
| `body` | ❌ | Mensagem para o cliente. **SEMPRE ENVIA** (mesmo vazio!) |
| `externalKey` | ❌ | Chave única para rastreamento |
| `forceTicketToDepartment` | ❌ | Se true, força ticket para queueId |
| `queueId` | ❌ | ID da fila destino (544=billing, 545=manutenção) |
| `forceTicketToUser` | ❌ | Se true, força atribuição para userId |
| `userId` | ❌ | ID do usuário/atendente (1095=Ana) |

### Resposta do POST PUSH

```json
{
  "message": {
    "ticketId": 869050
  },
  "ticket": {
    "id": 869050,
    "queueId": 544,
    "userId": 1095,
    "status": "open"
  }
}
```

### Por que PUT de Confirmação?

Após o POST PUSH, o sistema faz um PUT adicional porque:

1. **PUSH pode ignorar `forceTicketToDepartment`** em alguns casos
2. **Garante que o ticket está na fila correta** (544 ou 545)
3. **Aguarda 2 segundos** para o PUSH processar antes do PUT

```python
# apps/ia/app/services/leadbox_push.py:223-238
await asyncio.sleep(2)  # Aguarda PUSH processar
put_payload = {"queueId": queue_id, "userId": user_id}
await client.put(f"/tickets/{ticket_id}", json=put_payload)
```

### Quem Chama o Dispatch?

| Job/Serviço | Arquivo | Fila |
|-------------|---------|------|
| `billing_charge` | `billing/dispatcher.py:128` | 544 |
| `billing_orchestrator` | `domain/billing/services/billing_orchestrator.py:151` | 544 |
| `payment_message_service` | `domain/billing/services/payment_message_service.py:325` | 544 |
| `retry_deferred_job` | `jobs/retry_deferred_job.py:137` | 544 ou 545 |

### Retorno do Dispatch

```python
{
    "success": True,
    "ticket_existed": False,      # True = PUT usado, False = PUSH usado
    "ticket_id": 869050,
    "message_sent_via_push": True, # True = PUSH já enviou, não usar UAZAPI
    "ticket_check_failed": False,  # True = não conseguiu verificar, aborta
    "queue_confirmation_failed": False,  # True = PUT de confirmação falhou
}
```

### Lógica do Caller (quem chama o dispatch)

```python
push_result = await leadbox_push_silent(phone, queue_id, agent_id, message)

if push_result["success"]:
    if not push_result["message_sent_via_push"]:
        # Ticket já existia → PUSH não enviou → enviar via UAZAPI
        await uazapi.send_text_message(phone, message)
    # else: PUSH já enviou, não fazer nada
```

---

## Regras de Negócio da Ana

### Processamento de Mensagens

1. **Buffer de 14 segundos** — Agrupa mensagens consecutivas do mesmo lead antes de processar
2. **Lock distribuído** — Redis com TTL 60s, heartbeat a cada 20s (evita processamento duplicado)
3. **Assinatura** — Toda resposta inicia com `*Ana:*\n`
4. **Chunking** — Mensagens >4000 caracteres quebradas por parágrafo/frase
5. **Typing indicator** — Simula digitação antes de cada chunk

### Gemini AI

1. **Safety settings** — `BLOCK_NONE` para todas as categorias
2. **Retry automático** — 3 tentativas com backoff exponencial (2s, 4s, 8s)
3. **Timeout global** — 60 segundos
4. **Fallback** — Se Gemini falhar, envia mensagem de dificuldade técnica

### Fail-safe Leadbox

1. Se `current_queue_id=None` no banco → consulta API Leadbox em tempo real
2. Se API retorna fila humana (453/454) → ignora mensagem
3. Se API retorna fila IA (537/544/545) → processa normalmente

---

## Contextos de Disparo

| Contexto | Descrição | Job | Horário |
|----------|-----------|-----|---------|
| `manutencao_preventiva` | Lembrete D-7 antes da manutenção preventiva | `maintenance_notifier` | 09:00 (Cuiabá) |
| `billing` / `disparo_billing` | Cobrança automática de parcelas | `billing_charge` | 09:00 (São Paulo) |

### Detecção de Contexto

- Busca campo `context` nas **últimas 10 mensagens**
- Janela de tempo: **7 dias**
- Se encontrado, carrega prompt específico do `context_prompts` do agente
- Se não encontrado, usa prompt genérico

### Estrutura da Mensagem com Contexto

```json
{
  "role": "model",
  "parts": [{"text": "Sua manutenção está agendada..."}],
  "timestamp": "2026-03-17T09:00:00Z",
  "context": "manutencao_preventiva",
  "contract_id": "uuid-do-contrato"
}
```

---

## Glossário

| Termo | Definição |
|-------|-----------|
| **remotejid** | ID WhatsApp no formato `55DDD9XXXXXXXX@s.whatsapp.net` |
| **ticket** | Conversa ativa no Leadbox. Cada conversa = 1 ticket. Ticket fechado = sem conversa ativa |
| **handoff** | Transferência de lead da IA para atendente humano |
| **dispatch** | Envio de mensagem automática (billing, manutenção) |
| **buffer** | Fila temporária no Redis para agrupar mensagens antes de processar |
| **pause** | Flag Redis (`pause:{agent_id}:{phone}`) que impede a IA de responder |
| **BTU** | Unidade de capacidade de ar-condicionado (produto do Aluga Ar) |
| **PUSH** | POST na API Leadbox que cria/transfere ticket e **sempre envia mensagem** |
| **PUT** | Operação **silenciosa** no Leadbox (mover fila, fechar ticket, sem mensagem) |
| **context** | Campo nas mensagens que identifica o tipo de disparo (billing, manutenção) |
| **context_prompts** | Configuração do agente com prompts específicos por contexto |
| **IA_QUEUES** | Set de filas onde a IA processa: `{537, 544, 545}` |
| **HUMAN_QUEUES** | Filas humanas onde a IA pausa: `{453, 454}` |
| **UpdateOnTicket** | Webhook que o Leadbox dispara quando ticket é criado/modificado |
| **FinishedTicket** | Webhook que o Leadbox dispara quando ticket é fechado |
| **assign_user_silent** | Função que atribui userId via PUT (sem enviar mensagem) |
| **handle_queue_change** | Handler que processa mudanças de fila vindas do Leadbox |
| **INBOUND** | Fluxo de entrada: lead envia mensagem → webhook chega |
| **OUTBOUND** | Fluxo de saída: sistema dispara billing/manutenção → PUSH |

---

## Jobs Agendados

| Job | Horário | Fuso | Dias | Função |
|-----|---------|------|------|--------|
| `billing_reconciliation` | 06:00 | São Paulo | seg-sex | Reconcilia cobranças com Asaas |
| `billing_charge` | 09:00 | São Paulo | seg-sex | Dispara mensagens de cobrança |
| `maintenance_notifier` | 09:00 | Cuiabá | seg-sex | Dispara lembretes D-7 de manutenção |
| `follow_up` | cada 5 min | — | todos | Verifica follow-ups pendentes |

---

## Ciclo de Vida do Lead

```
┌─────────────────────────────────────────────────────────────┐
│ LEAD NOVO: Mensagem chega, ticket_id=null                   │
│   → Leadbox cria ticket automaticamente                     │
│   → Sistema atribui userId via PUT/PUSH                     │
│   → Supabase: ticket_id preenchido, current_state='ai'      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ CONVERSA ATIVA: Lead em fila 537 (IA)                       │
│   → Mensagens processadas pelo Gemini                       │
│   → Respostas enviadas via UAZAPI                           │
│   → Histórico salvo no Supabase                             │
└─────────────────────────────────────────────────────────────┘
                              │
           ┌──────────────────┴──────────────────┐
           ▼                                     ▼
┌───────────────────────┐           ┌───────────────────────┐
│ TRANSFERÊNCIA (453/454)│          │ TICKET FECHADO        │
│   → Tool transferir_  │           │   → Webhook Finished  │
│     departamento()    │           │   → ticket_id=null    │
│   → Redis pause SET   │           │   → current_state='ai'│
│   → current_state=    │           │   → Pronto para nova  │
│     'human'           │           │     conversa          │
└───────────────────────┘           └───────────────────────┘
           │
           ▼
┌───────────────────────┐
│ VOLTA PARA IA (537)   │
│   → Redis pause CLEAR │
│   → current_state='ai'│
│   → Gemini reativado  │
└───────────────────────┘
```

---

*Gerado a partir de: docs/apis/leadbox.md, docs/patterns/ana-agent.md, RUNBOOK.md*
