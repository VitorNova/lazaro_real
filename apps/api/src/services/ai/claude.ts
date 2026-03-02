import Anthropic from '@anthropic-ai/sdk';
import {
  ClaudeMessage,
  ClaudeResponse,
  ToolDefinition,
  SendMessageParams,
  SendWithToolsParams,
  ContentBlock,
  ThinkingConfig,
} from './types';

const DEFAULT_MODEL = 'claude-sonnet-4-20250514';
const DEFAULT_MAX_TOKENS = 4096;
const MAX_RETRIES = 3;
const RETRY_DELAY_MS = 1000;

export class ClaudeClient {
  private client: Anthropic;
  private model: string;

  constructor(apiKey: string, model?: string) {
    this.client = new Anthropic({
      apiKey,
    });
    this.model = model || DEFAULT_MODEL;
  }

  /**
   * Envia uma mensagem para o Claude
   */
  async sendMessage(params: SendMessageParams): Promise<ClaudeResponse> {
    const {
      systemPrompt,
      messages,
      tools,
      maxTokens = DEFAULT_MAX_TOKENS,
      temperature = 0.7,
      stopSequences,
      thinking,
    } = params;

    return this.executeWithRetry(async () => {
      // Quando thinking está habilitado, temperature deve ser 1
      const effectiveTemperature = thinking ? 1 : temperature;

      const requestParams: Anthropic.MessageCreateParams = {
        model: this.model,
        max_tokens: maxTokens,
        temperature: effectiveTemperature,
        system: systemPrompt,
        messages: this.formatMessages(messages),
        tools: tools ? this.formatTools(tools) : undefined,
        stop_sequences: stopSequences,
      };

      // Adiciona thinking se habilitado
      if (thinking) {
        (requestParams as any).thinking = thinking;
      }

      const response = await this.client.messages.create(requestParams);

      return this.parseResponse(response);
    });
  }

  /**
   * Envia mensagem com tools habilitadas
   */
  async sendWithTools(params: SendWithToolsParams): Promise<ClaudeResponse> {
    const {
      systemPrompt,
      messages,
      tools,
      maxTokens = DEFAULT_MAX_TOKENS,
      temperature = 0.7,
      toolChoice,
      thinking,
    } = params;

    return this.executeWithRetry(async () => {
      // Quando thinking está habilitado, temperature deve ser 1
      const effectiveTemperature = thinking ? 1 : temperature;

      const requestParams: Anthropic.MessageCreateParams = {
        model: this.model,
        max_tokens: maxTokens,
        temperature: effectiveTemperature,
        system: systemPrompt,
        messages: this.formatMessages(messages),
        tools: this.formatTools(tools),
        tool_choice: toolChoice,
      };

      // Adiciona thinking se habilitado
      if (thinking) {
        (requestParams as any).thinking = thinking;
      }

      const response = await this.client.messages.create(requestParams);

      return this.parseResponse(response);
    });
  }

  /**
   * Continua uma conversa após executar tools
   */
  async continueWithToolResults(
    params: SendMessageParams,
    previousResponse: ClaudeResponse,
    toolResults: Array<{ tool_use_id: string; content: string; is_error?: boolean }>
  ): Promise<ClaudeResponse> {
    // Adiciona a resposta anterior do assistant e os resultados das tools
    const updatedMessages: ClaudeMessage[] = [
      ...params.messages,
      {
        role: 'assistant',
        content: previousResponse.content as ContentBlock[],
      },
      {
        role: 'user',
        content: toolResults.map((result) => ({
          type: 'tool_result' as const,
          tool_use_id: result.tool_use_id,
          content: result.content,
          is_error: result.is_error,
        })),
      },
    ];

    return this.sendMessage({
      ...params,
      messages: updatedMessages,
    });
  }

  /**
   * Formata mensagens para o formato da API
   */
  private formatMessages(messages: ClaudeMessage[]): Anthropic.MessageParam[] {
    return messages.map((msg) => ({
      role: msg.role,
      content: msg.content,
    })) as Anthropic.MessageParam[];
  }

  /**
   * Formata tools para o formato da API
   */
  private formatTools(tools: ToolDefinition[]): Anthropic.Tool[] {
    return tools.map((tool) => ({
      name: tool.name,
      description: tool.description,
      input_schema: tool.input_schema as Anthropic.Tool.InputSchema,
    }));
  }

  /**
   * Parseia a resposta da API para o formato interno
   */
  private parseResponse(response: Anthropic.Message): ClaudeResponse {
    return {
      id: response.id,
      type: response.type,
      role: response.role,
      content: response.content as ContentBlock[],
      model: response.model,
      stop_reason: response.stop_reason as ClaudeResponse['stop_reason'],
      stop_sequence: response.stop_sequence,
      usage: {
        input_tokens: response.usage.input_tokens,
        output_tokens: response.usage.output_tokens,
      },
    };
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
            `[ClaudeClient] Attempt ${attempt} failed, retrying in ${RETRY_DELAY_MS * attempt}ms...`,
            lastError.message
          );
          await this.delay(RETRY_DELAY_MS * attempt);
          continue;
        }

        // Erro não recuperável ou última tentativa
        break;
      }
    }

    console.error('[ClaudeClient] All retry attempts failed:', lastError);
    throw lastError;
  }

  /**
   * Verifica se o erro é recuperável
   */
  private isRetryableError(error: unknown): boolean {
    if (error instanceof Anthropic.APIError) {
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
}

/**
 * Factory function para criar cliente Claude
 */
export function createClaudeClient(apiKey: string, model?: string): ClaudeClient {
  return new ClaudeClient(apiKey, model);
}
