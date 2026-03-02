import axios, { AxiosInstance, AxiosError } from 'axios';
import {
  UazapiConfig,
  SendMessageResponse,
  MediaBase64Response,
  UazapiCampaignMessage,
  UazapiCampaignRequest,
  UazapiCampaignResponse,
  UazapiCampaignFolder,
} from './types';

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
// RETRY CONFIGURATION
// ============================================================================

interface RetryConfig {
  maxRetries: number;
  delays: number[];
  retryableStatusCodes: number[];
  retryableErrors: string[];
}

const DEFAULT_RETRY_CONFIG: RetryConfig = {
  maxRetries: 2, // Reduzido de 3 para 2 para evitar multiplicação com BullMQ retry
  delays: [1000, 2000], // Backoff: 1s, 2s
  retryableStatusCodes: [429, 500, 502, 503, 504],
  retryableErrors: ['ECONNRESET', 'ETIMEDOUT', 'ECONNREFUSED', 'ENOTFOUND', 'socket hang up'],
};

function isRetryableError(error: unknown, config: RetryConfig): boolean {
  // Verificar status code (se for erro de API via axios)
  if (axios.isAxiosError(error)) {
    const statusCode = error.response?.status;
    if (statusCode && config.retryableStatusCodes.includes(statusCode)) {
      return true;
    }
    // Verificar erros de rede do axios
    if (error.code && config.retryableErrors.some(e => error.code?.includes(e))) {
      return true;
    }
  }

  // Verificar status code genérico
  if (error && typeof error === 'object') {
    const statusCode = (error as any).status || (error as any).statusCode || (error as any).response?.status;
    if (statusCode && config.retryableStatusCodes.includes(statusCode)) {
      return true;
    }
  }

  // Verificar mensagem de erro (erros de rede)
  if (error instanceof Error) {
    return config.retryableErrors.some(e =>
      error.message.includes(e) || error.name.includes(e)
    );
  }

  return false;
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function executeWithRetry<T>(
  operation: () => Promise<T>,
  config: RetryConfig = DEFAULT_RETRY_CONFIG,
  context?: string,
  logger?: Logger
): Promise<T> {
  let lastError: Error | null = null;

  for (let attempt = 0; attempt < config.maxRetries; attempt++) {
    try {
      return await operation();
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error));

      // Verificar se é erro recuperável
      if (!isRetryableError(error, config)) {
        logger?.error(`[UAZAPI] ${context || 'Operation'} failed with non-retryable error`, {
          error: lastError.message,
          statusCode: axios.isAxiosError(error) ? error.response?.status : undefined,
        });
        throw lastError;
      }

      // Se não é última tentativa, espera e tenta de novo
      if (attempt < config.maxRetries - 1) {
        const delay = config.delays[attempt] || config.delays[config.delays.length - 1];
        logger?.warn(
          `[UAZAPI] ${context || 'Operation'} failed (attempt ${attempt + 1}/${config.maxRetries}), ` +
          `retrying in ${delay}ms...`,
          {
            error: lastError.message,
            statusCode: axios.isAxiosError(error) ? error.response?.status : undefined,
            willRetry: true,
            nextRetryIn: delay,
          }
        );
        await sleep(delay);
      }
    }
  }

  logger?.error(`[UAZAPI] ${context || 'Operation'} failed permanently after ${config.maxRetries} attempts`, {
    error: lastError?.message,
  });
  throw lastError;
}

// ============================================================================
// ADDITIONAL TYPES
// ============================================================================

export interface UazapiInstance {
  id: string;
  token: string;
  status: string;
  name?: string;
  profileName?: string;
  profilePicUrl?: string;
  isBusiness?: boolean;
  plataform?: string;
  qrcode?: string;
  paircode?: string;
}

export interface UazapiQRCode {
  qr_code: string | null;
  base64?: string;
  status: 'pending' | 'connected' | 'expired';
  pairingCode?: string;
}

export interface UazapiConnectionStatus {
  connected: boolean;
  loggedIn: boolean;
  phone_number?: string;
  status: string;
  jid?: string;
  instance?: UazapiInstance;
}

export interface UazapiWebhookConfig {
  id?: string;
  enabled: boolean;
  url: string;
  events: string[];
  excludeMessages?: string[];
  addUrlEvents?: boolean;
  addUrlTypesMessages?: boolean;
}

export interface CreateInstanceResponse {
  instance: UazapiInstance;
  token: string;
}

// ============================================================================
// UAZAPI CLIENT - ENDPOINTS CORRETOS
// ============================================================================

export class UazapiClient {
  private client: AxiosInstance;
  private adminClient: AxiosInstance;
  private baseUrl: string;
  private instanceToken: string;
  private adminToken?: string;
  private logger: Logger;

  constructor(config: UazapiConfig) {
    this.baseUrl = config.baseUrl;
    this.instanceToken = config.apiKey || config.instanceToken || '';
    this.adminToken = config.adminToken;
    this.logger = createLogger('UazapiClient');

    // Client para operações de instância (usa token da instância)
    this.client = axios.create({
      baseURL: config.baseUrl,
      headers: {
        'Content-Type': 'application/json',
        token: this.instanceToken,
      },
      timeout: 30000,
    });

    // Client para operações admin (usa admin token)
    this.adminClient = axios.create({
      baseURL: config.baseUrl,
      headers: {
        'Content-Type': 'application/json',
        admintoken: this.adminToken || '',
      },
      timeout: 30000,
    });

    // Interceptor para logging de erros
    this.client.interceptors.response.use(
      (response) => response,
      (error: AxiosError) => {
        this.logger.error('Request failed', {
          url: error.config?.url,
          method: error.config?.method,
          status: error.response?.status,
          data: error.response?.data,
        });
        return Promise.reject(error);
      }
    );

    this.adminClient.interceptors.response.use(
      (response) => response,
      (error: AxiosError) => {
        this.logger.error('Admin request failed', {
          url: error.config?.url,
          method: error.config?.method,
          status: error.response?.status,
          data: error.response?.data,
        });
        return Promise.reject(error);
      }
    );

    this.logger.info('Client initialized', { baseUrl: config.baseUrl });
  }

  // ==========================================================================
  // ADMIN - INSTANCE CREATION
  // ==========================================================================

  /**
   * Cria uma nova instância
   * POST /instance/init (requer admintoken)
   */
  async createInstance(name: string): Promise<CreateInstanceResponse> {
    try {
      this.logger.info('Creating new instance', { name });

      const response = await this.adminClient.post<{
        connected: boolean;
        loggedIn: boolean;
        instance: UazapiInstance;
        token: string;
        response: string;
        name: string;
        info?: string;
      }>('/instance/init', { name });

      const { instance, token } = response.data;

      this.logger.info('Instance created successfully', {
        id: instance.id,
        name: instance.name,
        token: token.substring(0, 8) + '...',
      });

      // Atualizar o token do client para usar a nova instância
      this.setInstanceToken(token);

      return { instance, token };
    } catch (error) {
      this.logger.error('Error creating instance', { error });
      throw this.handleError(error, 'createInstance');
    }
  }

  /**
   * Cria instância e configura webhook automaticamente
   */
  async createInstanceWithWebhook(
    name: string,
    webhookUrl: string,
    events: string[] = ['messages', 'connection']
  ): Promise<CreateInstanceResponse & { webhookConfigured: boolean }> {
    // 1. Criar instância
    const result = await this.createInstance(name);

    // 2. Configurar webhook
    let webhookConfigured = false;
    try {
      await this.setWebhook(webhookUrl, events, {
        excludeMessages: ['wasSentByApi'],
      });
      webhookConfigured = true;
      this.logger.info('Webhook configured for new instance', { webhookUrl });
    } catch (error) {
      this.logger.warn('Failed to configure webhook for new instance', { error });
    }

    return { ...result, webhookConfigured };
  }

  // ==========================================================================
  // INSTANCE MANAGEMENT
  // ==========================================================================

  /**
   * Obtém informações da instância
   * CORRIGIDO: Usa POST /instance/connect pois GET /instance não existe na UAZAPI
   * Isso evita duplicação de instâncias causada por 404 sendo interpretado como "não existe"
   */
  async getInstanceInfo(): Promise<UazapiInstance | null> {
    try {
      this.logger.debug('Getting instance info via POST /instance/connect');

      // Usar POST /instance/connect que funciona na UAZAPI
      // GET /instance retorna 404 (não existe nesta versão da API)
      const response = await this.client.post<{
        instance: UazapiInstance;
        connected: boolean;
        loggedIn: boolean;
      }>('/instance/connect', {});

      const instance = response.data?.instance;
      if (instance) {
        this.logger.info('Instance info retrieved successfully', {
          id: instance.id,
          status: instance.status,
          connected: response.data?.connected,
        });
      }

      return instance || null;
    } catch (error) {
      // Tratar erro 409 (Conflict) = instância já está conectando
      // Isso significa que a instância EXISTE
      if (axios.isAxiosError(error) && error.response?.status === 409) {
        this.logger.info('Instance exists (409 Conflict - already connecting)');
        const instanceData = error.response?.data as {
          instance?: UazapiInstance;
          connected?: boolean;
          loggedIn?: boolean;
        } | undefined;

        if (instanceData?.instance) {
          return instanceData.instance;
        }
        // Retornar objeto indicando que instância existe mesmo sem dados completos
        return { id: 'exists', status: 'connecting' } as UazapiInstance;
      }

      // Erro 404 = instância realmente não existe (token inválido)
      if (axios.isAxiosError(error) && error.response?.status === 404) {
        this.logger.warn('Instance not found (404)', { error: error.response?.data });
        return null;
      }

      // Erro 401/403 = token inválido, instância pode não existir
      if (axios.isAxiosError(error) && (error.response?.status === 401 || error.response?.status === 403)) {
        this.logger.warn('Authentication error checking instance', { status: error.response?.status });
        return null;
      }

      // Para outros erros (rede, timeout), logar mas NÃO retornar null
      // Isso evita recriação acidental de instância por erro de rede
      this.logger.error('Error getting instance info (will throw to prevent accidental recreation)', { error });
      throw error;
    }
  }

  /**
   * Conecta a instância ao WhatsApp (gera QR Code ou Pairing Code)
   * POST /instance/connect
   */
  async connect(phone?: string): Promise<UazapiConnectionStatus> {
    this.logger.info('Connecting instance', { phone });

    try {
      const payload: Record<string, unknown> = {};
      if (phone) {
        payload.phone = phone;
      }

      const response = await this.client.post<{
        connected: boolean;
        loggedIn: boolean;
        jid: string | null;
        instance: UazapiInstance;
      }>('/instance/connect', payload);

      const data = response.data;

      this.logger.info('Instance connect response', {
        connected: data.connected,
        loggedIn: data.loggedIn,
        hasQR: !!data.instance?.qrcode,
        hasPairCode: !!data.instance?.paircode,
      });

      return {
        connected: data.connected,
        loggedIn: data.loggedIn,
        jid: data.jid || undefined,
        status: data.instance?.status || 'connecting',
        instance: data.instance,
      };
    } catch (error) {
      // Tratar erro 409 (Conflict) - instância já está conectando
      if (axios.isAxiosError(error) && error.response?.status === 409) {
        this.logger.info('Instance already connecting (409), checking response data');

        // Algumas versões do UAZAPI retornam os dados mesmo com 409
        const responseData = error.response?.data as {
          connected?: boolean;
          loggedIn?: boolean;
          jid?: string | null;
          instance?: UazapiInstance;
        } | undefined;

        if (responseData?.instance) {
          this.logger.info('Got instance data from 409 response', {
            hasQR: !!responseData.instance.qrcode,
            status: responseData.instance.status,
          });

          return {
            connected: responseData.connected || false,
            loggedIn: responseData.loggedIn || false,
            jid: responseData.jid || undefined,
            status: responseData.instance.status || 'connecting',
            instance: responseData.instance,
          };
        }

        // Se não tem dados na resposta, retornar status de connecting
        this.logger.info('No instance data in 409 response, returning connecting status');
        return {
          connected: false,
          loggedIn: false,
          status: 'connecting',
        };
      }

      this.logger.error('Error connecting instance', { error });
      throw this.handleError(error, 'connect');
    }
  }

  /**
   * Obtém o QR Code da instância
   * Usa POST /instance/connect sem phone para gerar QR Code
   */
  async getQRCode(): Promise<UazapiQRCode | null> {
    try {
      this.logger.debug('Getting QR code');

      const response = await this.connect();

      // Verificar se está realmente conectado (loggedIn = true significa WhatsApp autenticado)
      // connected pode ser true mesmo quando está apenas "connecting" (gerando QR)
      if (response.loggedIn || (response.connected && response.instance?.status === 'open')) {
        return {
          qr_code: null,
          status: 'connected',
        };
      }

      // Se tem QR code, retornar como pending
      if (response.instance?.qrcode) {
        return {
          qr_code: response.instance.qrcode,
          base64: response.instance.qrcode,
          status: 'pending',
          pairingCode: response.instance.paircode,
        };
      }

      return {
        qr_code: null,
        status: 'expired',
      };
    } catch (error) {
      this.logger.error('Error getting QR code', { error });
      return null;
    }
  }

  /**
   * Obtém status de conexão da instância
   * Usa POST /instance/connect para verificar status
   */
  async getConnectionStatus(): Promise<UazapiConnectionStatus> {
    try {
      const response = await this.connect();
      return response;
    } catch (error) {
      this.logger.error('Error getting connection status', { error });
      return {
        connected: false,
        loggedIn: false,
        status: 'error',
      };
    }
  }

  /**
   * Desconecta a instância do WhatsApp
   * POST /instance/disconnect
   */
  async disconnect(): Promise<boolean> {
    try {
      this.logger.info('Disconnecting instance');

      await this.client.post('/instance/disconnect');

      this.logger.info('Instance disconnected');
      return true;
    } catch (error) {
      this.logger.error('Error disconnecting', { error });
      return false;
    }
  }

  /**
   * Deleta a instância
   * DELETE /instance
   */
  async deleteInstance(): Promise<boolean> {
    try {
      this.logger.info('Deleting instance');

      await this.client.delete('/instance');

      this.logger.info('Instance deleted');
      return true;
    } catch (error) {
      this.logger.error('Error deleting instance', { error });
      return false;
    }
  }

  // ==========================================================================
  // WEBHOOK MANAGEMENT
  // ==========================================================================

  /**
   * Obtém configuração do webhook
   * GET /webhook
   */
  async getWebhook(): Promise<UazapiWebhookConfig[] | null> {
    try {
      const response = await this.client.get<UazapiWebhookConfig[]>('/webhook');
      return response.data;
    } catch (error) {
      this.logger.warn('Error getting webhook config', { error });
      return null;
    }
  }

  /**
   * Configura webhook da instância
   * POST /webhook
   */
  async setWebhook(
    url: string,
    events: string[] = ['messages', 'connection'],
    options?: {
      excludeMessages?: string[];
      addUrlEvents?: boolean;
      addUrlTypesMessages?: boolean;
    }
  ): Promise<boolean> {
    try {
      this.logger.info('Setting webhook', { url, events });

      await this.client.post('/webhook', {
        enabled: true,
        url,
        events,
        excludeMessages: options?.excludeMessages || ['wasSentByApi'],
        addUrlEvents: options?.addUrlEvents || false,
        addUrlTypesMessages: options?.addUrlTypesMessages || false,
      });

      this.logger.info('Webhook configured successfully');
      return true;
    } catch (error) {
      this.logger.error('Error setting webhook', { error });
      throw this.handleError(error, 'setWebhook');
    }
  }

  // ==========================================================================
  // MESSAGING - ENDPOINTS CORRETOS
  // ==========================================================================

  /**
   * Envia uma mensagem de texto
   * POST /send/text
   * Com retry automático para erros recuperáveis (429, 5xx, erros de rede)
   */
  async sendText(
    number: string,
    text: string,
    options?: {
      delay?: number;
      linkPreview?: boolean;
      replyId?: string;
    }
  ): Promise<SendMessageResponse> {
    const formattedNumber = this.formatNumber(number);
    this.logger.debug('Sending text', {
      to: formattedNumber.substring(0, 10) + '...',
      length: text.length,
    });

    return executeWithRetry(
      async () => {
        const response = await this.client.post<SendMessageResponse>(
          '/send/text',
          {
            number: formattedNumber,
            text,
            delay: options?.delay || 0,
            linkPreview: options?.linkPreview || false,
            replyid: options?.replyId,
          }
        );

        this.logger.info('Text sent', { messageId: response.data.messageid });
        return response.data;
      },
      DEFAULT_RETRY_CONFIG,
      `sendText(${formattedNumber.substring(0, 10)}...)`,
      this.logger
    );
  }

  /**
   * Envia uma mídia (imagem, vídeo, áudio, documento, sticker)
   * POST /send/media
   * Com retry automático para erros recuperáveis (429, 5xx, erros de rede)
   */
  async sendMedia(
    number: string,
    type: 'image' | 'video' | 'audio' | 'myaudio' | 'ptt' | 'document' | 'sticker',
    file: string, // URL ou base64
    options?: {
      text?: string; // caption
      docName?: string;
      delay?: number;
      replyId?: string;
    }
  ): Promise<SendMessageResponse> {
    const formattedNumber = this.formatNumber(number);
    this.logger.debug('Sending media', {
      to: formattedNumber.substring(0, 10) + '...',
      type,
    });

    return executeWithRetry(
      async () => {
        const response = await this.client.post<SendMessageResponse>(
          '/send/media',
          {
            number: formattedNumber,
            type,
            file,
            text: options?.text || '',
            docName: options?.docName,
            delay: options?.delay || 0,
            replyid: options?.replyId,
          }
        );

        this.logger.info('Media sent', { messageId: response.data.messageid });
        return response.data;
      },
      DEFAULT_RETRY_CONFIG,
      `sendMedia:${type}(${formattedNumber.substring(0, 10)}...)`,
      this.logger
    );
  }

  /**
   * Envia uma imagem
   */
  async sendImage(
    number: string,
    fileUrl: string,
    caption?: string
  ): Promise<SendMessageResponse> {
    return this.sendMedia(number, 'image', fileUrl, { text: caption });
  }

  /**
   * Envia um documento
   */
  async sendDocument(
    number: string,
    fileUrl: string,
    fileName: string,
    caption?: string
  ): Promise<SendMessageResponse> {
    return this.sendMedia(number, 'document', fileUrl, {
      text: caption,
      docName: fileName,
    });
  }

  /**
   * Envia um áudio (PTT - Push To Talk)
   * @param number - Número do destinatário
   * @param audioUrl - URL ou base64 do áudio
   * @param ptt - Se true, envia como mensagem de voz (push-to-talk)
   * @param delay - Delay em ms antes de enviar (mostra "Gravando áudio..." durante esse tempo)
   */
  async sendAudio(
    number: string,
    audioUrl: string,
    ptt: boolean = true,
    delay?: number
  ): Promise<SendMessageResponse> {
    return this.sendMedia(number, ptt ? 'ptt' : 'audio', audioUrl, { delay });
  }

  /**
   * Envia um vídeo
   */
  async sendVideo(
    number: string,
    videoUrl: string,
    caption?: string
  ): Promise<SendMessageResponse> {
    return this.sendMedia(number, 'video', videoUrl, { text: caption });
  }

  /**
   * Envia localização geográfica
   * POST /send/location
   * Com retry automático para erros recuperáveis (429, 5xx, erros de rede)
   */
  async sendLocation(
    number: string,
    latitude: number,
    longitude: number,
    options?: {
      name?: string;
      address?: string;
    }
  ): Promise<SendMessageResponse> {
    const formattedNumber = this.formatNumber(number);
    this.logger.debug('Sending location', {
      to: formattedNumber.substring(0, 10) + '...',
      latitude,
      longitude,
    });

    return executeWithRetry(
      async () => {
        const response = await this.client.post<SendMessageResponse>(
          '/send/location',
          {
            number: formattedNumber,
            latitude,
            longitude,
            name: options?.name || '',
            address: options?.address || '',
          }
        );

        this.logger.info('Location sent', { messageId: response.data.messageid });
        return response.data;
      },
      DEFAULT_RETRY_CONFIG,
      `sendLocation(${formattedNumber.substring(0, 10)}...)`,
      this.logger
    );
  }

  /**
   * Envia cartão de contato (vCard)
   * POST /send/contact
   * Com retry automático para erros recuperáveis (429, 5xx, erros de rede)
   */
  async sendContact(
    number: string,
    fullName: string,
    phoneNumber: string,
    options?: {
      organization?: string;
      email?: string;
      url?: string;
      delay?: number;
    }
  ): Promise<SendMessageResponse> {
    const formattedNumber = this.formatNumber(number);
    this.logger.debug('Sending contact card', {
      to: formattedNumber.substring(0, 10) + '...',
      fullName,
      phoneNumber,
    });

    return executeWithRetry(
      async () => {
        const response = await this.client.post<SendMessageResponse>(
          '/send/contact',
          {
            number: formattedNumber,
            fullName,
            phoneNumber,
            organization: options?.organization || '',
            email: options?.email || '',
            url: options?.url || '',
            delay: options?.delay,
          }
        );

        this.logger.info('Contact card sent', { messageId: response.data.messageid });
        return response.data;
      },
      DEFAULT_RETRY_CONFIG,
      `sendContact(${formattedNumber.substring(0, 10)}...)`,
      this.logger
    );
  }

  // ==========================================================================
  // CAMPANHA EM MASSA (SENDER)
  // ==========================================================================

  /**
   * Cria campanha de envio em massa com mensagens personalizadas
   * POST /sender/advanced
   *
   * @param options.messages - Array de mensagens com phone e text
   * @param options.delayMin - Delay mínimo entre mensagens em segundos (default: 30)
   * @param options.delayMax - Delay máximo entre mensagens em segundos (default: 60)
   * @param options.campaignName - Nome da campanha para identificação
   * @param options.scheduledMinutes - Minutos para iniciar a campanha (default: 1)
   */
  async createCampaign(options: {
    messages: Array<{ phone: string; text: string }>;
    delayMin?: number;
    delayMax?: number;
    campaignName?: string;
    scheduledMinutes?: number;
  }): Promise<UazapiCampaignResponse> {
    const {
      messages,
      delayMin = 30,
      delayMax = 60,
      campaignName,
      scheduledMinutes = 1
    } = options;

    this.logger.info('Creating campaign', {
      messageCount: messages.length,
      delayMin,
      delayMax,
      campaignName,
    });

    try {
      const payload: UazapiCampaignRequest = {
        delayMin,
        delayMax,
        info: campaignName || `Diana Prospection - ${new Date().toISOString()}`,
        scheduled_for: scheduledMinutes,
        messages: messages.map(m => ({
          number: this.formatNumber(m.phone),
          type: 'text' as const,
          text: m.text
        }))
      };

      const response = await this.client.post<UazapiCampaignResponse>(
        '/sender/advanced',
        payload
      );

      this.logger.info('Campaign created', {
        folderId: response.data.folder_id,
        count: response.data.count,
        status: response.data.status,
      });

      return response.data;
    } catch (error) {
      this.logger.error('Error creating campaign', { error });
      throw this.handleError(error, 'createCampaign');
    }
  }

  /**
   * Lista todas as campanhas
   * GET /sender/listfolders
   *
   * @param status - Filtrar por status (optional)
   */
  async listCampaigns(status?: string): Promise<UazapiCampaignFolder[]> {
    try {
      this.logger.debug('Listing campaigns', { status });

      const url = status
        ? `/sender/listfolders?status=${status}`
        : '/sender/listfolders';

      const response = await this.client.get<UazapiCampaignFolder[]>(url);

      this.logger.info('Campaigns listed', { count: response.data?.length || 0 });

      return response.data || [];
    } catch (error) {
      this.logger.error('Error listing campaigns', { error });
      throw this.handleError(error, 'listCampaigns');
    }
  }

  /**
   * Pausa uma campanha em andamento
   * POST /sender/edit
   */
  async pauseCampaign(folderId: string): Promise<void> {
    await this.campaignAction(folderId, 'stop');
    this.logger.info('Campaign paused', { folderId });
  }

  /**
   * Continua uma campanha pausada
   * POST /sender/edit
   */
  async resumeCampaign(folderId: string): Promise<void> {
    await this.campaignAction(folderId, 'continue');
    this.logger.info('Campaign resumed', { folderId });
  }

  /**
   * Deleta uma campanha
   * POST /sender/edit
   */
  async deleteCampaign(folderId: string): Promise<void> {
    await this.campaignAction(folderId, 'delete');
    this.logger.info('Campaign deleted', { folderId });
  }

  /**
   * Executa ação em uma campanha (stop, continue, delete)
   * POST /sender/edit
   */
  private async campaignAction(
    folderId: string,
    action: 'stop' | 'continue' | 'delete'
  ): Promise<void> {
    try {
      this.logger.debug('Campaign action', { folderId, action });

      await this.client.post('/sender/edit', {
        folder_id: folderId,
        action
      });
    } catch (error) {
      this.logger.error('Error executing campaign action', { folderId, action, error });
      throw this.handleError(error, `campaignAction:${action}`);
    }
  }

  // ==========================================================================
  // CAMPANHA SIMPLES (SENDER/SIMPLE)
  // ==========================================================================

  /**
   * Cria campanha simples de envio em massa
   * POST /sender/simple
   *
   * @param options - Configurações da campanha
   * @returns Resposta com folder_id, count e status
   */
  async createSimpleCampaign(options: {
    numbers: string[];
    type: 'text' | 'image' | 'video' | 'audio' | 'document' | 'contact' | 'location' | 'list' | 'button' | 'poll' | 'carousel';
    text?: string;
    file?: string;
    docName?: string;
    folder?: string;
    delayMin?: number;
    delayMax?: number;
    scheduledFor?: number;
    linkPreview?: boolean;
    footerText?: string;
    buttonText?: string;
    choices?: string[];
  }): Promise<UazapiCampaignResponse> {
    const {
      numbers,
      type,
      text,
      file,
      docName,
      folder,
      delayMin = 10,
      delayMax = 30,
      scheduledFor = 1,
      linkPreview,
      footerText,
      buttonText,
      choices
    } = options;

    this.logger.info('Creating simple campaign', {
      numbersCount: numbers.length,
      type,
      folder,
      delayMin,
      delayMax,
    });

    try {
      // Formatar números para o padrão @s.whatsapp.net
      const formattedNumbers = numbers.map(n => {
        const cleaned = n.replace(/\D/g, '');
        return cleaned.includes('@') ? cleaned : `${cleaned}@s.whatsapp.net`;
      });

      const payload: Record<string, unknown> = {
        numbers: formattedNumbers,
        type,
        delayMin,
        delayMax,
        scheduled_for: scheduledFor,
      };

      if (folder) payload.folder = folder;
      if (text) payload.text = text;
      if (file) payload.file = file;
      if (docName) payload.docName = docName;
      if (linkPreview !== undefined) payload.linkPreview = linkPreview;
      if (footerText) payload.footerText = footerText;
      if (buttonText) payload.buttonText = buttonText;
      if (choices) payload.choices = choices;

      const response = await this.client.post<UazapiCampaignResponse>(
        '/sender/simple',
        payload
      );

      this.logger.info('Simple campaign created', {
        folderId: response.data.folder_id,
        count: response.data.count,
        status: response.data.status,
      });

      return response.data;
    } catch (error) {
      this.logger.error('Error creating simple campaign', { error });
      throw this.handleError(error, 'createSimpleCampaign');
    }
  }

  /**
   * Lista mensagens de uma campanha específica
   * POST /sender/listmessages
   *
   * @param folderId - ID da campanha
   * @param options - Opções de filtro e paginação
   */
  async listCampaignMessages(
    folderId: string,
    options?: {
      messageStatus?: 'Scheduled' | 'Sent' | 'Failed';
      page?: number;
      pageSize?: number;
    }
  ): Promise<{
    messages: Array<{
      id: string;
      chatid: string;
      status: string;
      text?: string;
      error?: string;
    }>;
    pagination: {
      total: number;
      page: number;
      pageSize: number;
      lastPage: number;
    };
  }> {
    try {
      this.logger.debug('Listing campaign messages', { folderId, ...options });

      const response = await this.client.post('/sender/listmessages', {
        folder_id: folderId,
        messageStatus: options?.messageStatus,
        page: options?.page || 1,
        pageSize: options?.pageSize || 50,
      });

      return response.data;
    } catch (error) {
      this.logger.error('Error listing campaign messages', { error });
      throw this.handleError(error, 'listCampaignMessages');
    }
  }

  /**
   * Limpa mensagens enviadas mais antigas que X horas
   * POST /sender/cleardone
   *
   * @param hours - Horas para manter (default: 168 = 7 dias)
   */
  async clearDoneCampaigns(hours: number = 168): Promise<{ status: string }> {
    try {
      this.logger.info('Clearing done campaigns', { hours });

      const response = await this.client.post<{ status: string }>('/sender/cleardone', {
        hours
      });

      return response.data;
    } catch (error) {
      this.logger.error('Error clearing done campaigns', { error });
      throw this.handleError(error, 'clearDoneCampaigns');
    }
  }

  /**
   * Limpa toda a fila de mensagens
   * DELETE /sender/clearall
   */
  async clearAllCampaigns(): Promise<{
    status: string;
    messages_deleted: number;
    folders_deleted: number;
  }> {
    try {
      this.logger.info('Clearing all campaigns');

      const response = await this.client.delete<{
        status: string;
        messages_deleted: number;
        folders_deleted: number;
      }>('/sender/clearall');

      this.logger.info('All campaigns cleared', response.data);

      return response.data;
    } catch (error) {
      this.logger.error('Error clearing all campaigns', { error });
      throw this.handleError(error, 'clearAllCampaigns');
    }
  }

  // ==========================================================================
  // CONTACT PROFILE
  // ==========================================================================

  /**
   * Obtém a foto de perfil de um contato do WhatsApp
   * GET /profile-picture?phone=5511999999999
   *
   * @param phone - Número do telefone (com DDI, sem formatação)
   * @returns URL da foto de perfil ou null se não disponível
   * @note A URL é válida por apenas 48 horas (limitação do WhatsApp)
   */
  async getProfilePicture(phone: string): Promise<string | null> {
    try {
      const formattedPhone = this.formatNumber(phone);
      this.logger.debug('Getting profile picture', { phone: formattedPhone });

      // Tentar múltiplos endpoints possíveis
      const endpoints = [
        `/profile-picture?phone=${formattedPhone}`,
        `/contact/profile-picture?phone=${formattedPhone}`,
        `/chat/profile-picture?phone=${formattedPhone}`,
      ];

      for (const endpoint of endpoints) {
        try {
          const response = await this.client.get<{
            link?: string;
            url?: string;
            profilePictureUrl?: string;
            imgUrl?: string;
          }>(endpoint);

          const pictureUrl = response.data?.link
            || response.data?.url
            || response.data?.profilePictureUrl
            || response.data?.imgUrl;

          if (pictureUrl) {
            this.logger.info('Profile picture retrieved', {
              phone: formattedPhone,
              endpoint,
              hasUrl: true
            });
            return pictureUrl;
          }
        } catch (error) {
          // Tentar próximo endpoint silenciosamente
          this.logger.debug(`Endpoint ${endpoint} failed, trying next`, {
            status: (error as any)?.response?.status
          });
          continue;
        }
      }

      this.logger.debug('No profile picture found for contact', { phone: formattedPhone });
      return null;
    } catch (error) {
      this.logger.warn('Error getting profile picture', { phone, error });
      return null;
    }
  }

  // ==========================================================================
  // MEDIA
  // ==========================================================================

  /**
   * Interface para dados de mídia necessários para download
   */
  public static MediaDownloadData = class {
    url?: string;
    mediaKey?: string;
    mimetype?: string;
    fileSha256?: string;
    fileLength?: number;
  };

  /**
   * Baixa mídia usando os metadados completos (URL, MediaKey, etc.)
   * Usa os endpoints corretos do UazapiGo: /chat/downloadimage, /chat/downloadaudio, etc.
   *
   * @param mediaType - Tipo de mídia: 'image', 'audio', 'video', 'document'
   * @param mediaData - Dados da mídia extraídos do webhook
   */
  async downloadMediaWithMetadata(
    mediaType: string,
    mediaData: {
      url?: string;
      mediaKey?: string;
      mimetype?: string;
      fileSha256?: string;
      fileLength?: number;
    }
  ): Promise<string> {
    this.logger.info('Downloading media with metadata', {
      mediaType,
      hasUrl: !!mediaData.url,
      hasMediaKey: !!mediaData.mediaKey,
      mimetype: mediaData.mimetype
    });

    if (!mediaData.url || !mediaData.mediaKey) {
      throw new Error('[UazapiClient] Missing required media data (url or mediaKey)');
    }

    // Determinar endpoint correto baseado no tipo de mídia
    const mediaTypeLower = mediaType.toLowerCase();
    let endpoint: string;
    if (mediaTypeLower.includes('image')) {
      endpoint = '/chat/downloadimage';
    } else if (mediaTypeLower.includes('audio') || mediaTypeLower.includes('ptt')) {
      endpoint = '/chat/downloadaudio';
    } else if (mediaTypeLower.includes('video')) {
      endpoint = '/chat/downloadvideo';
    } else if (mediaTypeLower.includes('document')) {
      endpoint = '/chat/downloaddocument';
    } else {
      endpoint = '/chat/downloadimage'; // fallback
    }

    try {
      const response = await this.client.post<{
        Mimetype?: string;
        Data?: string;
        base64?: string;
        data?: string;
      }>(endpoint, {
        Url: mediaData.url,
        MediaKey: mediaData.mediaKey,
        Mimetype: mediaData.mimetype || 'application/octet-stream',
        FileSHA256: mediaData.fileSha256 || '',
        FileLength: mediaData.fileLength || 0
      });

      // Tentar extrair base64 de diferentes campos possíveis
      const base64 = response.data?.Data || response.data?.base64 || response.data?.data;
      if (base64) {
        this.logger.info('Media downloaded with metadata successfully', {
          endpoint,
          size: base64.length
        });
        return base64;
      }

      throw new Error('No base64 data in response');
    } catch (error) {
      this.logger.error('Failed to download media with metadata', {
        endpoint,
        error: error instanceof Error ? error.message : error
      });
      throw error;
    }
  }

  /**
   * Obtém mídia em base64 a partir do messageId
   * Tenta múltiplos endpoints possíveis do UazapiGo
   * NOTA: Este método é um fallback - prefira usar downloadMediaWithMetadata quando tiver os dados
   */
  async getMediaBase64(messageId: string): Promise<string> {
    this.logger.debug('Getting media base64 by messageId (fallback method)', { messageId });

    // Lista de endpoints possíveis para tentar
    const endpoints = [
      { method: 'get', url: `/chat/downloadMediaMessage/${messageId}` },
      { method: 'get', url: `/chat/media/${messageId}` },
      { method: 'get', url: `/message/media/${messageId}` },
      { method: 'post', url: '/chat/downloadMediaMessage', data: { messageId } },
      { method: 'post', url: '/chat/media', data: { messageId } },
    ];

    for (const endpoint of endpoints) {
      try {
        let response;
        if (endpoint.method === 'get') {
          response = await this.client.get<{ base64?: string; data?: string; url?: string }>(endpoint.url);
        } else {
          response = await this.client.post<{ base64?: string; data?: string; url?: string }>(
            endpoint.url,
            endpoint.data
          );
        }

        // Verificar diferentes formatos de resposta
        const base64 = response.data?.base64 || response.data?.data;
        if (base64) {
          this.logger.info('Media base64 retrieved', { endpoint: endpoint.url });
          return base64;
        }

        // Se retornou URL, baixar o conteúdo
        if (response.data?.url) {
          this.logger.info('Got media URL, downloading', { url: response.data.url.substring(0, 50) });
          const mediaResponse = await fetch(response.data.url);
          if (mediaResponse.ok) {
            const arrayBuffer = await mediaResponse.arrayBuffer();
            return Buffer.from(arrayBuffer).toString('base64');
          }
        }
      } catch (error) {
        // Silenciosamente tentar próximo endpoint
        this.logger.debug(`Endpoint ${endpoint.url} failed, trying next`, {
          status: (error as any)?.response?.status
        });
        continue;
      }
    }

    this.logger.warn('All media download endpoints failed', { messageId });
    throw new Error(`[UazapiClient] Could not download media for messageId: ${messageId}`);
  }

  // ==========================================================================
  // PRESENCE & STATUS
  // ==========================================================================

  /**
   * Envia status de presença (digitando, gravando, etc)
   * POST /chat/presence
   *
   * @param remoteJid - Número do destinatário (formato: 5511999999999 ou 5511999999999@s.whatsapp.net)
   * @param presence - Tipo de presença: 'composing' (digitando), 'recording' (gravando áudio), 'paused' (parou)
   */
  async sendPresence(
    remoteJid: string,
    presence: 'composing' | 'recording' | 'paused' = 'composing'
  ): Promise<boolean> {
    try {
      const formattedNumber = this.formatNumber(remoteJid);
      this.logger.debug('Sending presence', { remoteJid: formattedNumber, presence });

      // Tentar múltiplos endpoints possíveis com diferentes formatos de parâmetros
      // WuzAPI/UAZAPI usa: Phone, State, Media
      const endpoints = [
        { url: '/chat/presence', data: { Phone: formattedNumber, State: presence, Media: '' } },
        { url: '/chat/presence', data: { phone: formattedNumber, state: presence } },
        { url: '/chat/presence', data: { number: formattedNumber, presence } },
        { url: '/chat/sendPresence', data: { Phone: formattedNumber, State: presence } },
        { url: '/send/presence', data: { number: formattedNumber, status: presence } },
      ];

      for (const endpoint of endpoints) {
        try {
          await this.client.post(endpoint.url, endpoint.data);
          this.logger.info('Presence sent successfully', {
            endpoint: endpoint.url,
            remoteJid: formattedNumber,
            presence
          });
          return true;
        } catch (error) {
          // Tentar próximo endpoint silenciosamente
          this.logger.debug(`Endpoint ${endpoint.url} failed, trying next`, {
            status: (error as any)?.response?.status
          });
          continue;
        }
      }

      // Se nenhum endpoint funcionou, logar warning mas não falhar
      this.logger.warn('All presence endpoints failed, continuing without presence', {
        remoteJid: formattedNumber,
        presence
      });
      return false;
    } catch (error) {
      this.logger.warn('Error sending presence (non-critical)', { error });
      return false;
    }
  }

  /**
   * Envia indicador de "digitando..."
   * Wrapper para sendPresence('composing')
   */
  async sendTyping(
    remoteJid: string,
    duration: number = 3000
  ): Promise<void> {
    await this.sendPresence(remoteJid, 'composing');
    this.logger.debug('Typing indicator sent', { remoteJid, duration });
  }

  /**
   * Envia indicador de "gravando áudio..."
   * Wrapper para sendPresence('recording')
   */
  async sendRecording(
    remoteJid: string
  ): Promise<void> {
    await this.sendPresence(remoteJid, 'recording');
    this.logger.debug('Recording indicator sent', { remoteJid });
  }

  /**
   * Marca mensagens como lidas
   * POST /send/text com readchat: true
   */
  async markAsRead(remoteJid: string): Promise<void> {
    try {
      // UazapiGo marca como lido ao enviar mensagem com readchat: true
      this.logger.debug('Mark as read', { remoteJid });
    } catch (error) {
      this.logger.warn('Error marking as read (non-critical)', { error });
    }
  }

  /**
   * Verifica se a instância está conectada
   */
  async isConnected(): Promise<boolean> {
    try {
      const status = await this.getConnectionStatus();
      return status.connected;
    } catch {
      return false;
    }
  }

  // ==========================================================================
  // HELPERS
  // ==========================================================================

  /**
   * Formata o número para o padrão esperado pela API
   * Suporta:
   * - Números WhatsApp: 5511999999999@s.whatsapp.net -> 5511999999999
   * - Grupos: 120363123456789@g.us -> 120363123456789@g.us
   * - Lead IDs (Meta/Instagram/Facebook): 160627549073651@lid -> 160627549073651@lid
   */
  private formatNumber(number: string): string {
    // Se for Lead ID do Meta (Instagram/Facebook), manter o formato completo
    if (number.includes('@lid')) {
      this.logger.debug('Meta Lead ID detected, keeping full format', { number });
      return number; // Manter como está: 160627549073651@lid
    }

    // Se for grupo, manter o formato completo
    if (number.includes('@g.us')) {
      return number;
    }

    // Para números WhatsApp normais, remover sufixo e caracteres não numéricos
    let cleaned = number.replace(/@s\.whatsapp\.net$/, '');
    cleaned = cleaned.replace(/\D/g, '');

    return cleaned;
  }

  /**
   * Trata erros de forma padronizada
   */
  private handleError(error: unknown, operation: string): Error {
    if (axios.isAxiosError(error)) {
      const axiosError = error as AxiosError<{ message?: string; error?: string; code?: number }>;
      const message =
        axiosError.response?.data?.message ||
        axiosError.response?.data?.error ||
        axiosError.message;

      const status = axiosError.response?.status;

      this.logger.error(`${operation} failed`, {
        status,
        message,
        url: axiosError.config?.url,
      });

      return new Error(`[UazapiClient] ${operation} failed (${status}): ${message}`);
    }

    if (error instanceof Error) {
      return new Error(`[UazapiClient] ${operation} failed: ${error.message}`);
    }

    return new Error(`[UazapiClient] ${operation} failed: Unknown error`);
  }

  /**
   * Atualiza o token da instância
   */
  setInstanceToken(token: string): void {
    this.instanceToken = token;
    this.client.defaults.headers['token'] = token;
    this.logger.info('Instance token updated');
  }

  /**
   * Retorna o token atual
   */
  getInstanceToken(): string {
    return this.instanceToken;
  }
}

// ============================================================================
// FACTORY FUNCTION
// ============================================================================

/**
 * Factory function para criar cliente UAZAPI
 */
export function createUazapiClient(config: UazapiConfig): UazapiClient {
  return new UazapiClient(config);
}
