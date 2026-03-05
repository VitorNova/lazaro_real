# Supabase Integration - Convenções

## Tabelas Dinâmicas por Agente

Cada agente tem suas próprias tabelas. Os nomes são definidos no registro do agente:

| Campo | Exemplo | Descrição |
|-------|---------|-----------|
| `table_leads` | `LeadboxCRM_Ana_14e6e5ce` | Tabela de leads do agente |
| `table_messages` | `leadbox_messages_Ana_14e6e5ce` | Histórico de conversas |

### Padrão de Nomenclatura
```
{tipo}_{nome_agente}_{uuid[:8]}
```

Onde:
- `tipo`: `LeadboxCRM` ou `leadbox_messages`
- `nome_agente`: Nome do agente (ex: `Ana`, `EnzoComercial`)
- `uuid[:8]`: Primeiros 8 caracteres do UUID do agente

### IMPORTANTE: Nunca Construir Nome Manualmente

```python
# ERRADO - não faça isso
table_name = f"leadbox_messages_{agent_id.replace('-', '_')}"

# CORRETO - sempre usar o campo do agent
table_name = agent.get("table_messages")
table_leads = agent.get("table_leads")
```

### Onde Obter o Agent

```python
# Via Supabase
from app.services.supabase import get_supabase_service
supabase = get_supabase_service()
agent = supabase.get_agent_by_id(agent_id)
table_messages = agent["table_messages"]

# Via contexto (se disponível)
table_messages = context.get("table_messages")
```

## Estrutura de Dados

### LeadboxCRM (table_leads)
- `id`: ID do lead
- `remotejid`: WhatsApp JID (ex: `5566999999999@s.whatsapp.net`)
- `nome`, `telefone`, `email`
- `current_state`: `ai`, `human`, `active`
- `ticket_id`, `current_queue_id`, `current_user_id`
- `conversation_history`: JSON com histórico (deprecated - usar table_messages)
- `billing_context`: Contexto de cobrança

### leadbox_messages (table_messages)
- `id`: UUID
- `remotejid`: WhatsApp JID
- `conversation_history`: `{"messages": [...]}`
- `Msg_user`: Timestamp última msg do usuário
- `Msg_model`: Timestamp última msg da IA

### Formato de Mensagem no conversation_history
```json
{
  "messages": [
    {
      "role": "user",
      "parts": [{"text": "mensagem do usuario"}],
      "timestamp": "2026-03-05T14:04:37.262676",
      "context": "manutencao_preventiva",  // opcional
      "contract_id": "uuid-do-contrato"    // opcional
    },
    {
      "role": "model",
      "parts": [{"text": "resposta da IA"}],
      "timestamp": "2026-03-05T14:04:37.262676"
    }
  ]
}
```

## Arquivos Principais

| Arquivo | Responsabilidade |
|---------|------------------|
| `services/supabase.py` | Classe SupabaseService (sync) |
| `integrations/supabase/client.py` | Cliente base |
| `integrations/supabase/repositories/dynamic.py` | Operações async em tabelas dinâmicas |
| `integrations/supabase/repositories/agents.py` | CRUD de agentes |
