import { supabaseAdmin } from '../client';
import {
  Message,
  MessageCreate,
  MessageRole,
} from '../types';

const TABLE = 'messages';

export const messagesRepository = {
  async create(orgId: string, data: Omit<MessageCreate, 'organization_id'>): Promise<Message> {
    const { data: message, error } = await supabaseAdmin
      .from(TABLE)
      .insert({ ...data, organization_id: orgId })
      .select()
      .single();

    if (error) {
      console.error('[MessagesRepository] Error creating message:', error);
      throw new Error(`Failed to create message: ${error.message}`);
    }

    return message;
  },

  async getHistory(orgId: string, remoteJid: string, limit: number = 50): Promise<Message[]> {
    const { data: messages, error } = await supabaseAdmin
      .from(TABLE)
      .select()
      .eq('organization_id', orgId)
      .eq('remote_jid', remoteJid)
      .order('created_at', { ascending: true })
      .limit(limit);

    if (error) {
      console.error('[MessagesRepository] Error getting message history:', error);
      throw new Error(`Failed to get message history: ${error.message}`);
    }

    return messages || [];
  },

  async getHistoryByLeadId(orgId: string, leadId: string, limit: number = 50): Promise<Message[]> {
    const { data: messages, error } = await supabaseAdmin
      .from(TABLE)
      .select()
      .eq('organization_id', orgId)
      .eq('lead_id', leadId)
      .order('created_at', { ascending: true })
      .limit(limit);

    if (error) {
      console.error('[MessagesRepository] Error getting message history by lead_id:', error);
      throw new Error(`Failed to get message history: ${error.message}`);
    }

    return messages || [];
  },

  async getLastMessage(orgId: string, remoteJid: string): Promise<Message | null> {
    const { data: message, error } = await supabaseAdmin
      .from(TABLE)
      .select()
      .eq('organization_id', orgId)
      .eq('remote_jid', remoteJid)
      .order('created_at', { ascending: false })
      .limit(1)
      .single();

    if (error) {
      if (error.code === 'PGRST116') {
        return null;
      }
      console.error('[MessagesRepository] Error getting last message:', error);
      throw new Error(`Failed to get last message: ${error.message}`);
    }

    return message;
  },

  async getLastUserMessage(orgId: string, remoteJid: string): Promise<Message | null> {
    const { data: message, error } = await supabaseAdmin
      .from(TABLE)
      .select()
      .eq('organization_id', orgId)
      .eq('remote_jid', remoteJid)
      .eq('role', MessageRole.USER)
      .order('created_at', { ascending: false })
      .limit(1)
      .single();

    if (error) {
      if (error.code === 'PGRST116') {
        return null;
      }
      console.error('[MessagesRepository] Error getting last user message:', error);
      throw new Error(`Failed to get last user message: ${error.message}`);
    }

    return message;
  },

  async countUserMessages(orgId: string, remoteJid: string): Promise<number> {
    const { count, error } = await supabaseAdmin
      .from(TABLE)
      .select('*', { count: 'exact', head: true })
      .eq('organization_id', orgId)
      .eq('remote_jid', remoteJid)
      .eq('role', MessageRole.USER);

    if (error) {
      console.error('[MessagesRepository] Error counting user messages:', error);
      throw new Error(`Failed to count user messages: ${error.message}`);
    }

    return count || 0;
  },

  async deleteByRemoteJid(orgId: string, remoteJid: string): Promise<void> {
    const { error } = await supabaseAdmin
      .from(TABLE)
      .delete()
      .eq('organization_id', orgId)
      .eq('remote_jid', remoteJid);

    if (error) {
      console.error('[MessagesRepository] Error deleting messages by remote_jid:', error);
      throw new Error(`Failed to delete messages: ${error.message}`);
    }
  },

  async deleteByLeadId(orgId: string, leadId: string): Promise<void> {
    const { error } = await supabaseAdmin
      .from(TABLE)
      .delete()
      .eq('organization_id', orgId)
      .eq('lead_id', leadId);

    if (error) {
      console.error('[MessagesRepository] Error deleting messages by lead_id:', error);
      throw new Error(`Failed to delete messages: ${error.message}`);
    }
  },

  async getRecentMessages(
    orgId: string,
    remoteJid: string,
    since: Date
  ): Promise<Message[]> {
    const { data: messages, error } = await supabaseAdmin
      .from(TABLE)
      .select()
      .eq('organization_id', orgId)
      .eq('remote_jid', remoteJid)
      .gte('created_at', since.toISOString())
      .order('created_at', { ascending: true });

    if (error) {
      console.error('[MessagesRepository] Error getting recent messages:', error);
      throw new Error(`Failed to get recent messages: ${error.message}`);
    }

    return messages || [];
  },
};
