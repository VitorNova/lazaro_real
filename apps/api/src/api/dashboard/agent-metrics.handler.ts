import { FastifyRequest, FastifyReply } from 'fastify';
import { supabaseAdmin } from '../../services/supabase/client';
// REMOVIDO: Salvador deletado do projeto
// import { getFollowUpMetrics } from '../../services/salvador/follow-up-history.service';
const getFollowUpMetrics = async (_agentId: string, _days: number) => ({
  total: 0, responded: 0, rate: 0, avgTimeToRespond: 0,
  totalLeads: 0, leadsReengajados: 0, taxaReengajamento: 0, totalSent: 0,
  totalResponded: 0, responseRate: 0, avgResponseTimeMinutes: 0,
  byStep: [] as { step: number; rate: number; sent: number; responded: number }[]
});

// ============================================================================
// TYPES
// ============================================================================

interface AgentExpandedMetrics {
  agent_id: string;
  agent_type: string;
  metrics: Record<string, number | string | null>;
  selected_metrics: string[];
}

// Catálogo de métricas disponíveis para Agnes (SDR)
export const SDR_METRICS_CATALOG = [
  // Atendimento
  { id: 'leads_atendidos', label: 'Leads Atendidos', icon: '👥', category: 'Atendimento', description: 'Total de leads reais atendidos' },
  { id: 'agendamentos_ia', label: 'Agendamentos IA', icon: '📅', category: 'Atendimento', description: 'Agendamentos feitos pela IA' },
  // Agendamentos
  { id: 'confirmados', label: 'Confirmados', icon: '✔️', category: 'Agendamentos', description: 'Agendamentos confirmados' },
  { id: 'aguardando', label: 'Aguardando Confirmação', icon: '⏳', category: 'Agendamentos', description: 'Aguardando resposta do lead' },
  // Operacional
  { id: 'handoff_humano', label: 'Em Atend. Humano', icon: '🙋', category: 'Operacional', description: 'Leads transferidos para humano' },
];

// Catálogo de métricas disponíveis para Salvador (FOLLOWUP)
export const FOLLOWUP_METRICS_CATALOG = [
  // Reengajamento
  { id: 'leads_contactados', label: 'Leads Contactados', icon: '📨', category: 'Reengajamento', description: 'Total de leads que receberam follow-up' },
  { id: 'leads_reengajados', label: 'Leads Reengajados', icon: '🔄', category: 'Reengajamento', description: 'Leads que responderam pelo menos 1 follow-up' },
  { id: 'taxa_reengajamento', label: 'Taxa de Reengajamento', icon: '📈', category: 'Reengajamento', description: '% de leads que responderam' },
  { id: 'followups_enviados', label: 'Follow-ups Enviados', icon: '📤', category: 'Reengajamento', description: 'Total de mensagens de follow-up enviadas' },
  // Respostas
  { id: 'total_respondidos', label: 'Follow-ups Respondidos', icon: '💬', category: 'Respostas', description: 'Quantos follow-ups tiveram resposta do lead' },
  { id: 'taxa_resposta_msg', label: 'Taxa de Resposta/Msg', icon: '📊', category: 'Respostas', description: '% de follow-ups individuais respondidos' },
  { id: 'tempo_medio_resposta', label: 'Tempo Médio de Resposta', icon: '⏱️', category: 'Respostas', description: 'Tempo médio que o lead demora pra responder' },
  // Performance por Step
  { id: 'step1_taxa', label: 'Taxa Step 1', icon: '1️⃣', category: 'Performance por Step', description: 'Taxa de resposta do 1o follow-up' },
  { id: 'step2_taxa', label: 'Taxa Step 2', icon: '2️⃣', category: 'Performance por Step', description: 'Taxa de resposta do 2o follow-up' },
  { id: 'step3_taxa', label: 'Taxa Step 3', icon: '3️⃣', category: 'Performance por Step', description: 'Taxa de resposta do 3o follow-up' },
  { id: 'melhor_step', label: 'Melhor Follow-up', icon: '🏆', category: 'Performance por Step', description: 'Qual step tem a maior taxa de resposta' },
];

// Métricas padrão se o usuário nunca personalizou
const DEFAULT_SELECTED_METRICS = ['leads_atendidos', 'agendamentos_ia', 'confirmados', 'handoff_humano'];
const FOLLOWUP_DEFAULT_SELECTED_METRICS = ['leads_contactados', 'leads_reengajados', 'taxa_reengajamento', 'followups_enviados'];

// Filtro para excluir leads de teste
const TEST_LEAD_FILTER = `remotejid.not.like.test_%,remotejid.not.like.teste_%,remotejid.not.like.demo_%,remotejid.not.like.monitor_%`;

// ============================================================================
// GET EXPANDED METRICS FOR AN AGENT
// ============================================================================

export async function getAgentExpandedMetrics(
  request: FastifyRequest<{ Params: { agent_id: string } }>,
  reply: FastifyReply
) {
  try {
    const { agent_id } = request.params;
    const user_id = (request as any).user?.userId || (request as any).user?.id;

    if (!user_id) {
      return reply.status(401).send({ status: 'error', message: 'Authentication required' });
    }

    // Buscar o agente
    const { data: agent, error: agentError } = await supabaseAdmin
      .from('agents')
      .select('*')
      .eq('id', agent_id)
      .eq('user_id', user_id)
      .single();

    if (agentError || !agent) {
      return reply.status(404).send({ status: 'error', message: 'Agent not found' });
    }

    // Suporta métricas expandidas para SDR e FOLLOWUP
    if (agent.agent_type !== 'SDR' && agent.agent_type !== 'FOLLOWUP') {
      return reply.status(400).send({ status: 'error', message: 'Expanded metrics only available for SDR and FOLLOWUP agents' });
    }

    // ========================================================================
    // FOLLOWUP (Salvador) - usa getFollowUpMetrics()
    // ========================================================================
    if (agent.agent_type === 'FOLLOWUP') {
      const fm = await getFollowUpMetrics(agent_id, 30);

      // Encontrar melhor step
      const bestStep = fm.byStep.length > 0
        ? fm.byStep.reduce((best, s) => s.rate > best.rate ? s : best, fm.byStep[0])
        : null;

      // Encontrar taxa por step
      const findStepRate = (step: number): number => {
        const s = fm.byStep.find(s => s.step === step);
        return s ? s.rate : 0;
      };

      // Buscar preferência de métricas salva
      const { data: followupConfig } = await supabaseAdmin
        .from('agents')
        .select('dashboard_config')
        .eq('id', agent_id)
        .single();

      const followupDashboardConfig = followupConfig?.dashboard_config || {};
      const followupSelectedMetrics = followupDashboardConfig.selected_metrics || FOLLOWUP_DEFAULT_SELECTED_METRICS;

      const followupMetrics: AgentExpandedMetrics = {
        agent_id,
        agent_type: 'FOLLOWUP',
        metrics: {
          leads_contactados: fm.totalLeads,
          leads_reengajados: fm.leadsReengajados,
          taxa_reengajamento: fm.taxaReengajamento,
          followups_enviados: fm.totalSent,
          total_respondidos: fm.totalResponded,
          taxa_resposta_msg: fm.responseRate,
          tempo_medio_resposta: fm.avgResponseTimeMinutes,
          step1_taxa: findStepRate(1),
          step2_taxa: findStepRate(2),
          step3_taxa: findStepRate(3),
          melhor_step: bestStep ? `Step ${bestStep.step} (${bestStep.rate}%)` : '--',
        },
        selected_metrics: followupSelectedMetrics,
      };

      return reply.send({ status: 'success', data: followupMetrics });
    }

    // ========================================================================
    // SDR (Agnes) - queries existentes
    // ========================================================================
    const tableLeads = agent.table_leads;
    if (!tableLeads) {
      return reply.status(400).send({ status: 'error', message: 'Agent has no leads table configured' });
    }

    // Executar todas as queries em paralelo
    const [
      leadsAtendidosResult,
      agendamentosResult,
      confirmadosResult,
      aguardandoResult,
      handoffHumanoResult,
    ] = await Promise.all([
      // leads_atendidos - excluir leads de teste
      supabaseAdmin
        .from(tableLeads)
        .select('*', { count: 'exact', head: true })
        .not('remotejid', 'like', 'test_%')
        .not('remotejid', 'like', 'teste_%')
        .not('remotejid', 'like', 'demo_%')
        .not('remotejid', 'like', 'monitor_%'),

      // agendamentos_ia
      supabaseAdmin
        .from('schedules')
        .select('*', { count: 'exact', head: true })
        .eq('agent_id', agent_id),

      // confirmados
      supabaseAdmin
        .from('schedules')
        .select('*', { count: 'exact', head: true })
        .eq('agent_id', agent_id)
        .eq('status', 'confirmed'),

      // aguardando - schedules onde awaiting_confirmation = true
      supabaseAdmin
        .from('schedules')
        .select('*', { count: 'exact', head: true })
        .eq('agent_id', agent_id)
        .eq('awaiting_confirmation', true),

      // handoff_humano - leads com atendimento pausado (IA não responde)
      supabaseAdmin
        .from(tableLeads)
        .select('*', { count: 'exact', head: true })
        .eq('Atendimento_Finalizado', 'true')
        .not('remotejid', 'like', 'test_%')
        .not('remotejid', 'like', 'teste_%')
        .not('remotejid', 'like', 'demo_%')
        .not('remotejid', 'like', 'monitor_%'),
    ]);

    // Buscar preferência de métricas salva do usuário
    const { data: userConfig } = await supabaseAdmin
      .from('agents')
      .select('dashboard_config')
      .eq('id', agent_id)
      .single();

    const dashboardConfig = userConfig?.dashboard_config || {};
    const selectedMetrics = dashboardConfig.selected_metrics || DEFAULT_SELECTED_METRICS;

    const metrics: AgentExpandedMetrics = {
      agent_id,
      agent_type: 'SDR',
      metrics: {
        leads_atendidos: leadsAtendidosResult.count || 0,
        agendamentos_ia: agendamentosResult.count || 0,
        confirmados: confirmadosResult.count || 0,
        aguardando: aguardandoResult.count || 0,
        handoff_humano: handoffHumanoResult.count || 0,
      },
      selected_metrics: selectedMetrics,
    };

    return reply.send({ status: 'success', data: metrics });
  } catch (error) {
    console.error('[getAgentExpandedMetrics] Error:', error);
    return reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

// ============================================================================
// SAVE SELECTED METRICS PREFERENCE
// ============================================================================

export async function saveAgentDashboardConfig(
  request: FastifyRequest<{
    Params: { agent_id: string };
    Body: { selected_metrics: string[] };
  }>,
  reply: FastifyReply
) {
  try {
    const { agent_id } = request.params;
    const { selected_metrics } = request.body;
    const user_id = (request as any).user?.userId || (request as any).user?.id;

    if (!user_id) {
      return reply.status(401).send({ status: 'error', message: 'Authentication required' });
    }

    // Validar que são exatamente 4 métricas
    if (!selected_metrics || !Array.isArray(selected_metrics) || selected_metrics.length !== 4) {
      return reply.status(400).send({ status: 'error', message: 'Exactly 4 metrics must be selected' });
    }

    // Verificar se o agente pertence ao usuário
    const { data: agent, error: agentError } = await supabaseAdmin
      .from('agents')
      .select('id, agent_type, dashboard_config')
      .eq('id', agent_id)
      .eq('user_id', user_id)
      .single();

    if (agentError || !agent) {
      return reply.status(404).send({ status: 'error', message: 'Agent not found' });
    }

    // Validar que todas as métricas são válidas para o tipo do agente
    const catalog = agent.agent_type === 'FOLLOWUP' ? FOLLOWUP_METRICS_CATALOG : SDR_METRICS_CATALOG;
    const validMetricIds = catalog.map(m => m.id);
    const invalidMetrics = selected_metrics.filter(m => !validMetricIds.includes(m));
    if (invalidMetrics.length > 0) {
      return reply.status(400).send({ status: 'error', message: `Invalid metrics: ${invalidMetrics.join(', ')}` });
    }

    // Merge com config existente
    const currentConfig = agent.dashboard_config || {};
    const newConfig = {
      ...currentConfig,
      selected_metrics,
      updated_at: new Date().toISOString(),
    };

    // Salvar no banco
    const { error: updateError } = await supabaseAdmin
      .from('agents')
      .update({ dashboard_config: newConfig })
      .eq('id', agent_id);

    if (updateError) {
      console.error('[saveAgentDashboardConfig] Update error:', updateError);
      return reply.status(500).send({ status: 'error', message: 'Failed to save configuration' });
    }

    return reply.send({ status: 'success', message: 'Configuration saved', data: { selected_metrics } });
  } catch (error) {
    console.error('[saveAgentDashboardConfig] Error:', error);
    return reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

// ============================================================================
// GET METRICS CATALOG
// ============================================================================

export async function getMetricsCatalog(
  request: FastifyRequest<{ Params: { agent_type: string } }>,
  reply: FastifyReply
) {
  const { agent_type } = request.params;

  if (agent_type.toUpperCase() === 'SDR') {
    return reply.send({
      status: 'success',
      data: {
        catalog: SDR_METRICS_CATALOG,
        default_selected: DEFAULT_SELECTED_METRICS,
      },
    });
  }

  if (agent_type.toUpperCase() === 'FOLLOWUP') {
    return reply.send({
      status: 'success',
      data: {
        catalog: FOLLOWUP_METRICS_CATALOG,
        default_selected: FOLLOWUP_DEFAULT_SELECTED_METRICS,
      },
    });
  }

  return reply.status(400).send({ status: 'error', message: 'Metrics catalog not available for this agent type' });
}
