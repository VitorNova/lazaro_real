/**
 * AI Factory - Abstrai a criacao de clientes de IA
 * Suporta: Gemini, Claude, OpenAI
 */

import { GeminiClient, createGeminiClient, GeminiChatOptions, GeminiChatWithToolsOptions, GeminiResponse, GeminiResponseWithTools, GeminiFunctionDeclarationInput } from './gemini-client';
import { ClaudeClient, createClaudeClient } from './claude';
import { OpenAIClient, createOpenAIClient, OpenAIChatOptions, OpenAIChatWithToolsOptions, OpenAIFunctionDeclaration } from './openai-client';

// ============================================================================
// TYPES
// ============================================================================

export type AIProvider = 'gemini' | 'claude' | 'openai';

export interface AIConfig {
  provider: AIProvider;
  apiKey: string;
  model?: string;
}

export interface AIMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export interface AIChatOptions {
  systemPrompt?: string;
  history?: AIMessage[];
  message: string;
  maxTokens?: number;
  temperature?: number;
}

export interface AIFunctionDeclaration {
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

export interface AIFunctionCall {
  name: string;
  args: Record<string, unknown>;
}

export type AIFunctionCallingMode = 'auto' | 'required' | 'none';

export interface AIChatWithToolsOptions extends AIChatOptions {
  tools?: AIFunctionDeclaration[];
  onFunctionCall?: (functionCall: AIFunctionCall) => Promise<Record<string, unknown>>;
  functionCallingMode?: AIFunctionCallingMode;
  allowedFunctions?: string[];
}

export interface AIResponse {
  text: string;
  tokensUsed?: {
    input: number;
    output: number;
  };
}

export interface AIResponseWithTools extends AIResponse {
  functionCall?: AIFunctionCall;
  finishReason?: string;
}

// ============================================================================
// AVAILABLE MODELS
// ============================================================================

export const AI_MODELS: Record<AIProvider, Array<{ id: string; name: string; description: string }>> = {
  gemini: [
    { id: 'gemini-2.0-flash', name: 'Gemini 2.0 Flash', description: 'Rapido e estavel (Recomendado)' },
    { id: 'gemini-2.5-flash', name: 'Gemini 2.5 Flash', description: 'Rapido com boa qualidade' },
  ],
  claude: [
    { id: 'claude-sonnet-4-20250514', name: 'Claude Sonnet 4', description: 'Mais recente e capaz' },
    { id: 'claude-3-5-sonnet-20241022', name: 'Claude 3.5 Sonnet', description: 'Excelente equilibrio' },
    { id: 'claude-3-haiku-20240307', name: 'Claude 3 Haiku', description: 'Mais rapido e economico' },
  ],
  openai: [
    { id: 'gpt-4o', name: 'GPT-4o', description: 'Mais capaz e multimodal' },
    { id: 'gpt-4o-mini', name: 'GPT-4o Mini', description: 'Rapido e economico' },
    { id: 'gpt-4-turbo', name: 'GPT-4 Turbo', description: 'Alta capacidade' },
    { id: 'gpt-3.5-turbo', name: 'GPT-3.5 Turbo', description: 'Economico, bom para tarefas simples' },
  ],
};

export const DEFAULT_MODELS: Record<AIProvider, string> = {
  gemini: 'gemini-2.0-flash',
  claude: 'claude-sonnet-4-20250514',
  openai: 'gpt-4o-mini',
};

// ============================================================================
// RESPONSE SIZE CONFIGURATION
// ============================================================================

export type ResponseSize = 'short' | 'medium' | 'long';

export interface ResponseSizeConfig {
  maxTokens: number;
  instruction: string;
}

export const RESPONSE_SIZE_CONFIG: Record<ResponseSize, ResponseSizeConfig> = {
  short: {
    maxTokens: 150,
    instruction: 'IMPORTANTE: Seja EXTREMAMENTE conciso. Responda em no máximo 1-2 frases curtas e diretas. Vá direto ao ponto sem rodeios.',
  },
  medium: {
    maxTokens: 500,
    instruction: 'Responda de forma clara, objetiva e natural. Use parágrafos curtos quando necessário.',
  },
  long: {
    maxTokens: 1000,
    instruction: 'Forneça uma resposta detalhada e completa. Pode usar múltiplos parágrafos para explicar bem o assunto.',
  },
};

/**
 * Obtém a configuração de tamanho de resposta
 */
export function getResponseSizeConfig(size: ResponseSize | undefined): ResponseSizeConfig {
  return RESPONSE_SIZE_CONFIG[size || 'medium'];
}

// ============================================================================
// UNIFIED AI CLIENT
// ============================================================================

export class UnifiedAIClient {
  private provider: AIProvider;
  private geminiClient?: GeminiClient;
  private claudeClient?: ClaudeClient;
  private openaiClient?: OpenAIClient;

  constructor(config: AIConfig) {
    this.provider = config.provider;

    switch (config.provider) {
      case 'gemini':
        this.geminiClient = createGeminiClient({
          apiKey: config.apiKey,
          model: config.model || DEFAULT_MODELS.gemini,
        });
        break;

      case 'claude':
        this.claudeClient = createClaudeClient(
          config.apiKey,
          config.model || DEFAULT_MODELS.claude
        );
        break;

      case 'openai':
        this.openaiClient = createOpenAIClient({
          apiKey: config.apiKey,
          model: config.model || DEFAULT_MODELS.openai,
        });
        break;

      default:
        throw new Error(`Unknown AI provider: ${config.provider}`);
    }

    console.info(`[UnifiedAIClient] Initialized with provider: ${config.provider}, model: ${config.model || DEFAULT_MODELS[config.provider]}`);
  }

  // ========================================================================
  // SIMPLE CHAT
  // ========================================================================

  async chat(options: AIChatOptions): Promise<AIResponse> {
    switch (this.provider) {
      case 'gemini':
        return this.chatWithGemini(options);

      case 'claude':
        return this.chatWithClaude(options);

      case 'openai':
        return this.chatWithOpenAI(options);

      default:
        throw new Error(`Unknown provider: ${this.provider}`);
    }
  }

  private async chatWithGemini(options: AIChatOptions): Promise<AIResponse> {
    if (!this.geminiClient) throw new Error('Gemini client not initialized');

    const geminiHistory = options.history?.map(msg => ({
      role: msg.role === 'assistant' ? 'model' as const : 'user' as const,
      parts: [{ text: msg.content }],
    }));

    const response = await this.geminiClient.chat({
      systemPrompt: options.systemPrompt,
      history: geminiHistory,
      message: options.message,
      maxTokens: options.maxTokens,
      temperature: options.temperature,
    });

    return {
      text: response.text,
      tokensUsed: response.tokensUsed,
    };
  }

  private async chatWithClaude(options: AIChatOptions): Promise<AIResponse> {
    if (!this.claudeClient) throw new Error('Claude client not initialized');

    const claudeMessages = options.history?.map(msg => ({
      role: msg.role as 'user' | 'assistant',
      content: msg.content,
    })) || [];

    // Adicionar mensagem atual
    claudeMessages.push({
      role: 'user',
      content: options.message,
    });

    const response = await this.claudeClient.sendMessage({
      systemPrompt: options.systemPrompt || '',
      messages: claudeMessages,
      maxTokens: options.maxTokens,
      temperature: options.temperature,
    });

    // Extrair texto da resposta
    let text = '';
    for (const block of response.content) {
      if (block.type === 'text') {
        text += block.text;
      }
    }

    return {
      text,
      tokensUsed: {
        input: response.usage.input_tokens,
        output: response.usage.output_tokens,
      },
    };
  }

  private async chatWithOpenAI(options: AIChatOptions): Promise<AIResponse> {
    if (!this.openaiClient) throw new Error('OpenAI client not initialized');

    const openaiHistory = options.history?.map(msg => ({
      role: msg.role as 'user' | 'assistant' | 'system',
      content: msg.content,
    }));

    const response = await this.openaiClient.chat({
      systemPrompt: options.systemPrompt,
      history: openaiHistory,
      message: options.message,
      maxTokens: options.maxTokens,
      temperature: options.temperature,
    });

    return response;
  }

  // ========================================================================
  // CHAT WITH TOOLS
  // ========================================================================

  async chatWithTools(options: AIChatWithToolsOptions): Promise<AIResponseWithTools> {
    switch (this.provider) {
      case 'gemini':
        return this.chatWithToolsGemini(options);

      case 'claude':
        return this.chatWithToolsClaude(options);

      case 'openai':
        return this.chatWithToolsOpenAI(options);

      default:
        throw new Error(`Unknown provider: ${this.provider}`);
    }
  }

  private async chatWithToolsGemini(options: AIChatWithToolsOptions): Promise<AIResponseWithTools> {
    if (!this.geminiClient) throw new Error('Gemini client not initialized');

    const geminiHistory = options.history?.map(msg => ({
      role: msg.role === 'assistant' ? 'model' as const : 'user' as const,
      parts: [{ text: msg.content }],
    }));

    // Converter tools para formato Gemini
    const geminiTools: GeminiFunctionDeclarationInput[] = options.tools?.map(tool => ({
      name: tool.name,
      description: tool.description,
      parameters: tool.parameters,
    })) || [];

    // Converter modo
    let geminiMode: 'AUTO' | 'ANY' | 'NONE' = 'AUTO';
    if (options.functionCallingMode === 'required') geminiMode = 'ANY';
    if (options.functionCallingMode === 'none') geminiMode = 'NONE';

    const geminiOptions: GeminiChatWithToolsOptions = {
      systemPrompt: options.systemPrompt,
      history: geminiHistory,
      message: options.message,
      maxTokens: options.maxTokens,
      temperature: options.temperature,
      tools: geminiTools,
      functionCallingMode: geminiMode,
      allowedFunctions: options.allowedFunctions,
      onFunctionCall: options.onFunctionCall ? async (fc) => {
        return options.onFunctionCall!({ name: fc.name, args: fc.args });
      } : undefined,
    };

    const response = await this.geminiClient.chatWithTools(geminiOptions);

    return {
      text: response.text,
      tokensUsed: response.tokensUsed,
      functionCall: response.functionCall ? {
        name: response.functionCall.name,
        args: response.functionCall.args,
      } : undefined,
      finishReason: response.finishReason,
    };
  }

  private async chatWithToolsClaude(options: AIChatWithToolsOptions): Promise<AIResponseWithTools> {
    if (!this.claudeClient) throw new Error('Claude client not initialized');

    const claudeMessages = options.history?.map(msg => ({
      role: msg.role as 'user' | 'assistant',
      content: msg.content,
    })) || [];

    // Adicionar mensagem atual
    claudeMessages.push({
      role: 'user',
      content: options.message,
    });

    // Converter tools para formato Claude
    const claudeTools = options.tools?.map(tool => ({
      name: tool.name,
      description: tool.description,
      input_schema: {
        type: 'object' as const,
        properties: tool.parameters.properties,
        required: tool.parameters.required,
      },
    })) || [];

    const response = await this.claudeClient.sendWithTools({
      systemPrompt: options.systemPrompt || '',
      messages: claudeMessages,
      tools: claudeTools as any,
      maxTokens: options.maxTokens,
      temperature: options.temperature,
    });

    // Extrair texto e tool calls
    let text = '';
    let functionCall: AIFunctionCall | undefined;

    for (const block of response.content) {
      if (block.type === 'text') {
        text += block.text;
      } else if (block.type === 'tool_use') {
        functionCall = {
          name: block.name,
          args: block.input as Record<string, unknown>,
        };

        // Se tem callback, executar
        if (options.onFunctionCall && functionCall) {
          const result = await options.onFunctionCall(functionCall);

          // Continuar com resultado
          const continuedResponse = await this.claudeClient.continueWithToolResults(
            {
              systemPrompt: options.systemPrompt || '',
              messages: claudeMessages,
              tools: claudeTools as any,
              maxTokens: options.maxTokens,
              temperature: options.temperature,
            },
            response,
            [{
              tool_use_id: block.id,
              content: JSON.stringify(result),
            }]
          );

          // Extrair texto final
          text = '';
          for (const contBlock of continuedResponse.content) {
            if (contBlock.type === 'text') {
              text += contBlock.text;
            }
          }

          return {
            text,
            functionCall,
            tokensUsed: {
              input: continuedResponse.usage.input_tokens,
              output: continuedResponse.usage.output_tokens,
            },
            finishReason: continuedResponse.stop_reason || undefined,
          };
        }
      }
    }

    return {
      text,
      functionCall,
      tokensUsed: {
        input: response.usage.input_tokens,
        output: response.usage.output_tokens,
      },
      finishReason: response.stop_reason || undefined,
    };
  }

  private async chatWithToolsOpenAI(options: AIChatWithToolsOptions): Promise<AIResponseWithTools> {
    if (!this.openaiClient) throw new Error('OpenAI client not initialized');

    const openaiHistory = options.history?.map(msg => ({
      role: msg.role as 'user' | 'assistant' | 'system',
      content: msg.content,
    }));

    // Converter tools para formato OpenAI
    const openaiTools: OpenAIFunctionDeclaration[] = options.tools?.map(tool => ({
      name: tool.name,
      description: tool.description,
      parameters: tool.parameters,
    })) || [];

    // Converter modo
    let openaiMode: 'auto' | 'required' | 'none' = 'auto';
    if (options.functionCallingMode === 'required') openaiMode = 'required';
    if (options.functionCallingMode === 'none') openaiMode = 'none';

    const response = await this.openaiClient.chatWithTools({
      systemPrompt: options.systemPrompt,
      history: openaiHistory,
      message: options.message,
      maxTokens: options.maxTokens,
      temperature: options.temperature,
      tools: openaiTools,
      functionCallingMode: openaiMode,
      allowedFunctions: options.allowedFunctions,
      onFunctionCall: options.onFunctionCall,
    });

    return response;
  }

  // ========================================================================
  // UTILITY
  // ========================================================================

  getProvider(): AIProvider {
    return this.provider;
  }
}

// ============================================================================
// FACTORY FUNCTION
// ============================================================================

export function createAIClient(config: AIConfig): UnifiedAIClient {
  return new UnifiedAIClient(config);
}

/**
 * Helper para criar cliente a partir de dados do agent
 */
export function createAIClientFromAgent(agent: {
  ai_provider?: AIProvider | null;
  gemini_api_key?: string | null;
  gemini_model?: string | null;
  claude_api_key?: string | null;
  claude_model?: string | null;
  openai_api_key?: string | null;
  openai_model?: string | null;
}): UnifiedAIClient {
  // Determinar provider (default: gemini para compatibilidade)
  const provider = agent.ai_provider || 'gemini';

  let apiKey: string;
  let model: string | undefined;

  switch (provider) {
    case 'gemini':
      if (!agent.gemini_api_key) {
        throw new Error('Gemini API key is required');
      }
      apiKey = agent.gemini_api_key;
      model = agent.gemini_model || undefined;
      break;

    case 'claude':
      if (!agent.claude_api_key) {
        throw new Error('Claude API key is required');
      }
      apiKey = agent.claude_api_key;
      model = agent.claude_model || undefined;
      break;

    case 'openai':
      if (!agent.openai_api_key) {
        throw new Error('OpenAI API key is required');
      }
      apiKey = agent.openai_api_key;
      model = agent.openai_model || undefined;
      break;

    default:
      throw new Error(`Unknown AI provider: ${provider}`);
  }

  return createAIClient({
    provider,
    apiKey,
    model,
  });
}
