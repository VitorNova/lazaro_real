import { supabaseAdmin } from '../client';
import {
  Integration,
  IntegrationCreate,
  IntegrationUpdate,
} from '../types';

const TABLE = 'integrations';

export const integrationsRepository = {
  async create(orgId: string, data: Omit<IntegrationCreate, 'organization_id'>): Promise<Integration> {
    const { data: integration, error } = await supabaseAdmin
      .from(TABLE)
      .insert({ ...data, organization_id: orgId })
      .select()
      .single();

    if (error) {
      console.error('[IntegrationsRepository] Error creating integration:', error);
      throw new Error(`Failed to create integration: ${error.message}`);
    }

    return integration;
  },

  async getByOrgId(orgId: string): Promise<Integration | null> {
    const { data: integration, error } = await supabaseAdmin
      .from(TABLE)
      .select()
      .eq('organization_id', orgId)
      .single();

    if (error) {
      if (error.code === 'PGRST116') {
        return null;
      }
      console.error('[IntegrationsRepository] Error getting integration by org_id:', error);
      throw new Error(`Failed to get integration: ${error.message}`);
    }

    return integration;
  },

  async update(orgId: string, data: IntegrationUpdate): Promise<Integration> {
    const { data: integration, error } = await supabaseAdmin
      .from(TABLE)
      .update(data)
      .eq('organization_id', orgId)
      .select()
      .single();

    if (error) {
      console.error('[IntegrationsRepository] Error updating integration:', error);
      throw new Error(`Failed to update integration: ${error.message}`);
    }

    return integration;
  },

  async upsert(orgId: string, data: Omit<IntegrationCreate, 'organization_id'>): Promise<Integration> {
    const { data: integration, error } = await supabaseAdmin
      .from(TABLE)
      .upsert(
        { ...data, organization_id: orgId },
        { onConflict: 'organization_id' }
      )
      .select()
      .single();

    if (error) {
      console.error('[IntegrationsRepository] Error upserting integration:', error);
      throw new Error(`Failed to upsert integration: ${error.message}`);
    }

    return integration;
  },

  async delete(orgId: string): Promise<void> {
    const { error } = await supabaseAdmin
      .from(TABLE)
      .delete()
      .eq('organization_id', orgId);

    if (error) {
      console.error('[IntegrationsRepository] Error deleting integration:', error);
      throw new Error(`Failed to delete integration: ${error.message}`);
    }
  },

  async hasWhatsAppConfig(orgId: string): Promise<boolean> {
    const integration = await this.getByOrgId(orgId);
    return !!(
      integration?.uazapi_base_url &&
      integration?.uazapi_instance &&
      integration?.uazapi_api_key
    );
  },

  async hasAsaasConfig(orgId: string): Promise<boolean> {
    const integration = await this.getByOrgId(orgId);
    return !!integration?.asaas_api_key;
  },

  async hasGoogleCalendarConfig(orgId: string): Promise<boolean> {
    const integration = await this.getByOrgId(orgId);
    return !!(
      integration?.google_credentials &&
      integration?.google_calendar_id
    );
  },
};
