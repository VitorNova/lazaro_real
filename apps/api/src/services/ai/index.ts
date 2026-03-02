// Claude Client
export { ClaudeClient, createClaudeClient } from './claude';

// Gemini Client
export {
  GeminiClient,
  createGeminiClient,
  type GeminiConfig,
  type GeminiMessage,
  type GeminiChatOptions,
  type GeminiResponse,
  type GeminiStreamOptions,
} from './gemini-client';

// OpenAI Client
export {
  OpenAIClient,
  createOpenAIClient,
  type OpenAIConfig,
  type OpenAIMessage,
  type OpenAIChatOptions,
  type OpenAIResponse,
} from './openai-client';

// Unified AI Factory
export {
  UnifiedAIClient,
  createAIClient,
  createAIClientFromAgent,
  AI_MODELS,
  DEFAULT_MODELS,
  type AIProvider,
  type AIConfig,
  type AIMessage,
  type AIChatOptions,
  type AIResponse,
  type AIFunctionDeclaration,
  type AIFunctionCall,
  type AIFunctionCallingMode,
  type AIChatWithToolsOptions,
  type AIResponseWithTools,
} from './ai-factory';

// Whisper Client
export { WhisperClient, createWhisperClient } from './whisper';

// Types
export {
  // Message Types
  type MessageRole,
  type ClaudeMessage,
  type ClaudeResponse,
  type StopReason,
  type Usage,

  // Content Blocks
  type ContentBlock,
  type TextBlock,
  type ImageBlock,
  type ImageSource,

  // Tool Types
  type ToolDefinition,
  type PropertySchema,
  type ToolUseBlock,
  type ToolResultBlock,
  type ToolChoice,

  // Request Params
  type SendMessageParams,
  type SendWithToolsParams,

  // Whisper Types
  type TranscriptionParams,
  type TranscriptionResult,

  // Helper Functions
  extractTextFromResponse,
  extractToolUses,
  hasToolUse,
  createTextBlock,
  createImageBlock,
  createToolResult,
} from './types';
