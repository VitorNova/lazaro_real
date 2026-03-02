/**
 * Buffer Processor Service - Redis
 *
 * Servico completo de processamento de buffer de mensagens usando Redis.
 * Implementa a mesma logica do sistema atual (n8n-like) mas de forma distribuida.
 *
 * Fluxo:
 * 1. Mensagem chega -> adiciona ao buffer Redis
 * 2. Verifica se e a ultima mensagem
 * 3. Espera delay configuravel
 * 4. Verifica lock e adquire
 * 5. Busca e concatena mensagens
 * 6. Processa batch
 * 7. Libera lock
 */

import { getMessageBufferService, BufferedMessage, BufferMediaEntry } from './message-buffer.service';
import { getLockService } from './lock.service';
import { isRedisAvailable } from './client';

// ============================================================================
// TYPES
// ============================================================================

export interface BufferProcessorConfig {
  delayMs: number;
  marginMs?: number;
}

export interface BufferProcessResult {
  messages: string[];
  lastMessageId: string | null;
  originalMessageCount: number;
  vcardData?: { displayName?: string; vcard?: string };
  mediaEntries?: BufferMediaEntry[];
  skipped?: boolean;
  reason?: string;
}

export interface MessageInput {
  text: string;
  messageId: string;
  timestamp?: number;
  messageType?: string;
  vcardData?: { displayName?: string; vcard?: string };
  mediaData?: {
    mediaType?: string;
    mimeType?: string;
    mediaUrl?: string;
    mediaKey?: string;
    fileSha256?: string;
    fileLength?: number;
  };
}

// ============================================================================
// CONSTANTS
// ============================================================================

const DEFAULT_DELAY_MS = 9000;
const DEFAULT_MARGIN_MS = 5000;
const LOCK_TTL_SECONDS = 200;

// ============================================================================
// LOGGER
// ============================================================================

const Logger = {
  info: (message: string, data?: unknown) => {
    console.log(`[BufferProcessor] ${message}`, data ? JSON.stringify(data) : '');
  },
  error: (message: string, error?: unknown) => {
    console.error(`[BufferProcessor] ${message}`, error);
  },
  debug: (message: string, data?: unknown) => {
    if (process.env.DEBUG === 'true') {
      console.log(`[BufferProcessor:DEBUG] ${message}`, data ? JSON.stringify(data) : '');
    }
  },
  warn: (message: string, data?: unknown) => {
    console.warn(`[BufferProcessor] ${message}`, data ? JSON.stringify(data) : '');
  },
};

// ============================================================================
// BUFFER PROCESSOR SERVICE
// ============================================================================

export class BufferProcessorService {
  private bufferService = getMessageBufferService();
  private lockService = getLockService();
  private pendingTimers = new Map<string, NodeJS.Timeout>();
  private redisAvailable: boolean = false;

  constructor() {
    this.initialize();
  }

  private async initialize(): Promise<void> {
    this.redisAvailable = await isRedisAvailable();
    Logger.info('Service initialized', { redisAvailable: this.redisAvailable });
  }

  /**
   * Verifica se Redis esta disponivel
   */
  isRedisAvailable(): boolean {
    return this.redisAvailable;
  }

  /**
   * Processa uma mensagem usando buffer Redis
   *
   * @param remoteJid Identificador do lead
   * @param input Dados da mensagem
   * @param config Configuracoes de delay
   * @returns Resultado do processamento
   */
  async processMessage(
    remoteJid: string,
    input: MessageInput,
    config: BufferProcessorConfig = { delayMs: DEFAULT_DELAY_MS }
  ): Promise<BufferProcessResult> {
    const { delayMs, marginMs = DEFAULT_MARGIN_MS } = config;

    Logger.info('1. Processing message', {
      remoteJid,
      messageId: input.messageId,
      textPreview: input.text.substring(0, 30),
      delayMs,
      redisAvailable: this.redisAvailable
    });

    // Se Redis nao esta disponivel, retorna imediatamente
    if (!this.redisAvailable || !this.bufferService.isAvailable()) {
      Logger.warn('Redis not available, returning message immediately', { remoteJid });
      return this.createImmediateResult(input);
    }

    // 1. Adiciona mensagem ao buffer
    const bufferedMessage: BufferedMessage = {
      id: input.messageId,
      content: input.text,
      timestamp: input.timestamp || Math.floor(Date.now() / 1000),
      type: input.messageType || 'text',
      mediaType: input.mediaData?.mediaType,
      mimeType: input.mediaData?.mimeType,
      mediaUrl: input.mediaData?.mediaUrl,
      mediaKey: input.mediaData?.mediaKey,
      fileSha256: input.mediaData?.fileSha256,
      fileLength: input.mediaData?.fileLength,
    };

    await this.bufferService.addMessage(remoteJid, bufferedMessage);

    // 2. Verifica se e a ultima mensagem
    const isLast = await this.bufferService.isLastMessage(remoteJid, input.messageId);

    if (!isLast) {
      Logger.info('Not the last message, skipping', {
        remoteJid,
        messageId: input.messageId
      });
      return {
        messages: [],
        lastMessageId: null,
        originalMessageCount: 0,
        skipped: true,
        reason: 'not_last_message'
      };
    }

    // 3. Verifica se delay ja passou
    const lastTimestamp = await this.bufferService.getLastMessageTimestamp(remoteJid);
    const nowSeconds = Math.floor(Date.now() / 1000);
    const delaySeconds = Math.floor(delayMs / 1000);
    const delayThreshold = nowSeconds - delaySeconds;
    const delayPassed = lastTimestamp ? lastTimestamp < delayThreshold : true;

    Logger.info('2. Checking delay', {
      remoteJid,
      lastTimestamp,
      nowSeconds,
      delaySeconds,
      delayThreshold,
      delayPassed
    });

    if (delayPassed) {
      // Delay ja passou, processar imediatamente
      return await this.executeProcessing(remoteJid, input.vcardData);
    }

    // 4. Espera o delay + margem
    const waitMs = delayMs + marginMs;

    Logger.info('3. Waiting for delay', {
      remoteJid,
      waitMs,
      delayMs,
      marginMs
    });

    // Cancela timer anterior se existir
    const existingTimer = this.pendingTimers.get(remoteJid);
    if (existingTimer) {
      clearTimeout(existingTimer);
    }

    // Retorna Promise que resolve apos o delay
    return new Promise<BufferProcessResult>((resolve) => {
      const timer = setTimeout(async () => {
        this.pendingTimers.delete(remoteJid);
        const result = await this.recheckAndProcess(remoteJid, input.messageId, delayMs, marginMs, input.vcardData);
        resolve(result);
      }, waitMs);

      this.pendingTimers.set(remoteJid, timer);
    });
  }

  /**
   * Re-verifica o buffer apos o delay (loop de verificacao)
   */
  private async recheckAndProcess(
    remoteJid: string,
    originalMessageId: string,
    delayMs: number,
    marginMs: number,
    vcardData?: { displayName?: string; vcard?: string }
  ): Promise<BufferProcessResult> {
    Logger.info('4. Rechecking after wait', { remoteJid, originalMessageId });

    // Verifica se ainda e a ultima mensagem
    const isLast = await this.bufferService.isLastMessage(remoteJid, originalMessageId);

    if (!isLast) {
      Logger.info('New message arrived, skipping', { remoteJid, originalMessageId });
      return {
        messages: [],
        lastMessageId: null,
        originalMessageCount: 0,
        skipped: true,
        reason: 'new_message_arrived'
      };
    }

    // Verifica delay novamente
    const lastTimestamp = await this.bufferService.getLastMessageTimestamp(remoteJid);
    const nowSeconds = Math.floor(Date.now() / 1000);
    const delaySeconds = Math.floor(delayMs / 1000);
    const delayThreshold = nowSeconds - delaySeconds;
    const delayPassed = lastTimestamp ? lastTimestamp < delayThreshold : true;

    if (delayPassed) {
      return await this.executeProcessing(remoteJid, vcardData);
    }

    // Ainda nao passou o delay, espera mais uma vez
    const waitMs = delayMs + marginMs;
    Logger.info('5. Delay not passed, waiting again', { remoteJid, waitMs });

    return new Promise<BufferProcessResult>((resolve) => {
      const timer = setTimeout(async () => {
        this.pendingTimers.delete(remoteJid);
        const result = await this.recheckAndProcess(remoteJid, originalMessageId, delayMs, marginMs, vcardData);
        resolve(result);
      }, waitMs);

      this.pendingTimers.set(remoteJid, timer);
    });
  }

  /**
   * Executa o processamento do buffer com lock
   */
  private async executeProcessing(
    remoteJid: string,
    vcardData?: { displayName?: string; vcard?: string }
  ): Promise<BufferProcessResult> {
    Logger.info('6. Executing processing with lock', { remoteJid });

    // Tenta adquirir lock
    const lockAcquired = await this.lockService.acquireLock(remoteJid, LOCK_TTL_SECONDS);

    if (!lockAcquired) {
      Logger.warn('Could not acquire lock, skipping', { remoteJid });
      return {
        messages: [],
        lastMessageId: null,
        originalMessageCount: 0,
        skipped: true,
        reason: 'lock_not_acquired'
      };
    }

    try {
      // Concatena e limpa o buffer
      const result = await this.bufferService.concatenateAndClear(remoteJid);

      if (result.messageCount === 0) {
        Logger.info('Buffer empty, already processed', { remoteJid });
        return {
          messages: [],
          lastMessageId: null,
          originalMessageCount: 0,
          skipped: true,
          reason: 'buffer_empty'
        };
      }

      Logger.info('7. Buffer processed successfully', {
        remoteJid,
        messageCount: result.messageCount,
        textPreview: result.text.substring(0, 50),
        mediaCount: result.mediaEntries.length
      });

      return {
        messages: [result.text],
        lastMessageId: result.lastMessageId,
        originalMessageCount: result.messageCount,
        vcardData,
        mediaEntries: result.mediaEntries.length > 0 ? result.mediaEntries : undefined
      };
    } finally {
      // Libera lock com pequeno delay (igual ao sistema atual)
      setTimeout(async () => {
        await this.lockService.releaseLock(remoteJid);
        Logger.debug('Lock released', { remoteJid });
      }, 1000);
    }
  }

  /**
   * Cria resultado imediato (quando Redis nao esta disponivel)
   */
  private createImmediateResult(input: MessageInput): BufferProcessResult {
    const mediaEntries: BufferMediaEntry[] = [];

    if (input.mediaData?.mediaType) {
      mediaEntries.push({
        messageId: input.messageId,
        mediaType: input.mediaData.mediaType,
        mimeType: input.mediaData.mimeType,
        mediaUrl: input.mediaData.mediaUrl,
        mediaKey: input.mediaData.mediaKey,
        fileSha256: input.mediaData.fileSha256,
        fileLength: input.mediaData.fileLength,
        timestamp: input.timestamp || Math.floor(Date.now() / 1000)
      });
    }

    return {
      messages: [input.text],
      lastMessageId: input.messageId,
      originalMessageCount: 1,
      vcardData: input.vcardData,
      mediaEntries: mediaEntries.length > 0 ? mediaEntries : undefined
    };
  }

  /**
   * Limpa timers pendentes (para shutdown graceful)
   */
  clearPendingTimers(): void {
    for (const [remoteJid, timer] of this.pendingTimers) {
      clearTimeout(timer);
      Logger.debug('Timer cleared', { remoteJid });
    }
    this.pendingTimers.clear();
  }
}

// ============================================================================
// SINGLETON INSTANCE
// ============================================================================

let instance: BufferProcessorService | null = null;

export function getBufferProcessorService(): BufferProcessorService {
  if (!instance) {
    instance = new BufferProcessorService();
  }
  return instance;
}

export default BufferProcessorService;
