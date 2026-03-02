import { supabaseAdmin } from '../client';
import {
  Lead,
  LeadCreate,
  LeadUpdate,
  LeadStatus,
} from '../types';

const TABLE = 'leads';

export interface LeadFilters {
  status?: LeadStatus;
  pipeline_step?: string;
  atendimento_finalizado?: boolean;
  department_id?: string;
}

export const leadsRepository = {
  async create(orgId: string, data: Omit<LeadCreate, 'organization_id'>): Promise<Lead> {
    const { data: lead, error } = await supabaseAdmin
      .from(TABLE)
      .insert({ ...data, organization_id: orgId })
      .select()
      .single();

    if (error) {
      console.error('[LeadsRepository] Error creating lead:', error);
      throw new Error(`Failed to create lead: ${error.message}`);
    }

    return lead;
  },

  async getById(orgId: string, id: string): Promise<Lead | null> {
    const { data: lead, error } = await supabaseAdmin
      .from(TABLE)
      .select()
      .eq('organization_id', orgId)
      .eq('id', id)
      .single();

    if (error) {
      if (error.code === 'PGRST116') {
        return null;
      }
      console.error('[LeadsRepository] Error getting lead by id:', error);
      throw new Error(`Failed to get lead: ${error.message}`);
    }

    return lead;
  },

  async getByRemoteJid(orgId: string, remoteJid: string): Promise<Lead | null> {
    const { data: lead, error } = await supabaseAdmin
      .from(TABLE)
      .select()
      .eq('organization_id', orgId)
      .eq('remote_jid', remoteJid)
      .single();

    if (error) {
      if (error.code === 'PGRST116') {
        return null;
      }
      console.error('[LeadsRepository] Error getting lead by remote_jid:', error);
      throw new Error(`Failed to get lead: ${error.message}`);
    }

    return lead;
  },

  async update(orgId: string, id: string, data: LeadUpdate): Promise<Lead> {
    const { data: lead, error } = await supabaseAdmin
      .from(TABLE)
      .update(data)
      .eq('organization_id', orgId)
      .eq('id', id)
      .select()
      .single();

    if (error) {
      console.error('[LeadsRepository] Error updating lead:', error);
      throw new Error(`Failed to update lead: ${error.message}`);
    }

    return lead;
  },

  async updateByRemoteJid(orgId: string, remoteJid: string, data: LeadUpdate): Promise<Lead> {
    const { data: lead, error } = await supabaseAdmin
      .from(TABLE)
      .update(data)
      .eq('organization_id', orgId)
      .eq('remote_jid', remoteJid)
      .select()
      .single();

    if (error) {
      console.error('[LeadsRepository] Error updating lead by remote_jid:', error);
      throw new Error(`Failed to update lead: ${error.message}`);
    }

    return lead;
  },

  async delete(orgId: string, id: string): Promise<void> {
    const { error } = await supabaseAdmin
      .from(TABLE)
      .delete()
      .eq('organization_id', orgId)
      .eq('id', id);

    if (error) {
      console.error('[LeadsRepository] Error deleting lead:', error);
      throw new Error(`Failed to delete lead: ${error.message}`);
    }
  },

  async list(orgId: string, filters?: LeadFilters): Promise<Lead[]> {
    let query = supabaseAdmin
      .from(TABLE)
      .select()
      .eq('organization_id', orgId);

    if (filters?.status) {
      query = query.eq('status', filters.status);
    }
    if (filters?.pipeline_step) {
      query = query.eq('pipeline_step', filters.pipeline_step);
    }
    if (filters?.atendimento_finalizado !== undefined) {
      query = query.eq('atendimento_finalizado', filters.atendimento_finalizado);
    }
    if (filters?.department_id) {
      query = query.eq('department_id', filters.department_id);
    }

    const { data: leads, error } = await query.order('updated_at', { ascending: false });

    if (error) {
      console.error('[LeadsRepository] Error listing leads:', error);
      throw new Error(`Failed to list leads: ${error.message}`);
    }

    return leads || [];
  },

  async getEligibleForFollowUp(orgId: string): Promise<Lead[]> {
    const { data: leads, error } = await supabaseAdmin
      .from(TABLE)
      .select()
      .eq('organization_id', orgId)
      .eq('atendimento_finalizado', false)
      .eq('status', LeadStatus.OPEN)
      .lt('follow_count', 9)
      .order('updated_at', { ascending: true });

    if (error) {
      console.error('[LeadsRepository] Error getting leads eligible for follow-up:', error);
      throw new Error(`Failed to get leads for follow-up: ${error.message}`);
    }

    return leads || [];
  },

  async incrementFollowUp(orgId: string, id: string, followNumber: number): Promise<Lead> {
    const followField = `follow_0${followNumber}` as keyof LeadUpdate;

    const { data: lead, error } = await supabaseAdmin
      .from(TABLE)
      .update({
        [followField]: true,
        follow_count: followNumber,
      })
      .eq('organization_id', orgId)
      .eq('id', id)
      .select()
      .single();

    if (error) {
      console.error('[LeadsRepository] Error incrementing follow-up:', error);
      throw new Error(`Failed to increment follow-up: ${error.message}`);
    }

    return lead;
  },

  async getOrCreate(orgId: string, remoteJid: string): Promise<Lead> {
    const existing = await this.getByRemoteJid(orgId, remoteJid);
    if (existing) {
      return existing;
    }

    return this.create(orgId, { remote_jid: remoteJid });
  },

  /**
   * Busca lead por diana_prospect_id
   */
  async getByDianaProspectId(orgId: string, dianaProspectId: string): Promise<Lead | null> {
    const { data: lead, error } = await supabaseAdmin
      .from(TABLE)
      .select()
      .eq('organization_id', orgId)
      .eq('diana_prospect_id', dianaProspectId)
      .single();

    if (error) {
      if (error.code === 'PGRST116') {
        return null;
      }
      console.error('[LeadsRepository] Error getting lead by diana_prospect_id:', error);
      throw new Error(`Failed to get lead: ${error.message}`);
    }

    return lead;
  },

  /**
   * Cria ou obtém lead a partir de um prospect da Diana
   * Usado quando Diana envia mensagem para um prospect
   */
  async getOrCreateFromDianaProspect(
    orgId: string,
    remoteJid: string,
    dianaProspectId: string,
    prospectData: {
      nome?: string;
      empresa?: string;
      telefone?: string;
    }
  ): Promise<Lead> {
    // Primeiro tenta buscar pelo remote_jid (pode já existir como inbound)
    const existingByJid = await this.getByRemoteJid(orgId, remoteJid);
    if (existingByJid) {
      // Se já existe mas não está linkado ao prospect, linkar
      if (!existingByJid.diana_prospect_id) {
        return this.update(orgId, existingByJid.id, {
          diana_prospect_id: dianaProspectId,
          // Se lead_origin era genérico, atualizar para diana
          lead_origin: existingByJid.lead_origin === 'whatsapp' ? 'diana' : existingByJid.lead_origin,
        });
      }
      return existingByJid;
    }

    // Tenta buscar pelo diana_prospect_id
    const existingByProspect = await this.getByDianaProspectId(orgId, dianaProspectId);
    if (existingByProspect) {
      return existingByProspect;
    }

    // Criar novo lead com origem Diana
    return this.create(orgId, {
      remote_jid: remoteJid,
      diana_prospect_id: dianaProspectId,
      lead_origin: 'diana',
      pipeline_step: 'Diana - Prospectado',
      nome: prospectData.nome || null,
      empresa: prospectData.empresa || null,
      telefone: prospectData.telefone || null,
    });
  },

  /**
   * Lista leads por origem
   */
  async listByOrigin(orgId: string, origin: string): Promise<Lead[]> {
    const { data: leads, error } = await supabaseAdmin
      .from(TABLE)
      .select()
      .eq('organization_id', orgId)
      .eq('lead_origin', origin)
      .order('updated_at', { ascending: false });

    if (error) {
      console.error('[LeadsRepository] Error listing leads by origin:', error);
      throw new Error(`Failed to list leads: ${error.message}`);
    }

    return leads || [];
  },
};
