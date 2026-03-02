import axios, { AxiosInstance } from 'axios';

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

// ============================================================================
// TYPES
// ============================================================================

export interface EvolutionConfig {
  baseUrl: string;
  apiKey: string;
  instanceName?: string;
}

export interface EvolutionInstance {
  instanceName: string;
  instanceId?: string;
  status: string;
  state?: string;
  owner?: string;
  profileName?: string;
  profilePictureUrl?: string;
}

export interface EvolutionConnectionStatus {
  instance: {
    instanceName: string;
    state: 'open' | 'close' | 'connecting';
    owner?: string;
    profileName?: string;
    profilePictureUrl?: string;
  };
}

export interface EvolutionQRCode {
  pairingCode?: string;
  code?: string;
  base64?: string;
  count?: number;
}

export interface EvolutionWebhookConfig {
  url: string;
  webhook_by_events?: boolean;
  webhook_base64?: boolean;
  events?: string[];
}

export interface EvolutionSendMessageResponse {
  key: {
    remoteJid: string;
    fromMe: boolean;
    id: string;
  };
  message: unknown;
  messageTimestamp: number;
  status: string;
}

export interface CreateInstanceOptions {
  instanceName: string;
  qrcode?: boolean;
  integration?: 'WHATSAPP-BAILEYS' | 'WHATSAPP-BUSINESS';
  token?: string;
  webhook?: string;
  webhookByEvents?: boolean;
  webhookBase64?: boolean;
  webhookEvents?: string[];
}

// ============================================================================
// EVOLUTION CLIENT
// ============================================================================

export class EvolutionClient {
  private client: AxiosInstance;
  private logger: Logger;
  private instanceName: string | null;
  private baseUrl: string;

  constructor(config: EvolutionConfig) {
    this.baseUrl = config.baseUrl.replace(/\/$/, '');
    this.instanceName = config.instanceName || null;
    this.logger = createLogger('EvolutionClient');

    this.client = axios.create({
      baseURL: this.baseUrl,
      timeout: 60000,
      headers: {
        'Content-Type': 'application/json',
        'apikey': config.apiKey,
      },
    });

    this.logger.info('Evolution client initialized', {
      baseUrl: this.baseUrl,
      instanceName: this.instanceName,
    });
  }

  // ==========================================================================
  // INSTANCE MANAGEMENT
  // ==========================================================================

  /**
   * Lista todas as instâncias
   */
  async listInstances(): Promise<EvolutionInstance[]> {
    try {
      const response = await this.client.get('/instance/fetchInstances');
      return response.data.map((inst: any) => ({
        instanceName: inst.instance?.instanceName || inst.name,
        instanceId: inst.instance?.instanceId,
        status: inst.instance?.status || 'unknown',
        state: inst.instance?.state,
        owner: inst.instance?.owner,
        profileName: inst.instance?.profileName,
        profilePictureUrl: inst.instance?.profilePictureUrl,
      }));
    } catch (error) {
      this.logger.error('Error listing instances', error);
      throw this.handleError(error, 'listInstances');
    }
  }

  /**
   * Cria uma nova instância
   */
  async createInstance(options: CreateInstanceOptions): Promise<{ instance: EvolutionInstance; hash?: string; qrcode?: EvolutionQRCode }> {
    this.logger.info('Creating instance', { instanceName: options.instanceName });

    try {
      const payload: any = {
        instanceName: options.instanceName,
        qrcode: options.qrcode ?? true,
        integration: options.integration || 'WHATSAPP-BAILEYS',
      };

      if (options.token) payload.token = options.token;
      if (options.webhook) {
        payload.webhook = {
          url: options.webhook,
          webhook_by_events: options.webhookByEvents ?? false,
          webhook_base64: options.webhookBase64 ?? false,
          events: options.webhookEvents || [
            'MESSAGES_UPSERT',
            'MESSAGES_UPDATE',
            'CONNECTION_UPDATE',
            'QRCODE_UPDATED',
          ],
        };
      }

      const response = await this.client.post('/instance/create', payload);

      this.instanceName = options.instanceName;

      return {
        instance: {
          instanceName: response.data.instance?.instanceName || options.instanceName,
          instanceId: response.data.instance?.instanceId,
          status: response.data.instance?.status || 'created',
        },
        hash: response.data.hash,
        qrcode: response.data.qrcode,
      };
    } catch (error) {
      this.logger.error('Error creating instance', error);
      throw this.handleError(error, 'createInstance');
    }
  }

  /**
   * Conecta uma instância (gera QR Code)
   */
  async connect(instanceName?: string): Promise<EvolutionQRCode> {
    const name = instanceName || this.instanceName;
    if (!name) throw new Error('Instance name is required');

    this.logger.info('Connecting instance', { instanceName: name });

    try {
      const response = await this.client.get(`/instance/connect/${name}`);
      return {
        pairingCode: response.data.pairingCode,
        code: response.data.code,
        base64: response.data.base64,
        count: response.data.count,
      };
    } catch (error) {
      this.logger.error('Error connecting instance', error);
      throw this.handleError(error, 'connect');
    }
  }

  /**
   * Obtém status da conexão
   */
  async getConnectionState(instanceName?: string): Promise<EvolutionConnectionStatus> {
    const name = instanceName || this.instanceName;
    if (!name) throw new Error('Instance name is required');

    try {
      const response = await this.client.get(`/instance/connectionState/${name}`);
      return response.data;
    } catch (error) {
      this.logger.error('Error getting connection state', error);
      throw this.handleError(error, 'getConnectionState');
    }
  }

  /**
   * Desconecta a instância
   */
  async logout(instanceName?: string): Promise<void> {
    const name = instanceName || this.instanceName;
    if (!name) throw new Error('Instance name is required');

    this.logger.info('Logging out instance', { instanceName: name });

    try {
      await this.client.delete(`/instance/logout/${name}`);
    } catch (error) {
      this.logger.error('Error logging out', error);
      throw this.handleError(error, 'logout');
    }
  }

  /**
   * Deleta uma instância
   */
  async deleteInstance(instanceName?: string): Promise<void> {
    const name = instanceName || this.instanceName;
    if (!name) throw new Error('Instance name is required');

    this.logger.info('Deleting instance', { instanceName: name });

    try {
      await this.client.delete(`/instance/delete/${name}`);
    } catch (error) {
      this.logger.error('Error deleting instance', error);
      throw this.handleError(error, 'deleteInstance');
    }
  }

  // ==========================================================================
  // MESSAGING
  // ==========================================================================

  /**
   * Envia mensagem de texto
   */
  async sendText(phone: string, text: string, instanceName?: string): Promise<EvolutionSendMessageResponse> {
    const name = instanceName || this.instanceName;
    if (!name) throw new Error('Instance name is required');

    // Formatar número
    const formattedPhone = this.formatPhoneNumber(phone);

    this.logger.info('Sending text', { to: formattedPhone, length: text.length });

    try {
      const response = await this.client.post(`/message/sendText/${name}`, {
        number: formattedPhone,
        text: text,
      });

      return response.data;
    } catch (error) {
      this.logger.error('Error sending text', { error, phone: formattedPhone });
      throw this.handleError(error, 'sendText');
    }
  }

  /**
   * Envia mídia (imagem, vídeo, documento, áudio)
   */
  async sendMedia(
    phone: string,
    mediaType: 'image' | 'video' | 'document' | 'audio',
    media: string, // URL ou Base64
    options?: { caption?: string; fileName?: string; mimetype?: string },
    instanceName?: string
  ): Promise<EvolutionSendMessageResponse> {
    const name = instanceName || this.instanceName;
    if (!name) throw new Error('Instance name is required');

    const formattedPhone = this.formatPhoneNumber(phone);

    this.logger.info('Sending media', { to: formattedPhone, type: mediaType });

    try {
      const payload: any = {
        number: formattedPhone,
        mediatype: mediaType,
        media: media,
      };

      if (options?.caption) payload.caption = options.caption;
      if (options?.fileName) payload.fileName = options.fileName;
      if (options?.mimetype) payload.mimetype = options.mimetype;

      const response = await this.client.post(`/message/sendMedia/${name}`, payload);
      return response.data;
    } catch (error) {
      this.logger.error('Error sending media', error);
      throw this.handleError(error, 'sendMedia');
    }
  }

  /**
   * Envia áudio (PTT - Push to Talk)
   */
  async sendAudio(phone: string, audio: string, instanceName?: string): Promise<EvolutionSendMessageResponse> {
    const name = instanceName || this.instanceName;
    if (!name) throw new Error('Instance name is required');

    const formattedPhone = this.formatPhoneNumber(phone);

    this.logger.info('Sending audio', { to: formattedPhone });

    try {
      const response = await this.client.post(`/message/sendWhatsAppAudio/${name}`, {
        number: formattedPhone,
        audio: audio,
      });
      return response.data;
    } catch (error) {
      this.logger.error('Error sending audio', error);
      throw this.handleError(error, 'sendAudio');
    }
  }

  /**
   * Envia localização
   */
  async sendLocation(
    phone: string,
    latitude: number,
    longitude: number,
    options?: { name?: string; address?: string },
    instanceName?: string
  ): Promise<EvolutionSendMessageResponse> {
    const name = instanceName || this.instanceName;
    if (!name) throw new Error('Instance name is required');

    const formattedPhone = this.formatPhoneNumber(phone);

    try {
      const response = await this.client.post(`/message/sendLocation/${name}`, {
        number: formattedPhone,
        latitude,
        longitude,
        name: options?.name,
        address: options?.address,
      });
      return response.data;
    } catch (error) {
      this.logger.error('Error sending location', error);
      throw this.handleError(error, 'sendLocation');
    }
  }

  // ==========================================================================
  // WEBHOOK
  // ==========================================================================

  /**
   * Configura webhook da instância
   */
  async setWebhook(config: EvolutionWebhookConfig, instanceName?: string): Promise<void> {
    const name = instanceName || this.instanceName;
    if (!name) throw new Error('Instance name is required');

    this.logger.info('Setting webhook', { instanceName: name, url: config.url });

    try {
      await this.client.post(`/webhook/set/${name}`, {
        webhook: {
          enabled: true,
          url: config.url,
          webhook_by_events: config.webhook_by_events ?? false,
          webhook_base64: config.webhook_base64 ?? false,
          events: config.events || [
            'MESSAGES_UPSERT',
            'MESSAGES_UPDATE',
            'CONNECTION_UPDATE',
          ],
        },
      });
    } catch (error) {
      this.logger.error('Error setting webhook', error);
      throw this.handleError(error, 'setWebhook');
    }
  }

  /**
   * Obtém configuração do webhook
   */
  async getWebhook(instanceName?: string): Promise<EvolutionWebhookConfig | null> {
    const name = instanceName || this.instanceName;
    if (!name) throw new Error('Instance name is required');

    try {
      const response = await this.client.get(`/webhook/find/${name}`);
      return response.data;
    } catch (error) {
      this.logger.warn('Error getting webhook', error);
      return null;
    }
  }

  // ==========================================================================
  // PRESENCE & STATUS (typing, recording, etc.)
  // ==========================================================================

  /**
   * Envia indicador de presença (digitando, gravando, etc.)
   * @param remoteJid - Número do destinatário
   * @param presence - Tipo de presença: 'composing' (digitando) ou 'recording' (gravando áudio)
   * @param delay - Tempo em ms para manter o indicador (opcional)
   */
  async sendPresence(
    remoteJid: string,
    presence: 'composing' | 'recording' | 'paused' = 'composing',
    delay?: number,
    instanceName?: string
  ): Promise<boolean> {
    const name = instanceName || this.instanceName;
    if (!name) throw new Error('Instance name is required');

    const formattedPhone = this.formatPhoneNumber(remoteJid);

    console.log('[Evolution] sendPresence called:', { remoteJid, formattedPhone, presence, delay, instance: name });

    try {
      this.logger.info('Sending presence', {
        endpoint: `/chat/sendPresence/${name}`,
        payload: { number: formattedPhone, presence, delay: delay || 1000 }
      });

      await this.client.post(`/chat/sendPresence/${name}`, {
        number: formattedPhone,
        presence: presence,
        delay: delay || 1000,
      });

      this.logger.info('Presence sent successfully', { to: formattedPhone, presence, delay });
      return true;
    } catch (error: any) {
      // Presence não é crítico - logar mas não falhar
      const errorDetail = error?.response?.data || error?.message || error;
      this.logger.error('Error sending presence (non-critical)', {
        error: errorDetail,
        phone: formattedPhone,
        presence,
        instance: name,
        statusCode: error?.response?.status,
        requestUrl: error?.config?.url,
        requestData: error?.config?.data,
      });
      return false;
    }
  }

  /**
   * Envia indicador de "digitando..." (wrapper de sendPresence)
   * @param remoteJid - Número do destinatário
   * @param duration - Duração em ms para mostrar "digitando..."
   */
  async sendTyping(remoteJid: string, duration?: number, instanceName?: string): Promise<boolean> {
    return this.sendPresence(remoteJid, 'composing', duration, instanceName);
  }

  /**
   * Envia indicador de "gravando áudio..." (wrapper de sendPresence)
   * @param remoteJid - Número do destinatário
   */
  async sendRecording(remoteJid: string, duration?: number, instanceName?: string): Promise<boolean> {
    return this.sendPresence(remoteJid, 'recording', duration, instanceName);
  }

  /**
   * Marca mensagem como lida
   * @param remoteJid - JID do chat
   * @param messageId - ID da mensagem (opcional)
   */
  async markAsRead(remoteJid: string, messageId?: string, instanceName?: string): Promise<boolean> {
    const name = instanceName || this.instanceName;
    if (!name) throw new Error('Instance name is required');

    const formattedPhone = this.formatPhoneNumber(remoteJid);

    try {
      await this.client.put(`/chat/markMessageAsRead/${name}`, {
        readMessages: [{
          remoteJid: formattedPhone.includes('@') ? formattedPhone : `${formattedPhone}@s.whatsapp.net`,
          fromMe: false,
          id: messageId || 'all',
        }],
      });

      this.logger.debug('Message marked as read', { remoteJid: formattedPhone });
      return true;
    } catch (error) {
      this.logger.warn('Error marking as read (non-critical)', {
        error: error instanceof Error ? error.message : error,
      });
      return false;
    }
  }

  /**
   * Obtém URL da foto de perfil de um contato
   * @param phone - Número do contato
   */
  async getProfilePicture(phone: string, instanceName?: string): Promise<string | null> {
    const name = instanceName || this.instanceName;
    if (!name) throw new Error('Instance name is required');

    const formattedPhone = this.formatPhoneNumber(phone);

    try {
      const response = await this.client.post(`/chat/fetchProfilePictureUrl/${name}`, {
        number: formattedPhone,
      });

      return response.data?.profilePictureUrl || response.data?.url || null;
    } catch (error) {
      this.logger.warn('Error fetching profile picture', {
        error: error instanceof Error ? error.message : error,
        phone: formattedPhone,
      });
      return null;
    }
  }

  // ==========================================================================
  // CONVENIENCE MESSAGING METHODS (para paridade com UAZAPI)
  // ==========================================================================

  /**
   * Envia imagem (wrapper de sendMedia)
   * @param phone - Número do destinatário
   * @param imageUrl - URL ou Base64 da imagem
   * @param caption - Legenda da imagem (opcional)
   */
  async sendImage(
    phone: string,
    imageUrl: string,
    caption?: string,
    instanceName?: string
  ): Promise<EvolutionSendMessageResponse> {
    return this.sendMedia(phone, 'image', imageUrl, { caption }, instanceName);
  }

  /**
   * Envia vídeo (wrapper de sendMedia)
   * @param phone - Número do destinatário
   * @param videoUrl - URL ou Base64 do vídeo
   * @param caption - Legenda do vídeo (opcional)
   */
  async sendVideo(
    phone: string,
    videoUrl: string,
    caption?: string,
    instanceName?: string
  ): Promise<EvolutionSendMessageResponse> {
    return this.sendMedia(phone, 'video', videoUrl, { caption }, instanceName);
  }

  /**
   * Envia documento (wrapper de sendMedia)
   * @param phone - Número do destinatário
   * @param documentUrl - URL ou Base64 do documento
   * @param fileName - Nome do arquivo
   * @param caption - Descrição do documento (opcional)
   */
  async sendDocument(
    phone: string,
    documentUrl: string,
    fileName: string,
    caption?: string,
    instanceName?: string
  ): Promise<EvolutionSendMessageResponse> {
    return this.sendMedia(phone, 'document', documentUrl, { fileName, caption }, instanceName);
  }

  /**
   * Envia áudio com simulação de gravação
   * @param phone - Número do destinatário
   * @param audioUrl - URL ou Base64 do áudio
   * @param ptt - Push-to-Talk (voice message) - default true
   * @param recordingDelay - Delay em ms para mostrar "gravando..." antes de enviar
   */
  async sendAudioWithPresence(
    phone: string,
    audioUrl: string,
    ptt: boolean = true,
    recordingDelay: number = 0,
    instanceName?: string
  ): Promise<EvolutionSendMessageResponse> {
    const name = instanceName || this.instanceName;
    if (!name) throw new Error('Instance name is required');

    const formattedPhone = this.formatPhoneNumber(phone);

    // Se tem delay, mostrar "gravando..." primeiro
    if (recordingDelay > 0) {
      await this.sendRecording(formattedPhone, recordingDelay, name);
      await new Promise(resolve => setTimeout(resolve, recordingDelay));
    }

    this.logger.info('Sending audio with presence', { to: formattedPhone, ptt, recordingDelay });

    try {
      // Evolution usa endpoint específico para áudio WhatsApp (PTT)
      const response = await this.client.post(`/message/sendWhatsAppAudio/${name}`, {
        number: formattedPhone,
        audioMessage: {
          audio: audioUrl,
        },
        options: {
          delay: 0,
          presence: 'recording',
        },
      });
      return response.data;
    } catch (error) {
      this.logger.error('Error sending audio with presence', error);
      throw this.handleError(error, 'sendAudioWithPresence');
    }
  }

  // ==========================================================================
  // CHAT
  // ==========================================================================

  /**
   * Busca chats da instância
   */
  async fetchChats(instanceName?: string): Promise<any[]> {
    const name = instanceName || this.instanceName;
    if (!name) throw new Error('Instance name is required');

    try {
      const response = await this.client.post(`/chat/findChats/${name}`, {});
      return response.data;
    } catch (error) {
      this.logger.error('Error fetching chats', error);
      throw this.handleError(error, 'fetchChats');
    }
  }

  /**
   * Busca mensagens de um chat
   */
  async fetchMessages(phone: string, count: number = 20, instanceName?: string): Promise<any[]> {
    const name = instanceName || this.instanceName;
    if (!name) throw new Error('Instance name is required');

    const formattedPhone = this.formatPhoneNumber(phone);

    try {
      const response = await this.client.post(`/chat/findMessages/${name}`, {
        where: {
          key: {
            remoteJid: formattedPhone + '@s.whatsapp.net',
          },
        },
        limit: count,
      });
      return response.data;
    } catch (error) {
      this.logger.error('Error fetching messages', error);
      throw this.handleError(error, 'fetchMessages');
    }
  }

  // ==========================================================================
  // HELPERS
  // ==========================================================================

  private formatPhoneNumber(phone: string): string {
    // Remove tudo que não é número
    let cleaned = phone.replace(/\D/g, '');

    // Remove @s.whatsapp.net se presente
    cleaned = cleaned.replace('@s.whatsapp.net', '');

    // Adiciona 55 se não tiver código do país
    if (cleaned.length <= 11 && !cleaned.startsWith('55')) {
      cleaned = '55' + cleaned;
    }

    return cleaned;
  }

  private handleError(error: unknown, operation: string): Error {
    if (axios.isAxiosError(error)) {
      const status = error.response?.status;
      const message = error.response?.data?.response?.message ||
                      error.response?.data?.message ||
                      error.message;

      return new Error(`[EvolutionClient] ${operation} failed (${status}): ${Array.isArray(message) ? message.join(', ') : message}`);
    }

    return error instanceof Error ? error : new Error(String(error));
  }
}

// ============================================================================
// FACTORY FUNCTION
// ============================================================================

export function createEvolutionClient(config: EvolutionConfig): EvolutionClient {
  return new EvolutionClient(config);
}

export default EvolutionClient;
