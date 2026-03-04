# Agente IA - Phant

Backend Python/FastAPI para automacao de WhatsApp com IA usando Google Gemini 2.0 Flash.

## Stack Tecnologica

| Componente | Tecnologia |
|------------|------------|
| Linguagem | Python 3.11+ |
| Framework | FastAPI |
| IA | Gemini 2.0 Flash |
| WhatsApp | UAZAPI |
| Banco | Supabase (PostgreSQL) |
| Cache | Redis |
| CRM | Leadbox |

## Arquitetura

```
USUARIO (WhatsApp)
       |
       v
    UAZAPI -------> FASTAPI
                       |
           +-----------+-----------+
           v           v           v
        GEMINI     SUPABASE     REDIS
           |
           v
    FUNCTION CALLING
           |
     +-----+-----+
     v           v
  CALENDAR   LEADBOX
```

## Estrutura de Pastas

```
agente-ia/
├── app/
│   ├── main.py              # Entry point FastAPI
│   ├── config.py            # Pydantic Settings
│   ├── services/
│   │   ├── gemini.py        # Cliente Gemini + function calling
│   │   ├── supabase.py      # Operacoes no banco
│   │   ├── redis.py         # Buffer + cache
│   │   ├── uazapi.py        # WhatsApp API
│   │   ├── leadbox.py       # Integracao Leadbox
│   │   └── calendar.py      # Google Calendar
│   ├── tools/
│   │   └── functions.py     # 5 function declarations
│   └── webhooks/
│       └── whatsapp.py      # Webhook handler
├── .env                     # Configuracoes (criar a partir do .env.example)
├── .env.example             # Template de configuracao
├── requirements.txt         # Dependencias Python
├── ecosystem.config.js      # Configuracao PM2
└── install.sh              # Script de instalacao
```

## Instalacao

```bash
# Clone ou navegue ate o diretorio
cd /var/www/phant/agente-ia

# Execute o script de instalacao
chmod +x install.sh
./install.sh

# Configure as variaveis de ambiente
nano .env
```

## Execucao

### Desenvolvimento

```bash
# Ative o ambiente virtual
source venv/bin/activate

# Execute com hot reload
uvicorn app.main:app --reload --host 0.0.0.0 --port 3003
```

### Producao (PM2)

```bash
# Inicie com PM2
pm2 start ecosystem.config.js

# Salve configuracao
pm2 save

# Configure auto-start no boot
pm2 startup
```

## Endpoints

| Metodo | Endpoint | Descricao |
|--------|----------|-----------|
| GET | `/` | Informacoes da API |
| GET | `/health` | Health check basico |
| GET | `/health/detailed` | Status detalhado dos servicos |
| POST | `/api/webhook/whatsapp` | Webhook do WhatsApp (UAZAPI) |
| GET | `/api/webhook/whatsapp` | Verificacao do webhook |

## Comandos WhatsApp

| Comando | Acao |
|---------|------|
| `/p` | Pausa o bot (transfere para humano) |
| `/a` | Ativa o bot |
| `/r` | Reseta a conversa |

## Tools (Function Calling)

O agente possui 5 tools disponiveis:

1. **consulta_agenda** - Consulta horarios disponiveis
2. **agendar** - Cria novo agendamento com Google Meet
3. **cancelar_agendamento** - Cancela agendamento existente
4. **reagendar** - Altera data/hora de agendamento
5. **transferir_departamento** - Transfere para atendente humano

## Fluxo de Processamento

1. Webhook recebe mensagem do UAZAPI
2. Valida: nao e grupo, nao e mensagem propria
3. Verifica comandos de controle (/p, /a, /r)
4. Verifica se bot esta pausado
5. Adiciona mensagem ao buffer Redis
6. Aguarda 14 segundos (agrupa mensagens)
7. Busca historico de conversa do Supabase
8. Envia para Gemini com tools disponiveis
9. Se function_call: executa e retorna resultado
10. Envia resposta via UAZAPI
11. Salva historico atualizado

## Logs

```bash
# Logs do PM2
pm2 logs agente-ia --lines 100

# Logs em tempo real
pm2 logs agente-ia --raw
```

## Variaveis de Ambiente

Ver `.env.example` para lista completa. Principais:

| Variavel | Descricao |
|----------|-----------|
| `GOOGLE_API_KEY` | Chave do Google AI Studio |
| `SUPABASE_URL` | URL do projeto Supabase |
| `SUPABASE_SERVICE_KEY` | Service role key |
| `UAZAPI_BASE_URL` | URL da API UAZAPI |
| `UAZAPI_API_KEY` | Token da UAZAPI |
| `REDIS_URL` | URL de conexao Redis |

## Monitoramento

```bash
# Status dos processos
pm2 list

# Metricas em tempo real
pm2 monit

# Health check
curl http://localhost:3003/health/detailed
```

## Troubleshooting

### Erro de conexao Redis
```bash
# Verifique se Redis esta rodando
redis-cli ping
```

### Erro de autenticacao Gemini
```bash
# Verifique a chave no Google AI Studio
# https://aistudio.google.com/apikey
```

### Webhook nao recebe mensagens
```bash
# Verifique configuracao no painel UAZAPI
# O webhook deve apontar para: https://seu-dominio/api/webhook/whatsapp
```

## Autor

Desenvolvido por Claude Code para o projeto Phant.

## Licenca

Proprietario - Todos os direitos reservados.
