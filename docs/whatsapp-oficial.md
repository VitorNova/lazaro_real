# WhatsApp Business API Oficial — Guia Completo

> Documentação consolidada para migração do Lazaro de UAZAPI (não-oficial) para WhatsApp Cloud API (oficial).
>
> **Última atualização:** 2026-03-19

---

## Índice

1. [Visão Geral](#visão-geral)
2. [Modelo de Preços](#modelo-de-preços)
3. [Regra das 24 Horas](#regra-das-24-horas)
4. [Templates](#templates)
5. [Processo de Aprovação](#processo-de-aprovação)
6. [BSP (Business Solution Provider)](#bsp-business-solution-provider)
7. [Comparativo: UAZAPI vs Oficial](#comparativo-uazapi-vs-oficial)
8. [Impacto no Lazaro](#impacto-no-lazaro)
9. [Templates Necessários](#templates-necessários)
10. [Mudanças de Código](#mudanças-de-código)
11. [Plano de Migração](#plano-de-migração)
12. [Riscos e Mitigações](#riscos-e-mitigações)
13. [Guia Técnico para Desenvolvedores](#guia-técnico-para-desenvolvedores)

---

## Visão Geral

A **WhatsApp Business API** (também chamada WhatsApp Cloud API) é a solução oficial da Meta para empresas enviarem mensagens em escala via WhatsApp.

### Diferenças Fundamentais

| Aspecto | API Não-Oficial (UAZAPI) | API Oficial (Cloud API) |
|---------|--------------------------|-------------------------|
| Legalidade | Zona cinza, risco de ban | 100% autorizado pela Meta |
| Estabilidade | Depende de engenharia reversa | Garantida pela Meta |
| Custo | Fixo (R$ 97/mês) | Por mensagem + BSP |
| Templates | Não precisa | **Obrigatório** para iniciar conversa |
| Janela 24h | Não existe | **Obrigatória** |
| Typing indicator | ✅ Disponível | ❌ Não disponível |
| Mensagens livres | ✅ Sempre | ⚠️ Só dentro de 24h |

### Arquitetura

```
┌─────────────────────────────────────────────────────────────┐
│                        SUA APLICAÇÃO                        │
│                         (Lazaro)                            │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    BSP (360Dialog, etc.)                    │
│              Business Solution Provider                      │
│         • Gerencia conexão com Meta                         │
│         • Interface para templates                          │
│         • Webhooks e callbacks                              │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                   WhatsApp Cloud API                        │
│                        (Meta)                               │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                      WhatsApp App                           │
│                   (Celular do Cliente)                      │
└─────────────────────────────────────────────────────────────┘
```

---

## Modelo de Preços

### Mudança de Julho 2025

Antes: Cobrança por **conversa** (janela de 24h = 1 conversa)
Agora: Cobrança por **mensagem entregue**

### Categorias de Mensagem

| Categoria | Preço Brasil (USD) | Preço Brasil (BRL)* | Quando Usar |
|-----------|-------------------|---------------------|-------------|
| **Marketing** | $0.0625 | ~R$ 0,35 | Promoções, ofertas, campanhas |
| **Utility** | $0.0068 | ~R$ 0,04 | Cobranças, lembretes, confirmações |
| **Authentication** | $0.0068 | ~R$ 0,04 | Códigos OTP, verificação |
| **Service** | **GRÁTIS** | R$ 0,00 | Resposta dentro de 24h |

*Conversão aproximada: 1 USD = 5,60 BRL

### Tiers de Volume (Utility - Brasil)

| Volume Mensal | Preço/Msg | Desconto |
|---------------|-----------|----------|
| 0 - 250.000 | $0.0068 | 0% |
| 250.001 - 2.000.000 | $0.0065 | -4% |
| 2.000.001 - 10.000.000 | $0.0052 | -24% |
| 10.000.001+ | $0.0041 | -40% |

### Simulação de Custo Lazaro (Base: Março 2026)

**Dados reais de março:**
- Disparos billing: 616
- Disparos manutenção: 16
- Respostas IA (estimado): ~1.663

**Cenário 1: Tudo como Utility**
```
616 × $0.0068 = $4.19 (billing)
 16 × $0.0068 = $0.11 (manutenção)
────────────────────────
Total: $4.30 (~R$ 24/mês)
```

**Cenário 2: Utility + Service (dentro de 24h)**
```
632 × $0.0068 = $4.30 (templates proativos)
1.663 × $0.00 = $0.00 (respostas IA - GRÁTIS dentro de 24h)
────────────────────────
Total: $4.30 (~R$ 24/mês)
```

**Custo Total com BSP:**
```
BSP (360Dialog):     €49/mês  = ~R$ 280
Mensagens Utility:              ~R$ 24
─────────────────────────────────────
TOTAL:                         ~R$ 304/mês
```

**vs. UAZAPI atual: R$ 97/mês**

---

## Regra das 24 Horas

### Como Funciona

```
CLIENTE ENVIA MENSAGEM
         │
         ▼
┌─────────────────────────────────────┐
│      JANELA DE 24H ABERTA           │
│                                     │
│  ✅ Responder com texto livre       │
│  ✅ Enviar mídia                    │
│  ✅ Múltiplas mensagens             │
│  ✅ Custo: GRÁTIS (Service)         │
│                                     │
└─────────────────────────────────────┘
         │
         │ 24 horas depois...
         ▼
┌─────────────────────────────────────┐
│      JANELA FECHADA                 │
│                                     │
│  ❌ Texto livre bloqueado           │
│  ❌ Mídia bloqueada                 │
│                                     │
│  ✅ Apenas TEMPLATES permitidos     │
│  💰 Custo: Utility/Marketing        │
│                                     │
└─────────────────────────────────────┘
```

### Impacto Prático

| Cenário | UAZAPI (atual) | Oficial |
|---------|----------------|---------|
| Cliente manda msg → IA responde | ✅ Sempre funciona | ✅ Funciona (grátis) |
| IA inicia conversa (billing) | ✅ Texto livre | ⚠️ Só template |
| Cliente não responde em 24h → IA quer mandar msg | ✅ Funciona | ❌ Bloqueado (precisa template) |
| Lead inativo há 3 dias → follow-up | ✅ Texto livre | ⚠️ Só template (pago) |

### Renovação da Janela

A janela de 24h é **renovada** a cada mensagem do cliente:

```
09:00 - Cliente: "Oi"           → Janela abre (até 09:00 do dia seguinte)
09:05 - IA: "Olá! Como posso ajudar?"
14:00 - Cliente: "Qual o valor?"  → Janela RENOVA (até 14:00 do dia seguinte)
14:02 - IA: "O valor é R$ 150..."
...
(24h sem mensagem do cliente)
...
14:03 (dia seguinte) - Janela FECHA
14:04 - IA tenta responder → ❌ BLOQUEADO
```

---

## Templates

### O que são Templates

Templates são mensagens **pré-aprovadas pela Meta** que podem ser enviadas a qualquer momento, mesmo fora da janela de 24h.

### Estrutura de um Template

```
┌─────────────────────────────────────────────────────────────┐
│ HEADER (opcional)                                           │
│ Tipos: texto, imagem, vídeo, documento (PDF)                │
│ Limite texto: 60 caracteres                                 │
├─────────────────────────────────────────────────────────────┤
│ BODY (obrigatório)                                          │
│ Mensagem principal com variáveis {{1}}, {{2}}, etc.         │
│ Limite: 1.024 caracteres                                    │
│                                                             │
│ Exemplo:                                                    │
│ "Olá {{1}}, sua fatura de R$ {{2}} vence em {{3}}."        │
├─────────────────────────────────────────────────────────────┤
│ FOOTER (opcional)                                           │
│ Texto secundário em cinza                                   │
│ Limite: 60 caracteres                                       │
│ Exemplo: "Mensagem automática - não responda"               │
├─────────────────────────────────────────────────────────────┤
│ BUTTONS (opcional, máximo 3)                                │
│ Tipos:                                                      │
│   • URL: abre link externo                                  │
│   • PHONE: inicia ligação                                   │
│   • QUICK_REPLY: resposta rápida (texto)                    │
│                                                             │
│ Exemplo: [🔗 Pagar] [📞 Ligar] [❓ Dúvidas]                  │
└─────────────────────────────────────────────────────────────┘
```

### Variáveis (Placeholders)

Variáveis permitem personalização dinâmica:

```
Template registrado:
"Olá {{1}}, sua fatura de R$ {{2}} vence em {{3}}."

Enviado com valores:
"Olá João, sua fatura de R$ 150,00 vence em 25/03."
```

**Regras de variáveis:**
- Formato: `{{1}}`, `{{2}}`, `{{3}}` (números sequenciais)
- ❌ Não pode começar com variável
- ❌ Não pode terminar com variável
- ❌ Não pode ter duas variáveis adjacentes sem texto
- ✅ Deve ter contexto ao redor

```
❌ ERRADO: "{{1}}, sua fatura vence amanhã."
❌ ERRADO: "Sua fatura vence em {{1}}"
❌ ERRADO: "{{1}}{{2}} tem pendência"
✅ CERTO:  "Olá {{1}}, sua fatura de R$ {{2}} vence em {{3}}."
```

### Categorias de Template

| Categoria | Uso | Preço | Exemplos |
|-----------|-----|-------|----------|
| **Utility** | Transacional, iniciado por ação do usuário | $0.0068 | Confirmação de pedido, lembrete de pagamento, status de entrega |
| **Marketing** | Promocional, não solicitado | $0.0625 | Ofertas, descontos, lançamentos, reengajamento |
| **Authentication** | Verificação de identidade | $0.0068 | Código OTP, 2FA |

**⚠️ Atenção:** Se você registrar como Utility mas a Meta considerar promocional, ela **reclassifica automaticamente** para Marketing (9x mais caro).

---

## Processo de Aprovação

### Timeline

| Fase | Tempo | Observação |
|------|-------|------------|
| Review automático (ML) | Minutos | Maioria dos casos |
| Review humano | Até 48h | Se ML tiver dúvida |
| Template Pacing | 1-3 dias | Teste com ~1.000 destinatários |

### Status Possíveis

| Status | Significado | O que fazer |
|--------|-------------|-------------|
| **Pending** | Em análise | Aguardar (máx 48h) |
| **Approved** | Aprovado | Pode usar |
| **Rejected** | Rejeitado | Corrigir e reenviar com nome DIFERENTE |
| **Paused** | Pausado por feedback negativo | Melhorar conteúdo, reduzir volume |
| **Disabled** | Desativado permanentemente | Criar template completamente novo |

### 27 Motivos de Rejeição

**Formato (1-9):**
1. Variável `{{1}}` no início da mensagem
2. Variável no final da mensagem
3. Duas variáveis adjacentes sem texto (`{{1}}{{2}}`)
4. Numeração fora de ordem (`{{1}}`, `{{3}}`, `{{2}}`)
5. Placeholder malformado (`{1}` ao invés de `{{1}}`)
6. Espaços em branco excessivos
7. Mais de 10 emojis
8. Texto todo em MAIÚSCULAS
9. Body excede 1.024 caracteres

**Conteúdo (10-17):**
10. Conteúdo genérico demais
11. Conteúdo enganoso ou falso
12. Solicita informações sensíveis (senha, cartão)
13. Imita mensagens de sistema
14. Terminologia de jogos/apostas
15. Conteúdo adulto ou violento
16. Ameaças ou coerção
17. Linguagem discriminatória

**Política (18-24):**
18. Viola Termos de Serviço do WhatsApp
19. Viola Commerce Policy
20. Viola Business Policy
21. Categoria incorreta (promo em Utility)
22. Idioma não corresponde ao selecionado
23. Empresa não verificada no Facebook Business Manager
24. Setor restrito (tabaco, armas, farmacêutico)

**Técnico (25-27):**
25. Exemplos de variáveis não fornecidos
26. URL inválida em botões
27. Nome do template já usado (cooldown de 30 dias)

### Template Pacing

Após aprovação, a Meta **não libera 100% do volume imediatamente**:

```
Dia 1: Template aprovado
       ↓
       Meta testa em ~1.000 destinatários
       ↓
Dia 2-3: Analisa métricas (bloqueios, spam reports)
       ↓
       Se positivo → Libera 100%
       Se negativo → PAUSA o template
```

**⚠️ Não planeje campanha grande no dia 1 de um template novo.**

### Fluxo de Submissão

```
1. Acessar painel do BSP (360Dialog, Twilio, etc.)
         │
         ▼
2. Criar novo template:
   • Nome único (snake_case, ex: cobranca_lembrete_d1)
   • Categoria (Utility/Marketing/Authentication)
   • Idioma (pt_BR)
   • Header (opcional: texto, imagem, vídeo, PDF)
   • Body (texto com variáveis {{1}}, {{2}})
   • Footer (opcional)
   • Buttons (opcional, máx 3)
   • Exemplos de valores para cada variável
         │
         ▼
3. Submeter para Meta
         │
         ▼
4. Aguardar aprovação (minutos a 48h)
         │
         ├─── Aprovado → Pode usar
         │
         └─── Rejeitado → Corrigir problema
                          Criar NOVO template com nome diferente
                          (nome original bloqueado por 30 dias)
```

### Dicas para Aprovação Rápida

1. **Sempre forneça exemplos** realistas para cada variável
2. **Não misture** conteúdo promocional em templates Utility
3. **Seja específico** — quanto mais contexto, melhor
4. **Evite CAPS LOCK** — parece spam
5. **Use tom profissional** — evite gírias excessivas
6. **Inclua opt-out** se for Marketing ("Responda SAIR para cancelar")
7. **Teste com volume baixo** antes de campanha grande
8. **Monitore qualidade** — muitos bloqueios = template pausado

---

## BSP (Business Solution Provider)

### O que é

BSP é um **intermediário autorizado pela Meta** para acessar a WhatsApp Business API. Você não conecta diretamente na API da Meta — precisa de um BSP.

### Por que precisa de BSP

- Meta não oferece acesso direto a pequenas/médias empresas
- BSP gerencia infraestrutura, webhooks, templates
- BSP oferece suporte técnico
- BSP simplifica integração

### Principais BSPs

| BSP | Preço Base | Msg Inclusa | Destaque |
|-----|------------|-------------|----------|
| **360Dialog** | €49/mês | 0 | Mais barato, API simples |
| WATI | $49/mês | 1.000 | Interface amigável |
| Twilio | $0 + uso | 0 | Pay-as-you-go, mais flexível |
| Gupshup | Variável | Variável | Bom para alto volume |
| MessageBird | €50/mês | 0 | Multicanal |

### Recomendação para Lazaro: 360Dialog

**Por quê:**
- Menor custo fixo (€49/mês ≈ R$ 280)
- API REST simples e bem documentada
- Sem markup adicional nas mensagens (paga direto preço Meta)
- Suporte técnico responsivo
- Webhook fácil de configurar

---

## Comparativo: UAZAPI vs Oficial

### Funcionalidades

| Funcionalidade | UAZAPI | Oficial |
|----------------|--------|---------|
| Enviar texto | ✅ Sempre | ⚠️ 24h ou template |
| Enviar mídia | ✅ Sempre | ⚠️ 24h ou template |
| Receber mensagens | ✅ Webhook | ✅ Webhook |
| Typing indicator | ✅ Disponível | ❌ Não existe |
| Read receipts | ✅ Disponível | ✅ Disponível |
| Mensagem longa (chunking) | ✅ Automático | ✅ Manual |
| Iniciar conversa | ✅ Texto livre | ⚠️ Só template |
| Responder cliente | ✅ Sempre | ✅ Grátis em 24h |
| Número dedicado | ✅ Qualquer | ✅ Verificado pela Meta |
| Risco de ban | ⚠️ Alto | ✅ Zero |

### Custos (Base Março 2026)

| Item | UAZAPI | Oficial |
|------|--------|---------|
| Mensalidade | R$ 97 | R$ 280 (BSP) |
| Billing (616 msgs) | R$ 0 | R$ 24 |
| Manutenção (16 msgs) | R$ 0 | R$ 1 |
| Respostas IA (~1.663) | R$ 0 | R$ 0 (dentro de 24h) |
| **TOTAL** | **R$ 97** | **~R$ 305** |

### Código

| Aspecto | UAZAPI | Oficial |
|---------|--------|---------|
| Cliente HTTP | `UazapiClient` | `WhatsAppOfficialClient` (novo) |
| Envio simples | `send_text_message(phone, text)` | `send_template(phone, template, params)` |
| Envio livre | `send_text_message(phone, text)` | `send_text_message(phone, text)` ⚠️ só em 24h |
| Webhook format | Proprietário UAZAPI | Cloud API (diferente) |
| Tracking 24h | Não precisa | **Obrigatório** |

---

## Impacto no Lazaro

### Fluxos Atuais e Adaptações

#### 1. Billing Job (Cobrança)

**Atual (UAZAPI):**
```python
message = format_billing_message(customer_name, value, due_date)
await uazapi.send_text_message(phone, message)
```

**Oficial:**
```python
await whatsapp.send_template(
    phone=phone,
    template="cobranca_lembrete",
    params=["João", "150,00", "25/03"],
    buttons=[{"type": "url", "url": payment_link}]
)
```

#### 2. Manutenção Job

**Atual:**
```python
message = f"Olá {name}, seu veículo {vehicle} tem manutenção em {date}..."
await uazapi.send_text_message(phone, message)
```

**Oficial:**
```python
await whatsapp.send_template(
    phone=phone,
    template="manutencao_preventiva",
    params=[name, vehicle, date]
)
```

#### 3. Resposta da IA

**Atual:**
```python
# IA gera texto livre
response = await gemini.generate(context)
await uazapi.send_ai_response(phone, response)  # chunking automático
```

**Oficial:**
```python
# Verificar se janela está aberta
if await window_tracker.is_open(phone):
    # Dentro de 24h - pode enviar texto livre (GRÁTIS)
    await whatsapp.send_text_message(phone, response)
else:
    # Fora de 24h - só template (PAGO)
    # Opção 1: Enviar template de reengajamento
    await whatsapp.send_template(phone, "reengajamento", [...])
    # Opção 2: Não responder (aguardar cliente)
    logger.warning(f"Janela fechada para {phone}, não respondendo")
```

#### 4. Transferência para Humano

**Atual:**
```python
await uazapi.send_text_message(phone, "Transferindo para atendimento...")
await leadbox.transfer_ticket(phone, queue_id=453)
```

**Oficial:**
```python
if await window_tracker.is_open(phone):
    await whatsapp.send_text_message(phone, "Transferindo para atendimento...")
else:
    await whatsapp.send_template(phone, "transferencia_atendimento", [...])
await leadbox.transfer_ticket(phone, queue_id=453)
```

### O que NÃO muda

- Lógica de negócio (billing rules, manutenção rules)
- Integração Leadbox (filas, tickets)
- Integração Asaas (cobranças, webhooks)
- Processamento Gemini (IA)
- Redis (buffer, pausas)
- Supabase (leads, histórico)

### O que MUDA

| Componente | Mudança |
|------------|---------|
| `integrations/uazapi/` | Substituir por `integrations/whatsapp_official/` |
| `billing/dispatcher.py` | Usar templates ao invés de texto |
| `jobs/notificar_manutencoes.py` | Usar templates |
| `message_processor.py` | Adicionar verificação de janela 24h |
| `webhooks/mensagens.py` | Adaptar formato de payload |
| Typing indicator | **Remover** (não existe na API oficial) |

---

## Templates Necessários

### Lista Mínima (7 templates)

| Nome | Categoria | Uso | Variáveis |
|------|-----------|-----|-----------|
| `cobranca_lembrete_d2` | Utility | D-2 antes do vencimento | nome, valor, data |
| `cobranca_lembrete_d1` | Utility | D-1 antes do vencimento | nome, valor, data |
| `cobranca_vencimento` | Utility | Dia do vencimento (D0) | nome, valor |
| `cobranca_atraso` | Utility | D+1 a D+15 (vencido) | nome, valor, dias_atraso |
| `manutencao_preventiva` | Utility | Lembrete D-7 | nome, veiculo, data |
| `confirmacao_pagamento` | Utility | Pagamento recebido | nome, valor |
| `reengajamento_24h` | Marketing | Quando janela expira | nome |

### Exemplos de Conteúdo

#### `cobranca_lembrete_d2`
```
Olá {{1}},

Sua mensalidade de R$ {{2}} vence em {{3}}.

Para sua comodidade, segue o link de pagamento:

[🔗 Pagar Agora]

Dúvidas? Responda esta mensagem.
```

#### `cobranca_lembrete_d1`
```
Olá {{1}},

Lembrete: sua mensalidade de R$ {{2}} vence AMANHÃ ({{3}}).

Evite juros pagando hoje:

[🔗 Pagar Agora]
```

#### `cobranca_vencimento`
```
Olá {{1}},

Hoje é o último dia para pagar sua mensalidade de R$ {{2}} sem juros.

[🔗 Pagar Agora]

Já pagou? Desconsidere esta mensagem.
```

#### `cobranca_atraso`
```
Olá {{1}},

Sua mensalidade de R$ {{2}} está em atraso há {{3}} dias.

Regularize sua situação para evitar encargos adicionais:

[🔗 Pagar com Desconto]

Dificuldades? Responda para negociar.
```

#### `manutencao_preventiva`
```
Olá {{1}},

Seu veículo {{2}} tem manutenção preventiva agendada para {{3}}.

[✓ Confirmar] [📅 Reagendar]
```

#### `confirmacao_pagamento`
```
Olá {{1}},

Confirmamos o recebimento do seu pagamento de R$ {{2}}.

Obrigado pela confiança!

Qualquer dúvida, estamos à disposição.
```

#### `reengajamento_24h`
```
Olá {{1}},

Notamos que você não respondeu nossa última mensagem.

Podemos ajudar com algo?

[💬 Sim, preciso de ajuda] [❌ Não, obrigado]
```

---

## Mudanças de Código

### Novos Arquivos

```
apps/ia/app/integrations/whatsapp_official/
├── __init__.py
├── client.py              # WhatsAppOfficialClient
├── models.py              # TemplateMessage, WebhookPayload, etc.
├── templates.py           # Definições dos templates
└── window_tracker.py      # ConversationWindowTracker (Redis)
```

### Arquivos Modificados

| Arquivo | Mudança |
|---------|---------|
| `billing/dispatcher.py` | Usar `send_template()` ao invés de texto |
| `jobs/notificar_manutencoes.py` | Usar `send_template()` |
| `domain/messaging/services/message_processor.py` | Verificar janela 24h antes de responder |
| `webhooks/mensagens.py` | Adaptar parsing do webhook |
| `api/routes/webhooks.py` | Endpoint para webhook oficial |

### Exemplo: WhatsAppOfficialClient

```python
# apps/ia/app/integrations/whatsapp_official/client.py

import httpx
from typing import Optional, List, Dict, Any
from datetime import datetime

class WhatsAppOfficialClient:
    """Cliente para WhatsApp Cloud API via 360Dialog."""

    def __init__(self, api_key: str, phone_number_id: str):
        self.api_key = api_key
        self.phone_number_id = phone_number_id
        self.base_url = "https://waba.360dialog.io/v1"

    async def send_template(
        self,
        phone: str,
        template_name: str,
        language: str = "pt_BR",
        components: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """
        Envia mensagem de template.

        Args:
            phone: Número do destinatário (apenas dígitos)
            template_name: Nome do template aprovado
            language: Código do idioma
            components: Parâmetros do template (header, body, buttons)
        """
        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language},
            }
        }

        if components:
            payload["template"]["components"] = components

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/messages",
                json=payload,
                headers={
                    "D360-API-KEY": self.api_key,
                    "Content-Type": "application/json",
                }
            )
            response.raise_for_status()
            return response.json()

    async def send_text_message(
        self,
        phone: str,
        text: str,
    ) -> Dict[str, Any]:
        """
        Envia mensagem de texto livre.

        ⚠️ Só funciona dentro da janela de 24h!
        """
        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "text",
            "text": {"body": text}
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/messages",
                json=payload,
                headers={
                    "D360-API-KEY": self.api_key,
                    "Content-Type": "application/json",
                }
            )
            response.raise_for_status()
            return response.json()
```

### Exemplo: ConversationWindowTracker

```python
# apps/ia/app/integrations/whatsapp_official/window_tracker.py

from datetime import datetime, timedelta
from typing import Optional
import redis.asyncio as redis

class ConversationWindowTracker:
    """
    Rastreia janela de 24h de conversação.

    A janela abre quando o CLIENTE envia mensagem e fecha 24h depois.
    Dentro da janela: texto livre permitido (grátis).
    Fora da janela: só templates (pagos).
    """

    WINDOW_DURATION = timedelta(hours=24)
    KEY_PREFIX = "whatsapp_window:"

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

    async def record_customer_message(self, phone: str) -> None:
        """Registra mensagem do cliente, abrindo/renovando janela."""
        key = f"{self.KEY_PREFIX}{phone}"
        expires_at = datetime.utcnow() + self.WINDOW_DURATION

        # Armazena timestamp de expiração
        await self.redis.setex(
            key,
            int(self.WINDOW_DURATION.total_seconds()),
            expires_at.isoformat()
        )

    async def is_window_open(self, phone: str) -> bool:
        """Verifica se janela de 24h está aberta."""
        key = f"{self.KEY_PREFIX}{phone}"
        value = await self.redis.get(key)

        if not value:
            return False

        expires_at = datetime.fromisoformat(value.decode())
        return datetime.utcnow() < expires_at

    async def get_window_expires_at(self, phone: str) -> Optional[datetime]:
        """Retorna quando a janela expira (ou None se fechada)."""
        key = f"{self.KEY_PREFIX}{phone}"
        value = await self.redis.get(key)

        if not value:
            return None

        return datetime.fromisoformat(value.decode())
```

### Exemplo: Dispatcher Adaptado

```python
# apps/ia/app/billing/dispatcher.py (modificado)

async def dispatch_single(
    agent: Dict[str, Any],
    eligible: EligiblePayment,
    decision: RulerDecision,
    messages_config: Dict[str, Any],
) -> DispatchResult:
    """Envia notificação usando template oficial."""

    whatsapp = WhatsAppOfficialClient(
        api_key=agent["whatsapp_api_key"],
        phone_number_id=agent["whatsapp_phone_id"],
    )

    # Mapear decision.phase para template
    template_map = {
        "reminder": "cobranca_lembrete_d1",
        "due_date": "cobranca_vencimento",
        "overdue": "cobranca_atraso",
    }
    template_name = template_map.get(decision.phase, "cobranca_lembrete_d1")

    # Montar parâmetros
    components = [
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": eligible.customer_name},
                {"type": "text", "text": f"{eligible.payment.value:.2f}"},
                {"type": "text", "text": str(eligible.payment.due_date)},
            ]
        }
    ]

    # Adicionar botão de pagamento se disponível
    if eligible.payment.invoice_url:
        components.append({
            "type": "button",
            "sub_type": "url",
            "index": 0,
            "parameters": [
                {"type": "text", "text": eligible.payment.invoice_url}
            ]
        })

    try:
        result = await whatsapp.send_template(
            phone=eligible.phone,
            template_name=template_name,
            components=components,
        )

        return DispatchResult(
            status="sent",
            payment_id=eligible.payment.id,
            template_used=template_name,
            message_id=result.get("messages", [{}])[0].get("id"),
        )

    except Exception as e:
        return DispatchResult(
            status="error",
            payment_id=eligible.payment.id,
            error=str(e),
        )
```

---

## Plano de Migração

### Fase 1: Preparação (Semana 1)

- [ ] Criar conta no BSP (360Dialog)
- [ ] Verificar empresa no Facebook Business Manager
- [ ] Registrar número de telefone
- [ ] Configurar webhook no BSP

### Fase 2: Templates (Semana 2)

- [ ] Redigir conteúdo dos 7 templates
- [ ] Submeter templates para aprovação
- [ ] Aguardar aprovação (pode levar até 48h cada)
- [ ] Testar templates aprovados manualmente

### Fase 3: Código (Semana 3)

- [ ] Implementar `WhatsAppOfficialClient`
- [ ] Implementar `ConversationWindowTracker`
- [ ] Adaptar `billing/dispatcher.py`
- [ ] Adaptar `jobs/notificar_manutencoes.py`
- [ ] Adaptar `message_processor.py`
- [ ] Adaptar `webhooks/mensagens.py`
- [ ] Remover typing indicator
- [ ] Testes unitários

### Fase 4: Testes (Semana 4)

- [ ] Testar billing dispatch em staging
- [ ] Testar manutenção dispatch em staging
- [ ] Testar resposta IA dentro de 24h
- [ ] Testar resposta IA fora de 24h (deve usar template ou não responder)
- [ ] Testar webhook de entrada
- [ ] Testar transferência para humano

### Fase 5: Migração (Semana 5)

- [ ] Configurar variáveis de ambiente em produção
- [ ] Deploy gradual (10% → 50% → 100%)
- [ ] Monitorar métricas (entregas, erros, custos)
- [ ] Desativar UAZAPI após estabilização

---

## Riscos e Mitigações

### Risco 1: Rejeição de Templates

**Problema:** Template rejeitado atrasa migração.

**Mitigação:**
- Seguir rigorosamente as guidelines
- Submeter templates com antecedência
- Ter templates alternativos prontos
- Começar pelos mais simples (maior chance de aprovação)

### Risco 2: Janela de 24h Limita IA

**Problema:** Cliente não responde em 24h, IA não pode continuar conversa.

**Mitigação:**
- Template de reengajamento ("Podemos ajudar?")
- Aceitar que alguns leads ficarão sem resposta
- Priorizar resolução rápida dentro da janela
- Configurar lembretes para equipe humana

### Risco 3: Mudança de Número

**Problema:** Novo número oficial, clientes não reconhecem.

**Mitigação:**
- Comunicar mudança antecipadamente
- Manter número antigo ativo temporariamente
- Atualizar todos os pontos de contato (site, materiais)

### Risco 4: Custo Maior

**Problema:** R$ 305/mês vs R$ 97/mês atual.

**Mitigação:**
- Otimizar templates (menos mensagens marketing)
- Maximizar uso da janela de 24h (grátis)
- Considerar custo vs. risco de ban (UAZAPI)
- Escala futura dilui custo fixo do BSP

### Risco 5: Template Pacing

**Problema:** Template novo limitado a ~1.000 envios iniciais.

**Mitigação:**
- Aprovar templates com antecedência
- Não lançar campanha grande no dia 1
- Testar com volume baixo primeiro
- Monitorar métricas de qualidade

---

## Guia Técnico para Desenvolvedores

Esta seção detalha as diferenças técnicas entre UAZAPI e WhatsApp Cloud API do ponto de vista de implementação.

### Conceito de "Instância" vs "Phone Number ID"

| UAZAPI (atual) | WhatsApp Oficial |
|----------------|------------------|
| **Instância** = sessão WhatsApp conectada | **Phone Number ID** = número verificado |
| Precisa escanear QR Code | Número registrado via Meta Business |
| Pode desconectar (celular desligou) | Sempre conectado (cloud) |
| Token por instância | Access Token (OAuth) |
| `base_url/instance/{name}` | `graph.facebook.com/v21.0/{phone_number_id}` |

**UAZAPI:**
```python
client = UazapiClient(
    base_url="https://api.uazapi.com",
    api_key="token-da-instancia"
)
# Se desconectar → QR Code novamente
```

**Oficial:**
```python
client = WhatsAppOfficialClient(
    phone_number_id="123456789",
    access_token="EAAxxxxxxx..."
)
# Nunca desconecta (cloud-based)
```

### Formato do Webhook — Comparativo

#### UAZAPI (como recebemos HOJE)

```json
{
  "EventType": "messages",
  "instanceName": "ana-instance",
  "token": "xxx",
  "message": {
    "chatid": "5566997194084@s.whatsapp.net",
    "text": "Olá, quero pagar minha mensalidade",
    "fromMe": false,
    "isGroup": false,
    "messageid": "3EB0ABC123",
    "senderName": "João",
    "messageTimestamp": 1710849600000,
    "wasSentByApi": false,
    "mediaType": null,
    "mediaUrl": null
  },
  "chat": {
    "wa_isGroup": false
  }
}
```

#### WhatsApp Oficial (como vamos receber)

```json
{
  "object": "whatsapp_business_account",
  "entry": [{
    "id": "WHATSAPP_BUSINESS_ACCOUNT_ID",
    "changes": [{
      "value": {
        "messaging_product": "whatsapp",
        "metadata": {
          "display_phone_number": "5566997194084",
          "phone_number_id": "123456789"
        },
        "contacts": [{
          "profile": {"name": "João"},
          "wa_id": "5566997194084"
        }],
        "messages": [{
          "from": "5566997194084",
          "id": "wamid.HBgLNTU2Njk5NzE5NDA4NBUCABEYEjNFQjBBQkMxMjM=",
          "timestamp": "1710849600",
          "type": "text",
          "text": {"body": "Olá, quero pagar minha mensalidade"}
        }]
      },
      "field": "messages"
    }]
  }]
}
```

#### Diferenças Críticas no Webhook

| Campo | UAZAPI | Oficial |
|-------|--------|---------|
| Estrutura | Plana | Aninhada (`entry[].changes[].value`) |
| Telefone | `message.chatid` com `@s.whatsapp.net` | `messages[].from` só dígitos |
| ID da mensagem | `messageid` simples | `id` em formato `wamid.xxx` (base64) |
| Nome do contato | `message.senderName` | `contacts[].profile.name` |
| Timestamp | Milissegundos (int) | Segundos (string) |
| Tipo de mídia | `message.mediaType` | `messages[].type` |
| fromMe | `message.fromMe` | Não enviado (só recebe msgs do cliente) |

### Envio de Mensagens — Comparativo

#### UAZAPI (atual)

```python
# Texto simples - SEMPRE funciona
await client.send_text_message(
    phone="5566997194084",
    text="Olá! Como posso ajudar?"
)

# Com typing indicator
await client.send_typing(phone, duration=2000)
await client.send_text_message(phone, text)

# Mensagem longa - chunking automático
await client.send_ai_response(
    phone="5566997194084",
    text="Mensagem muito longa...",  # 4000+ chars
    agent_name="Ana"
)
# → Divide em chunks de 4000 chars automaticamente
```

#### WhatsApp Oficial

```python
# Texto simples - SÓ FUNCIONA DENTRO DE 24H
if await window_tracker.is_window_open(phone):
    await client.send_text_message(
        phone="5566997194084",
        text="Olá! Como posso ajudar?"
    )
else:
    raise Exception("Janela fechada - use template")

# NÃO existe typing indicator na API oficial!

# Mensagem longa - chunking MANUAL
chunks = split_text(text, max_size=4096)
for chunk in chunks:
    await client.send_text_message(phone, chunk)
```

#### Envio de Template (fora de 24h)

```python
# Enviar template - SEMPRE funciona (mas pago)
await client.send_template(
    phone="5566997194084",
    template_name="cobranca_lembrete",
    language="pt_BR",
    components=[
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": "João"},
                {"type": "text", "text": "150,00"},
                {"type": "text", "text": "25/03/2026"}
            ]
        },
        {
            "type": "button",
            "sub_type": "url",
            "index": 0,
            "parameters": [
                {"type": "text", "text": "https://pay.asaas.com/xxx"}
            ]
        }
    ]
)
```

### Endpoints da API — Comparativo

#### UAZAPI

| Endpoint | Método | Uso |
|----------|--------|-----|
| `/message/sendText` | POST | Enviar texto |
| `/message/sendMedia` | POST | Enviar mídia |
| `/message/sendDocument` | POST | Enviar documento |
| `/message/sendAudio` | POST | Enviar áudio |
| `/message/sendSticker` | POST | Enviar sticker |
| `/message/sendList` | POST | Enviar lista |
| `/message/sendButtons` | POST | Enviar botões |
| `/message/markread` | POST | Marcar como lido |
| `/instance/status` | GET | Status da conexão |
| `/presence/update` | POST | Typing indicator |
| `/chat/check` | GET | Verificar se número existe |

#### WhatsApp Oficial (Cloud API)

| Endpoint | Método | Uso |
|----------|--------|-----|
| `/{phone_id}/messages` | POST | Enviar TUDO (text, template, media, interactive) |
| `/{phone_id}/media` | POST | Upload de mídia |
| `/media/{media_id}` | GET | Download de mídia |
| `/{phone_id}` | GET | Info do número |
| `/{waba_id}/message_templates` | GET/POST | Gerenciar templates |

**Nota:** API oficial tem MENOS endpoints — tudo consolidado em `/messages`.

### Autenticação

#### UAZAPI

```python
headers = {
    "apikey": "token-da-instancia",
    "Content-Type": "application/json"
}
```

#### WhatsApp Oficial (direto)

```python
headers = {
    "Authorization": "Bearer EAAxxxxxxx...",
    "Content-Type": "application/json"
}
```

#### WhatsApp Oficial (via 360Dialog)

```python
headers = {
    "D360-API-KEY": "seu-api-key-360dialog",
    "Content-Type": "application/json"
}
```

**Tipos de Token Oficial:**
- **Temporary Token**: expira em 24h (desenvolvimento)
- **System User Token**: permanente (produção)
- **Via BSP**: cada BSP tem seu próprio header

### Webhook Verification

#### UAZAPI

Não tem verificação. Configura a URL no painel e pronto.

#### WhatsApp Oficial

Precisa responder ao challenge da Meta:

```python
@router.get("/webhook/whatsapp")
async def verify_webhook(request: Request):
    """Endpoint de verificação do webhook Meta."""
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    # Token configurado no painel Meta/BSP
    VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        # Retornar o challenge como texto puro
        return Response(content=challenge, media_type="text/plain")

    raise HTTPException(status_code=403, detail="Verification failed")
```

### Rate Limits

| API | Limite | Observação |
|-----|--------|------------|
| UAZAPI | Não documentado | Depende do servidor |
| Oficial | **80 msgs/segundo** | Por número |
| Oficial (tier inicial) | **1.000 msgs/dia** | Aumenta com qualidade |
| Oficial (tier máximo) | **Ilimitado** | Após verificação completa |

### Status de Entrega — Comparativo

#### UAZAPI

```json
{
  "event": "messages.update",
  "data": {
    "key": {"id": "3EB0ABC123"},
    "update": {"status": 3}
  }
}
```
Status numérico: `1=pending, 2=sent, 3=delivered, 4=read`

#### WhatsApp Oficial

```json
{
  "entry": [{
    "changes": [{
      "value": {
        "statuses": [{
          "id": "wamid.xxx",
          "status": "delivered",
          "timestamp": "1710849700",
          "recipient_id": "5566997194084"
        }]
      }
    }]
  }]
}
```
Status string: `"sent"`, `"delivered"`, `"read"`, `"failed"`

### Mensagens Interativas — Comparativo

#### UAZAPI — Botões

```python
await client.send_buttons(
    phone="5566997194084",
    title="Escolha uma opção",
    buttons=[
        {"buttonId": "1", "buttonText": {"displayText": "Opção 1"}},
        {"buttonId": "2", "buttonText": {"displayText": "Opção 2"}},
    ]
)
```

#### WhatsApp Oficial — Botões

```python
await client.send_message({
    "messaging_product": "whatsapp",
    "to": "5566997194084",
    "type": "interactive",
    "interactive": {
        "type": "button",
        "body": {"text": "Escolha uma opção"},
        "action": {
            "buttons": [
                {"type": "reply", "reply": {"id": "1", "title": "Opção 1"}},
                {"type": "reply", "reply": {"id": "2", "title": "Opção 2"}},
            ]
        }
    }
})
```

#### UAZAPI — Lista

```python
await client.send_list(
    phone="5566997194084",
    title="Menu",
    buttonText="Ver opções",
    sections=[{
        "title": "Serviços",
        "rows": [
            {"title": "Pagar", "rowId": "pay"},
            {"title": "Suporte", "rowId": "support"},
        ]
    }]
)
```

#### WhatsApp Oficial — Lista

```python
await client.send_message({
    "messaging_product": "whatsapp",
    "to": "5566997194084",
    "type": "interactive",
    "interactive": {
        "type": "list",
        "body": {"text": "Menu"},
        "action": {
            "button": "Ver opções",
            "sections": [{
                "title": "Serviços",
                "rows": [
                    {"id": "pay", "title": "Pagar"},
                    {"id": "support", "title": "Suporte"},
                ]
            }]
        }
    }
})
```

### Adaptação do Webhook Handler

#### Código Atual (UAZAPI)

```python
# apps/ia/app/domain/messaging/handlers/incoming_message_handler.py

def extract_message_data(webhook_data: Dict) -> Optional[ExtractedMessage]:
    """Extrai dados do webhook UAZAPI."""
    if webhook_data.get("EventType") == "messages":
        msg = webhook_data.get("message", {})
        return ExtractedMessage(
            phone=msg.get("chatid", "").replace("@s.whatsapp.net", ""),
            text=msg.get("text", ""),
            from_me=msg.get("fromMe", False),
            message_id=msg.get("messageid", ""),
            push_name=msg.get("senderName", ""),
            timestamp=msg.get("messageTimestamp", ""),
            is_group=msg.get("isGroup", False),
            media_type=msg.get("mediaType"),
            media_url=msg.get("mediaUrl"),
        )
    return None
```

#### Código Novo (Oficial)

```python
# apps/ia/app/integrations/whatsapp_official/webhook_parser.py

def extract_message_data(webhook_data: Dict) -> Optional[ExtractedMessage]:
    """Extrai dados do webhook WhatsApp Cloud API."""
    if webhook_data.get("object") != "whatsapp_business_account":
        return None

    try:
        entry = webhook_data.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})

        # Ignorar se não for mensagem
        if changes.get("field") != "messages":
            return None

        messages = value.get("messages", [])
        if not messages:
            return None

        msg = messages[0]
        contacts = value.get("contacts", [{}])[0]
        metadata = value.get("metadata", {})

        # Extrair texto baseado no tipo
        msg_type = msg.get("type", "text")
        if msg_type == "text":
            text = msg.get("text", {}).get("body", "")
        elif msg_type == "image":
            text = msg.get("image", {}).get("caption", "[IMAGEM]")
        elif msg_type == "audio":
            text = "[AUDIO]"
        elif msg_type == "video":
            text = msg.get("video", {}).get("caption", "[VIDEO]")
        elif msg_type == "document":
            text = msg.get("document", {}).get("caption", "[DOCUMENTO]")
        elif msg_type == "sticker":
            text = "[STICKER]"
        elif msg_type == "interactive":
            # Resposta de botão ou lista
            interactive = msg.get("interactive", {})
            if interactive.get("type") == "button_reply":
                text = interactive.get("button_reply", {}).get("title", "")
            elif interactive.get("type") == "list_reply":
                text = interactive.get("list_reply", {}).get("title", "")
            else:
                text = "[INTERATIVO]"
        else:
            text = f"[{msg_type.upper()}]"

        return ExtractedMessage(
            phone=msg.get("from", ""),
            remotejid=f"{msg.get('from', '')}@s.whatsapp.net",
            text=text,
            from_me=False,  # API oficial só envia msgs recebidas
            message_id=msg.get("id", ""),
            push_name=contacts.get("profile", {}).get("name", ""),
            timestamp=msg.get("timestamp", ""),
            is_group=False,  # Cloud API não suporta grupos
            media_type=msg_type if msg_type != "text" else None,
            media_url=None,  # Precisa fazer GET separado para mídia
            instance_id=metadata.get("phone_number_id", ""),
        )

    except Exception as e:
        logger.error(f"Erro ao extrair dados do webhook oficial: {e}")
        return None
```

### O que PERDEMOS na Migração

| Feature | UAZAPI | Oficial | Impacto |
|---------|--------|---------|---------|
| Typing indicator | ✅ | ❌ | UX menor, cliente não vê "digitando..." |
| Texto livre sempre | ✅ | ❌ (só 24h) | Billing/manutenção precisa de template |
| QR Code simples | ✅ | ❌ | Precisa verificação Meta Business |
| Webhook simples | ✅ | ⚠️ | Payload mais complexo, verificação |
| Custo fixo | ✅ R$97 | ❌ ~R$305 | 3x mais caro |
| Grupos | ✅ | ❌ | Cloud API não suporta grupos |

### O que GANHAMOS na Migração

| Feature | UAZAPI | Oficial | Benefício |
|---------|--------|---------|-----------|
| Estabilidade | ⚠️ Pode cair | ✅ Cloud | Nunca desconecta |
| Conformidade | ❌ Zona cinza | ✅ 100% legal | Sem risco jurídico |
| Suporte Meta | ❌ | ✅ | Documentação oficial |
| Templates aprovados | ❌ | ✅ | Qualidade garantida |
| Métricas oficiais | ❌ | ✅ | Analytics do WhatsApp |
| Escala | ⚠️ Limitado | ✅ 80msg/s | Enterprise-ready |
| Risco de ban | ⚠️ Alto | ✅ Zero | Operação segura |

### Resumo de Mudanças para Desenvolvedores

| Aspecto | O que muda |
|---------|------------|
| **Cliente HTTP** | Trocar `UazapiClient` por `WhatsAppOfficialClient` |
| **Webhook parsing** | Payload aninhado `entry[].changes[].value` |
| **Envio de texto** | Verificar janela 24h antes |
| **Billing/Manutenção** | Obrigatório usar templates |
| **Typing** | Remover completamente (não existe) |
| **Autenticação** | Bearer token ou header do BSP |
| **Verificação webhook** | Responder `hub.challenge` |
| **Rate limit** | Implementar throttling (80/s) |
| **Chunking** | Implementar manualmente (máx 4096 chars) |
| **Grupos** | Não suportado — remover lógica |

---

## Referências

- [Meta - WhatsApp Business Platform](https://business.whatsapp.com/products/platform-pricing)
- [Meta Developers - Templates Overview](https://developers.facebook.com/docs/whatsapp/message-templates/)
- [Twilio - Template Approvals](https://www.twilio.com/docs/whatsapp/tutorial/message-template-approvals-statuses)
- [360Dialog - Documentation](https://docs.360dialog.com/)
- [GuruSup - WhatsApp Templates Guide 2026](https://gurusup.com/blog/whatsapp-api-message-templates)

---

## Changelog

| Data | Autor | Mudança |
|------|-------|---------|
| 2026-03-19 | Claude | Documento inicial criado |
| 2026-03-19 | Claude | Adicionado Guia Técnico para Desenvolvedores (webhooks, endpoints, código) |
