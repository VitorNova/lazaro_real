import { supabaseAdmin } from '../client';
import {
  MessageBuffer,
  MessageBufferCreate,
} from '../types';

const TABLE = 'message_buffer';

export const bufferRepository = {
  async add(orgId: string, data: Omit<MessageBufferCreate, 'organization_id'>): Promise<MessageBuffer> {
    const { data: buffer, error } = await supabaseAdmin
      .from(TABLE)
      .insert({ ...data, organization_id: orgId })
      .select()
      .single();

    if (error) {
      console.error('[BufferRepository] Error adding to buffer:', error);
      throw new Error(`Failed to add to buffer: ${error.message}`);
    }

    return buffer;
  },

  async getByRemoteJid(orgId: string, remoteJid: string): Promise<MessageBuffer[]> {
    const { data: buffers, error } = await supabaseAdmin
      .from(TABLE)
      .select()
      .eq('organization_id', orgId)
      .eq('remote_jid', remoteJid)
      .order('created_at', { ascending: true });

    if (error) {
      console.error('[BufferRepository] Error getting buffer by remote_jid:', error);
      throw new Error(`Failed to get buffer: ${error.message}`);
    }

    return buffers || [];
  },

  async getAndClear(orgId: string, remoteJid: string): Promise<MessageBuffer[]> {
    // First, get all buffered messages
    const buffers = await this.getByRemoteJid(orgId, remoteJid);

    if (buffers.length === 0) {
      return [];
    }

    // Then, clear them
    await this.clear(orgId, remoteJid);

    return buffers;
  },

  async clear(orgId: string, remoteJid: string): Promise<void> {
    const { error } = await supabaseAdmin
      .from(TABLE)
      .delete()
      .eq('organization_id', orgId)
      .eq('remote_jid', remoteJid);

    if (error) {
      console.error('[BufferRepository] Error clearing buffer:', error);
      throw new Error(`Failed to clear buffer: ${error.message}`);
    }
  },

  async count(orgId: string, remoteJid: string): Promise<number> {
    const { count, error } = await supabaseAdmin
      .from(TABLE)
      .select('*', { count: 'exact', head: true })
      .eq('organization_id', orgId)
      .eq('remote_jid', remoteJid);

    if (error) {
      console.error('[BufferRepository] Error counting buffer:', error);
      throw new Error(`Failed to count buffer: ${error.message}`);
    }

    return count || 0;
  },

  async getOldestTimestamp(orgId: string, remoteJid: string): Promise<Date | null> {
    const { data: buffer, error } = await supabaseAdmin
      .from(TABLE)
      .select('created_at')
      .eq('organization_id', orgId)
      .eq('remote_jid', remoteJid)
      .order('created_at', { ascending: true })
      .limit(1)
      .single();

    if (error) {
      if (error.code === 'PGRST116') {
        return null;
      }
      console.error('[BufferRepository] Error getting oldest timestamp:', error);
      throw new Error(`Failed to get oldest timestamp: ${error.message}`);
    }

    return buffer ? new Date(buffer.created_at) : null;
  },

  async clearOlderThan(orgId: string, date: Date): Promise<void> {
    const { error } = await supabaseAdmin
      .from(TABLE)
      .delete()
      .eq('organization_id', orgId)
      .lt('created_at', date.toISOString());

    if (error) {
      console.error('[BufferRepository] Error clearing old buffer entries:', error);
      throw new Error(`Failed to clear old buffer entries: ${error.message}`);
    }
  },
};
