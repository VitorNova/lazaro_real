import { FastifyRequest, FastifyReply } from 'fastify';
import { supabaseAdmin } from '../../services/supabase/client';
import { removeFromHumanTakeoverCache, markAsHumanTakeover } from '../webhooks/human-takeover';

// ============================================================================
// TYPES
// ============================================================================

interface Lead {
  id: string;
  name: string;
  phone: string;
  stage: string;
  score: string;
  bant: {
    budget: boolean;
    authority: boolean;
    need: boolean;
    timeline: boolean;
  };
  agent_id: string;
  agent_name: string;
  created_at: string;
  last_message_at: string | null;
}

interface PipelineStage {
  slug: string;
  name: string;
  color: string;
  order: number;
  description_for_ai?: string;
}

interface AgentWithLeads {
  id: string;
  name: string;
  table_leads: string; // Nome da tabela de leads (para Supabase Realtime)
  pipeline_stages: PipelineStage[];
  leads: LeadSimple[];
  total_leads: number;
  uazapi_connected?: boolean;
  uses_shared_whatsapp?: boolean;
  parent_agent_id?: string | null;
}

interface LeadSimple {
  id: number;
  nome: string | null;
  telefone: string | null;
  email: string | null;
  empresa: string | null;
  remotejid: string | null;
  pipeline_step: string | null;
  resumo: string | null;
  Atendimento_Finalizado: string | null;
  responsavel: string | null;
  updated_date: string | null;
  lead_origin: string | null;
  ad_url: string | null;
  transfer_reason: string | null;
  handoff_at: string | null;
  current_state: string | null;
  // Observer insights (AI-extracted data from conversations)
  insights?: {
    summary?: string;
    sentiment?: 'positivo' | 'neutro' | 'negativo';
    suggested_stage?: string;
    auto_moved?: boolean;
    ad_urls?: string[];
    origin?: string;
    origin_reason?: string; // Motivo da classificação de origem
    speakers?: {
      lead?: string;
      human?: { name?: string; role?: string };
    };
  } | null;
}

// ============================================================================
// GET ALL LEADS
// ============================================================================

export async function getLeadsHandler(
  request: FastifyRequest<{ Querystring: { user_id?: string; agent_id?: string } }>,
  reply: FastifyReply
) {
  try {
    const { agent_id } = request.query;
    // Prioridade: 1) request.user do JWT middleware, 2) query param (legado)
    const user_id = (request as any).user?.id || request.query.user_id;

    if (!user_id) {
      return reply.status(400).send({ status: 'error', message: 'Authentication required' });
    }

    // Buscar agentes do usuario
    let agentsQuery = supabaseAdmin
      .from('agents')
      .select('id, name, table_leads, table_messages')
      .eq('user_id', user_id);

    if (agent_id) {
      agentsQuery = agentsQuery.eq('id', agent_id);
    }

    const { data: agents, error: agentsError } = await agentsQuery;

    if (agentsError) {
      console.error('[LeadsHandler] Error fetching agents:', agentsError);
      return reply.status(500).send({ status: 'error', message: 'Error fetching agents' });
    }

    if (!agents || agents.length === 0) {
      return reply.send({
        status: 'success',
        data: {
          leads: [],
          total: 0,
        },
      });
    }

    const allLeads: Lead[] = [];

    // Buscar leads de cada agente
    for (const agent of agents) {
      try {
        const { data: leadsData, error: leadsError } = await supabaseAdmin
          .from(agent.table_leads)
          .select('*')
          .order('created_date', { ascending: false })
          .limit(100);

        if (leadsError) {
          console.error(`[LeadsHandler] Error fetching leads from ${agent.table_leads}:`, leadsError);
          continue;
        }

        if (leadsData) {
          for (const lead of leadsData) {
            // Buscar ultima mensagem do lead
            let lastMessageAt = null;
            try {
              const { data: lastMsg } = await supabaseAdmin
                .from(agent.table_messages)
                .select('timestamp')
                .eq('sender', lead.phone_number)
                .order('timestamp', { ascending: false })
                .limit(1)
                .single();

              lastMessageAt = lastMsg?.timestamp || null;
            } catch {
              // Ignorar erro de mensagem
            }

            // Mapear campos para formato padrao
            allLeads.push({
              id: lead.id || lead.phone_number,
              name: lead.name || lead.lead_name || 'Sem nome',
              phone: lead.phone_number || '',
              stage: lead.pipeline_step || lead.status || 'Novo',
              score: calculateScore(lead),
              bant: {
                budget: lead.budget_qualified || lead.bant_budget || false,
                authority: lead.authority_qualified || lead.bant_authority || false,
                need: lead.need_qualified || lead.bant_need || false,
                timeline: lead.timeline_qualified || lead.bant_timeline || false,
              },
              agent_id: agent.id,
              agent_name: agent.name,
              created_at: lead.created_date || lead.created_at || new Date().toISOString(),
              last_message_at: lastMessageAt,
            });
          }
        }
      } catch (err) {
        console.error(`[LeadsHandler] Error processing agent ${agent.id}:`, err);
      }
    }

    // Ordenar por data de criacao
    allLeads.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

    return reply.send({
      status: 'success',
      data: {
        leads: allLeads,
        total: allLeads.length,
      },
    });
  } catch (error) {
    console.error('[LeadsHandler] Error:', error);
    return reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

// ============================================================================
// GET ALL AGENTS WITH LEADS (Para aba Leads - mostra todos os agents)
// ============================================================================

export async function getAgentsWithLeadsHandler(
  request: FastifyRequest<{ Querystring: { user_id?: string } }>,
  reply: FastifyReply
) {
  try {
    const user_id = (request as any).user?.id || request.query.user_id;

    if (!user_id) {
      return reply.status(400).send({ status: 'error', message: 'Authentication required' });
    }

    // Buscar todos os agentes do usuario com pipeline_stages e status de conexao
    // Não incluir agentes FOLLOWUP (Salvador) pois não capturam leads próprios
    const { data: agents, error: agentsError } = await supabaseAdmin
      .from('agents')
      .select('id, name, table_leads, table_messages, pipeline_stages, agent_type, type, avatar_url, uazapi_connected, uazapi_token, uazapi_base_url, uses_shared_whatsapp, parent_agent_id')
      .eq('user_id', user_id)
      .not('table_leads', 'is', null)
      .neq('agent_type', 'FOLLOWUP') // Filtrar Salvador (FOLLOWUP) do pipeline
      .order('created_at', { ascending: false });

    if (agentsError) {
      console.error('[LeadsHandler] Error fetching agents:', agentsError);
      return reply.status(500).send({ status: 'error', message: 'Error fetching agents' });
    }

    if (!agents || agents.length === 0) {
      return reply.send({
        status: 'success',
        data: {
          agents: [],
          total_agents: 0,
        },
      });
    }

    // Default pipeline stages
    const defaultPipelineStages: PipelineStage[] = [
      { slug: 'novo-lead', name: 'Novo Lead', color: 'gray', order: 1 },
      { slug: 'qualificado', name: 'Qualificado', color: 'blue', order: 2 },
      { slug: 'agendado', name: 'Agendado', color: 'amber', order: 3 },
      { slug: 'proposta', name: 'Proposta', color: 'violet', order: 4 },
      { slug: 'ganho', name: 'Ganho', color: 'green', order: 5 },
      { slug: 'perdido', name: 'Perdido', color: 'red', order: 6 },
    ];

    const agentsWithLeads: AgentWithLeads[] = [];

    // Buscar leads de cada agente em paralelo
    const leadsPromises = agents.map(async (agent) => {
      try {
        // Tentar primeiro com follow_count
        let leadsData: any[] | null = null;
        let leadsError: any = null;

        // Tratamento especial para agentes Diana (tabela diana_prospects tem estrutura diferente)
        if ((agent as any).type === 'diana') {
          const dianaFields = 'id, phone, company, contact_name, contact_role, status, segment, city, source, decisor_name, decisor_phone, is_blocked, is_paused, created_at, updated_at, insights';

          const dianaResult = await supabaseAdmin
            .from(agent.table_leads)
            .select(dianaFields)
            .eq('agent_id', agent.id)
            .order('updated_at', { ascending: false })
            .limit(200);

          if (!dianaResult.error && dianaResult.data) {
            // Mapear campos da Diana para o formato esperado pelo frontend
            leadsData = dianaResult.data.map((prospect: any) => ({
              id: prospect.id,
              nome: prospect.contact_name || prospect.decisor_name || prospect.company,
              telefone: prospect.phone,
              email: null,
              empresa: prospect.company,
              remotejid: prospect.phone ? `${prospect.phone}@s.whatsapp.net` : null,
              pipeline_step: prospect.status || 'prospect-novo',
              resumo: prospect.segment ? `${prospect.segment} - ${prospect.city || ''}` : null,
              Atendimento_Finalizado: prospect.is_blocked ? 'true' : 'false',
              responsavel: prospect.is_paused ? 'Pausado' : 'AI',
              updated_date: prospect.updated_at,
              lead_origin: prospect.source || 'diana',
              current_agent_id: agent.id,
              insights: prospect.insights || null, // Incluir insights se disponível
            }));
          } else {
            console.warn(`[LeadsHandler] Error fetching Diana prospects for agent ${agent.name}:`, dianaResult.error?.message);
            leadsData = [];
          }
        } else {
          // Lógica padrão para Agnes e outros agentes
          // Campos principais + campos de qualificação e follow-up + current_agent_id para filtragem multi-agente + handoff tracking
          const leadFields = 'id, nome, telefone, email, empresa, remotejid, pipeline_step, resumo, "Atendimento_Finalizado", responsavel, updated_date, lead_origin, ad_url, follow_count, follow_up_count, last_follow_up_at, captado_por, captado_em, qualification_score, lead_temperature, bant_budget, bant_authority, bant_need, bant_timing, current_agent_id, transfer_reason, handoff_at, current_state, insights';

          // Filtrar por current_agent_id para evitar leads duplicados quando múltiplos agentes compartilham a mesma tabela
          // Mostra leads que: pertencem a este agente OU não têm agente atribuído (compatibilidade com leads antigos)
          const result1 = await supabaseAdmin
            .from(agent.table_leads)
            .select(leadFields)
            .or(`current_agent_id.eq.${agent.id},current_agent_id.is.null`)
            .order('updated_date', { ascending: false })
            .limit(200);

          if (!result1.error) {
            leadsData = result1.data;
          } else if (result1.error.code === '42703') {
            // Algumas colunas não existem - tentar campos básicos sem colunas de follow-up avançadas mas com handoff tracking
            const result2 = await supabaseAdmin
              .from(agent.table_leads)
              .select('id, nome, telefone, email, empresa, remotejid, pipeline_step, resumo, "Atendimento_Finalizado", responsavel, updated_date, lead_origin, ad_url, current_agent_id, transfer_reason, handoff_at, current_state, insights')
              .or(`current_agent_id.eq.${agent.id},current_agent_id.is.null`)
              .order('updated_date', { ascending: false })
              .limit(200);

            if (!result2.error) {
              leadsData = result2.data;
            } else if (result2.error.code === '42703') {
              // Fallback final - campos mínimos sem current_agent_id
              const result3 = await supabaseAdmin
                .from(agent.table_leads)
                .select('id, nome, telefone, email, empresa, remotejid, pipeline_step, resumo, "Atendimento_Finalizado", responsavel, updated_date, lead_origin, insights')
                .order('updated_date', { ascending: false })
                .limit(200);

              leadsData = result3.data;
              leadsError = result3.error;
            } else {
              leadsError = result2.error;
            }
          } else {
            leadsError = result1.error;
          }

          if (leadsError) {
            console.warn(`[LeadsHandler] Error fetching leads for agent ${agent.name}:`, leadsError.message);
            return null;
          }
        }

        // Ordenar pipeline_stages por order
        const pipelineStages = agent.pipeline_stages?.length > 0
          ? (agent.pipeline_stages as PipelineStage[]).sort((a, b) => (a.order || 0) - (b.order || 0))
          : defaultPipelineStages;

        // Count leads where AI actually responded (Msg_model IS NOT NULL in messages table)
        let leadsAttendedByAi = 0;
        if ((agent as any).table_messages) {
          try {
            const { count } = await supabaseAdmin
              .from((agent as any).table_messages)
              .select('id', { count: 'exact', head: true })
              .not('Msg_model', 'is', null);
            leadsAttendedByAi = count || 0;
          } catch (e) {
            // Table might not exist yet
          }
        }

        // Adicionar campo ia_ativa em cada lead
        const leadsWithIaStatus = (leadsData || []).map((lead: LeadSimple) => ({
          ...lead,
          ia_ativa: lead.Atendimento_Finalizado !== 'true',
        }));

        return {
          id: agent.id,
          name: agent.name,
          table_leads: agent.table_leads, // Para Supabase Realtime
          agent_type: agent.agent_type,
          type: (agent as any).type,
          avatar_url: (agent as any).avatar_url,
          pipeline_stages: pipelineStages,
          leads: leadsWithIaStatus,
          total_leads: leadsData?.length || 0,
          leads_attended_by_ai: leadsAttendedByAi,
          // Campos de conexão UAZAPI
          uazapi_connected: (agent as any).uazapi_connected || false,
          uses_shared_whatsapp: (agent as any).uses_shared_whatsapp || false,
          parent_agent_id: (agent as any).parent_agent_id || null,
        };
      } catch (err) {
        console.error(`[LeadsHandler] Error processing agent ${agent.id}:`, err);
        return null;
      }
    });

    const results = await Promise.all(leadsPromises);

    // Filtrar resultados nulos e adicionar
    for (const result of results) {
      if (result) {
        agentsWithLeads.push(result);
      }
    }

    // Processar agentes com conexao compartilhada - herdar status do pai
    const agentsById: Record<string, AgentWithLeads> = {};
    agentsWithLeads.forEach((a) => {
      agentsById[a.id] = a;
    });

    agentsWithLeads.forEach((agent) => {
      if (agent.uses_shared_whatsapp && agent.parent_agent_id) {
        const parent = agentsById[agent.parent_agent_id];
        if (parent) {
          agent.uazapi_connected = parent.uazapi_connected;
        }
      }
    });

    return reply.send({
      status: 'success',
      data: {
        agents: agentsWithLeads,
        total_agents: agentsWithLeads.length,
        total_leads: agentsWithLeads.reduce((sum, a) => sum + a.total_leads, 0),
      },
    });
  } catch (error) {
    console.error('[LeadsHandler] Error:', error);
    return reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

// ============================================================================
// UPDATE LEAD PIPELINE STEP
// ============================================================================

export async function updateLeadPipelineHandler(
  request: FastifyRequest<{
    Params: { leadId: string };
    Body: { agent_id: string; pipeline_step: string };
  }>,
  reply: FastifyReply
) {
  try {
    const { leadId } = request.params;
    const { agent_id, pipeline_step } = request.body;
    const user_id = (request as any).user?.id;

    if (!user_id) {
      return reply.status(401).send({ status: 'error', message: 'Authentication required' });
    }

    // Buscar agente para verificar propriedade e obter table_leads
    const { data: agent, error: agentError } = await supabaseAdmin
      .from('agents')
      .select('id, table_leads')
      .eq('id', agent_id)
      .eq('user_id', user_id)
      .single();

    if (agentError || !agent) {
      return reply.status(404).send({ status: 'error', message: 'Agent not found' });
    }

    // Atualizar lead
    const { data: updatedLead, error: updateError } = await supabaseAdmin
      .from(agent.table_leads)
      .update({
        pipeline_step,
        updated_date: new Date().toISOString(),
      })
      .eq('id', leadId)
      .select()
      .single();

    if (updateError) {
      console.error('[LeadsHandler] Error updating lead:', updateError);
      return reply.status(500).send({ status: 'error', message: 'Error updating lead' });
    }

    return reply.send({
      status: 'success',
      data: updatedLead,
    });
  } catch (error) {
    console.error('[LeadsHandler] Error:', error);
    return reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

// ============================================================================
// TOGGLE LEAD AI STATUS
// ============================================================================

export async function toggleLeadAIHandler(
  request: FastifyRequest<{
    Params: { leadId: string };
    Body: { agent_id: string; enabled: boolean };
  }>,
  reply: FastifyReply
) {
  try {
    const { leadId } = request.params;
    const { agent_id, enabled } = request.body;
    const user_id = (request as any).user?.id;

    if (!user_id) {
      return reply.status(401).send({ status: 'error', message: 'Authentication required' });
    }

    // Buscar agente
    const { data: agent, error: agentError } = await supabaseAdmin
      .from('agents')
      .select('id, table_leads')
      .eq('id', agent_id)
      .eq('user_id', user_id)
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
        console.log('[LeadsHandler] Removed from human takeover cache', { leadId, remoteJid });
      } else {
        await markAsHumanTakeover(remoteJid, agent_id);
        console.log('[LeadsHandler] Added to human takeover cache', { leadId, remoteJid, agentId: agent_id });
      }
    }

    // Atualizar lead
    // Handoff tracking: registrar paused_at/paused_by ou resumed_at
    const now = new Date().toISOString();
    const updateData: Record<string, any> = {
      Atendimento_Finalizado: enabled ? 'false' : 'true',
      responsavel: enabled ? 'AI' : 'Humano',
      current_state: enabled ? 'ai' : 'paused', // Atualizar current_state junto com o toggle
      updated_date: now,
    };

    if (enabled) {
      // Reativando IA - registrar quando foi retomado
      updateData.resumed_at = now;
    } else {
      // Pausando IA - registrar quando e por quem foi pausado
      updateData.paused_at = now;
      updateData.paused_by = 'Dashboard';
    }

    const { data: updatedLead, error: updateError } = await supabaseAdmin
      .from(agent.table_leads)
      .update(updateData)
      .eq('id', leadId)
      .select()
      .single();

    if (updateError) {
      console.error('[LeadsHandler] Error toggling AI:', updateError);
      return reply.status(500).send({ status: 'error', message: 'Error updating lead' });
    }

    console.info(`[LeadsHandler] AI ${enabled ? 'enabled' : 'disabled'} for lead ${leadId} (database and cache synced)`);

    return reply.send({
      status: 'success',
      data: updatedLead,
      ai_enabled: enabled,
    });
  } catch (error) {
    console.error('[LeadsHandler] Error:', error);
    return reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

// ============================================================================
// UPDATE LEAD DETAILS (nome, telefone, resumo)
// ============================================================================

export async function updateLeadDetailsHandler(
  request: FastifyRequest<{
    Params: { leadId: string };
    Body: { agent_id: string; nome?: string; telefone?: string; resumo?: string };
  }>,
  reply: FastifyReply
) {
  try {
    const { leadId } = request.params;
    const { agent_id, nome, telefone, resumo } = request.body;
    const user_id = (request as any).user?.id;

    if (!user_id) {
      return reply.status(401).send({ status: 'error', message: 'Authentication required' });
    }

    if (!agent_id) {
      return reply.status(400).send({ status: 'error', message: 'agent_id is required' });
    }

    // Pelo menos um campo deve ser fornecido
    if (nome === undefined && telefone === undefined && resumo === undefined) {
      return reply.status(400).send({ status: 'error', message: 'At least one field (nome, telefone, resumo) is required' });
    }

    // Buscar agente para verificar propriedade e obter table_leads
    const { data: agent, error: agentError } = await supabaseAdmin
      .from('agents')
      .select('id, table_leads')
      .eq('id', agent_id)
      .eq('user_id', user_id)
      .single();

    if (agentError || !agent) {
      return reply.status(404).send({ status: 'error', message: 'Agent not found' });
    }

    // Montar objeto de atualização apenas com campos fornecidos
    const updateData: Record<string, any> = {
      updated_date: new Date().toISOString(),
    };

    if (nome !== undefined) {
      updateData.nome = nome;
    }
    if (telefone !== undefined) {
      updateData.telefone = telefone;
    }
    if (resumo !== undefined) {
      updateData.resumo = resumo;
    }

    // Atualizar lead
    const { data: updatedLead, error: updateError } = await supabaseAdmin
      .from(agent.table_leads)
      .update(updateData)
      .eq('id', leadId)
      .select()
      .single();

    if (updateError) {
      console.error('[LeadsHandler] Error updating lead details:', updateError);
      return reply.status(500).send({ status: 'error', message: 'Error updating lead' });
    }

    console.info(`[LeadsHandler] Lead ${leadId} updated successfully`, { nome, telefone, resumo: resumo?.substring(0, 50) });

    return reply.send({
      status: 'success',
      data: updatedLead,
    });
  } catch (error) {
    console.error('[LeadsHandler] Error:', error);
    return reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

// ============================================================================
// DELETE LEAD
// ============================================================================

export async function deleteLeadHandler(
  request: FastifyRequest<{
    Params: { leadId: string };
    Body: { agent_id: string };
  }>,
  reply: FastifyReply
) {
  try {
    const { leadId } = request.params;
    const { agent_id } = request.body;
    const user_id = (request as any).user?.id;

    if (!user_id) {
      return reply.status(401).send({ status: 'error', message: 'Authentication required' });
    }

    if (!agent_id) {
      return reply.status(400).send({ status: 'error', message: 'agent_id is required' });
    }

    // Buscar agente para verificar propriedade e obter table_leads
    const { data: agent, error: agentError } = await supabaseAdmin
      .from('agents')
      .select('id, table_leads')
      .eq('id', agent_id)
      .eq('user_id', user_id)
      .single();

    if (agentError || !agent) {
      return reply.status(404).send({ status: 'error', message: 'Agent not found' });
    }

    // Buscar o lead para obter o remotejid (para limpar cache se necessário)
    const { data: leadData } = await supabaseAdmin
      .from(agent.table_leads)
      .select('remotejid')
      .eq('id', leadId)
      .single();

    if (!leadData) {
      return reply.status(404).send({ status: 'error', message: 'Lead not found' });
    }

    // Remover do cache de human takeover se existir
    if (leadData.remotejid) {
      // Precisamos do agent_id para deletar do Redis
      const agent_id = leadData.agent_id;
      await removeFromHumanTakeoverCache(leadData.remotejid, agent_id);
      console.log('[LeadsHandler] Removed from human takeover cache', { leadId, remotejid: leadData.remotejid });
    }

    // CORREÇÃO: Deletar agendamentos associados ao lead (tabela schedules)
    // Isso evita que um novo lead herde dados de agendamentos antigos
    if (leadData.remotejid) {
      try {
        const { count: deletedSchedules } = await supabaseAdmin
          .from('schedules')
          .delete()
          .eq('remote_jid', leadData.remotejid);

        if (deletedSchedules && deletedSchedules > 0) {
          console.log('[LeadsHandler] Deleted orphan schedules', { leadId, remotejid: leadData.remotejid, count: deletedSchedules });
        }
      } catch (scheduleError) {
        console.warn('[LeadsHandler] Could not delete schedules (table may not exist)', { error: scheduleError });
      }
    }

    // Deletar o lead
    const { error: deleteError } = await supabaseAdmin
      .from(agent.table_leads)
      .delete()
      .eq('id', leadId);

    if (deleteError) {
      console.error('[LeadsHandler] Error deleting lead:', deleteError);
      return reply.status(500).send({ status: 'error', message: 'Error deleting lead' });
    }

    console.info(`[LeadsHandler] Lead ${leadId} deleted successfully`);

    return reply.send({
      status: 'success',
      message: 'Lead deleted successfully',
    });
  } catch (error) {
    console.error('[LeadsHandler] Error:', error);
    return reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

// ============================================================================
// GET LEAD FOLLOW-UP HISTORY
// ============================================================================

export async function getLeadFollowUpHistoryHandler(
  request: FastifyRequest<{
    Params: { remotejid: string };
    Querystring: { agent_id?: string };
  }>,
  reply: FastifyReply
) {
  try {
    const { remotejid } = request.params;
    const { agent_id } = request.query;
    const user_id = (request as any).user?.id;

    if (!user_id) {
      return reply.status(401).send({ status: 'error', message: 'Authentication required' });
    }

    if (!remotejid) {
      return reply.status(400).send({ status: 'error', message: 'remotejid is required' });
    }

    // Decodificar remotejid (pode vir URL encoded)
    const decodedRemotejid = decodeURIComponent(remotejid);

    // Buscar histórico de follow-ups da tabela follow_up_history
    let query = supabaseAdmin
      .from('follow_up_history')
      .select('id, step_number, sent_at, message_sent, lead_responded, responded_at, response_time_minutes, personality, follow_up_type')
      .eq('remotejid', decodedRemotejid)
      .order('sent_at', { ascending: false });

    if (agent_id) {
      query = query.eq('agent_id', agent_id);
    }

    const { data: followUps, error } = await query;

    if (error) {
      console.error('[LeadsHandler] Error fetching follow-up history:', error);
      return reply.status(500).send({ status: 'error', message: 'Error fetching follow-up history' });
    }

    return reply.send({
      status: 'success',
      data: {
        remotejid: decodedRemotejid,
        totalFollowUps: followUps?.length || 0,
        followUps: (followUps || []).map(f => ({
          id: f.id,
          stepNumber: f.step_number,
          sentAt: f.sent_at,
          message: f.message_sent,
          responded: f.lead_responded,
          respondedAt: f.responded_at,
          responseTimeMinutes: f.response_time_minutes,
          type: f.follow_up_type,
        })),
      },
    });
  } catch (error) {
    console.error('[LeadsHandler] Error:', error);
    return reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

function calculateScore(lead: any): string {
  const bantCount = [
    lead.budget_qualified || lead.bant_budget,
    lead.authority_qualified || lead.bant_authority,
    lead.need_qualified || lead.bant_need,
    lead.timeline_qualified || lead.bant_timeline,
  ].filter(Boolean).length;

  if (bantCount >= 3) return 'Hot';
  if (bantCount >= 2) return 'Warm';
  return 'Cold';
}
