import { GoogleGenerativeAI, FunctionDeclaration, SchemaType, Tool as GeminiTool, FunctionCallingMode as GeminiFunctionCallingMode } from '@google/generative-ai';

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
// RESPONSE SANITIZATION
// ============================================================================

const EMOJI_PATTERN = /[\u{1F300}-\u{1F9FF}]|[\u{2600}-\u{26FF}]|[\u{2700}-\u{27BF}]|[\u{1F600}-\u{1F64F}]|[\u{1F680}-\u{1F6FF}]|[\u{1F1E0}-\u{1F1FF}]/gu;
const PYTHON_TOOL_PATTERN = /print\s*\(\s*default_api\.([a-z_]+)\s*\(([^)]*)\)\s*\)/gi;
const PYTHON_TOOL_PATTERN_REMOVE = /print\s*\(\s*default_api\.[a-z_]+\s*\([^)]*\)\s*\)\s*/gi;
const LEAKED_TOOL_PATTERN = /@([a-z_]+)\s*\(([^)]*)\)/gi;
const LEAKED_TOOL_PATTERN_REMOVE = /@[a-z_]+\s*\([^)]*\)\s*/gi;

/** Mensagem fallback quando resposta fica vazia após sanitização */
const FALLBACK_MESSAGE = 'Desculpe, tive um problema ao processar. Pode repetir sua pergunta?';

/**
 * Resultado da sanitização
 */
interface SanitizeResult {
  text: string;
  extractedFunctionCall?: {
    name: string;
    args: Record<string, string>;
  };
  hadLeakedCode: boolean;
}

/**
 * Extrai argumentos de uma string no formato key='value' ou key="value"
 */
function parseToolArgs(argsString: string): Record<string, string> {
  const args: Record<string, string> = {};
  const argPattern = /(\w+)\s*=\s*["']([^"']*)["']/g;
  let match;
  while ((match = argPattern.exec(argsString)) !== null) {
    args[match[1]] = match[2];
  }
  return args;
}

/**
 * Tenta extrair function call de vazamento Python/OpenAPI
 * Formato: print(default_api.tool_name(param='value'))
 */
function extractPythonFunctionCall(text: string): { name: string; args: Record<string, string> } | null {
  const pattern = /print\s*\(\s*default_api\.([a-z_]+)\s*\(([^)]*)\)\s*\)/i;
  const match = text.match(pattern);

  if (match) {
    const name = match[1];
    const args = parseToolArgs(match[2]);
    console.log(`[GeminiClient] Extraída function call de vazamento Python: ${name}`, args);
    return { name, args };
  }
  return null;
}

/**
 * Tenta extrair function call de vazamento @tool_name()
 * Formato: @tool_name(param='value')
 */
function extractLeakedFunctionCall(text: string): { name: string; args: Record<string, string> } | null {
  const pattern = /@([a-z_]+)\s*\(([^)]*)\)/i;
  const match = text.match(pattern);

  if (match) {
    const name = match[1];
    const args = parseToolArgs(match[2]);
    console.log(`[GeminiClient] Extraída function call de vazamento @tool: ${name}`, args);
    return { name, args };
  }
  return null;
}

/**
 * Sanitiza a resposta do modelo removendo:
 * - Emojis (agentes geralmente têm regra de não usar)
 * - Vazamentos de código Python/OpenAPI
 * - Vazamentos de tool calls @tool_name()
 *
 * Se a resposta ficar vazia após sanitização, tenta extrair function call
 * do vazamento ou retorna mensagem fallback.
 */
function sanitizeResponse(text: string): SanitizeResult {
  let sanitized = text;
  let extractedFunctionCall: { name: string; args: Record<string, string> } | undefined;
  let hadLeakedCode = false;

  // Remove emojis
  if (EMOJI_PATTERN.test(sanitized)) {
    console.warn('[GeminiClient] Removendo emojis da resposta');
    sanitized = sanitized.replace(EMOJI_PATTERN, '');
  }

  // Detecta e tenta extrair function call de vazamento Python/OpenAPI
  if (PYTHON_TOOL_PATTERN_REMOVE.test(sanitized)) {
    console.warn('[GeminiClient] Detectado vazamento de padrão Python/OpenAPI');
    hadLeakedCode = true;

    // Tenta extrair a function call antes de remover
    const extracted = extractPythonFunctionCall(sanitized);
    if (extracted) {
      extractedFunctionCall = extracted;
    }

    // Remove o vazamento
    sanitized = sanitized.replace(PYTHON_TOOL_PATTERN_REMOVE, '');
  }

  // Detecta e tenta extrair function call de vazamento @tool_name()
  if (LEAKED_TOOL_PATTERN_REMOVE.test(sanitized)) {
    console.warn('[GeminiClient] Detectado vazamento de tool call @');
    hadLeakedCode = true;

    // Tenta extrair a function call antes de remover (se ainda não extraiu)
    if (!extractedFunctionCall) {
      const extracted = extractLeakedFunctionCall(sanitized);
      if (extracted) {
        extractedFunctionCall = extracted;
      }
    }

    // Remove o vazamento
    sanitized = sanitized.replace(LEAKED_TOOL_PATTERN_REMOVE, '');
  }

  // Limpar espaços múltiplos e trim
  sanitized = sanitized.replace(/\s+/g, ' ').trim();

  // Se ficou vazio após sanitização e tinha código vazado, usar fallback
  if (!sanitized && hadLeakedCode) {
    console.warn('[GeminiClient] Resposta ficou vazia após sanitização, usando fallback');
    sanitized = FALLBACK_MESSAGE;
  }

  return {
    text: sanitized,
    extractedFunctionCall,
    hadLeakedCode,
  };
}

// ============================================================================
// GEMINI TYPES
// ============================================================================

export interface GeminiConfig {
  apiKey: string;
  model?: string;
}

export interface GeminiMessage {
  role: 'user' | 'model';
  parts: { text: string }[];
}

export interface GeminiChatOptions {
  systemPrompt?: string;
  history?: GeminiMessage[];
  message: string;
  maxTokens?: number;
  temperature?: number;
}

// ============================================================================
// FUNCTION CALLING TYPES
// ============================================================================

export interface GeminiFunctionDeclarationInput {
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

/**
 * Converte nossa definição de função para o formato do SDK Gemini
 */
function toGeminiFunctionDeclaration(input: GeminiFunctionDeclarationInput): FunctionDeclaration {
  const properties: Record<string, any> = {};

  for (const [key, value] of Object.entries(input.parameters.properties)) {
    properties[key] = {
      type: mapTypeToSchemaType(value.type),
      description: value.description,
      enum: value.enum,
    };
  }

  return {
    name: input.name,
    description: input.description,
    parameters: {
      type: SchemaType.OBJECT,
      properties,
      required: input.parameters.required,
    },
  };
}

/**
 * Mapeia string de tipo para SchemaType
 */
function mapTypeToSchemaType(type: string): SchemaType {
  switch (type.toLowerCase()) {
    case 'string':
      return SchemaType.STRING;
    case 'number':
      return SchemaType.NUMBER;
    case 'integer':
      return SchemaType.INTEGER;
    case 'boolean':
      return SchemaType.BOOLEAN;
    case 'array':
      return SchemaType.ARRAY;
    case 'object':
      return SchemaType.OBJECT;
    default:
      return SchemaType.STRING;
  }
}

export interface GeminiFunctionCall {
  name: string;
  args: Record<string, unknown>;
}

export interface GeminiFunctionResponse {
  name: string;
  response: Record<string, unknown>;
}

export type FunctionCallingMode = 'AUTO' | 'ANY' | 'NONE';

/**
 * Converte string mode para enum do SDK Gemini
 */
function toGeminiFunctionCallingMode(mode: FunctionCallingMode): GeminiFunctionCallingMode {
  switch (mode) {
    case 'AUTO':
      return GeminiFunctionCallingMode.AUTO;
    case 'ANY':
      return GeminiFunctionCallingMode.ANY;
    case 'NONE':
      return GeminiFunctionCallingMode.NONE;
    default:
      return GeminiFunctionCallingMode.AUTO;
  }
}

export interface GeminiChatWithToolsOptions extends GeminiChatOptions {
  tools?: GeminiFunctionDeclarationInput[];
  onFunctionCall?: (functionCall: GeminiFunctionCall) => Promise<Record<string, unknown>>;
  /**
   * Function calling mode:
   * - AUTO: Model decides when to call functions (default)
   * - ANY: Model MUST call one of the functions
   * - NONE: Model won't call functions
   */
  functionCallingMode?: FunctionCallingMode;
  /**
   * Allowed functions - if set, model can only call these functions
   * Only used when mode is 'ANY'
   */
  allowedFunctions?: string[];
}

export interface GeminiResponseWithTools extends GeminiResponse {
  functionCall?: GeminiFunctionCall;
  finishReason?: string;
}

export interface GeminiResponse {
  text: string;
  tokensUsed?: {
    input: number;
    output: number;
  };
}

export interface GeminiStreamOptions extends GeminiChatOptions {
  onChunk?: (chunk: string) => void;
}

// ============================================================================
// CONSTANTS
// ============================================================================

const DEFAULT_MODEL = 'gemini-2.0-flash';
const MAX_RETRIES = 3;
const INITIAL_RETRY_DELAY_MS = 1000;

// Mapeamento de modelos descontinuados/problematicos para modelos estaveis
const DEPRECATED_MODEL_MAPPING: Record<string, string> = {
  'gemini-1.5-pro': 'gemini-2.0-flash',
  'gemini-1.5-pro-latest': 'gemini-2.0-flash',
  'gemini-1.5-flash': 'gemini-2.0-flash',
  'gemini-1.5-flash-latest': 'gemini-2.0-flash',
  'gemini-1.0-pro': 'gemini-2.0-flash',
  'gemini-pro': 'gemini-2.0-flash',
  'gemini-pro-vision': 'gemini-2.0-flash',
  'gemini-2.5-pro': 'gemini-2.0-flash', // 2.5-pro tendo problemas, usar 2.0-flash
};

function migrateModel(model: string): string {
  if (DEPRECATED_MODEL_MAPPING[model]) {
    console.warn(`[GeminiClient] Model ${model} is deprecated, migrating to ${DEPRECATED_MODEL_MAPPING[model]}`);
    return DEPRECATED_MODEL_MAPPING[model];
  }
  return model;
}

// ============================================================================
// GEMINI CLIENT
// ============================================================================

export class GeminiClient {
  private genAI: GoogleGenerativeAI;
  private model: string;
  private logger: Logger;

  constructor(config: GeminiConfig) {
    if (!config.apiKey) {
      throw new Error('GeminiClient: apiKey is required');
    }

    this.genAI = new GoogleGenerativeAI(config.apiKey);
    this.model = migrateModel(config.model || DEFAULT_MODEL);
    this.logger = createLogger('GeminiClient');

    this.logger.info('Client initialized', { model: this.model });
  }

  /**
   * Envia uma mensagem em formato de chat
   */
  async chat(options: GeminiChatOptions): Promise<GeminiResponse> {
    const { systemPrompt, history, message, maxTokens, temperature } = options;

    this.logger.debug('Starting chat', {
      hasSystemPrompt: !!systemPrompt,
      historyLength: history?.length || 0,
      messageLength: message.length,
    });

    return this.retryWithBackoff(async () => {
      try {
        // Configurar modelo
        const modelConfig: {
          model: string;
          systemInstruction?: string;
          generationConfig?: {
            maxOutputTokens?: number;
            temperature?: number;
          };
        } = {
          model: this.model,
        };

        // Adicionar system instruction se fornecido
        if (systemPrompt) {
          modelConfig.systemInstruction = systemPrompt;
        }

        // Adicionar generation config se fornecidos
        if (maxTokens || temperature !== undefined) {
          modelConfig.generationConfig = {};
          if (maxTokens) {
            modelConfig.generationConfig.maxOutputTokens = maxTokens;
          }
          if (temperature !== undefined) {
            modelConfig.generationConfig.temperature = temperature;
          }
        }

        const generativeModel = this.genAI.getGenerativeModel(modelConfig);

        // Iniciar chat com historico
        const formattedHistory = history || [];
        const chat = generativeModel.startChat({
          history: formattedHistory,
        });

        // Enviar mensagem
        const result = await chat.sendMessage(message);
        const response = result.response;

        // Extrair texto
        const text = response.text();

        // Extrair tokens usados
        const tokensUsed = response.usageMetadata
          ? {
              input: response.usageMetadata.promptTokenCount || 0,
              output: response.usageMetadata.candidatesTokenCount || 0,
            }
          : undefined;

        const sanitizeResult = sanitizeResponse(text);

        this.logger.info('Chat completed', {
          responseLength: sanitizeResult.text.length,
          tokensUsed,
          hadLeakedCode: sanitizeResult.hadLeakedCode,
        });

        return { text: sanitizeResult.text, tokensUsed };

      } catch (error) {
        this.logger.error('Chat failed', {
          error: error instanceof Error ? error.message : error,
        });
        throw error;
      }
    });
  }

  /**
   * Envia uma mensagem com suporte a function calling
   * Executa automaticamente as funções e retorna a resposta final
   */
  async chatWithTools(options: GeminiChatWithToolsOptions): Promise<GeminiResponseWithTools> {
    const { systemPrompt, history, message, maxTokens, temperature, tools, onFunctionCall, functionCallingMode, allowedFunctions } = options;

    this.logger.debug('Starting chat with tools', {
      hasSystemPrompt: !!systemPrompt,
      historyLength: history?.length || 0,
      messageLength: message.length,
      toolsCount: tools?.length || 0,
      functionCallingMode: functionCallingMode || 'AUTO',
    });

    return this.retryWithBackoff(async () => {
      try {
        // Configurar modelo com tools
        const modelConfig: {
          model: string;
          systemInstruction?: string;
          generationConfig?: {
            maxOutputTokens?: number;
            temperature?: number;
          };
          tools?: GeminiTool[];
          toolConfig?: {
            functionCallingConfig: {
              mode: GeminiFunctionCallingMode;
              allowedFunctionNames?: string[];
            };
          };
        } = {
          model: this.model,
        };

        if (systemPrompt) {
          modelConfig.systemInstruction = systemPrompt;
        }

        if (maxTokens || temperature !== undefined) {
          modelConfig.generationConfig = {};
          if (maxTokens) {
            modelConfig.generationConfig.maxOutputTokens = maxTokens;
          }
          if (temperature !== undefined) {
            modelConfig.generationConfig.temperature = temperature;
          }
        }

        // Adicionar tools se fornecidas
        if (tools && tools.length > 0) {
          const geminiTools: GeminiTool[] = [{
            functionDeclarations: tools.map(toGeminiFunctionDeclaration),
          }];
          modelConfig.tools = geminiTools;

          // Adicionar toolConfig se especificado
          if (functionCallingMode) {
            modelConfig.toolConfig = {
              functionCallingConfig: {
                mode: toGeminiFunctionCallingMode(functionCallingMode),
              },
            };

            // Adicionar funções permitidas se modo é ANY e foram especificadas
            if (functionCallingMode === 'ANY' && allowedFunctions && allowedFunctions.length > 0) {
              modelConfig.toolConfig.functionCallingConfig.allowedFunctionNames = allowedFunctions;
            }
          }
        }

        this.logger.debug('Model config', {
          hasTools: !!modelConfig.tools,
          hasToolConfig: !!modelConfig.toolConfig,
          toolConfig: modelConfig.toolConfig,
        });

        const generativeModel = this.genAI.getGenerativeModel(modelConfig);

        // Iniciar chat com historico
        // IMPORTANTE: Gemini exige que primeira mensagem seja do 'user'
        let formattedHistory = history || [];
        if (formattedHistory.length > 0 && formattedHistory[0].role === 'model') {
          this.logger.info('History starts with model, adding user placeholder');
          formattedHistory = [
            { role: 'user' as const, parts: [{ text: '[Início da conversa]' }] },
            ...formattedHistory,
          ];
        }

        const chat = generativeModel.startChat({
          history: formattedHistory,
        });

        // Enviar mensagem inicial
        let result = await chat.sendMessage(message);
        let response = result.response;

        // Loop de processamento de function calls
        let maxIterations = 5; // Limite de segurança
        let iteration = 0;

        while (iteration < maxIterations) {
          iteration++;

          // Verificar se há function calls na resposta
          const candidate = response.candidates?.[0];
          const parts = candidate?.content?.parts || [];

          // Coletar TODAS as function calls (Gemini 2.0 pode retornar múltiplas)
          const functionCallParts: Array<{ functionCall: GeminiFunctionCall }> = [];
          for (const part of parts) {
            if ((part as any).functionCall) {
              functionCallParts.push(part as any);
            }
          }

          if (functionCallParts.length > 0) {
            this.logger.info('Function calls detected', {
              count: functionCallParts.length,
              names: functionCallParts.map(p => p.functionCall.name),
              iteration,
            });

            // Se não temos handler, retornar a primeira function call para processamento externo
            if (!onFunctionCall) {
              this.logger.debug('No onFunctionCall handler, returning first function call');
              return {
                text: '',
                functionCall: functionCallParts[0].functionCall,
                finishReason: 'function_call',
                tokensUsed: response.usageMetadata
                  ? {
                      input: response.usageMetadata.promptTokenCount || 0,
                      output: response.usageMetadata.candidatesTokenCount || 0,
                    }
                  : undefined,
              };
            }

            // Executar TODAS as funções e coletar resultados
            const functionResponses: Array<{ functionResponse: { name: string; response: Record<string, unknown> } }> = [];

            for (const functionCallPart of functionCallParts) {
              const functionCall = functionCallPart.functionCall;

              this.logger.debug('Executing function', { name: functionCall.name });
              const functionResult = await onFunctionCall(functionCall);

              this.logger.debug('Function result', {
                name: functionCall.name,
                resultKeys: Object.keys(functionResult),
              });

              functionResponses.push({
                functionResponse: {
                  name: functionCall.name,
                  response: functionResult,
                },
              });
            }

            // Após executar as funções, precisamos enviar os resultados
            // Se estávamos no modo ANY, criar novo modelo sem forçar função para permitir resposta em texto
            if (functionCallingMode === 'ANY' && iteration === 1) {
              this.logger.debug('Switching from ANY mode to AUTO for response generation');

              // Criar modelo sem toolConfig para permitir resposta em texto
              const responseModelConfig: {
                model: string;
                systemInstruction?: string;
                generationConfig?: {
                  maxOutputTokens?: number;
                  temperature?: number;
                };
                tools?: GeminiTool[];
              } = {
                model: this.model,
              };

              if (systemPrompt) {
                responseModelConfig.systemInstruction = systemPrompt;
              }

              if (maxTokens || temperature !== undefined) {
                responseModelConfig.generationConfig = {};
                if (maxTokens) {
                  responseModelConfig.generationConfig.maxOutputTokens = maxTokens;
                }
                if (temperature !== undefined) {
                  responseModelConfig.generationConfig.temperature = temperature;
                }
              }

              // Manter tools mas sem forçar chamada (modo AUTO implícito)
              if (tools && tools.length > 0) {
                responseModelConfig.tools = [{
                  functionDeclarations: tools.map(toGeminiFunctionDeclaration),
                }];
              }

              const responseModel = this.genAI.getGenerativeModel(responseModelConfig);

              // Reconstruir histórico incluindo TODAS as chamadas de função
              const functionCallHistoryParts = functionCallParts.map(p => ({
                functionCall: { name: p.functionCall.name, args: p.functionCall.args }
              }));

              const fullHistory = [
                ...formattedHistory,
                { role: 'user' as const, parts: [{ text: message }] },
                { role: 'model' as const, parts: functionCallHistoryParts },
              ];

              const responseChat = responseModel.startChat({
                history: fullHistory,
              });

              // Enviar TODOS os resultados das funções
              result = await responseChat.sendMessage(functionResponses as any);
              response = result.response;
            } else {
              // Modo normal - enviar TODOS os resultados das funções de volta para o modelo
              result = await chat.sendMessage(functionResponses as any);
              response = result.response;
            }
          } else {
            // Não há mais function calls, extrair texto
            break;
          }
        }

        // Extrair texto da resposta final
        const text = response.text();
        const sanitizeResult = sanitizeResponse(text);

        const tokensUsed = response.usageMetadata
          ? {
              input: response.usageMetadata.promptTokenCount || 0,
              output: response.usageMetadata.candidatesTokenCount || 0,
            }
          : undefined;

        // Se extraiu uma function call de vazamento e temos handler, tentar executar
        if (sanitizeResult.extractedFunctionCall && onFunctionCall) {
          this.logger.info('Executando function call extraída de vazamento', {
            name: sanitizeResult.extractedFunctionCall.name,
            args: sanitizeResult.extractedFunctionCall.args,
          });

          try {
            const functionResult = await onFunctionCall({
              name: sanitizeResult.extractedFunctionCall.name,
              args: sanitizeResult.extractedFunctionCall.args,
            });

            this.logger.info('Function call extraída executada com sucesso', {
              name: sanitizeResult.extractedFunctionCall.name,
              resultKeys: Object.keys(functionResult),
            });

            // Fazer nova chamada ao modelo para gerar resposta natural baseada no resultado
            this.logger.info('Gerando resposta natural após function call extraída');

            // Reconstruir histórico com a função executada
            const updatedHistory = [
              ...formattedHistory,
              { role: 'user' as const, parts: [{ text: message }] },
              {
                role: 'model' as const,
                parts: [{
                  functionCall: {
                    name: sanitizeResult.extractedFunctionCall.name,
                    args: sanitizeResult.extractedFunctionCall.args
                  }
                }]
              },
            ];

            // Criar modelo sem forçar function calling para resposta em texto
            const responseModelConfig: {
              model: string;
              systemInstruction?: string;
              generationConfig?: { maxOutputTokens?: number; temperature?: number };
              tools?: GeminiTool[];
            } = { model: this.model };

            if (systemPrompt) {
              responseModelConfig.systemInstruction = systemPrompt;
            }
            if (maxTokens || temperature !== undefined) {
              responseModelConfig.generationConfig = {};
              if (maxTokens) responseModelConfig.generationConfig.maxOutputTokens = maxTokens;
              if (temperature !== undefined) responseModelConfig.generationConfig.temperature = temperature;
            }
            if (tools && tools.length > 0) {
              responseModelConfig.tools = [{ functionDeclarations: tools.map(toGeminiFunctionDeclaration) }];
            }

            const responseModel = this.genAI.getGenerativeModel(responseModelConfig);
            const responseChat = responseModel.startChat({ history: updatedHistory });

            // Enviar resultado da função para gerar resposta
            const followUpResult = await responseChat.sendMessage([{
              functionResponse: {
                name: sanitizeResult.extractedFunctionCall.name,
                response: functionResult,
              }
            }]);

            const followUpResponse = followUpResult.response;
            const followUpText = followUpResponse.text();
            const followUpSanitized = sanitizeResponse(followUpText);

            this.logger.info('Resposta natural gerada após function call extraída', {
              responseLength: followUpSanitized.text.length,
            });

            return {
              text: followUpSanitized.text || 'Pronto, já verifiquei as informações.',
              tokensUsed,
              finishReason: 'stop',
            };
          } catch (fnError) {
            this.logger.error('Erro ao executar function call extraída', {
              name: sanitizeResult.extractedFunctionCall.name,
              error: fnError instanceof Error ? fnError.message : fnError,
            });
          }
        }

        this.logger.info('Chat with tools completed', {
          responseLength: sanitizeResult.text.length,
          tokensUsed,
          iterations: iteration,
          hadLeakedCode: sanitizeResult.hadLeakedCode,
        });

        return {
          text: sanitizeResult.text,
          tokensUsed,
          finishReason: 'stop',
        };

      } catch (error) {
        this.logger.error('Chat with tools failed', {
          error: error instanceof Error ? error.message : error,
        });
        throw error;
      }
    });
  }

  /**
   * Envia mensagem com streaming
   */
  async chatStream(options: GeminiStreamOptions): Promise<GeminiResponse> {
    const { systemPrompt, history, message, maxTokens, temperature, onChunk } = options;

    this.logger.debug('Starting streaming chat', {
      hasSystemPrompt: !!systemPrompt,
      messageLength: message.length,
    });

    return this.retryWithBackoff(async () => {
      try {
        const modelConfig: {
          model: string;
          systemInstruction?: string;
          generationConfig?: {
            maxOutputTokens?: number;
            temperature?: number;
          };
        } = {
          model: this.model,
        };

        if (systemPrompt) {
          modelConfig.systemInstruction = systemPrompt;
        }

        if (maxTokens || temperature !== undefined) {
          modelConfig.generationConfig = {};
          if (maxTokens) {
            modelConfig.generationConfig.maxOutputTokens = maxTokens;
          }
          if (temperature !== undefined) {
            modelConfig.generationConfig.temperature = temperature;
          }
        }

        const generativeModel = this.genAI.getGenerativeModel(modelConfig);
        const chat = generativeModel.startChat({
          history: history || [],
        });

        // Enviar com streaming
        const result = await chat.sendMessageStream(message);

        let fullText = '';
        for await (const chunk of result.stream) {
          const chunkText = chunk.text();
          fullText += chunkText;

          if (onChunk) {
            onChunk(chunkText);
          }
        }

        // Obter resposta final para metadata
        const finalResponse = await result.response;
        const tokensUsed = finalResponse.usageMetadata
          ? {
              input: finalResponse.usageMetadata.promptTokenCount || 0,
              output: finalResponse.usageMetadata.candidatesTokenCount || 0,
            }
          : undefined;

        const sanitizeResult = sanitizeResponse(fullText);

        this.logger.info('Streaming chat completed', {
          responseLength: sanitizeResult.text.length,
          tokensUsed,
          hadLeakedCode: sanitizeResult.hadLeakedCode,
        });

        return { text: sanitizeResult.text, tokensUsed };

      } catch (error) {
        this.logger.error('Streaming chat failed', {
          error: error instanceof Error ? error.message : error,
        });
        throw error;
      }
    });
  }

  /**
   * Gera conteudo simples sem chat
   */
  async generateContent(prompt: string): Promise<string> {
    this.logger.debug('Generating content', { promptLength: prompt.length });

    return this.retryWithBackoff(async () => {
      try {
        const generativeModel = this.genAI.getGenerativeModel({
          model: this.model,
        });

        const result = await generativeModel.generateContent(prompt);
        const text = result.response.text();

        this.logger.info('Content generated', { responseLength: text.length });

        return text;

      } catch (error) {
        this.logger.error('Content generation failed', {
          error: error instanceof Error ? error.message : error,
        });
        throw error;
      }
    });
  }

  /**
   * Gera conteudo com imagem (multimodal)
   */
  async generateContentWithImage(
    prompt: string,
    imageBase64: string,
    mimeType: string = 'image/jpeg'
  ): Promise<string> {
    this.logger.debug('Generating content with image', {
      promptLength: prompt.length,
      mimeType,
    });

    return this.retryWithBackoff(async () => {
      try {
        const generativeModel = this.genAI.getGenerativeModel({
          model: this.model,
        });

        const result = await generativeModel.generateContent([
          prompt,
          {
            inlineData: {
              mimeType,
              data: imageBase64,
            },
          },
        ]);

        const text = result.response.text();

        this.logger.info('Content with image generated', {
          responseLength: text.length,
        });

        return text;

      } catch (error) {
        this.logger.error('Content with image generation failed', {
          error: error instanceof Error ? error.message : error,
        });
        throw error;
      }
    });
  }

  /**
   * Converte historico para formato Gemini
   */
  formatHistory(messages: Array<{ role: string; content: string }>): GeminiMessage[] {
    return messages.map((msg) => ({
      role: msg.role === 'assistant' || msg.role === 'model' ? 'model' : 'user',
      parts: [{ text: msg.content }],
    }));
  }

  /**
   * Executa operacao com retry e backoff exponencial
   */
  private async retryWithBackoff<T>(
    fn: () => Promise<T>,
    maxRetries: number = MAX_RETRIES
  ): Promise<T> {
    let lastError: Error | null = null;

    for (let attempt = 1; attempt <= maxRetries; attempt++) {
      try {
        return await fn();
      } catch (error) {
        lastError = error instanceof Error ? error : new Error(String(error));

        // Verificar se e erro retryable
        if (!this.isRetryableError(error)) {
          this.logger.error('Non-retryable error', { error: lastError.message });
          throw lastError;
        }

        if (attempt < maxRetries) {
          // Backoff exponencial: 1s, 2s, 4s
          const delay = INITIAL_RETRY_DELAY_MS * Math.pow(2, attempt - 1);

          this.logger.warn(`Attempt ${attempt} failed, retrying in ${delay}ms`, {
            error: lastError.message,
          });

          await this.delay(delay);
        }
      }
    }

    this.logger.error('All retry attempts failed', { error: lastError?.message });
    throw lastError;
  }

  /**
   * Verifica se o erro e recuperavel (retry)
   */
  private isRetryableError(error: unknown): boolean {
    if (error instanceof Error) {
      const message = error.message.toLowerCase();

      // Erros de rate limit
      if (message.includes('429') || message.includes('rate limit') || message.includes('quota')) {
        return true;
      }

      // Erros de servidor
      if (
        message.includes('500') ||
        message.includes('502') ||
        message.includes('503') ||
        message.includes('504')
      ) {
        return true;
      }

      // Erros de rede
      if (
        message.includes('econnreset') ||
        message.includes('etimedout') ||
        message.includes('enotfound') ||
        message.includes('socket hang up') ||
        message.includes('network')
      ) {
        return true;
      }

      // Erro temporario do Gemini
      if (message.includes('temporarily unavailable') || message.includes('overloaded')) {
        return true;
      }
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
    this.logger.info('Model updated', { model });
  }

  /**
   * Retorna o modelo atual
   */
  getModel(): string {
    return this.model;
  }

  /**
   * Conta tokens de um texto (estimativa)
   */
  async countTokens(text: string): Promise<number> {
    try {
      const generativeModel = this.genAI.getGenerativeModel({ model: this.model });
      const result = await generativeModel.countTokens(text);
      return result.totalTokens;
    } catch (error) {
      this.logger.warn('Token counting failed, using estimate', {
        error: error instanceof Error ? error.message : error,
      });
      // Estimativa: ~4 caracteres por token
      return Math.ceil(text.length / 4);
    }
  }

  /**
   * Lista modelos disponiveis
   */
  async listModels(): Promise<string[]> {
    // Modelos Gemini atuais (fevereiro 2026)
    return [
      'gemini-2.5-pro',
      'gemini-2.5-flash',
      'gemini-2.0-flash',
    ];
  }
}

// ============================================================================
// FACTORY FUNCTION
// ============================================================================

/**
 * Factory function para criar cliente Gemini
 */
export function createGeminiClient(config: GeminiConfig): GeminiClient {
  return new GeminiClient(config);
}
