import axios, { AxiosInstance, AxiosError } from 'axios';
import {
  AsaasConfig,
  AsaasCustomer,
  CreateCustomerInput,
  UpdateCustomerInput,
  AsaasSubscription,
  CreateSubscriptionInput,
  UpdateSubscriptionInput,
  AsaasPaymentLink,
  CreatePaymentLinkInput,
  UpdatePaymentLinkInput,
  AsaasPayment,
  CreatePaymentInput,
  AsaasListResponse,
  AsaasError,
  ListPaymentsFilter,
  AsaasDocument,
  ASAAS_BASE_URL,
} from './types';

const MAX_RETRIES = 3;
const RETRY_DELAY_MS = 1000;

/**
 * Rate limiter para controlar requisições à API Asaas
 * Limite: 30 requisições por minuto (janela deslizante)
 */
class RateLimiter {
  private timestamps: number[] = [];
  private readonly maxRequests: number;
  private readonly windowMs: number;

  constructor(maxRequests = 30, windowMs = 60000) {
    this.maxRequests = maxRequests;
    this.windowMs = windowMs;
  }

  async acquire(): Promise<void> {
    const now = Date.now();
    // Remove timestamps fora da janela
    this.timestamps = this.timestamps.filter(t => now - t < this.windowMs);

    if (this.timestamps.length >= this.maxRequests) {
      const oldestTimestamp = this.timestamps[0];
      const waitTime = this.windowMs - (now - oldestTimestamp) + 100; // +100ms de margem
      console.log(`[Asaas] Rate limit interno atingido. Aguardando ${waitTime}ms... (${this.timestamps.length}/${this.maxRequests} req/min)`);
      await new Promise(resolve => setTimeout(resolve, waitTime));
      return this.acquire(); // Revalidar após espera
    }

    this.timestamps.push(now);
  }
}

export class AsaasClient {
  private client: AxiosInstance;
  private rateLimiter: RateLimiter;

  constructor(config: AsaasConfig) {
    this.rateLimiter = new RateLimiter(30, 60000); // 30 req/min
    const baseURL = config.baseUrl || ASAAS_BASE_URL;

    this.client = axios.create({
      baseURL,
      headers: {
        'Content-Type': 'application/json',
        access_token: config.apiKey,
      },
      timeout: 30000,
    });

    // Interceptor para logging de erros (sanitizado)
    this.client.interceptors.response.use(
      (response) => response,
      (error: AxiosError) => {
        // NUNCA logar response.data completo - pode conter dados de clientes
        // NUNCA logar headers - podem conter API keys
        console.error('[AsaasClient] Request failed:', {
          url: error.config?.url,
          method: error.config?.method,
          status: error.response?.status,
          // Logar apenas codigo de erro, NÃO dados sensíveis
          errorCode: (error.response?.data as { errors?: Array<{ code?: string }> })?.errors?.[0]?.code,
        });
        return Promise.reject(error);
      }
    );
  }

  // ============================================================================
  // CUSTOMER METHODS
  // ============================================================================

  /**
   * Cria um novo cliente
   */
  async createCustomer(input: CreateCustomerInput): Promise<AsaasCustomer> {
    return this.executeWithRetry(async () => {
      const response = await this.client.post<AsaasCustomer>('/customers', input);
      return response.data;
    });
  }

  /**
   * Obtém um cliente por ID
   */
  async getCustomer(id: string): Promise<AsaasCustomer | null> {
    try {
      const response = await this.client.get<AsaasCustomer>(`/customers/${id}`);
      return response.data;
    } catch (error) {
      if (this.isNotFoundError(error)) {
        return null;
      }
      throw this.handleError(error, 'getCustomer');
    }
  }

  /**
   * Busca cliente por email
   */
  async findCustomerByEmail(email: string): Promise<AsaasCustomer | null> {
    try {
      const response = await this.client.get<AsaasListResponse<AsaasCustomer>>(
        '/customers',
        { params: { email } }
      );

      if (response.data.data.length > 0) {
        return response.data.data[0];
      }
      return null;
    } catch (error) {
      throw this.handleError(error, 'findCustomerByEmail');
    }
  }

  /**
   * Busca cliente por CPF/CNPJ
   */
  async findCustomerByCpfCnpj(cpfCnpj: string): Promise<AsaasCustomer | null> {
    try {
      const response = await this.client.get<AsaasListResponse<AsaasCustomer>>(
        '/customers',
        { params: { cpfCnpj } }
      );

      if (response.data.data.length > 0) {
        return response.data.data[0];
      }
      return null;
    } catch (error) {
      throw this.handleError(error, 'findCustomerByCpfCnpj');
    }
  }

  /**
   * Atualiza um cliente
   */
  async updateCustomer(id: string, input: UpdateCustomerInput): Promise<AsaasCustomer> {
    return this.executeWithRetry(async () => {
      const response = await this.client.put<AsaasCustomer>(`/customers/${id}`, input);
      return response.data;
    });
  }

  /**
   * Lista clientes
   */
  async listCustomers(params?: { offset?: number; limit?: number }): Promise<AsaasListResponse<AsaasCustomer>> {
    try {
      const response = await this.client.get<AsaasListResponse<AsaasCustomer>>(
        '/customers',
        { params }
      );
      return response.data;
    } catch (error) {
      throw this.handleError(error, 'listCustomers');
    }
  }

  /**
   * Busca ou cria cliente por email
   */
  async getOrCreateCustomer(input: CreateCustomerInput): Promise<AsaasCustomer> {
    if (input.email) {
      const existing = await this.findCustomerByEmail(input.email);
      if (existing) {
        return existing;
      }
    }

    if (input.cpfCnpj) {
      const existing = await this.findCustomerByCpfCnpj(input.cpfCnpj);
      if (existing) {
        return existing;
      }
    }

    return this.createCustomer(input);
  }

  // ============================================================================
  // SUBSCRIPTION METHODS
  // ============================================================================

  /**
   * Cria uma nova assinatura
   */
  async createSubscription(input: CreateSubscriptionInput): Promise<AsaasSubscription> {
    return this.executeWithRetry(async () => {
      const response = await this.client.post<AsaasSubscription>('/subscriptions', input);
      return response.data;
    });
  }

  /**
   * Obtém uma assinatura por ID
   */
  async getSubscription(id: string): Promise<AsaasSubscription | null> {
    try {
      const response = await this.client.get<AsaasSubscription>(`/subscriptions/${id}`);
      return response.data;
    } catch (error) {
      if (this.isNotFoundError(error)) {
        return null;
      }
      throw this.handleError(error, 'getSubscription');
    }
  }

  /**
   * Lista todas as assinaturas de um cliente (com paginação automática)
   */
  async listSubscriptionsByCustomer(customerId: string): Promise<AsaasSubscription[]> {
    const allSubscriptions: AsaasSubscription[] = [];
    let offset = 0;
    const limit = 100;
    const maxPages = 10;

    try {
      for (let page = 0; page < maxPages; page++) {
        const response = await this.client.get<AsaasListResponse<AsaasSubscription>>(
          '/subscriptions',
          { params: { customer: customerId, offset, limit } }
        );
        allSubscriptions.push(...response.data.data);

        if (!response.data.hasMore) break;
        offset += limit;
      }
      return allSubscriptions;
    } catch (error) {
      throw this.handleError(error, 'listSubscriptionsByCustomer');
    }
  }

  /**
   * Atualiza uma assinatura
   */
  async updateSubscription(id: string, input: UpdateSubscriptionInput): Promise<AsaasSubscription> {
    return this.executeWithRetry(async () => {
      const response = await this.client.put<AsaasSubscription>(`/subscriptions/${id}`, input);
      return response.data;
    });
  }

  /**
   * Cancela uma assinatura
   */
  async cancelSubscription(id: string): Promise<void> {
    try {
      await this.client.delete(`/subscriptions/${id}`);
    } catch (error) {
      if (this.isNotFoundError(error)) {
        return;
      }
      throw this.handleError(error, 'cancelSubscription');
    }
  }

  // ============================================================================
  // PAYMENT LINK METHODS
  // ============================================================================

  /**
   * Cria um novo link de pagamento
   */
  async createPaymentLink(input: CreatePaymentLinkInput): Promise<AsaasPaymentLink> {
    return this.executeWithRetry(async () => {
      const response = await this.client.post<AsaasPaymentLink>('/paymentLinks', input);
      return response.data;
    });
  }

  /**
   * Obtém um link de pagamento por ID
   */
  async getPaymentLink(id: string): Promise<AsaasPaymentLink | null> {
    try {
      const response = await this.client.get<AsaasPaymentLink>(`/paymentLinks/${id}`);
      return response.data;
    } catch (error) {
      if (this.isNotFoundError(error)) {
        return null;
      }
      throw this.handleError(error, 'getPaymentLink');
    }
  }

  /**
   * Lista links de pagamento
   */
  async listPaymentLinks(params?: { offset?: number; limit?: number }): Promise<AsaasListResponse<AsaasPaymentLink>> {
    try {
      const response = await this.client.get<AsaasListResponse<AsaasPaymentLink>>(
        '/paymentLinks',
        { params }
      );
      return response.data;
    } catch (error) {
      throw this.handleError(error, 'listPaymentLinks');
    }
  }

  /**
   * Atualiza um link de pagamento
   */
  async updatePaymentLink(id: string, input: UpdatePaymentLinkInput): Promise<AsaasPaymentLink> {
    return this.executeWithRetry(async () => {
      const response = await this.client.put<AsaasPaymentLink>(`/paymentLinks/${id}`, input);
      return response.data;
    });
  }

  /**
   * Desativa um link de pagamento
   */
  async deactivatePaymentLink(id: string): Promise<AsaasPaymentLink> {
    return this.updatePaymentLink(id, { active: false });
  }

  /**
   * Deleta um link de pagamento
   */
  async deletePaymentLink(id: string): Promise<void> {
    try {
      await this.client.delete(`/paymentLinks/${id}`);
    } catch (error) {
      if (this.isNotFoundError(error)) {
        return;
      }
      throw this.handleError(error, 'deletePaymentLink');
    }
  }

  // ============================================================================
  // PAYMENT METHODS
  // ============================================================================

  /**
   * Cria uma nova cobrança
   */
  async createPayment(input: CreatePaymentInput): Promise<AsaasPayment> {
    return this.executeWithRetry(async () => {
      const response = await this.client.post<AsaasPayment>('/payments', input);
      return response.data;
    });
  }

  /**
   * Obtém uma cobrança por ID
   */
  async getPayment(id: string): Promise<AsaasPayment | null> {
    try {
      const response = await this.client.get<AsaasPayment>(`/payments/${id}`);
      return response.data;
    } catch (error) {
      if (this.isNotFoundError(error)) {
        return null;
      }
      throw this.handleError(error, 'getPayment');
    }
  }

  /**
   * Lista todas as cobranças de um cliente (com paginação automática)
   */
  async listPaymentsByCustomer(customerId: string): Promise<AsaasPayment[]> {
    return this.listAllPayments({ customer: customerId, limit: 100 });
  }

  /**
   * Lista cobranças por status
   * @param status - PENDING, RECEIVED, CONFIRMED, OVERDUE, REFUNDED, etc.
   * @param limit - Limite de resultados (default: 100)
   */
  async listPaymentsByStatus(status: string, limit: number = 100): Promise<AsaasPayment[]> {
    try {
      const response = await this.client.get<AsaasListResponse<AsaasPayment>>(
        '/payments',
        { params: { status, limit } }
      );
      return response.data.data;
    } catch (error) {
      throw this.handleError(error, 'listPaymentsByStatus');
    }
  }

  /**
   * Lista cobranças com filtros avançados
   * @param filter - Filtros de busca (dueDate, status, billingType, etc.)
   */
  async listPayments(filter: ListPaymentsFilter): Promise<AsaasListResponse<AsaasPayment>> {
    try {
      const response = await this.client.get<AsaasListResponse<AsaasPayment>>(
        '/payments',
        { params: filter }
      );
      return response.data;
    } catch (error) {
      throw this.handleError(error, 'listPayments');
    }
  }

  /**
   * Lista todas as cobranças com paginação automática
   * @param filter - Filtros de busca
   * @param maxPages - Número máximo de páginas (default: 10)
   */
  async listAllPayments(filter: ListPaymentsFilter, maxPages: number = 10): Promise<AsaasPayment[]> {
    const allPayments: AsaasPayment[] = [];
    let offset = filter.offset || 0;
    const limit = filter.limit || 100;
    let page = 0;

    try {
      while (page < maxPages) {
        const response = await this.listPayments({ ...filter, offset, limit });
        allPayments.push(...response.data);

        if (!response.hasMore) {
          break;
        }

        offset += limit;
        page++;
      }

      return allPayments;
    } catch (error) {
      throw this.handleError(error, 'listAllPayments');
    }
  }

  /**
   * Obtém QR Code PIX de uma cobrança
   */
  async getPixQrCode(paymentId: string): Promise<{ encodedImage: string; payload: string; expirationDate: string } | null> {
    try {
      const response = await this.client.get<{
        encodedImage: string;
        payload: string;
        expirationDate: string;
      }>(`/payments/${paymentId}/pixQrCode`);
      return response.data;
    } catch (error) {
      if (this.isNotFoundError(error)) {
        return null;
      }
      throw this.handleError(error, 'getPixQrCode');
    }
  }

  /**
   * Cancela uma cobrança
   */
  async cancelPayment(id: string): Promise<void> {
    try {
      await this.client.delete(`/payments/${id}`);
    } catch (error) {
      if (this.isNotFoundError(error)) {
        return;
      }
      throw this.handleError(error, 'cancelPayment');
    }
  }

  // ============================================================================
  // DOCUMENT METHODS
  // ============================================================================

  /**
   * Lista documentos de uma cobrança
   */
  async listPaymentDocuments(paymentId: string): Promise<AsaasDocument[]> {
    try {
      const response = await this.client.get<{ data: AsaasDocument[] }>(
        `/payments/${paymentId}/documents`
      );
      return response.data.data || [];
    } catch (error) {
      if (this.isNotFoundError(error)) {
        return [];
      }
      throw this.handleError(error, 'listPaymentDocuments');
    }
  }

  /**
   * Baixa o conteúdo binário de um documento (PDF) via URL pública
   */
  async downloadDocument(downloadUrl: string): Promise<Buffer> {
    try {
      const response = await axios.get(downloadUrl, {
        responseType: 'arraybuffer',
        timeout: 60000,
      });
      return Buffer.from(response.data);
    } catch (error) {
      throw this.handleError(error, 'downloadDocument');
    }
  }

  // ============================================================================
  // CONNECTION TEST
  // ============================================================================

  /**
   * Testa a conexão com a API do Asaas
   * Retorna informações sobre a conexão e status
   */
  async testConnection(): Promise<{
    success: boolean;
    message: string;
    details?: {
      totalCustomers?: number;
      apiKeyValid: boolean;
    };
  }> {
    try {
      // Tenta listar clientes com limit=1 para verificar se a API key é válida
      const response = await this.client.get<AsaasListResponse<AsaasCustomer>>(
        '/customers',
        { params: { limit: 1 } }
      );

      return {
        success: true,
        message: 'Conexão com Asaas estabelecida com sucesso!',
        details: {
          totalCustomers: response.data.totalCount,
          apiKeyValid: true,
        },
      };
    } catch (error) {
      if (axios.isAxiosError(error)) {
        const status = error.response?.status;

        if (status === 401) {
          return {
            success: false,
            message: 'API Key inválida ou não autorizada',
            details: { apiKeyValid: false },
          };
        }

        if (status === 403) {
          return {
            success: false,
            message: 'Acesso negado. Verifique as permissões da API Key',
            details: { apiKeyValid: false },
          };
        }

        return {
          success: false,
          message: `Erro de conexão: ${error.message}`,
          details: { apiKeyValid: false },
        };
      }

      return {
        success: false,
        message: `Erro inesperado: ${error instanceof Error ? error.message : 'Erro desconhecido'}`,
        details: { apiKeyValid: false },
      };
    }
  }

  // ============================================================================
  // HELPER METHODS
  // ============================================================================

  /**
   * Executa operação com retry e rate limiting
   */
  private async executeWithRetry<T>(
    operation: () => Promise<T>,
    retries: number = MAX_RETRIES
  ): Promise<T> {
    let lastError: Error | null = null;

    for (let attempt = 1; attempt <= retries; attempt++) {
      try {
        // Aplicar rate limiter ANTES de cada tentativa
        await this.rateLimiter.acquire();
        return await operation();
      } catch (error) {
        lastError = error instanceof Error ? error : new Error(String(error));

        // Tratamento especial para erro 429 (rate limit da API)
        if (axios.isAxiosError(error) && error.response?.status === 429) {
          const waitTime = Math.min(30000, RETRY_DELAY_MS * Math.pow(3, attempt)); // Backoff exponencial até 30s
          console.warn(
            `[Asaas] Rate limited pela API (429). Aguardando ${waitTime}ms antes de retry (tentativa ${attempt}/${retries})...`
          );
          await this.delay(waitTime);
          continue;
        }

        if (this.isRetryableError(error) && attempt < retries) {
          const delay = RETRY_DELAY_MS * attempt;
          console.warn(
            `[AsaasClient] Tentativa ${attempt} falhou, retry em ${delay}ms...`,
            lastError.message
          );
          await this.delay(delay);
          continue;
        }

        break;
      }
    }

    console.error('[AsaasClient] Todas as tentativas falharam:', lastError);
    throw lastError;
  }

  /**
   * Verifica se é erro recuperável
   */
  private isRetryableError(error: unknown): boolean {
    if (axios.isAxiosError(error)) {
      const status = error.response?.status;
      return (
        status === 429 || // Rate limit
        status === 500 ||
        status === 502 ||
        status === 503 ||
        status === 504
      );
    }

    if (error instanceof Error) {
      return (
        error.message.includes('ECONNRESET') ||
        error.message.includes('ETIMEDOUT') ||
        error.message.includes('ENOTFOUND')
      );
    }

    return false;
  }

  /**
   * Verifica se é erro de não encontrado
   */
  private isNotFoundError(error: unknown): boolean {
    if (axios.isAxiosError(error)) {
      return error.response?.status === 404;
    }
    return false;
  }

  /**
   * Trata erros
   */
  private handleError(error: unknown, operation: string): Error {
    if (axios.isAxiosError(error)) {
      const axiosError = error as AxiosError<AsaasError>;
      const asaasErrors = axiosError.response?.data?.errors;

      if (asaasErrors && asaasErrors.length > 0) {
        const errorMessages = asaasErrors
          .map((e) => `${e.code}: ${e.description}`)
          .join('; ');
        return new Error(`[AsaasClient] ${operation} failed: ${errorMessages}`);
      }

      return new Error(
        `[AsaasClient] ${operation} failed: ${axiosError.message}`
      );
    }

    if (error instanceof Error) {
      return new Error(`[AsaasClient] ${operation} failed: ${error.message}`);
    }

    return new Error(`[AsaasClient] ${operation} failed: Unknown error`);
  }

  /**
   * Helper para delay
   */
  private delay(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}

/**
 * Factory function para criar cliente Asaas
 */
export function createAsaasClient(config: AsaasConfig): AsaasClient {
  return new AsaasClient(config);
}
