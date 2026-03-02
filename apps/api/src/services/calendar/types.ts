// ============================================================================
// CONFIGURAÇÃO
// ============================================================================

export interface CalendarConfig {
  clientId: string;
  clientSecret: string;
  refreshToken: string;
  calendarId: string;
}

// ============================================================================
// EVENTO DO CALENDÁRIO
// ============================================================================

export interface CalendarEvent {
  id: string;
  summary: string;
  description?: string;
  start: EventDateTime;
  end: EventDateTime;
  attendees?: Attendee[];
  conferenceData?: ConferenceData;
  status?: EventStatus;
  htmlLink?: string;
  created?: string;
  updated?: string;
  isAllDay?: boolean; // true se for evento de dia inteiro
  // NOVO: Metadados Agnes (extendedProperties)
  extendedProperties?: ExtendedProperties;
  agnesMetadata?: AgnesEventMetadata; // Parsed metadata se for evento Agnes
}

export interface EventDateTime {
  dateTime: string; // ISO 8601
  timeZone: string;
}

export interface Attendee {
  email: string;
  displayName?: string;
  responseStatus?: AttendeeResponseStatus;
  organizer?: boolean;
  self?: boolean;
}

export type AttendeeResponseStatus =
  | 'needsAction'
  | 'declined'
  | 'tentative'
  | 'accepted';

export type EventStatus = 'confirmed' | 'tentative' | 'cancelled';

// ============================================================================
// CONFERENCE DATA (GOOGLE MEET)
// ============================================================================

export interface ConferenceData {
  entryPoints?: EntryPoint[];
  conferenceSolution?: ConferenceSolution;
  conferenceId?: string;
}

export interface EntryPoint {
  entryPointType: 'video' | 'phone' | 'sip' | 'more';
  uri: string;
  label?: string;
  pin?: string;
  regionCode?: string;
}

export interface ConferenceSolution {
  key: {
    type: string;
  };
  name: string;
  iconUri?: string;
}

// ============================================================================
// INPUT PARA CRIAÇÃO DE EVENTO
// ============================================================================

// ============================================================================
// EXTENDED PROPERTIES (METADADOS AGNES)
// ============================================================================

/**
 * Metadados Agnes armazenados no evento do Google Calendar
 * Usados para identificar eventos criados pela Agnes e vincular ao lead
 */
export interface AgnesEventMetadata {
  source: 'agnes' | 'diana'; // Identificador do agente que criou o evento
  agent_id: string;          // UUID do agente que criou
  remote_jid: string;        // WhatsApp JID do lead (ex: "5511999999999@s.whatsapp.net")
  lead_id?: string;          // UUID do lead (opcional)
  organization_id?: string;  // UUID da organização (opcional)
  created_at: string;        // ISO timestamp de quando foi criado
}

export interface ExtendedProperties {
  private?: Record<string, string>;  // Visível apenas para o app que criou
  shared?: Record<string, string>;   // Visível para todos os apps
}

export interface CreateEventInput {
  summary: string;
  description?: string;
  startDateTime: string; // ISO 8601
  endDateTime: string; // ISO 8601
  timezone: string;
  attendeeEmail?: string;
  attendeeName?: string;
  createMeetLink?: boolean;
  sendNotifications?: boolean;
  // NOVO: Metadados Agnes para identificar eventos criados pela IA
  agnesMetadata?: AgnesEventMetadata;
}

export interface UpdateEventInput {
  summary?: string;
  description?: string;
  startDateTime?: string;
  endDateTime?: string;
  timezone?: string;
  attendeeEmail?: string;
  attendeeName?: string;
}

// ============================================================================
// DISPONIBILIDADE
// ============================================================================

export interface TimeSlot {
  start: string; // ISO 8601
  end: string; // ISO 8601
}

export interface AvailabilityResult {
  date: string; // YYYY-MM-DD
  timezone: string;
  workHoursStart: number;
  workHoursEnd: number;
  slotDuration: number;
  availableSlots: TimeSlot[];
  busySlots: TimeSlot[];
}

export interface AvailabilityParams {
  date: string; // YYYY-MM-DD
  workHoursStart: number; // 0-23
  workHoursEnd: number; // 0-23
  slotDuration: number; // minutos
  breakBetweenSlots?: number; // minutos de intervalo entre slots
  timezone: string;
}

// ============================================================================
// HELPERS
// ============================================================================

/**
 * Extrai o link do Google Meet de um evento
 */
export function extractMeetLink(event: CalendarEvent): string | null {
  if (!event.conferenceData?.entryPoints) {
    return null;
  }

  const videoEntry = event.conferenceData.entryPoints.find(
    (entry) => entry.entryPointType === 'video'
  );

  return videoEntry?.uri || null;
}

/**
 * Formata um slot de tempo para exibição
 */
export function formatTimeSlot(slot: TimeSlot, timezone: string): string {
  const start = new Date(slot.start);
  const end = new Date(slot.end);

  const timeFormatter = new Intl.DateTimeFormat('pt-BR', {
    hour: '2-digit',
    minute: '2-digit',
    timeZone: timezone,
  });

  return `${timeFormatter.format(start)} - ${timeFormatter.format(end)}`;
}

/**
 * Converte um horário (hora:minuto) em Date para uma data específica
 */
export function timeToDate(
  date: string,
  hour: number,
  minute: number = 0,
  timezone: string
): Date {
  const dateStr = `${date}T${hour.toString().padStart(2, '0')}:${minute.toString().padStart(2, '0')}:00`;

  // Criar date com timezone correto
  const formatter = new Intl.DateTimeFormat('en-CA', {
    timeZone: timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });

  // Ajuste simples para criar a data correta
  return new Date(dateStr);
}

/**
 * Verifica se dois períodos de tempo se sobrepõem
 */
export function doTimePeriodsOverlap(
  start1: Date,
  end1: Date,
  start2: Date,
  end2: Date
): boolean {
  return start1 < end2 && end1 > start2;
}

// ============================================================================
// CONFIGURAÇÕES ESPECIAIS POR AGENTE (HARDCODED)
// ============================================================================

/**
 * Configuração de horários específicos para agentes
 * Agentes não listados aqui usam business_hours padrão do banco
 */
interface AgentCustomSchedule {
  agentId: string;
  agentName: string;
  allowedPeriods: Array<{
    start: number; // hora de início (0-23)
    end: number;   // hora de fim (0-23)
  }>;
  // NOVO: Lista de horários EXATOS permitidos (ex: ['08:00', '09:00', '14:00'])
  // Se definido, APENAS estes horários serão aceitos (ignora allowedPeriods)
  allowedExactTimes?: string[];
  meetingDuration: number; // minutos
}

// NOTA: Configurações de horários específicos devem estar no banco de dados (tabela agents)
// Não hardcode configurações de clientes aqui!
const CUSTOM_AGENT_SCHEDULES: AgentCustomSchedule[] = [];

/**
 * Verifica se um agente tem configuração de horário customizada
 */
export function hasCustomSchedule(agentId: string): boolean {
  return CUSTOM_AGENT_SCHEDULES.some(s => s.agentId === agentId);
}

/**
 * Obtém a configuração customizada de um agente
 */
export function getCustomSchedule(agentId: string): AgentCustomSchedule | null {
  return CUSTOM_AGENT_SCHEDULES.find(s => s.agentId === agentId) || null;
}

// ============================================================================
// CONFIGURAÇÕES DE PERÍODO (MANHÃ/TARDE) POR AGENDA
// ============================================================================

/**
 * Configuração de horários de uma agenda específica
 */
export interface AccountScheduleConfig {
  morning_enabled: boolean;
  morning_start: string; // HH:MM
  morning_end: string;   // HH:MM
  afternoon_enabled: boolean;
  afternoon_start: string; // HH:MM
  afternoon_end: string;   // HH:MM
  work_days?: Record<string, boolean>; // { seg: true, ter: true, ... }
}

/**
 * Converte string HH:MM para hora numérica (ex: "14:30" => 14.5)
 */
export function timeStringToHours(time: string): number {
  const [hours, minutes] = time.split(':').map(Number);
  return hours + (minutes / 60);
}

/**
 * Verifica se um horário específico está dentro dos períodos permitidos (manhã/tarde)
 * IMPORTANTE: Considera a duração da reunião para garantir que ela caiba inteira no período
 *
 * @param time Horário no formato HH:MM
 * @param config Configuração de períodos
 * @param durationMinutes Duração da reunião em minutos (default: 60)
 * @returns { allowed: boolean, reason: string }
 *
 * Exemplo com manhã 08:00-10:00 e duração 60min:
 * - 08:00 -> termina 09:00 -> OK (09:00 <= 10:00)
 * - 09:00 -> termina 10:00 -> OK (10:00 <= 10:00)
 * - 09:30 -> termina 10:30 -> BLOQUEADO (10:30 > 10:00)
 */
export function isTimeInAllowedPeriod(
  time: string,
  config: AccountScheduleConfig,
  durationMinutes: number = 60
): { allowed: boolean; reason: string } {
  const timeHours = timeStringToHours(time);
  const durationHours = durationMinutes / 60; // Converter duração para horas decimais
  const endTimeHours = timeHours + durationHours; // Horário de término da reunião

  // Se nenhum período está habilitado, bloquear
  if (!config.morning_enabled && !config.afternoon_enabled) {
    return { allowed: false, reason: 'Nenhum período de atendimento está habilitado para esta agenda.' };
  }

  // Verificar período da manhã
  // A reunião DEVE começar >= início E terminar <= fim do período
  if (config.morning_enabled) {
    const morningStart = timeStringToHours(config.morning_start);
    const morningEnd = timeStringToHours(config.morning_end);
    if (timeHours >= morningStart && endTimeHours <= morningEnd) {
      return { allowed: true, reason: 'Horário dentro do período da manhã.' };
    }
  }

  // Verificar período da tarde
  // A reunião DEVE começar >= início E terminar <= fim do período
  if (config.afternoon_enabled) {
    const afternoonStart = timeStringToHours(config.afternoon_start);
    const afternoonEnd = timeStringToHours(config.afternoon_end);
    if (timeHours >= afternoonStart && endTimeHours <= afternoonEnd) {
      return { allowed: true, reason: 'Horário dentro do período da tarde.' };
    }
  }

  // Construir mensagem de erro com horários disponíveis
  // Calcular o último horário válido para cada período (considerando duração)
  const availablePeriods: string[] = [];
  if (config.morning_enabled) {
    const morningEnd = timeStringToHours(config.morning_end);
    const lastValidMorning = morningEnd - durationHours;
    const lastValidMorningStr = `${Math.floor(lastValidMorning).toString().padStart(2, '0')}:${Math.round((lastValidMorning % 1) * 60).toString().padStart(2, '0')}`;
    availablePeriods.push(`manhã (${config.morning_start} às ${lastValidMorningStr})`);
  }
  if (config.afternoon_enabled) {
    const afternoonEnd = timeStringToHours(config.afternoon_end);
    const lastValidAfternoon = afternoonEnd - durationHours;
    const lastValidAfternoonStr = `${Math.floor(lastValidAfternoon).toString().padStart(2, '0')}:${Math.round((lastValidAfternoon % 1) * 60).toString().padStart(2, '0')}`;
    availablePeriods.push(`tarde (${config.afternoon_start} às ${lastValidAfternoonStr})`);
  }

  return {
    allowed: false,
    reason: `O horário ${time} está fora dos períodos de atendimento (considerando duração de ${durationMinutes} minutos). Horários disponíveis: ${availablePeriods.join(' e ')}.`,
  };
}

/**
 * Verifica se um dia da semana está habilitado na configuração
 * @param date Data no formato YYYY-MM-DD
 * @param workDays Configuração de dias { seg: true, ter: false, ... }
 * @returns { allowed: boolean, dayName: string }
 */
export function isDayAllowed(
  date: string,
  workDays?: Record<string, boolean>
): { allowed: boolean; dayName: string } {
  const dateObj = new Date(date + 'T12:00:00');
  const dayOfWeek = dateObj.getDay(); // 0=domingo, 1=segunda, etc.

  const dayMap: Record<number, { key: string; name: string }> = {
    0: { key: 'dom', name: 'domingo' },
    1: { key: 'seg', name: 'segunda-feira' },
    2: { key: 'ter', name: 'terça-feira' },
    3: { key: 'qua', name: 'quarta-feira' },
    4: { key: 'qui', name: 'quinta-feira' },
    5: { key: 'sex', name: 'sexta-feira' },
    6: { key: 'sab', name: 'sábado' },
  };

  const day = dayMap[dayOfWeek];

  // Se não tem configuração de dias, usar padrão seg-sex
  if (!workDays) {
    const defaultAllowed = dayOfWeek >= 1 && dayOfWeek <= 5;
    return { allowed: defaultAllowed, dayName: day.name };
  }

  const allowed = workDays[day.key] === true;
  return { allowed, dayName: day.name };
}

/**
 * Valida completamente se um agendamento está dentro do escopo permitido
 * IMPORTANTE: Considera a duração da reunião para garantir que ela caiba inteira no período
 *
 * @param date Data no formato YYYY-MM-DD
 * @param time Horário no formato HH:MM
 * @param config Configuração de horários da agenda
 * @param durationMinutes Duração da reunião em minutos (default: 60)
 * @returns { allowed: boolean, reason: string }
 */
export function validateScheduleTime(
  date: string,
  time: string,
  config: AccountScheduleConfig,
  durationMinutes: number = 60
): { allowed: boolean; reason: string } {
  // 1. Verificar dia da semana
  const dayCheck = isDayAllowed(date, config.work_days);
  if (!dayCheck.allowed) {
    return {
      allowed: false,
      reason: `Não há atendimento em ${dayCheck.dayName}. Por favor, escolha outro dia.`,
    };
  }

  // 2. Verificar período (manhã/tarde) considerando a duração da reunião
  const periodCheck = isTimeInAllowedPeriod(time, config, durationMinutes);
  if (!periodCheck.allowed) {
    return periodCheck;
  }

  return { allowed: true, reason: 'Horário dentro do escopo permitido.' };
}

/**
 * Filtra slots disponíveis baseado na configuração de períodos (manhã/tarde)
 * IMPORTANTE: Considera a duração da reunião para garantir que ela caiba inteira no período
 *
 * @param slots Lista de slots para filtrar
 * @param config Configuração de períodos
 * @param timezone Timezone para formatação
 * @param durationMinutes Duração da reunião em minutos (default: 60)
 */
export function filterSlotsByPeriod(
  slots: TimeSlot[],
  config: AccountScheduleConfig,
  timezone: string,
  durationMinutes: number = 60
): TimeSlot[] {
  return slots.filter(slot => {
    const slotStart = new Date(slot.start);
    const timeStr = slotStart.toLocaleTimeString('pt-BR', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZone: timezone,
    });

    const check = isTimeInAllowedPeriod(timeStr, config, durationMinutes);
    return check.allowed;
  });
}

/**
 * Formata hora no padrão HH:MM (sempre 2 dígitos)
 * Resolve inconsistências de toLocaleTimeString entre diferentes locales
 */
function formatTimeHHMM(date: Date, timezone: string): string {
  const hours = parseInt(
    date.toLocaleTimeString('en-US', {
      hour: '2-digit',
      hour12: false,
      timeZone: timezone,
    })
  );
  const minutes = date.getMinutes();
  return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}`;
}

/**
 * Filtra slots disponíveis baseado na configuração customizada do agente
 * Retorna apenas slots que estão dentro dos períodos permitidos
 *
 * CORREÇÃO: Se allowedExactTimes estiver definido, usa APENAS esses horários exatos
 * CORREÇÃO 2: Agora usa formatação consistente HH:MM para comparação
 */
export function filterSlotsForAgent(agentId: string, slots: TimeSlot[], timezone: string): TimeSlot[] {
  const customSchedule = getCustomSchedule(agentId);

  if (!customSchedule) {
    // Sem configuração customizada, retorna todos os slots
    return slots;
  }

  console.log(`[CustomSchedule] Filtrando slots para ${customSchedule.agentName}`);
  console.log(`[CustomSchedule] Slots antes da filtragem: ${slots.length}`);
  console.log(`[CustomSchedule] Slots recebidos: ${slots.map(s => new Date(s.start).toISOString()).join(', ')}`);

  // NOVO: Se tem horários exatos definidos, usa APENAS eles
  if (customSchedule.allowedExactTimes && customSchedule.allowedExactTimes.length > 0) {
    console.log(`[CustomSchedule] Usando horários EXATOS: ${customSchedule.allowedExactTimes.join(', ')}`);

    const filteredSlots = slots.filter(slot => {
      const slotStart = new Date(slot.start);
      // CORREÇÃO: Usar função que garante formato HH:MM consistente
      const slotTime = formatTimeHHMM(slotStart, timezone);

      const isAllowed = customSchedule.allowedExactTimes!.includes(slotTime);

      console.log(`[CustomSchedule] Verificando slot ${slotTime} - ${isAllowed ? 'PERMITIDO' : 'REMOVIDO'}`);

      return isAllowed;
    });

    console.log(`[CustomSchedule] Slots após filtragem por horários exatos: ${filteredSlots.length}`);
    console.log(`[CustomSchedule] Horários finais: ${filteredSlots.map(s => formatTimeHHMM(new Date(s.start), timezone)).join(', ')}`);
    return filteredSlots;
  }

  // Fallback: usa allowedPeriods (comportamento antigo)
  console.log(`[CustomSchedule] Períodos permitidos: ${customSchedule.allowedPeriods.map(p => `${p.start}:00-${p.end}:00`).join(', ')}`);

  const filteredSlots = slots.filter(slot => {
    const slotStart = new Date(slot.start);
    const slotHour = parseInt(
      slotStart.toLocaleTimeString('en-US', {
        hour: '2-digit',
        hour12: false,
        timeZone: timezone,
      })
    );

    // Verificar se o slot está dentro de algum período permitido
    const isAllowed = customSchedule.allowedPeriods.some(period => {
      return slotHour >= period.start && slotHour < period.end;
    });

    if (!isAllowed) {
      console.log(`[CustomSchedule] Slot ${slotHour}:00 REMOVIDO (fora dos períodos permitidos)`);
    }

    return isAllowed;
  });

  console.log(`[CustomSchedule] Slots após filtragem: ${filteredSlots.length}`);

  return filteredSlots;
}
