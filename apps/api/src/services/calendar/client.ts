import { google, calendar_v3 } from 'googleapis';
import { OAuth2Client } from 'google-auth-library';
import {
  CalendarConfig,
  CalendarEvent,
  CreateEventInput,
  UpdateEventInput,
  AvailabilityResult,
  AvailabilityParams,
  TimeSlot,
  doTimePeriodsOverlap,
  AgnesEventMetadata,
  ExtendedProperties,
} from './types';

export class GoogleCalendarClient {
  private calendar: calendar_v3.Calendar;
  private oauth2Client: OAuth2Client;
  private calendarId: string;

  constructor(config: CalendarConfig) {
    this.calendarId = config.calendarId;

    // Configurar OAuth2
    this.oauth2Client = new google.auth.OAuth2(
      config.clientId,
      config.clientSecret
    );

    // Configurar refresh token
    this.oauth2Client.setCredentials({
      refresh_token: config.refreshToken,
    });

    // Criar cliente do Calendar
    this.calendar = google.calendar({
      version: 'v3',
      auth: this.oauth2Client,
    });
  }

  /**
   * Cria um evento no calendário
   * Se agnesMetadata for fornecido, adiciona extendedProperties para identificar o evento
   */
  async createEvent(input: CreateEventInput): Promise<CalendarEvent> {
    try {
      const event: calendar_v3.Schema$Event = {
        summary: input.summary,
        description: input.description,
        start: {
          dateTime: input.startDateTime,
          timeZone: input.timezone,
        },
        end: {
          dateTime: input.endDateTime,
          timeZone: input.timezone,
        },
      };

      // Adicionar participante se fornecido
      if (input.attendeeEmail) {
        event.attendees = [
          {
            email: input.attendeeEmail,
            displayName: input.attendeeName,
          },
        ];
      }

      // Configurar Google Meet se solicitado (padrão: true)
      if (input.createMeetLink !== false) {
        event.conferenceData = {
          createRequest: {
            requestId: `meet-${Date.now()}-${Math.random().toString(36).substring(7)}`,
            conferenceSolutionKey: {
              type: 'hangoutsMeet',
            },
          },
        };
      }

      // NOVO: Adicionar extendedProperties com metadados Agnes
      if (input.agnesMetadata) {
        event.extendedProperties = {
          private: {
            source: input.agnesMetadata.source,
            agent_id: input.agnesMetadata.agent_id,
            remote_jid: input.agnesMetadata.remote_jid,
            lead_id: input.agnesMetadata.lead_id || '',
            organization_id: input.agnesMetadata.organization_id || '',
            created_at: input.agnesMetadata.created_at,
          },
        };
        console.log('[GoogleCalendarClient] Adding Agnes metadata to event:', {
          agent_id: input.agnesMetadata.agent_id,
          remote_jid: input.agnesMetadata.remote_jid,
        });
      }

      const response = await this.calendar.events.insert({
        calendarId: this.calendarId,
        requestBody: event,
        conferenceDataVersion: input.createMeetLink !== false ? 1 : 0,
        sendUpdates: input.sendNotifications ? 'all' : 'none',
      });

      return this.parseEvent(response.data);
    } catch (error) {
      console.error('[GoogleCalendarClient] Error creating event:', error);
      throw this.handleError(error, 'createEvent');
    }
  }

  /**
   * Lista eventos em um período
   */
  async listEvents(startDate: Date, endDate: Date): Promise<CalendarEvent[]> {
    try {
      const response = await this.calendar.events.list({
        calendarId: this.calendarId,
        timeMin: startDate.toISOString(),
        timeMax: endDate.toISOString(),
        singleEvents: true,
        orderBy: 'startTime',
      });

      const events = response.data.items || [];
      return events.map((event) => this.parseEvent(event));
    } catch (error) {
      console.error('[GoogleCalendarClient] Error listing events:', error);
      throw this.handleError(error, 'listEvents');
    }
  }

  /**
   * Obtém um evento específico
   */
  async getEvent(eventId: string): Promise<CalendarEvent | null> {
    try {
      const response = await this.calendar.events.get({
        calendarId: this.calendarId,
        eventId,
      });

      return this.parseEvent(response.data);
    } catch (error: unknown) {
      // Retornar null se evento não encontrado
      if (this.isNotFoundError(error)) {
        return null;
      }
      console.error('[GoogleCalendarClient] Error getting event:', error);
      throw this.handleError(error, 'getEvent');
    }
  }

  /**
   * Calcula disponibilidade para uma data
   */
  async getAvailability(params: AvailabilityParams): Promise<AvailabilityResult> {
    const {
      date,
      workHoursStart,
      workHoursEnd,
      slotDuration,
      breakBetweenSlots = 0,
      timezone,
    } = params;

    try {
      // Criar datas de início e fim do dia
      const dayStart = new Date(`${date}T00:00:00`);
      const dayEnd = new Date(`${date}T23:59:59`);

      // Buscar eventos do dia
      const events = await this.listEvents(dayStart, dayEnd);

      // Extrair períodos ocupados (ignorar eventos de dia inteiro e cancelados)
      const busySlots: TimeSlot[] = events
        .filter((event) => event.status !== 'cancelled' && !event.isAllDay)
        .map((event) => ({
          start: event.start.dateTime,
          end: event.end.dateTime,
        }));

      // Calcular slots disponíveis
      const availableSlots = this.calculateAvailableSlots({
        date,
        workHoursStart,
        workHoursEnd,
        slotDuration,
        breakBetweenSlots,
        timezone,
        busySlots,
      });

      return {
        date,
        timezone,
        workHoursStart,
        workHoursEnd,
        slotDuration,
        availableSlots,
        busySlots,
      };
    } catch (error) {
      console.error('[GoogleCalendarClient] Error getting availability:', error);
      throw this.handleError(error, 'getAvailability');
    }
  }

  /**
   * Calcula slots disponíveis baseado nos eventos existentes
   */
  private calculateAvailableSlots(params: {
    date: string;
    workHoursStart: number;
    workHoursEnd: number;
    slotDuration: number;
    breakBetweenSlots: number;
    timezone: string;
    busySlots: TimeSlot[];
  }): TimeSlot[] {
    const {
      date,
      workHoursStart,
      workHoursEnd,
      slotDuration,
      breakBetweenSlots,
      timezone,
      busySlots,
    } = params;

    const availableSlots: TimeSlot[] = [];
    const slotDurationMs = slotDuration * 60 * 1000;
    const breakDurationMs = breakBetweenSlots * 60 * 1000;

    // Criar horário de início do expediente NO TIMEZONE DO AGENTE
    // Usar Intl.DateTimeFormat para obter o offset correto do timezone
    const getTimezoneOffset = (tz: string, dateStr: string): number => {
      // Criar uma data de referência
      const refDate = new Date(`${dateStr}T12:00:00Z`);
      // Formatar no timezone alvo para extrair o offset
      const formatter = new Intl.DateTimeFormat('en-US', {
        timeZone: tz,
        timeZoneName: 'shortOffset',
      });
      const parts = formatter.formatToParts(refDate);
      const tzPart = parts.find(p => p.type === 'timeZoneName')?.value || '+00:00';

      // Parse do offset (ex: "GMT-4" -> -4, "GMT-3" -> -3)
      const match = tzPart.match(/GMT([+-]?\d+)/);
      if (match) {
        return parseInt(match[1], 10) * 60; // Retorna em minutos
      }
      return 0;
    };

    const tzOffsetMinutes = getTimezoneOffset(timezone, date);
    const tzOffsetHours = tzOffsetMinutes / 60;

    // Criar datas considerando o timezone
    // Se workHoursStart=9 e timezone=America/Cuiaba (UTC-4), então 09:00 local = 13:00 UTC
    // CORRIGIDO: Usar Date math para lidar com overflow de dia corretamente
    const baseDate = new Date(`${date}T00:00:00Z`);

    // Calcular início e fim em UTC considerando o offset do timezone
    // workHoursStart local + offset = hora UTC
    // Exemplo: 8:00 em UTC-4 = 8:00 + 4 = 12:00 UTC
    const startMs = baseDate.getTime() + (workHoursStart - tzOffsetHours) * 60 * 60 * 1000;
    const endMs = baseDate.getTime() + (workHoursEnd - tzOffsetHours) * 60 * 60 * 1000;

    let currentTime = new Date(startMs);
    const endOfWorkDay = new Date(endMs);

    console.log(`[Calendar] Timezone: ${timezone}, Offset: ${tzOffsetMinutes}min, Work hours: ${workHoursStart}-${workHoursEnd} local, Start UTC: ${currentTime.toISOString()}, End UTC: ${endOfWorkDay.toISOString()}`);

    // Converter busy slots para Date
    const busyPeriods = busySlots.map((slot) => ({
      start: new Date(slot.start),
      end: new Date(slot.end),
    }));

    while (currentTime.getTime() + slotDurationMs <= endOfWorkDay.getTime()) {
      const slotEnd = new Date(currentTime.getTime() + slotDurationMs);

      // Verificar se o slot conflita com algum período ocupado
      const hasConflict = busyPeriods.some((busy) =>
        doTimePeriodsOverlap(currentTime, slotEnd, busy.start, busy.end)
      );

      if (!hasConflict) {
        availableSlots.push({
          start: currentTime.toISOString(),
          end: slotEnd.toISOString(),
        });
      }

      // Avançar para o próximo slot (incluindo intervalo)
      currentTime = new Date(currentTime.getTime() + slotDurationMs + breakDurationMs);
    }

    return availableSlots;
  }

  /**
   * Obtém disponibilidade para múltiplos dias
   */
  async getAvailabilityRange(
    startDate: string,
    endDate: string,
    params: Omit<AvailabilityParams, 'date'>
  ): Promise<AvailabilityResult[]> {
    const results: AvailabilityResult[] = [];
    const currentDate = new Date(startDate);
    const lastDate = new Date(endDate);

    while (currentDate <= lastDate) {
      const dateStr = currentDate.toISOString().split('T')[0];
      const availability = await this.getAvailability({
        ...params,
        date: dateStr,
      });
      results.push(availability);

      currentDate.setDate(currentDate.getDate() + 1);
    }

    return results;
  }

  /**
   * Atualiza um evento
   */
  async updateEvent(
    eventId: string,
    input: UpdateEventInput
  ): Promise<CalendarEvent> {
    try {
      // Buscar evento atual
      const currentEvent = await this.getEvent(eventId);
      if (!currentEvent) {
        throw new Error(`Event not found: ${eventId}`);
      }

      const updateData: calendar_v3.Schema$Event = {};

      if (input.summary !== undefined) {
        updateData.summary = input.summary;
      }

      if (input.description !== undefined) {
        updateData.description = input.description;
      }

      if (input.startDateTime) {
        updateData.start = {
          dateTime: input.startDateTime,
          timeZone: input.timezone || currentEvent.start.timeZone,
        };
      }

      if (input.endDateTime) {
        updateData.end = {
          dateTime: input.endDateTime,
          timeZone: input.timezone || currentEvent.end.timeZone,
        };
      }

      if (input.attendeeEmail) {
        updateData.attendees = [
          {
            email: input.attendeeEmail,
            displayName: input.attendeeName,
          },
        ];
      }

      const response = await this.calendar.events.patch({
        calendarId: this.calendarId,
        eventId,
        requestBody: updateData,
        sendUpdates: 'all',
      });

      return this.parseEvent(response.data);
    } catch (error) {
      console.error('[GoogleCalendarClient] Error updating event:', error);
      throw this.handleError(error, 'updateEvent');
    }
  }

  /**
   * Deleta um evento
   */
  async deleteEvent(eventId: string): Promise<void> {
    try {
      await this.calendar.events.delete({
        calendarId: this.calendarId,
        eventId,
        sendUpdates: 'all',
      });
    } catch (error) {
      // Ignorar se evento já foi deletado
      if (this.isNotFoundError(error)) {
        return;
      }
      console.error('[GoogleCalendarClient] Error deleting event:', error);
      throw this.handleError(error, 'deleteEvent');
    }
  }

  /**
   * Cancela um evento (não deleta, apenas marca como cancelado)
   */
  async cancelEvent(eventId: string): Promise<CalendarEvent> {
    try {
      const response = await this.calendar.events.patch({
        calendarId: this.calendarId,
        eventId,
        requestBody: {
          status: 'cancelled',
        },
        sendUpdates: 'all',
      });

      return this.parseEvent(response.data);
    } catch (error) {
      console.error('[GoogleCalendarClient] Error cancelling event:', error);
      throw this.handleError(error, 'cancelEvent');
    }
  }

  /**
   * Lista eventos criados pela Agnes em um período
   * Filtra por extendedProperties.private.source = 'agnes'
   * Com fallback para descrição padrão (eventos antigos)
   */
  async listAgnesEvents(
    startDate: Date,
    endDate: Date,
    agentId?: string
  ): Promise<CalendarEvent[]> {
    try {
      // Buscar eventos usando privateExtendedProperty filter
      // Formato: key=value (array de strings)
      const response = await this.calendar.events.list({
        calendarId: this.calendarId,
        timeMin: startDate.toISOString(),
        timeMax: endDate.toISOString(),
        singleEvents: true,
        orderBy: 'startTime',
        privateExtendedProperty: ['source=agnes'],
      });

      let events = response.data.items || [];

      // Filtrar por agent_id se fornecido
      if (agentId) {
        events = events.filter((event: calendar_v3.Schema$Event) => {
          const props = event.extendedProperties?.private;
          return props?.agent_id === agentId;
        });
      }

      const parsedEvents = events.map((event: calendar_v3.Schema$Event) => this.parseEvent(event));

      console.log(`[GoogleCalendarClient] Found ${parsedEvents.length} Agnes events (with extendedProperties)`);

      return parsedEvents;
    } catch (error) {
      console.error('[GoogleCalendarClient] Error listing Agnes events:', error);
      throw this.handleError(error, 'listAgnesEvents');
    }
  }

  /**
   * Lista eventos criados pela Agnes usando fallback de descrição
   * Para eventos antigos que não têm extendedProperties
   * Busca por descrição contendo "Agendamento realizado via WhatsApp"
   */
  async listAgnesEventsWithFallback(
    startDate: Date,
    endDate: Date,
    agentId?: string
  ): Promise<CalendarEvent[]> {
    try {
      // Primeiro buscar eventos com extendedProperties
      const agnesEvents = await this.listAgnesEvents(startDate, endDate, agentId);
      const agnesEventIds = new Set(agnesEvents.map((e) => e.id));

      // Depois buscar TODOS os eventos do período para fallback
      const allEvents = await this.listEvents(startDate, endDate);

      // Filtrar eventos que podem ser da Agnes (descrição padrão) mas não têm extendedProperties
      const fallbackEvents = allEvents.filter((event) => {
        // Ignorar se já está na lista de eventos Agnes
        if (agnesEventIds.has(event.id)) return false;

        // Ignorar eventos cancelados
        if (event.status === 'cancelled') return false;

        // Verificar descrição padrão da Agnes
        const description = event.description?.toLowerCase() || '';
        const isAgnesDescription =
          description.includes('agendamento realizado via whatsapp') ||
          description.includes('agendamento via whatsapp') ||
          description.includes('lead:') && description.includes('telefone:');

        return isAgnesDescription;
      });

      // Combinar eventos
      const combinedEvents = [...agnesEvents, ...fallbackEvents];

      console.log(`[GoogleCalendarClient] Found ${agnesEvents.length} Agnes events (extendedProperties) + ${fallbackEvents.length} fallback events (description)`);

      return combinedEvents;
    } catch (error) {
      console.error('[GoogleCalendarClient] Error listing Agnes events with fallback:', error);
      throw this.handleError(error, 'listAgnesEventsWithFallback');
    }
  }

  /**
   * Extrai remote_jid de um evento Agnes (para enviar confirmação)
   * Tenta primeiro extendedProperties, depois descrição
   */
  extractRemoteJidFromEvent(event: CalendarEvent): string | null {
    // Primeiro tentar extendedProperties
    if (event.agnesMetadata?.remote_jid) {
      return event.agnesMetadata.remote_jid;
    }

    // Fallback: extrair da descrição
    if (event.description) {
      // Padrão: "Telefone: 5511999999999" ou "Telefone: 5511999999999@s.whatsapp.net"
      const phoneMatch = event.description.match(/telefone:\s*(\d+)/i);
      if (phoneMatch) {
        const phone = phoneMatch[1];
        // Adicionar sufixo WhatsApp se não tiver
        return phone.includes('@') ? phone : `${phone}@s.whatsapp.net`;
      }
    }

    return null;
  }

  /**
   * Extrai nome do cliente de um evento Agnes
   */
  extractCustomerNameFromEvent(event: CalendarEvent): string | null {
    // Tentar extrair do título (formato: "Reunião com Nome")
    const titleMatch = event.summary?.match(/reuni[aã]o com\s+(.+)/i);
    if (titleMatch) {
      return titleMatch[1].trim();
    }

    // Fallback: extrair da descrição
    if (event.description) {
      const leadMatch = event.description.match(/lead:\s*(.+)/i);
      if (leadMatch) {
        return leadMatch[1].trim().split('\n')[0]; // Pegar só a primeira linha
      }
    }

    return null;
  }

  /**
   * Parseia evento da API para formato interno
   */
  private parseEvent(event: calendar_v3.Schema$Event): CalendarEvent {
    // Evento de dia inteiro tem .date ao invés de .dateTime
    const isAllDay = !event.start?.dateTime && !!event.start?.date;

    // Parsear extendedProperties
    const extendedProperties: ExtendedProperties | undefined = event.extendedProperties
      ? {
          private: event.extendedProperties.private as Record<string, string> | undefined,
          shared: event.extendedProperties.shared as Record<string, string> | undefined,
        }
      : undefined;

    // Extrair agnesMetadata se for evento Agnes
    let agnesMetadata: AgnesEventMetadata | undefined;
    if (extendedProperties?.private?.source === 'agnes') {
      agnesMetadata = {
        source: 'agnes',
        agent_id: extendedProperties.private.agent_id || '',
        remote_jid: extendedProperties.private.remote_jid || '',
        lead_id: extendedProperties.private.lead_id || undefined,
        organization_id: extendedProperties.private.organization_id || undefined,
        created_at: extendedProperties.private.created_at || '',
      };
    }

    return {
      id: event.id || '',
      summary: event.summary || '',
      description: event.description || undefined,
      isAllDay,
      start: {
        dateTime: event.start?.dateTime || event.start?.date || '',
        timeZone: event.start?.timeZone || 'America/Sao_Paulo',
      },
      end: {
        dateTime: event.end?.dateTime || event.end?.date || '',
        timeZone: event.end?.timeZone || 'America/Sao_Paulo',
      },
      attendees: event.attendees?.map((a) => ({
        email: a.email || '',
        displayName: a.displayName || undefined,
        responseStatus: a.responseStatus as 'needsAction' | 'declined' | 'tentative' | 'accepted',
        organizer: a.organizer || undefined,
        self: a.self || undefined,
      })),
      conferenceData: event.conferenceData
        ? {
            entryPoints: event.conferenceData.entryPoints?.map((e) => ({
              entryPointType: e.entryPointType as 'video' | 'phone' | 'sip' | 'more',
              uri: e.uri || '',
              label: e.label || undefined,
              pin: e.pin || undefined,
              regionCode: e.regionCode || undefined,
            })),
            conferenceSolution: event.conferenceData.conferenceSolution
              ? {
                  key: { type: event.conferenceData.conferenceSolution.key?.type || '' },
                  name: event.conferenceData.conferenceSolution.name || '',
                  iconUri: event.conferenceData.conferenceSolution.iconUri || undefined,
                }
              : undefined,
            conferenceId: event.conferenceData.conferenceId || undefined,
          }
        : undefined,
      status: event.status as CalendarEvent['status'],
      htmlLink: event.htmlLink || undefined,
      created: event.created || undefined,
      updated: event.updated || undefined,
      extendedProperties,
      agnesMetadata,
    };
  }

  /**
   * Verifica se é erro de não encontrado
   */
  private isNotFoundError(error: unknown): boolean {
    if (error && typeof error === 'object' && 'code' in error) {
      return (error as { code: number }).code === 404;
    }
    return false;
  }

  /**
   * Trata erros de forma padronizada
   */
  private handleError(error: unknown, operation: string): Error {
    if (error instanceof Error) {
      return new Error(`[GoogleCalendarClient] ${operation} failed: ${error.message}`);
    }
    return new Error(`[GoogleCalendarClient] ${operation} failed: Unknown error`);
  }
}

/**
 * Factory function para criar cliente do Google Calendar
 */
export function createGoogleCalendarClient(config: CalendarConfig): GoogleCalendarClient {
  return new GoogleCalendarClient(config);
}
