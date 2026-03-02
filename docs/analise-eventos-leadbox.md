# Análise de Eventos do Webhook Leadbox

**Data:** 2026-03-02
**Arquivo analisado:** `/var/www/lazaro-v2/apps/ia/app/main.py` (linhas 605-1294)

---

## 1. MAPEAMENTO DE WEBHOOKS ATUAIS

### 1.1. Endpoints Configurados

| Endpoint | Descrição | Arquivo |
|----------|-----------|---------|
| `/webhooks/leadbox` | Eventos do Leadbox (tickets, mensagens) | `main.py:605` |
| `/webhooks/dynamic` | Mensagens WhatsApp via UAZAPI | `main.py:530` |
| `/webhooks/asaas` | Pagamentos Asaas | `pagamentos.py` |

### 1.2. Eventos Processados pelo `/webhooks/leadbox`

| Evento | Status | Ação Executada |
|--------|--------|----------------|
| `NewMessage` | ✅ PROCESSADO | Processa mensagem do lead com IA (fromMe=false) ou salva histórico do humano (fromMe=true) |
| `UpdateOnTicket` | ✅ PROCESSADO | Atualiza `current_queue_id`, `current_user_id`, `ticket_id` no Supabase |
| `TransferOfTicket` | ✅ PROCESSADO | Mesmo tratamento de UpdateOnTicket - detecta mudança de fila |
| `AckMessage` | 🚫 IGNORADO | Confirmação de leitura - sem ação |
| `FinishedTicketHistoricMessages` | 🚫 IGNORADO | Histórico completo - sem ação |

### 1.3. Lógica de Processamento Atual

```
Mensagem/Evento chega
    ↓
Verifica event_type
    ↓
Se NewMessage (fromMe=false):
    → Processa com IA via handler.handle_message()
    ↓
Se NewMessage (fromMe=true, não API):
    → Salva no histórico como "model" (humano)
    ↓
Extrai dados: queue_id, user_id, ticket_id, phone
    ↓
Verifica se queue_id está em IA_QUEUES (537, 544, 545, etc.)
    ↓
Se SIM (fila IA):
    → Atendimento_Finalizado = "false"
    → Limpa pause no Redis
    → Força userId para queue_ia_user_id (auto-assign)
    ↓
Se NÃO (fila humana):
    → Atendimento_Finalizado = "true"
    → Seta pause no Redis
    → IA PAUSADA
```

---

## 2. ANÁLISE DO EVENTO "FECHAR TICKET"

### 2.1. Situação Atual: ❌ NÃO EXISTE TRATAMENTO ESPECÍFICO

**Evidência nos logs:**
- Todos os payloads observados têm `status: "open"` ou `status: "group"`
- Campo `closedAt: null` em todos os tickets abertos
- Campo `closingReasonId: null` enquanto aberto

**Campos relevantes no payload que indicam fechamento:**
```json
{
  "ticket": {
    "status": "closed",      // ← muda de "open" para "closed"
    "closedAt": "2026-03-02T...",  // ← timestamp do fechamento
    "closingReasonId": 123   // ← motivo do fechamento
  }
}
```

### 2.2. O que acontece HOJE quando um ticket é fechado?

1. Leadbox envia evento `UpdateOnTicket` com `status: "closed"`
2. O webhook processa normalmente (não há filtro para status)
3. Como `closedAt` não é `null`, o ticket está fechado
4. **PROBLEMA:** O código NÃO verifica o campo `status` ou `closedAt`
5. **RESULTADO:** O sistema pode tentar atualizar um lead para um ticket fechado

### 2.3. Impacto do GAP

| Cenário | Impacto |
|---------|---------|
| Ticket fechado pelo humano | Lead continua com `current_queue_id` da última fila |
| Lead envia mensagem após fechamento | Novo ticket criado, mas `ticket_id` no banco está desatualizado |
| Reabertura de ticket | Sistema pode ter dados inconsistentes |

---

## 3. MAPEAMENTO DE GAPS

### 3.1. Eventos NÃO Tratados

| Evento Possível | Status | Impacto |
|-----------------|--------|---------|
| `CloseTicket` / Ticket fechado | ⚠️ GAP | Não limpa `ticket_id`, não registra fechamento |
| `ReopenTicket` / Ticket reaberto | ⚠️ GAP | Não detecta reabertura |
| `NewTicket` / Ticket criado | ⚠️ GAP | Race condition com webhook WhatsApp |
| `DeleteTicket` | ⚠️ GAP | Ticket deletado não é tratado |
| `AssignTicket` | ✅ OK | Tratado via `UpdateOnTicket` (userId muda) |

### 3.2. Cenários de Ciclo de Vida do Ticket

| # | Cenário | Cobertura | Arquivo/Linha |
|---|---------|-----------|---------------|
| 1 | Ticket criado | ⚠️ Parcial | `main.py:909-954` - cria lead se não existe |
| 2 | Ticket atribuído a fila | ✅ Coberto | `main.py:860-974` - UpdateOnTicket |
| 3 | Ticket transferido entre filas | ✅ Coberto | `main.py:998-1083` - detecta queue_id |
| 4 | Ticket atribuído a atendente | ✅ Coberto | `main.py:1039-1073` - auto-assign |
| 5 | Mensagem recebida | ✅ Coberto | `main.py:636-837` - NewMessage |
| 6 | Mensagem enviada (humano) | ✅ Coberto | `main.py:666-737` - salva histórico |
| 7 | **Ticket fechado** | ❌ NÃO COBERTO | --- |
| 8 | **Ticket reaberto** | ❌ NÃO COBERTO | --- |
| 9 | **Ticket deletado** | ❌ NÃO COBERTO | --- |

### 3.3. Dados Importantes no Payload do Leadbox

```python
# Campos que indicam estado do ticket (extraídos dos logs reais)
ticket = {
    "id": 841898,
    "status": "open",           # "open", "closed", "pending", "group"
    "closedAt": null,           # null = aberto, timestamp = fechado
    "closingReasonId": null,    # ID do motivo de fechamento
    "queueId": 517,             # Fila atual
    "userId": 1090,             # Atendente atual
    "contactId": 641492,        # ID do contato
    "tenantId": 123,            # ID do tenant
}
```

---

## 4. RECOMENDAÇÕES

### 4.1. Correção Prioritária: Tratar Fechamento de Ticket

**Arquivo:** `apps/ia/app/main.py`
**Local:** Após linha 860 (antes do loop de agentes)

```python
# SUGESTÃO: Adicionar verificação de ticket fechado
ticket_status = ticket.get("status", "open")
closed_at = ticket.get("closedAt")

if ticket_status == "closed" or closed_at is not None:
    logger.info(
        "[LEADBOX WEBHOOK] Ticket %s FECHADO - limpando dados do lead %s",
        ticket_id, phone
    )
    # Limpar ticket_id do lead (ticket não existe mais)
    # Manter current_queue_id para referência histórica
    # Registrar timestamp de fechamento
    for ag in (agents.data or []):
        table_leads = ag.get("table_leads")
        if table_leads:
            try:
                supabase_svc.client.table(table_leads) \
                    .update({
                        "ticket_id": None,
                        "ticket_closed_at": closed_at or datetime.utcnow().isoformat(),
                        "closing_reason_id": body.get("ticket", {}).get("closingReasonId"),
                    }) \
                    .eq("remotejid", f"{phone}@s.whatsapp.net") \
                    .execute()
            except Exception as e:
                logger.debug("Erro ao limpar ticket: %s", e)
    return {"status": "ok", "event": "ticket_closed"}
```

### 4.2. Melhorias de Rastreabilidade

1. **Adicionar colunas ao Supabase:**
   - `ticket_closed_at` (timestamp)
   - `closing_reason_id` (integer)
   - `last_ticket_id` (integer) - preserva histórico

2. **Criar evento de log estruturado:**
   ```python
   logger.info({
       "event": "ticket_lifecycle",
       "action": "closed",
       "ticket_id": ticket_id,
       "phone": phone,
       "closing_reason": closing_reason_id,
   })
   ```

### 4.3. Priorização

| Prioridade | Ação | Justificativa |
|------------|------|---------------|
| 🔴 ALTA | Tratar ticket fechado | Dados inconsistentes no CRM |
| 🟡 MÉDIA | Registrar fechamento no histórico | Análise de conversões |
| 🟢 BAIXA | Tratar reabertura | Caso raro |

---

## 5. CONCLUSÃO

O sistema atual **NÃO trata explicitamente o fechamento de tickets**. O webhook Leadbox processa eventos de atualização, mas não verifica se o ticket foi fechado (`status: "closed"` ou `closedAt != null`).

**Impacto prático:**
- Leads mantêm `ticket_id` de tickets que já foram fechados
- Quando o lead envia nova mensagem, a consulta `get_current_queue()` pode retornar dados inconsistentes
- Não há registro histórico de quando os atendimentos foram encerrados

**Ação recomendada:** Implementar verificação de `ticket.status == "closed"` ou `ticket.closedAt != null` no início do webhook para limpar dados e registrar o fechamento.
