/**
 * Dashboard Routes
 *
 * Extracted from index.legacy.ts - Phase 9.11
 *
 * Groups:
 * - Dashboard Stats (leads by category, leads by origin)
 * - Asaas Dashboard (financial data, contracts, sync)
 * - Maintenance Dashboard (manutencoes)
 * - Agent Expanded Metrics
 */

import { FastifyInstance } from 'fastify';
import { getDashboardStats, getLeadsByCategory, getLeadsByOrigin } from '../dashboard/stats.handler';
import {
  getAsaasDashboardHandler,
  parseContractHandler,
  parseAllContractsHandler,
  getAsaasCustomersHandler,
  getAsaasParcelamentosHandler,
  syncAllAsaasHandler,
  getAsaasAvailableMonthsHandler,
} from '../dashboard/asaas.handler';
import {
  getManutencoesHandler,
  updateMaintenanceStatusHandler,
  getManutencoesDashboardHandler,
  concluirManutencaoHandler,
} from '../dashboard/manutencoes.handler';
import {
  getAgentExpandedMetrics,
  saveAgentDashboardConfig,
  getMetricsCatalog,
} from '../dashboard/agent-metrics.handler';
import { legacyAuthMiddleware, AuthenticatedRequest } from '../middleware/auth.middleware';

/**
 * Auth middleware wrapper for compatibility
 */
async function authMiddleware(
  request: import('fastify').FastifyRequest,
  reply: import('fastify').FastifyReply
): Promise<void> {
  await legacyAuthMiddleware(request, reply);
  const authRequest = request as AuthenticatedRequest;
  if (authRequest.user) {
    (request as unknown as { user: { id: string } }).user = { id: authRequest.user.userId };
  }
}

/**
 * Register dashboard routes
 */
export async function registerDashboardRoutes(fastify: FastifyInstance): Promise<void> {
  console.info('[DashboardRoutes] Registering dashboard routes...');

  // ==========================================================================
  // DASHBOARD STATS
  // ==========================================================================

  // GET /api/dashboard/stats - Estatísticas do dashboard
  fastify.get<{ Querystring: { user_id?: string } }>(
    '/api/dashboard/stats',
    { preHandler: authMiddleware },
    getDashboardStats
  );

  // GET /api/dashboard/leads-by-category - Leads por categoria
  fastify.get<{ Querystring: { user_id?: string; period?: string; category: string } }>(
    '/api/dashboard/leads-by-category',
    { preHandler: authMiddleware },
    getLeadsByCategory
  );

  // GET /api/dashboard/leads - Leads por origem
  fastify.get<{ Querystring: { user_id?: string; origin: string; limit?: string } }>(
    '/api/dashboard/leads',
    { preHandler: authMiddleware },
    getLeadsByOrigin
  );

  // ==========================================================================
  // ASAAS DASHBOARD
  // ==========================================================================

  // GET /api/dashboard/asaas - Dados financeiros do Asaas
  fastify.get(
    '/api/dashboard/asaas',
    { preHandler: authMiddleware },
    getAsaasDashboardHandler
  );

  // POST /api/dashboard/asaas/parse-contract/:subscriptionId - Parse PDF contract
  fastify.post(
    '/api/dashboard/asaas/parse-contract/:subscriptionId',
    { preHandler: authMiddleware },
    parseContractHandler
  );

  // POST /api/dashboard/asaas/parse-all-contracts - Parse ALL pending contracts
  fastify.post(
    '/api/dashboard/asaas/parse-all-contracts',
    { preHandler: authMiddleware },
    parseAllContractsHandler
  );

  // GET /api/dashboard/asaas/customers - Lista todos os clientes do Asaas
  fastify.get(
    '/api/dashboard/asaas/customers',
    { preHandler: authMiddleware },
    getAsaasCustomersHandler
  );

  // GET /api/dashboard/asaas/parcelamentos - Lista clientes com parcelamento
  fastify.get(
    '/api/dashboard/asaas/parcelamentos',
    { preHandler: authMiddleware },
    getAsaasParcelamentosHandler
  );

  // POST /api/dashboard/asaas/sync-all - Sincroniza todos os dados do Asaas
  fastify.post(
    '/api/dashboard/asaas/sync-all',
    { preHandler: authMiddleware },
    syncAllAsaasHandler
  );

  // GET /api/dashboard/asaas/available-months - Lista meses com cobranças
  fastify.get(
    '/api/dashboard/asaas/available-months',
    { preHandler: authMiddleware },
    getAsaasAvailableMonthsHandler
  );

  // ==========================================================================
  // MAINTENANCE (MANUTENCOES)
  // ==========================================================================

  // GET /api/dashboard/manutencoes - Listar todas as manutenções
  fastify.get<{ Querystring: { user_id?: string; agent_id?: string; status?: string } }>(
    '/api/dashboard/manutencoes',
    { preHandler: authMiddleware },
    getManutencoesHandler
  );

  // PATCH /api/dashboard/manutencoes/:id - Atualizar status de manutenção
  fastify.patch<{ Params: { id: string }; Body: { status: string } }>(
    '/api/dashboard/manutencoes/:id',
    { preHandler: authMiddleware },
    updateMaintenanceStatusHandler
  );

  // GET /api/dashboard/manutencoes/resumo - Dashboard de manutenções
  fastify.get<{ Querystring: { user_id?: string; agent_id?: string; month?: string } }>(
    '/api/dashboard/manutencoes/resumo',
    { preHandler: authMiddleware },
    getManutencoesDashboardHandler
  );

  // POST /api/dashboard/manutencoes/:id/concluir - Marcar manutenção como concluída
  fastify.post<{ Params: { id: string } }>(
    '/api/dashboard/manutencoes/:id/concluir',
    { preHandler: authMiddleware },
    concluirManutencaoHandler
  );

  // ==========================================================================
  // AGENT EXPANDED METRICS
  // ==========================================================================

  // GET /api/agents/:agent_id/metrics - Métricas expandidas do agente
  fastify.get<{ Params: { agent_id: string } }>(
    '/api/agents/:agent_id/metrics',
    { preHandler: authMiddleware },
    getAgentExpandedMetrics
  );

  // POST /api/agents/:agent_id/dashboard-config - Salvar preferência de métricas
  fastify.post<{ Params: { agent_id: string }; Body: { selected_metrics: string[] } }>(
    '/api/agents/:agent_id/dashboard-config',
    { preHandler: authMiddleware },
    saveAgentDashboardConfig
  );

  // GET /api/metrics-catalog/:agent_type - Catálogo de métricas disponíveis
  fastify.get<{ Params: { agent_type: string } }>(
    '/api/metrics-catalog/:agent_type',
    { preHandler: authMiddleware },
    getMetricsCatalog
  );

  console.info('[DashboardRoutes] Dashboard routes registered.');
}
