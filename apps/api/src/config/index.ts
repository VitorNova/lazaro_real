import { z } from 'zod';

// ============================================================================
// SCHEMA DE CONFIGURAÇÃO
// ============================================================================

const configSchema = z.object({
  // Server
  port: z.coerce.number().default(3000),
  nodeEnv: z.enum(['development', 'production', 'test']).default('development'),

  // Supabase
  supabase: z.object({
    url: z.string().url(),
    anonKey: z.string().min(1),
    serviceRoleKey: z.string().min(1),
  }),

  // WhatsApp Provider (UAZAPI or Evolution)
  whatsappProvider: z.enum(['uazapi', 'evolution']).default('uazapi'),

  // UAZAPI (WhatsApp provider)
  uazapi: z.object({
    baseUrl: z.string().optional(),
    instance: z.string().default('default'),
    apiKey: z.string().optional(),
    adminToken: z.string().optional(),
    instanceToken: z.string().optional(),
  }),

  // Evolution API (WhatsApp provider - alternative to UAZAPI)
  evolution: z.object({
    baseUrl: z.string().url().optional(),
    apiKey: z.string().optional(),
  }),

  // Anthropic
  anthropic: z.object({
    apiKey: z.string().min(1),
    model: z.string().default('claude-sonnet-4-20250514'),
    maxTokens: z.coerce.number().default(4096),
  }),

  // OpenAI (opcional)
  openai: z.object({
    apiKey: z.string().optional(),
    whisperModel: z.string().default('whisper-1'),
  }),

  // Google Calendar (opcional)
  google: z.object({
    clientId: z.string().optional(),
    clientSecret: z.string().optional(),
    redirectUri: z.string().optional(),
  }),

  // Asaas (opcional)
  asaas: z.object({
    apiKey: z.string().optional(),
    baseUrl: z.string().default('https://api.asaas.com/v3'),
    environment: z.enum(['sandbox', 'production']).default('sandbox'),
    webhookToken: z.string().optional(),
  }),

  // Business
  business: z.object({
    workHoursStart: z.string().default('08:00'),
    workHoursEnd: z.string().default('18:00'),
    sessionDurationMinutes: z.coerce.number().default(60),
    messageBufferDelayMs: z.coerce.number().default(9000),
    timezone: z.string().default('America/Sao_Paulo'),
  }),
});

// ============================================================================
// LOAD CONFIG
// ============================================================================

function loadConfig() {
  const result = configSchema.safeParse({
    port: process.env.PORT,
    nodeEnv: process.env.NODE_ENV,

    supabase: {
      url: process.env.SUPABASE_URL,
      anonKey: process.env.SUPABASE_ANON_KEY,
      serviceRoleKey: process.env.SUPABASE_SERVICE_KEY,
    },

    // WhatsApp Provider (UAZAPI or Evolution - reads from env or agent config)
    whatsappProvider: process.env.WHATSAPP_PROVIDER || 'uazapi',

    // UAZAPI
    uazapi: {
      baseUrl: process.env.UAZAPI_BASE_URL,
      instance: process.env.UAZAPI_INSTANCE_KEY || process.env.UAZAPI_INSTANCE,
      apiKey: process.env.UAZAPI_API_KEY,
      adminToken: process.env.UAZAPI_ADMIN_TOKEN,
      instanceToken: process.env.UAZAPI_INSTANCE_TOKEN,
    },

    // Evolution API
    evolution: {
      baseUrl: process.env.EVOLUTION_BASE_URL,
      apiKey: process.env.EVOLUTION_API_KEY,
    },

    anthropic: {
      apiKey: process.env.ANTHROPIC_API_KEY,
      model: process.env.ANTHROPIC_MODEL,
      maxTokens: process.env.ANTHROPIC_MAX_TOKENS,
    },

    openai: {
      apiKey: process.env.OPENAI_API_KEY,
      whisperModel: process.env.OPENAI_WHISPER_MODEL,
    },

    google: {
      clientId: process.env.GOOGLE_CLIENT_ID,
      clientSecret: process.env.GOOGLE_CLIENT_SECRET,
      redirectUri: process.env.GOOGLE_REDIRECT_URI,
    },

    asaas: {
      apiKey: process.env.ASAAS_API_KEY,
      baseUrl: process.env.ASAAS_BASE_URL,
      environment: process.env.ASAAS_ENVIRONMENT,
      webhookToken: process.env.ASAAS_WEBHOOK_TOKEN,
    },

    business: {
      workHoursStart: process.env.WORK_HOURS_START,
      workHoursEnd: process.env.WORK_HOURS_END,
      sessionDurationMinutes: process.env.SESSION_DURATION_MINUTES,
      messageBufferDelayMs: process.env.MESSAGE_BUFFER_DELAY_MS,
      timezone: process.env.TIMEZONE,
    },
  });

  if (!result.success) {
    console.error('Configuration validation failed:');
    console.error(result.error.format());
    throw new Error('Invalid configuration');
  }

  return result.data;
}

export const config = loadConfig();

export type Config = z.infer<typeof configSchema>;
