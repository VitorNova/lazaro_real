/**
 * Agent Connection Routes
 *
 * Extracted from index.ts - Phase 9.11
 * Routes: QR Code, connection status, webhook config, Evolution, UAZAPI
 */

import { FastifyInstance, FastifyRequest, FastifyReply } from 'fastify';
import { supabaseAdmin } from '../../services/supabase/client';
import {
  getQRCodeHandler,
  checkConnectionHandler,
  getQRCodeImageHandler,
  disconnectHandler,
} from './qrcode.handler';
import {
  configureWebhookHandler,
  getWebhookConfigHandler,
  deleteWebhookConfigHandler,
} from './webhook-config.handler';
import {
  getEvolutionStatusHandler,
  connectEvolutionHandler,
  getEvolutionQRCodeHandler,
  disconnectEvolutionHandler,
  listEvolutionInstancesHandler,
} from './evolution.handler';
import { getUazapiStatusHandler } from './uazapi-status.handler';
import {
  legacyAuthMiddleware,
  AuthenticatedRequest,
} from '../middleware/auth.middleware';

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

export async function registerConnectionRoutes(fastify: FastifyInstance): Promise<void> {
  // ==========================================================================
  // QR CODE & CONNECTION
  // ==========================================================================

  // GET /api/agents/:id/qr - Obter QR Code da instancia
  fastify.get<{ Params: { id: string }; Querystring: { provider?: 'uazapi' | 'evolution' } }>(
    '/api/agents/:id/qr',
    { preHandler: authMiddleware },
    getQRCodeHandler
  );

  // GET /api/agents/:id/qr/image - Obter QR Code como imagem PNG
  fastify.get<{ Params: { id: string } }>(
    '/api/agents/:id/qr/image',
    { preHandler: authMiddleware },
    getQRCodeImageHandler
  );

  // GET /api/agents/:id/connection - Verificar status de conexao
  fastify.get<{ Params: { id: string } }>(
    '/api/agents/:id/connection',
    { preHandler: authMiddleware },
    checkConnectionHandler
  );

  // POST /api/agents/:id/disconnect - Desconectar WhatsApp
  fastify.post<{ Params: { id: string } }>(
    '/api/agents/:id/disconnect',
    { preHandler: authMiddleware },
    disconnectHandler
  );

  // POST /api/agents/:id/create-instance - Criar nova instância
  fastify.post<{ Params: { id: string }; Body: { provider?: string } }>(
    '/api/agents/:id/create-instance',
    { preHandler: authMiddleware },
    async (request, reply) => {
      try {
        const { id: agentId } = request.params;
        const userId = (request as any).user?.id;

        if (!userId) {
          return reply.status(401).send({ status: 'error', message: 'Authentication required' });
        }

        const { data: agent, error: agentError } = await supabaseAdmin
          .from('agents')
          .select('id, name, user_id')
          .eq('id', agentId)
          .eq('user_id', userId)
          .single();

        if (agentError || !agent) {
          return reply.status(404).send({ status: 'error', message: 'Agent not found' });
        }

        console.info('[CreateInstance] Clearing existing instance for agent:', agentId);

        const { error: updateError } = await supabaseAdmin
          .from('agents')
          .update({
            uazapi_instance_id: null,
            uazapi_token: null,
            uazapi_connected: false,
            uses_shared_whatsapp: false,
            parent_agent_id: null,
          })
          .eq('id', agentId);

        if (updateError) {
          console.error('[CreateInstance] Error clearing instance:', updateError);
          return reply.status(500).send({ status: 'error', message: 'Failed to clear instance' });
        }

        console.info('[CreateInstance] Instance cleared, ready for new creation:', agentId);

        return reply.send({
          status: 'success',
          message: 'Instance cleared. Call /api/agents/:id/qr to create new instance.',
        });
      } catch (error) {
        console.error('[CreateInstance] Error:', error);
        return reply.status(500).send({ status: 'error', message: 'Internal server error' });
      }
    }
  );

  // ==========================================================================
  // WEBHOOK CONFIGURATION
  // ==========================================================================

  fastify.post<{ Params: { id: string }; Body: { webhook_url?: string; events?: string[] } }>(
    '/api/agents/:id/webhook/config',
    { preHandler: authMiddleware },
    configureWebhookHandler
  );

  fastify.get<{ Params: { id: string } }>(
    '/api/agents/:id/webhook/config',
    { preHandler: authMiddleware },
    getWebhookConfigHandler
  );

  fastify.delete<{ Params: { id: string } }>(
    '/api/agents/:id/webhook/config',
    { preHandler: authMiddleware },
    deleteWebhookConfigHandler
  );

  // ==========================================================================
  // EVOLUTION API ROUTES
  // ==========================================================================

  fastify.get<{ Params: { agentId: string } }>(
    '/api/agents/:agentId/evolution/status',
    { preHandler: authMiddleware },
    getEvolutionStatusHandler
  );

  fastify.post<{ Params: { agentId: string }; Body: { evolution_base_url: string; evolution_api_key: string; instance_name?: string; webhook_url?: string } }>(
    '/api/agents/:agentId/evolution/connect',
    { preHandler: authMiddleware },
    connectEvolutionHandler
  );

  fastify.get<{ Params: { agentId: string } }>(
    '/api/agents/:agentId/evolution/qr',
    { preHandler: authMiddleware },
    getEvolutionQRCodeHandler
  );

  fastify.post<{ Params: { agentId: string } }>(
    '/api/agents/:agentId/evolution/disconnect',
    { preHandler: authMiddleware },
    disconnectEvolutionHandler
  );

  fastify.get<{ Querystring: { base_url: string; api_key: string } }>(
    '/api/evolution/instances',
    { preHandler: authMiddleware },
    listEvolutionInstancesHandler
  );

  // ==========================================================================
  // UAZAPI STATUS ROUTE
  // ==========================================================================

  fastify.get<{ Params: { agentId: string } }>(
    '/api/agents/:agentId/uazapi/status',
    { preHandler: authMiddleware },
    getUazapiStatusHandler
  );
}
