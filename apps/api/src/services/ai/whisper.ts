import OpenAI from 'openai';
import { TranscriptionParams, TranscriptionResult } from './types';

const DEFAULT_MODEL = 'whisper-1';
const DEFAULT_LANGUAGE = 'pt';
const MAX_RETRIES = 2;
const RETRY_DELAY_MS = 1000;

export class WhisperClient {
  private client: OpenAI;
  private model: string;
  private defaultLanguage: string;

  constructor(apiKey: string, model?: string, defaultLanguage?: string) {
    this.client = new OpenAI({
      apiKey,
    });
    this.model = model || DEFAULT_MODEL;
    this.defaultLanguage = defaultLanguage || DEFAULT_LANGUAGE;
  }

  /**
   * Transcreve um áudio em base64 para texto
   */
  async transcribe(params: TranscriptionParams): Promise<TranscriptionResult> {
    const {
      audioBase64,
      mimeType,
      language = this.defaultLanguage,
      prompt,
    } = params;

    return this.executeWithRetry(async () => {
      // Converter base64 para File
      const file = this.base64ToFile(audioBase64, mimeType);

      const response = await this.client.audio.transcriptions.create({
        file,
        model: this.model,
        language,
        prompt,
        response_format: 'verbose_json',
      });

      return {
        text: response.text,
        language: response.language,
        duration: response.duration,
      };
    });
  }

  /**
   * Transcreve um áudio diretamente de base64 (método simplificado)
   */
  async transcribeBase64(audioBase64: string, mimeType: string): Promise<string> {
    const result = await this.transcribe({ audioBase64, mimeType });
    return result.text;
  }

  /**
   * Converte base64 para File
   */
  private base64ToFile(base64: string, mimeType: string): File {
    // Remover prefixo data:audio/xxx;base64, se presente
    const cleanBase64 = base64.replace(/^data:audio\/[a-z]+;base64,/, '');

    // Converter para buffer
    const buffer = Buffer.from(cleanBase64, 'base64');

    // Determinar extensão do arquivo
    const extension = this.getExtensionFromMimeType(mimeType);
    const fileName = `audio.${extension}`;

    // Criar Blob e File
    const blob = new Blob([buffer], { type: mimeType });
    return new File([blob], fileName, { type: mimeType });
  }

  /**
   * Obtém a extensão do arquivo a partir do mimeType
   */
  private getExtensionFromMimeType(mimeType: string): string {
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

    // Normalizar mimeType (remover parâmetros extras)
    const normalizedMime = mimeType.split(';')[0].trim().toLowerCase();

    return mimeToExtension[normalizedMime] || 'ogg';
  }

  /**
   * Executa uma operação com retry automático
   */
  private async executeWithRetry<T>(
    operation: () => Promise<T>,
    retries: number = MAX_RETRIES
  ): Promise<T> {
    let lastError: Error | null = null;

    for (let attempt = 1; attempt <= retries; attempt++) {
      try {
        return await operation();
      } catch (error) {
        lastError = error instanceof Error ? error : new Error(String(error));

        // Verificar se é um erro recuperável
        if (this.isRetryableError(error) && attempt < retries) {
          console.warn(
            `[WhisperClient] Attempt ${attempt} failed, retrying in ${RETRY_DELAY_MS * attempt}ms...`,
            lastError.message
          );
          await this.delay(RETRY_DELAY_MS * attempt);
          continue;
        }

        // Erro não recuperável ou última tentativa
        break;
      }
    }

    console.error('[WhisperClient] All retry attempts failed:', lastError);
    throw lastError;
  }

  /**
   * Verifica se o erro é recuperável
   */
  private isRetryableError(error: unknown): boolean {
    if (error instanceof OpenAI.APIError) {
      // Retry em erros de rate limit ou servidor
      return (
        error.status === 429 || // Rate limit
        error.status === 500 || // Internal server error
        error.status === 502 || // Bad gateway
        error.status === 503 || // Service unavailable
        error.status === 504 // Gateway timeout
      );
    }

    // Retry em erros de rede
    if (error instanceof Error) {
      return (
        error.message.includes('ECONNRESET') ||
        error.message.includes('ETIMEDOUT') ||
        error.message.includes('ENOTFOUND') ||
        error.message.includes('socket hang up')
      );
    }

    return false;
  }

  /**
   * Helper para delay
   */
  private delay(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  /**
   * Atualiza o modelo usado
   */
  setModel(model: string): void {
    this.model = model;
  }

  /**
   * Retorna o modelo atual
   */
  getModel(): string {
    return this.model;
  }

  /**
   * Atualiza o idioma padrão
   */
  setDefaultLanguage(language: string): void {
    this.defaultLanguage = language;
  }

  /**
   * Retorna o idioma padrão atual
   */
  getDefaultLanguage(): string {
    return this.defaultLanguage;
  }
}

/**
 * Factory function para criar cliente Whisper
 */
export function createWhisperClient(
  apiKey: string,
  model?: string,
  defaultLanguage?: string
): WhisperClient {
  return new WhisperClient(apiKey, model, defaultLanguage);
}
