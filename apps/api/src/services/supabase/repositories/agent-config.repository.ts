import { supabaseAdmin } from '../client';
import {
  AgentConfig,
  AgentConfigCreate,
  AgentConfigUpdate,
} from '../types';

const TABLE = 'agent_config';

export const agentConfigRepository = {
  async create(orgId: string, data: Omit<AgentConfigCreate, 'organization_id'>): Promise<AgentConfig> {
    const { data: config, error } = await supabaseAdmin
      .from(TABLE)
      .insert({ ...data, organization_id: orgId })
      .select()
      .single();

    if (error) {
      console.error('[AgentConfigRepository] Error creating agent config:', error);
      throw new Error(`Failed to create agent config: ${error.message}`);
    }

    return config;
  },

  async getByOrgId(orgId: string): Promise<AgentConfig | null> {
    const { data: config, error } = await supabaseAdmin
      .from(TABLE)
      .select()
      .eq('organization_id', orgId)
      .single();

    if (error) {
      if (error.code === 'PGRST116') {
        return null;
      }
      console.error('[AgentConfigRepository] Error getting agent config by org_id:', error);
      throw new Error(`Failed to get agent config: ${error.message}`);
    }

    return config;
  },

  async update(orgId: string, data: AgentConfigUpdate): Promise<AgentConfig> {
    const { data: config, error } = await supabaseAdmin
      .from(TABLE)
      .update(data)
      .eq('organization_id', orgId)
      .select()
      .single();

    if (error) {
      console.error('[AgentConfigRepository] Error updating agent config:', error);
      throw new Error(`Failed to update agent config: ${error.message}`);
    }

    return config;
  },

  async upsert(orgId: string, data: Omit<AgentConfigCreate, 'organization_id'>): Promise<AgentConfig> {
    const { data: config, error } = await supabaseAdmin
      .from(TABLE)
      .upsert(
        { ...data, organization_id: orgId },
        { onConflict: 'organization_id' }
      )
      .select()
      .single();

    if (error) {
      console.error('[AgentConfigRepository] Error upserting agent config:', error);
      throw new Error(`Failed to upsert agent config: ${error.message}`);
    }

    return config;
  },

  async delete(orgId: string): Promise<void> {
    const { error } = await supabaseAdmin
      .from(TABLE)
      .delete()
      .eq('organization_id', orgId);

    if (error) {
      console.error('[AgentConfigRepository] Error deleting agent config:', error);
      throw new Error(`Failed to delete agent config: ${error.message}`);
    }
  },

  async getOrCreateDefault(orgId: string): Promise<AgentConfig> {
    const existing = await this.getByOrgId(orgId);
    if (existing) {
      return existing;
    }

    return this.create(orgId, {});
  },

  async isWithinWorkHours(orgId: string, date: Date = new Date()): Promise<boolean> {
    const config = await this.getByOrgId(orgId);
    if (!config) {
      return true; // Default to allowing if no config
    }

    const hour = date.getHours();
    return hour >= config.work_hours_start && hour < config.work_hours_end;
  },
};
