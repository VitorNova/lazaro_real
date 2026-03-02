import { FastifyRequest, FastifyReply } from 'fastify';
import { randomUUID } from 'crypto';
import axios from 'axios';
import { supabaseAdmin } from '../../services/supabase/client';
import { AgentsRepository } from '../../services/supabase/repositories/agents.repository';
import { DynamicRepository } from '../../services/supabase/repositories/dynamic.repository';
import { createUazapiClient, UazapiClient } from '../../services/uazapi';
import { createAllTablesSQL, createDianaTablesSQL, createMessagesTableSQL, createMsgTempTableSQL, dropTablesSQL, enableRealtimeForLeadTableSQL } from '../../utils/table-creator';
import {
  AgentCreate,
  PipelineStage,
  BusinessHours,
  AsaasEnvironment,
  WhatsAppProvider,
  ScheduleConfirmationConfig,
  AsaasConfig,
} from '../../services/supabase/types';
import { config } from '../../config';

// ============================================================================
// API KEY VALIDATION FUNCTIONS
// ============================================================================

/**
 * Valida API key do Gemini fazendo uma requisição simples
 */
async function validateGeminiApiKey(apiKey: string): Promise<{ valid: boolean; error?: string }> {
  try {
    const response = await axios.post(
      `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=${apiKey}`,
      { contents: [{ parts: [{ text: 'Hi' }] }] },
      { timeout: 10000 }
    );
    return { valid: response.status === 200 };
  } catch (error: any) {
    const status = error.response?.status;
    const message = error.response?.data?.error?.message || error.message;
    if (status === 400 && message?.includes('API key')) {
      return { valid: false, error: 'API key inválida' };
    }
    if (status === 403) {
      return { valid: false, error: 'API key sem permissão ou inválida' };
    }
    // Outros erros podem ser de rede, considerar válido para não bloquear
    return { valid: true };
  }
}

/**
 * Valida API key do Claude/Anthropic fazendo uma requisição simples
 */
async function validateClaudeApiKey(apiKey: string): Promise<{ valid: boolean; error?: string }> {
  try {
    const response = await axios.post(
      'https://api.anthropic.com/v1/messages',
      {
        model: 'claude-3-haiku-20240307',
        max_tokens: 10,
        messages: [{ role: 'user', content: 'Hi' }],
      },
      {
        headers: {
          'x-api-key': apiKey,
          'anthropic-version': '2023-06-01',
          'Content-Type': 'application/json',
        },
        timeout: 10000,
      }
    );
    return { valid: response.status === 200 };
  } catch (error: any) {
    const status = error.response?.status;
    if (status === 401) {
      return { valid: false, error: 'API key inválida' };
    }
    if (status === 403) {
      return { valid: false, error: 'API key sem permissão' };
    }
    // Outros erros podem ser de rede, considerar válido para não bloquear
    return { valid: true };
  }
}

/**
 * Valida API key do OpenAI fazendo uma requisição simples
 */
async function validateOpenAIApiKey(apiKey: string): Promise<{ valid: boolean; error?: string }> {
  try {
    const response = await axios.get('https://api.openai.com/v1/models', {
      headers: { Authorization: `Bearer ${apiKey}` },
      timeout: 10000,
    });
    return { valid: response.status === 200 };
  } catch (error: any) {
    const status = error.response?.status;
    if (status === 401) {
      return { valid: false, error: 'API key inválida' };
    }
    if (status === 403) {
      return { valid: false, error: 'API key sem permissão' };
    }
    // Outros erros podem ser de rede, considerar válido para não bloquear
    return { valid: true };
  }
}

// ============================================================================
// LOGGER
// ============================================================================

const Logger = {
  info: (msg: string, data?: unknown) => console.info(`[CreateAgent] ${msg}`, data ?? ''),
  warn: (msg: string, data?: unknown) => console.warn(`[CreateAgent] ${msg}`, data ?? ''),
  error: (msg: string, data?: unknown) => console.error(`[CreateAgent] ${msg}`, data ?? ''),
  debug: (msg: string, data?: unknown) => {
    if (process.env.DEBUG === 'true') {
      console.debug(`[CreateAgent:DEBUG] ${msg}`, data ?? '');
    }
  },
};

// ============================================================================
// TYPES
// ============================================================================

export interface CreateAgentBody {
  name: string;
  // AI Provider Config
  ai_provider?: 'gemini' | 'claude' | 'openai';
  gemini_api_key?: string;
  gemini_model?: string;
  claude_api_key?: string;
  claude_model?: string;
  openai_api_key?: string;
  openai_model?: string;
  owner_phone?: string; // Telefone do proprietario para notificacoes
  system_prompt: string;
  pipeline_stages: PipelineStage[];
  google_calendar_enabled?: boolean;
  google_credentials?: unknown;
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
  }>;
  asaas_enabled?: boolean;
  asaas_api_key?: string;
  asaas_environment?: 'sandbox' | 'production';
  asaas_config?: AsaasConfig;
  product_description?: string;
  product_value?: number;
  business_hours?: BusinessHours;
  work_days?: string[];
  meeting_duration?: number;
  timezone?: string;
  // Response Size Config
  response_size?: 'short' | 'medium' | 'long';
  split_messages?: boolean;
  split_mode?: 'smart' | 'paragraph' | 'natural'; // Modo de quebra de mensagens
  message_buffer_delay?: number; // Delay em ms para aguardar mais mensagens
  // WhatsApp Provider (UAZAPI or Evolution)
  whatsapp_provider?: 'uazapi' | 'evolution';
  // UAZAPI base URL
  uazapi_base_url?: string;
  // Evolution API fields
  evolution_base_url?: string;
  evolution_api_key?: string;
  // Follow-up Config
  follow_up_enabled?: boolean;
  follow_up_config?: {
    inactivity: {
      enabled: boolean;
      delays: number[];
      messages: string[];
      steps?: Array<{
        delayMinutes: number;
        useAI: boolean;
        message: string;
      }>;
    };
    nurture: {
      enabled: boolean;
      delays: number[];
      messages: string[];
      steps?: Array<{
        delayMinutes: number;
        useAI: boolean;
        message: string;
      }>;
    };
    reminder: {
      enabled: boolean;
      minutesBefore: number;
      useAI?: boolean;
      message?: string;
    };
  };
  // Qualification BANT Config
  qualification_enabled?: boolean;
  qualification_config?: {
    qualifyAfterMessages: number;
    bantCriteria: { budget: string; authority: string; need: string; timing: string };
    fitCriteria: { companySize: string; industry: string; digitalMaturity: string };
    hotLeadThreshold: number;
    warmLeadThreshold: number;
  };
  // Agent Type
  agent_type?: 'SDR' | 'FOLLOWUP' | 'SUPPORT' | 'CUSTOM';
  // Shared WhatsApp - usar instância de outro agente
  parent_agent_id?: string;
  uses_shared_whatsapp?: boolean;
  // Diana Prospection Fields
  type?: 'agnes' | 'salvador' | 'diana';
  google_places_api_key?: string;
  diana_company_name?: string;
  diana_company_description?: string;
  diana_agent_name?: string;
  prospection_niche?: string;
  prospection_niche_custom?: string;
  prospection_location_type?: 'state' | 'city' | 'both';
  prospection_state?: string;
  prospection_city?: string;
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
  }>;
  // Schedule Confirmation Config
  schedule_confirmation_enabled?: boolean;
  schedule_confirmation_config?: ScheduleConfirmationConfig;

  // Localizacao da empresa
  location_latitude?: number | null;
  location_longitude?: number | null;
  location_name?: string | null;
  location_address?: string | null;
  // Servicos/Procedimentos configurados
  services?: Array<{
    name: string;
    duration: number;
    isDefault?: boolean;
  }>;
  // Titulo e descricao padrao para reunioes
  meeting_title?: string;
  meeting_description?: string;
  // RAG (Base de Conhecimento)
  rag_enabled?: boolean;
  // Leadbox Handoff
  handoff_triggers?: {
    type: string;
    enabled: boolean;
    api_url: string;
    api_uuid?: string;
    api_token: string;
    queue_ia?: number;
    departments: Record<string, { id: number; name: string; userId?: number | null }>;
  };
  // Observer AI Prompt
  observer_prompt?: string | null;
}

export interface CreateAgentRequest {
  Body: CreateAgentBody;
}

interface CreateAgentResponse {
  agent_id: string;
  qr_code_url: string;
  webhook_url: string;
  status: 'success' | 'error';
  message: string;
  // Novos campos para WhatsApp compartilhado
  uses_shared_whatsapp?: boolean;
  parent_agent_id?: string | null;
  whatsapp_already_connected?: boolean;
}

// ============================================================================
// HANDLER
// ============================================================================

export async function createAgentHandler(
  request: FastifyRequest<CreateAgentRequest>,
  reply: FastifyReply
): Promise<FastifyReply> {
  // Variaveis para rollback
  let agentId: string | null = null;
  let tableLeads: string | null = null;
  let tableMessages: string | null = null;
  let tableMsgTemp: string | null = null; // Tabela de buffer de mensagens (null para Salvador)
  let uazapiInstanceId: string | null = null;
  let uazapiInstanceName: string | null = null;
  let uazapiClient: UazapiClient | null = null;
  let usesSharedWhatsApp = false; // Declarado aqui para estar acessível no catch/rollback

  try {
    Logger.info('=== INICIANDO CRIACAO DE AGENTE ===');

    // ========================================================================
    // 1. EXTRAIR USER_ID DO REQUEST (JWT middleware ou header legado)
    // ========================================================================

    // Prioridade: 1) request.user do JWT middleware, 2) x-user-id header (legado)
    const userId = (request as any).user?.id || request.headers['x-user-id'] as string;

    if (!userId) {
      Logger.warn('Missing user authentication');
      return reply.status(401).send({
        status: 'error',
        message: 'Unauthorized: Authentication required',
      });
    }

    Logger.info('Creating agent for user', { userId });

    // ========================================================================
    // 1.5 VERIFICAR/CRIAR USUARIO NA TABELA USERS
    // ========================================================================

    // Verificar se o usuario existe
    const { data: existingUser, error: userCheckError } = await supabaseAdmin
      .from('users')
      .select('id')
      .eq('id', userId)
      .single();

    if (userCheckError && userCheckError.code !== 'PGRST116') {
      // PGRST116 = not found, que é ok
      Logger.error('Error checking user', { error: userCheckError.message });
    }

    // Se usuario não existe, criar automaticamente
    if (!existingUser) {
      Logger.info('User not found, creating new user', { userId });

      const { error: createUserError } = await supabaseAdmin
        .from('users')
        .insert({
          id: userId,
          email: `${userId}@temp.leadbox.ai`,
          google_id: `temp_${userId}`,
          name: 'Usuário Leadbox',
        });

      if (createUserError) {
        Logger.error('Failed to create user', { error: createUserError.message });
        return reply.status(500).send({
          status: 'error',
          message: 'Falha ao criar usuario no sistema',
        });
      }

      Logger.info('User created successfully', { userId });
    }

    // ========================================================================
    // 1.6 VERIFICAR LIMITE DE AGENTES DO PLANO
    // ========================================================================

    const { data: userPlan } = await supabaseAdmin
      .from('user_plans')
      .select('max_agents, plan')
      .eq('user_id', userId)
      .single();

    const maxAgents = userPlan?.max_agents ?? 2; // Default: 2 (plano free)

    // -1 significa ilimitado (enterprise)
    if (maxAgents !== -1) {
      const { count: currentAgents } = await supabaseAdmin
        .from('agents')
        .select('*', { count: 'exact', head: true })
        .eq('user_id', userId);

      if ((currentAgents || 0) >= maxAgents) {
        Logger.warn('Agent limit reached', { userId, currentAgents, maxAgents, plan: userPlan?.plan });
        return reply.status(403).send({
          status: 'error',
          message: `Limite de ${maxAgents} agentes atingido. Faça upgrade do seu plano.`,
          code: 'AGENT_LIMIT_REACHED',
        });
      }
    }

    // ========================================================================
    // 2. VALIDAR CAMPOS OBRIGATORIOS
    // ========================================================================

    const body = request.body;

    if (!body.name || body.name.trim() === '') {
      return reply.status(400).send({
        status: 'error',
        message: 'Campo obrigatorio: name',
      });
    }

    // Validar API Key baseado no provider selecionado
    const aiProvider = body.ai_provider || 'gemini';

    // gemini_api_key é opcional — se não informada, o runtime usa a key global do .env

    if (aiProvider === 'claude' && (!body.claude_api_key || body.claude_api_key.trim() === '')) {
      return reply.status(400).send({
        status: 'error',
        message: 'Campo obrigatorio: claude_api_key (provider selecionado: Claude)',
      });
    }

    if (aiProvider === 'openai' && (!body.openai_api_key || body.openai_api_key.trim() === '')) {
      return reply.status(400).send({
        status: 'error',
        message: 'Campo obrigatorio: openai_api_key (provider selecionado: OpenAI)',
      });
    }

    if (!body.system_prompt || body.system_prompt.trim() === '') {
      return reply.status(400).send({
        status: 'error',
        message: 'Campo obrigatorio: system_prompt',
      });
    }

    if (!body.pipeline_stages || !Array.isArray(body.pipeline_stages) || body.pipeline_stages.length === 0) {
      return reply.status(400).send({
        status: 'error',
        message: 'Campo obrigatorio: pipeline_stages (array com pelo menos 1 etapa)',
      });
    }

    // ========================================================================
    // 2.3 VALIDAR API KEY COM TESTE REAL (não apenas verificar se está vazia)
    // ========================================================================

    Logger.info('Validating AI API key...', { provider: aiProvider });

    try {
      if (aiProvider === 'gemini' && body.gemini_api_key) {
        const validation = await validateGeminiApiKey(body.gemini_api_key);
        if (!validation.valid) {
          Logger.warn('Gemini API key validation failed', { error: validation.error });
          return reply.status(400).send({
            status: 'error',
            message: `API key do Gemini inválida: ${validation.error}`,
            code: 'INVALID_API_KEY',
          });
        }
      }

      if (aiProvider === 'claude' && body.claude_api_key) {
        const validation = await validateClaudeApiKey(body.claude_api_key);
        if (!validation.valid) {
          Logger.warn('Claude API key validation failed', { error: validation.error });
          return reply.status(400).send({
            status: 'error',
            message: `API key do Claude inválida: ${validation.error}`,
            code: 'INVALID_API_KEY',
          });
        }
      }

      if (aiProvider === 'openai' && body.openai_api_key) {
        const validation = await validateOpenAIApiKey(body.openai_api_key);
        if (!validation.valid) {
          Logger.warn('OpenAI API key validation failed', { error: validation.error });
          return reply.status(400).send({
            status: 'error',
            message: `API key do OpenAI inválida: ${validation.error}`,
            code: 'INVALID_API_KEY',
          });
        }
      }

      Logger.info('AI API key validated successfully', { provider: aiProvider });
    } catch (validationError) {
      // Se a validação falhar por erro de rede, continuar (não bloquear criação)
      Logger.warn('API key validation skipped due to network error', {
        provider: aiProvider,
        error: validationError instanceof Error ? validationError.message : validationError,
      });
    }

    // ========================================================================
    // 2.5 VERIFICAR LIMITE DE AGENTES POR TIPO (usando user_limits do admin)
    // ========================================================================

    // DEBUG: Log the received type to diagnose salvador->agnes conversion bug
    Logger.info('Received agent type from frontend', {
      'body.type': body.type,
      'body.agent_type': body.agent_type,
      'typeof body.type': typeof body.type,
      'body.type truthy?': !!body.type
    });

    const agentType = body.type || 'agnes';

    // Defaults caso user_limits não exista para o usuário
    const DEFAULT_LIMITS: Record<string, number> = {
      agnes: 3,
      diana: 1,
      salvador: 5,
    };

    // Mapeia tipo do agente para campo na tabela user_limits
    const limitFieldMap: Record<string, string> = {
      agnes: 'max_agnes_agents',
      diana: 'max_diana_agents',
      salvador: 'max_salvador_agents',
    };

    // Buscar limites configurados pelo admin na tabela user_limits
    const { data: userLimits } = await supabaseAdmin
      .from('user_limits')
      .select('max_agnes_agents, max_diana_agents, max_salvador_agents')
      .eq('user_id', userId)
      .single();

    const limitField = limitFieldMap[agentType];
    const maxForType = limitField && userLimits
      ? (userLimits as Record<string, any>)[limitField] ?? DEFAULT_LIMITS[agentType] ?? 2
      : DEFAULT_LIMITS[agentType] ?? 2;

    Logger.info('Agent limit resolved', { userId, agentType, maxForType, source: userLimits ? 'user_limits' : 'default' });

    const { data: existingAgents, error: countError } = await supabaseAdmin
      .from('agents')
      .select('id, name')
      .eq('user_id', userId)
      .eq('type', agentType);

    if (countError) {
      Logger.error('Error checking agent count', { error: countError.message });
    }

    const agentCount = existingAgents?.length || 0;

    if (agentCount >= maxForType) {
      const typeNames: Record<string, string> = {
        'agnes': 'Agnes (SDR)',
        'diana': 'Diana (Prospecção)',
        'salvador': 'Salvador (Suporte)'
      };
      const typeName = typeNames[agentType] || agentType;

      Logger.warn('Agent limit reached', { userId, agentType, count: agentCount, max: maxForType });
      return reply.status(400).send({
        status: 'error',
        message: `Limite atingido: você já possui ${agentCount} agente(s) do tipo ${typeName}. O máximo permitido é ${maxForType} agentes por tipo.`,
        code: 'AGENT_LIMIT_REACHED',
        details: {
          type: agentType,
          current: agentCount,
          max: maxForType,
          existingAgents: existingAgents?.map(a => a.name) || []
        }
      });
    }

    Logger.info('Agent count check passed', { userId, agentType, current: agentCount, max: maxForType });

    // ========================================================================
    // 3. GERAR AGENT_ID E SHORT_ID
    // ========================================================================

    agentId = randomUUID();
    const shortId = agentId.substring(0, 8);

    // ========================================================================
    // 4. GERAR NOMES DAS TABELAS
    // Formato: {Prefix}_{AgentName}_{shortId}
    // ========================================================================

    // Sanitizar o nome do agente para uso em nomes de tabela
    // Remove acentos, caracteres especiais, espaços -> PascalCase
    const sanitizeAgentName = (name: string): string => {
      // Remover acentos
      const normalized = name.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
      // Remover caracteres não alfanuméricos (exceto espaços)
      const cleaned = normalized.replace(/[^a-zA-Z0-9\s]/g, '');
      // Converter para PascalCase (cada palavra capitalizada, sem espaços)
      const words = cleaned.trim().split(/\s+/);
      const pascalCase = words
        .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
        .join('');
      // Garantir que começa com letra (requisito PostgreSQL)
      if (!/^[a-zA-Z]/.test(pascalCase)) {
        return 'Agent' + pascalCase;
      }
      return pascalCase || 'Agent';
    };

    const sanitizedName = sanitizeAgentName(body.name);

    // Diana usa tabela global 'diana', outros agentes usam tabelas dinâmicas
    // Salvador NÃO usa buffer de mensagens (é agente de follow-up)
    if (body.type === 'salvador') {
      // Salvador herda tabelas do parent Agnes, não tem buffer próprio
      tableMsgTemp = null;
      // tableLeads, tableMessages serão herdados do parent
    } else if (body.type === 'diana') {
      tableLeads = 'diana'; // Tabela global de prospecção Diana
      tableMessages = `leadbox_messages_${sanitizedName}_${shortId}`;
      tableMsgTemp = `msg_temp_${sanitizedName}_${shortId}`;
    } else {
      // agnes e outros tipos
      tableLeads = `LeadboxCRM_${sanitizedName}_${shortId}`;
      tableMessages = `leadbox_messages_${sanitizedName}_${shortId}`;
      tableMsgTemp = `msg_temp_${sanitizedName}_${shortId}`;
    }

    Logger.info('Generated identifiers', {
      agentId,
      shortId,
      agentName: body.name,
      sanitizedName,
      tableLeads,
      tableMessages,
      tableMsgTemp,
    });

    // ========================================================================
    // 5. CONFIGURAR WHATSAPP (UAZAPI ou EVOLUTION)
    // ========================================================================

    // Determinar provider - default para UAZAPI se não especificado
    const whatsappProvider: WhatsAppProvider = body.whatsapp_provider || 'uazapi';
    const webhookUrl = `${process.env.API_BASE_URL}/webhooks/dynamic`;

    let uazapiToken: string | null = null;
    // usesSharedWhatsApp já declarado antes do try para acesso no rollback
    let parentAgentId: string | null = null;

    // Evolution-specific fields
    let evolutionBaseUrl: string | null = null;
    let evolutionApiKey: string | null = null;

    Logger.info('WhatsApp provider configured', { whatsappProvider });

    // ========================================================================
    // REGRA: Salvador SEMPRE deve ter parent_agent_id apontando para Agnes
    // Se o tipo for 'salvador' e não tiver parent_agent_id, buscar automaticamente
    // ========================================================================
    if (body.type === 'salvador' && !body.parent_agent_id) {
      Logger.info('Salvador agent without parent_agent_id - auto-finding Agnes parent');

      // Buscar Agnes do mesmo user_id
      const { data: agnesParent, error: agnesError } = await supabaseAdmin
        .from('agents')
        .select('id, name, uazapi_instance_id, uazapi_token, uazapi_connected')
        .eq('user_id', userId)
        .eq('type', 'agnes')
        .limit(1)
        .single();

      if (agnesError || !agnesParent) {
        Logger.error('No Agnes agent found for Salvador', { userId, error: agnesError?.message });
        return reply.status(400).send({
          status: 'error',
          message: 'Para criar um agente Salvador, você precisa ter um agente Agnes (SDR) criado primeiro.',
          code: 'AGNES_REQUIRED_FOR_SALVADOR',
        });
      }

      // Verificar se o Agnes tem WhatsApp conectado
      if (!agnesParent.uazapi_connected) {
        Logger.error('Agnes WhatsApp not connected', { agnesId: agnesParent.id });
        return reply.status(400).send({
          status: 'error',
          message: 'O agente Agnes precisa estar com WhatsApp conectado antes de criar um Salvador.',
          code: 'AGNES_NOT_CONNECTED',
        });
      }

      // Configurar Salvador para usar WhatsApp compartilhado do Agnes
      body.parent_agent_id = agnesParent.id;
      body.uses_shared_whatsapp = true;

      Logger.info('Salvador auto-linked to Agnes', {
        salvadorName: body.name,
        agnesId: agnesParent.id,
        agnesName: agnesParent.name,
      });
    }

    // Verificar se deve usar WhatsApp compartilhado de outro agente
    if (body.uses_shared_whatsapp && body.parent_agent_id) {
      Logger.info('Using shared WhatsApp from parent agent', { parentAgentId: body.parent_agent_id });

      // Buscar dados do agente pai (incluindo tabelas para herança)
      const { data: parentAgent, error: parentError } = await supabaseAdmin
        .from('agents')
        .select('id, uazapi_instance_id, uazapi_token, uazapi_connected, table_leads, table_messages')
        .eq('id', body.parent_agent_id)
        .eq('user_id', userId)
        .single();

      if (parentError || !parentAgent) {
        Logger.error('Parent agent not found', { parentAgentId: body.parent_agent_id, error: parentError?.message });
        return reply.status(400).send({
          status: 'error',
          message: 'Agente pai não encontrado para compartilhamento de WhatsApp',
        });
      }

      // Verificar se agente pai tem WhatsApp conectado
      if (!parentAgent.uazapi_connected) {
        Logger.error('Parent agent WhatsApp not connected', { parentAgentId: body.parent_agent_id });
        return reply.status(400).send({
          status: 'error',
          message: 'O agente pai não tem WhatsApp conectado',
        });
      }

      // Usar dados do agente pai
      uazapiInstanceId = parentAgent.uazapi_instance_id;
      uazapiToken = parentAgent.uazapi_token;
      usesSharedWhatsApp = true;
      parentAgentId = body.parent_agent_id;

      // ========================================================================
      // REGRA CRÍTICA: Salvador com WhatsApp compartilhado DEVE usar as tabelas do pai
      // Os leads são criados na tabela do Agnes, então o Salvador precisa acessar a mesma tabela
      // ========================================================================
      if (!parentAgent.table_leads || !parentAgent.table_messages) {
        Logger.error('Parent agent has missing tables', {
          parentAgentId: body.parent_agent_id,
          tableLeads: parentAgent.table_leads,
          tableMessages: parentAgent.table_messages,
        });
        return reply.status(400).send({
          status: 'error',
          message: 'Agente pai não tem tabelas configuradas corretamente',
        });
      }

      tableLeads = parentAgent.table_leads;
      tableMessages = parentAgent.table_messages;

      Logger.info('Shared WhatsApp configured - using parent tables', {
        parentAgentId,
        tableLeads,
        tableMessages,
      });

    } else {
      // ========================================================================
      // WhatsApp Provider: NÃO criar instância aqui
      // A instância será criada APENAS quando o usuário clicar em "Gerar QR Code"
      // Isso evita instâncias órfãs e duplicação
      // ========================================================================
      if (whatsappProvider === 'evolution') {
        // Evolution API - configurar credenciais se fornecidas
        evolutionBaseUrl = body.evolution_base_url || config.evolution.baseUrl || null;
        evolutionApiKey = body.evolution_api_key || config.evolution.apiKey || null;

        Logger.info('Evolution provider selected - instance will be created when user clicks "Generate QR Code"', {
          agentId,
          provider: 'evolution',
          hasCredentials: !!(evolutionBaseUrl && evolutionApiKey),
        });
      } else {
        // UAZAPI (default)
        Logger.info('UAZAPI provider selected - instance will be created when user clicks "Generate QR Code"', {
          agentId,
          provider: 'uazapi',
        });
      }

      // Apenas configurar base_url para uso posterior
      // As instâncias serão criadas pelo qrcode.handler
    }

    // ========================================================================
    // 6. CRIAR TABELAS NO BANCO
    // ========================================================================

    Logger.info('Creating dynamic tables...');

    try {
      const dynamicRepo = new DynamicRepository(supabaseAdmin);

      // Para Diana, não criar tabela LeadboxCRM (usa tabela global 'diana')
      // Apenas criar tabela de mensagens
      if (body.type === 'diana') {
        Logger.info('Diana agent - using global diana table, creating only messages table');

        // Criar apenas tabela de mensagens
        const messagesSQL = createMessagesTableSQL(tableMessages!);

        const { error: msgError } = await dynamicRepo.executeRawSQL(messagesSQL);
        if (msgError) {
          Logger.error('Failed to create messages table', { error: msgError.message });
          throw new Error(`Failed to create messages table: ${msgError.message}`);
        }

        // Criar tabela de buffer de mensagens para Diana
        if (tableMsgTemp) {
          Logger.info('Creating msg_temp table for Diana', { tableMsgTemp });
          const msgTempSQL = createMsgTempTableSQL(tableMsgTemp);
          const { error: msgTempError } = await dynamicRepo.executeRawSQL(msgTempSQL);
          if (msgTempError) {
            Logger.error('Failed to create msg_temp table', { error: msgTempError.message });
            throw new Error(`Failed to create msg_temp table: ${msgTempError.message}`);
          }
        }

        // Criar tabelas auxiliares da Diana (diana_prospects, diana_mensagens) se não existirem
        Logger.info('Creating Diana auxiliary tables (if not exist)...');
        const dianaTablesSQL = createDianaTablesSQL();
        const { error: dianaError } = await dynamicRepo.executeRawSQL(dianaTablesSQL);
        if (dianaError) {
          Logger.warn('Diana auxiliary tables creation warning (may already exist)', { error: dianaError.message });
        }

        Logger.info('Diana tables configured successfully');
      } else if (body.type === 'salvador') {
        // Salvador herda tabelas do parent Agnes, não cria tabelas próprias
        // tableMsgTemp já é null para Salvador
        Logger.info('Salvador agent - inherits tables from parent Agnes, no msg_temp buffer');
      } else {
        // Para outros agentes (agnes), criar todas as tabelas normalmente + msg_temp
        const tablesSQL = createAllTablesSQL(tableLeads!, tableMessages!, tableMsgTemp);
        const { error: sqlError } = await dynamicRepo.executeRawSQL(tablesSQL);

        if (sqlError) {
          Logger.error('Failed to create tables', { error: sqlError.message });
          throw new Error(`Failed to create dynamic tables: ${sqlError.message}`);
        }

        Logger.info('Dynamic tables created successfully', { tableMsgTemp });

        // Habilitar Supabase Realtime para a tabela de leads
        try {
          const realtimeSQL = enableRealtimeForLeadTableSQL(tableLeads!);
          const { error: realtimeError } = await dynamicRepo.executeRawSQL(realtimeSQL);
          if (realtimeError) {
            // Log warning mas nao falha a criacao do agente
            Logger.warn('Failed to enable Realtime for leads table', {
              table: tableLeads,
              error: realtimeError.message,
            });
          } else {
            Logger.info('Supabase Realtime enabled for leads table', { table: tableLeads });
          }
        } catch (realtimeErr) {
          Logger.warn('Error enabling Realtime (non-fatal)', {
            table: tableLeads,
            error: realtimeErr instanceof Error ? realtimeErr.message : realtimeErr,
          });
        }
      }
    } catch (error) {
      Logger.error('Error creating dynamic tables', {
        error: error instanceof Error ? error.message : error,
      });

      // UAZAPI: Não precisa rollback aqui pois instância é criada apenas no qrcode.handler

      return reply.status(500).send({
        status: 'error',
        message: 'Falha ao criar tabelas dinamicas no banco de dados',
      });
    }

    // ========================================================================
    // 7. SALVAR AGENT NO BANCO
    // ========================================================================

    Logger.info('Saving agent to database...');

    const agentsRepo = new AgentsRepository(supabaseAdmin);

    const agentData: AgentCreate = {
      user_id: userId,
      name: body.name.trim(),
      status: 'creating',
      // WhatsApp Provider (UAZAPI or Evolution)
      whatsapp_provider: whatsappProvider,
      // UAZAPI fields (only used when provider is 'uazapi')
      uazapi_instance_id: whatsappProvider === 'uazapi' ? uazapiInstanceId : null,
      uazapi_token: whatsappProvider === 'uazapi' ? uazapiToken : null,
      uazapi_base_url: whatsappProvider === 'uazapi' ? (config.uazapi.baseUrl || '') : null,
      uazapi_connected: false,
      // Evolution fields (only used when provider is 'evolution')
      evolution_base_url: whatsappProvider === 'evolution' ? evolutionBaseUrl : null,
      evolution_api_key: whatsappProvider === 'evolution' ? evolutionApiKey : null,
      evolution_instance_name: null, // Sera criado pelo qrcode.handler
      evolution_connected: false,
      // Dynamic tables
      table_leads: tableLeads!,
      table_messages: tableMessages!,
      table_msg_temp: tableMsgTemp, // Tabela de buffer de mensagens (null para Salvador)
      // AI Config
      ai_provider: body.ai_provider || 'gemini',
      gemini_api_key: body.gemini_api_key || null,
      gemini_model: body.gemini_model || 'gemini-2.0-flash',
      claude_api_key: body.claude_api_key || null,
      claude_model: body.claude_model || 'claude-sonnet-4-20250514',
      openai_api_key: body.openai_api_key || null,
      openai_model: body.openai_model || 'gpt-4o-mini',
      owner_phone: body.owner_phone || null, // Telefone para notificacoes
      system_prompt: body.system_prompt,
      // Google Calendar - suporte a multiplas contas
      google_calendar_enabled: body.google_calendar_enabled || false,
      google_credentials: body.google_credentials as unknown as null,
      google_calendar_id: body.google_calendar_id || 'primary',
      google_accounts: body.google_accounts || null, // Array de contas: [{ email, credentials, calendar_id }]
      // Asaas Payments
      asaas_enabled: body.asaas_enabled || false,
      asaas_api_key: body.asaas_api_key || null,
      asaas_environment: (body.asaas_environment || 'sandbox') as AsaasEnvironment,
      asaas_config: body.asaas_config || null,
      // Product Info
      product_description: body.product_description || null,
      product_value: body.product_value || null,
      // Business Config
      business_hours: body.business_hours || { start: '08:00', end: '17:00' },
      work_days: body.work_days || ['seg', 'ter', 'qua', 'qui', 'sex'],
      meeting_duration: body.meeting_duration || 30,
      timezone: body.timezone || 'America/Sao_Paulo',
      pipeline_stages: body.pipeline_stages,
      // Response Size Config
      response_size: body.response_size || 'medium',
      split_messages: body.split_messages !== false, // default true
      split_mode: body.split_mode || 'paragraph', // default paragraph (quebra por parágrafos como n8n)
      message_buffer_delay: body.message_buffer_delay || 9000, // default 9 segundos
      // Follow-up Config - desabilitado por padrão, usuário deve habilitar explicitamente
      follow_up_enabled: body.follow_up_enabled !== undefined ? body.follow_up_enabled : false,
      follow_up_config: body.follow_up_config || {
        inactivity: {
          enabled: true,
          delays: [10, 30, 60, 1440],
          messages: [],
          steps: [
            { delayMinutes: 10, useAI: true, message: '' },
            { delayMinutes: 30, useAI: true, message: '' },
            { delayMinutes: 60, useAI: true, message: '' },
            { delayMinutes: 1440, useAI: true, message: '' },
          ],
        },
        nurture: {
          enabled: true,
          delays: [1440, 4320, 10080],
          messages: [],
          steps: [
            { delayMinutes: 1440, useAI: true, message: '' },
            { delayMinutes: 4320, useAI: true, message: '' },
            { delayMinutes: 10080, useAI: true, message: '' },
          ],
        },
        reminder: { enabled: true, minutesBefore: 30, useAI: true, message: '' },
      },
      // Qualification BANT Config
      qualification_enabled: body.qualification_enabled !== undefined ? body.qualification_enabled : true,
      qualification_config: body.qualification_config || {
        qualifyAfterMessages: 3,
        bantCriteria: {
          budget: 'Tem orçamento definido para investir na solução?',
          authority: 'É o decisor ou precisa consultar alguém?',
          need: 'Tem necessidade real e urgente do produto/serviço?',
          timing: 'Tem prazo definido para implementar a solução?',
        },
        fitCriteria: {
          companySize: 'Porte da empresa',
          industry: 'Segmento',
          digitalMaturity: 'Maturidade digital',
        },
        hotLeadThreshold: 70,
        warmLeadThreshold: 40,
        // Configuração dinâmica de critérios BANT habilitados
        // O criador do agente pode desabilitar critérios individuais no frontend
        bantEnabled: {
          budget: true,    // Orçamento - habilitado por padrão
          authority: true, // Autoridade/Decisor - habilitado por padrão
          need: true,      // Necessidade - habilitado por padrão
          timing: true,    // Prazo/Urgência - habilitado por padrão
        },
      },
      // Agent Type
      agent_type: (body.agent_type || 'SDR') as 'SDR' | 'FOLLOWUP' | 'SUPPORT' | 'CUSTOM',
      // Shared WhatsApp
      parent_agent_id: parentAgentId,
      uses_shared_whatsapp: usesSharedWhatsApp,
      // Diana Prospection Fields
      type: body.type || 'agnes',
      google_places_api_key: body.google_places_api_key || null,
      diana_company_name: body.diana_company_name || null,
      diana_company_description: body.diana_company_description || null,
      diana_agent_name: body.diana_agent_name || 'Diana',
      prospection_niche: body.prospection_niche || null,
      prospection_niche_custom: body.prospection_niche_custom || null,
      prospection_location_type: body.prospection_location_type || 'state',
      prospection_state: body.prospection_state || null,
      prospection_city: body.prospection_city || null,
      prospection_strategy: body.prospection_strategy || 'consultiva',
      prospection_daily_goal: body.prospection_daily_goal || 20,
      prospection_sequence: body.prospection_sequence || [],
      // Prompt Medias (audio, imagem, video) - apenas para agentes Agnes
      prompt_medias: body.prompt_medias || [],
      // Schedule Confirmation Config - desabilitado por padrão, usuário deve habilitar explicitamente
      schedule_confirmation_enabled: body.schedule_confirmation_enabled !== undefined ? body.schedule_confirmation_enabled : false,
      schedule_confirmation_config: body.schedule_confirmation_config || {
        intervals: [
          { minutesBefore: 1440, enabled: true, messageTemplate: null },
          { minutesBefore: 120, enabled: true, messageTemplate: null },
        ],
        positiveKeywords: ['sim', 'confirmo', 'confirmado', 'vou', 'estarei', 'pode ser', 'ok', 'beleza', 'combinado', 'certo', 'claro', 'com certeza'],
        negativeKeywords: ['nao', 'não', 'cancelar', 'cancela', 'desmarcar', 'nao vou', 'não vou', 'nao posso', 'não posso', 'desisto'],
        rescheduleKeywords: ['remarcar', 'outro horario', 'outro horário', 'mudar', 'alterar', 'trocar', 'adiar', 'antecipar'],
        defaultConfirmationMessage24h: 'Olá {{nome}}! 👋 Passando para lembrar do nosso compromisso amanhã às {{horario}}. Você confirma sua presença? Responda SIM para confirmar ou me avise caso precise remarcar.',
        defaultConfirmationMessage2h: 'Olá {{nome}}! ⏰ Seu compromisso está chegando - daqui a 2 horas, às {{horario}}. Tudo certo para nos vermos?',
        confirmationResponseMessage: 'Perfeito, {{nome}}! ✅ Sua presença está confirmada para {{horario}}. Até logo!',
        cancellationResponseMessage: 'Entendido, {{nome}}. Seu agendamento foi cancelado. Se precisar remarcar, é só me avisar!',
        rescheduleResponseMessage: 'Claro, {{nome}}! Vamos remarcar. Qual horário seria melhor para você?',
        awaitingResponseTimeout: 60,
        maxReminders: 2,
      },

      // Localizacao da empresa
      location_latitude: body.location_latitude || null,
      location_longitude: body.location_longitude || null,
      location_name: body.location_name || null,
      location_address: body.location_address || null,
      // Servicos/Procedimentos configurados
      services: body.services || [],
      // Titulo e descricao padrao para reunioes
      meeting_title: body.meeting_title || null,
      meeting_description: body.meeting_description || null,
      // RAG (Base de Conhecimento)
      rag_enabled: body.rag_enabled || false,
      // Leadbox Handoff Config
      handoff_triggers: body.handoff_triggers || null,
      handoff_enabled: body.handoff_triggers?.enabled || false,
      // Observer AI Prompt
      observer_prompt: body.observer_prompt || null,
    };

    // Inserir com ID especifico
    const { data: createdAgent, error: insertError } = await supabaseAdmin
      .from('agents')
      .insert({ id: agentId, ...agentData })
      .select()
      .single();

    if (insertError) {
      Logger.error('Failed to save agent', { error: insertError.message });
      throw new Error(`Failed to save agent: ${insertError.message}`);
    }

    Logger.info('Agent saved successfully', { agentId: createdAgent.id });

    // ========================================================================
    // 8. ATUALIZAR STATUS PARA ACTIVE (ou conectado se usar WhatsApp compartilhado)
    // ========================================================================

    if (usesSharedWhatsApp) {
      // Se usa WhatsApp compartilhado, já está conectado
      await agentsRepo.update(agentId, { status: 'active', uazapi_connected: true });
      Logger.info('Agent with shared WhatsApp status updated to active (already connected)');
    } else {
      await agentsRepo.update(agentId, { status: 'active' });
      Logger.info('Agent status updated to active');
    }

    // ========================================================================
    // 8.5 AUTO-LINK DIANA ↔ AGNES
    // ========================================================================
    // Quando Diana é criada: busca Agnes do mesmo usuário e configura handoff
    // Quando Agnes é criada: atualiza Diana existente para apontar para Agnes

    if (body.type === 'diana') {
      // Diana criada: buscar Agnes existente do mesmo usuário
      const { data: existingAgnes } = await supabaseAdmin
        .from('agents')
        .select('id, name')
        .eq('user_id', userId)
        .eq('type', 'agnes')
        .eq('active', true)
        .limit(1)
        .single();

      if (existingAgnes) {
        // Atualiza Diana para apontar para Agnes
        await supabaseAdmin.from('agents').update({
          handoff_target_agent_id: existingAgnes.id,
          handoff_enabled: true,
        }).eq('id', agentId);

        Logger.info('Diana auto-linked to existing Agnes', {
          dianaId: agentId,
          agnesId: existingAgnes.id,
          agnesName: existingAgnes.name,
        });
      } else {
        Logger.info('No Agnes found for Diana - handoff will be configured when Agnes is created', { dianaId: agentId });
      }
    }

    if (body.type === 'agnes') {
      // Agnes criada: atualizar Diana existente do mesmo usuário
      const { data: existingDiana } = await supabaseAdmin
        .from('agents')
        .select('id, name')
        .eq('user_id', userId)
        .eq('type', 'diana')
        .eq('active', true)
        .limit(1)
        .single();

      if (existingDiana) {
        // Atualiza Diana para apontar para esta Agnes
        await supabaseAdmin.from('agents').update({
          handoff_target_agent_id: agentId,
          handoff_enabled: true,
        }).eq('id', existingDiana.id);

        Logger.info('Existing Diana auto-linked to new Agnes', {
          dianaId: existingDiana.id,
          dianaName: existingDiana.name,
          agnesId: agentId,
        });
      } else {
        Logger.info('No Diana found - will be linked when Diana is created', { agnesId: agentId });
      }
    }

    // ========================================================================
    // 9. RETORNAR SUCESSO
    // ========================================================================

    const response: CreateAgentResponse = {
      agent_id: agentId,
      qr_code_url: usesSharedWhatsApp ? '' : `/api/agents/${agentId}/qr`,
      webhook_url: webhookUrl,
      status: 'success',
      message: usesSharedWhatsApp
        ? 'Agent criado com sucesso usando WhatsApp compartilhado'
        : 'Agent criado com sucesso',
      uses_shared_whatsapp: usesSharedWhatsApp,
      parent_agent_id: parentAgentId,
      whatsapp_already_connected: usesSharedWhatsApp,
    };

    return reply.status(201).send(response);

  } catch (error) {
    Logger.error('=== ERRO CRIANDO AGENTE ===', {
      error: error instanceof Error ? error.message : error,
      stack: error instanceof Error ? error.stack : undefined,
      agentId,
      tableLeads,
    });
    console.error('FULL ERROR:', error);

    // ========================================================================
    // ROLLBACK
    // ========================================================================

    try {
      // Deletar agent se foi criado
      if (agentId) {
        Logger.info('Rolling back: deleting agent', { agentId });
        await supabaseAdmin.from('agents').delete().eq('id', agentId);
      }

      // Deletar tabelas se foram criadas
      // SEGURANÇA CRÍTICA: NÃO dropar tabelas herdadas de agente pai (tipo Salvador/shared)
      // pois as tabelas pertencem ao agente pai e seriam destruídas junto com os dados dele.
      if (tableLeads && tableMessages && !usesSharedWhatsApp) {
        Logger.info('Rolling back: dropping tables', { tableMsgTemp });
        const dynamicRepo = new DynamicRepository(supabaseAdmin);
        let dropSQL = `
          DROP TABLE IF EXISTS "${tableLeads}" CASCADE;
          DROP TABLE IF EXISTS "${tableMessages}" CASCADE;
        `;
        if (tableMsgTemp) {
          dropSQL += `DROP TABLE IF EXISTS "${tableMsgTemp}" CASCADE;`;
        }
        await dynamicRepo.executeRawSQL(dropSQL);
      } else if (usesSharedWhatsApp) {
        Logger.info('Rolling back: skipping table drop for shared/parent tables', { tableLeads, tableMessages });
      }

      // UAZAPI: Não precisa rollback aqui pois instância é criada apenas no qrcode.handler

    } catch (rollbackError) {
      Logger.error('Rollback failed', {
        error: rollbackError instanceof Error ? rollbackError.message : rollbackError,
      });
    }

    return reply.status(500).send({
      status: 'error',
      message: 'Erro interno ao criar agente. Por favor, tente novamente.',
    });
  }
}
