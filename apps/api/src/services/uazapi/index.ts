// Client
export {
  UazapiClient,
  createUazapiClient,
  type UazapiInstance,
  type UazapiQRCode,
  type UazapiConnectionStatus,
  type UazapiWebhookConfig,
  type CreateInstanceResponse,
} from './client';

// Webhook Parser
export {
  parseWebhookPayload,
  extractPhoneNumber,
  isGroupJid,
  formatToRemoteJid,
  isMediaMessage,
  isTextMessage,
} from './webhook-parser';

// Types
export {
  // Config
  type UazapiConfig,

  // Send Payloads
  type SendTextPayload,
  type SendMediaPayload,
  type SendAudioPayload,
  type SendDocumentPayload,
  type SendButtonsPayload,
  type SendListPayload,

  // API Responses
  type SendMessageResponse,
  type InstanceStatusResponse,
  type MediaBase64Response,

  // Webhook Types
  type WebhookPayload,
  type WebhookData,
  type WebhookMessage,
  type MessageKey,
  type ContextInfo,
  WebhookEventType,

  // Parsed Message
  type ParsedMessageType,
  type MessageReceived,
  type MessageContent,
  type QuotedMessage,
} from './types';
