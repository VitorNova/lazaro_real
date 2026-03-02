/**
 * Media Analyzer - Serviço de análise de mídia multi-provider
 * Suporta: OpenAI (Whisper + GPT-4 Vision), Gemini (Flash 2.0)
 */

import OpenAI from 'openai';
import { GoogleGenerativeAI } from '@google/generative-ai';
import { AIProvider, Agent } from '../supabase/types';

// ============================================================================
// LOGGER
// ============================================================================

interface Logger {
  debug(message: string, data?: unknown): void;
  info(message: string, data?: unknown): void;
  warn(message: string, data?: unknown): void;
  error(message: string, data?: unknown): void;
}

function createLogger(name: string): Logger {
  return {
    debug: (msg, data) => console.debug(`[${name}] ${msg}`, data ?? ''),
    info: (msg, data) => console.info(`[${name}] ${msg}`, data ?? ''),
    warn: (msg, data) => console.warn(`[${name}] ${msg}`, data ?? ''),
    error: (msg, data) => console.error(`[${name}] ${msg}`, data ?? ''),
  };
}

const logger = createLogger('MediaAnalyzer');

// ============================================================================
// TYPES
// ============================================================================

export interface MediaAnalysisResult {
  success: boolean;
  text: string;
  type: 'transcription' | 'vision' | 'error';
  provider: AIProvider;
  duration?: number;
  confidence?: number;
}

export interface MediaData {
  base64: string;
  mimeType: string;
  messageId?: string;
}

// ============================================================================
// AUDIO TRANSCRIPTION
// ============================================================================

/**
 * Transcreve áudio usando o provider configurado do agent
 */
export async function transcribeAudio(
  agent: Agent,
  mediaData: MediaData
): Promise<MediaAnalysisResult> {
  const provider = agent.ai_provider || 'gemini';

  logger.info('Transcribing audio', {
    provider,
    mimeType: mediaData.mimeType,
    hasBase64: !!mediaData.base64
  });

  try {
    switch (provider) {
      case 'openai':
        return await transcribeWithOpenAI(agent, mediaData);
      case 'gemini':
        return await transcribeWithGemini(agent, mediaData);
      case 'claude':
        // Claude não tem transcrição nativa, fallback para descrição
        return await describeAudioWithClaude(agent, mediaData);
      default:
        return await transcribeWithGemini(agent, mediaData);
    }
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : String(error);
    logger.error('Transcription failed', { provider, error: errorMessage });

    return {
      success: false,
      text: '[Não foi possível transcrever o áudio]',
      type: 'error',
      provider,
    };
  }
}

/**
 * Transcreve áudio usando OpenAI Whisper
 */
async function transcribeWithOpenAI(
  agent: Agent,
  mediaData: MediaData
): Promise<MediaAnalysisResult> {
  const apiKey = (agent as any).openai_api_key;

  if (!apiKey) {
    throw new Error('OpenAI API key not configured for this agent');
  }

  const client = new OpenAI({ apiKey });

  // Converter base64 para Buffer e criar arquivo usando toFile do SDK
  const base64Clean = cleanBase64Data(mediaData.base64);
  const buffer = Buffer.from(base64Clean, 'base64');
  const extension = getAudioExtension(mediaData.mimeType);
  const filename = `audio.${extension}`;

  logger.debug('Calling OpenAI Whisper', { extension, mimeType: mediaData.mimeType, bufferSize: buffer.length });

  // Usar toFile do SDK do OpenAI para criar um arquivo compatível com Node.js
  const file = await OpenAI.toFile(buffer, filename, { type: mediaData.mimeType });

  const response = await client.audio.transcriptions.create({
    file,
    model: 'whisper-1',
    language: 'pt',
    response_format: 'verbose_json',
  });

  logger.info('OpenAI transcription completed', {
    textLength: response.text.length,
    duration: response.duration
  });

  return {
    success: true,
    text: response.text,
    type: 'transcription',
    provider: 'openai',
    duration: response.duration,
  };
}

/**
 * Transcreve áudio usando Gemini Flash 2.0
 * Gemini 2.0 Flash suporta áudio nativamente
 */
async function transcribeWithGemini(
  agent: Agent,
  mediaData: MediaData
): Promise<MediaAnalysisResult> {
  const apiKey = agent.gemini_api_key;

  if (!apiKey) {
    throw new Error('Gemini API key not configured for this agent');
  }

  const genAI = new GoogleGenerativeAI(apiKey);
  const model = genAI.getGenerativeModel({ model: 'gemini-2.0-flash' });

  // Limpar base64 usando helper universal
  const base64Clean = cleanBase64Data(mediaData.base64);

  logger.debug('Calling Gemini for audio transcription', { mimeType: mediaData.mimeType });

  const result = await model.generateContent([
    {
      inlineData: {
        mimeType: mediaData.mimeType,
        data: base64Clean,
      },
    },
    'Transcreva este áudio em português. Retorne apenas a transcrição, sem comentários adicionais.',
  ]);

  const text = result.response.text();

  logger.info('Gemini transcription completed', { textLength: text.length });

  return {
    success: true,
    text,
    type: 'transcription',
    provider: 'gemini',
  };
}

/**
 * Para Claude, tentamos fallback para Gemini ou OpenAI
 * Claude não tem transcrição nativa de áudio
 */
async function describeAudioWithClaude(
  agent: Agent,
  mediaData: MediaData
): Promise<MediaAnalysisResult> {
  // Tentar fallback para Gemini primeiro (mais comum)
  if (agent.gemini_api_key) {
    logger.info('Claude does not support audio, falling back to Gemini');
    try {
      const result = await transcribeWithGemini(agent, mediaData);
      return {
        ...result,
        provider: 'claude', // Manter Claude como provider principal
      };
    } catch (error) {
      logger.warn('Gemini fallback failed', { error: error instanceof Error ? error.message : error });
    }
  }

  // Tentar fallback para OpenAI
  if ((agent as any).openai_api_key) {
    logger.info('Claude does not support audio, falling back to OpenAI Whisper');
    try {
      const result = await transcribeWithOpenAI(agent, mediaData);
      return {
        ...result,
        provider: 'claude', // Manter Claude como provider principal
      };
    } catch (error) {
      logger.warn('OpenAI fallback failed', { error: error instanceof Error ? error.message : error });
    }
  }

  // Se nenhum fallback disponível, retornar mensagem informativa
  logger.warn('No fallback available for Claude audio transcription');
  return {
    success: false,
    text: '[Mensagem de áudio recebida - Configure uma API key do Gemini ou OpenAI para transcrição]',
    type: 'transcription',
    provider: 'claude',
  };
}

// ============================================================================
// IMAGE ANALYSIS
// ============================================================================

/**
 * Analisa imagem usando o provider configurado do agent
 */
export async function analyzeImage(
  agent: Agent,
  mediaData: MediaData,
  prompt?: string
): Promise<MediaAnalysisResult> {
  const provider = agent.ai_provider || 'gemini';
  const analysisPrompt = prompt || 'Descreva o que você vê nesta imagem de forma clara e concisa.';

  logger.info('Analyzing image', {
    provider,
    mimeType: mediaData.mimeType,
    hasBase64: !!mediaData.base64
  });

  try {
    switch (provider) {
      case 'openai':
        return await analyzeWithOpenAI(agent, mediaData, analysisPrompt);
      case 'gemini':
        return await analyzeWithGemini(agent, mediaData, analysisPrompt);
      case 'claude':
        return await analyzeWithClaude(agent, mediaData, analysisPrompt);
      default:
        return await analyzeWithGemini(agent, mediaData, analysisPrompt);
    }
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : String(error);
    logger.error('Image analysis failed', { provider, error: errorMessage });

    return {
      success: false,
      text: '[Não foi possível analisar a imagem]',
      type: 'error',
      provider,
    };
  }
}

/**
 * Analisa imagem usando OpenAI GPT-4 Vision
 */
async function analyzeWithOpenAI(
  agent: Agent,
  mediaData: MediaData,
  prompt: string
): Promise<MediaAnalysisResult> {
  const apiKey = (agent as any).openai_api_key;
  const model = (agent as any).openai_model || 'gpt-4o';

  if (!apiKey) {
    throw new Error('OpenAI API key not configured for this agent');
  }

  const client = new OpenAI({ apiKey });

  // Preparar base64 com prefixo correto
  let imageData = mediaData.base64;
  if (!imageData.startsWith('data:')) {
    imageData = `data:${mediaData.mimeType};base64,${mediaData.base64}`;
  }

  logger.debug('Calling OpenAI Vision', { model, mimeType: mediaData.mimeType });

  const response = await client.chat.completions.create({
    model,
    messages: [
      {
        role: 'user',
        content: [
          {
            type: 'image_url',
            image_url: {
              url: imageData,
            },
          },
          {
            type: 'text',
            text: prompt,
          },
        ],
      },
    ],
    max_tokens: 500,
  });

  const text = response.choices[0]?.message?.content || '';

  logger.info('OpenAI vision completed', { textLength: text.length });

  return {
    success: true,
    text,
    type: 'vision',
    provider: 'openai',
  };
}

/**
 * Analisa imagem usando Gemini Vision
 */
async function analyzeWithGemini(
  agent: Agent,
  mediaData: MediaData,
  prompt: string
): Promise<MediaAnalysisResult> {
  const apiKey = agent.gemini_api_key;
  const modelName = agent.gemini_model || 'gemini-2.0-flash';

  if (!apiKey) {
    throw new Error('Gemini API key not configured for this agent');
  }

  const genAI = new GoogleGenerativeAI(apiKey);
  const model = genAI.getGenerativeModel({ model: modelName });

  // Limpar base64 usando helper universal
  const base64Clean = cleanBase64Data(mediaData.base64);

  logger.debug('Calling Gemini Vision', { model: modelName, mimeType: mediaData.mimeType });

  const result = await model.generateContent([
    prompt,
    {
      inlineData: {
        mimeType: mediaData.mimeType,
        data: base64Clean,
      },
    },
  ]);

  const text = result.response.text();

  logger.info('Gemini vision completed', { textLength: text.length });

  return {
    success: true,
    text,
    type: 'vision',
    provider: 'gemini',
  };
}

/**
 * Analisa imagem usando Claude Vision
 */
async function analyzeWithClaude(
  agent: Agent,
  mediaData: MediaData,
  prompt: string
): Promise<MediaAnalysisResult> {
  const Anthropic = (await import('@anthropic-ai/sdk')).default;

  const apiKey = (agent as any).claude_api_key;
  const model = (agent as any).claude_model || 'claude-sonnet-4-20250514';

  if (!apiKey) {
    throw new Error('Claude API key not configured for this agent');
  }

  const client = new Anthropic({ apiKey });

  // Limpar base64 usando helper universal
  const base64Clean = cleanBase64Data(mediaData.base64);

  // Mapear mimeType para tipo aceito pelo Claude
  const mediaType = mapToClaudeMediaType(mediaData.mimeType);

  logger.debug('Calling Claude Vision', { model, mimeType: mediaType });

  const response = await client.messages.create({
    model,
    max_tokens: 500,
    messages: [
      {
        role: 'user',
        content: [
          {
            type: 'image',
            source: {
              type: 'base64',
              media_type: mediaType,
              data: base64Clean,
            },
          },
          {
            type: 'text',
            text: prompt,
          },
        ],
      },
    ],
  });

  // Extrair texto da resposta
  let text = '';
  for (const block of response.content) {
    if (block.type === 'text') {
      text += block.text;
    }
  }

  logger.info('Claude vision completed', { textLength: text.length });

  return {
    success: true,
    text,
    type: 'vision',
    provider: 'claude',
  };
}

// ============================================================================
// HELPERS
// ============================================================================

/**
 * Remove prefixo data:xxx;base64, do base64 de forma universal
 * Funciona para qualquer tipo de mídia (audio, image, video, etc)
 */
function cleanBase64Data(base64: string): string {
  // Regex universal que remove qualquer prefixo data:mimetype;base64,
  return base64.replace(/^data:[^;]+;base64,/i, '');
}

/**
 * Obtém extensão de arquivo de áudio a partir do mimeType
 */
function getAudioExtension(mimeType: string): string {
  const mimeToExtension: Record<string, string> = {
    'audio/ogg': 'ogg',
    'audio/ogg; codecs=opus': 'ogg',
    'audio/opus': 'opus',
    'audio/mpeg': 'mp3',
    'audio/mp3': 'mp3',
    'audio/mp4': 'm4a',
    'audio/m4a': 'm4a',
    'audio/wav': 'wav',
    'audio/wave': 'wav',
    'audio/x-wav': 'wav',
    'audio/webm': 'webm',
    'audio/flac': 'flac',
  };

  const normalizedMime = mimeType.split(';')[0].trim().toLowerCase();
  return mimeToExtension[normalizedMime] || 'ogg';
}

/**
 * Mapeia mimeType para tipo aceito pelo Claude
 */
function mapToClaudeMediaType(mimeType: string): 'image/jpeg' | 'image/png' | 'image/gif' | 'image/webp' {
  const normalizedMime = mimeType.split(';')[0].trim().toLowerCase();

  if (normalizedMime === 'image/jpeg' || normalizedMime === 'image/jpg') {
    return 'image/jpeg';
  }
  if (normalizedMime === 'image/png') {
    return 'image/png';
  }
  if (normalizedMime === 'image/gif') {
    return 'image/gif';
  }
  if (normalizedMime === 'image/webp') {
    return 'image/webp';
  }

  // Default para jpeg
  return 'image/jpeg';
}

/**
 * Determina se um mimeType é de áudio
 */
export function isAudioMimeType(mimeType: string): boolean {
  return mimeType.startsWith('audio/');
}

/**
 * Determina se um mimeType é de imagem
 */
export function isImageMimeType(mimeType: string): boolean {
  return mimeType.startsWith('image/');
}

/**
 * Determina se um mimeType é de vídeo
 */
export function isVideoMimeType(mimeType: string): boolean {
  return mimeType.startsWith('video/');
}
