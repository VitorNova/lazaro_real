// ============================================================================
// MESSAGE TRACKING REPOSITORY
// Rastreia TODAS as mensagens geradas pela IA e seu status de envio
// Permite retry automatico e alertas para mensagens que falharam
// ============================================================================

import { SupabaseClient } from '@supabase/supabase-js';
import { supabaseAdmin } from '../client';

// ============================================================================
// TYPES
// ============================================================================

export type MessageTrackingStatus = 'pending' | 'sending' | 'sent' | 'failed' | 'retry';

export interface MessageTracking {
  id: string;
  agent_id: string;
  remote_jid: string;
  lead_id?: number;
  message_content: string;
  message_type: 'text' | 'audio' | 'image' | 'video' | 'document';
  status: MessageTrackingStatus;
  attempts: number;
  max_attempts: number;
  last_attempt_at?: string;
  last_error?: string;
  sent_at?: string;
  uazapi_message_id?: string;
  correlation_id: string; // ID unico para rastrear a mensagem em todos os logs
  metadata?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface MessageTrackingCreate {
  agent_id: string;
  remote_jid: string;
  lead_id?: number;
  message_content: string;
  message_type?: 'text' | 'audio' | 'image' | 'video' | 'document';
  correlation_id?: string;
  metadata?: Record<string, unknown>;
}

export interface MessageTrackingUpdate {
  status?: MessageTrackingStatus;
  attempts?: number;
  last_attempt_at?: string;
  last_error?: string;
  sent_at?: string;
  uazapi_message_id?: string;
  metadata?: Record<string, unknown>;
}

// ============================================================================
// LOGGER
// ============================================================================

const Logger = {
  info: (message: string, data?: unknown) => {
    console.log(`[MessageTracking] ${message}`, data ? JSON.stringify(data, null, 2) : '');
  },
  error: (message: string, error?: unknown) => {
    console.error(`[MessageTracking] ${message}`, error);
  },
  warn: (message: string, data?: unknown) => {
    console.warn(`[MessageTracking] ${message}`, data ? JSON.stringify(data, null, 2) : '');
  },
  debug: (message: string, data?: unknown) => {
    if (process.env.DEBUG === 'true') {
      console.log(`[MessageTracking:DEBUG] ${message}`, data ? JSON.stringify(data, null, 2) : '');
    }
  },
};

// ============================================================================
// REPOSITORY
// ============================================================================

export class MessageTrackingRepository {
  private supabase: SupabaseClient;
  private tableName = 'message_tracking';

  constructor(supabase?: SupabaseClient) {
    this.supabase = supabase || supabaseAdmin;
  }

  /**
   * Gera um correlation ID unico para rastreamento
   */
  generateCorrelationId(): string {
    const timestamp = Date.now().toString(36);
    const random = Math.random().toString(36).substring(2, 8);
    return `msg_${timestamp}_${random}`;
  }

  /**
   * Cria um novo registro de tracking para uma mensagem
   */
  async create(data: MessageTrackingCreate): Promise<MessageTracking | null> {
    try {
      const now = new Date().toISOString();
      const correlationId = data.correlation_id || this.generateCorrelationId();

      const trackingData = {
        agent_id: data.agent_id,
        remote_jid: data.remote_jid,
        lead_id: data.lead_id,
        message_content: data.message_content,
        message_type: data.message_type || 'text',
        status: 'pending' as MessageTrackingStatus,
        attempts: 0,
        max_attempts: 3,
        correlation_id: correlationId,
        metadata: data.metadata || {},
        created_at: now,
        updated_at: now,
      };

      Logger.info('Creating message tracking', {
        correlationId,
        agentId: data.agent_id,
        remoteJid: data.remote_jid,
        contentLength: data.message_content.length,
      });

      const { data: tracking, error } = await this.supabase
        .from(this.tableName)
        .insert(trackingData)
        .select()
        .single();

      if (error) {
        Logger.error('Error creating message tracking', error);
        return null;
      }

      Logger.info('Message tracking created', { id: tracking.id, correlationId });
      return tracking;
    } catch (error) {
      Logger.error('Exception creating message tracking', error);
      return null;
    }
  }

  /**
   * Atualiza o status de uma mensagem
   */
  async update(id: string, data: MessageTrackingUpdate): Promise<MessageTracking | null> {
    try {
      const updateData = {
        ...data,
        updated_at: new Date().toISOString(),
      };

      const { data: tracking, error } = await this.supabase
        .from(this.tableName)
        .update(updateData)
        .eq('id', id)
        .select()
        .single();

      if (error) {
        Logger.error('Error updating message tracking', { id, error });
        return null;
      }

      Logger.debug('Message tracking updated', { id, status: data.status });
      return tracking;
    } catch (error) {
      Logger.error('Exception updating message tracking', error);
      return null;
    }
  }

  /**
   * Marca uma mensagem como enviando (status = 'sending')
   */
  async markSending(id: string): Promise<MessageTracking | null> {
    return this.update(id, {
      status: 'sending',
      last_attempt_at: new Date().toISOString(),
    });
  }

  /**
   * Marca uma mensagem como enviada com sucesso
   */
  async markSent(id: string, uazapiMessageId?: string): Promise<MessageTracking | null> {
    const now = new Date().toISOString();
    return this.update(id, {
      status: 'sent',
      sent_at: now,
      uazapi_message_id: uazapiMessageId,
    });
  }

  /**
   * Marca uma mensagem como falha
   * Se ainda houver tentativas disponiveis, marca como 'retry'
   */
  async markFailed(id: string, error: string, currentAttempts: number): Promise<MessageTracking | null> {
    const now = new Date().toISOString();

    // Buscar mensagem para verificar max_attempts
    const { data: existing } = await this.supabase
      .from(this.tableName)
      .select('max_attempts')
      .eq('id', id)
      .single();

    const maxAttempts = existing?.max_attempts || 3;
    const newAttempts = currentAttempts + 1;
    const status: MessageTrackingStatus = newAttempts >= maxAttempts ? 'failed' : 'retry';

    return this.update(id, {
      status,
      attempts: newAttempts,
      last_attempt_at: now,
      last_error: error,
    });
  }

  /**
   * Busca mensagens pendentes de retry
   * Retorna mensagens com status 'pending' ou 'retry' e attempts < max_attempts
   */
  async findPendingRetries(limit = 100): Promise<MessageTracking[]> {
    try {
      const { data, error } = await this.supabase
        .from(this.tableName)
        .select('*')
        .in('status', ['pending', 'retry'])
        .lt('attempts', 3) // max_attempts default
        .order('created_at', { ascending: true })
        .limit(limit);

      if (error) {
        Logger.error('Error finding pending retries', error);
        return [];
      }

      return data || [];
    } catch (error) {
      Logger.error('Exception finding pending retries', error);
      return [];
    }
  }

  /**
   * Busca mensagens que estao pendentes ha mais de X minutos
   * Usado para gerar alertas
   */
  async findStaleMessages(minutesThreshold: number): Promise<MessageTracking[]> {
    try {
      const thresholdDate = new Date(Date.now() - minutesThreshold * 60 * 1000).toISOString();

      const { data, error } = await this.supabase
        .from(this.tableName)
        .select('*')
        .in('status', ['pending', 'retry', 'sending'])
        .lt('created_at', thresholdDate)
        .order('created_at', { ascending: true });

      if (error) {
        Logger.error('Error finding stale messages', error);
        return [];
      }

      return data || [];
    } catch (error) {
      Logger.error('Exception finding stale messages', error);
      return [];
    }
  }

  /**
   * Busca uma mensagem pelo correlation ID
   */
  async findByCorrelationId(correlationId: string): Promise<MessageTracking | null> {
    try {
      const { data, error } = await this.supabase
        .from(this.tableName)
        .select('*')
        .eq('correlation_id', correlationId)
        .single();

      if (error) {
        if (error.code === 'PGRST116') {
          return null;
        }
        Logger.error('Error finding by correlation ID', error);
        return null;
      }

      return data;
    } catch (error) {
      Logger.error('Exception finding by correlation ID', error);
      return null;
    }
  }

  /**
   * Busca mensagens por remote_jid
   */
  async findByRemoteJid(remoteJid: string, limit = 50): Promise<MessageTracking[]> {
    try {
      const { data, error } = await this.supabase
        .from(this.tableName)
        .select('*')
        .eq('remote_jid', remoteJid)
        .order('created_at', { ascending: false })
        .limit(limit);

      if (error) {
        Logger.error('Error finding by remote_jid', error);
        return [];
      }

      return data || [];
    } catch (error) {
      Logger.error('Exception finding by remote_jid', error);
      return [];
    }
  }

  /**
   * Obtem estatisticas de mensagens
   */
  async getStats(agentId?: string): Promise<{
    total: number;
    pending: number;
    sent: number;
    failed: number;
    retry: number;
  }> {
    try {
      let query = this.supabase
        .from(this.tableName)
        .select('status', { count: 'exact' });

      if (agentId) {
        query = query.eq('agent_id', agentId);
      }

      const { data, error } = await query;

      if (error) {
        Logger.error('Error getting stats', error);
        return { total: 0, pending: 0, sent: 0, failed: 0, retry: 0 };
      }

      const stats = {
        total: data?.length || 0,
        pending: 0,
        sent: 0,
        failed: 0,
        retry: 0,
      };

      data?.forEach((row: { status: string }) => {
        const status = row.status as MessageTrackingStatus;
        if (status === 'pending') stats.pending++;
        else if (status === 'sent') stats.sent++;
        else if (status === 'failed') stats.failed++;
        else if (status === 'retry') stats.retry++;
      });

      return stats;
    } catch (error) {
      Logger.error('Exception getting stats', error);
      return { total: 0, pending: 0, sent: 0, failed: 0, retry: 0 };
    }
  }

  /**
   * Limpa mensagens antigas (mais de 7 dias e com status 'sent')
   * Mantém mensagens com falha para análise
   */
  async cleanupOldMessages(daysToKeep = 7): Promise<number> {
    try {
      const cutoffDate = new Date(Date.now() - daysToKeep * 24 * 60 * 60 * 1000).toISOString();

      const { data, error } = await this.supabase
        .from(this.tableName)
        .delete()
        .eq('status', 'sent')
        .lt('created_at', cutoffDate)
        .select('id');

      if (error) {
        Logger.error('Error cleaning up old messages', error);
        return 0;
      }

      const count = data?.length || 0;
      if (count > 0) {
        Logger.info(`Cleaned up ${count} old messages`);
      }

      return count;
    } catch (error) {
      Logger.error('Exception cleaning up old messages', error);
      return 0;
    }
  }
}

// Instancia padrao
export const messageTrackingRepository = new MessageTrackingRepository();
