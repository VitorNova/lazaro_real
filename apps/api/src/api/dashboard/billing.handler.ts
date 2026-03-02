import { FastifyRequest, FastifyReply } from 'fastify';
import { supabaseAdmin } from '../../services/supabase/client';
import { AsaasClient } from '../../services/asaas/client';
import { BillingType, ChargeType } from '../../services/asaas/types';

// ============================================================================
// TYPES
// ============================================================================

interface BillingStats {
  totalRevenue: number;
  totalRevenueChange: string;
  pendingAmount: number;
  pendingAmountChange: string;
  overdueAmount: number;
  overdueAmountChange: string;
  paidThisMonth: number;
  paidThisMonthChange: string;
  tokenUsage: number;
  tokenLimit: number;
  planName: string;
  planAmount: string;
  nextInvoiceDate: string;
}

interface TokenStatement {
  id: string;
  agent: string;
  task: string;
  amount: string;
  time: string;
  created_at: string;
}

interface Invoice {
  id: string;
  date: string;
  amount: string;
  status: 'paid' | 'pending' | 'overdue';
  pdf_url?: string;
}

// ============================================================================
// HANDLERS
// ============================================================================

/**
 * GET /api/billing/stats - Estatísticas de billing do usuário
 * Agrega dados de asaas_cobrancas, asaas_contratos e user_plans
 */
export async function getBillingStatsHandler(
  request: FastifyRequest<{ Querystring: { agent_id?: string } }>,
  reply: FastifyReply
): Promise<void> {
  try {
    const userId = (request as any).user?.id;
    const { agent_id } = request.query;

    if (!userId) {
      reply.status(401).send({ status: 'error', message: 'Authentication required' });
      return;
    }

    // Buscar agentes do usuário
    let agentsQuery = supabaseAdmin
      .from('agents')
      .select('id, name, asaas_api_key')
      .eq('user_id', userId);

    if (agent_id) {
      agentsQuery = agentsQuery.eq('id', agent_id);
    }

    const { data: agents, error: agentsError } = await agentsQuery;

    if (agentsError) {
      console.error('[BillingStats] Error fetching agents:', agentsError);
      reply.status(500).send({ status: 'error', message: 'Failed to fetch agents' });
      return;
    }

    if (!agents || agents.length === 0) {
      reply.send({
        status: 'success',
        data: {
          totalRevenue: 0,
          totalRevenueChange: '0%',
          activeSubscriptions: 0,
          pendingPayments: 0,
          overduePayments: 0,
          recentPayments: [],
          revenueByMonth: [],
          planDistribution: [],
        },
      });
      return;
    }

    const agentIds = agents.map(a => a.id);

    // Buscar cobranças
    const { data: cobrancas, error: cobrancasError } = await supabaseAdmin
      .from('asaas_cobrancas')
      .select('*')
      .in('agent_id', agentIds)
      .eq('deleted', false)
      .order('due_date', { ascending: false })
      .limit(100);

    if (cobrancasError) {
      console.error('[BillingStats] Error fetching cobrancas:', cobrancasError);
    }

    // Buscar contratos ativos
    const { data: contratos, error: contratosError } = await supabaseAdmin
      .from('asaas_contratos')
      .select('*')
      .in('agent_id', agentIds)
      .eq('deleted', false)
      .eq('status', 'ACTIVE');

    if (contratosError) {
      console.error('[BillingStats] Error fetching contratos:', contratosError);
    }

    // Calcular métricas
    const now = new Date();
    const startOfMonth = new Date(now.getFullYear(), now.getMonth(), 1);
    const startOfLastMonth = new Date(now.getFullYear(), now.getMonth() - 1, 1);
    const endOfLastMonth = new Date(now.getFullYear(), now.getMonth(), 0);

    // Receita do mês atual (cobranças pagas)
    const currentMonthRevenue = (cobrancas || [])
      .filter(c => {
        const paidDate = c.payment_date ? new Date(c.payment_date) : null;
        return paidDate && paidDate >= startOfMonth && c.status === 'RECEIVED';
      })
      .reduce((sum, c) => sum + (c.value || 0), 0);

    // Receita do mês passado
    const lastMonthRevenue = (cobrancas || [])
      .filter(c => {
        const paidDate = c.payment_date ? new Date(c.payment_date) : null;
        return paidDate && paidDate >= startOfLastMonth && paidDate <= endOfLastMonth && c.status === 'RECEIVED';
      })
      .reduce((sum, c) => sum + (c.value || 0), 0);

    // Calcular mudança
    const revenueChange = lastMonthRevenue === 0
      ? (currentMonthRevenue > 0 ? '+100%' : '0%')
      : `${((currentMonthRevenue - lastMonthRevenue) / lastMonthRevenue * 100).toFixed(1)}%`;

    // Valores pendentes e vencidos (soma em R$, não count)
    const pendingAmount = (cobrancas || [])
      .filter(c => c.status === 'PENDING')
      .reduce((sum, c) => sum + (c.value || 0), 0);

    const overdueAmount = (cobrancas || [])
      .filter(c => c.status === 'OVERDUE')
      .reduce((sum, c) => sum + (c.value || 0), 0);

    // Próxima cobrança (menor data futura)
    const nextInvoice = (cobrancas || [])
      .filter(c => c.status === 'PENDING' && new Date(c.due_date) >= now)
      .sort((a, b) => new Date(a.due_date).getTime() - new Date(b.due_date).getTime())[0];

    // Estimar tokens (count de audit logs * 50)
    const { count: auditCount } = await supabaseAdmin
      .from('agent_audit_logs')
      .select('*', { count: 'exact', head: true })
      .in('agent_id', agentIds);

    const tokenUsage = (auditCount || 0) * 50;

    // TODO: Buscar plano real de user_plans
    const planName = 'Free';
    const planAmount = 'R$ 0,00';
    const tokenLimit = 10000;

    reply.send({
      status: 'success',
      data: {
        totalRevenue: currentMonthRevenue,
        totalRevenueChange: revenueChange,
        pendingAmount,
        pendingAmountChange: '0%', // TODO: calcular comparado ao mês passado
        overdueAmount,
        overdueAmountChange: '0%', // TODO: calcular comparado ao mês passado
        paidThisMonth: currentMonthRevenue,
        paidThisMonthChange: revenueChange,
        tokenUsage,
        tokenLimit,
        planName,
        planAmount,
        nextInvoiceDate: nextInvoice?.due_date || '',
      },
    });
  } catch (error) {
    console.error('[BillingStats] Error:', error);
    reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

/**
 * GET /api/billing/token-statement - Extrato de consumo de tokens
 */
export async function getTokenStatementHandler(
  request: FastifyRequest<{ Querystring: { limit?: string; offset?: string } }>,
  reply: FastifyReply
): Promise<void> {
  try {
    const userId = (request as any).user?.id;
    const limit = parseInt(request.query.limit || '50', 10);
    const offset = parseInt(request.query.offset || '0', 10);

    if (!userId) {
      reply.status(401).send({ status: 'error', message: 'Authentication required' });
      return;
    }

    // Buscar agentes do usuário
    const { data: agents, error: agentsError } = await supabaseAdmin
      .from('agents')
      .select('id')
      .eq('user_id', userId);

    if (agentsError) {
      console.error('[TokenStatement] Error fetching agents:', agentsError);
      reply.status(500).send({ status: 'error', message: 'Failed to fetch agents' });
      return;
    }

    if (!agents || agents.length === 0) {
      reply.send({
        status: 'success',
        data: { statements: [], total: 0 },
      });
      return;
    }

    const agentIds = agents.map(a => a.id);

    // Buscar logs de auditoria com JOIN para pegar nome do agente
    const { data: logs, error: logsError, count } = await supabaseAdmin
      .from('agent_audit_logs')
      .select('id, agent_id, action, duration_ms, created_at, agents!inner(name)', { count: 'exact' })
      .in('agent_id', agentIds)
      .order('created_at', { ascending: false })
      .range(offset, offset + limit - 1);

    if (logsError) {
      console.error('[TokenStatement] Error fetching logs:', logsError);
      reply.status(500).send({ status: 'error', message: 'Failed to fetch token statement' });
      return;
    }

    // Mapear para formato TokenStatement
    const statements: TokenStatement[] = (logs || []).map((log: any) => ({
      id: log.id.toString(),
      agent: log.agents?.name || 'Agente',
      task: log.action || 'Ação não especificada',
      amount: '50', // Estimativa fixa de 50 tokens por ação
      time: log.duration_ms ? log.duration_ms.toString() : '0',
      created_at: log.created_at,
    }));

    reply.send({
      status: 'success',
      data: {
        statements,
        total: count || 0,
      },
    });
  } catch (error) {
    console.error('[TokenStatement] Error:', error);
    reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

/**
 * GET /api/billing/invoices - Histórico de faturas
 */
export async function getInvoicesHandler(
  request: FastifyRequest<{ Querystring: { limit?: string; offset?: string } }>,
  reply: FastifyReply
): Promise<void> {
  try {
    const userId = (request as any).user?.id;
    const limit = parseInt(request.query.limit || '20', 10);
    const offset = parseInt(request.query.offset || '0', 10);

    if (!userId) {
      reply.status(401).send({ status: 'error', message: 'Authentication required' });
      return;
    }

    // Buscar agentes do usuário
    const { data: agents, error: agentsError } = await supabaseAdmin
      .from('agents')
      .select('id')
      .eq('user_id', userId);

    if (agentsError) {
      console.error('[Invoices] Error fetching agents:', agentsError);
      reply.status(500).send({ status: 'error', message: 'Failed to fetch agents' });
      return;
    }

    if (!agents || agents.length === 0) {
      reply.send({
        status: 'success',
        data: { invoices: [], total: 0 },
      });
      return;
    }

    const agentIds = agents.map(a => a.id);

    // Buscar cobranças do Asaas
    const { data: cobrancas, error: cobrancasError, count } = await supabaseAdmin
      .from('asaas_cobrancas')
      .select('id, due_date, value, status, invoice_url', { count: 'exact' })
      .in('agent_id', agentIds)
      .eq('deleted', false)
      .order('due_date', { ascending: false })
      .range(offset, offset + limit - 1);

    if (cobrancasError) {
      console.error('[Invoices] Error fetching cobrancas:', cobrancasError);
      reply.status(500).send({ status: 'error', message: 'Failed to fetch invoices' });
      return;
    }

    // Mapear status Asaas para status frontend
    const mapStatus = (status: string): 'paid' | 'pending' | 'overdue' => {
      if (status === 'RECEIVED' || status === 'CONFIRMED') return 'paid';
      if (status === 'OVERDUE') return 'overdue';
      return 'pending';
    };

    // Mapear para formato Invoice
    const invoices: Invoice[] = (cobrancas || []).map(c => ({
      id: c.id,
      date: c.due_date,
      amount: c.value ? c.value.toFixed(2) : '0.00',
      status: mapStatus(c.status),
      pdf_url: c.invoice_url || undefined,
    }));

    reply.send({
      status: 'success',
      data: {
        invoices,
        total: count || 0,
      },
    });
  } catch (error) {
    console.error('[Invoices] Error:', error);
    reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

/**
 * POST /api/billing/upgrade - Criar link de pagamento para upgrade de plano
 */
export async function upgradePlanHandler(
  request: FastifyRequest<{ Body: { planId: string } }>,
  reply: FastifyReply
): Promise<void> {
  try {
    const userId = (request as any).user?.id;
    const { planId } = request.body;

    if (!userId) {
      reply.status(401).send({ status: 'error', message: 'Authentication required' });
      return;
    }

    if (!planId) {
      reply.status(400).send({ status: 'error', message: 'planId is required' });
      return;
    }

    // Planos disponíveis (hardcoded por enquanto)
    const plans: Record<string, { name: string; price: number }> = {
      starter: { name: 'Starter', price: 97 },
      professional: { name: 'Professional', price: 197 },
      enterprise: { name: 'Enterprise', price: 497 },
    };

    const plan = plans[planId];
    if (!plan) {
      reply.status(400).send({ status: 'error', message: 'Invalid planId' });
      return;
    }

    // Buscar primeiro agente do usuário para obter API key
    const { data: agent, error: agentError } = await supabaseAdmin
      .from('agents')
      .select('id, asaas_api_key')
      .eq('user_id', userId)
      .limit(1)
      .single();

    if (agentError || !agent || !agent.asaas_api_key) {
      console.error('[UpgradePlan] No agent with Asaas API key found:', agentError);
      reply.status(400).send({ status: 'error', message: 'No payment integration configured' });
      return;
    }

    // Criar cliente Asaas
    const asaasClient = new AsaasClient({ apiKey: agent.asaas_api_key });

    // Criar payment link
    const paymentLink = await asaasClient.createPaymentLink({
      name: `Upgrade para Plano ${plan.name}`,
      description: `Assinatura do plano ${plan.name} - PHANT`,
      value: plan.price,
      billingType: BillingType.UNDEFINED, // Permite escolher forma de pagamento
      chargeType: ChargeType.DETACHED, // Cobrança única (não recorrente)
      externalReference: `plan:${planId}:${userId}`,
      notificationEnabled: true,
    });

    reply.send({
      status: 'success',
      data: {
        success: true,
        checkout_url: paymentLink.url,
      },
    });
  } catch (error) {
    console.error('[UpgradePlan] Error:', error);
    reply.status(500).send({ status: 'error', message: 'Failed to create payment link' });
  }
}

/**
 * POST /api/billing/recharge - Criar link de pagamento para recarga de tokens
 */
export async function rechargeTokensHandler(
  request: FastifyRequest<{ Body: { amount: number } }>,
  reply: FastifyReply
): Promise<void> {
  try {
    const userId = (request as any).user?.id;
    const { amount } = request.body;

    if (!userId) {
      reply.status(401).send({ status: 'error', message: 'Authentication required' });
      return;
    }

    if (!amount || amount < 10 || amount > 1000) {
      reply.status(400).send({ status: 'error', message: 'Amount must be between R$ 10 and R$ 1000' });
      return;
    }

    // Buscar primeiro agente do usuário para obter API key
    const { data: agent, error: agentError } = await supabaseAdmin
      .from('agents')
      .select('id, asaas_api_key')
      .eq('user_id', userId)
      .limit(1)
      .single();

    if (agentError || !agent || !agent.asaas_api_key) {
      console.error('[RechargeTokens] No agent with Asaas API key found:', agentError);
      reply.status(400).send({ status: 'error', message: 'No payment integration configured' });
      return;
    }

    // Criar cliente Asaas
    const asaasClient = new AsaasClient({ apiKey: agent.asaas_api_key });

    // Criar payment link
    const paymentLink = await asaasClient.createPaymentLink({
      name: `Recarga de Tokens - R$ ${amount.toFixed(2)}`,
      description: `Recarga de tokens para uso da IA - PHANT`,
      value: amount,
      billingType: BillingType.UNDEFINED, // Permite escolher forma de pagamento
      chargeType: ChargeType.DETACHED, // Cobrança única (não recorrente)
      externalReference: `tokens:${amount}:${userId}`,
      notificationEnabled: true,
    });

    reply.send({
      status: 'success',
      data: {
        success: true,
        checkout_url: paymentLink.url,
      },
    });
  } catch (error) {
    console.error('[RechargeTokens] Error:', error);
    reply.status(500).send({ status: 'error', message: 'Failed to create payment link' });
  }
}
