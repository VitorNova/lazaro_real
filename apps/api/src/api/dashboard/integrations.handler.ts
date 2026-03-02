import { FastifyRequest, FastifyReply } from 'fastify';
import { supabaseAdmin } from '../../services/supabase/client';

// ============================================================================
// TYPES
// ============================================================================

export type IntegrationType = 'google' | 'asaas' | 'uazapi' | 'evolution';

const VALID_INTEGRATION_TYPES: IntegrationType[] = ['google', 'asaas', 'uazapi', 'evolution'];

function isValidIntegrationType(type: string): type is IntegrationType {
  return VALID_INTEGRATION_TYPES.includes(type as IntegrationType);
}

interface Integration {
  id: string;
  user_id: string;
  integration_type: IntegrationType;
  config: Record<string, any>;
  connected: boolean;
  connected_at?: string;
  last_sync_at?: string;
  error_message?: string;
  created_at: string;
  updated_at: string;
}

// ============================================================================
// HANDLERS
// ============================================================================

/**
 * GET /api/integrations - Lista todas as integrações do usuário
 */
export async function listIntegrationsHandler(
  request: FastifyRequest,
  reply: FastifyReply
): Promise<void> {
  try {
    const userId = (request as any).user?.id;

    if (!userId) {
      reply.status(401).send({ status: 'error', message: 'Authentication required' });
      return;
    }

    const { data: integrations, error } = await supabaseAdmin
      .from('user_integrations')
      .select('*')
      .eq('user_id', userId)
      .order('integration_type');

    if (error) {
      console.error('[Integrations] Error fetching integrations:', error);
      reply.status(500).send({ status: 'error', message: 'Failed to fetch integrations' });
      return;
    }

    // Retornar integrações com config sanitizado (sem expor tokens)
    const sanitizedIntegrations = (integrations || []).map(i => ({
      ...i,
      config: sanitizeConfig(i.config),
    }));

    reply.send({
      status: 'success',
      data: sanitizedIntegrations,
    });
  } catch (error) {
    console.error('[Integrations] Error:', error);
    reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

/**
 * GET /api/integrations/:type - Obter configuração de uma integração específica
 */
export async function getIntegrationHandler(
  request: FastifyRequest<{ Params: { type: string } }>,
  reply: FastifyReply
): Promise<void> {
  try {
    const userId = (request as any).user?.id;
    const { type } = request.params;

    if (!userId) {
      reply.status(401).send({ status: 'error', message: 'Authentication required' });
      return;
    }

    // Validar tipo
    if (!isValidIntegrationType(type)) {
      reply.status(400).send({ status: 'error', message: 'Invalid integration type' });
      return;
    }

    const { data: integration, error } = await supabaseAdmin
      .from('user_integrations')
      .select('*')
      .eq('user_id', userId)
      .eq('integration_type', type)
      .single();

    if (error && error.code !== 'PGRST116') {
      console.error('[Integrations] Error fetching integration:', error);
      reply.status(500).send({ status: 'error', message: 'Failed to fetch integration' });
      return;
    }

    reply.send({
      status: 'success',
      data: integration
        ? { ...integration, config: sanitizeConfig(integration.config) }
        : null,
    });
  } catch (error) {
    console.error('[Integrations] Error:', error);
    reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

/**
 * POST /api/integrations/:type - Criar/atualizar configuração de integração
 */
export async function upsertIntegrationHandler(
  request: FastifyRequest<{
    Params: { type: string };
    Body: {
      config: Record<string, any>;
      connected?: boolean;
    };
  }>,
  reply: FastifyReply
): Promise<void> {
  try {
    const userId = (request as any).user?.id;
    const { type } = request.params;
    const { config, connected } = request.body;

    if (!userId) {
      reply.status(401).send({ status: 'error', message: 'Authentication required' });
      return;
    }

    // Validar tipo
    if (!isValidIntegrationType(type)) {
      reply.status(400).send({ status: 'error', message: 'Invalid integration type' });
      return;
    }

    const now = new Date().toISOString();

    // Upsert da integração
    const { data: integration, error } = await supabaseAdmin
      .from('user_integrations')
      .upsert(
        {
          user_id: userId,
          integration_type: type,
          config: config || {},
          connected: connected ?? false,
          connected_at: connected ? now : null,
          updated_at: now,
        },
        { onConflict: 'user_id,integration_type' }
      )
      .select()
      .single();

    if (error) {
      console.error('[Integrations] Error upserting integration:', error);
      reply.status(500).send({ status: 'error', message: 'Failed to save integration' });
      return;
    }

    reply.send({
      status: 'success',
      message: 'Integration saved successfully',
      data: { ...integration, config: sanitizeConfig(integration.config) },
    });
  } catch (error) {
    console.error('[Integrations] Error:', error);
    reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

/**
 * DELETE /api/integrations/:type - Remover integração
 */
export async function deleteIntegrationHandler(
  request: FastifyRequest<{ Params: { type: string } }>,
  reply: FastifyReply
): Promise<void> {
  try {
    const userId = (request as any).user?.id;
    const { type } = request.params;

    if (!userId) {
      reply.status(401).send({ status: 'error', message: 'Authentication required' });
      return;
    }

    const { error } = await supabaseAdmin
      .from('user_integrations')
      .delete()
      .eq('user_id', userId)
      .eq('integration_type', type);

    if (error) {
      console.error('[Integrations] Error deleting integration:', error);
      reply.status(500).send({ status: 'error', message: 'Failed to delete integration' });
      return;
    }

    reply.send({
      status: 'success',
      message: 'Integration deleted successfully',
    });
  } catch (error) {
    console.error('[Integrations] Error:', error);
    reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

/**
 * POST /api/integrations/:type/test - Testar conexão de uma integração
 */
export async function testIntegrationHandler(
  request: FastifyRequest<{ Params: { type: string } }>,
  reply: FastifyReply
): Promise<void> {
  try {
    const userId = (request as any).user?.id;
    const { type } = request.params;

    if (!userId) {
      reply.status(401).send({ status: 'error', message: 'Authentication required' });
      return;
    }

    // Buscar configuração atual
    const { data: integration } = await supabaseAdmin
      .from('user_integrations')
      .select('*')
      .eq('user_id', userId)
      .eq('integration_type', type)
      .single();

    if (!integration) {
      reply.status(404).send({ status: 'error', message: 'Integration not configured' });
      return;
    }

    let testResult = { success: false, message: 'Test not implemented' };
    const axios = (await import('axios')).default;

    switch (type) {
      case 'asaas':
        if (integration.config?.api_key) {
          try {
            const resp = await axios.get('https://api.asaas.com/v3/myAccount', {
              headers: { 'access_token': integration.config.api_key },
              timeout: 10000,
            });
            testResult = { success: true, message: `Conectado como: ${resp.data.name}` };
          } catch (err: any) {
            testResult = { success: false, message: err.response?.data?.message || 'Falha na conexão' };
          }
        } else {
          testResult = { success: false, message: 'API key não configurada' };
        }
        break;

      case 'uazapi':
        if (integration.config?.base_url && integration.config?.token) {
          try {
            const resp = await axios.post(
              `${integration.config.base_url}/instance/connect`,
              {},
              {
                headers: { apikey: integration.config.token },
                timeout: 10000,
              }
            );
            const connected = resp.data?.loggedIn === true || resp.data?.status === 'open';
            testResult = {
              success: connected,
              message: connected ? 'WhatsApp conectado' : 'WhatsApp desconectado',
            };
          } catch (err: any) {
            testResult = { success: false, message: 'Falha ao conectar com UAZAPI' };
          }
        } else {
          testResult = { success: false, message: 'URL ou token não configurados' };
        }
        break;

      case 'google':
        testResult = {
          success: !!integration.config?.refresh_token,
          message: integration.config?.refresh_token ? 'Google conectado' : 'Google não conectado',
        };
        break;

      case 'evolution':
        if (integration.config?.base_url && integration.config?.api_key) {
          try {
            const resp = await axios.get(
              `${integration.config.base_url}/instance/fetchInstances`,
              {
                headers: { apikey: integration.config.api_key },
                timeout: 10000,
              }
            );
            testResult = {
              success: true,
              message: `${resp.data?.length || 0} instância(s) encontrada(s)`,
            };
          } catch (err: any) {
            testResult = { success: false, message: 'Falha ao conectar com Evolution API' };
          }
        } else {
          testResult = { success: false, message: 'URL ou API key não configurados' };
        }
        break;
    }

    // Atualizar status da integração
    const now = new Date().toISOString();
    await supabaseAdmin
      .from('user_integrations')
      .update({
        connected: testResult.success,
        connected_at: testResult.success ? now : null,
        last_sync_at: now,
        error_message: testResult.success ? null : testResult.message,
        updated_at: now,
      })
      .eq('user_id', userId)
      .eq('integration_type', type);

    reply.send({
      status: 'success',
      data: testResult,
    });
  } catch (error) {
    console.error('[Integrations] Error testing:', error);
    reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

// ============================================================================
// HELPERS
// ============================================================================

/**
 * Remove informações sensíveis da config antes de retornar ao frontend
 */
function sanitizeConfig(config: Record<string, any>): Record<string, any> {
  if (!config) return {};

  const sanitized = { ...config };

  // Mascarar tokens e API keys
  const sensitiveKeys = ['api_key', 'token', 'access_token', 'refresh_token', 'secret'];
  for (const key of sensitiveKeys) {
    if (sanitized[key] && typeof sanitized[key] === 'string') {
      const value = sanitized[key];
      sanitized[key] = value.length > 8
        ? `${value.substring(0, 4)}...${value.substring(value.length - 4)}`
        : '****';
      sanitized[`${key}_configured`] = true;
    }
  }

  return sanitized;
}
