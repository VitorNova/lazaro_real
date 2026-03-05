/**
 * Learning Entries Routes
 *
 * Extracted from index.legacy.ts - Phase 9.11
 *
 * Handles AI learning/curation entries.
 */

import { FastifyInstance, FastifyRequest, FastifyReply } from 'fastify';
import {
  getLearningEntriesHandler,
  createLearningEntryHandler,
  updateLearningEntryHandler,
  deleteLearningEntryHandler,
  applyLearningEntryHandler,
  getEntryByIdHandler,
  teachHandler,
  approveHandler,
  rejectHandler,
  getStatsHandler,
  bulkApplyHandler,
} from '../dashboard/learning.handler';
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
 * Register learning entries routes
 */
export async function registerLearningRoutes(fastify: FastifyInstance): Promise<void> {
  console.info('[LearningRoutes] Registering learning entries routes...');

  // GET /api/learning-entries - Lista entradas de curadoria
  fastify.get<{
    Querystring: {
      agent_id?: string;
      status?: string;
      page?: string;
      limit?: string;
    };
  }>(
    '/api/learning-entries',
    { preHandler: authMiddleware },
    getLearningEntriesHandler
  );

  // POST /api/learning-entries - Criar nova entrada
  fastify.post<{
    Body: {
      agent_id: string;
      lead_id?: string;
      user_question: string;
      ai_response: string;
      correct_response?: string;
      tags?: string[];
      metadata?: any;
    };
  }>(
    '/api/learning-entries',
    { preHandler: authMiddleware },
    createLearningEntryHandler
  );

  // PATCH /api/learning-entries/:id - Atualizar entrada
  fastify.patch<{
    Params: { id: string };
    Body: {
      status?: string;
      correct_response?: string;
      tags?: string[];
    };
  }>(
    '/api/learning-entries/:id',
    { preHandler: authMiddleware },
    updateLearningEntryHandler
  );

  // DELETE /api/learning-entries/:id - Deletar entrada
  fastify.delete<{ Params: { id: string } }>(
    '/api/learning-entries/:id',
    { preHandler: authMiddleware },
    deleteLearningEntryHandler
  );

  // POST /api/learning-entries/:id/apply - Aplicar à base de conhecimento
  fastify.post<{
    Params: { id: string };
    Body: { knowledge_base_id: string };
  }>(
    '/api/learning-entries/:id/apply',
    { preHandler: authMiddleware },
    applyLearningEntryHandler
  );

  // GET /api/learning-entries/stats - Estatísticas de aprendizado (antes de /:id)
  fastify.get<{ Querystring: { agent_id?: string } }>(
    '/api/learning-entries/stats',
    { preHandler: authMiddleware },
    getStatsHandler
  );

  // POST /api/learning-entries/bulk-apply - Aplicar em lote
  fastify.post<{ Body: { ids: string[] } }>(
    '/api/learning-entries/bulk-apply',
    { preHandler: authMiddleware },
    bulkApplyHandler
  );

  // GET /api/learning-entries/:id - Buscar entrada específica
  fastify.get<{ Params: { id: string } }>(
    '/api/learning-entries/:id',
    { preHandler: authMiddleware },
    getEntryByIdHandler
  );

  // POST /api/learning-entries/:id/teach - Ensinar IA
  fastify.post<{
    Params: { id: string };
    Body: { correct_response: string };
  }>(
    '/api/learning-entries/:id/teach',
    { preHandler: authMiddleware },
    teachHandler
  );

  // POST /api/learning-entries/:id/approve - Aprovar entrada
  fastify.post<{ Params: { id: string } }>(
    '/api/learning-entries/:id/approve',
    { preHandler: authMiddleware },
    approveHandler
  );

  // POST /api/learning-entries/:id/reject - Rejeitar entrada
  fastify.post<{
    Params: { id: string };
    Body: { reason?: string };
  }>(
    '/api/learning-entries/:id/reject',
    { preHandler: authMiddleware },
    rejectHandler
  );

  console.info('[LearningRoutes] Learning entries routes registered.');
}
