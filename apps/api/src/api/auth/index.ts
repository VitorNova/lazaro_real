// ============================================================================
// AUTH ROUTES
// Registro das rotas de autenticação
// ============================================================================

import { FastifyInstance } from 'fastify';
import { SupabaseClient } from '@supabase/supabase-js';
import { createAuthHandlers } from './auth.handler';
import { createUserAgentsHandlers } from './user-agents.handler';
import { authMiddleware, legacyAuthMiddleware } from '../middleware/auth.middleware';
import {
  loginRateLimiter,
  registerRateLimiter,
  forgotPasswordRateLimiter,
} from '../middleware/rate-limit.middleware';

// ============================================================================
// REGISTER AUTH ROUTES
// ============================================================================

export async function registerAuthRoutes(
  fastify: FastifyInstance,
  supabase: SupabaseClient
): Promise<void> {
  console.info('[AuthRoutes] Registering authentication routes...');

  const handlers = createAuthHandlers(supabase);

  // ========================================================================
  // PUBLIC ROUTES (sem autenticação, com rate limiting)
  // ========================================================================

  // POST /api/auth/register - Criar nova conta
  fastify.post<{ Body: { email: string; password: string; name: string } }>(
    '/api/auth/register',
    { preHandler: registerRateLimiter },
    handlers.register
  );

  // POST /api/auth/login - Fazer login
  fastify.post<{ Body: { email: string; password: string } }>(
    '/api/auth/login',
    { preHandler: loginRateLimiter },
    handlers.login
  );

  // POST /api/auth/refresh - Renovar access token
  fastify.post('/api/auth/refresh', handlers.refresh);

  // POST /api/auth/forgot-password - Solicitar reset de senha
  fastify.post<{ Body: { email: string } }>(
    '/api/auth/forgot-password',
    { preHandler: forgotPasswordRateLimiter },
    handlers.forgotPassword
  );

  // POST /api/auth/reset-password - Resetar senha com token
  fastify.post('/api/auth/reset-password', handlers.resetPassword);

  // ========================================================================
  // PROTECTED ROUTES (requerem autenticação)
  // ========================================================================

  // POST /api/auth/logout - Fazer logout
  fastify.post<{ Body: { refreshToken?: string; allDevices?: boolean } }>(
    '/api/auth/logout',
    { preHandler: authMiddleware },
    handlers.logout
  );

  // GET /api/auth/me - Obter dados do usuário atual
  fastify.get('/api/auth/me', { preHandler: authMiddleware }, handlers.me);

  // POST /api/auth/change-password - Alterar senha
  fastify.post<{ Body: { currentPassword: string; newPassword: string } }>(
    '/api/auth/change-password',
    { preHandler: authMiddleware },
    handlers.changePassword
  );

  // GET /api/auth/sessions - Listar sessões ativas
  fastify.get('/api/auth/sessions', { preHandler: authMiddleware }, handlers.getSessions);

  // DELETE /api/auth/sessions - Encerrar todas as sessões (logout de todos os dispositivos)
  fastify.delete('/api/auth/sessions', { preHandler: authMiddleware }, handlers.logoutAllDevices);

  // ========================================================================
  // USER AGENTS ROUTES (requerem autenticação)
  // ========================================================================

  const userAgentsHandlers = createUserAgentsHandlers(supabase);

  // GET /api/user/agents - Listar agents do usuário logado
  // Usando legacyAuthMiddleware para suportar x-user-id do frontend
  fastify.get('/api/user/agents', { preHandler: legacyAuthMiddleware }, userAgentsHandlers.listAgents);

  // GET /api/user/stats - Estatísticas do usuário
  fastify.get('/api/user/stats', { preHandler: authMiddleware }, userAgentsHandlers.getDashboardStats);

  // GET /api/user/agents/:agentId - Detalhes de um agent específico
  fastify.get<{ Params: { agentId: string } }>(
    '/api/user/agents/:agentId',
    { preHandler: authMiddleware },
    userAgentsHandlers.getAgentDetails
  );

  console.info('[AuthRoutes] Authentication routes registered:');
  console.info('  POST   /api/auth/register (public + rate limit)');
  console.info('  POST   /api/auth/login (public + rate limit)');
  console.info('  POST   /api/auth/refresh (public)');
  console.info('  POST   /api/auth/forgot-password (public + rate limit)');
  console.info('  POST   /api/auth/reset-password (public)');
  console.info('  POST   /api/auth/logout (protected)');
  console.info('  GET    /api/auth/me (protected)');
  console.info('  POST   /api/auth/change-password (protected)');
  console.info('  GET    /api/auth/sessions (protected) - list active sessions');
  console.info('  DELETE /api/auth/sessions (protected) - logout all devices');
  console.info('  GET    /api/user/agents (protected)');
  console.info('  GET    /api/user/stats (protected)');
  console.info('  GET    /api/user/agents/:agentId (protected)');
}
