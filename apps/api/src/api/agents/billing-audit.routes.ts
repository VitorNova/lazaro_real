/**
 * Billing & Audit Routes
 *
 * Extracted from index.legacy.ts - Phase 9.11
 *
 * Groups:
 * - Billing API (stats, token statement, invoices, upgrade, recharge)
 * - Audit Logs API
 * - Interventions API (human takeover)
 * - Integrations API
 */

import { FastifyInstance, FastifyRequest, FastifyReply } from 'fastify';
import {
  getBillingStatsHandler,
  getTokenStatementHandler,
  getInvoicesHandler,
  upgradePlanHandler,
  rechargeTokensHandler,
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
 * Register billing, audit, interventions, and integrations routes
 */
export async function registerBillingAuditRoutes(fastify: FastifyInstance): Promise<void> {
  console.info('[BillingAuditRoutes] Registering billing and audit routes...');

  // ==========================================================================
  // BILLING API
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
  // AUDIT LOGS API
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
  // INTERVENTIONS API
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
  fastify.get<{ Querystring: { agent_id?: string } }>(
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
  // INTEGRATIONS API
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

  console.info('[BillingAuditRoutes] Billing and audit routes registered.');
}
