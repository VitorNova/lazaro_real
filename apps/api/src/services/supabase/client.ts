import { createClient, SupabaseClient } from '@supabase/supabase-js';
import { config } from '../../config';

/**
 * Cliente Supabase com chave anônima (anon key)
 *
 * Este cliente respeita as políticas RLS (Row Level Security).
 * Use para operações onde o contexto do usuário/organização é importante.
 *
 * Requer que app.current_organization_id seja configurado via:
 * - JWT claims no token de autenticação
 * - SET LOCAL app.current_organization_id = 'uuid'
 */
export const supabaseAnon: SupabaseClient = createClient(
  config.supabase.url,
  config.supabase.anonKey,
  {
    auth: {
      autoRefreshToken: true,
      persistSession: false,
    },
  }
);

/**
 * Cliente Supabase com chave de serviço (service key)
 *
 * Este cliente IGNORA as políticas RLS e tem acesso total ao banco.
 * Use apenas para:
 * - Operações administrativas
 * - Jobs em background
 * - Webhooks onde não há contexto de usuário
 * - Operações que precisam acessar dados de múltiplas organizações
 *
 * CUIDADO: Sempre filtre por organization_id manualmente ao usar este cliente!
 */
export const supabaseAdmin: SupabaseClient = createClient(
  config.supabase.url,
  config.supabase.serviceRoleKey,
  {
    auth: {
      autoRefreshToken: false,
      persistSession: false,
    },
  }
);

/**
 * Cria um cliente Supabase com organization_id configurado para RLS
 *
 * @param organizationId - UUID da organização
 * @returns Cliente Supabase configurado para a organização
 */
export function createOrgClient(organizationId: string): SupabaseClient {
  return createClient(
    config.supabase.url,
    config.supabase.anonKey,
    {
      auth: {
        autoRefreshToken: true,
        persistSession: false,
      },
      global: {
        headers: {
          'x-organization-id': organizationId,
        },
      },
    }
  );
}

/**
 * Helper para configurar organization_id em uma transação
 * Útil quando usando supabaseAdmin mas quer simular RLS
 *
 * @param organizationId - UUID da organização
 */
export async function setOrganizationContext(organizationId: string): Promise<void> {
  await supabaseAdmin.rpc('set_config', {
    setting: 'app.current_organization_id',
    value: organizationId,
  });
}
