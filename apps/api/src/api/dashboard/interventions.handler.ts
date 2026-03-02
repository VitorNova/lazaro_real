import { FastifyRequest, FastifyReply } from 'fastify';
import { supabaseAdmin } from '../../services/supabase/client';

// ============================================================================
// TYPES
// ============================================================================

interface InterventionLead {
  id: string;
  remotejid: string;
  nome: string;
  telefone?: string;
  agent_id: string;
  agent_name?: string;
  pipeline_step?: string;
  current_state?: string;
  responsavel?: string;
  paused_at?: string;
  paused_by?: string;
  reason?: string;
  last_message_at?: string;
  created_at?: string;
}

interface InterventionsResponse {
  interventions: InterventionLead[];
  total: number;
  by_agent: Record<string, number>;
}

interface Intervention {
  id: string;
  lead_id: string;
  lead_name: string;
  lead_phone?: string;
  agent_id: string;
  agent_name?: string;
  reason: string;
  last_message: string;
  avatar?: string;
  status: 'pending' | 'in_progress' | 'resolved';
  assigned_to?: string;
  created_at: string;
  updated_at?: string;
  resolved_at?: string;
}

interface EscalationRules {
  auto_escalate_after_minutes?: number;
  notify_phone?: string;
  notify_email?: string;
  keywords?: string[];
}

// ============================================================================
// HANDLERS
// ============================================================================

/**
 * GET /api/interventions - Lista leads em human takeover (atendimento humano)
 * Usado no InterventionMonitor para gerenciar leads que precisam de atenção humana
 */
export async function getInterventionsHandler(
  request: FastifyRequest<{
    Querystring: {
      agent_id?: string;
      status?: string;
      page?: string;
      limit?: string;
    };
  }>,
  reply: FastifyReply
): Promise<void> {
  try {
    const userId = (request as any).user?.id;
    const { agent_id, status, page = '1', limit = '50' } = request.query;

    if (!userId) {
      reply.status(401).send({ status: 'error', message: 'Authentication required' });
      return;
    }

    const pageNum = parseInt(page, 10);
    const limitNum = Math.min(parseInt(limit, 10), 100);

    // Buscar agentes do usuário
    let agentsQuery = supabaseAdmin
      .from('agents')
      .select('id, name, table_leads')
      .eq('user_id', userId)
      .not('table_leads', 'is', null);

    if (agent_id) {
      agentsQuery = agentsQuery.eq('id', agent_id);
    }

    const { data: agents, error: agentsError } = await agentsQuery;

    if (agentsError || !agents || agents.length === 0) {
      reply.send({
        status: 'success',
        data: {
          interventions: [],
          total: 0,
          by_agent: {},
        },
      });
      return;
    }

    const interventions: InterventionLead[] = [];
    const byAgent: Record<string, number> = {};

    // Buscar leads em human takeover de cada agente
    for (const agent of agents) {
      if (!agent.table_leads) continue;

      try {
        // Leads em human takeover: Atendimento_Finalizado = 'true' ou current_state = 'paused'
        const { data: leads, error: leadsError } = await supabaseAdmin
          .from(agent.table_leads)
          .select('*')
          .or('Atendimento_Finalizado.eq.true,current_state.eq.paused,responsavel.eq.Humano')
          .order('updated_at', { ascending: false })
          .limit(limitNum);

        if (leadsError) {
          console.error(`[Interventions] Error fetching leads from ${agent.table_leads}:`, leadsError);
          continue;
        }

        const agentLeads = (leads || []).map(lead => ({
          id: lead.id,
          remotejid: lead.remotejid,
          nome: lead.nome || 'Lead sem nome',
          telefone: lead.telefone || lead.remotejid?.replace('@s.whatsapp.net', ''),
          agent_id: agent.id,
          agent_name: agent.name,
          pipeline_step: lead.pipeline_step,
          current_state: lead.current_state,
          responsavel: lead.responsavel,
          paused_at: lead.paused_at,
          paused_by: lead.paused_by,
          reason: lead.paused_reason,
          last_message_at: lead.updated_at,
          created_at: lead.created_at,
        }));

        interventions.push(...agentLeads);
        byAgent[agent.id] = agentLeads.length;
      } catch (err) {
        console.error(`[Interventions] Error processing agent ${agent.id}:`, err);
      }
    }

    // Ordenar por data de pausa (mais recentes primeiro)
    interventions.sort((a, b) => {
      const dateA = a.paused_at ? new Date(a.paused_at).getTime() : 0;
      const dateB = b.paused_at ? new Date(b.paused_at).getTime() : 0;
      return dateB - dateA;
    });

    // Aplicar paginação
    const paginatedInterventions = interventions.slice(
      (pageNum - 1) * limitNum,
      pageNum * limitNum
    );

    reply.send({
      status: 'success',
      data: {
        interventions: paginatedInterventions,
        total: interventions.length,
        by_agent: byAgent,
      },
    });
  } catch (error) {
    console.error('[Interventions] Error:', error);
    reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

/**
 * POST /api/interventions/:leadId/resolve - Resolver intervenção e retornar para IA
 */
export async function resolveInterventionHandler(
  request: FastifyRequest<{
    Params: { leadId: string };
    Body: { agent_id: string; notes?: string };
  }>,
  reply: FastifyReply
): Promise<void> {
  try {
    const userId = (request as any).user?.id;
    const { leadId } = request.params;
    const { agent_id, notes } = request.body;

    if (!userId) {
      reply.status(401).send({ status: 'error', message: 'Authentication required' });
      return;
    }

    if (!agent_id) {
      reply.status(400).send({ status: 'error', message: 'agent_id is required' });
      return;
    }

    // Verificar se agente pertence ao usuário
    const { data: agent, error: agentError } = await supabaseAdmin
      .from('agents')
      .select('id, name, table_leads')
      .eq('id', agent_id)
      .eq('user_id', userId)
      .single();

    if (agentError || !agent) {
      reply.status(404).send({ status: 'error', message: 'Agent not found' });
      return;
    }

    // Atualizar lead para retornar ao controle da IA
    const now = new Date().toISOString();
    const { error: updateError } = await supabaseAdmin
      .from(agent.table_leads)
      .update({
        Atendimento_Finalizado: 'false',
        current_state: 'ai',
        responsavel: 'AI',
        resumed_at: now,
        intervention_notes: notes,
        updated_at: now,
      })
      .eq('id', leadId);

    if (updateError) {
      console.error('[Interventions] Error resolving intervention:', updateError);
      reply.status(500).send({ status: 'error', message: 'Failed to resolve intervention' });
      return;
    }

    // Registrar log de auditoria
    await supabaseAdmin.from('agent_audit_logs').insert({
      agent_id,
      lead_id: leadId,
      action: 'intervention_resolved',
      action_category: 'handoff',
      reasoning: notes || 'Intervention resolved by operator',
      success: true,
    });

    reply.send({
      status: 'success',
      message: 'Intervention resolved, lead returned to AI control',
    });
  } catch (error) {
    console.error('[Interventions] Error:', error);
    reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

/**
 * GET /api/interventions/:id - Buscar intervenção específica
 */
export async function getInterventionByIdHandler(
  request: FastifyRequest<{
    Params: { id: string };
    Querystring: { agent_id: string };
  }>,
  reply: FastifyReply
): Promise<void> {
  try {
    const userId = (request as any).user?.id;
    const { id } = request.params;
    const { agent_id } = request.query;

    if (!userId) {
      reply.status(401).send({ status: 'error', message: 'Authentication required' });
      return;
    }

    if (!agent_id) {
      reply.status(400).send({ status: 'error', message: 'agent_id is required' });
      return;
    }

    // Verificar se agente pertence ao usuário
    const { data: agent, error: agentError } = await supabaseAdmin
      .from('agents')
      .select('id, name, table_leads')
      .eq('id', agent_id)
      .eq('user_id', userId)
      .single();

    if (agentError || !agent || !agent.table_leads) {
      reply.status(404).send({ status: 'error', message: 'Agent not found' });
      return;
    }

    // Buscar lead
    const { data: lead, error: leadError } = await supabaseAdmin
      .from(agent.table_leads)
      .select('*')
      .eq('id', id)
      .single();

    if (leadError || !lead) {
      reply.status(404).send({ status: 'error', message: 'Lead not found' });
      return;
    }

    // Buscar última mensagem
    const { data: messages } = await supabaseAdmin
      .from('message_logs')
      .select('content')
      .eq('remotejid', lead.remotejid)
      .order('timestamp', { ascending: false })
      .limit(1);

    const lastMessage = messages && messages.length > 0 ? messages[0].content : '';

    // Derivar status do current_state
    let status: 'pending' | 'in_progress' | 'resolved' = 'pending';
    if (lead.current_state === 'human' || lead.responsavel === 'Humano') {
      status = 'in_progress';
    } else if (lead.resumed_at) {
      status = 'resolved';
    }

    const intervention: Intervention = {
      id: lead.id,
      lead_id: lead.id,
      lead_name: lead.nome || 'Lead sem nome',
      lead_phone: lead.telefone || lead.remotejid?.replace('@s.whatsapp.net', ''),
      agent_id: agent.id,
      agent_name: agent.name,
      reason: lead.paused_reason || 'human_requested',
      last_message: lastMessage,
      status,
      assigned_to: lead.responsavel,
      created_at: lead.created_at,
      updated_at: lead.updated_at,
      resolved_at: lead.resumed_at,
    };

    reply.send({
      status: 'success',
      data: intervention,
    });
  } catch (error) {
    console.error('[Interventions] Error:', error);
    reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

/**
 * POST /api/interventions/:id/takeover - Assumir atendimento (pausar IA)
 */
export async function takeoverHandler(
  request: FastifyRequest<{
    Params: { id: string };
    Body: { agent_id: string };
  }>,
  reply: FastifyReply
): Promise<void> {
  try {
    const userId = (request as any).user?.id;
    const { id } = request.params;
    const { agent_id } = request.body;

    if (!userId) {
      reply.status(401).send({ status: 'error', message: 'Authentication required' });
      return;
    }

    if (!agent_id) {
      reply.status(400).send({ status: 'error', message: 'agent_id is required' });
      return;
    }

    // Buscar dados do usuário para registrar responsável
    const { data: userData, error: userError } = await supabaseAdmin
      .from('users')
      .select('name, email')
      .eq('id', userId)
      .single();

    const userName = userData?.name || userData?.email || 'Operador';

    // Verificar se agente pertence ao usuário
    const { data: agent, error: agentError } = await supabaseAdmin
      .from('agents')
      .select('id, name, table_leads')
      .eq('id', agent_id)
      .eq('user_id', userId)
      .single();

    if (agentError || !agent || !agent.table_leads) {
      reply.status(404).send({ status: 'error', message: 'Agent not found' });
      return;
    }

    // Buscar lead para pegar remotejid
    const { data: lead, error: leadError } = await supabaseAdmin
      .from(agent.table_leads)
      .select('remotejid')
      .eq('id', id)
      .single();

    if (leadError || !lead) {
      reply.status(404).send({ status: 'error', message: 'Lead not found' });
      return;
    }

    // Atualizar lead para estado humano
    const now = new Date().toISOString();
    const { error: updateError } = await supabaseAdmin
      .from(agent.table_leads)
      .update({
        current_state: 'human',
        responsavel: userName,
        paused_at: now,
        paused_by: userId,
        Atendimento_Finalizado: 'true',
        updated_at: now,
      })
      .eq('id', id);

    if (updateError) {
      console.error('[Interventions] Error taking over:', updateError);
      reply.status(500).send({ status: 'error', message: 'Failed to take over' });
      return;
    }

    // Registrar log de auditoria
    await supabaseAdmin.from('agent_audit_logs').insert({
      agent_id,
      lead_id: id,
      action: 'human_takeover',
      action_category: 'handoff',
      reasoning: `Takeover by ${userName}`,
      success: true,
    });

    // Gerar URL do WhatsApp Web
    const phoneNumber = lead.remotejid.replace('@s.whatsapp.net', '');
    const chatUrl = `https://web.whatsapp.com/send?phone=${phoneNumber}`;

    reply.send({
      status: 'success',
      data: {
        success: true,
        chat_url: chatUrl,
      },
    });
  } catch (error) {
    console.error('[Interventions] Error:', error);
    reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

/**
 * POST /api/interventions/:id/assign - Atribuir a outro operador
 */
export async function assignHandler(
  request: FastifyRequest<{
    Params: { id: string };
    Body: { agent_id: string; user_id: string };
  }>,
  reply: FastifyReply
): Promise<void> {
  try {
    const userId = (request as any).user?.id;
    const { id } = request.params;
    const { agent_id, user_id } = request.body;

    if (!userId) {
      reply.status(401).send({ status: 'error', message: 'Authentication required' });
      return;
    }

    if (!agent_id || !user_id) {
      reply.status(400).send({ status: 'error', message: 'agent_id and user_id are required' });
      return;
    }

    // Buscar nome do usuário que será assignado
    const { data: assignedUser, error: assignedUserError } = await supabaseAdmin
      .from('users')
      .select('name, email')
      .eq('id', user_id)
      .single();

    if (assignedUserError || !assignedUser) {
      reply.status(404).send({ status: 'error', message: 'User to assign not found' });
      return;
    }

    const assignedName = assignedUser.name || assignedUser.email || 'Operador';

    // Verificar se agente pertence ao usuário
    const { data: agent, error: agentError } = await supabaseAdmin
      .from('agents')
      .select('id, name, table_leads')
      .eq('id', agent_id)
      .eq('user_id', userId)
      .single();

    if (agentError || !agent || !agent.table_leads) {
      reply.status(404).send({ status: 'error', message: 'Agent not found' });
      return;
    }

    // Atualizar responsável
    const now = new Date().toISOString();
    const { error: updateError } = await supabaseAdmin
      .from(agent.table_leads)
      .update({
        responsavel: assignedName,
        paused_by: user_id,
        updated_at: now,
      })
      .eq('id', id);

    if (updateError) {
      console.error('[Interventions] Error assigning:', updateError);
      reply.status(500).send({ status: 'error', message: 'Failed to assign' });
      return;
    }

    // Registrar log de auditoria
    await supabaseAdmin.from('agent_audit_logs').insert({
      agent_id,
      lead_id: id,
      action: 'intervention_assigned',
      action_category: 'handoff',
      reasoning: `Assigned to ${assignedName} by user ${userId}`,
      success: true,
    });

    // Buscar lead atualizado para retornar
    const { data: lead, error: leadError } = await supabaseAdmin
      .from(agent.table_leads)
      .select('*')
      .eq('id', id)
      .single();

    if (leadError || !lead) {
      reply.status(404).send({ status: 'error', message: 'Lead not found after update' });
      return;
    }

    // Buscar última mensagem
    const { data: messages } = await supabaseAdmin
      .from('message_logs')
      .select('content')
      .eq('remotejid', lead.remotejid)
      .order('timestamp', { ascending: false })
      .limit(1);

    const lastMessage = messages && messages.length > 0 ? messages[0].content : '';

    // Derivar status
    let status: 'pending' | 'in_progress' | 'resolved' = 'pending';
    if (lead.current_state === 'human' || lead.responsavel === 'Humano') {
      status = 'in_progress';
    } else if (lead.resumed_at) {
      status = 'resolved';
    }

    const intervention: Intervention = {
      id: lead.id,
      lead_id: lead.id,
      lead_name: lead.nome || 'Lead sem nome',
      lead_phone: lead.telefone || lead.remotejid?.replace('@s.whatsapp.net', ''),
      agent_id: agent.id,
      agent_name: agent.name,
      reason: lead.paused_reason || 'human_requested',
      last_message: lastMessage,
      status,
      assigned_to: lead.responsavel,
      created_at: lead.created_at,
      updated_at: lead.updated_at,
      resolved_at: lead.resumed_at,
    };

    reply.send({
      status: 'success',
      data: intervention,
    });
  } catch (error) {
    console.error('[Interventions] Error:', error);
    reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

/**
 * GET /api/interventions/stats - Estatísticas de intervenções
 */
export async function getInterventionStatsHandler(
  request: FastifyRequest<{
    Querystring: { agent_id?: string };
  }>,
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
      .select('id, name, table_leads')
      .eq('user_id', userId)
      .not('table_leads', 'is', null);

    if (agent_id) {
      agentsQuery = agentsQuery.eq('id', agent_id);
    }

    const { data: agents, error: agentsError } = await agentsQuery;

    if (agentsError || !agents || agents.length === 0) {
      reply.send({
        status: 'success',
        data: {
          pending: 0,
          resolved_today: 0,
          avg_resolution_time: '0m',
          by_reason: {},
        },
      });
      return;
    }

    let totalPending = 0;
    let totalResolvedToday = 0;
    const resolutionTimes: number[] = [];
    const byReason: Record<string, number> = {};

    const todayStart = new Date();
    todayStart.setHours(0, 0, 0, 0);

    // Iterar pelos agentes
    for (const agent of agents) {
      if (!agent.table_leads) continue;

      try {
        // Contar pendentes
        const { count: pendingCount } = await supabaseAdmin
          .from(agent.table_leads)
          .select('*', { count: 'exact', head: true })
          .or('Atendimento_Finalizado.eq.true,current_state.eq.paused,responsavel.eq.Humano')
          .is('resumed_at', null);

        totalPending += pendingCount || 0;

        // Contar resolvidos hoje
        const { count: resolvedCount } = await supabaseAdmin
          .from(agent.table_leads)
          .select('*', { count: 'exact', head: true })
          .gte('resumed_at', todayStart.toISOString())
          .not('resumed_at', 'is', null);

        totalResolvedToday += resolvedCount || 0;

        // Buscar leads resolvidos para calcular tempo médio
        const { data: resolvedLeads } = await supabaseAdmin
          .from(agent.table_leads)
          .select('paused_at, resumed_at')
          .not('resumed_at', 'is', null)
          .not('paused_at', 'is', null)
          .limit(100);

        if (resolvedLeads) {
          for (const lead of resolvedLeads) {
            if (lead.paused_at && lead.resumed_at) {
              const pausedTime = new Date(lead.paused_at).getTime();
              const resumedTime = new Date(lead.resumed_at).getTime();
              const diffMinutes = (resumedTime - pausedTime) / 1000 / 60;
              resolutionTimes.push(diffMinutes);
            }
          }
        }

        // Contar por motivo
        const { data: leadsWithReason } = await supabaseAdmin
          .from(agent.table_leads)
          .select('paused_reason')
          .or('Atendimento_Finalizado.eq.true,current_state.eq.paused,responsavel.eq.Humano')
          .not('paused_reason', 'is', null);

        if (leadsWithReason) {
          for (const lead of leadsWithReason) {
            const reason = lead.paused_reason || 'human_requested';
            byReason[reason] = (byReason[reason] || 0) + 1;
          }
        }
      } catch (err) {
        console.error(`[Interventions] Error processing stats for agent ${agent.id}:`, err);
      }
    }

    // Calcular tempo médio de resolução
    let avgResolutionTime = '0m';
    if (resolutionTimes.length > 0) {
      const avgMinutes = resolutionTimes.reduce((a, b) => a + b, 0) / resolutionTimes.length;
      const hours = Math.floor(avgMinutes / 60);
      const minutes = Math.floor(avgMinutes % 60);
      if (hours > 0) {
        avgResolutionTime = `${hours}h ${minutes}m`;
      } else {
        avgResolutionTime = `${minutes}m`;
      }
    }

    reply.send({
      status: 'success',
      data: {
        pending: totalPending,
        resolved_today: totalResolvedToday,
        avg_resolution_time: avgResolutionTime,
        by_reason: byReason,
      },
    });
  } catch (error) {
    console.error('[Interventions] Error:', error);
    reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

/**
 * PUT /api/interventions/escalation-rules - Configurar regras de escalonamento
 */
export async function updateEscalationRulesHandler(
  request: FastifyRequest<{
    Body: {
      agent_id: string;
      auto_escalate_after_minutes?: number;
      notify_phone?: string;
      notify_email?: string;
      keywords?: string[];
    };
  }>,
  reply: FastifyReply
): Promise<void> {
  try {
    const userId = (request as any).user?.id;
    const { agent_id, auto_escalate_after_minutes, notify_phone, notify_email, keywords } = request.body;

    if (!userId) {
      reply.status(401).send({ status: 'error', message: 'Authentication required' });
      return;
    }

    if (!agent_id) {
      reply.status(400).send({ status: 'error', message: 'agent_id is required' });
      return;
    }

    // Verificar se agente pertence ao usuário
    const { data: agent, error: agentError } = await supabaseAdmin
      .from('agents')
      .select('id, handoff_triggers')
      .eq('id', agent_id)
      .eq('user_id', userId)
      .single();

    if (agentError || !agent) {
      reply.status(404).send({ status: 'error', message: 'Agent not found' });
      return;
    }

    // Montar regras de escalonamento
    const currentTriggers = agent.handoff_triggers || {};
    const escalationRules: EscalationRules = {
      auto_escalate_after_minutes,
      notify_phone,
      notify_email,
      keywords,
    };

    // Atualizar handoff_triggers
    const updatedTriggers = {
      ...currentTriggers,
      escalation_rules: escalationRules,
    };

    const { error: updateError } = await supabaseAdmin
      .from('agents')
      .update({
        handoff_triggers: updatedTriggers,
        updated_at: new Date().toISOString(),
      })
      .eq('id', agent_id);

    if (updateError) {
      console.error('[Interventions] Error updating escalation rules:', updateError);
      reply.status(500).send({ status: 'error', message: 'Failed to update escalation rules' });
      return;
    }

    // Registrar log de auditoria
    await supabaseAdmin.from('agent_audit_logs').insert({
      agent_id,
      action: 'escalation_rules_updated',
      action_category: 'settings',
      reasoning: `Escalation rules updated by user ${userId}`,
      success: true,
    });

    reply.send({
      status: 'success',
      data: {
        success: true,
      },
    });
  } catch (error) {
    console.error('[Interventions] Error:', error);
    reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}
