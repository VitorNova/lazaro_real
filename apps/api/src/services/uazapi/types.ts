// ============================================================================
// CONFIGURAÇÃO
// ============================================================================

export interface UazapiConfig {
  baseUrl: string;
  instance?: string;
  apiKey?: string;
  // Novos campos para UazapiGo
  instanceToken?: string; // Token específico da instância
  adminToken?: string;    // Token admin para criar instâncias
}

// ============================================================================
// PAYLOADS DE ENVIO
// ============================================================================

export interface SendTextPayload {
  number: string;
  text: string;
  delay?: number;
}

export interface SendMediaPayload {
  number: string;
  media: string; // base64 ou URL
  caption?: string;
  fileName?: string;
}

export interface SendAudioPayload {
  number: string;
  audio: string; // base64
  ptt?: boolean; // push to talk (áudio de voz)
}

export interface SendDocumentPayload {
  number: string;
  document: string; // base64
  fileName: string;
  caption?: string;
}

export interface SendButtonsPayload {
  number: string;
  title: string;
  description: string;
  footer?: string;
  buttons: Array<{
    buttonId: string;
    buttonText: { displayText: string };
    type: number;
  }>;
}

export interface SendListPayload {
  number: string;
  title: string;
  description: string;
  buttonText: string;
  footerText?: string;
  sections: Array<{
    title: string;
    rows: Array<{
      title: string;
      description?: string;
      rowId: string;
    }>;
  }>;
}

export interface SendContactPayload {
  number: string;
  fullName: string;
  phoneNumber: string; // Múltiplos números separados por vírgula
  organization?: string;
  email?: string;
  url?: string;
  delay?: number;
}

// ============================================================================
// RESPOSTAS DA API
// ============================================================================

export interface SendMessageResponse {
  id?: string;
  messageid?: string;
  chatid?: string;
  fromMe?: boolean;
  isGroup?: boolean;
  messageType?: string;
  messageTimestamp?: number;
  sender?: string;
  senderName?: string;
  status?: string;
  text?: string;
  fileURL?: string;
  // Formato legado (compatibilidade)
  key?: {
    remoteJid: string;
    fromMe: boolean;
    id: string;
  };
  message?: Record<string, unknown>;
  response?: {
    status: string;
    message: string;
  };
}

export interface InstanceStatusResponse {
  instance: {
    instanceName: string;
    state: 'open' | 'close' | 'connecting';
  };
}

export interface MediaBase64Response {
  base64: string;
  mimetype: string;
}

// ============================================================================
// WEBHOOK - ESTRUTURA RECEBIDA
// ============================================================================

export interface WebhookPayload {
  event?: string;
  instance?: string;
  data?: WebhookData;
  // Estrutura alternativa (algumas versões)
  key?: MessageKey;
  message?: WebhookMessage;
  messageTimestamp?: number | string;
  pushName?: string;
  messageType?: string;
}

export interface WebhookData {
  key: MessageKey;
  pushName?: string;
  message?: WebhookMessage;
  messageType?: string;
  messageTimestamp?: number | string;
  owner?: string;
  source?: string;
}

export interface MessageKey {
  remoteJid: string;
  fromMe: boolean;
  id: string;
  participant?: string;
}

export interface WebhookMessage {
  conversation?: string;
  extendedTextMessage?: {
    text: string;
    contextInfo?: ContextInfo;
  };
  imageMessage?: {
    url?: string;
    mimetype?: string;
    caption?: string;
    fileSha256?: string;
    fileLength?: string;
    mediaKey?: string;
    jpegThumbnail?: string;
  };
  audioMessage?: {
    url?: string;
    mimetype?: string;
    fileSha256?: string;
    fileLength?: string;
    seconds?: number;
    ptt?: boolean;
    mediaKey?: string;
  };
  videoMessage?: {
    url?: string;
    mimetype?: string;
    caption?: string;
    fileSha256?: string;
    fileLength?: string;
    seconds?: number;
    mediaKey?: string;
    jpegThumbnail?: string;
  };
  documentMessage?: {
    url?: string;
    mimetype?: string;
    title?: string;
    fileSha256?: string;
    fileLength?: string;
    mediaKey?: string;
    fileName?: string;
  };
  stickerMessage?: {
    url?: string;
    mimetype?: string;
    fileSha256?: string;
    fileLength?: string;
    mediaKey?: string;
  };
  locationMessage?: {
    degreesLatitude?: number;
    degreesLongitude?: number;
    name?: string;
    address?: string;
  };
  contactMessage?: {
    displayName?: string;
    vcard?: string;
  };
  buttonsResponseMessage?: {
    selectedButtonId?: string;
    selectedDisplayText?: string;
  };
  listResponseMessage?: {
    title?: string;
    listType?: number;
    singleSelectReply?: {
      selectedRowId?: string;
    };
  };
}

export interface ContextInfo {
  stanzaId?: string;
  participant?: string;
  quotedMessage?: WebhookMessage;
}

// ============================================================================
// MENSAGEM PARSEADA (SAÍDA DO PARSER)
// ============================================================================

export type ParsedMessageType =
  | 'text'
  | 'audio'
  | 'image'
  | 'video'
  | 'document'
  | 'sticker'
  | 'location'
  | 'contact'
  | 'button_response'
  | 'list_response'
  | 'unknown';

export interface MessageReceived {
  remoteJid: string;
  fromMe: boolean;
  messageId: string;
  messageType: ParsedMessageType;
  pushName?: string;
  timestamp: number;
  content: MessageContent;
  quotedMessage?: QuotedMessage;
  participant?: string; // Para mensagens de grupo
  isGroup: boolean;
}

export interface MessageContent {
  text?: string;
  caption?: string;
  url?: string;
  mimetype?: string;
  fileName?: string;
  fileLength?: number;
  seconds?: number;
  latitude?: number;
  longitude?: number;
  locationName?: string;
  address?: string;
  displayName?: string;
  vcard?: string;
  selectedButtonId?: string;
  selectedRowId?: string;
  base64?: string;
  mediaKey?: string;
}

export interface QuotedMessage {
  messageId: string;
  participant?: string;
  content: MessageContent;
}

// ============================================================================
// TIPOS DE EVENTOS DO WEBHOOK
// ============================================================================

// ============================================================================
// CAMPANHA EM MASSA (SENDER)
// ============================================================================

export interface UazapiCampaignMessage {
  number: string;      // formato: 5566997194084 (sem @s.whatsapp.net)
  type: 'text';        // tipo da mensagem
  text: string;        // mensagem personalizada
}

export interface UazapiCampaignRequest {
  delayMin: number;           // delay mínimo em segundos (ex: 30)
  delayMax: number;           // delay máximo em segundos (ex: 60)
  info: string;               // nome da campanha
  scheduled_for: number;      // minutos para iniciar (1 = iniciar em 1 minuto)
  messages: UazapiCampaignMessage[];
}

export interface UazapiCampaignResponse {
  folder_id: string;
  count: number;
  status: 'queued' | string;
}

export interface UazapiCampaignFolder {
  id: string;
  info: string;
  status: string;
  count: number;
  sent: number;
  failed: number;
  created_at: string;
}

export interface UazapiCampaignEditRequest {
  folder_id: string;
  action: 'stop' | 'continue' | 'delete';
}

// ============================================================================
// CAMPANHA SIMPLES (SENDER/SIMPLE)
// ============================================================================

export type SimpleCampaignMessageType =
  | 'text'
  | 'image'
  | 'video'
  | 'audio'
  | 'document'
  | 'contact'
  | 'location'
  | 'list'
  | 'button'
  | 'poll'
  | 'carousel';

export interface SimpleCampaignRequest {
  // Campos obrigatórios
  numbers: string[];           // Lista de números (formato: 5511999999999@s.whatsapp.net)
  type: SimpleCampaignMessageType;
  delayMin: number;            // Delay mínimo entre mensagens em segundos
  delayMax: number;            // Delay máximo entre mensagens em segundos
  scheduled_for: number;       // Timestamp em ms ou minutos a partir de agora

  // Campos opcionais
  folder?: string;             // Nome da campanha
  info?: string;               // Informações adicionais
  delay?: number;              // Delay fixo (opcional)

  // Campos para type = 'text'
  text?: string;               // Texto da mensagem
  linkPreview?: boolean;       // Habilitar preview de links
  linkPreviewTitle?: string;
  linkPreviewDescription?: string;
  linkPreviewImage?: string;
  linkPreviewLarge?: boolean;
  mentions?: string;           // Menções em formato JSON

  // Campos para mídia (image, video, audio, document)
  file?: string;               // URL da mídia ou base64
  docName?: string;            // Nome do arquivo (document)

  // Campos para type = 'contact'
  fullName?: string;
  phoneNumber?: string;
  organization?: string;
  email?: string;
  url?: string;

  // Campos para type = 'location'
  latitude?: number;
  longitude?: number;
  name?: string;
  address?: string;

  // Campos para type = 'list', 'button', 'poll', 'carousel'
  footerText?: string;
  buttonText?: string;
  listButton?: string;
  selectableCount?: number;    // Para poll
  choices?: string[];          // Opções
  imageButton?: string;        // URL da imagem para botão
}

export interface SimpleCampaignResponse {
  folder_id: string;
  count: number;
  status: 'queued' | string;
}

export interface CampaignFolderDetails {
  id: string;
  info: string;
  status: 'scheduled' | 'sending' | 'paused' | 'done' | 'deleting' | string;
  scheduled_for: number;
  delayMin: number;
  delayMax: number;
  log_delivered: number;
  log_failed: number;
  log_played: number;
  log_read: number;
  log_sucess: number;
  log_total: number;
  owner: string;
  created: string;
  updated: string;
}

export interface CampaignMessage {
  id: string;
  messageid?: string;
  chatid: string;
  sender: string;
  senderName?: string;
  isGroup: boolean;
  fromMe: boolean;
  messageType: string;
  source?: string;
  messageTimestamp: number;
  status: 'Scheduled' | 'Sent' | 'Failed' | string;
  text?: string;
  error?: string;
  send_folder_id: string;
}

export interface ListCampaignMessagesRequest {
  folder_id: string;
  messageStatus?: 'Scheduled' | 'Sent' | 'Failed';
  page?: number;
  pageSize?: number;
}

export interface ListCampaignMessagesResponse {
  messages: CampaignMessage[];
  pagination: {
    total: number;
    page: number;
    pageSize: number;
    lastPage: number;
  };
}

export enum WebhookEventType {
  MESSAGES_UPSERT = 'messages.upsert',
  MESSAGES_UPDATE = 'messages.update',
  MESSAGES_DELETE = 'messages.delete',
  SEND_MESSAGE = 'send.message',
  CONNECTION_UPDATE = 'connection.update',
  QRCODE_UPDATED = 'qrcode.updated',
  PRESENCE_UPDATE = 'presence.update',
  CHATS_SET = 'chats.set',
  CHATS_UPDATE = 'chats.update',
  CONTACTS_SET = 'contacts.set',
  CONTACTS_UPDATE = 'contacts.update',
  GROUPS_UPSERT = 'groups.upsert',
  GROUPS_UPDATE = 'groups.update',
}
