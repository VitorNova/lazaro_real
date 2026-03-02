// ============================================================================
// ENUMS
// ============================================================================

export enum PlanType {
  BASIC = 'basic',
  PRO = 'pro',
  ENTERPRISE = 'enterprise',
}

export enum UserRole {
  OWNER = 'owner',
  ADMIN = 'admin',
  MEMBER = 'member',
}

export enum AsaasEnvironment {
  SANDBOX = 'sandbox',
  PRODUCTION = 'production',
}

export enum LeadStatus {
  OPEN = 'open',
  QUALIFIED = 'qualified',
  CONVERTED = 'converted',
  LOST = 'lost',
  INACTIVE = 'inactive',
}

export enum PipelineStep {
  LEADS = 'Leads',
  CONTACTED = 'Contacted',
  QUALIFIED = 'Qualified',
  PROPOSAL = 'Proposal',
  NEGOTIATION = 'Negotiation',
  WON = 'Won',
  LOST = 'Lost',
}

export enum MessageRole {
  USER = 'user',
  ASSISTANT = 'assistant',
  FUNCTION = 'function',
  SYSTEM = 'system',
}

export enum MessageType {
  TEXT = 'text',
  AUDIO = 'audio',
  IMAGE = 'image',
  DOCUMENT = 'document',
  VIDEO = 'video',
  STICKER = 'sticker',
  LOCATION = 'location',
}

export enum ScheduleStatus {
  SCHEDULED = 'scheduled',
  CONFIRMED = 'confirmed',
  CANCELLED = 'cancelled',
  COMPLETED = 'completed',
  NO_SHOW = 'no_show',
}

export enum PaymentStatus {
  PENDING = 'pending',
  CONFIRMED = 'confirmed',
  RECEIVED = 'received',
  OVERDUE = 'overdue',
  REFUNDED = 'refunded',
  CANCELLED = 'cancelled',
}

// ============================================================================
// ORGANIZATION
// ============================================================================

export interface Organization {
  id: string;
  name: string;
  slug: string;
  logo_url: string | null;
  plan: PlanType;
  is_active: boolean;
  trial_ends_at: string | null;
  webhook_secret: string | null;
  created_at: string;
  updated_at: string;
}

export interface OrganizationCreate {
  name: string;
  slug: string;
  logo_url?: string | null;
  plan?: PlanType;
  is_active?: boolean;
  trial_ends_at?: string | null;
  webhook_secret?: string | null;
}

export interface OrganizationUpdate {
  name?: string;
  slug?: string;
  logo_url?: string | null;
  plan?: PlanType;
  is_active?: boolean;
  trial_ends_at?: string | null;
  webhook_secret?: string | null;
}

// ============================================================================
// USER
// ============================================================================

export interface User {
  id: string;
  organization_id: string;
  email: string;
  name: string | null;
  role: UserRole;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface UserCreate {
  organization_id: string;
  email: string;
  name?: string | null;
  role?: UserRole;
  is_active?: boolean;
}

export interface UserUpdate {
  email?: string;
  name?: string | null;
  role?: UserRole;
  is_active?: boolean;
}

// ============================================================================
// INTEGRATION
// ============================================================================

export interface GoogleCredentials {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expiry_date: number;
}

export interface Integration {
  id: string;
  organization_id: string;
  uazapi_base_url: string | null;
  uazapi_instance: string | null;
  uazapi_api_key: string | null;
  asaas_api_key: string | null;
  asaas_environment: AsaasEnvironment;
  google_credentials: GoogleCredentials | null;
  google_calendar_id: string | null;
  google_accounts?: Array<{
    email: string;
    credentials: {
      refresh_token: string;
      access_token?: string;
      [key: string]: unknown;
    };
    calendar_id: string;
    // Configuracoes de horario por agenda
    work_days?: { seg: boolean; ter: boolean; qua: boolean; qui: boolean; sex: boolean; sab: boolean; dom: boolean };
    morning_enabled?: boolean;
    morning_start?: string;
    morning_end?: string;
    afternoon_enabled?: boolean;
    afternoon_start?: string;
    afternoon_end?: string;
    // Duracao da reuniao em minutos (15, 30, 45 ou 60). Default: 60
    meeting_duration?: number;
  }> | null;
  created_at: string;
  updated_at: string;
}

export interface IntegrationCreate {
  organization_id: string;
  uazapi_base_url?: string | null;
  uazapi_instance?: string | null;
  uazapi_api_key?: string | null;
  asaas_api_key?: string | null;
  asaas_environment?: AsaasEnvironment;
  google_credentials?: GoogleCredentials | null;
  google_calendar_id?: string | null;
}

export interface IntegrationUpdate {
  uazapi_base_url?: string | null;
  uazapi_instance?: string | null;
  uazapi_api_key?: string | null;
  asaas_api_key?: string | null;
  asaas_environment?: AsaasEnvironment;
  google_credentials?: GoogleCredentials | null;
  google_calendar_id?: string | null;
}

// ============================================================================
// ASAAS PAYMENT CONFIG
// ============================================================================

export interface AsaasProduct {
  name: string;
  value: number;
  isDynamic?: boolean; // Se true, valor é definido dinamicamente pela IA conforme o prompt
  chargeType?: 'DETACHED' | 'RECURRENT';
  subscriptionCycle?: 'WEEKLY' | 'BIWEEKLY' | 'MONTHLY' | 'BIMONTHLY' | 'QUARTERLY' | 'SEMIANNUALLY' | 'YEARLY';
  allowInstallments: boolean;
  maxInstallments: number;
}

export interface AsaasConfig {
  useDynamicPricing?: boolean; // Se true, IA usa valores do prompt ao invés de produtos fixos
  products: AsaasProduct[];
  billingTypes: ('PIX' | 'CREDIT_CARD' | 'BOLETO')[];
  defaultDueDays: number;
  autoCollection?: AutoCollectionConfig;
}

// ============================================================================
// AUTO COLLECTION CONFIG (Cobrança Automática)
// ============================================================================

export interface AutoCollectionConfig {
  enabled: boolean;
  reminderDays: number[];           // Dias antes do vencimento para enviar lembrete (ex: [2] = D-2)
  onDueDate: boolean;               // Enviar aviso no dia do vencimento (D0)
  afterDue: {
    enabled: boolean;
    overdueDays?: number[];         // Dias específicos após vencer (ex: [1, 3] = D+1, D+3) - PREFERIDO
    intervalDays?: number;          // Fallback: cobrar a cada X dias após vencer
    maxAttempts: number;            // Máximo de tentativas de cobrança
  };
  sendTime?: string;                // Horário de envio (ex: "09:00") - job roda às 9h por padrão
  messages?: {
    reminderTemplate?: string;      // Template de lembrete (suporta {{nome}}, {{valor}}, {{vencimento}}, {{link}})
    dueDateTemplate?: string;       // Template do dia do vencimento
    overdueTemplate?: string;       // Template após vencer (suporta {{dias_atraso}})
  };
}

// ============================================================================
// AGENT CONFIG
// ============================================================================

export interface AgentConfig {
  id: string;
  organization_id: string;
  agent_name: string;
  company_name: string | null;
  product_name: string | null;
  product_price: number | null;
  product_description: string | null;
  system_prompt: string | null;
  follow_up_prompt: string | null;
  qualification_prompt: string | null;
  work_hours_start: number;
  work_hours_end: number;
  timezone: string;
  session_duration: number;
  break_between_sessions: number;
  message_buffer_delay: number;
  max_follow_ups: number;
  created_at: string;
  updated_at: string;
}

export interface AgentConfigCreate {
  organization_id: string;
  agent_name?: string;
  company_name?: string | null;
  product_name?: string | null;
  product_price?: number | null;
  product_description?: string | null;
  system_prompt?: string | null;
  follow_up_prompt?: string | null;
  qualification_prompt?: string | null;
  work_hours_start?: number;
  work_hours_end?: number;
  timezone?: string;
  session_duration?: number;
  break_between_sessions?: number;
  message_buffer_delay?: number;
  max_follow_ups?: number;
}

export interface AgentConfigUpdate {
  agent_name?: string;
  company_name?: string | null;
  product_name?: string | null;
  product_price?: number | null;
  product_description?: string | null;
  system_prompt?: string | null;
  follow_up_prompt?: string | null;
  qualification_prompt?: string | null;
  work_hours_start?: number;
  work_hours_end?: number;
  timezone?: string;
  session_duration?: number;
  break_between_sessions?: number;
  message_buffer_delay?: number;
  max_follow_ups?: number;
}

// ============================================================================
// DEPARTMENT
// ============================================================================

export interface Department {
  id: string;
  organization_id: string;
  name: string;
  queue_id: number;
  is_ai_enabled: boolean;
  created_at: string;
}

export interface DepartmentCreate {
  organization_id: string;
  name: string;
  queue_id: number;
  is_ai_enabled?: boolean;
}

export interface DepartmentUpdate {
  name?: string;
  queue_id?: number;
  is_ai_enabled?: boolean;
}

// ============================================================================
// LEAD
// ============================================================================

export interface Lead {
  id: string;
  organization_id: string;
  remote_jid: string;
  nome: string | null;
  name?: string | null; // Alias para nome
  telefone: string | null;
  phone?: string | null; // Alias para telefone
  email: string | null;
  empresa: string | null;
  company?: string | null; // Alias para empresa
  cpf_cnpj?: string | null;
  lead_origin: string;
  diana_prospect_id: string | null;
  ad_url: string | null;
  pacote: string | null;
  valor: number | null;
  pipeline_step: string;
  status: LeadStatus;
  current_state?: string | null;
  conversation_summary?: string | null;
  asaas_customer_id?: string | null;
  bant_budget: number;
  bant_authority: number;
  bant_need: number;
  bant_timing: number;
  bant_total: number;
  fit_porte: number;
  fit_volume_whatsapp: number;
  fit_maturidade_digital: number;
  fit_potencial_crescimento: number;
  fit_total: number;
  responsavel: string;
  ultimo_intent: string | null;
  resumo: string | null;
  atendimento_finalizado: boolean;
  department_id: string | null;
  follow_01: boolean;
  follow_02: boolean;
  follow_03: boolean;
  follow_04: boolean;
  follow_05: boolean;
  follow_06: boolean;
  follow_07: boolean;
  follow_08: boolean;
  follow_09: boolean;
  follow_count: number;
  created_at: string;
  updated_at: string;

  // Campos Diana Campaigns (quando lead vem da prospecção)
  diana_lead_id?: string | null;
  diana_campanha_id?: string | null;
  diana_score?: number | null;
  diana_temperatura?: string | null;
  diana_dores?: string[] | null;
  diana_interesses?: string[] | null;
  diana_objecoes?: string[] | null;
  diana_historico_validacao?: any[] | null;
  diana_historico_qualificacao?: any[] | null;
  diana_resumo_jornada?: string | null;
  observacoes?: string | null;
  origem?: string | null;
  cargo?: string | null;
  cidade?: string | null;
  nicho?: string | null;
  estado?: string | null;
  timezone?: string | null;  // Ex: 'America/Sao_Paulo', 'America/Cuiaba'
}

export interface LeadCreate {
  organization_id: string;
  remote_jid: string;
  nome?: string | null;
  telefone?: string | null;
  email?: string | null;
  empresa?: string | null;
  lead_origin?: string;
  diana_prospect_id?: string | null;
  ad_url?: string | null;
  pacote?: string | null;
  valor?: number | null;
  pipeline_step?: string;
  status?: LeadStatus;
  bant_budget?: number;
  bant_authority?: number;
  bant_need?: number;
  bant_timing?: number;
  fit_porte?: number;
  fit_volume_whatsapp?: number;
  fit_maturidade_digital?: number;
  fit_potencial_crescimento?: number;
  responsavel?: string;
  ultimo_intent?: string | null;
  resumo?: string | null;
  atendimento_finalizado?: boolean;
  department_id?: string | null;
}

export interface LeadUpdate {
  nome?: string | null;
  telefone?: string | null;
  email?: string | null;
  empresa?: string | null;
  lead_origin?: string;
  diana_prospect_id?: string | null;
  ad_url?: string | null;
  pacote?: string | null;
  valor?: number | null;
  pipeline_step?: string;
  status?: LeadStatus;
  bant_budget?: number;
  bant_authority?: number;
  bant_need?: number;
  bant_timing?: number;
  fit_porte?: number;
  fit_volume_whatsapp?: number;
  fit_maturidade_digital?: number;
  fit_potencial_crescimento?: number;
  responsavel?: string;
  ultimo_intent?: string | null;
  resumo?: string | null;
  atendimento_finalizado?: boolean;
  department_id?: string | null;
  follow_01?: boolean;
  follow_02?: boolean;
  follow_03?: boolean;
  follow_04?: boolean;
  follow_05?: boolean;
  follow_06?: boolean;
  follow_07?: boolean;
  follow_08?: boolean;
  follow_09?: boolean;
  follow_count?: number;
  cidade?: string | null;
  estado?: string | null;
  timezone?: string | null;  // Ex: 'America/Sao_Paulo', 'America/Cuiaba'
}

// ============================================================================
// MESSAGE
// ============================================================================

export interface MessageContent {
  text?: string;
  caption?: string;
  url?: string;
  mimetype?: string;
  filename?: string;
  latitude?: number;
  longitude?: number;
  [key: string]: unknown;
}

export interface Message {
  id: string;
  organization_id: string;
  lead_id: string;
  remote_jid: string;
  role: MessageRole;
  content: MessageContent;
  message_type: MessageType | null;
  function_name: string | null;
  function_result: Record<string, unknown> | null;
  created_at: string;
}

export interface MessageCreate {
  organization_id: string;
  lead_id: string;
  remote_jid: string;
  role: MessageRole;
  content: MessageContent;
  message_type?: MessageType | null;
  function_name?: string | null;
  function_result?: Record<string, unknown> | null;
}

// ============================================================================
// MESSAGE BUFFER
// ============================================================================

export interface FileData {
  url?: string;
  mimetype?: string;
  filename?: string;
  base64?: string;
  [key: string]: unknown;
}

export interface MessageBuffer {
  id: string;
  organization_id: string;
  remote_jid: string;
  content: string;
  message_type: string;
  file_data: FileData | null;
  created_at: string;
}

export interface MessageBufferCreate {
  organization_id: string;
  remote_jid: string;
  content: string;
  message_type?: string;
  file_data?: FileData | null;
}

// ============================================================================
// SCHEDULE
// ============================================================================

export interface Schedule {
  id: string;
  organization_id: string;
  agent_id: string;
  lead_id: string;
  remote_jid: string;
  google_event_id: string | null;
  customer_name: string | null;
  company_name: string | null;
  scheduled_at: string;
  ends_at: string;
  timezone: string;
  status: ScheduleStatus;
  created_at: string;
  // Campos de confirmacao de agendamento
  confirmation_sent_at: string | null;
  confirmation_response: string | null;
  confirmation_response_at: string | null;
  last_reminder_type: '24h' | '2h' | null;
  awaiting_confirmation: boolean;
  reminder_count: number;
  // Link da reunião (Google Meet ou outro)
  meeting_link: string | null;
  // Serviço agendado
  service_id: string | null;
  service_name: string | null;
}

export interface ScheduleCreate {
  organization_id: string;
  lead_id: string;
  remote_jid: string;
  google_event_id?: string | null;
  customer_name?: string | null;
  company_name?: string | null;
  scheduled_at: string;
  ends_at: string;
  timezone?: string;
  status?: ScheduleStatus;
  service_id?: string | null;
  service_name?: string | null;
  meeting_link?: string | null;
  notes?: string | null;
}

export interface ScheduleUpdate {
  google_event_id?: string | null;
  customer_name?: string | null;
  company_name?: string | null;
  scheduled_at?: string;
  ends_at?: string;
  timezone?: string;
  status?: ScheduleStatus;
  service_id?: string | null;
  service_name?: string | null;
}

// ============================================================================
// PAYMENT
// ============================================================================

export interface Payment {
  id: string;
  organization_id: string;
  lead_id: string;
  remote_jid: string | null;
  asaas_customer_id: string | null;
  asaas_subscription_id: string | null;
  asaas_payment_link_id: string | null;
  asaas_payment_id: string | null;
  payment_link_url: string | null;
  payment_link: string | null;
  payment_method: string | null;
  due_date: string | null;
  amount: number | null;
  status: PaymentStatus | string;
  created_at: string;
  paid_at: string | null;
}

export interface PaymentCreate {
  organization_id?: string;
  lead_id: string;
  remote_jid?: string | null;
  asaas_customer_id?: string | null;
  asaas_subscription_id?: string | null;
  asaas_payment_link_id?: string | null;
  asaas_payment_id?: string | null;
  payment_link_url?: string | null;
  payment_link?: string | null;
  payment_method?: string | null;
  due_date?: string | null;
  amount?: number | null;
  status?: PaymentStatus | string;
}

export interface PaymentUpdate {
  asaas_customer_id?: string | null;
  asaas_subscription_id?: string | null;
  asaas_payment_link_id?: string | null;
  asaas_payment_id?: string | null;
  payment_link_url?: string | null;
  payment_link?: string | null;
  payment_method?: string | null;
  due_date?: string | null;
  amount?: number | null;
  status?: PaymentStatus | string;
  paid_at?: string | null;
}

// ============================================================================
// DATABASE TYPES (para uso com Supabase)
// ============================================================================

export interface Database {
  public: {
    Tables: {
      organizations: {
        Row: Organization;
        Insert: OrganizationCreate;
        Update: OrganizationUpdate;
      };
      users: {
        Row: User;
        Insert: UserCreate;
        Update: UserUpdate;
      };
      integrations: {
        Row: Integration;
        Insert: IntegrationCreate;
        Update: IntegrationUpdate;
      };
      agent_config: {
        Row: AgentConfig;
        Insert: AgentConfigCreate;
        Update: AgentConfigUpdate;
      };
      departments: {
        Row: Department;
        Insert: DepartmentCreate;
        Update: DepartmentUpdate;
      };
      leads: {
        Row: Lead;
        Insert: LeadCreate;
        Update: LeadUpdate;
      };
      messages: {
        Row: Message;
        Insert: MessageCreate;
        Update: never;
      };
      message_buffer: {
        Row: MessageBuffer;
        Insert: MessageBufferCreate;
        Update: never;
      };
      schedules: {
        Row: Schedule;
        Insert: ScheduleCreate;
        Update: ScheduleUpdate;
      };
      payments: {
        Row: Payment;
        Insert: PaymentCreate;
        Update: PaymentUpdate;
      };
      agents: {
        Row: Agent;
        Insert: AgentCreate;
        Update: AgentUpdate;
      };
    };
  };
}

// ============================================================================
// LEADBOX USER (tabela users - autenticacao Google)
// ============================================================================

export interface LeadboxUser {
  id: string;
  email: string;
  name: string | null;
  avatar_url: string | null;
  google_id: string;
  created_at: string;
  last_login: string;
}

export interface LeadboxUserCreate {
  email: string;
  name?: string | null;
  avatar_url?: string | null;
  google_id: string;
}

export interface LeadboxUserUpdate {
  email?: string;
  name?: string | null;
  avatar_url?: string | null;
  last_login?: string;
}

// ============================================================================
// AGENT (tabela agents)
// ============================================================================

export type AgentStatus = 'active' | 'paused' | 'creating';
export type WhatsAppProvider = 'uazapi' | 'evolution';
export type AgentType = 'SDR' | 'FOLLOWUP' | 'SUPPORT' | 'CUSTOM' | 'DIANA';
export type AIProvider = 'gemini' | 'claude' | 'openai';
export type ResponseSize = 'short' | 'medium' | 'long';

/**
 * Modo de quebra de mensagens:
 * - 'smart': Quebra inteligente por tamanho (padrão atual)
 * - 'paragraph': Quebra primeiro por parágrafos (\n\n), depois por tamanho se necessário
 * - 'natural': Quebra por parágrafos com tamanho menor (~300 chars) para parecer mais humanizado
 */
export type SplitMode = 'smart' | 'paragraph' | 'natural';

export interface PipelineStage {
  order: number;
  name: string;
  slug: string;
  icon: string;
  color: string;
  description_for_ai: string;
}

export interface BusinessHours {
  start: string;
  end: string;
}

// Follow-up Configuration Types

/**
 * Configuração de um único step de follow-up
 */
// Personalidades disponíveis para follow-up com IA
export type FollowUpPersonality =
  | 'amigavel'      // Friendly, casual tone like a friend reminding you
  | 'profissional'  // Formal, corporate, direct approach
  | 'persuasivo'    // Highlights benefits and results
  | 'urgente'       // Creates sense of urgency, limited time
  | 'curioso'       // Asks questions to re-engage conversation
  | 'despedida';    // Final respectful contact, no pressure

export interface FollowUpStep {
  id?: number;                       // ID do step (opcional para compatibilidade)
  delayMinutes: number;              // Tempo de espera em minutos antes de enviar
  delayValue?: number;               // Valor numérico do delay (ex: 1, 2, 24)
  delayUnit?: 'minutes' | 'hours' | 'days';
  useAI: boolean;                    // true = IA gera a mensagem, false = usa mensagem fixa
  message?: string;                  // Mensagem fixa (usada se useAI = false) - tornada opcional
  prompt?: string;                   // Prompt customizado para IA (quando useAI = true)
  personality?: FollowUpPersonality; // Personalidade da mensagem AI (usado quando useAI = true)
}

export interface FollowUpInactivityConfig {
  enabled: boolean;
  delays: number[];                    // em minutos (mantido para compatibilidade)
  messages: string[];                  // mensagens customizadas (mantido para compatibilidade)
  personalities?: FollowUpPersonality[]; // personalidades para cada step (usado com IA)
  steps?: FollowUpStep[];              // Nova estrutura mais detalhada (opcional)
}

export interface FollowUpNurtureConfig {
  enabled: boolean;
  delays: number[];         // em minutos
  messages: string[];
  steps?: FollowUpStep[];   // Nova estrutura mais detalhada (opcional)
}

export interface FollowUpReminderConfig {
  enabled: boolean;
  minutesBefore: number;
  useAI?: boolean;          // true = IA gera o lembrete, false = usa mensagem fixa
  message?: string;         // Mensagem fixa para o lembrete
}

/**
 * Configuração de limites de rate limiting para follow-ups.
 * Todos os campos são opcionais - se não definidos, usa defaults.
 *
 * Defaults:
 * - maxFollowUpsPerDay: 50
 * - maxFollowUpsPerLead: 4
 * - minIntervalBetweenMessages: 60 (minutos)
 * - silenceWindowAfterNegative: 168 (horas = 7 dias)
 * - cooldownAfterNoResponse: 1440 (minutos = 24h)
 */
export interface FollowUpLimits {
  maxFollowUpsPerDay?: number;           // Máximo de follow-ups por dia (por agente)
  maxFollowUpsPerLead?: number;          // Máximo de follow-ups por lead (total)
  minIntervalBetweenMessages?: number;   // Intervalo mínimo entre mensagens (minutos)
  silenceWindowAfterNegative?: number;   // Silêncio após resposta negativa (horas)
  cooldownAfterNoResponse?: number;      // Espera após não resposta (minutos)
}

export interface FollowUpConfig {
  inactivity: FollowUpInactivityConfig;
  nurture: FollowUpNurtureConfig;
  reminder: FollowUpReminderConfig;
  limits?: FollowUpLimits;  // Limites de rate limiting (opcional)
}

// ============================================================================
// SALVADOR MULTI-AGENT FOLLOW-UP CONFIG (V2)
// ============================================================================

/**
 * Configuração de um único step de follow-up com prompt customizado (V2)
 */
export interface FollowUpStepV2 {
  id: number;
  delayMinutes: number;              // Delay total em minutos (calculado)
  delayValue: number;                // Valor numérico do delay (ex: 1, 2, 24)
  delayUnit: 'minutes' | 'hours' | 'days';
  useAI: boolean;
  message?: string;                  // Mensagem fixa (quando useAI=false)
  prompt?: string;                   // Prompt customizado para IA (quando useAI=true)
  personality?: FollowUpPersonality; // Personalidade complementar ao prompt
}

/**
 * Configuração de follow-up para um agente específico
 */
export interface PerAgentFollowUpConfig {
  enabled: boolean;
  maxFollowUps: number;
  silenceWindowHours?: number;       // Horas de silêncio após resposta negativa
  steps: FollowUpStepV2[];
}

/**
 * Configuração global do Salvador para múltiplos agentes
 * Armazenado no campo `salvador_config` JSONB da tabela agents
 */
export interface SalvadorMultiAgentConfig {
  global: {
    workHoursStart: string;          // "08:00"
    workHoursEnd: string;            // "18:00"
    workDays: string[];              // ["monday", "tuesday", ...]
  };
  agents: {
    [agentId: string]: PerAgentFollowUpConfig;
  };
}

// Qualification (BANT/FIT) Configuration Types
export interface BANTCriteria {
  budget: string;
  authority: string;
  need: string;
  timing: string;
}

export interface FITCriteria {
  companySize: string;
  industry: string;
  digitalMaturity: string;
}

// Interface para controlar quais critérios BANT estão habilitados
export interface BANTEnabled {
  budget: boolean;    // Orçamento
  authority: boolean; // Autoridade/Decisor
  need: boolean;      // Necessidade
  timing: boolean;    // Prazo/Urgência
}

export interface QualificationConfig {
  qualifyAfterMessages: number;
  bantCriteria: BANTCriteria;
  fitCriteria: FITCriteria;
  hotLeadThreshold: number; // 0-100
  warmLeadThreshold: number; // 0-100
  spinSellingEnabled?: boolean; // Se true, bloqueia apresentacao ate qualificar (default: true)
  bantEnabled?: BANTEnabled; // Controla quais critérios BANT estão ativos (default: todos ativos)
}

// Schedule Confirmation Configuration Types
export interface ScheduleConfirmationInterval {
  minutesBefore: number;  // 1440 = 24h, 120 = 2h
  enabled: boolean;
  messageTemplate: string | null;  // null = usar mensagem padrao
}

export interface ScheduleConfirmationConfig {
  intervals: ScheduleConfirmationInterval[];
  positiveKeywords: string[];
  negativeKeywords: string[];
  rescheduleKeywords: string[];
  defaultConfirmationMessage24h: string;
  defaultConfirmationMessage2h: string;
  confirmationResponseMessage: string;
  cancellationResponseMessage: string;
  rescheduleResponseMessage: string;
  awaitingResponseTimeout: number;  // minutos para considerar timeout
  maxReminders: number;
}

// ============================================================================
// CONTEXT PROMPTS
// ============================================================================

export interface ContextPrompt {
  nome: string;
  descricao?: string;
  prompt: string;
  ativo: boolean;
}

export interface Agent {
  id: string;
  user_id: string;
  name: string;
  status: AgentStatus;
  created_at: string;
  updated_at: string;
  // WhatsApp Provider
  whatsapp_provider: WhatsAppProvider;
  // UAZAPI fields
  uazapi_instance_id: string | null;
  uazapi_instance_name: string | null;
  uazapi_token: string | null;
  uazapi_base_url: string | null;
  uazapi_connected: boolean;
  // Evolution API fields
  evolution_instance_name: string | null;
  evolution_api_key: string | null;
  evolution_base_url: string | null;
  evolution_connected: boolean;
  // Dynamic tables
  table_leads: string;
  table_messages: string;
  table_msg_temp: string | null; // Tabela de buffer de mensagens (null para Salvador)
  // AI Config
  ai_provider: AIProvider;
  gemini_api_key: string | null;
  gemini_model: string;
  claude_api_key: string | null;
  claude_model: string;
  openai_api_key: string | null;
  openai_model: string;
  system_prompt: string | null;
  response_size: ResponseSize;
  split_messages: boolean;
  split_mode: SplitMode; // Modo de quebra: 'smart' | 'paragraph' | 'natural'
  max_chars_per_message: number;
  message_buffer_delay: number; // Delay em ms para aguardar mais mensagens (padrão: 9000)
  // Recording Simulation (mostrar "gravando áudio..." antes de enviar áudios)
  recording_simulation: boolean; // Se true, mostra "gravando..." antes de enviar áudios (padrão: true)
  recording_delay: number; // Delay em ms para mostrar "gravando..." antes de enviar (padrão: 15000 = 15 segundos)
  // Google Calendar
  google_calendar_enabled: boolean;
  google_credentials: GoogleCredentials | null;
  google_calendar_id: string;
  google_accounts: Array<{
    email: string;
    credentials: unknown;
    calendar_id: string;
    // Configuracoes de horario por agenda
    work_days?: { seg: boolean; ter: boolean; qua: boolean; qui: boolean; sex: boolean; sab: boolean; dom: boolean };
    morning_enabled?: boolean;
    morning_start?: string;
    morning_end?: string;
    afternoon_enabled?: boolean;
    afternoon_start?: string;
    afternoon_end?: string;
    // Duracao da reuniao em minutos (15, 30, 45 ou 60). Default: 60
    meeting_duration?: number;
  }> | null;
  // Asaas Payments
  asaas_enabled: boolean;
  asaas_api_key: string | null;
  asaas_environment: AsaasEnvironment;
  asaas_config: AsaasConfig | null;
  // Product Info
  product_description: string | null;
  product_value: number | null;
  // Business Config
  business_hours: BusinessHours;
  work_days: string[];
  meeting_duration: number;
  timezone: string;
  pipeline_stages: PipelineStage[];
  // Follow-up Config
  follow_up_enabled: boolean;
  follow_up_config: FollowUpConfig | null;
  // Qualification Config
  qualification_enabled: boolean;
  qualification_config: QualificationConfig | null;
  // Schedule Confirmation Config
  schedule_confirmation_enabled: boolean;
  schedule_confirmation_config: ScheduleConfirmationConfig | null;
  // Agent Type
  agent_type: AgentType;
  type?: 'agnes' | 'salvador' | 'diana'; // Type of agent (agnes=SDR, salvador=follow-up, diana=prospection)
  // Shared WhatsApp
  parent_agent_id: string | null;
  uses_shared_whatsapp: boolean;
  // Notifications
  owner_phone: string | null;
  last_quota_alert: string | null;
  // Location (for send_location tool)
  location_latitude: number | null;
  location_longitude: number | null;
  location_name: string | null;
  location_address: string | null;
  // CRM Ghost Config (legacy - coluna mantida no banco)
  crm_ghost_config: Record<string, any> | null;
  // Structured Prompt (nova estrutura de 4 blocos)
  // Se true, usa o PromptBuilder com Security + AgentPrompt + Context + Tools
  // Se false (default), usa system_prompt direto sem modificações
  use_structured_prompt?: boolean;
  // AI Temperature (0.1 = preciso, 1.0 = criativo)
  // Default: 0.4 - Recomendado para atendimento: 0.3-0.5
  ai_temperature?: number;
  // AI Temperature para conversação (usado na resposta final, após tools)
  // Default: usa ai_temperature. Valores mais altos (0.7-1.0) = respostas mais naturais
  ai_temperature_conversation?: number;
  // Servicos/Procedimentos configurados
  services: Array<{
    name: string;
    duration: number;
    isDefault?: boolean;
  }> | null;
  // Titulo e descricao padrao para reunioes
  meeting_title: string | null;
  meeting_description: string | null;
  // RAG (Base de Conhecimento)
  rag_enabled: boolean;
  // Handoff/Leadbox Integration
  // A IA lê queueId/userId do prompt, não precisa de departments no config
  handoff_triggers: {
    enabled: boolean;
    type: string; // 'leadbox' ou 'leadbox_api'
    api_url: string; // Ex: https://enterprise-135api.leadbox.app.br
    api_uuid: string; // UUID da API externa do Leadbox
    api_token: string; // Bearer token para autenticação
    // Campos opcionais para sincronização de status
    ia_queue_id?: number; // ID do departamento da IA (para reativar quando ticket voltar)
    ia_user_id?: number;  // ID do usuário da IA
    default_user_id?: number; // @deprecated - use ia_user_id
    // @deprecated - departments não é mais necessário, a IA lê do prompt
    departments?: Record<string, { id: number; name: string; keywords?: string[]; userId?: number }>;
  } | null;

  // Configurações do Salvador (editáveis no frontend)
  salvador_prompt?: string | null;
  salvador_follow_count?: number | null;
  salvador_delays?: number[] | null;
  // Observer AI Prompt (analisa conversas em segundo plano)
  observer_prompt?: string | null;

  // Horário comercial configurável (para cálculo de "leads fora do horário")
  commercial_start_hour?: number | null;
  commercial_end_hour?: number | null;

  // Prompts dinâmicos por contexto (cobrança, manutenção, etc)
  context_prompts?: Record<string, ContextPrompt> | null;
}

export interface AgentCreate {
  user_id: string;
  name: string;
  status?: AgentStatus;
  // WhatsApp Provider
  whatsapp_provider?: WhatsAppProvider;
  // UAZAPI fields
  uazapi_instance_id?: string | null;
  uazapi_instance_name?: string | null;
  uazapi_token?: string | null;
  uazapi_base_url?: string | null;
  uazapi_connected?: boolean;
  // Evolution API fields
  evolution_instance_name?: string | null;
  evolution_api_key?: string | null;
  evolution_base_url?: string | null;
  evolution_connected?: boolean;
  // Dynamic tables
  table_leads: string;
  table_messages: string;
  table_msg_temp?: string | null; // Tabela de buffer de mensagens (null para Salvador)
  // AI Config
  ai_provider?: AIProvider;
  gemini_api_key?: string | null;
  gemini_model?: string;
  claude_api_key?: string | null;
  claude_model?: string;
  openai_api_key?: string | null;
  openai_model?: string;
  system_prompt?: string | null;
  response_size?: ResponseSize;
  split_messages?: boolean;
  split_mode?: SplitMode;
  max_chars_per_message?: number;
  message_buffer_delay?: number;
  // Recording Simulation
  recording_simulation?: boolean;
  recording_delay?: number;
  // Google Calendar
  google_calendar_enabled?: boolean;
  google_credentials?: GoogleCredentials | null;
  google_calendar_id?: string;
  google_accounts?: Array<{
    email: string;
    credentials: unknown;
    calendar_id: string;
    // Configuracoes de horario por agenda
    work_days?: { seg: boolean; ter: boolean; qua: boolean; qui: boolean; sex: boolean; sab: boolean; dom: boolean };
    morning_enabled?: boolean;
    morning_start?: string;
    morning_end?: string;
    afternoon_enabled?: boolean;
    afternoon_start?: string;
    afternoon_end?: string;
    // Duracao da reuniao em minutos (15, 30, 45 ou 60). Default: 60
    meeting_duration?: number;
  }> | null;
  // Asaas Payments
  asaas_enabled?: boolean;
  asaas_api_key?: string | null;
  asaas_environment?: AsaasEnvironment;
  asaas_config?: AsaasConfig | null;
  // Product Info
  product_description?: string | null;
  product_value?: number | null;
  // Business Config
  business_hours?: BusinessHours;
  work_days?: string[];
  meeting_duration?: number;
  timezone?: string;
  pipeline_stages?: PipelineStage[];
  // Follow-up Config
  follow_up_enabled?: boolean;
  follow_up_config?: FollowUpConfig | null;
  // Qualification Config
  qualification_enabled?: boolean;
  qualification_config?: QualificationConfig | null;
  // Agent Type
  agent_type?: AgentType;
  // Shared WhatsApp
  parent_agent_id?: string | null;
  uses_shared_whatsapp?: boolean;
  // Notifications
  owner_phone?: string | null;
  // Diana Prospection Fields
  type?: 'agnes' | 'salvador' | 'diana';
  google_places_api_key?: string | null;
  diana_company_name?: string | null;
  diana_company_description?: string | null;
  diana_agent_name?: string | null;
  prospection_niche?: string | null;
  prospection_niche_custom?: string | null;
  prospection_location_type?: 'state' | 'city' | 'both';
  prospection_state?: string | null;
  prospection_city?: string | null;
  prospection_strategy?: string;
  prospection_daily_goal?: number;
  prospection_sequence?: Array<{
    id: number;
    day: number;
    useAI: boolean;
    strategy: string;
    message: string;
  }>;
  // Prompt Medias (audio, imagem, video)
  prompt_medias?: Array<{
    id: string;
    type: 'audio' | 'image' | 'video';
    identifier: string;
    name: string;
    url: string | null;
    size?: number;
    mime_type?: string;
    created_at?: string;
  }>;
  // Schedule Confirmation Config
  schedule_confirmation_enabled?: boolean;
  schedule_confirmation_config?: ScheduleConfirmationConfig | null;
  // Location (for send_location tool)
  location_latitude?: number | null;
  location_longitude?: number | null;
  location_name?: string | null;
  location_address?: string | null;
  // CRM Ghost Config
  crm_ghost_config?: Record<string, any> | null;
  // AI Temperature
  ai_temperature?: number;
  ai_temperature_conversation?: number;
  // Servicos/Procedimentos configurados
  services?: Array<{
    name: string;
    duration: number;
    isDefault?: boolean;
  }>;
  // Titulo e descricao padrao para reunioes
  meeting_title?: string | null;
  meeting_description?: string | null;
  // RAG (Base de Conhecimento)
  rag_enabled?: boolean;
  // Leadbox Handoff
  handoff_triggers?: Record<string, unknown> | null;
  handoff_enabled?: boolean;
  // Observer AI Prompt
  observer_prompt?: string | null;
  // Horário comercial configurável
  commercial_start_hour?: number | null;
  commercial_end_hour?: number | null;
}

export interface AgentUpdate {
  name?: string;
  status?: AgentStatus;
  // WhatsApp Provider
  whatsapp_provider?: WhatsAppProvider;
  // UAZAPI fields
  uazapi_instance_id?: string | null;
  uazapi_instance_name?: string | null;
  uazapi_token?: string | null;
  uazapi_base_url?: string | null;
  uazapi_connected?: boolean;
  // Evolution API fields
  evolution_instance_name?: string | null;
  evolution_api_key?: string | null;
  evolution_base_url?: string | null;
  evolution_connected?: boolean;
  // Dynamic tables
  table_leads?: string;
  table_messages?: string;
  table_msg_temp?: string | null; // Tabela de buffer de mensagens (null para Salvador)
  // AI Config
  ai_provider?: AIProvider;
  gemini_api_key?: string | null;
  gemini_model?: string;
  claude_api_key?: string | null;
  claude_model?: string;
  openai_api_key?: string | null;
  openai_model?: string;
  system_prompt?: string | null;
  response_size?: ResponseSize;
  split_messages?: boolean;
  split_mode?: SplitMode;
  max_chars_per_message?: number;
  message_buffer_delay?: number;
  // Recording Simulation
  recording_simulation?: boolean;
  recording_delay?: number;
  // Google Calendar
  google_calendar_enabled?: boolean;
  google_credentials?: GoogleCredentials | null;
  google_calendar_id?: string;
  google_accounts?: Array<{
    email: string;
    credentials: unknown;
    calendar_id: string;
    // Configuracoes de horario por agenda
    work_days?: { seg: boolean; ter: boolean; qua: boolean; qui: boolean; sex: boolean; sab: boolean; dom: boolean };
    morning_enabled?: boolean;
    morning_start?: string;
    morning_end?: string;
    afternoon_enabled?: boolean;
    afternoon_start?: string;
    afternoon_end?: string;
    // Duracao da reuniao em minutos (15, 30, 45 ou 60). Default: 60
    meeting_duration?: number;
  }> | null;
  // Asaas Payments
  asaas_enabled?: boolean;
  asaas_api_key?: string | null;
  asaas_environment?: AsaasEnvironment;
  asaas_config?: AsaasConfig | null;
  // Product Info
  product_description?: string | null;
  product_value?: number | null;
  // Business Config
  business_hours?: BusinessHours;
  work_days?: string[];
  meeting_duration?: number;
  timezone?: string;
  pipeline_stages?: PipelineStage[];
  // Follow-up Config
  follow_up_enabled?: boolean;
  follow_up_config?: FollowUpConfig | null;
  // Qualification Config
  qualification_enabled?: boolean;
  qualification_config?: QualificationConfig | null;
  // Notifications
  owner_phone?: string | null;
  last_quota_alert?: string | null;
  // Schedule Confirmation Config
  schedule_confirmation_enabled?: boolean;
  schedule_confirmation_config?: ScheduleConfirmationConfig | null;
  // Location (for send_location tool)
  location_latitude?: number | null;
  location_longitude?: number | null;
  location_name?: string | null;
  location_address?: string | null;
  // CRM Ghost Config
  crm_ghost_config?: Record<string, any> | null;
  // AI Temperature
  ai_temperature?: number;
  ai_temperature_conversation?: number;
  // Servicos/Procedimentos configurados
  services?: Array<{
    name: string;
    duration: number;
    isDefault?: boolean;
  }>;
  // Titulo e descricao padrao para reunioes
  meeting_title?: string | null;
  meeting_description?: string | null;
  // RAG (Base de Conhecimento)
  rag_enabled?: boolean;
  // Observer AI Prompt
  observer_prompt?: string | null;
  // Horário comercial configurável
  commercial_start_hour?: number | null;
  commercial_end_hour?: number | null;
}

// ============================================================================
// DYNAMIC LEAD (tabelas LeadboxCRM_*)
// ============================================================================

export interface DynamicLead {
  id: number;
  nome: string | null;
  telefone: string | null;
  email: string | null;
  empresa: string | null;
  ad_url: string | null;
  pacote: string | null;
  resumo: string | null;
  pipeline_step: string;
  valor: number | null;
  status: string;
  close_date: string | null;
  lead_origin: string | null;
  diana_prospect_id: string | null;
  responsavel: string;
  remotejid: string | null;
  follow_count: number;
  updated_date: string;
  created_date: string;
  venda_realizada: string | null;
  Atendimento_Finalizado: string;
  // Follow_01-09 removidos (dead code - nunca usados)
  ultimo_intent: string | null;
  crm: string | null;
  // BANT qualification fields
  bant_budget: number | null;
  bant_authority: number | null;
  bant_need: number | null;
  bant_timing: number | null;
  bant_total: number | null;
  bant_notes: string | null;
  qualification_score: number | null;
  lead_temperature: string | null;
  // Opt-out de follow-up
  follow_up_opted_out: boolean | null;
  follow_up_opted_out_reason: string | null;
  follow_up_opted_out_at: string | null;
  // Localização e Timezone do lead
  cidade: string | null;
  estado: string | null;
  timezone: string | null;  // Ex: 'America/Sao_Paulo', 'America/Cuiaba'
  // Follow-up tracking
  follow_up_notes: string | null;
  last_follow_up_at: string | null;
  // Scheduling fields (synced from schedules table)
  next_appointment_at: string | null;
  next_appointment_link: string | null;
  last_scheduled_at: string | null;
  // Agent journey tracking
  attended_by: string | null;
  journey_stage: string | null;
  // Leadbox ticket tracking (for context detection)
  ticket_id?: number | null;
  current_queue_id?: number | null;
  current_user_id?: number | null;
  // Message tracking (for follow-up validation)
  last_lead_message_at?: string | null;
  last_user_message_at?: string | null;
  // Observer insights (AI-extracted data from conversations)
  insights?: {
    ad_urls?: string[];
    origin?: string;
    summary?: string;
    suggested_stage?: string;
    sentiment?: string;
    speakers?: {
      lead?: string;
      ai?: string;
      human?: { name: string; role?: string } | null;
    };
    current_handler?: 'ai' | 'human';
    last_speaker?: 'lead' | 'ai' | 'human';
    human_since?: string;
    auto_moved?: boolean;
    moved_reason?: string;
    updated_at?: string;
  } | null;
}

export interface DynamicLeadCreate {
  nome?: string | null;
  telefone?: string | null;
  email?: string | null;
  empresa?: string | null;
  ad_url?: string | null;
  pacote?: string | null;
  resumo?: string | null;
  pipeline_step?: string;
  valor?: number | null;
  status?: string;
  close_date?: string | null;
  lead_origin?: string | null;
  diana_prospect_id?: string | null;
  current_agent_id?: string | null;
  responsavel?: string;
  remotejid?: string | null;
  follow_count?: number;
  venda_realizada?: string | null;
  Atendimento_Finalizado?: string;
  ultimo_intent?: string | null;
  crm?: string | null;
}

export interface DynamicLeadUpdate {
  nome?: string | null;
  telefone?: string | null;
  email?: string | null;
  empresa?: string | null;
  ad_url?: string | null;
  pacote?: string | null;
  resumo?: string | null;
  pipeline_step?: string;
  valor?: number | null;
  status?: string;
  close_date?: string | null;
  lead_origin?: string | null;
  diana_prospect_id?: string | null;
  responsavel?: string;
  remotejid?: string | null;
  follow_count?: number;
  updated_date?: string;
  venda_realizada?: string | null;
  Atendimento_Finalizado?: string;
  // Follow_01-09 removidos (dead code)
  ultimo_intent?: string | null;
  crm?: string | null;
  // Opt-out de follow-up
  follow_up_opted_out?: boolean | null;
  follow_up_opted_out_reason?: string | null;
  follow_up_opted_out_at?: string | null;
  // Follow-up tracking
  follow_up_notes?: string | null;
  last_follow_up_at?: string | null;
  // Timezone detection
  cidade?: string | null;
  timezone?: string | null;
  // Conversation history sync
  conversation_history?: unknown | null;
  // Scheduling fields (synced from schedules table)
  next_appointment_at?: string | null;
  next_appointment_link?: string | null;
  last_scheduled_at?: string | null;
  // Agent journey tracking
  attended_by?: string | null;
  journey_stage?: string | null;
  // Handoff fields (human handoff tracking)
  current_state?: string | null;
  handoff_reason?: string | null;
  handoff_priority?: string | null;
  handoff_department?: string | null;
  handoff_at?: string | null;
  pausar_ia?: boolean | null;
  // Observacoes (notes)
  observacoes?: string | null;
  // Observer insights
  insights?: Record<string, unknown> | null;
}

// ============================================================================
// LEAD MESSAGE (tabelas leadbox_messages_*)
// ============================================================================

export interface LeadMessage {
  id: string;
  creat: string;
  remotejid: string;
  conversation_history: unknown | null;
  Msg_model: string | null;
  Msg_user: string | null;
}

export interface LeadMessageCreate {
  remotejid: string;
  conversation_history?: unknown | null;
  Msg_model?: string | null;
  Msg_user?: string | null;
}

export interface LeadMessageUpdate {
  conversation_history?: unknown | null;
  Msg_model?: string | null;
  Msg_user?: string | null;
}

// ============================================================================
// CONTROLE (tabelas Controle_*)
// ============================================================================

export interface Controle {
  id: number;
  created_at: string;
  Agendamentos: string | null;
  remotejid: string | null;
  link_pagamento: string | null;
  nome: string | null;
  update_date: string | null;
  empressa_name: string | null;
}

export interface ControleCreate {
  Agendamentos?: string | null;
  remotejid?: string | null;
  link_pagamento?: string | null;
  nome?: string | null;
  empressa_name?: string | null;
}

export interface ControleUpdate {
  Agendamentos?: string | null;
  remotejid?: string | null;
  link_pagamento?: string | null;
  nome?: string | null;
  update_date?: string | null;
  empressa_name?: string | null;
}

// ============================================================================
// FOLLOW-UP HISTORY (tabela follow_up_history)
// Rastreia todos os follow-ups enviados para métricas e análise
// ============================================================================

export interface FollowUpHistory {
  id: string;

  // Relacionamentos
  agent_id: string;
  parent_agent_id: string | null;
  lead_id: number;
  table_leads: string;
  remotejid: string;

  // Dados do follow-up
  step_number: number;
  follow_up_type: 'inactivity' | 'nurture' | 'reminder';
  personality: FollowUpPersonality | null;

  // Mensagem enviada
  message_sent: string;
  prompt_context: string | null;

  // Contexto do lead no momento do envio
  lead_name: string | null;
  pipeline_step: string | null;
  bant_score: number | null;
  sentiment: string | null;
  days_without_interaction: number | null;

  // Timestamps
  scheduled_at: string | null;
  sent_at: string;

  // Resposta do lead
  lead_responded: boolean;
  responded_at: string | null;
  response_time_minutes: number | null;
  response_message: string | null;

  // Conversão
  converted: boolean;
  converted_at: string | null;
  conversion_type: 'agendamento' | 'venda' | 'reengajamento' | null;

  // Metadata
  created_at: string;
}

export interface FollowUpHistoryCreate {
  agent_id: string;
  parent_agent_id?: string | null;
  lead_id: number;  // Required - Diana leads (UUID) skip logging entirely
  table_leads: string;
  remotejid: string;
  step_number: number;
  follow_up_type?: 'inactivity' | 'nurture' | 'reminder';
  personality?: FollowUpPersonality | null;
  message_sent: string;
  prompt_context?: string | null;
  lead_name?: string | null;
  pipeline_step?: string | null;
  bant_score?: number | null;
  sentiment?: string | null;
  days_without_interaction?: number | null;
  scheduled_at?: string | null;
}

export interface FollowUpMetrics {
  // Métricas de LEADS únicos (mais importantes)
  totalLeads: number;           // Leads únicos que receberam follow-up
  leadsReengajados: number;     // Leads únicos que responderam
  taxaReengajamento: number;    // % de leads que responderam
  // Métricas de FOLLOW-UPS (mensagens)
  totalSent: number;            // Total de follow-ups enviados
  totalResponded: number;       // Total de follow-ups com resposta
  responseRate: number;         // % de follow-ups com resposta
  avgResponseTimeMinutes: number;
  byStep: Array<{
    step: number;
    sent: number;
    responded: number;
    rate: number;
  }>;
}

// ============================================================================
// SERVICES (serviços/produtos oferecidos pelo agente)
// ============================================================================

export interface AgentService {
  id: string;
  name: string;
  category?: string;
  price?: number;
  description?: string;
}

// ============================================================================
// CONTRACT DETAILS (tabela contract_details - contratos de locação Lázaro)
// ============================================================================

export type MaintenanceStatus = 'pending' | 'notified' | 'contacted' | 'scheduled' | 'completed' | 'skipped';

export interface ContractEquipment {
  marca?: string;
  modelo?: string;
  btus?: number | string;
  patrimonio?: string;
  tipo?: string;
}

export interface ContractDetails {
  id: string;
  agent_id: string;
  subscription_id: string;
  customer_id: string;
  payment_id: string | null;
  document_id: string | null;
  numero_contrato: string | null;
  locatario_nome: string | null;
  locatario_cpf_cnpj: string | null;
  locatario_telefone: string | null;
  locatario_endereco: string | null;
  fiador_nome: string | null;
  fiador_cpf: string | null;
  fiador_telefone: string | null;
  equipamentos: ContractEquipment[] | null;
  qtd_ars: number | null;
  valor_comercial_total: number | null;
  endereco_instalacao: string | null;
  prazo_meses: number | null;
  data_inicio: string | null;
  data_termino: string | null;
  dia_vencimento: number | null;
  valor_mensal: number | null;
  // Campos de manutenção preventiva
  proxima_manutencao: string | null;
  maintenance_status: MaintenanceStatus | null;
  notificacao_enviada_at: string | null;
  // PDF do contrato
  pdf_url: string | null;
  pdf_filename: string | null;
  parsed_at: string | null;
  // Timestamps
  created_at: string;
  updated_at: string;
}

export interface ContractDetailsCreate {
  agent_id: string;
  subscription_id: string;
  customer_id: string;
  payment_id?: string | null;
  document_id?: string | null;
  numero_contrato?: string | null;
  locatario_nome?: string | null;
  locatario_cpf_cnpj?: string | null;
  locatario_telefone?: string | null;
  locatario_endereco?: string | null;
  fiador_nome?: string | null;
  fiador_cpf?: string | null;
  fiador_telefone?: string | null;
  equipamentos?: ContractEquipment[] | null;
  qtd_ars?: number | null;
  valor_comercial_total?: number | null;
  endereco_instalacao?: string | null;
  prazo_meses?: number | null;
  data_inicio?: string | null;
  data_termino?: string | null;
  dia_vencimento?: number | null;
  valor_mensal?: number | null;
  proxima_manutencao?: string | null;
  maintenance_status?: MaintenanceStatus | null;
  pdf_url?: string | null;
  pdf_filename?: string | null;
}

export interface ContractDetailsUpdate {
  payment_id?: string | null;
  document_id?: string | null;
  numero_contrato?: string | null;
  locatario_nome?: string | null;
  locatario_cpf_cnpj?: string | null;
  locatario_telefone?: string | null;
  locatario_endereco?: string | null;
  fiador_nome?: string | null;
  fiador_cpf?: string | null;
  fiador_telefone?: string | null;
  equipamentos?: ContractEquipment[] | null;
  qtd_ars?: number | null;
  valor_comercial_total?: number | null;
  endereco_instalacao?: string | null;
  prazo_meses?: number | null;
  data_inicio?: string | null;
  data_termino?: string | null;
  dia_vencimento?: number | null;
  valor_mensal?: number | null;
  proxima_manutencao?: string | null;
  maintenance_status?: MaintenanceStatus | null;
  notificacao_enviada_at?: string | null;
  pdf_url?: string | null;
  pdf_filename?: string | null;
  parsed_at?: string | null;
}

