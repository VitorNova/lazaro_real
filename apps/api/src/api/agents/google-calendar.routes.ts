/**
 * Google Calendar OAuth Routes
 *
 * Extracted from index.legacy.ts - Phase 9.11
 *
 * Handles Google Calendar OAuth flow and calendar management.
 */

import { FastifyInstance, FastifyRequest, FastifyReply } from 'fastify';
import { supabaseAdmin } from '../../services/supabase/client';
import {
  googleOAuthStartHandler,
  createGoogleOAuthCallbackHandler,
  createGoogleOAuthStatusHandler,
  createGoogleOAuthDisconnectHandler,
  createGoogleCalendarsListHandler,
  createGoogleCalendarSelectHandler,
  googleCalendarsFromCredentialsHandler,
} from '../google';
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
 * Register Google Calendar OAuth routes
 */
export async function registerGoogleCalendarRoutes(fastify: FastifyInstance): Promise<void> {
  console.info('[GoogleCalendarRoutes] Registering Google Calendar OAuth routes...');

  // GET /api/google/oauth/start - Iniciar fluxo OAuth
  fastify.get<{ Querystring: { agent_id: string; redirect_uri?: string } }>(
    '/api/google/oauth/start',
    { preHandler: authMiddleware },
    googleOAuthStartHandler as any
  );

  // GET /api/google/oauth/callback - Callback do OAuth (sem auth pois vem do Google)
  fastify.get(
    '/api/google/oauth/callback',
    createGoogleOAuthCallbackHandler(supabaseAdmin)
  );

  // GET /api/agents/:agentId/google/status - Status da conexão Google
  fastify.get<{ Params: { agentId: string } }>(
    '/api/agents/:agentId/google/status',
    { preHandler: authMiddleware },
    createGoogleOAuthStatusHandler(supabaseAdmin)
  );

  // POST /api/agents/:agentId/google/disconnect - Desconectar Google
  fastify.post<{ Params: { agentId: string } }>(
    '/api/agents/:agentId/google/disconnect',
    { preHandler: authMiddleware },
    createGoogleOAuthDisconnectHandler(supabaseAdmin)
  );

  // GET /api/agents/:agentId/google/calendars - Listar calendários
  fastify.get<{ Params: { agentId: string } }>(
    '/api/agents/:agentId/google/calendars',
    { preHandler: authMiddleware },
    createGoogleCalendarsListHandler(supabaseAdmin)
  );

  // POST /api/agents/:agentId/google/calendar - Selecionar calendário
  fastify.post<{ Params: { agentId: string }; Body: { calendar_id: string } }>(
    '/api/agents/:agentId/google/calendar',
    { preHandler: authMiddleware },
    createGoogleCalendarSelectHandler(supabaseAdmin)
  );

  // POST /api/google/calendars - Listar calendários usando credenciais (para wizard)
  fastify.post<{ Body: { credentials: any } }>(
    '/api/google/calendars',
    { preHandler: authMiddleware },
    googleCalendarsFromCredentialsHandler
  );

  console.info('[GoogleCalendarRoutes] Google Calendar OAuth routes registered.');
}
