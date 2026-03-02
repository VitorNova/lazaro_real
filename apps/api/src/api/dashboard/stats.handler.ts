import { FastifyRequest, FastifyReply } from 'fastify';
import { supabaseAdmin } from '../../services/supabase/client';
import { Agent } from '../../services/supabase/types';
// REMOVIDO: Salvador deletado do projeto
// import { getFollowUpMetrics } from '../../services/salvador/follow-up-history.service';
const getFollowUpMetrics = async (_agentId: string, _days: number) => ({
  total: 0, responded: 0, rate: 0, avgTimeToRespond: 0,
  totalLeads: 0, leadsReengajados: 0, taxaReengajamento: 0, totalSent: 0,
  totalResponded: 0, responseRate: 0, avgResponseTimeMinutes: 0,
  byStep: [] as { step: number; rate: number; sent: number; responded: number }[]
});
import { getInitializedRedisCacheModule } from '../../core/modules/redis-cache/redis-cache.module';
import { resolveAgentNameSync } from '../../utils/resolvers';

// ============================================================================
// TYPES
// ============================================================================

interface DashboardStats {
  // Metricas principais
  totalLeads: number;
  totalLeadsChange: string;
  // Metricas secundarias
  conversionRate: number;
  conversionRateChange: string;
  schedulesTotal: number;
  schedulesTotalChange: string;
  leadsOutsideHours: number;
  leadsOutsideHoursChange: string;
  // Metricas financeiras (Asaas)
  recoveredAmount: number;
  recoveredAmountChange: string;
  pendingAmount: number;
  overdueAmount: number;
  // Metricas de follow-up (Salvador)
  followUpsSent: number;
  followUpResponseRate: number;
  leadsReengaged: number;
  // Metricas operacionais
  handoffsTotal: number;
  leadsInAI: number;
  // Funil detalhado
  pipelineFunnel: Array<{ etapa: string; quantidade: number; percentual: number }>;
  // Dados visuais
  leadsByTemperature: { hot: number; warm: number; cold: number };
  leadsOverTime: Array<{ name: string; leads: number }>;
  leadSources: Array<{ name: string; value: number; color: string }>;
  agentsPerformance: AgentPerformance[];
  // Periodo selecionado
  period: 'day' | 'week' | 'month' | 'total';
}

interface FollowUpStepMetric {
  follow: number;
  enviados: number;
  respondidos: number;
  taxa: string;
}

interface AgentPerformance {
  id: string;
  name: string;
  type: string;
  color: string;
  status: 'online' | 'offline';
  metrics: Record<string, string | number | FollowUpStepMetric[]>;
  pipelineCards: Array<{ etapa: string; quantidade: number }>;
  lastActivity: string;
}

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

function getColorForAgent(agentType: string): string {
  switch (agentType?.toLowerCase()) {
    case 'agnes':
    case 'sdr':
      return 'violet';
    case 'salvador':
    case 'followup':
      return 'amber';
    case 'diana':
      return 'blue';
    default:
      return 'gray';
  }
}

function formatTimeAgo(date: Date | string | null): string {
  if (!date) return 'Nunca';

  const now = new Date();
  const then = new Date(date);
  const diffMs = now.getTime() - then.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return 'Agora';
  if (diffMins < 60) return `Ha ${diffMins} minutos`;
  if (diffHours < 24) return `Ha ${diffHours} horas`;
  return `Ha ${diffDays} dias`;
}

function calculateChange(current: number, previous: number): string {
  if (previous === 0) return current > 0 ? '+100%' : '0%';
  const change = ((current - previous) / previous) * 100;
  const sign = change >= 0 ? '+' : '';
  return `${sign}${change.toFixed(1)}%`;
}

/**
 * Retorna hora e dia da semana no timezone especificado
 * @param date - Data a ser convertida
 * @param timezone - Timezone do agente (ex: 'America/Sao_Paulo')
 * @returns { hour: number, dayOfWeek: number }
 */
function getTimeInTimezone(date: Date, timezone?: string): { hour: number; dayOfWeek: number } {
  const tz = timezone || 'America/Sao_Paulo'; // Default para horário de Brasília

  try {
    // Usar Intl.DateTimeFormat para obter hora e dia no timezone correto
    const formatter = new Intl.DateTimeFormat('en-US', {
      timeZone: tz,
      hour: 'numeric',
      hour12: false,
      weekday: 'short',
    });

    const parts = formatter.formatToParts(date);
    const hourPart = parts.find(p => p.type === 'hour');
    const dayPart = parts.find(p => p.type === 'weekday');

    const hour = hourPart ? parseInt(hourPart.value) : date.getHours();

    // Converter weekday para número (0=domingo, 6=sábado)
    const dayMap: Record<string, number> = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
    const dayOfWeek = dayPart ? (dayMap[dayPart.value] ?? date.getDay()) : date.getDay();

    return { hour, dayOfWeek };
  } catch {
    // Fallback para horário local do servidor se timezone inválido
    return { hour: date.getHours(), dayOfWeek: date.getDay() };
  }
}

// ============================================================================
// MAIN HANDLER
// ============================================================================

export async function getDashboardStats(
  request: FastifyRequest<{ Querystring: { user_id?: string; period?: 'day' | 'week' | 'month' | 'total' } }>,
  reply: FastifyReply
) {
  try {
    // Prioridade: 1) request.user do JWT middleware, 2) query param (legado)
    // NOTA: authMiddleware em agents/index.ts transforma { userId } -> { id } para compatibilidade
    const user_id = (request as any).user?.id || request.query.user_id;
    const period = request.query.period || 'week'; // default: semana

    if (!user_id) {
      return reply.status(400).send({ status: 'error', message: 'Authentication required' });
    }

    // ========================================================================
    // CACHE: Verificar se já existe no Redis
    // ========================================================================
    const cache = await getInitializedRedisCacheModule();
    const cacheKey = `dashboard:stats:${user_id}:${period}`;

    try {
      const cached = await cache.getJson<DashboardStats>(cacheKey);
      if (cached) {
        console.log('[DashboardStats] Cache HIT:', cacheKey);
        return reply.send({ status: 'success', data: cached });
      }
      console.log('[DashboardStats] Cache MISS:', cacheKey);
    } catch (cacheError) {
      console.warn('[DashboardStats] Cache read error:', cacheError);
      // Continue without cache
    }

    // Buscar todos os agentes do usuario
    const { data: agents, error: agentsError } = await supabaseAdmin
      .from('agents')
      .select('*')
      .eq('user_id', user_id);

    if (agentsError) {
      console.error('[DashboardStats] Error fetching agents:', agentsError);
      return reply.status(500).send({ status: 'error', message: 'Error fetching agents' });
    }

    if (!agents || agents.length === 0) {
      // Retornar dados vazios se nao houver agentes
      return reply.send({
        status: 'success',
        data: {
          totalLeads: 0,
          totalLeadsChange: '0%',
          conversionRate: 0,
          conversionRateChange: '0%',
          schedulesTotal: 0,
          schedulesTotalChange: '0%',
          leadsOutsideHours: 0,
          leadsOutsideHoursChange: '0%',
          leadsByTemperature: { hot: 0, warm: 0, cold: 0 },
          leadsOverTime: [],
          leadSources: [],
          agentsPerformance: [],
        },
      });
    }

    // Data atual e periodos baseados no filtro
    const now = new Date();
    const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const yesterdayStart = new Date(todayStart.getTime() - 86400000);
    const thisMonthStart = new Date(now.getFullYear(), now.getMonth(), 1);
    const lastMonthStart = new Date(now.getFullYear(), now.getMonth() - 1, 1);

    // Calcular datas da semana
    const weekStart = new Date(todayStart);
    weekStart.setDate(weekStart.getDate() - weekStart.getDay());
    const lastWeekStart = new Date(weekStart.getTime() - 7 * 86400000);

    // Definir periodo baseado no filtro
    let periodStart: Date;
    let previousPeriodStart: Date;
    let previousPeriodEnd: Date;

    switch (period) {
      case 'day':
        periodStart = todayStart;
        previousPeriodStart = yesterdayStart;
        previousPeriodEnd = todayStart;
        break;
      case 'month':
        periodStart = thisMonthStart;
        previousPeriodStart = lastMonthStart;
        previousPeriodEnd = thisMonthStart;
        break;
      case 'total':
        // Total: desde o início (sem comparação de período anterior)
        periodStart = new Date('2020-01-01');
        previousPeriodStart = new Date('2019-01-01');
        previousPeriodEnd = new Date('2020-01-01');
        break;
      case 'week':
      default:
        periodStart = weekStart;
        previousPeriodStart = lastWeekStart;
        previousPeriodEnd = weekStart;
        break;
    }

    // Variaveis de contagem
    let totalLeads = 0;
    let totalLeadsPrevious = 0;
    let leadsConverted = 0;
    let leadsOutsideHours = 0;
    let leadsOutsideHoursPrevious = 0;
    let schedulesTotal = 0;
    let schedulesPrevious = 0;
    let leadsByTemperature = { hot: 0, warm: 0, cold: 0 };
    const leadsOverTimeMap: Record<string, number> = {};
    const leadSourcesMap: Record<string, number> = {};
    const agentsPerformance: AgentPerformance[] = [];

    // Track processed tables to avoid counting duplicates
    // (multiple agents may share the same leads/messages table)
    const processedLeadsTables = new Set<string>();

    // ========================================================================
    // OTIMIZAÇÃO: Processar todos os agentes em paralelo
    // ========================================================================

    // Primeiro, identificar quais tabelas precisam ser processadas
    const uniqueLeadsTables: { table: string; agent: Agent }[] = [];
    const agentsMap = new Map<string, Agent>();

    for (const agent of agents as Agent[]) {
      agentsMap.set(agent.id, agent);
      const tableLeads = agent.table_leads;
      if (tableLeads && !processedLeadsTables.has(tableLeads)) {
        processedLeadsTables.add(tableLeads);
        uniqueLeadsTables.push({ table: tableLeads, agent });
      }
    }

    // OTIMIZAÇÃO: Executar todas as queries de leads em paralelo
    const leadsPromises = uniqueLeadsTables.map(async ({ table: tableLeads, agent }) => {
      // Horário comercial CONFIGURÁVEL por agente (default: 8h-17h)
      // Campos: commercial_start_hour e commercial_end_hour na tabela agents
      // Nota: business_hours do agente é o horário de funcionamento do bot, não o horário comercial
      const startHour = agent.commercial_start_hour ?? 8;
      const endHour = agent.commercial_end_hour ?? 17;

      // Executar queries em paralelo para esta tabela
      const [
        leadsCountResult,
        leadsPrevResult,
        leadsWithTimeResult,
        leadsPrevTimeResult,
        convertedResult,
        tempDataResult,
        leadsDataResult,
        pipelineDataResult,
      ] = await Promise.all([
        // Count leads do periodo (excluindo leads de teste)
        supabaseAdmin
          .from(tableLeads)
          .select('*', { count: 'exact', head: true })
          .gte('created_date', periodStart.toISOString())
          .not('remotejid', 'like', 'test_%')
          .not('remotejid', 'like', 'teste_%')
          .not('remotejid', 'like', 'demo_%')
          .not('remotejid', 'like', 'monitor_%'),

        // Count leads periodo anterior (excluindo leads de teste)
        supabaseAdmin
          .from(tableLeads)
          .select('*', { count: 'exact', head: true })
          .gte('created_date', previousPeriodStart.toISOString())
          .lt('created_date', previousPeriodEnd.toISOString())
          .not('remotejid', 'like', 'test_%')
          .not('remotejid', 'like', 'teste_%')
          .not('remotejid', 'like', 'demo_%')
          .not('remotejid', 'like', 'monitor_%'),

        // Leads com horario (periodo atual)
        supabaseAdmin
          .from(tableLeads)
          .select('created_date')
          .gte('created_date', periodStart.toISOString()),

        // Leads com horario (periodo anterior)
        supabaseAdmin
          .from(tableLeads)
          .select('created_date')
          .gte('created_date', previousPeriodStart.toISOString())
          .lt('created_date', previousPeriodEnd.toISOString()),

        // Leads convertidos (por pipeline_step, excluindo teste)
        supabaseAdmin
          .from(tableLeads)
          .select('*', { count: 'exact', head: true })
          .or('pipeline_step.ilike.%ganho%,pipeline_step.ilike.%fechado%,pipeline_step.ilike.%convertido%,pipeline_step.ilike.%converted%,pipeline_step.ilike.%cliente%')
          .not('remotejid', 'like', 'test_%')
          .not('remotejid', 'like', 'teste_%')
          .not('remotejid', 'like', 'demo_%')
          .not('remotejid', 'like', 'monitor_%'),

        // Temperatura dos leads
        supabaseAdmin
          .from(tableLeads)
          .select('lead_temperature'),

        // Dados para origem e timeline (limitado)
        supabaseAdmin
          .from(tableLeads)
          .select('created_date, lead_origin')
          .order('created_date', { ascending: false })
          .limit(1000),

        // Dados do pipeline
        supabaseAdmin
          .from(tableLeads)
          .select('pipeline_step'),
      ]);

      // Processar resultados
      const leadsCount = leadsCountResult.count || 0;
      const leadsPrev = leadsPrevResult.count || 0;
      const converted = convertedResult.count || 0;

      // Calcular leads fora do horario comercial (usando timezone do agente)
      const agentTimezone = agent.timezone || 'America/Sao_Paulo';
      let outsideHours = 0;
      let outsideHoursPrev = 0;

      if (leadsWithTimeResult.data) {
        for (const lead of leadsWithTimeResult.data) {
          if (lead.created_date) {
            const leadDate = new Date(lead.created_date);
            const { hour, dayOfWeek } = getTimeInTimezone(leadDate, agentTimezone);
            if (hour < startHour || hour >= endHour || dayOfWeek === 0 || dayOfWeek === 6) {
              outsideHours++;
            }
          }
        }
      }

      if (leadsPrevTimeResult.data) {
        for (const lead of leadsPrevTimeResult.data) {
          if (lead.created_date) {
            const leadDate = new Date(lead.created_date);
            const { hour, dayOfWeek } = getTimeInTimezone(leadDate, agentTimezone);
            if (hour < startHour || hour >= endHour || dayOfWeek === 0 || dayOfWeek === 6) {
              outsideHoursPrev++;
            }
          }
        }
      }

      // Temperatura
      const tempCounts = { hot: 0, warm: 0, cold: 0 };
      if (tempDataResult.data) {
        for (const lead of tempDataResult.data) {
          const temp = (lead.lead_temperature || 'cold').toLowerCase();
          if (temp === 'hot' || temp === 'quente') tempCounts.hot++;
          else if (temp === 'warm' || temp === 'morno') tempCounts.warm++;
          else tempCounts.cold++;
        }
      }

      // Timeline e origem
      const timelineMap: Record<string, number> = {};
      const sourcesMap: Record<string, number> = {};
      if (leadsDataResult.data) {
        for (const lead of leadsDataResult.data) {
          if (lead.created_date) {
            const leadDate = new Date(lead.created_date);
            const monthKey = leadDate.toLocaleString('pt-BR', { month: 'short' }).replace('.', '');
            const monthKeyCapitalized = monthKey.charAt(0).toUpperCase() + monthKey.slice(1);
            timelineMap[monthKeyCapitalized] = (timelineMap[monthKeyCapitalized] || 0) + 1;
          }
          // Normalizar origem: null, 'null' (string), vazio → 'whatsapp'
          let origin = lead.lead_origin;
          if (!origin || origin === 'null') {
            origin = 'whatsapp';
          }
          sourcesMap[origin] = (sourcesMap[origin] || 0) + 1;
        }
      }

      // Pipeline
      const pipelineCounts: Record<string, number> = {};
      if (pipelineDataResult.data) {
        for (const lead of pipelineDataResult.data) {
          const step = lead.pipeline_step || 'Novo';
          pipelineCounts[step] = (pipelineCounts[step] || 0) + 1;
        }
      }

      return {
        tableLeads,
        agentId: agent.id,
        leadsCount,
        leadsPrev,
        converted,
        outsideHours,
        outsideHoursPrev,
        tempCounts,
        timelineMap,
        sourcesMap,
        pipelineCounts,
      };
    });

    // Executar queries de agentes em paralelo
    const agentMetricsPromises = (agents as Agent[]).map(async (agent) => {
      const tableMessages = agent.table_messages;
      const isOnline = (agent as any).active === true;

      let lastActivity: string | null = null;
      let mensagensCount = 0;

      // Buscar última mensagem e contagem (cada agente precisa do seu próprio lastActivity)
      if (tableMessages) {
        const [lastMsgResult, msgCountResult] = await Promise.all([
          // Última mensagem
          supabaseAdmin
            .from(tableMessages)
            .select('creat')
            .order('creat', { ascending: false })
            .limit(1)
            .single(),

          // OTIMIZAÇÃO: Contar mensagens pela quantidade de registros (cada registro = 1 conversa)
          // Ao invés de buscar todo o JSONB, estimamos baseado no número de conversas
          supabaseAdmin
            .from(tableMessages)
            .select('*', { count: 'exact', head: true }),
        ]);

        lastActivity = lastMsgResult.data?.creat || null;
        // Usar contagem real de conversas (cada registro = 1 conversa)
        mensagensCount = msgCountResult.count || 0;
      }

      // Métricas específicas por tipo de agente (em paralelo)
      let sdrMetrics = null;
      let followupMetrics = null;
      let dianaMetrics = null;

      if (agent.agent_type === 'SDR' && agent.table_leads) {
        const [schedulesResult, qualificadosResult] = await Promise.all([
          // Agendamentos criados pela IA
          supabaseAdmin
            .from('schedules')
            .select('*', { count: 'exact', head: true })
            .eq('agent_id', agent.id),

          // Leads qualificados
          supabaseAdmin
            .from(agent.table_leads)
            .select('*', { count: 'exact', head: true })
            .eq('pipeline_step', 'qualificado'),
        ]);

        sdrMetrics = {
          agendamentosIA: schedulesResult.count || 0,
          qualificadosCount: qualificadosResult.count || 0,
        };
      } else if (agent.agent_type === 'FOLLOWUP') {
        // Buscar métricas de follow-up da tabela follow_up_history
        followupMetrics = await getFollowUpMetrics(agent.id, 30);
      } else if (agent.agent_type === 'DIANA' && agent.table_leads) {
        // Buscar métricas de prospecção Diana
        const [
          totalProspectsResult,
          decisoresResult,
          emQualificacaoResult,
          transferidosResult,
        ] = await Promise.all([
          // Total de prospects contactados (diana_agent >= 1)
          supabaseAdmin
            .from(agent.table_leads)
            .select('*', { count: 'exact', head: true })
            .gte('diana_agent', 1),

          // Decisores encontrados
          supabaseAdmin
            .from(agent.table_leads)
            .select('*', { count: 'exact', head: true })
            .eq('decisor', true),

          // Em qualificação (diana_agent = 2)
          supabaseAdmin
            .from(agent.table_leads)
            .select('*', { count: 'exact', head: true })
            .eq('diana_agent', 2),

          // Transferidos para Agnes
          supabaseAdmin
            .from(agent.table_leads)
            .select('*', { count: 'exact', head: true })
            .eq('transferred', true),
        ]);

        const totalProspects = totalProspectsResult.count || 0;
        const decisores = decisoresResult.count || 0;
        const emQualificacao = emQualificacaoResult.count || 0;
        const transferidos = transferidosResult.count || 0;

        dianaMetrics = {
          prospectsContactados: totalProspects,
          decisoresEncontrados: decisores,
          taxaColeta: totalProspects > 0 ? Math.round((decisores / totalProspects) * 100) : 0,
          emQualificacao,
          transferidos,
          taxaConversao: decisores > 0 ? Math.round((transferidos / decisores) * 100) : 0,
        };
      }

      return {
        agentId: agent.id,
        agent,
        isOnline,
        lastActivity,
        mensagensCount,
        sdrMetrics,
        followupMetrics,
        dianaMetrics,
      };
    });

    // Aguardar todas as queries em paralelo
    const [leadsResults, agentMetricsResults] = await Promise.all([
      Promise.all(leadsPromises),
      Promise.all(agentMetricsPromises),
    ]);

    // Consolidar resultados de leads
    const leadsDataByTable = new Map(leadsResults.map(r => [r.tableLeads, r]));

    for (const result of leadsResults) {
      totalLeads += result.leadsCount;
      totalLeadsPrevious += result.leadsPrev;
      leadsConverted += result.converted;
      leadsOutsideHours += result.outsideHours;
      leadsOutsideHoursPrevious += result.outsideHoursPrev;

      // Temperatura
      leadsByTemperature.hot += result.tempCounts.hot;
      leadsByTemperature.warm += result.tempCounts.warm;
      leadsByTemperature.cold += result.tempCounts.cold;

      // Timeline
      for (const [month, count] of Object.entries(result.timelineMap)) {
        leadsOverTimeMap[month] = (leadsOverTimeMap[month] || 0) + count;
      }

      // Origens
      for (const [source, count] of Object.entries(result.sourcesMap)) {
        leadSourcesMap[source] = (leadSourcesMap[source] || 0) + count;
      }
    }

    // Construir agentsPerformance
    for (const metrics of agentMetricsResults) {
      const agent = metrics.agent;
      const tableLeads = agent.table_leads;
      const leadsData = tableLeads ? leadsDataByTable.get(tableLeads) : null;

      const agentLeadsCount = leadsData?.leadsCount || 0;
      const pipelineCounts = leadsData?.pipelineCounts || {};

      let agentMetrics: Record<string, string | number | FollowUpStepMetric[]>;

      if (agent.agent_type === 'FOLLOWUP' && metrics.followupMetrics) {
        // Métricas específicas para Salvador (FOLLOWUP)
        const fm = metrics.followupMetrics;
        agentMetrics = {
          // Métricas de LEADS únicos (principais)
          leadsContactados: fm.totalLeads,
          leadsReengajados: fm.leadsReengajados,
          taxaReengajamento: `${fm.taxaReengajamento}%`,
          // Métricas de follow-ups enviados
          followUpsEnviados: fm.totalSent,
          // Detalhamento por número do follow-up
          respostasPorFollow: fm.byStep.map(s => ({
            follow: s.step,
            enviados: s.sent,
            respondidos: s.responded,
            taxa: `${s.rate}%`,
          })),
        };
      } else if (agent.agent_type === 'DIANA' && metrics.dianaMetrics) {
        // Métricas específicas para Diana (prospecção)
        const dm = metrics.dianaMetrics;
        agentMetrics = {
          prospectsContactados: dm.prospectsContactados,
          decisoresEncontrados: dm.decisoresEncontrados,
          taxaColeta: `${dm.taxaColeta}%`,
          emQualificacao: dm.emQualificacao,
          transferidos: dm.transferidos,
          taxaConversao: `${dm.taxaConversao}%`,
        };
      } else {
        // Métricas para Agnes (SDR) e outros
        agentMetrics = {
          leadsAtendidos: agentLeadsCount,
          mensagensEnviadas: metrics.mensagensCount,
          agendamentosIA: metrics.sdrMetrics?.agendamentosIA || 0,
        };
      }

      agentsPerformance.push({
        id: agent.id,
        name: agent.name,
        type: agent.agent_type || 'SDR',
        color: getColorForAgent(agent.agent_type || agent.name),
        status: metrics.isOnline ? 'online' : 'offline',
        metrics: agentMetrics,
        pipelineCards: Object.entries(pipelineCounts).map(([etapa, quantidade]) => ({
          etapa,
          quantidade,
        })),
        lastActivity: formatTimeAgo(metrics.lastActivity),
      });
    }

    // Buscar agendamentos CRIADOS no periodo (usa created_at, não scheduled_at)
    // Isso mostra quantos agendamentos a IA fez no período, independente de quando a reunião será
    const agentIds = agents.map((a: Agent) => a.id);

    // Agendamentos CRIADOS no periodo selecionado
    const { count: schPeriod } = await supabaseAdmin
      .from('schedules')
      .select('*', { count: 'exact', head: true })
      .in('agent_id', agentIds)
      .gte('created_at', periodStart.toISOString());
    schedulesTotal = schPeriod || 0;

    // Agendamentos CRIADOS no periodo anterior
    const { count: schPrev } = await supabaseAdmin
      .from('schedules')
      .select('*', { count: 'exact', head: true })
      .in('agent_id', agentIds)
      .gte('created_at', previousPeriodStart.toISOString())
      .lt('created_at', previousPeriodEnd.toISOString());
    schedulesPrevious = schPrev || 0;

    // ========================================================================
    // MÉTRICAS FINANCEIRAS (ASAAS)
    // ========================================================================
    let recoveredAmount = 0;
    let recoveredAmountPrevious = 0;
    let pendingAmount = 0;
    let overdueAmount = 0;

    // Buscar cobranças do Asaas para os agentes do usuário
    const { data: asaasData } = await supabaseAdmin
      .from('asaas_cobrancas')
      .select('value, status, payment_date, due_date')
      .in('agent_id', agentIds)
      .is('deleted_at', null);

    if (asaasData) {
      for (const cobranca of asaasData) {
        const value = Number(cobranca.value) || 0;
        if (cobranca.status === 'RECEIVED' || cobranca.status === 'CONFIRMED') {
          // Verificar se foi pago no período atual
          if (cobranca.payment_date) {
            const paymentDate = new Date(cobranca.payment_date);
            if (paymentDate >= periodStart) {
              recoveredAmount += value;
            } else if (paymentDate >= previousPeriodStart && paymentDate < previousPeriodEnd) {
              recoveredAmountPrevious += value;
            }
          }
        } else if (cobranca.status === 'PENDING') {
          pendingAmount += value;
        } else if (cobranca.status === 'OVERDUE') {
          overdueAmount += value;
        }
      }
    }

    // ========================================================================
    // MÉTRICAS DE FOLLOW-UP (SALVADOR)
    // ========================================================================
    let followUpsSent = 0;
    let followUpResponded = 0;
    let leadsReengaged = 0;

    // Buscar follow-ups enviados no período
    const { data: followUpData } = await supabaseAdmin
      .from('follow_up_history')
      .select('lead_responded, converted')
      .in('agent_id', agentIds)
      .gte('sent_at', periodStart.toISOString());

    if (followUpData) {
      followUpsSent = followUpData.length;
      followUpResponded = followUpData.filter(f => f.lead_responded).length;
      leadsReengaged = followUpData.filter(f => f.converted).length;
    }

    const followUpResponseRate = followUpsSent > 0 ? Math.round((followUpResponded / followUpsSent) * 100) : 0;

    // ========================================================================
    // MÉTRICAS OPERACIONAIS
    // ========================================================================
    let handoffsTotal = 0;
    let leadsInAI = 0;
    const pipelineFunnelMap: Record<string, number> = {};

    // Buscar métricas operacionais de cada tabela de leads
    for (const result of leadsResults) {
      // Pipeline funnel já foi calculado
      for (const [etapa, qtd] of Object.entries(result.pipelineCounts)) {
        pipelineFunnelMap[etapa] = (pipelineFunnelMap[etapa] || 0) + qtd;
      }
    }

    // Buscar handoffs e leads em AI de todas as tabelas
    for (const { table: tableLeads } of uniqueLeadsTables) {
      const [handoffsResult, leadsInAIResult] = await Promise.all([
        supabaseAdmin
          .from(tableLeads)
          .select('*', { count: 'exact', head: true })
          .not('handoff_at', 'is', null)
          .gte('handoff_at', periodStart.toISOString()),
        supabaseAdmin
          .from(tableLeads)
          .select('*', { count: 'exact', head: true })
          .eq('current_state', 'ai'),
      ]);
      handoffsTotal += handoffsResult.count || 0;
      leadsInAI += leadsInAIResult.count || 0;
    }

    // Formatar funil com percentuais
    const totalFunnel = Object.values(pipelineFunnelMap).reduce((a, b) => a + b, 0);
    const pipelineFunnel = Object.entries(pipelineFunnelMap)
      .sort((a, b) => b[1] - a[1])
      .map(([etapa, quantidade]) => ({
        etapa,
        quantidade,
        percentual: totalFunnel > 0 ? Math.round((quantidade / totalFunnel) * 100) : 0,
      }));

    // Calcular taxa de conversao
    const conversionRate = totalLeads > 0 ? (leadsConverted / totalLeads) * 100 : 0;
    const previousConversionRate = totalLeadsPrevious > 0 ? (leadsConverted / totalLeadsPrevious) * 100 : 0;

    // Formatar leads over time
    const monthOrder = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez'];
    const leadsOverTime = monthOrder
      .filter(month => leadsOverTimeMap[month])
      .map(month => ({ name: month, leads: leadsOverTimeMap[month] }));

    // ========================================================================
    // CONFIGURAÇÃO DE ORIGENS DOS LEADS
    // Cores e labels para cada tipo de origem detectada
    // ========================================================================
    const sourceConfig: Record<string, { color: string; label: string; icon: string }> = {
      // Ads - Redes Sociais
      'facebook_ads': { color: '#1877F2', label: 'Facebook Ads', icon: 'facebook' },
      'instagram_ads': { color: '#E4405F', label: 'Instagram Ads', icon: 'instagram' },
      'tiktok_ads': { color: '#000000', label: 'TikTok Ads', icon: 'tiktok' },
      'youtube_ads': { color: '#FF0000', label: 'YouTube Ads', icon: 'youtube' },
      'linkedin_ads': { color: '#0A66C2', label: 'LinkedIn Ads', icon: 'linkedin' },
      'twitter_ads': { color: '#000000', label: 'Twitter/X Ads', icon: 'twitter' },
      'pinterest_ads': { color: '#E60023', label: 'Pinterest Ads', icon: 'pinterest' },
      'kwai_ads': { color: '#FF7700', label: 'Kwai Ads', icon: 'kwai' },
      'snapchat_ads': { color: '#FFFC00', label: 'Snapchat Ads', icon: 'snapchat' },
      'spotify_ads': { color: '#1DB954', label: 'Spotify Ads', icon: 'spotify' },

      // Ads - Nativos
      'google_ads': { color: '#4285F4', label: 'Google Ads', icon: 'google' },
      'taboola_ads': { color: '#0066FF', label: 'Taboola', icon: 'taboola' },
      'outbrain_ads': { color: '#FF6600', label: 'Outbrain', icon: 'outbrain' },
      'other_ads': { color: '#6B7280', label: 'Outros Anúncios', icon: 'ads' },

      // Orgânicos
      'whatsapp': { color: '#25D366', label: 'WhatsApp', icon: 'whatsapp' },
      'instagram': { color: '#E4405F', label: 'Instagram', icon: 'instagram' },
      'site_organico': { color: '#059669', label: 'Site (Orgânico)', icon: 'site' },
      'indicacao': { color: '#10B981', label: 'Indicação', icon: 'indicacao' },

      // Marketing Direto
      'email_marketing': { color: '#6366F1', label: 'Email Marketing', icon: 'email' },
      'sms_marketing': { color: '#8B5CF6', label: 'SMS Marketing', icon: 'sms' },

      // Prospecção
      'diana': { color: '#8B5CF6', label: 'Diana (Prospecção)', icon: 'diana' },
      'diana_handoff': { color: '#A855F7', label: 'Diana Handoff', icon: 'diana' },

      // Campanhas e outros
      'campanha': { color: '#F59E0B', label: 'Campanha', icon: 'campaign' },
      'leadbox_import': { color: '#3B82F6', label: 'Leadbox Import', icon: 'import' },

      // Legados/Compatibilidade
      'Facebook': { color: '#1877F2', label: 'Facebook Ads', icon: 'facebook' },
      'facebook': { color: '#1877F2', label: 'Facebook Ads', icon: 'facebook' },
      'Google': { color: '#4285F4', label: 'Google Ads', icon: 'google' },
      'google': { color: '#4285F4', label: 'Google Ads', icon: 'google' },
      'WhatsApp': { color: '#25D366', label: 'WhatsApp', icon: 'whatsapp' },
      'Indicacao': { color: '#10B981', label: 'Indicação', icon: 'indicacao' },
      'Prospeccao': { color: '#8B5CF6', label: 'Prospecção', icon: 'diana' },
      'prospeccao': { color: '#8B5CF6', label: 'Prospecção', icon: 'diana' },
      'organic': { color: '#059669', label: 'Orgânico', icon: 'site' },
      'manual': { color: '#64748B', label: 'Manual', icon: 'site' },
    };

    // Formatar origens - SÓ RETORNA SE TIVER LEADS (count > 0)
    const totalSourceLeads = Object.values(leadSourcesMap).reduce((a, b) => a + b, 0);
    const leadSources = Object.entries(leadSourcesMap)
      .filter(([_, count]) => count > 0) // IMPORTANTE: Só origens com leads
      .sort((a, b) => b[1] - a[1])
      .slice(0, 10) // Top 10 origens
      .map(([name, count]) => {
        const config = sourceConfig[name] || { color: '#6B7280', label: name, icon: 'site' };
        return {
          name: config.label,        // Nome amigável
          originKey: name,           // Chave original para filtrar
          count,                     // Quantidade de leads
          value: totalSourceLeads > 0 ? Math.round((count / totalSourceLeads) * 100) : 0, // Percentual
          color: config.color,
          icon: config.icon,
        };
      });

    const stats: DashboardStats = {
      // Metricas principais
      totalLeads,
      totalLeadsChange: calculateChange(totalLeads, totalLeadsPrevious),
      // Metricas secundarias
      conversionRate: Math.round(conversionRate * 10) / 10,
      conversionRateChange: calculateChange(conversionRate, previousConversionRate),
      schedulesTotal,
      schedulesTotalChange: calculateChange(schedulesTotal, schedulesPrevious),
      leadsOutsideHours,
      leadsOutsideHoursChange: calculateChange(leadsOutsideHours, leadsOutsideHoursPrevious),
      // Metricas financeiras (Asaas)
      recoveredAmount,
      recoveredAmountChange: calculateChange(recoveredAmount, recoveredAmountPrevious),
      pendingAmount,
      overdueAmount,
      // Metricas de follow-up (Salvador)
      followUpsSent,
      followUpResponseRate,
      leadsReengaged,
      // Metricas operacionais
      handoffsTotal,
      leadsInAI,
      pipelineFunnel,
      // Dados visuais
      leadsByTemperature,
      leadsOverTime,
      leadSources,
      agentsPerformance,
      // Periodo
      period,
    };

    // ========================================================================
    // CACHE: Salvar no Redis (TTL 5 minutos)
    // ========================================================================
    try {
      await cache.setJson(cacheKey, stats, 300);
      console.log('[DashboardStats] Cache SET:', cacheKey);
    } catch (cacheError) {
      console.warn('[DashboardStats] Cache write error:', cacheError);
      // Continue without caching
    }

    return reply.send({ status: 'success', data: stats });
  } catch (error) {
    console.error('[DashboardStats] Error:', error);
    return reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

// ============================================================================
// GET LEADS BY CATEGORY (para clique nos big numbers)
// ============================================================================

type LeadCategory = 'total' | 'hot' | 'schedules' | 'outside_hours';

export async function getLeadsByCategory(
  request: FastifyRequest<{
    Querystring: {
      user_id?: string;
      period?: string;
      category: string;
    };
  }>,
  reply: FastifyReply
) {
  try {
    const user_id = (request as any).user?.id || request.query.user_id;
    const periodParam = request.query.period || 'week';
    const period = ['day', 'week', 'month', 'total'].includes(periodParam) ? periodParam as 'day' | 'week' | 'month' | 'total' : 'week';
    const category = request.query.category as LeadCategory;

    if (!user_id) {
      return reply.status(400).send({ status: 'error', message: 'Authentication required' });
    }

    if (!category) {
      return reply.status(400).send({ status: 'error', message: 'Category is required' });
    }

    // Buscar agentes do usuário
    const { data: agents, error: agentsError } = await supabaseAdmin
      .from('agents')
      .select('id, name, table_leads, timezone')
      .eq('user_id', user_id);

    if (agentsError || !agents || agents.length === 0) {
      return reply.send({ status: 'success', data: { leads: [], category, period } });
    }

    // Calcular período
    const now = new Date();
    const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const thisMonthStart = new Date(now.getFullYear(), now.getMonth(), 1);
    const weekStart = new Date(todayStart);
    weekStart.setDate(weekStart.getDate() - weekStart.getDay());

    let periodStart: Date | null = null;
    switch (period) {
      case 'day':
        periodStart = todayStart;
        break;
      case 'month':
        periodStart = thisMonthStart;
        break;
      case 'total':
        periodStart = null; // Sem filtro de data
        break;
      case 'week':
      default:
        periodStart = weekStart;
        break;
    }

    // Se categoria é 'schedules', buscar da tabela schedules
    if (category === 'schedules') {
      const agentIds = agents.map(a => a.id);
      let schedulesQuery = supabaseAdmin
        .from('schedules')
        .select('id, agent_id, lead_id, customer_name, company_name, remote_jid, scheduled_at, status, created_at')
        .in('agent_id', agentIds);

      // Aplicar filtro de data apenas se não for 'total'
      if (periodStart) {
        schedulesQuery = schedulesQuery.gte('scheduled_at', periodStart.toISOString());
      }

      const { data: schedules, error: schError } = await schedulesQuery.order('scheduled_at', { ascending: false });

      if (schError) {
        console.error('[getLeadsByCategory] Error fetching schedules:', schError);
        return reply.status(500).send({ status: 'error', message: 'Error fetching schedules' });
      }

      // Mapear agentes para incluir nome
      const agentMap = new Map(agents.map(a => [a.id, a.name]));

      // Extrair telefone do remote_jid (formato: 556699958623@s.whatsapp.net)
      const extractPhone = (jid: string | null) => {
        if (!jid) return null;
        return jid.replace('@s.whatsapp.net', '').replace('unknown_', '');
      };

      const formattedSchedules = (schedules || []).map(s => ({
        id: s.id,
        nome: s.customer_name || 'Sem nome',
        telefone: extractPhone(s.remote_jid),
        empresa: s.company_name,
        agendamento: s.scheduled_at,
        status: s.status,
        agente: resolveAgentNameSync(s.agent_id, agentMap),
        created_at: s.created_at,
      }));

      return reply.send({
        status: 'success',
        data: {
          leads: formattedSchedules,
          category,
          period,
          title: 'Agendamentos',
        },
      });
    }

    // Para outras categorias, buscar dos leads
    const allLeads: any[] = [];
    const processedTables = new Set<string>();

    for (const agent of agents) {
      if (!agent.table_leads || processedTables.has(agent.table_leads)) continue;
      processedTables.add(agent.table_leads);

      let query = supabaseAdmin
        .from(agent.table_leads)
        .select('id, nome, telefone, remotejid, pipeline_step, lead_temperature, qualification_score, created_date, updated_date, status')
        .order('created_date', { ascending: false })
        .limit(200);

      // Aplicar filtros baseados na categoria
      switch (category) {
        case 'total':
          // Leads do período (se periodStart definido)
          if (periodStart) {
            query = query.gte('created_date', periodStart.toISOString());
          }
          break;

        case 'hot':
          // Leads quentes
          query = query.or('lead_temperature.eq.hot,lead_temperature.eq.quente');
          break;

        case 'outside_hours':
          // Leads fora do horário - buscar todos do período e filtrar
          if (periodStart) {
            query = query.gte('created_date', periodStart.toISOString());
          }
          break;
      }

      const { data: leads, error: leadsError } = await query;

      if (leadsError) {
        console.error(`[getLeadsByCategory] Error fetching from ${agent.table_leads}:`, leadsError);
        continue;
      }

      if (leads) {
        // Para outside_hours, filtrar leads fora do horário comercial
        if (category === 'outside_hours') {
          const agentTimezone = agent.timezone || 'America/Sao_Paulo';
          const filteredLeads = leads.filter(lead => {
            if (!lead.created_date) return false;
            const leadDate = new Date(lead.created_date);
            const { hour, dayOfWeek } = getTimeInTimezone(leadDate, agentTimezone);
            // Fora do horário: antes das 8h, após 17h, ou fim de semana
            return hour < 8 || hour >= 17 || dayOfWeek === 0 || dayOfWeek === 6;
          });
          allLeads.push(...filteredLeads.map(l => ({ ...l, agente: agent.name })));
        } else {
          allLeads.push(...leads.map(l => ({ ...l, agente: agent.name })));
        }
      }
    }

    // Títulos para cada categoria
    const categoryTitles: Record<LeadCategory, string> = {
      total: 'Leads do Período',
      hot: 'Leads Quentes',
      schedules: 'Agendamentos',
      outside_hours: 'Leads Fora do Horário',
    };

    return reply.send({
      status: 'success',
      data: {
        leads: allLeads,
        category,
        period,
        title: categoryTitles[category],
      },
    });
  } catch (error) {
    console.error('[getLeadsByCategory] Error:', error);
    return reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

// ============================================================================
// GET LEADS BY ORIGIN (para clique nas origens do dashboard)
// ============================================================================

export async function getLeadsByOrigin(
  request: FastifyRequest<{
    Querystring: {
      user_id?: string;
      origin: string;
      limit?: string;
    };
  }>,
  reply: FastifyReply
) {
  try {
    const user_id = (request as any).user?.id || request.query.user_id;
    const origin = request.query.origin;
    const limit = parseInt(request.query.limit || '100', 10);

    if (!user_id) {
      return reply.status(400).send({ status: 'error', message: 'Authentication required' });
    }

    if (!origin) {
      return reply.status(400).send({ status: 'error', message: 'Origin parameter is required' });
    }

    console.log('[getLeadsByOrigin] Fetching leads', { user_id, origin, limit });

    // Buscar todos os agentes do usuário
    const { data: agents, error: agentsError } = await supabaseAdmin
      .from('agents')
      .select('id, name, table_leads')
      .eq('user_id', user_id);

    if (agentsError) {
      console.error('[getLeadsByOrigin] Error fetching agents:', agentsError);
      return reply.status(500).send({ status: 'error', message: 'Error fetching agents' });
    }

    if (!agents || agents.length === 0) {
      return reply.send({ status: 'success', data: { leads: [], origin, total: 0 } });
    }

    // Buscar leads de cada agente com a origem especificada
    const allLeads: any[] = [];
    const processedTables = new Set<string>();

    for (const agent of agents) {
      if (!agent.table_leads || processedTables.has(agent.table_leads)) continue;
      processedTables.add(agent.table_leads);

      try {
        // Construir query com filtro de origem
        // Suporta tanto a chave exata quanto variações do nome
        let query = supabaseAdmin
          .from(agent.table_leads)
          .select('id, nome, telefone, email, empresa, remotejid, pipeline_step, lead_origin, ad_url, created_date, updated_date, insights')
          .not('remotejid', 'like', 'test_%')
          .not('remotejid', 'like', 'teste_%')
          .not('remotejid', 'like', 'demo_%')
          .order('created_date', { ascending: false })
          .limit(limit);

        // Filtrar por origem - busca exata ou parcial
        if (origin === 'whatsapp') {
          // WhatsApp orgânico inclui null (leads sem origem definida) e string 'null'
          query = query.or('lead_origin.eq.whatsapp,lead_origin.is.null,lead_origin.eq.null');
        } else if (origin.includes('_ads') || origin.includes('Ads')) {
          // Ads - busca exata pela chave
          query = query.eq('lead_origin', origin);
        } else {
          // Outros - busca por ilike para pegar variações
          query = query.or(`lead_origin.eq.${origin},lead_origin.ilike.%${origin}%`);
        }

        const { data: leads, error: leadsError } = await query;

        if (leadsError) {
          console.error(`[getLeadsByOrigin] Error fetching from ${agent.table_leads}:`, leadsError);
          continue;
        }

        if (leads && leads.length > 0) {
          allLeads.push(...leads.map(l => ({
            ...l,
            agente: agent.name,
            agent_id: agent.id,
          })));
        }
      } catch (tableError) {
        console.error(`[getLeadsByOrigin] Error with table ${agent.table_leads}:`, tableError);
        continue;
      }
    }

    // Ordenar por data de criação (mais recentes primeiro) e limitar
    allLeads.sort((a, b) => {
      const dateA = new Date(a.created_date || 0).getTime();
      const dateB = new Date(b.created_date || 0).getTime();
      return dateB - dateA;
    });

    const limitedLeads = allLeads.slice(0, limit);

    console.log('[getLeadsByOrigin] Found leads', {
      origin,
      total: allLeads.length,
      returned: limitedLeads.length
    });

    return reply.send({
      status: 'success',
      data: {
        leads: limitedLeads,
        origin,
        total: allLeads.length,
      },
    });
  } catch (error) {
    console.error('[getLeadsByOrigin] Error:', error);
    return reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}
