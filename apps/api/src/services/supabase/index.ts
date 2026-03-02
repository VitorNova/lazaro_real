// Client exports
export {
  supabaseAnon,
  supabaseAdmin,
  createOrgClient,
  setOrganizationContext,
} from './client';

// Type exports
export {
  // Enums
  PlanType,
  UserRole,
  AsaasEnvironment,
  LeadStatus,
  PipelineStep,
  MessageRole,
  MessageType,
  ScheduleStatus,
  PaymentStatus,

  // Organization
  type Organization,
  type OrganizationCreate,
  type OrganizationUpdate,

  // User
  type User,
  type UserCreate,
  type UserUpdate,

  // Integration
  type GoogleCredentials,
  type Integration,
  type IntegrationCreate,
  type IntegrationUpdate,

  // Agent Config
  type AgentConfig,
  type AgentConfigCreate,
  type AgentConfigUpdate,

  // Department
  type Department,
  type DepartmentCreate,
  type DepartmentUpdate,

  // Lead
  type Lead,
  type LeadCreate,
  type LeadUpdate,

  // Message
  type MessageContent,
  type Message,
  type MessageCreate,

  // Message Buffer
  type FileData,
  type MessageBuffer,
  type MessageBufferCreate,

  // Schedule
  type Schedule,
  type ScheduleCreate,
  type ScheduleUpdate,

  // Payment
  type Payment,
  type PaymentCreate,
  type PaymentUpdate,

  // Database
  type Database,

  // Leadbox User
  type LeadboxUser,
  type LeadboxUserCreate,
  type LeadboxUserUpdate,

  // Agent
  type AgentStatus,
  type PipelineStage,
  type BusinessHours,
  type Agent,
  type AgentCreate,
  type AgentUpdate,

  // Dynamic Lead
  type DynamicLead,
  type DynamicLeadCreate,
  type DynamicLeadUpdate,

  // Lead Message
  type LeadMessage,
  type LeadMessageCreate,
  type LeadMessageUpdate,

  // Controle
  type Controle,
  type ControleCreate,
  type ControleUpdate,
} from './types';

// Repository exports
export {
  organizationsRepository,
  leadsRepository,
  messagesRepository,
  bufferRepository,
  integrationsRepository,
  agentConfigRepository,
  schedulesRepository,
  paymentsRepository,
  AgentsRepository,
  agentsRepository,
  DynamicRepository,
  dynamicRepository,
  type LeadFilters,
} from './repositories';
