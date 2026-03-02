import { FastifyRequest, FastifyReply } from 'fastify';
import { supabaseAdmin } from '../../services/supabase/client';

// ============================================================================
// LOGGER
// ============================================================================

const Logger = {
  info: (msg: string, data?: unknown) => console.info(`[UpdateAgent] ${msg}`, data ?? ''),
  warn: (msg: string, data?: unknown) => console.warn(`[UpdateAgent] ${msg}`, data ?? ''),
  error: (msg: string, data?: unknown) => console.error(`[UpdateAgent] ${msg}`, data ?? ''),
};

// ============================================================================
// TYPES
// ============================================================================

export interface UpdateAgentParams {
  id: string;
}

export interface UpdateAgentBody {
  // Informacoes basicas
  name?: string;
  status?: 'active' | 'paused';

  // AI Config
  ai_provider?: 'gemini' | 'claude' | 'openai';
  gemini_api_key?: string;
  gemini_model?: string;
  claude_api_key?: string;
  claude_model?: string;
  openai_api_key?: string;
  openai_model?: string;
  system_prompt?: string;

  // Notificacoes
  owner_phone?: string | null;

  // Produto
  product_description?: string;
  product_value?: number;

  // Horario de funcionamento
  business_hours?: {
    start: string;
    end: string;
  };
  work_days?: string[];
  timezone?: string;

  // Google Calendar
  google_calendar_enabled?: boolean;
  google_calendar_id?: string;
  google_credentials?: Record<string, unknown>;
  google_accounts?: Array<{
    email: string;
    credentials: Record<string, unknown>;
    calendar_id?: string;
    work_days?: Record<string, boolean>;
    morning_enabled?: boolean;
    morning_start?: string;
    morning_end?: string;
    afternoon_enabled?: boolean;
    afternoon_start?: string;
    afternoon_end?: string;
    // Duracao da reuniao em minutos (15, 30, 45 ou 60). Default: 60
    meeting_duration?: number;
  }>;

  // Asaas
  asaas_enabled?: boolean;
  asaas_api_key?: string;
  asaas_environment?: 'sandbox' | 'production';
  asaas_config?: {
    useDynamicPricing?: boolean;
    products: Array<{
      name: string;
      value: number;
      isDynamic?: boolean;
      chargeType?: 'DETACHED' | 'RECURRENT';
      subscriptionCycle?: 'WEEKLY' | 'BIWEEKLY' | 'MONTHLY' | 'BIMONTHLY' | 'QUARTERLY' | 'SEMIANNUALLY' | 'YEARLY';
      allowInstallments: boolean;
      maxInstallments: number;
    }>;
    billingTypes: ('PIX' | 'CREDIT_CARD' | 'BOLETO')[];
    defaultDueDays: number;
  };

  // Follow-up
  follow_up_enabled?: boolean;
  follow_up_config?: {
    inactivity?: {
      enabled: boolean;
      delays: number[];
      messages: string[];
      steps?: Array<{
        delayMinutes: number;
        useAI: boolean;
        message: string;
      }>;
    };
    nurture?: {
      enabled: boolean;
      delays: number[];
      messages: string[];
      steps?: Array<{
        delayMinutes: number;
        useAI: boolean;
        message: string;
      }>;
    };
    reminder?: {
      enabled: boolean;
      minutesBefore: number;
      useAI?: boolean;
      message?: string;
    };
  };

  // Salvador config (multi-agent)
  salvador_config?: {
    global?: {
      workHoursStart?: string;
      workHoursEnd?: string;
      workDays?: string[];
    };
    agents?: Record<string, unknown>;
  };

  // Qualification
  qualification_enabled?: boolean;
  qualification_config?: {
    qualifyAfterMessages?: number;
    bantCriteria?: {
      budget: string;
      authority: string;
      need: string;
      timing: string;
    };
    fitCriteria?: {
      companySize: string;
      industry: string;
      digitalMaturity: string;
    };
    hotLeadThreshold?: number;
    warmLeadThreshold?: number;
    spinSellingEnabled?: boolean;
    // Configuração dinâmica de critérios BANT habilitados
    bantEnabled?: {
      budget: boolean;    // Orçamento
      authority: boolean; // Autoridade/Decisor
      need: boolean;      // Necessidade
      timing: boolean;    // Prazo/Urgência
    };
  };

  // Pipeline
  pipeline_stages?: Array<{
    order: number;
    name: string;
    slug: string;
    icon: string;
    color: string;
    description_for_ai: string;
  }>;

  // Meeting
  meeting_duration?: number;
  meeting_title?: string;
  meeting_description?: string;
  services?: Array<{
    name: string;
    duration: number;
    isDefault?: boolean;
  }>;

  // Schedule Confirmation
  schedule_confirmation_enabled?: boolean;
  schedule_confirmation_config?: {
    intervals: Array<{
      enabled: boolean;
      minutesBefore: number;
      messageTemplate: string | null;
    }>;
    maxReminders: number;
    positiveKeywords: string[];
    negativeKeywords: string[];
    rescheduleKeywords: string[];
    awaitingResponseTimeout: number;
    confirmationResponseMessage: string;
    cancellationResponseMessage: string;
    rescheduleResponseMessage: string;
    defaultConfirmationMessage24h: string;
    defaultConfirmationMessage2h: string;
  };

  // Response size
  response_size?: 'short' | 'medium' | 'long';
  split_messages?: boolean;
  split_mode?: 'smart' | 'paragraph' | 'natural'; // Modo de quebra de mensagens
  message_buffer_delay?: number; // Delay em ms para aguardar mais mensagens

  // Diana specific - campos legados
  diana_company_name?: string;
  diana_company_description?: string;
  diana_agent_name?: string;
  diana_system_prompt?: string;  // Prompt unificado (novo)
  diana_prompt_agent1?: string;  // Legado
  diana_prompt_agent2?: string;  // Legado
  prospect_source?: 'google_only' | 'excel_only' | 'both';
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
  google_places_api_key?: string;

  // Diana specific - campos simplificados (novos)
  empresa?: string;
  produto?: string;
  beneficio?: string;
  preco?: string;
  vendedor_nome?: string;
  vendedor_whatsapp?: string;

  // Diana specific - horário de funcionamento
  diana_send_start_time?: string;
  diana_send_end_time?: string;
  diana_work_days?: string[];

  // Handoff config
  handoff_enabled?: boolean;
  handoff_type?: 'agnes' | 'human';
  handoff_target_agent_id?: string | null;
  handoff_target_agent_name?: string | null;
  handoff_human_name?: string | null;
  handoff_human_whatsapp?: string | null;
  handoff_triggers?: {
    decisionMakerFound?: boolean;
    bantScoreMin?: number;
    interestDetected?: boolean;
  };
  handoff_condition_prompt?: string | null;
  handoff_trigger_score?: number;
  handoff_trigger_decisor?: boolean;
  handoff_trigger_interest?: boolean;

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


  // Localizacao da empresa
  location_latitude?: number | null;
  location_longitude?: number | null;
  location_name?: string | null;
  location_address?: string | null;

  // RAG (Base de Conhecimento)
  rag_enabled?: boolean;
  // Observer AI Prompt
  observer_prompt?: string | null;

  // Context Prompts (prompts dinâmicos por contexto: billing, manutencao, etc)
  context_prompts?: Record<string, {
    nome: string;
    descricao?: string;
    prompt: string;
    ativo: boolean;
  }> | null;
}

// ============================================================================
// HANDLER
// ============================================================================

export async function updateAgentHandler(
  request: FastifyRequest<{ Params: UpdateAgentParams; Body: UpdateAgentBody }>,
  reply: FastifyReply
) {
  const { id: agentId } = request.params;
  // Prioridade: 1) request.user do JWT middleware, 2) x-user-id header (legado)
  const userId = (request as any).user?.id || request.headers['x-user-id'] as string;
  const body = request.body;

  if (!userId) {
    return reply.status(401).send({
      status: 'error',
      message: 'Unauthorized: Authentication required',
    });
  }

  Logger.info(`Atualizando agente ${agentId}`, { userId, fields: Object.keys(body) });

  try {
    // ========================================================================
    // 1. VERIFICAR SE O AGENTE EXISTE E PERTENCE AO USUARIO
    // ========================================================================

    const { data: existingAgent, error: fetchError } = await supabaseAdmin
      .from('agents')
      .select('id, user_id, name, type')
      .eq('id', agentId)
      .eq('user_id', userId)
      .single();

    if (fetchError || !existingAgent) {
      Logger.error('Agente nao encontrado', { agentId, userId, error: fetchError });
      return reply.status(404).send({
        status: 'error',
        message: 'Agente nao encontrado',
      });
    }

    // ========================================================================
    // 2. PREPARAR DADOS PARA UPDATE
    // ========================================================================

    const updateData: Record<string, unknown> = {
      updated_at: new Date().toISOString(),
    };

    // Campos basicos
    if (body.name !== undefined) updateData.name = body.name;
    if (body.status !== undefined) updateData.status = body.status;

    // AI Config
    if (body.ai_provider !== undefined) updateData.ai_provider = body.ai_provider;
    if (body.gemini_api_key !== undefined) updateData.gemini_api_key = body.gemini_api_key;
    if (body.gemini_model !== undefined) updateData.gemini_model = body.gemini_model;
    if (body.claude_api_key !== undefined) updateData.claude_api_key = body.claude_api_key;
    if (body.claude_model !== undefined) updateData.claude_model = body.claude_model;
    if (body.openai_api_key !== undefined) updateData.openai_api_key = body.openai_api_key;
    if (body.openai_model !== undefined) updateData.openai_model = body.openai_model;
    if (body.system_prompt !== undefined) updateData.system_prompt = body.system_prompt;

    // Notificacoes
    if (body.owner_phone !== undefined) updateData.owner_phone = body.owner_phone;

    // Produto
    if (body.product_description !== undefined) updateData.product_description = body.product_description;
    if (body.product_value !== undefined) updateData.product_value = body.product_value;

    // Horario
    if (body.business_hours !== undefined) updateData.business_hours = body.business_hours;
    if (body.work_days !== undefined) updateData.work_days = body.work_days;
    if (body.timezone !== undefined) updateData.timezone = body.timezone;

    // Google Calendar
    if (body.google_calendar_enabled !== undefined) updateData.google_calendar_enabled = body.google_calendar_enabled;
    if (body.google_calendar_id !== undefined) updateData.google_calendar_id = body.google_calendar_id;
    if (body.google_credentials !== undefined) updateData.google_credentials = body.google_credentials;
    if (body.google_accounts !== undefined) updateData.google_accounts = body.google_accounts;

    // Asaas
    if (body.asaas_enabled !== undefined) updateData.asaas_enabled = body.asaas_enabled;
    if (body.asaas_api_key !== undefined) updateData.asaas_api_key = body.asaas_api_key;
    if (body.asaas_environment !== undefined) updateData.asaas_environment = body.asaas_environment;
    if (body.asaas_config !== undefined) updateData.asaas_config = body.asaas_config;

    // Follow-up
    if (body.follow_up_enabled !== undefined) updateData.follow_up_enabled = body.follow_up_enabled;
    if (body.follow_up_config !== undefined) updateData.follow_up_config = body.follow_up_config;

    // Salvador config (multi-agent)
    if (body.salvador_config !== undefined) updateData.salvador_config = body.salvador_config;

    // Qualification
    if (body.qualification_enabled !== undefined) updateData.qualification_enabled = body.qualification_enabled;
    if (body.qualification_config !== undefined) updateData.qualification_config = body.qualification_config;

    // Pipeline
    if (body.pipeline_stages !== undefined) updateData.pipeline_stages = body.pipeline_stages;

    // Meeting
    if (body.meeting_duration !== undefined) updateData.meeting_duration = body.meeting_duration;
    if (body.meeting_title !== undefined) updateData.meeting_title = body.meeting_title;
    if (body.meeting_description !== undefined) updateData.meeting_description = body.meeting_description;
    if (body.services !== undefined) updateData.services = body.services;

    // Schedule Confirmation
    if (body.schedule_confirmation_enabled !== undefined) updateData.schedule_confirmation_enabled = body.schedule_confirmation_enabled;
    if (body.schedule_confirmation_config !== undefined) updateData.schedule_confirmation_config = body.schedule_confirmation_config;

    // Response size
    if (body.response_size !== undefined) updateData.response_size = body.response_size;
    if (body.split_messages !== undefined) updateData.split_messages = body.split_messages;
    if (body.split_mode !== undefined) updateData.split_mode = body.split_mode;
    if (body.message_buffer_delay !== undefined) updateData.message_buffer_delay = body.message_buffer_delay;

    // Diana specific - campos legados
    if (body.diana_company_name !== undefined) updateData.diana_company_name = body.diana_company_name;
    if (body.diana_company_description !== undefined) updateData.diana_company_description = body.diana_company_description;
    if (body.diana_agent_name !== undefined) updateData.diana_agent_name = body.diana_agent_name;
    if (body.prospection_niche !== undefined) updateData.prospection_niche = body.prospection_niche;
    if (body.prospection_niche_custom !== undefined) updateData.prospection_niche_custom = body.prospection_niche_custom;
    if (body.prospection_location_type !== undefined) updateData.prospection_location_type = body.prospection_location_type;
    if (body.prospection_state !== undefined) updateData.prospection_state = body.prospection_state;
    if (body.prospection_city !== undefined) updateData.prospection_city = body.prospection_city;
    if (body.prospection_strategy !== undefined) updateData.prospection_strategy = body.prospection_strategy;
    if (body.prospection_daily_goal !== undefined) updateData.prospection_daily_goal = body.prospection_daily_goal;
    if (body.prospection_sequence !== undefined) updateData.prospection_sequence = body.prospection_sequence;
    if (body.google_places_api_key !== undefined) updateData.google_places_api_key = body.google_places_api_key;

    // Diana specific - prompts (unificado e legados)
    if (body.diana_system_prompt !== undefined) updateData.diana_system_prompt = body.diana_system_prompt;
    if (body.diana_prompt_agent1 !== undefined) updateData.diana_prompt_agent1 = body.diana_prompt_agent1;
    if (body.diana_prompt_agent2 !== undefined) updateData.diana_prompt_agent2 = body.diana_prompt_agent2;
    if (body.prospect_source !== undefined) updateData.prospect_source = body.prospect_source;

    // Diana specific - campos simplificados (novos)
    if (body.empresa !== undefined) updateData.empresa = body.empresa;
    if (body.produto !== undefined) updateData.produto = body.produto;
    if (body.beneficio !== undefined) updateData.beneficio = body.beneficio;
    if (body.preco !== undefined) updateData.preco = body.preco;
    if (body.vendedor_nome !== undefined) updateData.vendedor_nome = body.vendedor_nome;
    if (body.vendedor_whatsapp !== undefined) updateData.vendedor_whatsapp = body.vendedor_whatsapp;

    // Diana specific - horário de funcionamento
    // IMPORTANTE: Campos específicos Diana têm prioridade sobre business_hours genérico
    // Primeiro aplicar business_hours (se existir), depois sobrescrever com campos específicos
    if (body.business_hours !== undefined && existingAgent.type === 'diana') {
      updateData.diana_send_start_time = body.business_hours.start;
      updateData.diana_send_end_time = body.business_hours.end;
    }
    if (body.work_days !== undefined && existingAgent.type === 'diana') {
      updateData.diana_work_days = body.work_days;
    }
    // Campos específicos Diana sobrescrevem business_hours se definidos
    if (body.diana_send_start_time !== undefined) updateData.diana_send_start_time = body.diana_send_start_time;
    if (body.diana_send_end_time !== undefined) updateData.diana_send_end_time = body.diana_send_end_time;
    if (body.diana_work_days !== undefined) updateData.diana_work_days = body.diana_work_days;

    // Handoff config
    if (body.handoff_enabled !== undefined) updateData.handoff_enabled = body.handoff_enabled;
    if (body.handoff_type !== undefined) updateData.handoff_type = body.handoff_type;
    if (body.handoff_target_agent_id !== undefined) updateData.handoff_target_agent_id = body.handoff_target_agent_id;
    if (body.handoff_target_agent_name !== undefined) updateData.handoff_target_agent_name = body.handoff_target_agent_name;
    if (body.handoff_human_name !== undefined) updateData.handoff_human_name = body.handoff_human_name;
    if (body.handoff_human_whatsapp !== undefined) updateData.handoff_human_whatsapp = body.handoff_human_whatsapp;
    if (body.handoff_triggers !== undefined) updateData.handoff_triggers = body.handoff_triggers;
    if (body.handoff_condition_prompt !== undefined) updateData.handoff_condition_prompt = body.handoff_condition_prompt;
    if (body.handoff_trigger_score !== undefined) {
      // Atualiza o objeto handoff_triggers com o novo score (legado)
      updateData.handoff_triggers = {
        bantScoreMin: body.handoff_trigger_score,
        decisionMakerFound: body.handoff_trigger_decisor ?? true,
        interestDetected: body.handoff_trigger_interest ?? true,
      };
    }

    // Prompt Medias (audio, imagem, video) - apenas para agentes Agnes
    if (body.prompt_medias !== undefined) updateData.prompt_medias = body.prompt_medias;


    // Localizacao da empresa
    if (body.location_latitude !== undefined) updateData.location_latitude = body.location_latitude;
    if (body.location_longitude !== undefined) updateData.location_longitude = body.location_longitude;
    if (body.location_name !== undefined) updateData.location_name = body.location_name;
    if (body.location_address !== undefined) updateData.location_address = body.location_address;

    // RAG (Base de Conhecimento)
    if (body.rag_enabled !== undefined) updateData.rag_enabled = body.rag_enabled;

    // Observer AI Prompt
    if (body.observer_prompt !== undefined) updateData.observer_prompt = body.observer_prompt;

    // Context Prompts (prompts dinâmicos por contexto)
    if (body.context_prompts !== undefined) updateData.context_prompts = body.context_prompts;

    // ========================================================================
    // 3. EXECUTAR UPDATE
    // ========================================================================

    Logger.info('Executando update', { agentId, updateData });

    const { data: updatedAgent, error: updateError } = await supabaseAdmin
      .from('agents')
      .update(updateData)
      .eq('id', agentId)
      .eq('user_id', userId)
      .select()
      .single();

    if (updateError) {
      Logger.error('Erro ao atualizar agente', updateError);
      return reply.status(500).send({
        status: 'error',
        message: 'Erro ao atualizar agente',
        details: updateError.message,
      });
    }

    Logger.info(`Agente ${agentId} atualizado com sucesso!`);

    // ========================================================================
    // 3.5 SINCRONIZAR FOLLOW_UP_CONFIG COM SALVADOR_CONFIG (para agents Diana)
    // ========================================================================

    if (existingAgent.type === 'diana' && body.follow_up_config !== undefined) {
      try {
        // Buscar o Salvador que monitora este agent Diana
        const { data: salvadorAgents } = await supabaseAdmin
          .from('agents')
          .select('id, salvador_config')
          .eq('type', 'salvador')
          .not('salvador_config', 'is', null);

        // Encontrar o Salvador que tem este agent na lista de sourceAgents
        const salvadorAgent = salvadorAgents?.find(s => {
          const config = s.salvador_config as Record<string, unknown>;
          const sourceAgents = config?.sourceAgents as string[] | undefined;
          return sourceAgents?.includes(agentId);
        });

        if (salvadorAgent) {
          const currentSalvadorConfig = salvadorAgent.salvador_config as Record<string, unknown>;
          const agentsConfig = (currentSalvadorConfig?.agents || {}) as Record<string, unknown>;
          const currentAgentConfig = (agentsConfig[agentId] || {}) as Record<string, unknown>;

          // Extrair dados do follow_up_config
          const followUpConfig = body.follow_up_config;
          const inactivitySteps = followUpConfig.inactivity?.steps || [];
          const subAgents = (updatedAgent.follow_up_config as any)?.sub_agents || {};

          // Construir nova config para agent1 (Coletor) e agent2 (Qualificador)
          const agent1Steps = inactivitySteps.map((step: any, index: number) => ({
            id: step.id || index + 1,
            delayMinutes: step.delayMinutes,
            delayValue: step.delayValue,
            delayUnit: step.delayUnit,
            useAI: step.useAI ?? true,
            personality: step.personality || 'amigavel',
            prompt: subAgents.coletor?.prompt || step.prompt,
          }));

          // Agent2 pode ter config diferente - se não tiver, usa a mesma do agent1
          const agent2Steps = inactivitySteps.map((step: any, index: number) => ({
            id: step.id || index + 1,
            delayMinutes: step.delayMinutes,
            delayValue: step.delayValue,
            delayUnit: step.delayUnit,
            useAI: step.useAI ?? true,
            personality: step.personality || 'amigavel',
            prompt: subAgents.qualificador?.prompt || step.prompt,
          }));

          // Mesclar com config existente
          const updatedAgentSalvadorConfig = {
            ...currentAgentConfig,
            enabled: followUpConfig.inactivity?.enabled ?? true,
            maxFollowUps: inactivitySteps.length,
            agent1: {
              ...(currentAgentConfig.agent1 as Record<string, unknown> || {}),
              steps: agent1Steps,
              maxFollowUps: inactivitySteps.length,
            },
            agent2: {
              ...(currentAgentConfig.agent2 as Record<string, unknown> || {}),
              steps: agent2Steps,
              maxFollowUps: inactivitySteps.length,
            },
          };

          // Atualizar salvador_config
          const updatedSalvadorConfig = {
            ...currentSalvadorConfig,
            agents: {
              ...agentsConfig,
              [agentId]: updatedAgentSalvadorConfig,
            },
          };

          const { error: salvadorUpdateError } = await supabaseAdmin
            .from('agents')
            .update({ salvador_config: updatedSalvadorConfig })
            .eq('id', salvadorAgent.id);

          if (salvadorUpdateError) {
            Logger.warn('Erro ao sincronizar com Salvador', { error: salvadorUpdateError });
          } else {
            Logger.info(`Salvador sincronizado com follow_up_config da Diana ${agentId}`);
          }
        }
      } catch (syncError) {
        Logger.warn('Erro na sincronizacao com Salvador (nao critico)', { error: syncError });
      }
    }

    // ========================================================================
    // 4. RETORNAR SUCESSO
    // ========================================================================

    return reply.send({
      status: 'success',
      message: 'Agente atualizado com sucesso',
      agent: {
        id: updatedAgent.id,
        name: updatedAgent.name,
        status: updatedAgent.status,
        type: updatedAgent.type,
        updated_at: updatedAgent.updated_at,
      },
    });

  } catch (error) {
    Logger.error('Erro ao atualizar agente', error);
    return reply.status(500).send({
      status: 'error',
      message: error instanceof Error ? error.message : 'Erro desconhecido ao atualizar agente',
    });
  }
}

// ============================================================================
// GET AGENT HANDLER - Para obter dados completos do agente para edicao
// ============================================================================

export async function getAgentHandler(
  request: FastifyRequest<{ Params: { id: string } }>,
  reply: FastifyReply
) {
  const { id: agentId } = request.params;
  // Prioridade: 1) request.user do JWT middleware, 2) x-user-id header (legado)
  const userId = (request as any).user?.id || request.headers['x-user-id'] as string;

  if (!userId) {
    return reply.status(401).send({
      status: 'error',
      message: 'Unauthorized: Authentication required',
    });
  }

  try {
    const { data: agent, error } = await supabaseAdmin
      .from('agents')
      .select('*')
      .eq('id', agentId)
      .eq('user_id', userId)
      .single();

    if (error || !agent) {
      return reply.status(404).send({
        status: 'error',
        message: 'Agente nao encontrado',
      });
    }

    // Remover campos sensiveis da resposta
    const safeAgent = {
      ...agent,
      // Mascarar API keys (mostrar apenas ultimos 4 caracteres)
      gemini_api_key: agent.gemini_api_key
        ? `${'*'.repeat(Math.max(0, agent.gemini_api_key.length - 4))}${agent.gemini_api_key.slice(-4)}`
        : null,
      claude_api_key: agent.claude_api_key
        ? `${'*'.repeat(Math.max(0, agent.claude_api_key.length - 4))}${agent.claude_api_key.slice(-4)}`
        : null,
      openai_api_key: agent.openai_api_key
        ? `${'*'.repeat(Math.max(0, agent.openai_api_key.length - 4))}${agent.openai_api_key.slice(-4)}`
        : null,
      asaas_api_key: agent.asaas_api_key
        ? `${'*'.repeat(Math.max(0, agent.asaas_api_key.length - 4))}${agent.asaas_api_key.slice(-4)}`
        : null,
      google_places_api_key: agent.google_places_api_key
        ? `${'*'.repeat(Math.max(0, agent.google_places_api_key.length - 4))}${agent.google_places_api_key.slice(-4)}`
        : null,
      uazapi_token: agent.uazapi_token ? '********' : null,
    };

    return reply.send({
      status: 'success',
      agent: safeAgent,
    });

  } catch (error) {
    Logger.error('Erro ao buscar agente', error);
    return reply.status(500).send({
      status: 'error',
      message: error instanceof Error ? error.message : 'Erro desconhecido',
    });
  }
}
