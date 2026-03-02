import { supabaseAdmin } from '../client';
import {
  Organization,
  OrganizationCreate,
  OrganizationUpdate,
} from '../types';

const TABLE = 'organizations';

export const organizationsRepository = {
  async create(data: OrganizationCreate): Promise<Organization> {
    const { data: organization, error } = await supabaseAdmin
      .from(TABLE)
      .insert(data)
      .select()
      .single();

    if (error) {
      console.error('[OrganizationsRepository] Error creating organization:', error);
      throw new Error(`Failed to create organization: ${error.message}`);
    }

    return organization;
  },

  async getById(id: string): Promise<Organization | null> {
    const { data: organization, error } = await supabaseAdmin
      .from(TABLE)
      .select()
      .eq('id', id)
      .single();

    if (error) {
      if (error.code === 'PGRST116') {
        return null;
      }
      console.error('[OrganizationsRepository] Error getting organization by id:', error);
      throw new Error(`Failed to get organization: ${error.message}`);
    }

    return organization;
  },

  async getBySlug(slug: string): Promise<Organization | null> {
    const { data: organization, error } = await supabaseAdmin
      .from(TABLE)
      .select()
      .eq('slug', slug)
      .single();

    if (error) {
      if (error.code === 'PGRST116') {
        return null;
      }
      console.error('[OrganizationsRepository] Error getting organization by slug:', error);
      throw new Error(`Failed to get organization: ${error.message}`);
    }

    return organization;
  },

  async update(id: string, data: OrganizationUpdate): Promise<Organization> {
    const { data: organization, error } = await supabaseAdmin
      .from(TABLE)
      .update(data)
      .eq('id', id)
      .select()
      .single();

    if (error) {
      console.error('[OrganizationsRepository] Error updating organization:', error);
      throw new Error(`Failed to update organization: ${error.message}`);
    }

    return organization;
  },

  async delete(id: string): Promise<void> {
    const { error } = await supabaseAdmin
      .from(TABLE)
      .delete()
      .eq('id', id);

    if (error) {
      console.error('[OrganizationsRepository] Error deleting organization:', error);
      throw new Error(`Failed to delete organization: ${error.message}`);
    }
  },

  async list(): Promise<Organization[]> {
    const { data: organizations, error } = await supabaseAdmin
      .from(TABLE)
      .select()
      .order('created_at', { ascending: false });

    if (error) {
      console.error('[OrganizationsRepository] Error listing organizations:', error);
      throw new Error(`Failed to list organizations: ${error.message}`);
    }

    return organizations || [];
  },

  async listActive(): Promise<Organization[]> {
    const { data: organizations, error } = await supabaseAdmin
      .from(TABLE)
      .select()
      .eq('is_active', true)
      .order('created_at', { ascending: false });

    if (error) {
      console.error('[OrganizationsRepository] Error listing active organizations:', error);
      throw new Error(`Failed to list active organizations: ${error.message}`);
    }

    return organizations || [];
  },
};
