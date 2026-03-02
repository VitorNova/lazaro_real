import OpenAI from 'openai';

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
// OPENAI TYPES
// ============================================================================

export interface OpenAIConfig {
  apiKey: string;
  model?: string;
}

export interface OpenAIMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export interface OpenAIChatOptions {
  systemPrompt?: string;
  history?: OpenAIMessage[];
  message: string;
  maxTokens?: number;
  temperature?: number;
}

// ============================================================================
// FUNCTION CALLING TYPES
// ============================================================================

export interface OpenAIFunctionDeclaration {
  name: string;
  description: string;
  parameters: {
    type: 'object';
    properties: Record<string, {
      type: string;
      description?: string;
      enum?: string[];
    }>;
    required?: string[];
  };
}

export interface OpenAIFunctionCall {
  name: string;
  args: Record<string, unknown>;
}

export type OpenAIFunctionCallingMode = 'auto' | 'required' | 'none';

export interface OpenAIChatWithToolsOptions extends OpenAIChatOptions {
  tools?: OpenAIFunctionDeclaration[];
  onFunctionCall?: (functionCall: OpenAIFunctionCall) => Promise<Record<string, unknown>>;
  functionCallingMode?: OpenAIFunctionCallingMode;
  allowedFunctions?: string[];
}

export interface OpenAIResponse {
  text: string;
  tokensUsed?: {
    input: number;
    output: number;
  };
}

export interface OpenAIResponseWithTools extends OpenAIResponse {
  functionCall?: OpenAIFunctionCall;
  finishReason?: string;
}

// ============================================================================
// CONSTANTS
// ============================================================================

const DEFAULT_MODEL = 'gpt-4o-mini';
const MAX_RETRIES = 3;
const INITIAL_RETRY_DELAY_MS = 1000;

// ============================================================================
// OPENAI CLIENT
// ============================================================================

export class OpenAIClient {
  private client: OpenAI;
  private model: string;
  private logger: Logger;

  constructor(config: OpenAIConfig) {
    if (!config.apiKey) {
      throw new Error('OpenAIClient: apiKey is required');
    }

    this.client = new OpenAI({ apiKey: config.apiKey });
    this.model = config.model || DEFAULT_MODEL;
    this.logger = createLogger('OpenAIClient');

    this.logger.info('Client initialized', { model: this.model });
  }

  // ========================================================================
  // SIMPLE CHAT
  // ========================================================================

  async chat(options: OpenAIChatOptions): Promise<OpenAIResponse> {
    const { systemPrompt, history = [], message, maxTokens = 4096, temperature = 0.7 } = options;

    this.logger.info('Starting chat', { model: this.model, messageLength: message.length });

    const messages: OpenAI.ChatCompletionMessageParam[] = [];

    // Adicionar system prompt
    if (systemPrompt) {
      messages.push({ role: 'system', content: systemPrompt });
    }

    // Adicionar historico
    for (const msg of history) {
      messages.push({ role: msg.role, content: msg.content });
    }

    // Adicionar mensagem atual
    messages.push({ role: 'user', content: message });

    return this.executeWithRetry(async () => {
      const response = await this.client.chat.completions.create({
        model: this.model,
        messages,
        max_tokens: maxTokens,
        temperature,
      });

      const choice = response.choices[0];
      const text = choice?.message?.content || '';

      this.logger.info('Chat completed', {
        tokensUsed: response.usage?.total_tokens,
        finishReason: choice?.finish_reason,
      });

      return {
        text,
        tokensUsed: response.usage ? {
          input: response.usage.prompt_tokens,
          output: response.usage.completion_tokens,
        } : undefined,
      };
    });
  }

  // ========================================================================
  // CHAT WITH TOOLS
  // ========================================================================

  async chatWithTools(options: OpenAIChatWithToolsOptions): Promise<OpenAIResponseWithTools> {
    const {
      systemPrompt,
      history = [],
      message,
      maxTokens = 4096,
      temperature = 0.7,
      tools = [],
      onFunctionCall,
      functionCallingMode = 'auto',
      allowedFunctions,
    } = options;

    this.logger.info('Starting chat with tools', {
      model: this.model,
      toolCount: tools.length,
      mode: functionCallingMode,
    });

    const messages: OpenAI.ChatCompletionMessageParam[] = [];

    // Adicionar system prompt
    if (systemPrompt) {
      messages.push({ role: 'system', content: systemPrompt });
    }

    // Adicionar historico
    for (const msg of history) {
      messages.push({ role: msg.role, content: msg.content });
    }

    // Adicionar mensagem atual
    messages.push({ role: 'user', content: message });

    // Preparar tools no formato OpenAI
    const openaiTools: OpenAI.ChatCompletionTool[] = tools.map(tool => ({
      type: 'function',
      function: {
        name: tool.name,
        description: tool.description,
        parameters: tool.parameters as OpenAI.FunctionParameters,
      },
    }));

    // Determinar tool_choice
    let toolChoice: OpenAI.ChatCompletionToolChoiceOption | undefined;
    if (functionCallingMode === 'required') {
      if (allowedFunctions && allowedFunctions.length === 1) {
        toolChoice = { type: 'function', function: { name: allowedFunctions[0] } };
      } else {
        toolChoice = 'required';
      }
    } else if (functionCallingMode === 'none') {
      toolChoice = 'none';
    } else {
      toolChoice = 'auto';
    }

    return this.executeWithRetry(async () => {
      const response = await this.client.chat.completions.create({
        model: this.model,
        messages,
        max_tokens: maxTokens,
        temperature,
        tools: openaiTools.length > 0 ? openaiTools : undefined,
        tool_choice: openaiTools.length > 0 ? toolChoice : undefined,
      });

      const choice = response.choices[0];
      const assistantMessage = choice?.message;

      // Verificar se tem tool call
      if (assistantMessage?.tool_calls && assistantMessage.tool_calls.length > 0) {
        // Processar TODAS as tool calls, não só a primeira
        const allToolCalls = assistantMessage.tool_calls;

        this.logger.info('Function calls detected', {
          count: allToolCalls.length,
          functions: allToolCalls.map(tc => tc.function.name),
        });

        // Se tem callback, executar TODAS as tools e continuar
        if (onFunctionCall) {
          // Adicionar resposta do assistant com todas as tool calls
          messages.push({
            role: 'assistant',
            content: assistantMessage.content,
            tool_calls: assistantMessage.tool_calls,
          });

          // Processar CADA tool call e adicionar resposta
          let primaryFunctionCall: OpenAIFunctionCall | undefined;
          for (const toolCall of allToolCalls) {
            const functionCall: OpenAIFunctionCall = {
              name: toolCall.function.name,
              args: JSON.parse(toolCall.function.arguments || '{}'),
            };

            // Guardar a primeira como principal
            if (!primaryFunctionCall) {
              primaryFunctionCall = functionCall;
            }

            this.logger.info('Executing function', { functionName: functionCall.name });
            const functionResult = await onFunctionCall(functionCall);

            // Adicionar resultado desta tool call
            messages.push({
              role: 'tool',
              tool_call_id: toolCall.id,
              content: JSON.stringify(functionResult),
            });
          }

          // Continuar a conversa
          const continuedResponse = await this.client.chat.completions.create({
            model: this.model,
            messages,
            max_tokens: maxTokens,
            temperature,
          });

          const continuedChoice = continuedResponse.choices[0];
          return {
            text: continuedChoice?.message?.content || '',
            functionCall: primaryFunctionCall,
            finishReason: continuedChoice?.finish_reason || undefined,
            tokensUsed: continuedResponse.usage ? {
              input: continuedResponse.usage.prompt_tokens,
              output: continuedResponse.usage.completion_tokens,
            } : undefined,
          };
        }

        // Se não tem callback, retornar primeira function call
        const toolCall = allToolCalls[0];
        const functionCall: OpenAIFunctionCall = {
          name: toolCall.function.name,
          args: JSON.parse(toolCall.function.arguments || '{}'),
        };

        // Se nao tem callback, retornar com function call
        return {
          text: assistantMessage.content || '',
          functionCall,
          finishReason: choice?.finish_reason || undefined,
          tokensUsed: response.usage ? {
            input: response.usage.prompt_tokens,
            output: response.usage.completion_tokens,
          } : undefined,
        };
      }

      // Sem tool call - resposta normal
      return {
        text: assistantMessage?.content || '',
        finishReason: choice?.finish_reason || undefined,
        tokensUsed: response.usage ? {
          input: response.usage.prompt_tokens,
          output: response.usage.completion_tokens,
        } : undefined,
      };
    });
  }

  // ========================================================================
  // RETRY LOGIC
  // ========================================================================

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

        // Verificar se e erro de quota/rate limit
        if (error instanceof OpenAI.APIError) {
          if (error.status === 429) {
            this.logger.warn(`Rate limited, attempt ${attempt}/${retries}`, { message: error.message });

            if (attempt < retries) {
              const delay = INITIAL_RETRY_DELAY_MS * Math.pow(2, attempt - 1);
              await this.delay(delay);
              continue;
            }
          }

          // Erros de servidor
          if (error.status && error.status >= 500 && attempt < retries) {
            const delay = INITIAL_RETRY_DELAY_MS * Math.pow(2, attempt - 1);
            await this.delay(delay);
            continue;
          }
        }

        // Erro nao recuperavel ou ultima tentativa
        break;
      }
    }

    this.logger.error('All retry attempts failed', lastError);
    throw lastError;
  }

  private delay(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  // ========================================================================
  // UTILITY METHODS
  // ========================================================================

  setModel(model: string): void {
    this.model = model;
    this.logger.info('Model updated', { model });
  }

  getModel(): string {
    return this.model;
  }
}

// ============================================================================
// FACTORY
// ============================================================================

export function createOpenAIClient(config: OpenAIConfig): OpenAIClient {
  return new OpenAIClient(config);
}
