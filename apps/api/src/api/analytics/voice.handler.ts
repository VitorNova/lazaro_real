// ============================================================================
// ATHENA - VOICE HANDLERS (STT & TTS)
// ============================================================================

import { FastifyRequest, FastifyReply } from 'fastify';
import OpenAI from 'openai';
import { createWhisperClient } from '../../services/ai/whisper';

// ============================================================================
// TYPES
// ============================================================================

interface TranscribeRequest {
  Body: {
    audio: string; // Base64 encoded audio
    mimeType?: string;
    language?: string;
  };
}

interface SpeakRequest {
  Body: {
    text: string;
    voice?: 'alloy' | 'echo' | 'fable' | 'onyx' | 'nova' | 'shimmer';
    speed?: number;
    api_key: string;
  };
}

// ============================================================================
// TRANSCRIBE HANDLER (STT - Speech to Text)
// ============================================================================

/**
 * POST /api/analytics/transcribe
 *
 * Recebe áudio em base64 e retorna texto usando Whisper (OpenAI)
 *
 * Body:
 * - audio: string (obrigatório) - Áudio em base64
 * - mimeType?: string - Tipo MIME do áudio (default: audio/webm)
 * - language?: string - Idioma do áudio (default: pt)
 * - api_key: string (obrigatório) - API key do OpenAI
 *
 * Response:
 * - success: boolean
 * - text: string - Texto transcrito
 * - duration?: number - Duração do áudio em segundos
 */
export async function transcribeHandler(
  request: FastifyRequest<TranscribeRequest & { Body: { api_key: string } }>,
  reply: FastifyReply
) {
  try {
    const { audio, mimeType = 'audio/webm', language = 'pt', api_key } = request.body;

    if (!audio) {
      return reply.status(400).send({
        success: false,
        error: 'Áudio não fornecido',
        message: 'Envie o áudio em base64 no campo "audio"',
      });
    }

    if (!api_key) {
      return reply.status(400).send({
        success: false,
        error: 'API key não fornecida',
        message: 'Envie sua API key do OpenAI no campo "api_key"',
      });
    }

    console.log(`[Athena Voice] Transcrevendo áudio (${mimeType}, ${language})`);

    // Criar cliente Whisper com a API key do usuário
    const whisper = createWhisperClient(api_key, 'whisper-1', language);

    // Transcrever
    const result = await whisper.transcribe({
      audioBase64: audio,
      mimeType,
      language,
    });

    console.log(`[Athena Voice] Transcrição concluída: "${result.text.substring(0, 50)}..."`);

    return reply.send({
      success: true,
      text: result.text,
      language: result.language,
      duration: result.duration,
    });
  } catch (error: any) {
    console.error('[Athena Voice] Erro na transcrição:', error);

    // Verificar se é erro de API key
    if (error?.status === 401 || error?.message?.includes('Incorrect API key')) {
      return reply.status(401).send({
        success: false,
        error: 'API key inválida',
        message: 'Verifique sua API key do OpenAI',
      });
    }

    return reply.status(500).send({
      success: false,
      error: 'Erro na transcrição',
      message: error?.message || 'Ocorreu um erro ao transcrever o áudio',
    });
  }
}

// ============================================================================
// SPEAK HANDLER (TTS - Text to Speech)
// ============================================================================

/**
 * POST /api/analytics/speak
 *
 * Recebe texto e retorna áudio sintetizado usando OpenAI TTS
 *
 * Body:
 * - text: string (obrigatório) - Texto para sintetizar
 * - voice?: string - Voz a usar (default: nova)
 * - speed?: number - Velocidade (0.25 a 4.0, default: 1.0)
 * - api_key: string (obrigatório) - API key do OpenAI
 *
 * Response:
 * - Áudio em formato MP3 (binary)
 */
export async function speakHandler(
  request: FastifyRequest<SpeakRequest>,
  reply: FastifyReply
) {
  try {
    const { text, voice = 'nova', speed = 1.0, api_key } = request.body;

    if (!text) {
      return reply.status(400).send({
        success: false,
        error: 'Texto não fornecido',
        message: 'Envie o texto no campo "text"',
      });
    }

    if (!api_key) {
      return reply.status(400).send({
        success: false,
        error: 'API key não fornecida',
        message: 'Envie sua API key do OpenAI no campo "api_key"',
      });
    }

    // Limitar texto para evitar custos excessivos (4096 caracteres max)
    const maxChars = 4096;
    const truncatedText = text.length > maxChars ? text.substring(0, maxChars) : text;

    console.log(`[Athena Voice] Sintetizando voz (${voice}, speed: ${speed}): "${truncatedText.substring(0, 50)}..."`);

    // Criar cliente OpenAI
    const openai = new OpenAI({ apiKey: api_key });

    // Gerar áudio
    const audioResponse = await openai.audio.speech.create({
      model: 'tts-1',
      voice: voice,
      input: truncatedText,
      speed: Math.min(Math.max(speed, 0.25), 4.0), // Limitar entre 0.25 e 4.0
      response_format: 'mp3',
    });

    // Converter para buffer
    const buffer = Buffer.from(await audioResponse.arrayBuffer());

    console.log(`[Athena Voice] Áudio gerado: ${buffer.length} bytes`);

    // Retornar áudio como base64 para facilitar uso no frontend
    return reply.send({
      success: true,
      audio: buffer.toString('base64'),
      format: 'mp3',
      voice,
      chars: truncatedText.length,
    });
  } catch (error: any) {
    console.error('[Athena Voice] Erro na síntese:', error);

    // Verificar se é erro de API key
    if (error?.status === 401 || error?.message?.includes('Incorrect API key')) {
      return reply.status(401).send({
        success: false,
        error: 'API key inválida',
        message: 'Verifique sua API key do OpenAI',
      });
    }

    return reply.status(500).send({
      success: false,
      error: 'Erro na síntese de voz',
      message: error?.message || 'Ocorreu um erro ao gerar o áudio',
    });
  }
}

// ============================================================================
// VOICES INFO HANDLER
// ============================================================================

/**
 * GET /api/analytics/voices
 *
 * Retorna informações sobre as vozes disponíveis
 */
export async function voicesHandler(
  request: FastifyRequest,
  reply: FastifyReply
) {
  const voices = [
    { id: 'nova', name: 'Nova', description: 'Voz feminina natural (recomendada para PT-BR)', gender: 'female', default: true },
    { id: 'alloy', name: 'Alloy', description: 'Voz neutra e versátil', gender: 'neutral' },
    { id: 'echo', name: 'Echo', description: 'Voz masculina profunda', gender: 'male' },
    { id: 'fable', name: 'Fable', description: 'Voz masculina expressiva', gender: 'male' },
    { id: 'onyx', name: 'Onyx', description: 'Voz masculina grave', gender: 'male' },
    { id: 'shimmer', name: 'Shimmer', description: 'Voz feminina clara', gender: 'female' },
  ];

  return reply.send({
    success: true,
    provider: 'OpenAI TTS',
    model: 'tts-1',
    voices,
    limits: {
      maxChars: 4096,
      minSpeed: 0.25,
      maxSpeed: 4.0,
      defaultSpeed: 1.0,
    },
  });
}
