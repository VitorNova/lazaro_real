/**
 * Legacy Agent Routes
 *
 * PHASE 9.11 - Reduced from 1790 lines to ~120 lines
 *
 * These are the remaining routes not yet extracted to dedicated route files.
 * They will be progressively migrated.
 *
 * Remaining routes:
 * - /api/agents/:id/status - Agent status (inline handler)
 * - /api/agents/:agentId/stats - Agent stats (uses stats.handler)
 * - /api/agents/:agentId/schedules - Schedules API (uses schedules.handler)
 */

import { FastifyInstance, FastifyRequest, FastifyReply } from 'fastify';
import { supabaseAdmin } from '../../services/supabase/client';
import { getAgentStatsHandler } from './stats.handler';
import { getSchedulesHandler, deleteScheduleHandler } from './schedules.handler';
import {
  legacyAuthMiddleware,
  AuthenticatedRequest,
} from '../middleware/auth.middleware';

/**
 * Auth middleware wrapper for compatibility
 */
async function authMiddleware(
  request: FastifyRequest,
  reply: FastifyReply
): Promise<void> {
  await legacyAuthMiddleware(request, reply);
  const authRequest = request as AuthenticatedRequest;
  if (authRequest.user) {
    (request as unknown as { user: { id: string } }).user = { id: authRequest.user.userId };
  }
}

/**
 * Register remaining legacy routes (to be extracted progressively)
 */
export async function registerLegacyRoutes(fastify: FastifyInstance): Promise<void> {
  console.info('[AgentRoutes/Legacy] Registering remaining legacy routes...');

  // ==========================================================================
  // AGENT STATUS (inline handler - to be extracted)
  // ==========================================================================

  // GET /api/agents/:id/status - Status completo do agente
  fastify.get<{ Params: { id: string } }>(
    '/api/agents/:id/status',
    { preHandler: authMiddleware },
    async (request, reply) => {
      const { id } = request.params;

      try {
        const { data: agent, error } = await supabaseAdmin
          .from('agents')
          .select('id, name, status, uazapi_connected, uazapi_base_url, uazapi_instance_id, uazapi_token, uses_shared_whatsapp, parent_agent_id')
          .eq('id', id)
          .single();

        if (error || !agent) {
          return reply.status(404).send({ status: 'error', message: 'Agent not found' });
        }

        // Se usa WhatsApp compartilhado, buscar credenciais do pai
        let uazapiConfig = agent;
        if ((agent as any).uses_shared_whatsapp && (agent as any).parent_agent_id) {
          const { data: parentAgent } = await supabaseAdmin
            .from('agents')
            .select('uazapi_connected, uazapi_base_url, uazapi_instance_id, uazapi_token')
            .eq('id', (agent as any).parent_agent_id)
            .single();

          if (parentAgent) {
            uazapiConfig = { ...agent, ...parentAgent };
          }
        }

        // Verificar conexao real na UAZAPI
        let realConnectionStatus = false;
        let phoneNumber = '';

        try {
          const axios = (await import('axios')).default;
          const statusResponse = await axios.get(
            `${uazapiConfig.uazapi_base_url}/instance/connectionState/${uazapiConfig.uazapi_instance_id}`,
            {
              headers: {
                apikey: uazapiConfig.uazapi_token || process.env.UAZAPI_API_KEY || '',
              },
              timeout: 10000,
            }
          );

          realConnectionStatus = statusResponse.data?.instance?.state === 'open';
          phoneNumber = statusResponse.data?.instance?.phoneNumber || '';

          // Atualizar status no banco
          const agentToUpdate = (agent as any).uses_shared_whatsapp ? (agent as any).parent_agent_id : id;
          if (realConnectionStatus !== uazapiConfig.uazapi_connected) {
            await supabaseAdmin
              .from('agents')
              .update({ uazapi_connected: realConnectionStatus })
              .eq('id', agentToUpdate);
          }
        } catch {
          realConnectionStatus = uazapiConfig.uazapi_connected;
        }

        return reply.send({
          status: 'success',
          agent: {
            id: agent.id,
            name: agent.name,
            status: agent.status,
            whatsapp_connected: realConnectionStatus,
            phone_number: phoneNumber,
            uses_shared_whatsapp: (agent as any).uses_shared_whatsapp || false,
          },
        });
      } catch (error) {
        console.error('[AgentStatus] Error getting status:', error);
        return reply.status(500).send({ status: 'error', message: 'Failed to get agent status' });
      }
    }
  );

  // ==========================================================================
  // AGENT STATS
  // ==========================================================================

  // GET /api/agents/:agentId/stats - Estatísticas detalhadas do agente
  fastify.get<{ Params: { agentId: string } }>(
    '/api/agents/:agentId/stats',
    { preHandler: authMiddleware },
    getAgentStatsHandler
  );

  // ==========================================================================
  // SCHEDULES API
  // ==========================================================================

  // GET /api/agents/:agentId/schedules - Listar agendamentos do agente
  fastify.get<{ Params: { agentId: string }; Querystring: { leadId?: string; status?: string } }>(
    '/api/agents/:agentId/schedules',
    { preHandler: authMiddleware },
    getSchedulesHandler
  );

  // DELETE /api/agents/:agentId/schedules/:scheduleId - Deletar agendamento
  fastify.delete<{ Params: { agentId: string; scheduleId: string } }>(
    '/api/agents/:agentId/schedules/:scheduleId',
    { preHandler: authMiddleware },
    deleteScheduleHandler
  );

  console.info('[AgentRoutes/Legacy] Legacy routes registered (status, stats, schedules).');
}

// ==========================================================================
// EXPORTS (kept for backward compatibility)
// ==========================================================================

export { createAgentHandler, type CreateAgentRequest, type CreateAgentBody } from './create.handler';
export { deleteAgentHandler } from './delete.handler';
export { updateAgentHandler, getAgentHandler, type UpdateAgentBody } from './update.handler';
export {
  getQRCodeHandler,
  checkConnectionHandler,
  getQRCodeImageHandler,
  disconnectHandler,
} from './qrcode.handler';
export {
  configureWebhookHandler,
  getWebhookConfigHandler,
  deleteWebhookConfigHandler,
} from './webhook-config.handler';
export {
  uploadMediaHandler,
  listMediasHandler,
  deleteMediaHandler,
  uploadAvatarHandler,
  deleteAvatarHandler,
} from './media.handler';
export {
  getSchedulesHandler,
  deleteScheduleHandler,
} from './schedules.handler';
