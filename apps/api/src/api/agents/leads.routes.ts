/**
 * Leads Routes
 *
 * Extracted from index.legacy.ts - Phase 9.11
 *
 * Groups:
 * - Leads API (list, update pipeline, delete, toggle AI, follow-up history)
 * - Conversations API (list, messages, AI status, profile picture)
 * - Special Agents (Salvador, Diana)
 */

import { FastifyInstance, FastifyRequest, FastifyReply } from 'fastify';
import { supabaseAdmin } from '../../services/supabase/client';
import { removeFromHumanTakeoverCache, markAsHumanTakeover } from '../webhooks/human-takeover';
import {
  getLeadsHandler,
  getAgentsWithLeadsHandler,
  updateLeadPipelineHandler,
  toggleLeadAIHandler,
  deleteLeadHandler,
  getLeadFollowUpHistoryHandler,
  updateLeadDetailsHandler,
} from '../dashboard/leads.handler';
import {
  getConversationsHandler,
  getConversationMessagesHandler,
  toggleAIStatusHandler,
  getAIStatusHandler,
  getProfilePictureHandler,
} from '../dashboard/conversations.handler';
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
 * Register leads and conversations routes
 */
export async function registerLeadsRoutes(fastify: FastifyInstance): Promise<void> {
  console.info('[LeadsRoutes] Registering leads and conversations routes...');

  // ==========================================================================
  // LEADS API
  // ==========================================================================

  // GET /api/leads - Listar todos os leads (legado)
  fastify.get<{ Querystring: { user_id?: string; agent_id?: string } }>(
    '/api/leads',
    { preHandler: authMiddleware },
    getLeadsHandler
  );

  // GET /api/agents-leads - Listar todos os agentes com seus leads
  fastify.get<{ Querystring: { user_id?: string } }>(
    '/api/agents-leads',
    { preHandler: authMiddleware },
    getAgentsWithLeadsHandler
  );

  // GET /api/leads/:remotejid/follow-up-history - Histórico de follow-ups
  fastify.get<{
    Params: { remotejid: string };
    Querystring: { agent_id?: string };
  }>(
    '/api/leads/:remotejid/follow-up-history',
    { preHandler: authMiddleware },
    getLeadFollowUpHistoryHandler
  );

  // GET /api/special-agents - Buscar agentes especiais (Salvador e Diana)
  fastify.get(
    '/api/special-agents',
    { preHandler: authMiddleware },
    async (request, reply) => {
      try {
        const user_id = (request as any).user?.id;

        if (!user_id) {
          return reply.status(400).send({ status: 'error', message: 'Authentication required' });
        }

        // Buscar Salvador (FOLLOWUP)
        const { data: salvadorData } = await supabaseAdmin
          .from('agents')
          .select('id, name, agent_type, type, avatar_url')
          .eq('user_id', user_id)
          .or('agent_type.eq.FOLLOWUP,name.ilike.%salvador%')
          .limit(1)
          .single();

        // Buscar Diana
        const { data: dianaData } = await supabaseAdmin
          .from('agents')
          .select('id, name, agent_type, type, avatar_url')
          .eq('user_id', user_id)
          .or('type.eq.diana,name.ilike.%diana%')
          .limit(1)
          .single();

        return reply.send({
          status: 'success',
          data: {
            salvador: salvadorData || null,
            diana: dianaData || null,
          },
        });
      } catch (error) {
        console.error('[SpecialAgents] Error:', error);
        return reply.send({
          status: 'success',
          data: { salvador: null, diana: null },
        });
      }
    }
  );

  // PATCH /api/leads/:leadId/pipeline - Atualizar etapa do pipeline
  fastify.patch<{
    Params: { leadId: string };
    Body: { agent_id: string; pipeline_step: string };
  }>(
    '/api/leads/:leadId/pipeline',
    { preHandler: authMiddleware },
    updateLeadPipelineHandler
  );

  // DELETE /api/leads/:leadId - Deletar um lead
  fastify.delete<{
    Params: { leadId: string };
    Body: { agent_id: string };
  }>(
    '/api/leads/:leadId',
    { preHandler: authMiddleware },
    deleteLeadHandler
  );

  // POST /api/leads/:leadId/ai - Toggle IA de um lead
  fastify.post<{
    Params: { leadId: string };
    Body: { agent_id: string; enabled: boolean };
  }>(
    '/api/leads/:leadId/ai',
    { preHandler: authMiddleware },
    toggleLeadAIHandler
  );

  // PATCH /api/leads/:leadId/details - Atualizar detalhes do lead
  fastify.patch<{
    Params: { leadId: string };
    Body: { agent_id: string; nome?: string; telefone?: string; resumo?: string };
  }>(
    '/api/leads/:leadId/details',
    { preHandler: authMiddleware },
    updateLeadDetailsHandler
  );

  // ==========================================================================
  // CONVERSATIONS API
  // ==========================================================================

  // GET /api/conversations - Listar todas as conversas
  fastify.get<{ Querystring: { user_id?: string; agent_id?: string } }>(
    '/api/conversations',
    { preHandler: authMiddleware },
    getConversationsHandler
  );

  // GET /api/conversations/:phone/messages - Mensagens de uma conversa
  fastify.get<{ Params: { phone: string }; Querystring: { user_id?: string; agent_id?: string } }>(
    '/api/conversations/:phone/messages',
    { preHandler: authMiddleware },
    getConversationMessagesHandler
  );

  // GET /api/conversations/:phone/ai-status - Status da IA para uma conversa
  fastify.get<{ Params: { phone: string }; Querystring: { agent_id: string } }>(
    '/api/conversations/:phone/ai-status',
    { preHandler: authMiddleware },
    getAIStatusHandler
  );

  // POST /api/conversations/:phone/toggle-ai - Pausar/Ativar IA para uma conversa
  fastify.post<{ Params: { phone: string }; Body: { agent_id: string; enabled: boolean } }>(
    '/api/conversations/:phone/toggle-ai',
    { preHandler: authMiddleware },
    toggleAIStatusHandler
  );

  // GET /api/contacts/:phone/picture - Foto de perfil do WhatsApp
  fastify.get<{ Params: { phone: string }; Querystring: { agent_id: string } }>(
    '/api/contacts/:phone/picture',
    { preHandler: authMiddleware },
    getProfilePictureHandler
  );

  // ==========================================================================
  // TOGGLE AI POR LEAD (inline handler)
  // ==========================================================================

  // POST /api/leads/:leadId/toggle-ai - Ativar/desativar IA para um lead específico
  fastify.post<{
    Params: { leadId: string };
    Body: { agent_id: string; enabled: boolean };
  }>(
    '/api/leads/:leadId/toggle-ai',
    { preHandler: authMiddleware },
    async (request, reply) => {
      try {
        const { leadId } = request.params;
        const { agent_id, enabled } = request.body;
        const userId = (request as any).user?.id || request.headers['x-user-id'];

        if (!userId) {
          return reply.status(401).send({ status: 'error', message: 'Authentication required' });
        }

        if (!agent_id) {
          return reply.status(400).send({ status: 'error', message: 'agent_id is required' });
        }

        // Verificar se agente pertence ao usuário
        const { data: agent, error: agentError } = await supabaseAdmin
          .from('agents')
          .select('id, table_leads')
          .eq('id', agent_id)
          .eq('user_id', userId)
          .single();

        if (agentError || !agent) {
          return reply.status(404).send({ status: 'error', message: 'Agent not found' });
        }

        // Buscar o lead para obter o remotejid
        const { data: leadData } = await supabaseAdmin
          .from(agent.table_leads)
          .select('remotejid')
          .eq('id', leadId)
          .single();

        const remoteJid = leadData?.remotejid;

        // Sincronizar com cache em memória ANTES de atualizar o banco
        if (remoteJid) {
          if (enabled) {
            await removeFromHumanTakeoverCache(remoteJid, agent_id);
            console.log('[ToggleAI] Removed from human takeover cache', { leadId, remoteJid });
          } else {
            await markAsHumanTakeover(remoteJid, agent_id);
            console.log('[ToggleAI] Added to human takeover cache', { leadId, remoteJid, agentId: agent_id });
          }
        }

        // Atualizar status da IA no lead
        const now = new Date().toISOString();
        const updateData: Record<string, any> = {
          Atendimento_Finalizado: enabled ? 'false' : 'true',
          responsavel: enabled ? 'AI' : 'Humano',
          current_state: enabled ? 'ai' : 'paused',
          updated_at: now,
        };

        if (enabled) {
          updateData.resumed_at = now;
        } else {
          updateData.paused_at = now;
          updateData.paused_by = 'API';
        }

        const { error: updateError } = await supabaseAdmin
          .from(agent.table_leads)
          .update(updateData)
          .eq('id', leadId);

        if (updateError) {
          console.error('[ToggleAI] Error updating lead:', updateError);
          return reply.status(500).send({ status: 'error', message: 'Failed to update lead' });
        }

        console.info(`[ToggleAI] AI ${enabled ? 'enabled' : 'disabled'} for lead ${leadId}`);

        return reply.send({
          status: 'success',
          message: enabled ? 'IA reativada para este lead' : 'IA pausada - atendimento humano ativo',
          ai_enabled: enabled,
        });
      } catch (error) {
        console.error('[ToggleAI] Error:', error);
        return reply.status(500).send({ status: 'error', message: 'Internal server error' });
      }
    }
  );

  console.info('[LeadsRoutes] Leads and conversations routes registered.');
}
