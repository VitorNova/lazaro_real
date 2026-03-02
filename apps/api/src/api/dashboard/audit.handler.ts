import { FastifyRequest, FastifyReply } from 'fastify';
import { supabaseAdmin } from '../../services/supabase/client';

// ============================================================================
// TYPES
// ============================================================================

interface AuditLogEntry {
  id: string;
  agent_id: string;
  agent_name?: string;
  lead_id?: string;
  action: string;
  action_category?: string;
  trigger_text?: string;
  reasoning?: string;
  tool_name?: string;
  tool_input?: any;
  tool_output?: any;
  success: boolean;
  error_message?: string;
  duration_ms?: number;
  metadata?: any;
  created_at: string;
}

interface AuditLogsResponse {
  logs: AuditLogEntry[];
  total: number;
  page: number;
  limit: number;
  categories: string[];
}

// ============================================================================
// HANDLERS
// ============================================================================

/**
 * GET /api/audit/logs - Logs de auditoria das ações dos agentes
 * Usado no TrustCenter para transparência e rastreabilidade
 */
export async function getAuditLogsHandler(
  request: FastifyRequest<{
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
  }>,
  reply: FastifyReply
): Promise<void> {
  try {
    const userId = (request as any).user?.id;
    const {
      agent_id,
      action,
      category,
      lead_id,
      success,
      page = '1',
      limit = '50',
      start_date,
      end_date,
    } = request.query;

    if (!userId) {
      reply.status(401).send({ status: 'error', message: 'Authentication required' });
      return;
    }

    const pageNum = parseInt(page, 10);
    const limitNum = Math.min(parseInt(limit, 10), 100);
    const offset = (pageNum - 1) * limitNum;

    // Buscar agentes do usuário para filtrar
    const { data: userAgents } = await supabaseAdmin
      .from('agents')
      .select('id, name')
      .eq('user_id', userId);

    if (!userAgents || userAgents.length === 0) {
      reply.send({
        status: 'success',
        data: {
          logs: [],
          total: 0,
          page: pageNum,
          limit: limitNum,
          categories: [],
        },
      });
      return;
    }

    const agentIds = userAgents.map(a => a.id);
    const agentMap = new Map(userAgents.map(a => [a.id, a.name]));

    // Construir query
    let query = supabaseAdmin
      .from('agent_audit_logs')
      .select('*', { count: 'exact' })
      .in('agent_id', agentIds)
      .order('created_at', { ascending: false })
      .range(offset, offset + limitNum - 1);

    // Aplicar filtros
    if (agent_id) {
      query = query.eq('agent_id', agent_id);
    }
    if (action) {
      query = query.eq('action', action);
    }
    if (category) {
      query = query.eq('action_category', category);
    }
    if (lead_id) {
      query = query.eq('lead_id', lead_id);
    }
    if (success !== undefined) {
      query = query.eq('success', success === 'true');
    }
    if (start_date) {
      query = query.gte('created_at', start_date);
    }
    if (end_date) {
      query = query.lte('created_at', end_date);
    }

    const { data: logs, error, count } = await query;

    if (error) {
      console.error('[AuditLogs] Error fetching logs:', error);
      reply.status(500).send({ status: 'error', message: 'Failed to fetch audit logs' });
      return;
    }

    // Adicionar nome do agente aos logs
    const logsWithAgentName = (logs || []).map(log => ({
      ...log,
      agent_name: agentMap.get(log.agent_id) || 'Unknown',
    }));

    // Buscar categorias distintas
    const { data: categoriesData } = await supabaseAdmin
      .from('agent_audit_logs')
      .select('action_category')
      .in('agent_id', agentIds)
      .not('action_category', 'is', null);

    const categories = [...new Set((categoriesData || []).map(c => c.action_category).filter(Boolean))];

    reply.send({
      status: 'success',
      data: {
        logs: logsWithAgentName,
        total: count || 0,
        page: pageNum,
        limit: limitNum,
        categories,
      },
    });
  } catch (error) {
    console.error('[AuditLogs] Error:', error);
    reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

/**
 * POST /api/audit/logs - Criar uma entrada de log de auditoria
 * Chamado internamente pelos agentes quando executam ações
 */
export async function createAuditLogHandler(
  request: FastifyRequest<{
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
  }>,
  reply: FastifyReply
): Promise<void> {
  try {
    const userId = (request as any).user?.id;
    const body = request.body;

    if (!userId) {
      reply.status(401).send({ status: 'error', message: 'Authentication required' });
      return;
    }

    // Verificar se agente pertence ao usuário
    const { data: agent } = await supabaseAdmin
      .from('agents')
      .select('id')
      .eq('id', body.agent_id)
      .eq('user_id', userId)
      .single();

    if (!agent) {
      reply.status(404).send({ status: 'error', message: 'Agent not found' });
      return;
    }

    // Criar entrada de log
    const { data: log, error } = await supabaseAdmin
      .from('agent_audit_logs')
      .insert({
        agent_id: body.agent_id,
        lead_id: body.lead_id,
        action: body.action,
        action_category: body.action_category,
        trigger_text: body.trigger_text,
        reasoning: body.reasoning,
        tool_name: body.tool_name,
        tool_input: body.tool_input,
        tool_output: body.tool_output,
        success: body.success ?? true,
        error_message: body.error_message,
        duration_ms: body.duration_ms,
        metadata: body.metadata,
      })
      .select()
      .single();

    if (error) {
      console.error('[AuditLogs] Error creating log:', error);
      reply.status(500).send({ status: 'error', message: 'Failed to create audit log' });
      return;
    }

    reply.send({ status: 'success', data: log });
  } catch (error) {
    console.error('[AuditLogs] Error:', error);
    reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}
