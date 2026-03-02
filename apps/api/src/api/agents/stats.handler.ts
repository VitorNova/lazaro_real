import { FastifyRequest, FastifyReply } from 'fastify';
import { supabaseAdmin } from '../../services/supabase/client';

/**
 * Retorna hora e dia da semana no timezone especificado
 */
function getTimeInTimezone(date: Date, timezone?: string): { hour: number; dayOfWeek: number } {
  const tz = timezone || 'America/Sao_Paulo';

  try {
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
    const dayMap: Record<string, number> = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
    const dayOfWeek = dayPart ? (dayMap[dayPart.value] ?? date.getDay()) : date.getDay();

    return { hour, dayOfWeek };
  } catch {
    return { hour: date.getHours(), dayOfWeek: date.getDay() };
  }
}

interface GetAgentStatsRequest {
  Params: {
    agentId: string;
  };
}

interface AgentStats {
  // Conversas
  totalConversations: number;
  activeConversations: number;
  conversationsToday: number;
  conversationsThisWeek: number;
  conversationsThisMonth: number;

  // Leads
  totalLeads: number;
  leadsToday: number;
  leadsThisWeek: number;
  leadsThisMonth: number;
  hotLeads: number;
  warmLeads: number;
  coldLeads: number;
  qualifiedLeads: number;

  // Leads por origem
  leadsByOrigin: Record<string, number>;

  // Leads por etapa do pipeline
  leadsByPipeline: Record<string, number>;

  // Agendamentos
  totalSchedules: number;
  schedulesToday: number;
  schedulesThisWeek: number;
  schedulesThisMonth: number;
  schedulesConfirmed: number;
  schedulesCancelled: number;
  schedulesCompleted: number;
  schedulesPending: number;

  // Pagamentos
  totalPaymentLinks: number;
  paymentLinksToday: number;
  totalPaymentsValue: number;

  // Horário comercial
  leadsOutsideBusinessHours: number;
  leadsInsideBusinessHours: number;

  // Follow-ups
  totalFollowUps: number;
  followUpsPending: number;
  followUpsSent: number;

  // Taxa de conversão
  conversionRate: number;
  avgQualificationScore: number;
}

export async function getAgentStatsHandler(
  request: FastifyRequest<GetAgentStatsRequest>,
  reply: FastifyReply
): Promise<FastifyReply> {
  try {
    const { agentId } = request.params;

    // Buscar dados do agente
    const { data: agent, error: agentError } = await supabaseAdmin
      .from('agents')
      .select('id, name, table_leads, table_messages, table_controle, business_hours, work_days, timezone')
      .eq('id', agentId)
      .single();

    if (agentError || !agent) {
      return reply.status(404).send({
        status: 'error',
        message: 'Agente não encontrado',
      });
    }

    // Datas para filtros
    const now = new Date();
    const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).toISOString();
    const weekStart = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000).toISOString();
    const monthStart = new Date(now.getFullYear(), now.getMonth(), 1).toISOString();

    const stats: AgentStats = {
      totalConversations: 0,
      activeConversations: 0,
      conversationsToday: 0,
      conversationsThisWeek: 0,
      conversationsThisMonth: 0,
      totalLeads: 0,
      leadsToday: 0,
      leadsThisWeek: 0,
      leadsThisMonth: 0,
      hotLeads: 0,
      warmLeads: 0,
      coldLeads: 0,
      qualifiedLeads: 0,
      leadsByOrigin: {},
      leadsByPipeline: {},
      totalSchedules: 0,
      schedulesToday: 0,
      schedulesThisWeek: 0,
      schedulesThisMonth: 0,
      schedulesConfirmed: 0,
      schedulesCancelled: 0,
      schedulesCompleted: 0,
      schedulesPending: 0,
      totalPaymentLinks: 0,
      paymentLinksToday: 0,
      totalPaymentsValue: 0,
      leadsOutsideBusinessHours: 0,
      leadsInsideBusinessHours: 0,
      totalFollowUps: 0,
      followUpsPending: 0,
      followUpsSent: 0,
      conversionRate: 0,
      avgQualificationScore: 0,
    };

    // ==========================================
    // ESTATÍSTICAS DE MENSAGENS/CONVERSAS
    // ==========================================
    if (agent.table_messages) {
      try {
        // Total de conversas
        const { count: totalConversations } = await supabaseAdmin
          .from(agent.table_messages)
          .select('*', { count: 'exact', head: true });
        stats.totalConversations = totalConversations || 0;

        // Conversas hoje
        const { count: conversationsToday } = await supabaseAdmin
          .from(agent.table_messages)
          .select('*', { count: 'exact', head: true })
          .gte('creat', todayStart);
        stats.conversationsToday = conversationsToday || 0;

        // Conversas esta semana
        const { count: conversationsThisWeek } = await supabaseAdmin
          .from(agent.table_messages)
          .select('*', { count: 'exact', head: true })
          .gte('creat', weekStart);
        stats.conversationsThisWeek = conversationsThisWeek || 0;

        // Conversas este mês
        const { count: conversationsThisMonth } = await supabaseAdmin
          .from(agent.table_messages)
          .select('*', { count: 'exact', head: true })
          .gte('creat', monthStart);
        stats.conversationsThisMonth = conversationsThisMonth || 0;

        // Conversas ativas (últimas 24h com mensagem do usuário)
        const yesterday = new Date(now.getTime() - 24 * 60 * 60 * 1000).toISOString();
        const { count: activeConversations } = await supabaseAdmin
          .from(agent.table_messages)
          .select('*', { count: 'exact', head: true })
          .gte('Msg_user', yesterday);
        stats.activeConversations = activeConversations || 0;
      } catch (err) {
        console.log(`[Stats] Erro ao buscar mensagens da tabela ${agent.table_messages}:`, err);
      }
    }

    // ==========================================
    // ESTATÍSTICAS DE LEADS (CRM)
    // ==========================================
    if (agent.table_leads) {
      try {
        // Total de leads
        const { count: totalLeads } = await supabaseAdmin
          .from(agent.table_leads)
          .select('*', { count: 'exact', head: true });
        stats.totalLeads = totalLeads || 0;

        // Leads hoje
        const { count: leadsToday } = await supabaseAdmin
          .from(agent.table_leads)
          .select('*', { count: 'exact', head: true })
          .gte('created_date', todayStart);
        stats.leadsToday = leadsToday || 0;

        // Leads esta semana
        const { count: leadsThisWeek } = await supabaseAdmin
          .from(agent.table_leads)
          .select('*', { count: 'exact', head: true })
          .gte('created_date', weekStart);
        stats.leadsThisWeek = leadsThisWeek || 0;

        // Leads este mês
        const { count: leadsThisMonth } = await supabaseAdmin
          .from(agent.table_leads)
          .select('*', { count: 'exact', head: true })
          .gte('created_date', monthStart);
        stats.leadsThisMonth = leadsThisMonth || 0;

        // Leads por temperatura (se tiver a coluna lead_temperature)
        try {
          const { count: hotLeads } = await supabaseAdmin
            .from(agent.table_leads)
            .select('*', { count: 'exact', head: true })
            .eq('lead_temperature', 'hot');
          stats.hotLeads = hotLeads || 0;

          const { count: warmLeads } = await supabaseAdmin
            .from(agent.table_leads)
            .select('*', { count: 'exact', head: true })
            .eq('lead_temperature', 'warm');
          stats.warmLeads = warmLeads || 0;

          const { count: coldLeads } = await supabaseAdmin
            .from(agent.table_leads)
            .select('*', { count: 'exact', head: true })
            .eq('lead_temperature', 'cold');
          stats.coldLeads = coldLeads || 0;
        } catch {
          // Tabela pode não ter coluna lead_temperature
        }

        // Leads qualificados (bant_total >= 70)
        try {
          const { count: qualifiedLeads } = await supabaseAdmin
            .from(agent.table_leads)
            .select('*', { count: 'exact', head: true })
            .gte('bant_total', 70);
          stats.qualifiedLeads = qualifiedLeads || 0;
        } catch {
          // Tabela pode não ter coluna bant_total
        }

        // ==========================================
        // LEADS POR ORIGEM
        // ==========================================
        try {
          const { data: leadsWithOrigin } = await supabaseAdmin
            .from(agent.table_leads)
            .select('lead_origin');

          if (leadsWithOrigin) {
            const originCounts: Record<string, number> = {};
            for (const lead of leadsWithOrigin) {
              const origin = lead.lead_origin || 'whatsapp';
              originCounts[origin] = (originCounts[origin] || 0) + 1;
            }
            stats.leadsByOrigin = originCounts;
          }
        } catch {
          // Tabela pode não ter coluna lead_origin
        }

        // ==========================================
        // LEADS POR ETAPA DO PIPELINE
        // ==========================================
        try {
          const { data: leadsWithPipeline } = await supabaseAdmin
            .from(agent.table_leads)
            .select('pipeline_step');

          if (leadsWithPipeline) {
            const pipelineCounts: Record<string, number> = {};
            for (const lead of leadsWithPipeline) {
              let step = lead.pipeline_step || 'novo';
              // Normaliza para exibição consistente
              step = step.toLowerCase().trim().replace(/-/g, ' ');
              // Capitaliza primeira letra de cada palavra
              step = step.split(' ').map((word: string) =>
                word.charAt(0).toUpperCase() + word.slice(1)
              ).join(' ');
              pipelineCounts[step] = (pipelineCounts[step] || 0) + 1;
            }
            stats.leadsByPipeline = pipelineCounts;
          }
        } catch {
          // Tabela pode não ter colunas de pipeline
        }

        // ==========================================
        // TAXA DE CONVERSÃO E QUALIFICAÇÃO MÉDIA
        // ==========================================
        try {
          const { data: leadsForConversion } = await supabaseAdmin
            .from(agent.table_leads)
            .select('pipeline_step, bant_total, qualification_score');

          if (leadsForConversion && leadsForConversion.length > 0) {
            // Conta leads convertidos por pipeline_step
            const convertedCount = leadsForConversion.filter(l => {
              const step = (l.pipeline_step || '').toLowerCase();
              return step.includes('fechado') ||
                     step.includes('ganho') ||
                     step.includes('converted') ||
                     step.includes('won') ||
                     step.includes('venda') ||
                     step.includes('cliente') ||
                     step.includes('closed');
            }).length;

            stats.conversionRate = Math.round((convertedCount / leadsForConversion.length) * 100);

            // Calcula média de qualificação
            const qualificationScores = leadsForConversion
              .map(l => l.qualification_score || l.bant_total || 0)
              .filter(score => score > 0);

            if (qualificationScores.length > 0) {
              stats.avgQualificationScore = Math.round(
                qualificationScores.reduce((sum, s) => sum + s, 0) / qualificationScores.length
              );
            }
          }
        } catch {
          // Ignorar erros de conversão
        }

        // Leads fora do horário comercial FIXO (8h-17h) usando timezone do agente
        // Nota: business_hours do agente é o horário de funcionamento do bot, não o horário comercial
        try {
          const startHour = 8;
          const endHour = 17;
          const agentTimezone = agent.timezone || 'America/Sao_Paulo';

          // Buscar todos os leads com data de criação
          const { data: allLeads } = await supabaseAdmin
            .from(agent.table_leads)
            .select('created_date')
            .not('created_date', 'is', null);

          if (allLeads) {
            for (const lead of allLeads) {
              if (lead.created_date) {
                const leadDate = new Date(lead.created_date);
                const { hour, dayOfWeek } = getTimeInTimezone(leadDate, agentTimezone);

                // Fora do horário: antes das 8h, depois das 17h, ou fim de semana
                if (hour < startHour || hour >= endHour || dayOfWeek === 0 || dayOfWeek === 6) {
                  stats.leadsOutsideBusinessHours++;
                } else {
                  stats.leadsInsideBusinessHours++;
                }
              }
            }
          }
        } catch {
          // Ignorar erros de horário comercial
        }
      } catch (err) {
        console.log(`[Stats] Erro ao buscar leads da tabela ${agent.table_leads}:`, err);
      }
    }

    // ==========================================
    // ESTATÍSTICAS DE AGENDAMENTOS
    // ==========================================
    try {
      // Total de agendamentos
      const { count: totalSchedules } = await supabaseAdmin
        .from('schedules')
        .select('*', { count: 'exact', head: true })
        .eq('agent_id', agentId);
      stats.totalSchedules = totalSchedules || 0;

      // Agendamentos hoje
      const { count: schedulesToday } = await supabaseAdmin
        .from('schedules')
        .select('*', { count: 'exact', head: true })
        .eq('agent_id', agentId)
        .gte('scheduled_at', todayStart);
      stats.schedulesToday = schedulesToday || 0;

      // Agendamentos esta semana
      const { count: schedulesThisWeek } = await supabaseAdmin
        .from('schedules')
        .select('*', { count: 'exact', head: true })
        .eq('agent_id', agentId)
        .gte('scheduled_at', weekStart);
      stats.schedulesThisWeek = schedulesThisWeek || 0;

      // Agendamentos este mês
      const { count: schedulesThisMonth } = await supabaseAdmin
        .from('schedules')
        .select('*', { count: 'exact', head: true })
        .eq('agent_id', agentId)
        .gte('scheduled_at', monthStart);
      stats.schedulesThisMonth = schedulesThisMonth || 0;

      // Por status
      const { count: schedulesConfirmed } = await supabaseAdmin
        .from('schedules')
        .select('*', { count: 'exact', head: true })
        .eq('agent_id', agentId)
        .eq('status', 'confirmed');
      stats.schedulesConfirmed = schedulesConfirmed || 0;

      const { count: schedulesCancelled } = await supabaseAdmin
        .from('schedules')
        .select('*', { count: 'exact', head: true })
        .eq('agent_id', agentId)
        .eq('status', 'cancelled');
      stats.schedulesCancelled = schedulesCancelled || 0;

      const { count: schedulesCompleted } = await supabaseAdmin
        .from('schedules')
        .select('*', { count: 'exact', head: true })
        .eq('agent_id', agentId)
        .eq('status', 'completed');
      stats.schedulesCompleted = schedulesCompleted || 0;

      const { count: schedulesPending } = await supabaseAdmin
        .from('schedules')
        .select('*', { count: 'exact', head: true })
        .eq('agent_id', agentId)
        .eq('status', 'pending');
      stats.schedulesPending = schedulesPending || 0;
    } catch (err) {
      console.log(`[Stats] Erro ao buscar agendamentos:`, err);
    }

    // ==========================================
    // ESTATÍSTICAS DE PAGAMENTOS (tabela payments)
    // ==========================================
    try {
      // Total de links de pagamento gerados (payment_link não nulo)
      const { count: totalPaymentLinks } = await supabaseAdmin
        .from('payments')
        .select('*', { count: 'exact', head: true })
        .eq('organization_id', agentId)
        .not('payment_link', 'is', null);
      stats.totalPaymentLinks = totalPaymentLinks || 0;

      // Links gerados hoje
      const { count: paymentLinksToday } = await supabaseAdmin
        .from('payments')
        .select('*', { count: 'exact', head: true })
        .eq('organization_id', agentId)
        .not('payment_link', 'is', null)
        .gte('created_at', todayStart);
      stats.paymentLinksToday = paymentLinksToday || 0;

      // Valor total de pagamentos pagos
      const { data: payments } = await supabaseAdmin
        .from('payments')
        .select('amount')
        .eq('organization_id', agentId)
        .eq('status', 'paid');

      if (payments) {
        stats.totalPaymentsValue = payments.reduce((sum, p) => sum + (Number(p.amount) || 0), 0);
      }
    } catch (err) {
      console.log(`[Stats] Erro ao buscar pagamentos:`, err);
    }

    // ==========================================
    // ESTATÍSTICAS DE FOLLOW-UPS
    // ==========================================
    try {
      const { count: totalFollowUps } = await supabaseAdmin
        .from('follow_up_history')
        .select('*', { count: 'exact', head: true })
        .eq('agent_id', agentId);
      stats.totalFollowUps = totalFollowUps || 0;

      const { count: followUpsPending } = await supabaseAdmin
        .from('follow_up_history')
        .select('*', { count: 'exact', head: true })
        .eq('agent_id', agentId)
        .eq('status', 'pending');
      stats.followUpsPending = followUpsPending || 0;

      const { count: followUpsSent } = await supabaseAdmin
        .from('follow_up_history')
        .select('*', { count: 'exact', head: true })
        .eq('agent_id', agentId)
        .eq('status', 'sent');
      stats.followUpsSent = followUpsSent || 0;
    } catch {
      // Tabela pode não existir
    }

    return reply.status(200).send({
      status: 'success',
      agent: {
        id: agent.id,
        name: agent.name,
      },
      stats,
    });
  } catch (error) {
    console.error('[getAgentStatsHandler] Erro:', error);
    return reply.status(500).send({
      status: 'error',
      message: 'Erro ao buscar estatísticas do agente',
    });
  }
}
