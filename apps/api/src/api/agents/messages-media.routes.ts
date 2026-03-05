/**
 * Messages & Media Routes
 *
 * Extracted from index.legacy.ts - Phase 9.11
 *
 * Groups:
 * - Messages API (send, get messages)
 * - Media API (upload, list, delete)
 * - Avatar API (upload, delete)
 */

import { FastifyInstance, FastifyRequest, FastifyReply } from 'fastify';
import { sendMessageHandler, getMessagesHandler, SendMessageBody } from '../messages/send.handler';
import {
  uploadMediaHandler,
  listMediasHandler,
  deleteMediaHandler,
  uploadAvatarHandler,
  deleteAvatarHandler,
} from './media.handler';
import { legacyAuthMiddleware, AuthenticatedRequest } from '../middleware/auth.middleware';

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
 * Register messages and media routes
 */
export async function registerMessagesMediaRoutes(fastify: FastifyInstance): Promise<void> {
  console.info('[MessagesMediaRoutes] Registering messages and media routes...');

  // ==========================================================================
  // MESSAGES API
  // ==========================================================================

  // POST /api/messages/send - Enviar mensagem para um lead
  fastify.post<{ Body: SendMessageBody }>(
    '/api/messages/send',
    { preHandler: authMiddleware },
    sendMessageHandler
  );

  // GET /api/agents/:agentId/leads/:leadId/messages - Buscar mensagens de um lead
  fastify.get<{ Params: { agentId: string; leadId: string } }>(
    '/api/agents/:agentId/leads/:leadId/messages',
    { preHandler: authMiddleware },
    getMessagesHandler
  );

  // ==========================================================================
  // MEDIA API
  // ==========================================================================

  // POST /api/agents/:agentId/media/upload - Upload de midia
  fastify.post<{
    Params: { agentId: string };
    Body: { file_data: string; file_name: string; file_type: string; media_type: 'audio' | 'image' | 'video' };
  }>(
    '/api/agents/:agentId/media/upload',
    { preHandler: authMiddleware },
    uploadMediaHandler
  );

  // GET /api/agents/:agentId/media - Listar midias do agente
  fastify.get<{ Params: { agentId: string } }>(
    '/api/agents/:agentId/media',
    { preHandler: authMiddleware },
    listMediasHandler
  );

  // DELETE /api/agents/:agentId/media/:mediaId - Remover midia
  fastify.delete<{ Params: { agentId: string; mediaId: string } }>(
    '/api/agents/:agentId/media/:mediaId',
    { preHandler: authMiddleware },
    deleteMediaHandler
  );

  // ==========================================================================
  // AVATAR API
  // ==========================================================================

  // POST /api/agents/:agentId/avatar - Upload de foto de perfil
  fastify.post<{
    Params: { agentId: string };
    Body: { file_data: string; file_name: string; file_type: string };
  }>(
    '/api/agents/:agentId/avatar',
    { preHandler: authMiddleware },
    uploadAvatarHandler
  );

  // DELETE /api/agents/:agentId/avatar - Remover foto de perfil
  fastify.delete<{ Params: { agentId: string } }>(
    '/api/agents/:agentId/avatar',
    { preHandler: authMiddleware },
    deleteAvatarHandler
  );

  console.info('[MessagesMediaRoutes] Messages and media routes registered.');
}
