/**
 * Message Buffer Service - Redis
 *
 * Servico de buffer de mensagens usando Redis para ambiente distribuido.
 * Substitui o buffer baseado em Supabase/memoria local.
 *
 * Funcionalidades:
 * - Armazena mensagens temporariamente antes do processamento
 * - Permite concatenacao de mensagens sequenciais
 * - TTL automatico para cleanup
 * - Funciona em ambiente multi-instancia
 */

import { getRedisConnection, isRedisAvailable } from './client';
import type { Redis } from 'ioredis';

// ============================================================================
// TYPES
// ============================================================================

export interface BufferedMessage {
  id: string;
  content: string;
  timestamp: number;
  type: string;
  // Campos de midia opcionais
  mediaType?: string;
  mimeType?: string;
  mediaUrl?: string;
  mediaKey?: string;
  fileSha256?: string;
  fileLength?: number;
}

export interface BufferMediaEntry {
  messageId: string;
  mediaType: string;
  mimeType?: string;
  mediaUrl?: string;
  mediaKey?: string;
  fileSha256?: string;
  fileLength?: number;
  timestamp: number;
}

// ============================================================================
// CONSTANTS
// ============================================================================

const BUFFER_KEY_PREFIX = 'buffer:';
const BUFFER_TTL_SECONDS = 3600; // 1 hora

// ============================================================================
// LOGGER
// ============================================================================

const Logger = {
  info: (message: string, data?: unknown) => {
    console.log(`[MessageBuffer] ${message}`, data ? JSON.stringify(data) : '');
  },
  error: (message: string, error?: unknown) => {
    console.error(`[MessageBuffer] ${message}`, error);
  },
  debug: (message: string, data?: unknown) => {
    if (process.env.DEBUG === 'true') {
      console.log(`[MessageBuffer:DEBUG] ${message}`, data ? JSON.stringify(data) : '');
    }
  },
};

// ============================================================================
// MESSAGE BUFFER SERVICE
// ============================================================================

export class MessageBufferService {
  private redis: Redis | null = null;
  private available: boolean = false;

  constructor() {
    this.initialize();
  }

  /**
   * Inicializa conexao Redis
   */
  private async initialize(): Promise<void> {
    try {
      this.available = await isRedisAvailable();
      if (this.available) {
        this.redis = getRedisConnection();
        Logger.info('Service initialized with Redis');
      } else {
        Logger.info('Redis not available, service will use fallback');
      }
    } catch (error) {
      Logger.error('Failed to initialize', error);
      this.available = false;
    }
  }

  /**
   * Verifica se o servico esta disponivel
   */
  isAvailable(): boolean {
    return this.available && this.redis !== null;
  }

  /**
   * Gera a chave Redis para um remoteJid
   */
  private getBufferKey(remoteJid: string): string {
    return `${BUFFER_KEY_PREFIX}${remoteJid}`;
  }

  /**
   * Adiciona uma mensagem ao buffer
   *
   * @param remoteJid Identificador do lead (WhatsApp JID)
   * @param message Dados da mensagem
   */
  async addMessage(remoteJid: string, message: BufferedMessage): Promise<void> {
    if (!this.redis) {
      Logger.error('Redis not available for addMessage');
      return;
    }

    const key = this.getBufferKey(remoteJid);

    try {
      // Serializa e adiciona ao final da lista
      const serialized = JSON.stringify(message);
      await this.redis.rpush(key, serialized);

      // Atualiza TTL para garantir cleanup automatico
      await this.redis.expire(key, BUFFER_TTL_SECONDS);

      Logger.debug('Message added to buffer', {
        remoteJid,
        messageId: message.id,
        bufferKey: key
      });
    } catch (error) {
      Logger.error('Failed to add message to buffer', { remoteJid, error });
      throw error;
    }
  }

  /**
   * Obtem todas as mensagens do buffer
   *
   * @param remoteJid Identificador do lead
   * @returns Array de mensagens no buffer
   */
  async getMessages(remoteJid: string): Promise<BufferedMessage[]> {
    if (!this.redis) {
      Logger.error('Redis not available for getMessages');
      return [];
    }

    const key = this.getBufferKey(remoteJid);

    try {
      const messages = await this.redis.lrange(key, 0, -1);

      return messages.map(msg => {
        try {
          return JSON.parse(msg) as BufferedMessage;
        } catch {
          Logger.error('Failed to parse message from buffer', { msg });
          return null;
        }
      }).filter((msg): msg is BufferedMessage => msg !== null);
    } catch (error) {
      Logger.error('Failed to get messages from buffer', { remoteJid, error });
      return [];
    }
  }

  /**
   * Verifica se uma mensagem e a ultima no buffer
   *
   * @param remoteJid Identificador do lead
   * @param messageId ID da mensagem a verificar
   * @returns true se for a ultima mensagem
   */
  async isLastMessage(remoteJid: string, messageId: string): Promise<boolean> {
    if (!this.redis) {
      return true; // Fallback: assume que e a ultima
    }

    const key = this.getBufferKey(remoteJid);

    try {
      // Pega apenas a ultima mensagem (indice -1)
      const lastMessages = await this.redis.lrange(key, -1, -1);

      if (lastMessages.length === 0) {
        return true;
      }

      const lastMessage = JSON.parse(lastMessages[0]) as BufferedMessage;
      return lastMessage.id === messageId;
    } catch (error) {
      Logger.error('Failed to check if last message', { remoteJid, error });
      return true; // Em caso de erro, processa a mensagem
    }
  }

  /**
   * Obtem o timestamp da ultima mensagem
   *
   * @param remoteJid Identificador do lead
   * @returns Timestamp da ultima mensagem ou null
   */
  async getLastMessageTimestamp(remoteJid: string): Promise<number | null> {
    if (!this.redis) {
      return null;
    }

    const key = this.getBufferKey(remoteJid);

    try {
      const lastMessages = await this.redis.lrange(key, -1, -1);

      if (lastMessages.length === 0) {
        return null;
      }

      const lastMessage = JSON.parse(lastMessages[0]) as BufferedMessage;
      return lastMessage.timestamp;
    } catch (error) {
      Logger.error('Failed to get last message timestamp', { remoteJid, error });
      return null;
    }
  }

  /**
   * Obtem o numero de mensagens no buffer
   *
   * @param remoteJid Identificador do lead
   * @returns Numero de mensagens
   */
  async getMessageCount(remoteJid: string): Promise<number> {
    if (!this.redis) {
      return 0;
    }

    const key = this.getBufferKey(remoteJid);

    try {
      return await this.redis.llen(key);
    } catch (error) {
      Logger.error('Failed to get message count', { remoteJid, error });
      return 0;
    }
  }

  /**
   * Limpa todas as mensagens do buffer
   *
   * @param remoteJid Identificador do lead
   */
  async clearMessages(remoteJid: string): Promise<void> {
    if (!this.redis) {
      Logger.error('Redis not available for clearMessages');
      return;
    }

    const key = this.getBufferKey(remoteJid);

    try {
      await this.redis.del(key);
      Logger.debug('Buffer cleared', { remoteJid, bufferKey: key });
    } catch (error) {
      Logger.error('Failed to clear buffer', { remoteJid, error });
      throw error;
    }
  }

  /**
   * Concatena todas as mensagens do buffer em um texto unico
   *
   * @param remoteJid Identificador do lead
   * @returns Objeto com texto concatenado e metadados
   */
  async concatenateAndClear(remoteJid: string): Promise<{
    text: string;
    messages: BufferedMessage[];
    mediaEntries: BufferMediaEntry[];
    lastMessageId: string | null;
    messageCount: number;
  }> {
    const messages = await this.getMessages(remoteJid);

    if (messages.length === 0) {
      return {
        text: '',
        messages: [],
        mediaEntries: [],
        lastMessageId: null,
        messageCount: 0
      };
    }

    // Concatena textos com newline (como o sistema atual)
    const text = messages.map(m => m.content).join('\n');
    const lastMessageId = messages[messages.length - 1].id;

    // Extrai entradas de midia
    const mediaEntries: BufferMediaEntry[] = messages
      .filter(m => m.mediaType)
      .map(m => ({
        messageId: m.id,
        mediaType: m.mediaType!,
        mimeType: m.mimeType,
        mediaUrl: m.mediaUrl,
        mediaKey: m.mediaKey,
        fileSha256: m.fileSha256,
        fileLength: m.fileLength,
        timestamp: m.timestamp
      }));

    // Limpa o buffer
    await this.clearMessages(remoteJid);

    Logger.info('Buffer concatenated and cleared', {
      remoteJid,
      messageCount: messages.length,
      mediaCount: mediaEntries.length,
      textPreview: text.substring(0, 50)
    });

    return {
      text,
      messages,
      mediaEntries,
      lastMessageId,
      messageCount: messages.length
    };
  }
}

// ============================================================================
// SINGLETON INSTANCE
// ============================================================================

let instance: MessageBufferService | null = null;

export function getMessageBufferService(): MessageBufferService {
  if (!instance) {
    instance = new MessageBufferService();
  }
  return instance;
}

export default MessageBufferService;
