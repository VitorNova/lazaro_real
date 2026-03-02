import { FastifyRequest, FastifyReply } from 'fastify';
import { supabaseAdmin } from '../../services/supabase/client';
import type { Schedule } from '../../services/supabase/types';

// ============================================================================
// TYPES
// ============================================================================

interface DeleteScheduleRequest {
  Params: { agentId: string; scheduleId: string };
}

interface GetSchedulesRequest {
  Params: { agentId: string };
  Querystring: { leadId?: string; status?: string };
}

// ============================================================================
// LOGGER
// ============================================================================

const Logger = {
  info: (msg: string, data?: unknown) => console.info(`[SchedulesHandler] ${msg}`, data ?? ''),
  warn: (msg: string, data?: unknown) => console.warn(`[SchedulesHandler] ${msg}`, data ?? ''),
  error: (msg: string, data?: unknown) => console.error(`[SchedulesHandler] ${msg}`, data ?? ''),
};

// ============================================================================
// HANDLERS
// ============================================================================

/**
 * GET /api/agents/:agentId/schedules
 * Lista agendamentos do agente (opcionalmente filtrado por lead ou status)
 */
export async function getSchedulesHandler(
  request: FastifyRequest<GetSchedulesRequest>,
  reply: FastifyReply
): Promise<FastifyReply> {
  try {
    const { agentId } = request.params;
    const { leadId, status } = request.query;
    const userId = (request as any).user?.id || request.headers['x-user-id'];

    if (!userId) {
      return reply.status(401).send({ status: 'error', message: 'Unauthorized' });
    }

    // Verificar se agente pertence ao usuario
    const { data: agent, error: agentError } = await supabaseAdmin
      .from('agents')
      .select('id, name, table_leads')
      .eq('id', agentId)
      .eq('user_id', userId)
      .single();

    if (agentError || !agent) {
      return reply.status(404).send({ status: 'error', message: 'Agent not found' });
    }

    // Construir query
    let query = supabaseAdmin
      .from('schedules')
      .select('*')
      .eq('agent_id', agentId)
      .order('scheduled_at', { ascending: true });

    // Filtrar por lead se fornecido
    if (leadId) {
      query = query.eq('lead_id', leadId);
    }

    // Filtrar por status se fornecido
    if (status) {
      query = query.eq('status', status);
    }

    const { data: schedules, error: schedulesError } = await query;

    if (schedulesError) {
      Logger.error('Error fetching schedules', { error: schedulesError.message });
      return reply.status(500).send({ status: 'error', message: 'Error fetching schedules' });
    }

    return reply.send({
      status: 'success',
      schedules: schedules || [],
      count: schedules?.length || 0,
    });

  } catch (error) {
    Logger.error('Unexpected error in getSchedulesHandler', {
      error: error instanceof Error ? error.message : error,
    });
    return reply.status(500).send({
      status: 'error',
      message: 'Erro interno ao listar agendamentos',
    });
  }
}

/**
 * DELETE /api/agents/:agentId/schedules/:scheduleId
 * Remove um agendamento e opcionalmente o evento do Google Calendar
 */
export async function deleteScheduleHandler(
  request: FastifyRequest<DeleteScheduleRequest>,
  reply: FastifyReply
): Promise<FastifyReply> {
  try {
    const { agentId, scheduleId } = request.params;
    const userId = (request as any).user?.id || request.headers['x-user-id'];

    if (!userId) {
      return reply.status(401).send({ status: 'error', message: 'Unauthorized' });
    }

    Logger.info('Delete schedule request', { agentId, scheduleId, userId });

    // Verificar se agente pertence ao usuario
    const { data: agent, error: agentError } = await supabaseAdmin
      .from('agents')
      .select('id, name, table_leads, google_calendar_enabled, google_credentials, google_calendar_id, google_accounts, timezone')
      .eq('id', agentId)
      .eq('user_id', userId)
      .single();

    if (agentError || !agent) {
      Logger.error('Agent not found', { agentId, userId, error: agentError });
      return reply.status(404).send({ status: 'error', message: 'Agent not found' });
    }

    // Buscar o agendamento
    const { data: schedule, error: scheduleError } = await supabaseAdmin
      .from('schedules')
      .select('*')
      .eq('id', scheduleId)
      .eq('agent_id', agentId)
      .single();

    if (scheduleError || !schedule) {
      Logger.error('Schedule not found', { scheduleId, agentId, error: scheduleError });
      return reply.status(404).send({ status: 'error', message: 'Schedule not found' });
    }

    const typedSchedule = schedule as Schedule;
    Logger.info('Found schedule to delete', {
      scheduleId,
      googleEventId: typedSchedule.google_event_id,
      leadId: typedSchedule.lead_id,
      scheduledAt: typedSchedule.scheduled_at,
    });

    // Se tem google_event_id, tentar deletar do Google Calendar
    let googleDeleteResult = { success: false, message: '' };

    if (typedSchedule.google_event_id && agent.google_calendar_enabled) {
      try {
        // Tentar deletar de todas as agendas configuradas
        if (agent.google_accounts && agent.google_accounts.length > 0) {
          for (const account of (agent.google_accounts as any[])) {
            try {
              const { createGoogleCalendarClient } = await import('../../services/calendar');
              const calendarClient = createGoogleCalendarClient({
                clientId: process.env.GOOGLE_CLIENT_ID || '',
                clientSecret: process.env.GOOGLE_CLIENT_SECRET || '',
                refreshToken: account.credentials?.refresh_token,
                calendarId: account.calendar_id,
              });

              await calendarClient.deleteEvent(typedSchedule.google_event_id!);
              googleDeleteResult = { success: true, message: `Event deleted from calendar ${account.email}` };
              Logger.info('Google Calendar event deleted', { eventId: typedSchedule.google_event_id, calendar: account.email });
              break; // Sucesso, nao precisa tentar outras agendas
            } catch (calError) {
              Logger.warn('Failed to delete from calendar account', {
                email: account.email,
                error: calError instanceof Error ? calError.message : calError
              });
            }
          }
        } else if (agent.google_credentials && agent.google_calendar_id) {
          // Fallback para credenciais simples
          const { createGoogleCalendarClient } = await import('../../services/calendar');
          const credentials = agent.google_credentials as { refresh_token?: string };

          const calendarClient = createGoogleCalendarClient({
            clientId: process.env.GOOGLE_CLIENT_ID || '',
            clientSecret: process.env.GOOGLE_CLIENT_SECRET || '',
            refreshToken: credentials.refresh_token || '',
            calendarId: agent.google_calendar_id,
          });

          await calendarClient.deleteEvent(typedSchedule.google_event_id);
          googleDeleteResult = { success: true, message: 'Event deleted from Google Calendar' };
          Logger.info('Google Calendar event deleted (simple credentials)', { eventId: typedSchedule.google_event_id });
        }
      } catch (googleError) {
        // Nao falhar a operacao se o Google Calendar falhar
        Logger.warn('Failed to delete Google Calendar event (continuing with database delete)', {
          eventId: typedSchedule.google_event_id,
          error: googleError instanceof Error ? googleError.message : googleError,
        });
        googleDeleteResult = {
          success: false,
          message: `Failed to delete from Google Calendar: ${googleError instanceof Error ? googleError.message : 'Unknown error'}`
        };
      }
    }

    // Deletar o agendamento do banco de dados
    const { error: deleteError } = await supabaseAdmin
      .from('schedules')
      .delete()
      .eq('id', scheduleId)
      .eq('agent_id', agentId);

    if (deleteError) {
      Logger.error('Failed to delete schedule from database', { error: deleteError.message });
      return reply.status(500).send({
        status: 'error',
        message: 'Failed to delete schedule from database',
      });
    }

    Logger.info('Schedule deleted from database', { scheduleId });

    // Atualizar next_appointment_at do lead se necessario
    if (typedSchedule.lead_id && agent.table_leads) {
      try {
        // Buscar proximo agendamento do lead
        const { data: nextSchedule } = await supabaseAdmin
          .from('schedules')
          .select('scheduled_at, meeting_link')
          .eq('lead_id', typedSchedule.lead_id)
          .eq('agent_id', agentId)
          .neq('status', 'cancelled')
          .order('scheduled_at', { ascending: true })
          .limit(1)
          .single();

        // Atualizar lead com proximo agendamento (ou null se nao houver)
        await supabaseAdmin
          .from(agent.table_leads)
          .update({
            next_appointment_at: nextSchedule?.scheduled_at || null,
            next_appointment_link: nextSchedule?.meeting_link || null,
            updated_date: new Date().toISOString(),
          })
          .eq('id', typedSchedule.lead_id);

        Logger.info('Lead next_appointment_at updated', {
          leadId: typedSchedule.lead_id,
          nextAppointment: nextSchedule?.scheduled_at || null
        });
      } catch (leadError) {
        // Nao falhar a operacao se a atualizacao do lead falhar
        Logger.warn('Failed to update lead next_appointment_at', {
          leadId: typedSchedule.lead_id,
          error: leadError instanceof Error ? leadError.message : leadError,
        });
      }
    }

    return reply.send({
      status: 'success',
      message: 'Schedule deleted successfully',
      deleted: {
        scheduleId,
        googleEventId: typedSchedule.google_event_id,
        googleCalendarDeleted: googleDeleteResult.success,
        googleCalendarMessage: googleDeleteResult.message,
      },
    });

  } catch (error) {
    Logger.error('Unexpected error in deleteScheduleHandler', {
      error: error instanceof Error ? error.message : error,
    });
    return reply.status(500).send({
      status: 'error',
      message: 'Erro interno ao deletar agendamento',
    });
  }
}
