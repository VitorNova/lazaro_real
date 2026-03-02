import {
  WebhookPayload,
  WebhookData,
  WebhookMessage,
  MessageReceived,
  MessageContent,
  ParsedMessageType,
  QuotedMessage,
  WebhookEventType,
} from './types';

/**
 * Parseia o payload do webhook da UAZAPI e retorna uma mensagem estruturada
 * Retorna null se não for uma mensagem válida para processar
 */
export function parseWebhookPayload(body: unknown): MessageReceived | null {
  try {
    const payload = body as WebhookPayload;

    // Verificar se é um evento de mensagem
    if (!isMessageEvent(payload)) {
      return null;
    }

    // Extrair dados da mensagem (diferentes estruturas possíveis)
    const data = extractMessageData(payload);
    if (!data) {
      return null;
    }

    const { key, message, pushName, messageTimestamp } = data;

    // Ignorar mensagens enviadas pelo próprio bot
    if (key.fromMe) {
      return null;
    }

    // Ignorar se não houver mensagem
    if (!message) {
      return null;
    }

    // Detectar tipo de mensagem e extrair conteúdo
    const { messageType, content } = parseMessageContent(message);

    // Ignorar tipos de mensagem não suportados
    if (messageType === 'unknown') {
      return null;
    }

    // Extrair mensagem citada (se houver)
    const quotedMessage = extractQuotedMessage(message);

    // Verificar se é grupo
    const isGroup = key.remoteJid.endsWith('@g.us');

    // Converter timestamp
    const timestamp = typeof messageTimestamp === 'string'
      ? parseInt(messageTimestamp, 10)
      : messageTimestamp || Math.floor(Date.now() / 1000);

    return {
      remoteJid: key.remoteJid,
      fromMe: key.fromMe,
      messageId: key.id,
      messageType,
      pushName,
      timestamp,
      content,
      quotedMessage,
      participant: key.participant,
      isGroup,
    };
  } catch (error) {
    console.error('[WebhookParser] Error parsing webhook payload:', error);
    return null;
  }
}

/**
 * Verifica se o payload é um evento de mensagem válido
 */
function isMessageEvent(payload: WebhookPayload): boolean {
  // Estrutura com event
  if (payload.event) {
    return (
      payload.event === WebhookEventType.MESSAGES_UPSERT ||
      payload.event === 'messages.upsert'
    );
  }

  // Estrutura direta (sem event wrapper)
  if (payload.key && payload.message) {
    return true;
  }

  // Estrutura com data
  if (payload.data?.key && payload.data?.message) {
    return true;
  }

  return false;
}

/**
 * Extrai os dados da mensagem do payload (suporta diferentes estruturas)
 */
function extractMessageData(payload: WebhookPayload): WebhookData | null {
  // Estrutura com data wrapper
  if (payload.data?.key) {
    return payload.data;
  }

  // Estrutura direta
  if (payload.key && payload.message) {
    return {
      key: payload.key,
      message: payload.message,
      pushName: payload.pushName,
      messageTimestamp: payload.messageTimestamp,
      messageType: payload.messageType,
    };
  }

  return null;
}

/**
 * Parseia o conteúdo da mensagem e detecta o tipo
 */
function parseMessageContent(message: WebhookMessage): {
  messageType: ParsedMessageType;
  content: MessageContent;
} {
  // Texto simples (conversation)
  if (message.conversation) {
    return {
      messageType: 'text',
      content: { text: message.conversation },
    };
  }

  // Texto estendido (com formatação ou citação)
  if (message.extendedTextMessage?.text) {
    return {
      messageType: 'text',
      content: { text: message.extendedTextMessage.text },
    };
  }

  // Imagem
  if (message.imageMessage) {
    return {
      messageType: 'image',
      content: {
        caption: message.imageMessage.caption,
        url: message.imageMessage.url,
        mimetype: message.imageMessage.mimetype,
        mediaKey: message.imageMessage.mediaKey,
      },
    };
  }

  // Áudio
  if (message.audioMessage) {
    return {
      messageType: 'audio',
      content: {
        url: message.audioMessage.url,
        mimetype: message.audioMessage.mimetype,
        seconds: message.audioMessage.seconds,
        mediaKey: message.audioMessage.mediaKey,
      },
    };
  }

  // Vídeo
  if (message.videoMessage) {
    return {
      messageType: 'video',
      content: {
        caption: message.videoMessage.caption,
        url: message.videoMessage.url,
        mimetype: message.videoMessage.mimetype,
        seconds: message.videoMessage.seconds,
        mediaKey: message.videoMessage.mediaKey,
      },
    };
  }

  // Documento
  if (message.documentMessage) {
    return {
      messageType: 'document',
      content: {
        url: message.documentMessage.url,
        mimetype: message.documentMessage.mimetype,
        fileName: message.documentMessage.fileName || message.documentMessage.title,
        fileLength: message.documentMessage.fileLength
          ? parseInt(message.documentMessage.fileLength, 10)
          : undefined,
        mediaKey: message.documentMessage.mediaKey,
      },
    };
  }

  // Sticker
  if (message.stickerMessage) {
    return {
      messageType: 'sticker',
      content: {
        url: message.stickerMessage.url,
        mimetype: message.stickerMessage.mimetype,
        mediaKey: message.stickerMessage.mediaKey,
      },
    };
  }

  // Localização
  if (message.locationMessage) {
    return {
      messageType: 'location',
      content: {
        latitude: message.locationMessage.degreesLatitude,
        longitude: message.locationMessage.degreesLongitude,
        locationName: message.locationMessage.name,
        address: message.locationMessage.address,
      },
    };
  }

  // Contato
  if (message.contactMessage) {
    return {
      messageType: 'contact',
      content: {
        displayName: message.contactMessage.displayName,
        vcard: message.contactMessage.vcard,
      },
    };
  }

  // Resposta de botão
  if (message.buttonsResponseMessage) {
    return {
      messageType: 'button_response',
      content: {
        text: message.buttonsResponseMessage.selectedDisplayText,
        selectedButtonId: message.buttonsResponseMessage.selectedButtonId,
      },
    };
  }

  // Resposta de lista
  if (message.listResponseMessage) {
    return {
      messageType: 'list_response',
      content: {
        text: message.listResponseMessage.title,
        selectedRowId: message.listResponseMessage.singleSelectReply?.selectedRowId,
      },
    };
  }

  // Tipo desconhecido
  return {
    messageType: 'unknown',
    content: {},
  };
}

/**
 * Extrai a mensagem citada (se houver)
 */
function extractQuotedMessage(message: WebhookMessage): QuotedMessage | undefined {
  const contextInfo = message.extendedTextMessage?.contextInfo;

  if (!contextInfo?.quotedMessage || !contextInfo.stanzaId) {
    return undefined;
  }

  const { messageType, content } = parseMessageContent(contextInfo.quotedMessage);

  return {
    messageId: contextInfo.stanzaId,
    participant: contextInfo.participant,
    content,
  };
}

/**
 * Extrai o número de telefone limpo do remoteJid
 */
export function extractPhoneNumber(remoteJid: string): string {
  return remoteJid.replace(/@s\.whatsapp\.net$/, '').replace(/@g\.us$/, '');
}

/**
 * Verifica se o remoteJid é um grupo
 */
export function isGroupJid(remoteJid: string): boolean {
  return remoteJid.endsWith('@g.us');
}

/**
 * Formata um número para remoteJid
 */
export function formatToRemoteJid(phone: string, isGroup: boolean = false): string {
  const cleaned = phone.replace(/\D/g, '');
  return isGroup ? `${cleaned}@g.us` : `${cleaned}@s.whatsapp.net`;
}

/**
 * Verifica se a mensagem é de mídia (precisa baixar)
 */
export function isMediaMessage(messageType: ParsedMessageType): boolean {
  return ['audio', 'image', 'video', 'document', 'sticker'].includes(messageType);
}

/**
 * Verifica se a mensagem é de texto
 */
export function isTextMessage(messageType: ParsedMessageType): boolean {
  return ['text', 'button_response', 'list_response'].includes(messageType);
}
