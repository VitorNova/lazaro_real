import { GoogleCalendarClient, createGoogleCalendarClient } from './client';
import {
  CalendarEvent,
  CreateEventInput,
  AvailabilityResult,
  AvailabilityParams,
  TimeSlot,
  filterSlotsForAgent,
} from './types';

// ============================================================================
// TYPES
// ============================================================================

export interface GoogleAccount {
  email: string;
  credentials: {
    refresh_token: string;
    access_token?: string;
    [key: string]: unknown;
  };
  calendar_id: string;
}

export interface MultiCalendarConfig {
  clientId: string;
  clientSecret: string;
  accounts: GoogleAccount[]; // Ordenado por prioridade (index 0 = prioritario)
}

/**
 * Cenarios de disponibilidade para multiplas agendas
 * - primary_only: Primaria tem horarios, secundaria nao tem
 * - secondary_only: Secundaria tem horarios, primaria nao tem
 * - both: Ambas tem horarios disponiveis
 * - none: Nenhuma agenda tem horarios
 */
export type AvailabilityScenario = 'primary_only' | 'secondary_only' | 'both' | 'none';

export interface MultiCalendarAvailabilityResult {
  /** Cenario de disponibilidade */
  scenario: AvailabilityScenario;
  /** Conta(s) onde agendar (pode ser uma ou ambas) */
  accountsToSchedule: GoogleAccount[];
  /** Conta que tem disponibilidade (ou null se nenhuma) - compatibilidade */
  availableAccount: GoogleAccount | null;
  /** Index da conta disponivel (ou -1 se nenhuma) - compatibilidade */
  availableAccountIndex: number;
  /** Resultado de disponibilidade da conta prioritaria */
  primaryAvailability: AvailabilityResult | null;
  /** Resultado de disponibilidade da conta secundaria */
  secondaryAvailability: AvailabilityResult | null;
  /** Todos os resultados de disponibilidade */
  allAvailabilities: Array<{
    account: GoogleAccount;
    availability: AvailabilityResult;
    hasSlots: boolean;
  }>;
  /** Slots disponiveis combinados (da conta com disponibilidade) */
  availableSlots: TimeSlot[];
  /** Mensagem descritiva */
  message: string;
}

export interface MultiCalendarEventResult {
  /** Conta principal onde o evento foi agendado */
  primaryAccount: GoogleAccount;
  /** Evento criado na conta principal */
  primaryEvent: CalendarEvent;
  /** Eventos criados nas contas secundarias */
  secondaryEvents: Array<{
    account: GoogleAccount;
    event: CalendarEvent | null;
    error?: string;
  }>;
  /** Se todos os eventos foram criados com sucesso */
  allCreated: boolean;
}

// ============================================================================
// MULTI-CALENDAR CLIENT
// ============================================================================

export class MultiCalendarClient {
  private config: MultiCalendarConfig;
  private clients: Map<string, GoogleCalendarClient> = new Map();

  constructor(config: MultiCalendarConfig) {
    this.config = config;

    // Criar clientes para cada conta
    for (const account of config.accounts) {
      const client = createGoogleCalendarClient({
        clientId: config.clientId,
        clientSecret: config.clientSecret,
        refreshToken: account.credentials.refresh_token,
        calendarId: account.calendar_id || 'primary',
      });
      this.clients.set(account.email, client);
    }
  }

  /**
   * Verifica disponibilidade em ambas agendas e determina o cenario:
   * - primary_only: Primaria tem, secundaria nao tem -> agendar so na primaria
   * - secondary_only: Secundaria tem, primaria nao tem -> agendar so na secundaria
   * - both: Ambas tem -> agendar em ambas
   * - none: Nenhuma tem -> nao agendar
   * @param params Parâmetros de disponibilidade
   * @param agentId ID do agente (opcional) - usado para filtrar slots customizados
   */
  async getAvailabilityWithPriority(
    params: AvailabilityParams,
    agentId?: string
  ): Promise<MultiCalendarAvailabilityResult> {
    const allAvailabilities: MultiCalendarAvailabilityResult['allAvailabilities'] = [];

    console.log(`[MultiCalendar] Verificando disponibilidade para ${this.config.accounts.length} contas`);
    console.log(`[MultiCalendar] Contas: ${this.config.accounts.map(a => a.email).join(', ')}`);

    // Verificar disponibilidade em TODAS as contas primeiro
    // Manter a ordem das contas mesmo quando ha erro
    for (let i = 0; i < this.config.accounts.length; i++) {
      const account = this.config.accounts[i];
      const client = this.clients.get(account.email);

      if (!client) {
        console.warn(`[MultiCalendar] Client not found for ${account.email}`);
        // Adicionar resultado vazio para manter a ordem
        allAvailabilities.push({
          account,
          availability: {
            date: params.date,
            timezone: params.timezone || 'America/Sao_Paulo',
            workHoursStart: params.workHoursStart,
            workHoursEnd: params.workHoursEnd,
            slotDuration: params.slotDuration,
            availableSlots: [],
            busySlots: [],
          },
          hasSlots: false,
        });
        continue;
      }

      try {
        console.log(`[MultiCalendar] Verificando disponibilidade para: ${account.email}`);
        const availability = await client.getAvailability(params);

        // Aplicar filtro de slots customizado se o agente tiver configuração especial
        if (agentId) {
          availability.availableSlots = filterSlotsForAgent(
            agentId,
            availability.availableSlots,
            params.timezone || 'America/Sao_Paulo'
          );
        }

        const hasSlots = availability.availableSlots.length > 0;
        console.log(`[MultiCalendar] ${account.email}: ${hasSlots ? availability.availableSlots.length + ' slots disponiveis' : 'sem slots'}`);

        allAvailabilities.push({
          account,
          availability,
          hasSlots,
        });
      } catch (error) {
        console.error(`[MultiCalendar] Error checking availability for ${account.email}:`, error);
        // Adicionar resultado vazio para manter a ordem das contas
        allAvailabilities.push({
          account,
          availability: {
            date: params.date,
            timezone: params.timezone || 'America/Sao_Paulo',
            workHoursStart: params.workHoursStart,
            workHoursEnd: params.workHoursEnd,
            slotDuration: params.slotDuration,
            availableSlots: [],
            busySlots: [],
          },
          hasSlots: false,
        });
      }
    }

    // Obter resultados da primaria e secundaria (agora sempre estarao na ordem correta)
    const primaryResult = allAvailabilities[0];
    const secondaryResult = allAvailabilities[1];

    console.log(`[MultiCalendar] primaryResult: ${primaryResult?.account?.email || 'undefined'}, hasSlots: ${primaryResult?.hasSlots}`);
    console.log(`[MultiCalendar] secondaryResult: ${secondaryResult?.account?.email || 'undefined'}, hasSlots: ${secondaryResult?.hasSlots}`);

    const primaryHasSlots = primaryResult?.hasSlots || false;
    const secondaryHasSlots = secondaryResult?.hasSlots || false;

    // Determinar cenario e contas onde agendar
    let scenario: AvailabilityScenario;
    let accountsToSchedule: GoogleAccount[] = [];
    let availableAccount: GoogleAccount | null = null;
    let availableAccountIndex = -1;
    let availableSlots: TimeSlot[] = [];
    let message: string;

    if (primaryHasSlots && secondaryHasSlots) {
      // AMBAS tem disponibilidade -> agendar em ambas
      scenario = 'both';
      accountsToSchedule = [primaryResult.account, secondaryResult.account];
      availableAccount = primaryResult.account; // Para compatibilidade
      availableAccountIndex = 0;
      // Combinar slots (usar interseção - horarios disponiveis em ambas)
      availableSlots = this.getIntersectionSlots(
        primaryResult.availability.availableSlots,
        secondaryResult.availability.availableSlots
      );
      message = `Horarios disponiveis em ambas agendas (${primaryResult.account.email} e ${secondaryResult.account.email})`;
      console.log(`[MultiCalendar] Cenario: BOTH - Agendar em ambas agendas`);
    } else if (primaryHasSlots && !secondaryHasSlots) {
      // PRIMARIA tem, SECUNDARIA nao tem -> agendar SOMENTE na primaria
      scenario = 'primary_only';
      accountsToSchedule = [primaryResult.account];
      availableAccount = primaryResult.account;
      availableAccountIndex = 0;
      availableSlots = primaryResult.availability.availableSlots;
      message = `Agenda primaria (${primaryResult.account.email}) tem horarios disponiveis`;
      console.log(`[MultiCalendar] Cenario: PRIMARY_ONLY - Agendar somente na primaria`);
    } else if (!primaryHasSlots && secondaryHasSlots) {
      // SECUNDARIA tem, PRIMARIA nao tem -> agendar SOMENTE na secundaria
      scenario = 'secondary_only';
      accountsToSchedule = [secondaryResult.account];
      availableAccount = secondaryResult.account;
      availableAccountIndex = 1;
      availableSlots = secondaryResult.availability.availableSlots;
      message = `Agenda secundaria (${secondaryResult.account.email}) tem horarios disponiveis`;
      console.log(`[MultiCalendar] Cenario: SECONDARY_ONLY - Agendar somente na secundaria`);
    } else {
      // NENHUMA tem disponibilidade
      scenario = 'none';
      accountsToSchedule = [];
      message = 'Nenhuma agenda tem horarios disponiveis para esta data';
      console.log(`[MultiCalendar] Cenario: NONE - Nenhuma agenda disponivel`);
    }

    return {
      scenario,
      accountsToSchedule,
      availableAccount,
      availableAccountIndex,
      primaryAvailability: primaryResult?.availability || null,
      secondaryAvailability: secondaryResult?.availability || null,
      allAvailabilities,
      availableSlots,
      message,
    };
  }

  /**
   * Retorna a intersecao de slots disponiveis em ambas agendas
   */
  private getIntersectionSlots(primarySlots: TimeSlot[], secondarySlots: TimeSlot[]): TimeSlot[] {
    return primarySlots.filter(primarySlot =>
      secondarySlots.some(secondarySlot =>
        primarySlot.start === secondarySlot.start && primarySlot.end === secondarySlot.end
      )
    );
  }

  /**
   * Verifica disponibilidade para multiplos dias com prioridade
   * @param dates Array de datas YYYY-MM-DD
   * @param params Parâmetros de disponibilidade
   * @param agentId ID do agente (opcional) - usado para filtrar slots customizados
   */
  async getAvailabilityRangeWithPriority(
    dates: string[],
    params: Omit<AvailabilityParams, 'date'>,
    agentId?: string
  ): Promise<Array<{ date: string; result: MultiCalendarAvailabilityResult }>> {
    const results: Array<{ date: string; result: MultiCalendarAvailabilityResult }> = [];

    for (const date of dates) {
      const result = await this.getAvailabilityWithPriority({
        ...params,
        date,
      }, agentId);
      results.push({ date, result });
    }

    return results;
  }

  /**
   * Cria evento SOMENTE nas agendas especificadas pelo cenario
   * - primary_only: Cria apenas na primaria
   * - secondary_only: Cria apenas na secundaria
   * - both: Cria em ambas (sem prefixo [Bloqueado])
   */
  async createEventInAllCalendars(
    input: CreateEventInput,
    targetAccounts: GoogleAccount[],
    scenario: AvailabilityScenario = 'primary_only'
  ): Promise<MultiCalendarEventResult> {
    console.log(`[MultiCalendar] createEventInAllCalendars chamado`);
    console.log(`[MultiCalendar] scenario: ${scenario}`);
    console.log(`[MultiCalendar] targetAccounts: ${targetAccounts.length} contas`);
    console.log(`[MultiCalendar] targetAccounts emails: ${targetAccounts.map(a => a.email).join(', ')}`);

    if (targetAccounts.length === 0) {
      throw new Error('Nenhuma conta especificada para criar evento');
    }

    // A primeira conta da lista sera a "principal" (de onde vem o Meet link)
    const primaryAccount = targetAccounts[0];
    const primaryClient = this.clients.get(primaryAccount.email);

    if (!primaryClient) {
      throw new Error(`Client not found for primary account: ${primaryAccount.email}`);
    }

    // Criar evento na conta principal (com Meet link)
    console.log(`[MultiCalendar] Cenario: ${scenario} - Criando evento PRINCIPAL em: ${primaryAccount.email}`);
    const primaryEvent = await primaryClient.createEvent(input);
    console.log(`[MultiCalendar] Evento principal criado com ID: ${primaryEvent.id}`);

    const secondaryEvents: MultiCalendarEventResult['secondaryEvents'] = [];
    let allCreated = true;

    // Se cenario e 'both', criar evento na segunda conta tambem (SEM prefixo [Bloqueado])
    console.log(`[MultiCalendar] Verificando se deve criar na secundaria: scenario='${scenario}', targetAccounts.length=${targetAccounts.length}`);
    if (scenario === 'both' && targetAccounts.length > 1) {
      const secondaryAccount = targetAccounts[1];
      const secondaryClient = this.clients.get(secondaryAccount.email);

      if (!secondaryClient) {
        secondaryEvents.push({
          account: secondaryAccount,
          event: null,
          error: 'Client not found',
        });
        allCreated = false;
      } else {
        try {
          console.log(`[MultiCalendar] Criando evento TAMBEM em: ${secondaryAccount.email}`);

          // Criar evento igual (sem prefixo [Bloqueado] pois ambas tem disponibilidade)
          const secondaryEvent = await secondaryClient.createEvent({
            ...input,
            createMeetLink: false, // Nao criar Meet link duplicado
            sendNotifications: false, // Nao enviar notificacao duplicada
          });

          secondaryEvents.push({
            account: secondaryAccount,
            event: secondaryEvent,
          });
        } catch (error) {
          console.error(`[MultiCalendar] Error creating event in ${secondaryAccount.email}:`, error);
          secondaryEvents.push({
            account: secondaryAccount,
            event: null,
            error: error instanceof Error ? error.message : 'Unknown error',
          });
          allCreated = false;
        }
      }
    }

    // Log do cenario
    if (scenario === 'primary_only') {
      console.log(`[MultiCalendar] Evento criado SOMENTE na primaria (${primaryAccount.email})`);
    } else if (scenario === 'secondary_only') {
      console.log(`[MultiCalendar] Evento criado SOMENTE na secundaria (${primaryAccount.email})`);
    } else if (scenario === 'both') {
      console.log(`[MultiCalendar] Evento criado em AMBAS agendas`);
    }

    return {
      primaryAccount,
      primaryEvent,
      secondaryEvents,
      allCreated,
    };
  }

  /**
   * Verifica conflitos diretamente no Google Calendar API
   * Faz uma chamada real para listEvents nas contas alvo para garantir que o horário está livre
   * @param targetAccounts Contas onde o evento será criado
   * @param startDateTime Data/hora de início em ISO 8601
   * @param endDateTime Data/hora de fim em ISO 8601
   * @param timezone Timezone para formatação das mensagens
   * @returns Objeto com informação de conflito e eventos conflitantes
   */
  async checkConflictsDirectly(
    targetAccounts: GoogleAccount[],
    startDateTime: string,
    endDateTime: string,
    timezone: string = 'America/Sao_Paulo'
  ): Promise<{
    hasConflict: boolean;
    conflictingEvents: Array<{
      account: string;
      eventId: string;
      summary: string;
      start: string;
      end: string;
    }>;
    message?: string;
  }> {
    const requestedStart = new Date(startDateTime);
    const requestedEnd = new Date(endDateTime);
    const conflictingEvents: Array<{
      account: string;
      eventId: string;
      summary: string;
      start: string;
      end: string;
    }> = [];

    console.log(`[MultiCalendar] checkConflictsDirectly - Verificando conflitos em ${targetAccounts.length} contas`);
    console.log(`[MultiCalendar] Período: ${startDateTime} a ${endDateTime}`);

    for (const account of targetAccounts) {
      const client = this.clients.get(account.email);
      if (!client) {
        console.warn(`[MultiCalendar] Client not found for ${account.email} during conflict check`);
        continue;
      }

      try {
        // Buscar eventos existentes diretamente no Google Calendar
        const existingEvents = await client.listEvents(requestedStart, requestedEnd);

        // Filtrar eventos que realmente conflitam
        for (const evt of existingEvents) {
          // Ignorar eventos cancelados
          if (evt.status === 'cancelled') continue;

          // Ignorar eventos de dia inteiro
          if (evt.isAllDay) continue;

          const evtStart = new Date(evt.start.dateTime);
          const evtEnd = new Date(evt.end.dateTime);

          // Verificar sobreposição: início solicitado < fim do evento E fim solicitado > início do evento
          if (requestedStart < evtEnd && requestedEnd > evtStart) {
            console.log(`[MultiCalendar] CONFLITO encontrado em ${account.email}:`, {
              eventId: evt.id,
              summary: evt.summary,
              start: evt.start.dateTime,
              end: evt.end.dateTime,
            });

            conflictingEvents.push({
              account: account.email,
              eventId: evt.id,
              summary: evt.summary || 'Evento sem título',
              start: evt.start.dateTime,
              end: evt.end.dateTime,
            });
          }
        }
      } catch (error) {
        console.error(`[MultiCalendar] Error checking conflicts in ${account.email}:`, error);
        // Continuar verificando outras contas mesmo com erro
      }
    }

    if (conflictingEvents.length > 0) {
      const firstConflict = conflictingEvents[0];
      const conflictStart = new Date(firstConflict.start);
      const conflictStartFormatted = conflictStart.toLocaleTimeString('pt-BR', {
        hour: '2-digit',
        minute: '2-digit',
        timeZone: timezone,
      });

      return {
        hasConflict: true,
        conflictingEvents,
        message: `Já existe um evento às ${conflictStartFormatted}: "${firstConflict.summary}"`,
      };
    }

    console.log(`[MultiCalendar] checkConflictsDirectly - Nenhum conflito encontrado`);
    return {
      hasConflict: false,
      conflictingEvents: [],
    };
  }

  /**
   * Deleta evento de todas as agendas
   */
  async deleteEventFromAllCalendars(
    eventIds: Array<{ accountEmail: string; eventId: string }>
  ): Promise<void> {
    for (const { accountEmail, eventId } of eventIds) {
      const client = this.clients.get(accountEmail);
      if (client) {
        try {
          await client.deleteEvent(eventId);
        } catch (error) {
          console.error(`[MultiCalendar] Error deleting event ${eventId} from ${accountEmail}:`, error);
        }
      }
    }
  }

  /**
   * Retorna numero de contas configuradas
   */
  get accountCount(): number {
    return this.config.accounts.length;
  }

  /**
   * Retorna se tem multiplas contas
   */
  get hasMultipleAccounts(): boolean {
    return this.config.accounts.length > 1;
  }
}

// ============================================================================
// FACTORY FUNCTION
// ============================================================================

export function createMultiCalendarClient(config: MultiCalendarConfig): MultiCalendarClient {
  return new MultiCalendarClient(config);
}

/**
 * Cria cliente de multi-calendario a partir de google_accounts do banco
 */
export function createMultiCalendarClientFromAccounts(
  accounts: GoogleAccount[] | null | undefined,
  clientId: string,
  clientSecret: string
): MultiCalendarClient | null {
  if (!accounts || accounts.length === 0) {
    return null;
  }

  return createMultiCalendarClient({
    clientId,
    clientSecret,
    accounts,
  });
}
