# Implementação de Suporte a Áudio - Agente IA

## Resumo Executivo

Este documento detalha como implementar suporte a áudio no agente Python (`agente-ia`), baseado na pesquisa das APIs UAZAPI e Gemini, além do código existente no `agnes-agent` (Node.js).

---

## 1. UAZAPI - Recebimento e Download de Mídia

### 1.1 Formato do Webhook de Áudio

Quando um áudio é recebido, o webhook UAZAPI envia:

```json
{
  "EventType": "messages",
  "instanceName": "Agent_xxx",
  "message": {
    "chatid": "5511999999999@s.whatsapp.net",
    "fromMe": false,
    "mediaType": "audio",        // ou "ptt" para mensagem de voz
    "mimetype": "audio/ogg; codecs=opus",
    "messageid": "7EB0F01D7244B421048F0706368376E0",
    "text": ""                   // áudios não têm texto
  }
}
```

### 1.2 Endpoint para Download de Mídia

**Endpoint:** `POST /message/download`

**Request:**
```json
{
  "id": "7EB0F01D7244B421048F0706368376E0",
  "return_base64": true,
  "generate_mp3": true,
  "transcribe": false
}
```

**Response:**
```json
{
  "fileURL": "https://api.uazapi.com/files/arquivo.mp3",
  "mimetype": "audio/mpeg",
  "base64Data": "UklGRkj...",
  "transcription": null
}
```

### 1.3 Parâmetros Importantes

| Parâmetro | Tipo | Default | Descrição |
|-----------|------|---------|-----------|
| `id` | string | required | ID da mensagem |
| `return_base64` | boolean | false | Retorna arquivo em base64 |
| `generate_mp3` | boolean | true | Converte áudio para MP3 |
| `return_link` | boolean | true | Retorna URL pública |
| `transcribe` | boolean | false | Transcreve via Whisper (requer API key OpenAI) |
| `openai_apikey` | string | null | API key OpenAI para transcrição |

### 1.4 Transcrição Integrada da UAZAPI

A UAZAPI oferece transcrição via Whisper integrada:

```json
{
  "id": "7EB0F01D7244B421048F0706368376E0",
  "transcribe": true,
  "openai_apikey": "sk-..."
}
```

**Vantagem:** Não precisa baixar o áudio, a transcrição é feita no servidor da UAZAPI.

---

## 2. Gemini 2.0 - Suporte Nativo a Áudio

### 2.1 Capacidades

O Gemini 2.0 Flash suporta áudio **nativamente**, podendo:

- Transcrever fala para texto
- Traduzir áudio
- Detectar diferentes speakers (diarização)
- Detectar emoções na fala
- Analisar segmentos com timestamps

### 2.2 Formatos Suportados

- WAV (`audio/wav`)
- MP3 (`audio/mp3`)
- AIFF (`audio/aiff`)
- AAC (`audio/aac`)
- OGG Vorbis (`audio/ogg`)
- FLAC (`audio/flac`)

### 2.3 Especificações Técnicas

- **1 segundo de áudio = 32 tokens**
- **1 minuto de áudio = 1.920 tokens**
- **Máximo: 9.5 horas** de áudio por prompt
- Downsampling automático para 16 Kbps
- Canais múltiplos são combinados em mono

### 2.4 Exemplo de Código Python

```python
from google import genai

client = genai.Client()

# Opção 1: Upload de arquivo
myfile = client.files.upload(file="path/to/audio.mp3")
response = client.models.generate_content(
    model="gemini-2.0-flash",
    contents=["Transcreva este áudio em português", myfile]
)

# Opção 2: Inline base64 (para arquivos pequenos < 20MB)
from google.genai import types

with open('audio.mp3', 'rb') as f:
    audio_bytes = f.read()

response = client.models.generate_content(
    model='gemini-2.0-flash',
    contents=[
        'Transcreva este áudio em português',
        types.Part.from_bytes(
            data=audio_bytes,
            mime_type='audio/mp3',
        )
    ]
)
```

### 2.5 Biblioteca Python Atual

O `agente-ia` usa a biblioteca **deprecated** `google.generativeai`. Para áudio, é recomendado migrar para `google.genai`:

```bash
pip install google-genai
```

---

## 3. Código Existente no agnes-agent (Node.js)

O `agnes-agent` já tem implementação completa de áudio:

### 3.1 Arquivos Relevantes

| Arquivo | Função |
|---------|--------|
| `services/ai/whisper.ts` | Cliente OpenAI Whisper para transcrição |
| `services/ai/media-analyzer.ts` | Serviço multi-provider (Whisper, Gemini) |
| `utils/whatsapp-media.ts` | Decriptação de mídia WhatsApp |
| `core/message-processor/processor.ts` | Processamento de mensagens com áudio |

### 3.2 Fluxo no agnes-agent

```
1. Webhook recebe mensagem com mediaType=audio/ptt
2. Verifica se downloadMedia está habilitado
3. Baixa mídia via URL ou usa base64
4. Se transcribeAudio=true, transcreve via Whisper ou Gemini
5. Texto transcrito é enviado para o LLM junto com contexto
```

### 3.3 Configuração

```typescript
// types.ts
export const DEFAULT_PROCESSOR_CONFIG = {
  transcribeAudio: true,
  downloadMedia: true,
  // ...
};
```

---

## 4. Decisão: Whisper vs Gemini Nativo

### Opção A: UAZAPI + Whisper (Recomendado para agente-ia)

**Prós:**
- Zero código adicional de download
- Transcrição feita no servidor UAZAPI
- Uma única chamada API
- Já funciona com o fluxo atual

**Contras:**
- Requer API key OpenAI configurada na UAZAPI
- Custo adicional do Whisper

**Implementação:**
```python
async def download_and_transcribe(message_id: str, uazapi_token: str):
    response = await uazapi.post("/message/download", {
        "id": message_id,
        "transcribe": True,
        "openai_apikey": os.getenv("OPENAI_API_KEY")
    })
    return response["transcription"]
```

### Opção B: Gemini Nativo

**Prós:**
- Não precisa de API key OpenAI
- Mais capacidades (emoção, diarização)
- Já usa Gemini, sem custo adicional

**Contras:**
- Precisa baixar o áudio primeiro
- Mais código para implementar
- Biblioteca atual é deprecated

**Implementação:**
```python
async def transcribe_with_gemini(audio_base64: str, mime_type: str):
    model = genai.GenerativeModel('gemini-2.0-flash')
    result = model.generate_content([
        {
            "inline_data": {
                "mime_type": mime_type,
                "data": audio_base64
            }
        },
        "Transcreva este áudio em português."
    ])
    return result.text
```

### Recomendação Final

**Para o `agente-ia` atual:** Usar **UAZAPI + Whisper** (Opção A)

Motivos:
1. Menor complexidade de implementação
2. Não precisa modificar a biblioteca Gemini
3. Transcrição de alta qualidade
4. Uma única chamada de API

---

## 5. Implementação Proposta para agente-ia

### 5.1 Modificar `app/webhooks/whatsapp.py`

```python
# Detectar mensagem de áudio
def is_audio_message(msg: dict) -> bool:
    media_type = msg.get("mediaType", "")
    return media_type in ["audio", "ptt", "myaudio"]

# No _extract_message_data, adicionar:
if is_audio_message(msg):
    return ExtractedMessage(
        phone=phone,
        remotejid=remotejid,
        text="[AUDIO]",  # Placeholder
        is_group=is_group,
        from_me=from_me,
        message_id=message_id,
        media_type="audio",
        # ...
    )
```

### 5.2 Criar `app/services/audio.py`

```python
from app.services.uazapi import UazapiService

async def transcribe_audio_message(
    message_id: str,
    uazapi: UazapiService,
    openai_api_key: str = None
) -> str:
    """
    Transcreve uma mensagem de áudio usando UAZAPI + Whisper.
    """
    result = await uazapi.download_media(
        message_id=message_id,
        transcribe=True,
        openai_apikey=openai_api_key
    )

    if result.get("transcription"):
        return result["transcription"]

    return "[Áudio não pôde ser transcrito]"
```

### 5.3 Atualizar `app/services/uazapi.py`

```python
async def download_media(
    self,
    message_id: str,
    return_base64: bool = False,
    generate_mp3: bool = True,
    transcribe: bool = False,
    openai_apikey: str = None
) -> dict:
    """
    Baixa mídia de uma mensagem.
    """
    payload = {
        "id": message_id,
        "return_base64": return_base64,
        "generate_mp3": generate_mp3,
        "transcribe": transcribe,
    }

    if openai_apikey:
        payload["openai_apikey"] = openai_apikey

    response = await self._post("/message/download", payload)
    return response
```

### 5.4 Fluxo Completo

```
1. Webhook recebe mensagem
2. Detecta mediaType == "audio" ou "ptt"
3. Chama UAZAPI /message/download com transcribe=true
4. Recebe transcrição no campo "transcription"
5. Substitui texto da mensagem pela transcrição
6. Processa normalmente com Gemini
```

---

## 6. Checklist de Implementação

- [ ] Adicionar detecção de áudio no `_extract_message_data`
- [ ] Criar método `download_media` no `UazapiService`
- [ ] Criar serviço `audio.py` para transcrição
- [ ] Modificar `handle_message` para processar áudios
- [ ] Configurar `OPENAI_API_KEY` no ambiente
- [ ] Testar com mensagens de voz reais
- [ ] (Futuro) Migrar para `google.genai` para suporte nativo

---

## Referências

- [UAZAPI Docs - Message Download](https://docs.uazapi.com/endpoint/post/message~download)
- [Gemini API - Audio Understanding](https://ai.google.dev/gemini-api/docs/audio)
- [OpenAI Whisper API](https://platform.openai.com/docs/guides/speech-to-text)
- agnes-agent: `src/services/ai/media-analyzer.ts`
