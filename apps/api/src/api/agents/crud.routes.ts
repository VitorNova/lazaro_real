/**
 * Agent CRUD Routes
 *
 * Extracted from index.ts - Phase 9.11
 * Routes: create, get, update, delete, list, statuses
 */

import { FastifyInstance, FastifyRequest, FastifyReply } from 'fastify';
import { supabaseAdmin } from '../../services/supabase/client';
import { createAgentHandler, CreateAgentBody } from './create.handler';
import { deleteAgentHandler } from './delete.handler';
import { updateAgentHandler, getAgentHandler, UpdateAgentBody } from './update.handler';
import {
  legacyAuthMiddleware,
  AuthenticatedRequest,
} from '../middleware/auth.middleware';

/**
 * Middleware de autenticação que suporta JWT e x-user-id legado
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

export async function registerCrudRoutes(fastify: FastifyInstance): Promise<void> {
  // POST /api/agents/create - Criar novo agente
  fastify.post<{ Body: CreateAgentBody }>(
    '/api/agents/create',
    { preHandler: authMiddleware },
    createAgentHandler
  );

  // GET /api/agents/:id - Obter dados do agente para edicao
  fastify.get<{ Params: { id: string } }>(
    '/api/agents/:id',
    { preHandler: authMiddleware },
    getAgentHandler
  );

  // PUT /api/agents/:id - Atualizar agente
  fastify.put<{ Params: { id: string }; Body: UpdateAgentBody }>(
    '/api/agents/:id',
    { preHandler: authMiddleware },
    updateAgentHandler
  );

  // GET /api/agents/list - Listar agentes do usuario (lightweight)
  fastify.get<{ Querystring: { include_all?: string } }>(
    '/api/agents/list',
    { preHandler: authMiddleware },
    async (request, reply) => {
      const userId = (request as any).user?.id;
      const includeAll = request.query.include_all === 'true';

      if (!userId) {
        return reply.status(401).send({ status: 'error', message: 'Authentication required' });
      }

      let query = supabaseAdmin
        .from('agents')
        .select('id, name, type, agent_type, avatar_url, system_prompt, uazapi_connected, uazapi_instance_id, uses_shared_whatsapp, parent_agent_id, created_at')
        .eq('user_id', userId);

      if (!includeAll) {
        query = query.neq('agent_type', 'FOLLOWUP');
      }

      const { data: agents, error } = await query.order('created_at', { ascending: false });

      if (error) {
        return reply.status(500).send({ status: 'error', message: 'Error fetching agents' });
      }

      const agentMap = new Map((agents || []).map(a => [a.id, a]));
      const result = (agents || []).map(agent => {
        let whatsappConnected = agent.uazapi_connected || false;
        if (agent.uses_shared_whatsapp && agent.parent_agent_id) {
          const parent = agentMap.get(agent.parent_agent_id);
          if (parent) {
            whatsappConnected = parent.uazapi_connected || false;
          }
        }
        return {
          ...agent,
          whatsapp_connected: whatsappConnected || !!agent.uazapi_instance_id,
        };
      });

      return reply.send({ status: 'success', agents: result });
    }
  );

  // GET /api/agents/statuses - Status real de conexão WhatsApp
  fastify.get(
    '/api/agents/statuses',
    { preHandler: authMiddleware },
    async (request, reply) => {
      const userId = (request as any).user?.id;
      if (!userId) {
        return reply.status(401).send({ status: 'error', message: 'Authentication required' });
      }

      const { data: agents, error } = await supabaseAdmin
        .from('agents')
        .select('id, uazapi_connected, uazapi_base_url, uazapi_instance_id, uazapi_token, uses_shared_whatsapp, parent_agent_id')
        .eq('user_id', userId);

      if (error || !agents) {
        return reply.status(500).send({ status: 'error', message: 'Error fetching agents' });
      }

      const parentIds = agents
        .filter(a => a.uses_shared_whatsapp && a.parent_agent_id)
        .map(a => a.parent_agent_id);

      let parentAgents: Record<string, any> = {};
      if (parentIds.length > 0) {
        const { data: parents } = await supabaseAdmin
          .from('agents')
          .select('id, uazapi_connected, uazapi_base_url, uazapi_instance_id, uazapi_token')
          .in('id', parentIds);
        if (parents) {
          parents.forEach(p => { parentAgents[p.id] = p; });
        }
      }

      const axios = (await import('axios')).default;
      const statuses = await Promise.all(
        agents.map(async (agent) => {
          const cfg = agent.uses_shared_whatsapp && agent.parent_agent_id
            ? { ...agent, ...(parentAgents[agent.parent_agent_id] || {}) }
            : agent;

          if (!cfg.uazapi_base_url || !cfg.uazapi_token) {
            return { id: agent.id, connected: false, phone_number: '' };
          }

          try {
            const resp = await axios.post(
              `${cfg.uazapi_base_url}/instance/connect`,
              {},
              {
                headers: { apikey: cfg.uazapi_token },
                timeout: 8000,
              }
            );

            const data = resp.data;
            const connected = data?.loggedIn === true || data?.status === 'open'
              || data?.instance?.status === 'open';
            const phone = data?.phone_number || data?.instance?.phone_number || '';

            const agentToUpdate = agent.uses_shared_whatsapp ? agent.parent_agent_id : agent.id;
            if (connected !== cfg.uazapi_connected && agentToUpdate) {
              await supabaseAdmin
                .from('agents')
                .update({ uazapi_connected: connected })
                .eq('id', agentToUpdate);
            }

            return { id: agent.id, connected, phone_number: phone };
          } catch {
            return { id: agent.id, connected: cfg.uazapi_connected || false, phone_number: '' };
          }
        })
      );

      return reply.send({
        status: 'success',
        statuses: statuses.reduce((map: Record<string, any>, s) => {
          map[s.id] = { connected: s.connected, phone_number: s.phone_number };
          return map;
        }, {}),
      });
    }
  );

  // DELETE /api/agents/:id - Excluir agente
  fastify.delete<{ Params: { id: string } }>(
    '/api/agents/:id',
    { preHandler: authMiddleware },
    deleteAgentHandler
  );
}
