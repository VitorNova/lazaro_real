// ============================================================================
// USER AGENTS HANDLER
// Handlers para gerenciar agents do usuário logado
// ============================================================================

import { FastifyRequest, FastifyReply } from 'fastify';
import { SupabaseClient } from '@supabase/supabase-js';
import { AuthenticatedRequest } from '../middleware/auth.middleware';

// ============================================================================
// TYPES
// ============================================================================

interface AgentSummary {
  id: string;
  name: string;
  type: string;
  status: string;
  whatsapp_connected: boolean;
  whatsapp_instance_name: string | null;
  created_at: string;
  updated_at: string;
}

interface AgentStats {
  total_agents: number;
  active_agents: number;
  total_leads: number;
  total_conversations: number;
}

// ============================================================================
// HANDLERS
// ============================================================================

export function createUserAgentsHandlers(supabase: SupabaseClient) {
  return {
    // ========================================================================
    // LIST USER AGENTS
    // ========================================================================
    listAgents: async (request: FastifyRequest, reply: FastifyReply) => {
      try {
        const authRequest = request as AuthenticatedRequest;
        const userId = authRequest.user?.userId;

        if (!userId) {
          return reply.status(401).send({
            status: 'error',
            message: 'Não autenticado',
          });
        }

        // Buscar agents do usuário
        const { data: agents, error } = await supabase
          .from('agents')
          .select(`
            id,
            name,
            type,
            status,
            uazapi_instance_id,
            uazapi_connected,
            uazapi_base_url,
            uazapi_token,
            whatsapp_instance_name,
            whatsapp_provider,
            uses_shared_whatsapp,
            parent_agent_id,
            evolution_instance_name,
            evolution_connected,
            table_leads,
            pipeline_stages,
            created_at,
            updated_at
          `)
          .eq('user_id', userId)
          .order('created_at', { ascending: false });

        if (error) {
          console.error('[UserAgents] List error:', error);
          return reply.status(500).send({
            status: 'error',
            message: 'Erro ao listar agentes',
          });
        }

        // Criar mapa de agentes por ID para herança de conexão
        const agentsById: Record<string, any> = {};
        (agents || []).forEach((a: any) => {
          agentsById[a.id] = a;
        });

        // Mapear para formato de resposta
        const agentList = (agents || []).map((agent: any) => {
          // Herdar status de conexão do pai se usa WhatsApp compartilhado
          let uazapiConnected = agent.uazapi_connected || false;
          if (agent.uses_shared_whatsapp && agent.parent_agent_id) {
            const parent = agentsById[agent.parent_agent_id];
            if (parent) {
              uazapiConnected = parent.uazapi_connected || false;
            }
          }

          return {
            id: agent.id,
            name: agent.name,
            type: agent.type,
            status: agent.status,
            whatsapp_connected: !!agent.uazapi_instance_id || uazapiConnected || agent.evolution_connected,
            whatsapp_instance_name: agent.whatsapp_instance_name || null,
            whatsapp_provider: agent.whatsapp_provider || 'uazapi',
            uses_shared_whatsapp: agent.uses_shared_whatsapp || false,
            parent_agent_id: agent.parent_agent_id || null,
            uazapi_instance_id: agent.uazapi_instance_id || null,
            uazapi_connected: uazapiConnected,
            evolution_instance_name: agent.evolution_instance_name || null,
            evolution_connected: agent.evolution_connected || false,
            table_leads: agent.table_leads,
            pipeline_stages: agent.pipeline_stages,
            created_at: agent.created_at,
            updated_at: agent.updated_at,
          };
        });

        return reply.send({
          status: 'success',
          agents: agentList,
          total: agentList.length,
        });
      } catch (error) {
        console.error('[UserAgents] List exception:', error);
        return reply.status(500).send({
          status: 'error',
          message: 'Erro interno',
        });
      }
    },

    // ========================================================================
    // GET USER DASHBOARD STATS
    // ========================================================================
    getDashboardStats: async (request: FastifyRequest, reply: FastifyReply) => {
      try {
        const authRequest = request as AuthenticatedRequest;
        const userId = authRequest.user?.userId;

        if (!userId) {
          return reply.status(401).send({
            status: 'error',
            message: 'Não autenticado',
          });
        }

        // Contar agents
        const { data: agents } = await supabase
          .from('agents')
          .select('id, status')
          .eq('user_id', userId);

        const totalAgents = agents?.length || 0;
        const activeAgents = agents?.filter((a) => a.status === 'active').length || 0;

        // Buscar IDs dos agents do usuário
        const agentIds = agents?.map((a) => a.id) || [];

        // Contar leads
        let totalLeads = 0;
        if (agentIds.length > 0) {
          const { count: leadsCount } = await supabase
            .from('leads')
            .select('id', { count: 'exact', head: true })
            .in('agent_id', agentIds);
          totalLeads = leadsCount || 0;
        }

        // Contar conversas
        let totalConversations = 0;
        if (agentIds.length > 0) {
          const { count: conversationsCount } = await supabase
            .from('messages')
            .select('remote_jid', { count: 'exact', head: true })
            .in('agent_id', agentIds);
          totalConversations = conversationsCount || 0;
        }

        const stats: AgentStats = {
          total_agents: totalAgents,
          active_agents: activeAgents,
          total_leads: totalLeads,
          total_conversations: totalConversations,
        };

        return reply.send({
          status: 'success',
          stats,
        });
      } catch (error) {
        console.error('[UserAgents] Stats exception:', error);
        return reply.status(500).send({
          status: 'error',
          message: 'Erro interno',
        });
      }
    },

    // ========================================================================
    // GET AGENT DETAILS (verificando ownership)
    // ========================================================================
    getAgentDetails: async (
      request: FastifyRequest<{ Params: { agentId: string } }>,
      reply: FastifyReply
    ) => {
      try {
        const authRequest = request as AuthenticatedRequest;
        const userId = authRequest.user?.userId;
        const { agentId } = request.params;

        if (!userId) {
          return reply.status(401).send({
            status: 'error',
            message: 'Não autenticado',
          });
        }

        // Buscar agent verificando ownership
        const { data: agent, error } = await supabase
          .from('agents')
          .select('*')
          .eq('id', agentId)
          .eq('user_id', userId)
          .single();

        if (error || !agent) {
          return reply.status(404).send({
            status: 'error',
            message: 'Agente não encontrado',
          });
        }

        // Remover campos sensíveis
        const {
          gemini_api_key,
          claude_api_key,
          openai_api_key,
          uazapi_token,
          ...safeAgent
        } = agent;

        return reply.send({
          status: 'success',
          agent: {
            ...safeAgent,
            has_gemini_key: !!gemini_api_key,
            has_claude_key: !!claude_api_key,
            has_openai_key: !!openai_api_key,
            has_uazapi_token: !!uazapi_token,
          },
        });
      } catch (error) {
        console.error('[UserAgents] Get details exception:', error);
        return reply.status(500).send({
          status: 'error',
          message: 'Erro interno',
        });
      }
    },
  };
}
