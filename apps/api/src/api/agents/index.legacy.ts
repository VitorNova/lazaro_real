import { FastifyInstance, FastifyRequest, FastifyReply } from 'fastify';
import { supabaseAdmin } from '../../services/supabase/client';
import { removeFromHumanTakeoverCache, markAsHumanTakeover } from '../webhooks/human-takeover';
import { createAgentHandler, CreateAgentRequest, CreateAgentBody } from './create.handler';
import { deleteAgentHandler } from './delete.handler';
import { updateAgentHandler, getAgentHandler, UpdateAgentBody } from './update.handler';
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
  googleOAuthStartHandler,
  createGoogleOAuthCallbackHandler,
  createGoogleOAuthStatusHandler,
  createGoogleOAuthDisconnectHandler,
  createGoogleCalendarsListHandler,
  createGoogleCalendarSelectHandler,
  googleCalendarsFromCredentialsHandler,
} from '../google';
// registerAuthRoutes é registrado no index.ts principal
import { getDashboardStats, getLeadsByCategory, getLeadsByOrigin } from '../dashboard/stats.handler';
import { getAsaasDashboardHandler, parseContractHandler, parseAllContractsHandler, getAsaasCustomersHandler, getAsaasParcelamentosHandler, syncAllAsaasHandler, getAsaasAvailableMonthsHandler } from '../dashboard/asaas.handler';
import {
  getAgentExpandedMetrics,
  saveAgentDashboardConfig,
  getMetricsCatalog,
} from '../dashboard/agent-metrics.handler';
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
import {
  getManutencoesHandler,
  updateMaintenanceStatusHandler,
  getManutencoesDashboardHandler,
  concluirManutencaoHandler,
} from '../dashboard/manutencoes.handler';
import { sendMessageHandler, getMessagesHandler, SendMessageBody } from '../messages/send.handler';
import {
  legacyAuthMiddleware,
  AuthenticatedRequest,
  getUserIdFromRequest,
} from '../middleware/auth.middleware';
import {
  uploadMediaHandler,
  listMediasHandler,
  deleteMediaHandler,
  uploadAvatarHandler,
  deleteAvatarHandler,
} from './media.handler';
import { getAgentStatsHandler } from './stats.handler';
import {
  getEvolutionStatusHandler,
  connectEvolutionHandler,
  getEvolutionQRCodeHandler,
  disconnectEvolutionHandler,
  listEvolutionInstancesHandler,
} from './evolution.handler';
import { getUazapiStatusHandler } from './uazapi-status.handler';
import { getSchedulesHandler, deleteScheduleHandler } from './schedules.handler';
// REMOVIDO: Salvador deletado do projeto
// import {
//   getSalvadorConfigHandler,
//   putSalvadorConfigHandler,
// } from './salvador-config.handler';
// New handlers for Leadbox.ia multi-tenant
import {
  getBillingStatsHandler,
  getTokenStatementHandler,
  getInvoicesHandler,
  upgradePlanHandler,
  rechargeTokensHandler
} from '../dashboard/billing.handler';
import { getAuditLogsHandler, createAuditLogHandler } from '../dashboard/audit.handler';
import {
  getInterventionsHandler,
  resolveInterventionHandler,
  getInterventionByIdHandler,
  takeoverHandler,
  assignHandler,
  getInterventionStatsHandler,
  updateEscalationRulesHandler,
} from '../dashboard/interventions.handler';
import {
  listIntegrationsHandler,
  getIntegrationHandler,
  upsertIntegrationHandler,
  deleteIntegrationHandler,
  testIntegrationHandler,
} from '../dashboard/integrations.handler';
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

// ============================================================================
// AUTH MIDDLEWARE
// ============================================================================

/**
 * Middleware de autenticação que suporta JWT e x-user-id legado
 * Usa o novo legacyAuthMiddleware para compatibilidade
 */
async function authMiddleware(
  request: FastifyRequest,
  reply: FastifyReply
): Promise<void> {
  await legacyAuthMiddleware(request, reply);

  // Manter compatibilidade com código existente que usa request.user.id
  const authRequest = request as AuthenticatedRequest;
  if (authRequest.user) {
    (request as unknown as { user: { id: string } }).user = { id: authRequest.user.userId };
  }
}

// ============================================================================
// REGISTER ROUTES
// ============================================================================

/**
 * LEGACY: Routes not yet migrated to separate files.
 * These routes will be progressively extracted.
 *
 * Already extracted to separate files:
 * - CRUD routes -> crud.routes.ts
 * - Connection routes -> connection.routes.ts
 */
export async function registerLegacyRoutes(fastify: FastifyInstance): Promise<void> {
  console.info('[AgentRoutes/Legacy] Registering remaining routes...');

  // ==========================================================================
  // AGENT CRUD
  // ==========================================================================

  // POST /api/agents/create - Criar novo agente (HANDLER REAL)
  fastify.post<{ Body: CreateAgentBody }>(
    '/api/agents/create',
    {
      preHandler: authMiddleware,
    },
    createAgentHandler
  );

  // GET /api/agents/:id - Obter dados do agente para edicao
  fastify.get<{ Params: { id: string } }>(
    '/api/agents/:id',
    {
      preHandler: authMiddleware,
    },
    getAgentHandler
  );

  // PUT /api/agents/:id - Atualizar agente
  fastify.put<{ Params: { id: string }; Body: UpdateAgentBody }>(
    '/api/agents/:id',
    {
      preHandler: authMiddleware,
    },
    updateAgentHandler
  );

  // GET /api/agents/list - Listar agentes do usuario (lightweight)
  // Query param: include_all=true para incluir todos (inclusive FOLLOWUP/Salvador)
  fastify.get<{ Querystring: { include_all?: string } }>(
    '/api/agents/list',
    {
      preHandler: authMiddleware,
    },
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

      // Se não for include_all, exclui FOLLOWUP (Salvador) do seletor de agentes
      if (!includeAll) {
        query = query.neq('agent_type', 'FOLLOWUP');
      }

      const { data: agents, error } = await query.order('created_at', { ascending: false });

      if (error) {
        return reply.status(500).send({ status: 'error', message: 'Error fetching agents' });
      }

      // Para agentes com WhatsApp compartilhado, herdar status de conexão do pai
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

  // GET /api/agents/statuses - Status real de conexão WhatsApp de todos os agentes
  fastify.get(
    '/api/agents/statuses',
    {
      preHandler: authMiddleware,
    },
    async (request, reply) => {
      const userId = (request as any).user?.id;
      if (!userId) {
        return reply.status(401).send({ status: 'error', message: 'Authentication required' });
      }

      const { supabaseAdmin } = await import('../../services/supabase/client');
      const { data: agents, error } = await supabaseAdmin
        .from('agents')
        .select('id, uazapi_connected, uazapi_base_url, uazapi_instance_id, uazapi_token, uses_shared_whatsapp, parent_agent_id')
        .eq('user_id', userId);

      if (error || !agents) {
        return reply.status(500).send({ status: 'error', message: 'Error fetching agents' });
      }

      // Mapear parent agents para lookup rápido
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

      // Verificar status real em paralelo (com timeout de 8s por agente)
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

            // Atualizar DB se mudou
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

  // DELETE /api/agents/:id - Excluir agente completamente
  fastify.delete<{ Params: { id: string } }>(
    '/api/agents/:id',
    {
      preHandler: authMiddleware,
    },
    deleteAgentHandler
  );

  // ==========================================================================
  // QR CODE & CONNECTION
  // ==========================================================================

  // GET /api/agents/:id/qr - Obter QR Code da instancia
  fastify.get<{ Params: { id: string }; Querystring: { provider?: 'uazapi' | 'evolution' } }>(
    '/api/agents/:id/qr',
    {
      preHandler: authMiddleware,
    },
    getQRCodeHandler
  );

  // GET /api/agents/:id/qr/image - Obter QR Code como imagem PNG
  fastify.get<{ Params: { id: string } }>(
    '/api/agents/:id/qr/image',
    {
      preHandler: authMiddleware,
    },
    getQRCodeImageHandler
  );

  // GET /api/agents/:id/connection - Verificar status de conexao
  fastify.get<{ Params: { id: string } }>(
    '/api/agents/:id/connection',
    {
      preHandler: authMiddleware,
    },
    checkConnectionHandler
  );

  // POST /api/agents/:id/disconnect - Desconectar WhatsApp
  fastify.post<{ Params: { id: string } }>(
    '/api/agents/:id/disconnect',
    {
      preHandler: authMiddleware,
    },
    disconnectHandler
  );

  // POST /api/agents/:id/create-instance - Criar nova instância (limpa existente primeiro)
  fastify.post<{ Params: { id: string }; Body: { provider?: string } }>(
    '/api/agents/:id/create-instance',
    {
      preHandler: authMiddleware,
    },
    async (request, reply) => {
      try {
        const { id: agentId } = request.params;
        const userId = (request as any).user?.id;

        if (!userId) {
          return reply.status(401).send({ status: 'error', message: 'Authentication required' });
        }

        // Verificar se agente pertence ao usuário
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

        // Limpar instância existente para forçar criação de nova
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

  // POST /api/agents/:id/webhook/config - Configurar webhook na UAZAPI
  fastify.post<{ Params: { id: string }; Body: { webhook_url?: string; events?: string[] } }>(
    '/api/agents/:id/webhook/config',
    {
      preHandler: authMiddleware,
    },
    configureWebhookHandler
  );

  // GET /api/agents/:id/webhook/config - Obter configuracao do webhook
  fastify.get<{ Params: { id: string } }>(
    '/api/agents/:id/webhook/config',
    {
      preHandler: authMiddleware,
    },
    getWebhookConfigHandler
  );

  // DELETE /api/agents/:id/webhook/config - Remover webhook
  fastify.delete<{ Params: { id: string } }>(
    '/api/agents/:id/webhook/config',
    {
      preHandler: authMiddleware,
    },
    deleteWebhookConfigHandler
  );

  // ==========================================================================
  // LEGACY STATUS ROUTE (kept for compatibility)
  // ==========================================================================

  // GET /api/agents/:id/status - Status completo do agente
  fastify.get<{ Params: { id: string } }>(
    '/api/agents/:id/status',
    {
      preHandler: authMiddleware,
    },
    async (request, reply) => {
      const { id } = request.params;

      try {
        const { supabaseAdmin } = await import('../../services/supabase/client');
        const { data: agent, error } = await supabaseAdmin
          .from('agents')
          .select('id, name, status, uazapi_connected, uazapi_base_url, uazapi_instance_id, uazapi_token, uses_shared_whatsapp, parent_agent_id')
          .eq('id', id)
          .single();

        if (error || !agent) {
          return reply.status(404).send({
            status: 'error',
            message: 'Agent not found',
          });
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

          // Atualizar status no banco do agente pai (se compartilhado) ou do próprio agente
          const agentToUpdate = (agent as any).uses_shared_whatsapp ? (agent as any).parent_agent_id : id;
          if (realConnectionStatus !== uazapiConfig.uazapi_connected) {
            await supabaseAdmin
              .from('agents')
              .update({ uazapi_connected: realConnectionStatus })
              .eq('id', agentToUpdate);
          }
        } catch {
          // Erro ao verificar - manter status do banco
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
        return reply.status(500).send({
          status: 'error',
          message: 'Failed to get agent status',
        });
      }
    }
  );

  // ==========================================================================
  // GOOGLE CALENDAR OAUTH
  // ==========================================================================

  // Importar supabase admin
  const { supabaseAdmin } = await import('../../services/supabase/client');

  // AUTH ROUTES são registradas no index.ts principal (não duplicar aqui)

  // GET /api/google/oauth/start - Iniciar fluxo OAuth
  fastify.get<{ Querystring: { agent_id: string; redirect_uri?: string } }>(
    '/api/google/oauth/start',
    {
      preHandler: authMiddleware,
    },
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
    {
      preHandler: authMiddleware,
    },
    createGoogleOAuthStatusHandler(supabaseAdmin)
  );

  // POST /api/agents/:agentId/google/disconnect - Desconectar Google
  fastify.post<{ Params: { agentId: string } }>(
    '/api/agents/:agentId/google/disconnect',
    {
      preHandler: authMiddleware,
    },
    createGoogleOAuthDisconnectHandler(supabaseAdmin)
  );

  // GET /api/agents/:agentId/google/calendars - Listar calendários
  fastify.get<{ Params: { agentId: string } }>(
    '/api/agents/:agentId/google/calendars',
    {
      preHandler: authMiddleware,
    },
    createGoogleCalendarsListHandler(supabaseAdmin)
  );

  // POST /api/agents/:agentId/google/calendar - Selecionar calendário
  fastify.post<{ Params: { agentId: string }; Body: { calendar_id: string } }>(
    '/api/agents/:agentId/google/calendar',
    {
      preHandler: authMiddleware,
    },
    createGoogleCalendarSelectHandler(supabaseAdmin)
  );

  // POST /api/google/calendars - Listar calendários usando credenciais (para wizard)
  fastify.post<{ Body: { credentials: any } }>(
    '/api/google/calendars',
    {
      preHandler: authMiddleware,
    },
    googleCalendarsFromCredentialsHandler
  );

  // ==========================================================================
  // DASHBOARD STATS
  // ==========================================================================

  // GET /api/dashboard/stats - Estatísticas do dashboard
  fastify.get<{ Querystring: { user_id?: string } }>(
    '/api/dashboard/stats',
    {
      preHandler: authMiddleware,
    },
    getDashboardStats
  );

  // GET /api/dashboard/leads-by-category - Leads por categoria (clique nos big numbers)
  fastify.get<{ Querystring: { user_id?: string; period?: string; category: string } }>(
    '/api/dashboard/leads-by-category',
    {
      preHandler: authMiddleware,
    },
    getLeadsByCategory
  );

  // GET /api/dashboard/leads - Leads por origem (clique nas origens)
  fastify.get<{ Querystring: { user_id?: string; origin: string; limit?: string } }>(
    '/api/dashboard/leads',
    {
      preHandler: authMiddleware,
    },
    getLeadsByOrigin
  );

  // GET /api/dashboard/asaas - Dados financeiros do Asaas (cache Supabase)
  fastify.get(
    '/api/dashboard/asaas',
    {
      preHandler: authMiddleware,
    },
    getAsaasDashboardHandler
  );

  // POST /api/dashboard/asaas/parse-contract/:subscriptionId - Parse PDF contract
  fastify.post(
    '/api/dashboard/asaas/parse-contract/:subscriptionId',
    {
      preHandler: authMiddleware,
    },
    parseContractHandler
  );

  // POST /api/dashboard/asaas/parse-all-contracts - Parse ALL pending contracts
  fastify.post(
    '/api/dashboard/asaas/parse-all-contracts',
    {
      preHandler: authMiddleware,
    },
    parseAllContractsHandler
  );

  // GET /api/dashboard/asaas/customers - Lista todos os clientes do Asaas
  fastify.get(
    '/api/dashboard/asaas/customers',
    {
      preHandler: authMiddleware,
    },
    getAsaasCustomersHandler
  );

  // GET /api/dashboard/asaas/parcelamentos - Lista clientes com parcelamento (quebras de contrato)
  fastify.get(
    '/api/dashboard/asaas/parcelamentos',
    {
      preHandler: authMiddleware,
    },
    getAsaasParcelamentosHandler
  );

  // POST /api/dashboard/asaas/sync-all - Sincroniza todos os dados do Asaas
  fastify.post(
    '/api/dashboard/asaas/sync-all',
    {
      preHandler: authMiddleware,
    },
    syncAllAsaasHandler
  );

  // GET /api/dashboard/asaas/available-months - Lista meses com cobranças
  fastify.get(
    '/api/dashboard/asaas/available-months',
    {
      preHandler: authMiddleware,
    },
    getAsaasAvailableMonthsHandler
  );

  // ==========================================================================
  // MAINTENANCE (MANUTENCOES)
  // ==========================================================================

  // GET /api/dashboard/manutencoes - Listar todas as manutenções
  fastify.get<{ Querystring: { user_id?: string; agent_id?: string; status?: string } }>(
    '/api/dashboard/manutencoes',
    {
      preHandler: authMiddleware,
    },
    getManutencoesHandler
  );

  // PATCH /api/dashboard/manutencoes/:id - Atualizar status de manutenção
  fastify.patch<{
    Params: { id: string };
    Body: { status: string };
  }>(
    '/api/dashboard/manutencoes/:id',
    {
      preHandler: authMiddleware,
    },
    updateMaintenanceStatusHandler
  );

  // GET /api/dashboard/manutencoes/resumo - Dashboard de manutenções com filtro por mês
  fastify.get<{ Querystring: { user_id?: string; agent_id?: string; month?: string } }>(
    '/api/dashboard/manutencoes/resumo',
    {
      preHandler: authMiddleware,
    },
    getManutencoesDashboardHandler
  );

  // POST /api/dashboard/manutencoes/:id/concluir - Marcar manutenção como concluída
  fastify.post<{ Params: { id: string } }>(
    '/api/dashboard/manutencoes/:id/concluir',
    {
      preHandler: authMiddleware,
    },
    concluirManutencaoHandler
  );

  // ==========================================================================
  // AGENT EXPANDED METRICS (Ver Mais)
  // ==========================================================================

  // GET /api/agents/:agent_id/metrics - Métricas expandidas do agente
  fastify.get<{ Params: { agent_id: string } }>(
    '/api/agents/:agent_id/metrics',
    {
      preHandler: authMiddleware,
    },
    getAgentExpandedMetrics
  );

  // POST /api/agents/:agent_id/dashboard-config - Salvar preferência de métricas
  fastify.post<{ Params: { agent_id: string }; Body: { selected_metrics: string[] } }>(
    '/api/agents/:agent_id/dashboard-config',
    {
      preHandler: authMiddleware,
    },
    saveAgentDashboardConfig
  );

  // GET /api/metrics-catalog/:agent_type - Catálogo de métricas disponíveis
  fastify.get<{ Params: { agent_type: string } }>(
    '/api/metrics-catalog/:agent_type',
    {
      preHandler: authMiddleware,
    },
    getMetricsCatalog
  );

  // GET /api/leads - Listar todos os leads (legado)
  fastify.get<{ Querystring: { user_id?: string; agent_id?: string } }>(
    '/api/leads',
    {
      preHandler: authMiddleware,
    },
    getLeadsHandler
  );

  // GET /api/agents-leads - Listar todos os agentes com seus leads (NOVO - para aba Leads)
  fastify.get<{ Querystring: { user_id?: string } }>(
    '/api/agents-leads',
    {
      preHandler: authMiddleware,
    },
    getAgentsWithLeadsHandler
  );

  // GET /api/leads/:remotejid/follow-up-history - Buscar histórico de follow-ups de um lead
  fastify.get<{
    Params: { remotejid: string };
    Querystring: { agent_id?: string };
  }>(
    '/api/leads/:remotejid/follow-up-history',
    {
      preHandler: authMiddleware,
    },
    getLeadFollowUpHistoryHandler
  );

  // GET /api/special-agents - Buscar agentes especiais (Salvador e Diana) para exibição de avatares
  fastify.get(
    '/api/special-agents',
    {
      preHandler: authMiddleware,
    },
    async (request, reply) => {
      try {
        const user_id = (request as any).user?.id;

        if (!user_id) {
          return reply.status(400).send({ status: 'error', message: 'Authentication required' });
        }

        // Buscar Salvador (FOLLOWUP) do mesmo usuário
        const { data: salvadorData } = await supabaseAdmin
          .from('agents')
          .select('id, name, agent_type, type, avatar_url')
          .eq('user_id', user_id)
          .or('agent_type.eq.FOLLOWUP,name.ilike.%salvador%')
          .limit(1)
          .single();

        // Buscar Diana do mesmo usuário
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

  // PATCH /api/leads/:leadId/pipeline - Atualizar etapa do pipeline de um lead
  fastify.patch<{
    Params: { leadId: string };
    Body: { agent_id: string; pipeline_step: string };
  }>(
    '/api/leads/:leadId/pipeline',
    {
      preHandler: authMiddleware,
    },
    updateLeadPipelineHandler
  );

  // DELETE /api/leads/:leadId - Deletar um lead
  fastify.delete<{
    Params: { leadId: string };
    Body: { agent_id: string };
  }>(
    '/api/leads/:leadId',
    {
      preHandler: authMiddleware,
    },
    deleteLeadHandler
  );

  // POST /api/leads/:leadId/ai - Toggle IA de um lead (nova rota)
  fastify.post<{
    Params: { leadId: string };
    Body: { agent_id: string; enabled: boolean };
  }>(
    '/api/leads/:leadId/ai',
    {
      preHandler: authMiddleware,
    },
    toggleLeadAIHandler
  );

  // PATCH /api/leads/:leadId/details - Atualizar detalhes do lead (nome, telefone, resumo)
  fastify.patch<{
    Params: { leadId: string };
    Body: { agent_id: string; nome?: string; telefone?: string; resumo?: string };
  }>(
    '/api/leads/:leadId/details',
    {
      preHandler: authMiddleware,
    },
    updateLeadDetailsHandler
  );

  // GET /api/conversations - Listar todas as conversas
  fastify.get<{ Querystring: { user_id?: string; agent_id?: string } }>(
    '/api/conversations',
    {
      preHandler: authMiddleware,
    },
    getConversationsHandler
  );

  // GET /api/conversations/:phone/messages - Mensagens de uma conversa
  fastify.get<{ Params: { phone: string }; Querystring: { user_id?: string; agent_id?: string } }>(
    '/api/conversations/:phone/messages',
    {
      preHandler: authMiddleware,
    },
    getConversationMessagesHandler
  );

  // GET /api/conversations/:phone/ai-status - Status da IA para uma conversa
  fastify.get<{ Params: { phone: string }; Querystring: { agent_id: string } }>(
    '/api/conversations/:phone/ai-status',
    {
      preHandler: authMiddleware,
    },
    getAIStatusHandler
  );

  // POST /api/conversations/:phone/toggle-ai - Pausar/Ativar IA para uma conversa
  fastify.post<{ Params: { phone: string }; Body: { agent_id: string; enabled: boolean } }>(
    '/api/conversations/:phone/toggle-ai',
    {
      preHandler: authMiddleware,
    },
    toggleAIStatusHandler
  );

  // GET /api/contacts/:phone/picture - Foto de perfil do WhatsApp
  fastify.get<{ Params: { phone: string }; Querystring: { agent_id: string } }>(
    '/api/contacts/:phone/picture',
    {
      preHandler: authMiddleware,
    },
    getProfilePictureHandler
  );

  // ========================================================================
  // CONTROLE DE IA POR LEAD
  // ========================================================================

  // POST /api/leads/:leadId/toggle-ai - Ativar/desativar IA para um lead específico
  fastify.post<{
    Params: { leadId: string };
    Body: { agent_id: string; enabled: boolean };
  }>(
    '/api/leads/:leadId/toggle-ai',
    {
      preHandler: authMiddleware,
    },
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

        // Buscar o lead para obter o remotejid (necessário para o cache)
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
        // enabled = true -> IA ativa (Atendimento_Finalizado = 'false')
        // enabled = false -> IA pausada (Atendimento_Finalizado = 'true')
        // Handoff tracking: registrar paused_at/paused_by ou resumed_at
        const now = new Date().toISOString();
        const updateData: Record<string, any> = {
          Atendimento_Finalizado: enabled ? 'false' : 'true',
          responsavel: enabled ? 'AI' : 'Humano',
          current_state: enabled ? 'ai' : 'paused', // Atualizar current_state junto com o toggle
          updated_at: now,
        };

        if (enabled) {
          // Reativando IA - registrar quando foi retomado
          updateData.resumed_at = now;
        } else {
          // Pausando IA - registrar quando e por quem foi pausado
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

        console.info(`[ToggleAI] AI ${enabled ? 'enabled' : 'disabled'} for lead ${leadId} (database and cache synced)`);

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

  // ==========================================================================
  // MESSAGES API - Envio de mensagens via WhatsApp
  // ==========================================================================

  // POST /api/messages/send - Enviar mensagem para um lead
  fastify.post<{ Body: SendMessageBody }>(
    '/api/messages/send',
    {
      preHandler: authMiddleware,
    },
    sendMessageHandler
  );

  // GET /api/agents/:agentId/leads/:leadId/messages - Buscar mensagens de um lead
  fastify.get<{ Params: { agentId: string; leadId: string } }>(
    '/api/agents/:agentId/leads/:leadId/messages',
    {
      preHandler: authMiddleware,
    },
    getMessagesHandler
  );

  // ==========================================================================
  // MEDIA API - Upload de midias para o prompt (apenas Agnes)
  // ==========================================================================

  // POST /api/agents/:agentId/media/upload - Upload de midia (audio, imagem, video)
  fastify.post<{
    Params: { agentId: string };
    Body: { file_data: string; file_name: string; file_type: string; media_type: 'audio' | 'image' | 'video' };
  }>(
    '/api/agents/:agentId/media/upload',
    {
      preHandler: authMiddleware,
    },
    uploadMediaHandler
  );

  // GET /api/agents/:agentId/media - Listar midias do agente
  fastify.get<{ Params: { agentId: string } }>(
    '/api/agents/:agentId/media',
    {
      preHandler: authMiddleware,
    },
    listMediasHandler
  );

  // DELETE /api/agents/:agentId/media/:mediaId - Remover midia
  fastify.delete<{ Params: { agentId: string; mediaId: string } }>(
    '/api/agents/:agentId/media/:mediaId',
    {
      preHandler: authMiddleware,
    },
    deleteMediaHandler
  );

  // ==========================================================================
  // AVATAR API - Foto de perfil do agente
  // ==========================================================================

  // POST /api/agents/:agentId/avatar - Upload de foto de perfil
  fastify.post<{
    Params: { agentId: string };
    Body: { file_data: string; file_name: string; file_type: string };
  }>(
    '/api/agents/:agentId/avatar',
    {
      preHandler: authMiddleware,
    },
    uploadAvatarHandler
  );

  // DELETE /api/agents/:agentId/avatar - Remover foto de perfil
  fastify.delete<{ Params: { agentId: string } }>(
    '/api/agents/:agentId/avatar',
    {
      preHandler: authMiddleware,
    },
    deleteAvatarHandler
  );

  // GET /api/agents/:agentId/stats - Estatísticas detalhadas do agente
  fastify.get<{ Params: { agentId: string } }>(
    '/api/agents/:agentId/stats',
    {
      preHandler: authMiddleware,
    },
    getAgentStatsHandler
  );

  // ==========================================================================
  // USER SETTINGS API - Configurações do usuário (logo, empresa, etc)
  // ==========================================================================

  // GET /api/users/:userId/settings - Obter configurações do usuário
  fastify.get<{ Params: { userId: string } }>(
    '/api/users/:userId/settings',
    {
      preHandler: authMiddleware,
    },
    async (request, reply) => {
      try {
        const { userId } = request.params;
        const authUserId = (request as any).user?.id;

        console.info('[UserSettings] GET request - userId:', userId, 'authUserId:', authUserId);

        // Verificar se o usuário está acessando suas próprias configurações
        if (userId !== authUserId) {
          console.error('[UserSettings] Access denied - userId:', userId, 'authUserId:', authUserId);
          return reply.status(403).send({ status: 'error', message: 'Access denied' });
        }

        // Buscar configurações do usuário
        const { data: settings, error } = await supabaseAdmin
          .from('user_settings')
          .select('*')
          .eq('user_id', userId)
          .single();

        if (error && error.code !== 'PGRST116') {
          console.error('[UserSettings] Error fetching settings:', error);
          return reply.status(500).send({ status: 'error', message: 'Failed to fetch settings' });
        }

        return reply.send({
          status: 'success',
          settings: settings || {
            logo_url: null,
            company_name: '',
          },
        });
      } catch (error) {
        console.error('[UserSettings] Error:', error);
        return reply.status(500).send({ status: 'error', message: 'Internal server error' });
      }
    }
  );

  // PUT /api/users/:userId/settings - Atualizar configurações do usuário
  fastify.put<{
    Params: { userId: string };
    Body: {
      company_name?: string;
      logo_data?: string | null;
      logo_name?: string | null;
      logo_type?: string | null;
      remove_logo?: boolean;
    };
  }>(
    '/api/users/:userId/settings',
    {
      preHandler: authMiddleware,
    },
    async (request, reply) => {
      try {
        const { userId } = request.params;
        const { company_name, logo_data, logo_name, logo_type, remove_logo } = request.body;
        const authUserId = (request as any).user?.id;

        console.info('[UserSettings] PUT request - userId:', userId, 'authUserId:', authUserId);

        // Verificar se o usuário está atualizando suas próprias configurações
        if (userId !== authUserId) {
          console.error('[UserSettings] Access denied - userId:', userId, 'authUserId:', authUserId);
          return reply.status(403).send({ status: 'error', message: 'Access denied' });
        }

        let logoUrl: string | null = null;

        // Se deve remover a logo
        if (remove_logo) {
          // Buscar logo atual para deletar do storage
          const { data: currentSettings } = await supabaseAdmin
            .from('user_settings')
            .select('logo_url')
            .eq('user_id', userId)
            .single();

          if (currentSettings?.logo_url) {
            // Extrair path do storage da URL
            const urlParts = currentSettings.logo_url.split('/user-logos/');
            if (urlParts.length > 1) {
              const filePath = urlParts[1];
              await supabaseAdmin.storage.from('user-logos').remove([filePath]);
            }
          }

          logoUrl = null;
        }
        // Se há nova logo para upload
        else if (logo_data && logo_name && logo_type) {
          // Remover logo antiga se existir
          const { data: currentSettings } = await supabaseAdmin
            .from('user_settings')
            .select('logo_url')
            .eq('user_id', userId)
            .single();

          if (currentSettings?.logo_url) {
            const urlParts = currentSettings.logo_url.split('/user-logos/');
            if (urlParts.length > 1) {
              const filePath = urlParts[1];
              await supabaseAdmin.storage.from('user-logos').remove([filePath]);
            }
          }

          // Upload da nova logo
          const base64Data = logo_data.split(',')[1] || logo_data;
          const buffer = Buffer.from(base64Data, 'base64');
          const extension = logo_name.split('.').pop() || 'png';
          const fileName = `${userId}/logo_${Date.now()}.${extension}`;

          const { error: uploadError } = await supabaseAdmin.storage
            .from('user-logos')
            .upload(fileName, buffer, {
              contentType: logo_type,
              upsert: true,
            });

          if (uploadError) {
            console.error('[UserSettings] Error uploading logo:', uploadError);
            return reply.status(500).send({ status: 'error', message: 'Failed to upload logo' });
          }

          // Obter URL pública
          const { data: urlData } = supabaseAdmin.storage
            .from('user-logos')
            .getPublicUrl(fileName);

          logoUrl = urlData.publicUrl;
        }

        // Upsert das configurações
        const updateData: Record<string, any> = {
          user_id: userId,
          updated_at: new Date().toISOString(),
        };

        if (company_name !== undefined) {
          updateData.company_name = company_name;
        }

        if (remove_logo || logo_data) {
          updateData.logo_url = logoUrl;
        }

        const { data: settings, error: upsertError } = await supabaseAdmin
          .from('user_settings')
          .upsert(updateData, { onConflict: 'user_id' })
          .select()
          .single();

        if (upsertError) {
          console.error('[UserSettings] Error upserting settings:', upsertError);
          return reply.status(500).send({ status: 'error', message: 'Failed to save settings' });
        }

        console.info('[UserSettings] Settings updated for user:', userId);

        return reply.send({
          status: 'success',
          message: 'Settings saved successfully',
          settings,
        });
      } catch (error) {
        console.error('[UserSettings] Error:', error);
        return reply.status(500).send({ status: 'error', message: 'Internal server error' });
      }
    }
  );

  // ==========================================================================
  // EVOLUTION API ROUTES
  // ==========================================================================

  // GET /api/agents/:agentId/evolution/status - Status da conexão Evolution
  fastify.get<{ Params: { agentId: string } }>(
    '/api/agents/:agentId/evolution/status',
    { preHandler: authMiddleware },
    getEvolutionStatusHandler
  );

  // POST /api/agents/:agentId/evolution/connect - Conectar agente à Evolution
  fastify.post<{
    Params: { agentId: string };
    Body: {
      evolution_base_url: string;
      evolution_api_key: string;
      instance_name?: string;
      webhook_url?: string;
    };
  }>(
    '/api/agents/:agentId/evolution/connect',
    { preHandler: authMiddleware },
    connectEvolutionHandler
  );

  // GET /api/agents/:agentId/evolution/qrcode - Obter QR Code Evolution
  fastify.get<{ Params: { agentId: string } }>(
    '/api/agents/:agentId/evolution/qrcode',
    { preHandler: authMiddleware },
    getEvolutionQRCodeHandler
  );

  // POST /api/agents/:agentId/evolution/disconnect - Desconectar Evolution
  fastify.post<{ Params: { agentId: string } }>(
    '/api/agents/:agentId/evolution/disconnect',
    { preHandler: authMiddleware },
    disconnectEvolutionHandler
  );

  // GET /api/evolution/instances - Listar instâncias Evolution (sem auth)
  fastify.get<{ Querystring: { base_url: string; api_key: string } }>(
    '/api/evolution/instances',
    listEvolutionInstancesHandler
  );

  // ==========================================================================
  // UAZAPI STATUS ROUTE
  // ==========================================================================

  // GET /api/agents/:agentId/uazapi/status - Status da conexão UAZAPI
  fastify.get<{ Params: { agentId: string } }>(
    '/api/agents/:agentId/uazapi/status',
    { preHandler: authMiddleware },
    getUazapiStatusHandler
  );

  // ==========================================================================
  // SCHEDULES API - Gerenciamento de agendamentos
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

  // ==========================================================================
  // SALVADOR CONFIG API - REMOVIDO (Salvador deletado do projeto)
  // ==========================================================================

  // ==========================================================================
  // BILLING API - Estatísticas financeiras
  // ==========================================================================

  // GET /api/billing/stats - Estatísticas de billing do usuário
  fastify.get<{ Querystring: { agent_id?: string } }>(
    '/api/billing/stats',
    { preHandler: authMiddleware },
    getBillingStatsHandler
  );

  // GET /api/billing/token-statement - Extrato de tokens
  fastify.get<{ Querystring: { limit?: string; offset?: string } }>(
    '/api/billing/token-statement',
    { preHandler: authMiddleware },
    getTokenStatementHandler
  );

  // GET /api/billing/invoices - Histórico de faturas
  fastify.get<{ Querystring: { limit?: string; offset?: string } }>(
    '/api/billing/invoices',
    { preHandler: authMiddleware },
    getInvoicesHandler
  );

  // POST /api/billing/upgrade - Upgrade de plano
  fastify.post<{ Body: { planId: string } }>(
    '/api/billing/upgrade',
    { preHandler: authMiddleware },
    upgradePlanHandler
  );

  // POST /api/billing/recharge - Recarregar tokens
  fastify.post<{ Body: { amount: number } }>(
    '/api/billing/recharge',
    { preHandler: authMiddleware },
    rechargeTokensHandler
  );

  // ==========================================================================
  // AUDIT LOGS API - Logs de auditoria das ações dos agentes
  // ==========================================================================

  // GET /api/audit/logs - Lista logs de auditoria
  fastify.get<{
    Querystring: {
      agent_id?: string;
      action?: string;
      category?: string;
      lead_id?: string;
      success?: string;
      page?: string;
      limit?: string;
      start_date?: string;
      end_date?: string;
    };
  }>(
    '/api/audit/logs',
    { preHandler: authMiddleware },
    getAuditLogsHandler
  );

  // POST /api/audit/logs - Criar entrada de log de auditoria
  fastify.post<{
    Body: {
      agent_id: string;
      lead_id?: string;
      action: string;
      action_category?: string;
      trigger_text?: string;
      reasoning?: string;
      tool_name?: string;
      tool_input?: any;
      tool_output?: any;
      success?: boolean;
      error_message?: string;
      duration_ms?: number;
      metadata?: any;
    };
  }>(
    '/api/audit/logs',
    { preHandler: authMiddleware },
    createAuditLogHandler
  );

  // ==========================================================================
  // INTERVENTIONS API - Leads em human takeover
  // ==========================================================================

  // GET /api/interventions - Lista leads em atendimento humano
  fastify.get<{
    Querystring: {
      agent_id?: string;
      status?: string;
      page?: string;
      limit?: string;
    };
  }>(
    '/api/interventions',
    { preHandler: authMiddleware },
    getInterventionsHandler
  );

  // GET /api/interventions/stats - Estatísticas de intervenções (ANTES de /:id)
  fastify.get<{
    Querystring: { agent_id?: string };
  }>(
    '/api/interventions/stats',
    { preHandler: authMiddleware },
    getInterventionStatsHandler
  );

  // GET /api/interventions/:id - Buscar intervenção específica
  fastify.get<{
    Params: { id: string };
    Querystring: { agent_id: string };
  }>(
    '/api/interventions/:id',
    { preHandler: authMiddleware },
    getInterventionByIdHandler
  );

  // POST /api/interventions/:id/takeover - Assumir atendimento
  fastify.post<{
    Params: { id: string };
    Body: { agent_id: string };
  }>(
    '/api/interventions/:id/takeover',
    { preHandler: authMiddleware },
    takeoverHandler
  );

  // POST /api/interventions/:id/assign - Atribuir a outro operador
  fastify.post<{
    Params: { id: string };
    Body: { agent_id: string; user_id: string };
  }>(
    '/api/interventions/:id/assign',
    { preHandler: authMiddleware },
    assignHandler
  );

  // POST /api/interventions/:leadId/resolve - Resolver intervenção
  fastify.post<{
    Params: { leadId: string };
    Body: { agent_id: string; notes?: string };
  }>(
    '/api/interventions/:leadId/resolve',
    { preHandler: authMiddleware },
    resolveInterventionHandler
  );

  // PUT /api/interventions/escalation-rules - Configurar regras de escalonamento
  fastify.put<{
    Body: {
      agent_id: string;
      auto_escalate_after_minutes?: number;
      notify_phone?: string;
      notify_email?: string;
      keywords?: string[];
    };
  }>(
    '/api/interventions/escalation-rules',
    { preHandler: authMiddleware },
    updateEscalationRulesHandler
  );

  // ==========================================================================
  // INTEGRATIONS API - Configurações de integrações do usuário
  // ==========================================================================

  // GET /api/integrations - Lista todas as integrações
  fastify.get('/api/integrations', { preHandler: authMiddleware }, listIntegrationsHandler);

  // GET /api/integrations/:type - Obter configuração de uma integração
  fastify.get<{ Params: { type: string } }>(
    '/api/integrations/:type',
    { preHandler: authMiddleware },
    getIntegrationHandler
  );

  // POST /api/integrations/:type - Criar/atualizar configuração
  fastify.post<{
    Params: { type: string };
    Body: { config: Record<string, any>; connected?: boolean };
  }>(
    '/api/integrations/:type',
    { preHandler: authMiddleware },
    upsertIntegrationHandler
  );

  // DELETE /api/integrations/:type - Remover integração
  fastify.delete<{ Params: { type: string } }>(
    '/api/integrations/:type',
    { preHandler: authMiddleware },
    deleteIntegrationHandler
  );

  // POST /api/integrations/:type/test - Testar conexão
  fastify.post<{ Params: { type: string } }>(
    '/api/integrations/:type/test',
    { preHandler: authMiddleware },
    testIntegrationHandler
  );

  // ==========================================================================
  // LEARNING ENTRIES API - Curadoria de conhecimento
  // ==========================================================================

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
  fastify.get<{
    Querystring: { agent_id?: string };
  }>(
    '/api/learning-entries/stats',
    { preHandler: authMiddleware },
    getStatsHandler
  );

  // POST /api/learning-entries/bulk-apply - Aplicar em lote
  fastify.post<{
    Body: { ids: string[] };
  }>(
    '/api/learning-entries/bulk-apply',
    { preHandler: authMiddleware },
    bulkApplyHandler
  );

  // GET /api/learning-entries/:id - Buscar entrada específica
  fastify.get<{
    Params: { id: string };
  }>(
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
  fastify.post<{
    Params: { id: string };
  }>(
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

  console.info('[AgentRoutes] Rotas de agents, Google OAuth, Diana, Dashboard, Leads, Conversas, Messages, Media, Avatar, Stats, UserSettings, Evolution, UAZAPI, Schedules, Billing, Audit, Interventions, Integrations e Learning registradas');
}

// ==========================================================================
// EXPORTS
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
