import { FastifyRequest, FastifyReply } from 'fastify';
import { supabaseAdmin } from '../../../services/supabase/client';
import { AsaasClient } from '../../../services/asaas/client';

/**
 * GET /api/dashboard/asaas/customers
 *
 * Returns all customers from Asaas API for the authenticated user's agent.
 */
export async function getAsaasCustomersHandler(
  request: FastifyRequest,
  reply: FastifyReply
) {
  try {
    const user_id = (request as any).user?.id;
    if (!user_id) {
      return reply.status(400).send({ status: 'error', message: 'Authentication required' });
    }

    // Get agentId from query params or find the user's agent with Asaas
    const queryAgentId = (request.query as any)?.agentId;

    let agent: { id: string; asaas_api_key: string } | null = null;

    if (queryAgentId) {
      const { data } = await supabaseAdmin
        .from('agents')
        .select('id, asaas_api_key')
        .eq('id', queryAgentId)
        .eq('user_id', user_id)
        .not('asaas_api_key', 'is', null)
        .single();
      agent = data;
    } else {
      const { data: agents } = await supabaseAdmin
        .from('agents')
        .select('id, asaas_api_key')
        .eq('user_id', user_id)
        .not('asaas_api_key', 'is', null)
        .limit(1);
      agent = agents?.[0] || null;
    }

    if (!agent) {
      return reply.status(404).send({ status: 'error', message: 'No Asaas integration found' });
    }

    // Data filter: only clients created from January 2026 onwards
    const DATA_FILTRO_CLIENTES = '2026-01-01';

    // Fetch all customers from Asaas
    const asaasClient = new AsaasClient({ apiKey: agent.asaas_api_key });
    const allCustomers = [];
    let offset = 0;
    const limit = 100;

    while (true) {
      const response = await asaasClient.listCustomers({ offset, limit });
      allCustomers.push(...response.data);

      if (!response.hasMore || response.data.length < limit) {
        break;
      }
      offset += limit;

      // Safety limit
      if (allCustomers.length >= 1000) {
        console.warn('[AsaasCustomers] Reached 1000 customer limit');
        break;
      }
    }

    // Filter clients by registration date (>= February 2026)
    const filteredCustomers = allCustomers.filter(c =>
      c.dateCreated && c.dateCreated >= DATA_FILTRO_CLIENTES
    );

    return reply.send({
      status: 'success',
      data: filteredCustomers.map(c => ({
        id: c.id,
        name: c.name,
        cpfCnpj: c.cpfCnpj,
        email: c.email,
        phone: c.phone,
        mobilePhone: c.mobilePhone,
        dateCreated: c.dateCreated,
      })),
    });

  } catch (error) {
    console.error('[AsaasCustomers] Error:', error);
    return reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

/**
 * GET /api/dashboard/asaas/parcelamentos
 *
 * Returns all installment customers (quebras de contrato) for the authenticated user's agent.
 * Fetches from the asaas_parcelamentos cache table.
 */
export async function getAsaasParcelamentosHandler(
  request: FastifyRequest,
  reply: FastifyReply
) {
  try {
    const user_id = (request as any).user?.id;
    if (!user_id) {
      return reply.status(400).send({ status: 'error', message: 'Authentication required' });
    }

    // Get agentId from query params or find the user's agent with Asaas
    const queryAgentId = (request.query as any)?.agentId;

    let agent: { id: string } | null = null;

    if (queryAgentId) {
      const { data } = await supabaseAdmin
        .from('agents')
        .select('id')
        .eq('id', queryAgentId)
        .eq('user_id', user_id)
        .single();
      agent = data;
    } else {
      const { data: agents } = await supabaseAdmin
        .from('agents')
        .select('id')
        .eq('user_id', user_id)
        .not('asaas_api_key', 'is', null)
        .limit(1);
      agent = agents?.[0] || null;
    }

    if (!agent) {
      return reply.status(404).send({ status: 'error', message: 'No Asaas integration found' });
    }

    // Fetch parcelamentos from cache table
    const { data: parcelamentos, error } = await supabaseAdmin
      .from('asaas_parcelamentos')
      .select('*')
      .eq('agent_id', agent.id)
      .eq('deleted', false)
      .order('date_created', { ascending: false });

    if (error) {
      console.error('[AsaasParcelamentos] Error fetching:', error);
      return reply.status(500).send({ status: 'error', message: 'Error fetching parcelamentos' });
    }

    // Get unique customers with their parcelamento details
    const customerMap = new Map<string, any>();
    for (const p of parcelamentos || []) {
      if (!customerMap.has(p.customer_id)) {
        customerMap.set(p.customer_id, {
          customer_id: p.customer_id,
          customer_name: p.customer_name,
          parcelamentos: [],
          total_value: 0,
        });
      }
      const customer = customerMap.get(p.customer_id);
      customer.parcelamentos.push({
        id: p.id,
        installment_count: p.installment_count,
        value: p.value,
        billing_type: p.billing_type,
        date_created: p.date_created,
      });
      customer.total_value += Number(p.value) || 0;
    }

    const customers = Array.from(customerMap.values());

    return reply.send({
      status: 'success',
      data: customers,
      total_parcelamentos: parcelamentos?.length || 0,
      total_clientes: customers.length,
    });

  } catch (error) {
    console.error('[AsaasParcelamentos] Error:', error);
    return reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

/**
 * GET /api/dashboard/asaas/available-months
 *
 * Returns list of months that have charges in asaas_cobrancas table.
 * Used to populate month filter dropdown with real data instead of hardcoded "last 6 months".
 */
export async function getAsaasAvailableMonthsHandler(
  request: FastifyRequest,
  reply: FastifyReply
) {
  try {
    const user_id = (request as any).user?.id;
    if (!user_id) {
      return reply.status(400).send({ status: 'error', message: 'Authentication required' });
    }

    // Get agentId from query params or find the user's agent with Asaas
    const queryAgentId = (request.query as any)?.agentId;

    let agent: { id: string } | null = null;

    if (queryAgentId) {
      const { data } = await supabaseAdmin
        .from('agents')
        .select('id')
        .eq('id', queryAgentId)
        .eq('user_id', user_id)
        .single();
      agent = data;
    } else {
      const { data: agents } = await supabaseAdmin
        .from('agents')
        .select('id')
        .eq('user_id', user_id)
        .not('asaas_api_key', 'is', null)
        .limit(1);
      agent = agents?.[0] || null;
    }

    if (!agent) {
      return reply.status(404).send({ status: 'error', message: 'No Asaas integration found' });
    }

    // Fetch all charges for this agent (non-deleted only)
    // Use due_date (vencimento) instead of date_created for filtering by month
    const { data: cobrancas, error } = await supabaseAdmin
      .from('asaas_cobrancas')
      .select('due_date')
      .eq('agent_id', agent.id)
      .eq('deleted_from_asaas', false)
      .not('due_date', 'is', null);

    if (error) {
      console.error('[AsaasAvailableMonths] Error fetching charges:', error);
      // Fallback: return empty array to allow frontend to use default behavior
      return reply.send({
        status: 'success',
        data: [],
      });
    }

    // Extract unique months and count charges per month
    const monthsMap = new Map<string, number>();

    for (const cobranca of cobrancas || []) {
      const dueDate = cobranca.due_date;
      if (!dueDate) continue;

      // Extract YYYY-MM from due_date (format: YYYY-MM-DD)
      const monthKey = dueDate.substring(0, 7); // Get "YYYY-MM"
      monthsMap.set(monthKey, (monthsMap.get(monthKey) || 0) + 1);
    }

    // Convert to array and sort DESC (most recent first)
    const months = Array.from(monthsMap.entries())
      .map(([monthKey, count]) => {
        const [year, month] = monthKey.split('-');
        const date = new Date(parseInt(year), parseInt(month) - 1, 1);
        const label = date.toLocaleDateString('pt-BR', { month: 'long', year: 'numeric' });
        const labelCapitalized = label.charAt(0).toUpperCase() + label.slice(1);

        return {
          month: monthKey, // YYYY-MM format
          label: labelCapitalized,
          count,
        };
      })
      .sort((a, b) => b.month.localeCompare(a.month)); // Sort DESC

    return reply.send({
      status: 'success',
      data: months,
    });

  } catch (error) {
    console.error('[AsaasAvailableMonths] Error:', error);
    return reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}
