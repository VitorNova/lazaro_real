// ============================================================================
// CLAUDE MESSAGE TYPES
// ============================================================================

export type MessageRole = 'user' | 'assistant';

export interface ClaudeMessage {
  role: MessageRole;
  content: string | ContentBlock[];
}

// ============================================================================
// CONTENT BLOCKS
// ============================================================================

export type ContentBlock =
  | TextBlock
  | ImageBlock
  | ToolUseBlock
  | ToolResultBlock
  | ThinkingBlock;

export interface ThinkingBlock {
  type: 'thinking';
  thinking: string;
}

export interface TextBlock {
  type: 'text';
  text: string;
}

export interface ImageBlock {
  type: 'image';
  source: ImageSource;
}

export interface ImageSource {
  type: 'base64';
  media_type: 'image/jpeg' | 'image/png' | 'image/gif' | 'image/webp';
  data: string;
}

// ============================================================================
// TOOL TYPES
// ============================================================================

export interface ToolDefinition {
  name: string;
  description: string;
  input_schema: {
    type: 'object';
    properties: Record<string, PropertySchema>;
    required?: string[];
  };
}

export interface PropertySchema {
  type: 'string' | 'number' | 'boolean' | 'array' | 'object';
  description?: string;
  enum?: string[];
  items?: PropertySchema;
  properties?: Record<string, PropertySchema>;
  required?: string[];
}

export interface ToolUseBlock {
  type: 'tool_use';
  id: string;
  name: string;
  input: Record<string, unknown>;
}

export interface ToolResultBlock {
  type: 'tool_result';
  tool_use_id: string;
  content: string | ContentBlock[];
  is_error?: boolean;
}

// ============================================================================
// CLAUDE RESPONSE
// ============================================================================

export interface ClaudeResponse {
  id: string;
  type: 'message';
  role: 'assistant';
  content: ContentBlock[];
  model: string;
  stop_reason: StopReason;
  stop_sequence: string | null;
  usage: Usage;
}

export type StopReason = 'end_turn' | 'max_tokens' | 'stop_sequence' | 'tool_use';

export interface Usage {
  input_tokens: number;
  output_tokens: number;
}

// ============================================================================
// REQUEST PARAMS
// ============================================================================

export interface ThinkingConfig {
  type: 'enabled';
  budget_tokens: number;
}

export interface SendMessageParams {
  systemPrompt: string;
  messages: ClaudeMessage[];
  tools?: ToolDefinition[];
  maxTokens?: number;
  temperature?: number;
  stopSequences?: string[];
  thinking?: ThinkingConfig;
}

export interface SendWithToolsParams {
  systemPrompt: string;
  messages: ClaudeMessage[];
  tools: ToolDefinition[];
  maxTokens?: number;
  temperature?: number;
  toolChoice?: ToolChoice;
  thinking?: ThinkingConfig;
}

export type ToolChoice =
  | { type: 'auto' }
  | { type: 'any' }
  | { type: 'tool'; name: string };

// ============================================================================
// WHISPER TYPES
// ============================================================================

export interface TranscriptionParams {
  audioBase64: string;
  mimeType: string;
  language?: string;
  prompt?: string;
}

export interface TranscriptionResult {
  text: string;
  language?: string;
  duration?: number;
}

// ============================================================================
// HELPERS
// ============================================================================

/**
 * Extrai o texto de uma resposta do Claude
 */
export function extractTextFromResponse(response: ClaudeResponse): string {
  const textBlocks = response.content.filter(
    (block): block is TextBlock => block.type === 'text'
  );

  return textBlocks.map((block) => block.text).join('\n');
}

/**
 * Extrai tool uses de uma resposta do Claude
 */
export function extractToolUses(response: ClaudeResponse): ToolUseBlock[] {
  return response.content.filter(
    (block): block is ToolUseBlock => block.type === 'tool_use'
  );
}

/**
 * Extrai thinking blocks de uma resposta do Claude
 */
export function extractThinking(response: ClaudeResponse): string {
  const thinkingBlocks = response.content.filter(
    (block): block is ThinkingBlock => block.type === 'thinking'
  );
  return thinkingBlocks.map((block) => block.thinking).join('\n');
}

/**
 * Verifica se a resposta contém tool uses
 */
export function hasToolUse(response: ClaudeResponse): boolean {
  return response.stop_reason === 'tool_use';
}

/**
 * Cria um bloco de texto
 */
export function createTextBlock(text: string): TextBlock {
  return { type: 'text', text };
}

/**
 * Cria um bloco de imagem
 */
export function createImageBlock(
  base64: string,
  mediaType: ImageSource['media_type']
): ImageBlock {
  return {
    type: 'image',
    source: {
      type: 'base64',
      media_type: mediaType,
      data: base64,
    },
  };
}

/**
 * Cria um bloco de resultado de tool
 */
export function createToolResult(
  toolUseId: string,
  content: string,
  isError: boolean = false
): ToolResultBlock {
  return {
    type: 'tool_result',
    tool_use_id: toolUseId,
    content,
    is_error: isError,
  };
}
