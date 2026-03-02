import { supabaseAdmin } from '../client';
import {
  Schedule,
  ScheduleCreate,
  ScheduleUpdate,
  ScheduleStatus,
} from '../types';

const TABLE = 'schedules';

export const schedulesRepository = {
  async create(agentId: string, data: Omit<ScheduleCreate, 'organization_id'>): Promise<Schedule> {
    const { data: schedule, error } = await supabaseAdmin
      .from(TABLE)
      .insert({ ...data, agent_id: agentId, organization_id: agentId })
      .select()
      .single();

    if (error) {
      console.error('[SchedulesRepository] Error creating schedule:', error);
      throw new Error(`Failed to create schedule: ${error.message}`);
    }

    return schedule;
  },

  async getById(agentId: string, id: string): Promise<Schedule | null> {
    const { data: schedule, error } = await supabaseAdmin
      .from(TABLE)
      .select()
      .eq('agent_id', agentId)
      .eq('id', id)
      .single();

    if (error) {
      if (error.code === 'PGRST116') {
        return null;
      }
      console.error('[SchedulesRepository] Error getting schedule by id:', error);
      throw new Error(`Failed to get schedule: ${error.message}`);
    }

    return schedule;
  },

  async getByLeadId(agentId: string, leadId: string): Promise<Schedule[]> {
    const { data: schedules, error } = await supabaseAdmin
      .from(TABLE)
      .select()
      .eq('agent_id', agentId)
      .eq('lead_id', leadId)
      .order('scheduled_at', { ascending: false });

    if (error) {
      console.error('[SchedulesRepository] Error getting schedules by lead_id:', error);
      throw new Error(`Failed to get schedules: ${error.message}`);
    }

    return schedules || [];
  },

  async getByRemoteJid(agentId: string, remoteJid: string): Promise<Schedule[]> {
    const { data: schedules, error } = await supabaseAdmin
      .from(TABLE)
      .select()
      .eq('agent_id', agentId)
      .eq('remote_jid', remoteJid)
      .order('scheduled_at', { ascending: false });

    if (error) {
      console.error('[SchedulesRepository] Error getting schedules by remote_jid:', error);
      throw new Error(`Failed to get schedules: ${error.message}`);
    }

    return schedules || [];
  },

  async update(agentId: string, id: string, data: ScheduleUpdate): Promise<Schedule> {
    const { data: schedule, error } = await supabaseAdmin
      .from(TABLE)
      .update(data)
      .eq('agent_id', agentId)
      .eq('id', id)
      .select()
      .single();

    if (error) {
      console.error('[SchedulesRepository] Error updating schedule:', error);
      throw new Error(`Failed to update schedule: ${error.message}`);
    }

    return schedule;
  },

  async listByDateRange(agentId: string, startDate: Date, endDate: Date): Promise<Schedule[]> {
    const { data: schedules, error } = await supabaseAdmin
      .from(TABLE)
      .select()
      .eq('agent_id', agentId)
      .gte('scheduled_at', startDate.toISOString())
      .lte('scheduled_at', endDate.toISOString())
      .order('scheduled_at', { ascending: true });

    if (error) {
      console.error('[SchedulesRepository] Error listing schedules by date range:', error);
      throw new Error(`Failed to list schedules: ${error.message}`);
    }

    return schedules || [];
  },

  async listUpcoming(agentId: string, limit: number = 10): Promise<Schedule[]> {
    const { data: schedules, error } = await supabaseAdmin
      .from(TABLE)
      .select()
      .eq('agent_id', agentId)
      .eq('status', ScheduleStatus.SCHEDULED)
      .gte('scheduled_at', new Date().toISOString())
      .order('scheduled_at', { ascending: true })
      .limit(limit);

    if (error) {
      console.error('[SchedulesRepository] Error listing upcoming schedules:', error);
      throw new Error(`Failed to list upcoming schedules: ${error.message}`);
    }

    return schedules || [];
  },

  async cancel(agentId: string, id: string): Promise<Schedule> {
    return this.update(agentId, id, { status: ScheduleStatus.CANCELLED });
  },

  async confirm(agentId: string, id: string): Promise<Schedule> {
    return this.update(agentId, id, { status: ScheduleStatus.CONFIRMED });
  },

  async markCompleted(agentId: string, id: string): Promise<Schedule> {
    return this.update(agentId, id, { status: ScheduleStatus.COMPLETED });
  },

  async markNoShow(agentId: string, id: string): Promise<Schedule> {
    return this.update(agentId, id, { status: ScheduleStatus.NO_SHOW });
  },

  async delete(agentId: string, id: string): Promise<void> {
    const { error } = await supabaseAdmin
      .from(TABLE)
      .delete()
      .eq('agent_id', agentId)
      .eq('id', id);

    if (error) {
      console.error('[SchedulesRepository] Error deleting schedule:', error);
      throw new Error(`Failed to delete schedule: ${error.message}`);
    }
  },

  async getByGoogleEventId(agentId: string, googleEventId: string): Promise<Schedule | null> {
    const { data: schedule, error } = await supabaseAdmin
      .from(TABLE)
      .select()
      .eq('agent_id', agentId)
      .eq('google_event_id', googleEventId)
      .single();

    if (error) {
      if (error.code === 'PGRST116') {
        return null;
      }
      console.error('[SchedulesRepository] Error getting schedule by google_event_id:', error);
      throw new Error(`Failed to get schedule: ${error.message}`);
    }

    return schedule;
  },
};
