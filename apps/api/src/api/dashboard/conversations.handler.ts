import { FastifyRequest, FastifyReply } from 'fastify';
import { supabaseAdmin } from '../../services/supabase/client';
import { removeFromHumanTakeoverCache, markAsHumanTakeover } from '../webhooks/human-takeover';
import { createUazapiClient } from '../../services/uazapi/client';

// ============================================================================
// TYPES (alinhado com message-formatter.ts)
// ============================================================================

interface Conversation {
  id: string;
  phone: string;
  name: string;
  lastMessage: string;
  lastMessageAt: string;
  unreadCount: number;
  agent_id: string;
  agent_name: string;
  ai_enabled: boolean;
  lead_id?: number;
}

interface Message {
  id: string;
  content: string;
  sender: 'user' | 'assistant';
  timestamp: string;
  type: string;
  messageType?: 'text' | 'image' | 'audio' | 'document' | 'video';
  mediaUrl?: string;
  fileName?: string;
  mimeType?: string;
  duration?: number;
}

// Estrutura do conversation_history salvo no banco (de message-formatter.ts)
interface ConversationMessage {
  role: 'user' | 'model' | 'assistant';
  content?: string;
  /** Formato Gemini: parts[].text contém o conteúdo da mensagem */
  parts?: Array<{ text?: string }>;
  timestamp?: string;
  /** Quem enviou a mensagem: 'ai' para IA, 'human' para atendente humano */
  sender?: 'ai' | 'human';
  /** Nome do atendente quando sender é 'human' */
  sender_name?: string | null;
  /** Tipo de mensagem: text, image, audio, document, video */
  messageType?: 'text' | 'image' | 'audio' | 'document' | 'video';
  /** URL da mídia (imagem, áudio, documento, vídeo) */
  mediaUrl?: string;
  /** Nome do arquivo para documentos */
  fileName?: string;
  /** MIME type da mídia */
  mimeType?: string;
  /** Duração em segundos (para áudio/vídeo) */
  duration?: number;
}

interface ConversationHistory {
  messages: ConversationMessage[];
  lastUpdated?: string;
}

// ============================================================================
// GET ALL CONVERSATIONS (Lista de conversas) - OTIMIZADO
// ============================================================================

export async function getConversationsHandler(
  request: FastifyRequest<{ Querystring: { user_id?: string; agent_id?: string; limit?: string; offset?: string } }>,
  reply: FastifyReply
) {
  try {
    const { agent_id, limit: limitStr, offset: offsetStr } = request.query;
    // Prioridade: 1) request.user do JWT middleware, 2) query param (legado)
    const user_id = (request as any).user?.id || request.query.user_id;

    // Paginação com defaults
    const limit = Math.min(parseInt(limitStr || '50', 10), 100); // Max 100
    const offset = parseInt(offsetStr || '0', 10);

    if (!user_id) {
      return reply.status(400).send({ status: 'error', message: 'Authentication required' });
    }

    // Buscar agentes do usuario
    let agentsQuery = supabaseAdmin
      .from('agents')
      .select('id, name, table_leads, table_messages')
      .eq('user_id', user_id);

    if (agent_id) {
      agentsQuery = agentsQuery.eq('id', agent_id);
    }

    const { data: agents, error: agentsError } = await agentsQuery;

    if (agentsError) {
      console.error('[ConversationsHandler] Error fetching agents:', agentsError);
      return reply.status(500).send({ status: 'error', message: 'Error fetching agents' });
    }

    if (!agents || agents.length === 0) {
      return reply.send({
        status: 'success',
        data: {
          conversations: [],
          total: 0,
        },
      });
    }

    const allConversations: Conversation[] = [];
    const processedTables = new Set<string>(); // Evitar duplicatas de tabelas compartilhadas

    // Criar mapa de agentes para lookup rápido por ID
    const agentsMap = new Map<string, { id: string; name: string }>();
    for (const ag of agents) {
      agentsMap.set(ag.id, { id: ag.id, name: ag.name });
    }

    // Buscar conversas de cada agente - OTIMIZADO
    for (const agent of agents) {
      if (!agent.table_messages) continue;

      // Se a tabela já foi processada por outro agente (ex: Salvador usa mesma tabela que Agnes), pular
      if (processedTables.has(agent.table_messages)) {
        continue;
      }
      processedTables.add(agent.table_messages);

      try {
        // OTIMIZAÇÃO 1: Buscar apenas campos necessários + limite
        // Não buscar conversation_history inteiro, só os metadados
        const { data: messagesData, error: msgError } = await supabaseAdmin
          .from(agent.table_messages)
          .select('id, remotejid, creat, conversation_history->lastUpdated, conversation_history->messages')
          .order('creat', { ascending: false })
          .limit(limit + offset); // Buscar um pouco mais para paginação

        if (msgError) {
          console.error(`[ConversationsHandler] Error fetching messages for agent ${agent.id}:`, msgError);
          continue;
        }

        if (!messagesData || messagesData.length === 0) continue;

        // OTIMIZAÇÃO 2: Buscar todos os leads de uma vez (batch)
        // Incluir current_agent_id para roteamento correto entre agentes
        const remoteJids = messagesData.map(m => m.remotejid).filter(Boolean);
        let leadsMap: Map<string, { id: number; nome: string | null; Atendimento_Finalizado: string | null; current_agent_id: string | null }> = new Map();

        if (agent.table_leads && remoteJids.length > 0) {
          // Tentar com current_agent_id primeiro
          let { data: leadsData, error: leadsError } = await supabaseAdmin
            .from(agent.table_leads)
            .select('id, nome, remotejid, "Atendimento_Finalizado", current_agent_id')
            .in('remotejid', remoteJids);

          // Fallback se current_agent_id não existir
          if (leadsError?.code === '42703') {
            const fallbackResult = await supabaseAdmin
              .from(agent.table_leads)
              .select('id, nome, remotejid, "Atendimento_Finalizado"')
              .in('remotejid', remoteJids);
            leadsData = fallbackResult.data?.map(l => ({ ...l, current_agent_id: null })) || null;
          }

          if (leadsData) {
            for (const lead of leadsData) {
              if (lead.remotejid) {
                leadsMap.set(lead.remotejid, lead);
              }
            }
          }
        }

        // Processar mensagens
        for (const msgRecord of messagesData) {
          const remoteJid = msgRecord.remotejid;
          if (!remoteJid) continue;

          // Usar dados do lead do batch (sem query adicional)
          const leadData = leadsMap.get(remoteJid);
          const leadName = leadData?.nome || formatPhoneNumber(remoteJid);
          const aiEnabled = leadData?.Atendimento_Finalizado !== 'true';
          const leadId = leadData?.id;

          // Extrair última mensagem de forma eficiente
          let lastMessage = '';
          let lastMessageAt = msgRecord.creat || new Date().toISOString();

          // messages vem do JSONB path
          const messages = (msgRecord as any).messages;
          const lastUpdated = (msgRecord as any).lastUpdated;

          if (messages && Array.isArray(messages) && messages.length > 0) {
            const lastItem = messages[messages.length - 1];
            lastMessage = lastItem?.content || '';
            lastMessageAt = lastItem?.timestamp || lastUpdated || lastMessageAt;
          }

          // Só adicionar se tiver alguma mensagem ou data
          if (lastMessage || msgRecord.creat) {
            // Usar current_agent_id do lead se disponível, senão usar o agente da tabela
            const currentAgentId = leadData?.current_agent_id || agent.id;
            const currentAgent = agentsMap.get(currentAgentId) || { id: agent.id, name: agent.name };

            allConversations.push({
              id: msgRecord.id || remoteJid,
              phone: remoteJid,
              name: leadName,
              lastMessage: truncateMessage(lastMessage),
              lastMessageAt,
              unreadCount: 0,
              agent_id: currentAgent.id,
              agent_name: currentAgent.name,
              ai_enabled: aiEnabled,
              lead_id: leadId,
            });
          }
        }
      } catch (err) {
        console.error(`[ConversationsHandler] Error processing agent ${agent.id}:`, err);
      }
    }

    // Ordenar por ultima mensagem (mais recente primeiro)
    allConversations.sort((a, b) =>
      new Date(b.lastMessageAt).getTime() - new Date(a.lastMessageAt).getTime()
    );

    // Aplicar paginação no resultado final
    const paginatedConversations = allConversations.slice(offset, offset + limit);

    return reply.send({
      status: 'success',
      data: {
        conversations: paginatedConversations,
        total: allConversations.length,
        limit,
        offset,
        hasMore: offset + limit < allConversations.length,
      },
    });
  } catch (error) {
    console.error('[ConversationsHandler] Error:', error);
    return reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

// ============================================================================
// GET CONVERSATION MESSAGES (Mensagens de uma conversa)
// ============================================================================

export async function getConversationMessagesHandler(
  request: FastifyRequest<{
    Params: { phone: string };
    Querystring: { user_id?: string; agent_id?: string }
  }>,
  reply: FastifyReply
) {
  try {
    const { phone } = request.params;
    const { agent_id } = request.query;
    // Prioridade: 1) request.user do JWT middleware, 2) query param (legado)
    const user_id = (request as any).user?.id || request.query.user_id;

    if (!user_id) {
      return reply.status(400).send({ status: 'error', message: 'Authentication required' });
    }

    if (!phone) {
      return reply.status(400).send({ status: 'error', message: 'phone is required' });
    }

    // Buscar agente
    let agentQuery = supabaseAdmin
      .from('agents')
      .select('id, name, table_messages')
      .eq('user_id', user_id);

    if (agent_id) {
      agentQuery = agentQuery.eq('id', agent_id);
    }

    const { data: agents, error: agentsError } = await agentQuery;

    if (agentsError || !agents || agents.length === 0) {
      return reply.status(404).send({ status: 'error', message: 'Agent not found' });
    }

    const allMessages: Message[] = [];

    // Buscar mensagens de cada agente
    for (const agent of agents) {
      if (!agent.table_messages) continue;

      try {
        // Decodificar o phone (pode vir URL encoded)
        const decodedPhone = decodeURIComponent(phone);

        // Buscar registro de mensagens pelo remotejid
        let msgRecord = null;

        // Tentar busca exata primeiro
        const { data: exactMatch, error: exactError } = await supabaseAdmin
          .from(agent.table_messages)
          .select('*')
          .eq('remotejid', decodedPhone)
          .single();

        if (!exactError && exactMatch) {
          msgRecord = exactMatch;
        } else {
          // Tentar buscar com variações do remotejid
          const cleanPhone = decodedPhone.replace('@s.whatsapp.net', '').replace(/\D/g, '');

          // Buscar por LIKE
          const { data: likeMatch } = await supabaseAdmin
            .from(agent.table_messages)
            .select('*')
            .like('remotejid', `%${cleanPhone}%`)
            .limit(1)
            .single();

          if (likeMatch) {
            msgRecord = likeMatch;
          }
        }

        if (msgRecord) {
          processMessageRecord(msgRecord, allMessages);
        }
      } catch (err) {
        console.error(`[ConversationMessages] Error processing agent ${agent.id}:`, err);
      }
    }

    // Ordenar por timestamp (mais antigo primeiro para chat)
    allMessages.sort((a, b) =>
      new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
    );

    return reply.send({
      status: 'success',
      data: {
        messages: allMessages,
        total: allMessages.length,
      },
    });
  } catch (error) {
    console.error('[ConversationMessages] Error:', error);
    return reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

function processMessageRecord(msgRecord: any, allMessages: Message[]): void {
  const historyData = msgRecord.conversation_history;

  if (historyData) {
    let history: ConversationHistory | null = null;

    // Pode ser objeto { messages: [...] } ou array direto
    if (typeof historyData === 'object' && 'messages' in historyData) {
      history = historyData as ConversationHistory;
    } else if (Array.isArray(historyData)) {
      history = { messages: historyData as ConversationMessage[] };
    }

    if (history && history.messages && Array.isArray(history.messages)) {
      let msgIndex = 0;
      for (const item of history.messages) {
        // Mapear 'model' para 'assistant' (padrão usado no sistema)
        const sender: 'user' | 'assistant' = item.role === 'user' ? 'user' : 'assistant';

        // Suportar ambos os formatos:
        // - Formato antigo: { content: "texto" }
        // - Formato Gemini: { parts: [{ text: "texto" }] }
        let content = item.content || '';
        if (!content && item.parts && Array.isArray(item.parts) && item.parts.length > 0) {
          content = item.parts[0]?.text || '';
        }

        // Determinar tipo de mensagem baseado nos campos disponíveis
        const messageType = item.messageType || 'text';

        allMessages.push({
          id: `${msgRecord.id}-${msgIndex}`,
          content,
          sender,
          timestamp: item.timestamp || msgRecord.creat || new Date().toISOString(),
          type: 'text',
          messageType,
          mediaUrl: item.mediaUrl,
          fileName: item.fileName,
          mimeType: item.mimeType,
          duration: item.duration,
        });
        msgIndex++;
      }
      return; // Se processou conversation_history, não precisa dos fallbacks
    }
  }

  // Fallback: usar Msg_user e Msg_model se não tiver conversation_history válido
  const baseTime = new Date(msgRecord.creat || Date.now());

  if (msgRecord.Msg_user) {
    allMessages.push({
      id: `${msgRecord.id}-user`,
      content: msgRecord.Msg_user,
      sender: 'user',
      timestamp: baseTime.toISOString(),
      type: 'text',
    });
  }

  if (msgRecord.Msg_model) {
    allMessages.push({
      id: `${msgRecord.id}-model`,
      content: msgRecord.Msg_model,
      sender: 'assistant',
      timestamp: new Date(baseTime.getTime() + 1000).toISOString(),
      type: 'text',
    });
  }
}

function formatPhoneNumber(phone: string): string {
  if (!phone) return 'Desconhecido';
  // Remove @s.whatsapp.net e formata
  const cleanPhone = phone.replace('@s.whatsapp.net', '').replace(/\D/g, '');
  if (cleanPhone.length === 13 && cleanPhone.startsWith('55')) {
    const ddd = cleanPhone.slice(2, 4);
    const part1 = cleanPhone.slice(4, 9);
    const part2 = cleanPhone.slice(9);
    return `+55 ${ddd} ${part1}-${part2}`;
  }
  return phone;
}

function truncateMessage(message: string, maxLength: number = 50): string {
  if (!message) return '';
  if (message.length <= maxLength) return message;
  return message.slice(0, maxLength) + '...';
}

// ============================================================================
// TOGGLE AI STATUS (Pausar/Ativar IA por conversa)
// ============================================================================

export async function toggleAIStatusHandler(
  request: FastifyRequest<{
    Params: { phone: string };
    Body: { agent_id: string; enabled: boolean };
  }>,
  reply: FastifyReply
) {
  try {
    const { phone } = request.params;
    const { agent_id, enabled } = request.body;
    const user_id = (request as any).user?.id || request.headers['x-user-id'];

    if (!user_id) {
      return reply.status(401).send({ status: 'error', message: 'Authentication required' });
    }

    if (!agent_id) {
      return reply.status(400).send({ status: 'error', message: 'agent_id is required' });
    }

    // Buscar agente
    const { data: agent, error: agentError } = await supabaseAdmin
      .from('agents')
      .select('id, table_leads')
      .eq('id', agent_id)
      .eq('user_id', user_id)
      .single();

    if (agentError || !agent) {
      return reply.status(404).send({ status: 'error', message: 'Agent not found' });
    }

    if (!agent.table_leads) {
      return reply.status(400).send({ status: 'error', message: 'Agent has no leads table configured' });
    }

    // Decodificar phone
    const decodedPhone = decodeURIComponent(phone);

    // Sincronizar com cache em memória ANTES de atualizar o banco
    // Isso garante que o estado seja consistente mesmo em cenários de race condition
    if (enabled) {
      // Reativando IA - remover do cache de human takeover
      await removeFromHumanTakeoverCache(decodedPhone, agent_id);
      console.log('[ToggleAI] Removed from human takeover cache', { phone: decodedPhone });
    } else {
      // Pausando IA - adicionar ao cache de human takeover
      await markAsHumanTakeover(decodedPhone, agent_id);
      console.log('[ToggleAI] Added to human takeover cache', { phone: decodedPhone, agentId: agent_id });
    }

    // Atualizar status da IA no lead
    // enabled = true -> IA ativa (Atendimento_Finalizado = 'false')
    // enabled = false -> IA pausada (Atendimento_Finalizado = 'true')
    // Handoff tracking: registrar paused_at/paused_by ou resumed_at
    const now = new Date().toISOString();
    const updateData: Record<string, any> = {
      Atendimento_Finalizado: enabled ? 'false' : 'true',
      responsavel: enabled ? 'AI' : 'Humano',
      updated_date: now,
    };

    if (enabled) {
      // Reativando IA - registrar quando foi retomado
      updateData.resumed_at = now;
    } else {
      // Pausando IA - registrar quando e por quem foi pausado
      updateData.paused_at = now;
      updateData.paused_by = 'Dashboard';
    }

    const { data: updatedLead, error: updateError } = await supabaseAdmin
      .from(agent.table_leads)
      .update(updateData)
      .eq('remotejid', decodedPhone)
      .select('id, nome, "Atendimento_Finalizado"')
      .single();

    if (updateError) {
      console.error('[ToggleAI] Error updating lead:', updateError);

      // Tentar criar o lead se não existir
      if (updateError.code === 'PGRST116') {
        return reply.status(404).send({
          status: 'error',
          message: 'Lead não encontrado para este número'
        });
      }

      return reply.status(500).send({ status: 'error', message: 'Failed to update lead' });
    }

    console.info(`[ToggleAI] AI ${enabled ? 'enabled' : 'disabled'} for ${decodedPhone} (database and cache synced)`);

    return reply.send({
      status: 'success',
      message: enabled ? 'IA reativada para este lead' : 'IA pausada - atendimento humano ativo',
      ai_enabled: enabled,
      lead_id: updatedLead?.id,
    });
  } catch (error) {
    console.error('[ToggleAI] Error:', error);
    return reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

// ============================================================================
// GET AI STATUS (Status da IA por conversa)
// ============================================================================

export async function getAIStatusHandler(
  request: FastifyRequest<{
    Params: { phone: string };
    Querystring: { agent_id: string };
  }>,
  reply: FastifyReply
) {
  try {
    const { phone } = request.params;
    const { agent_id } = request.query;
    const user_id = (request as any).user?.id || request.headers['x-user-id'];

    if (!user_id) {
      return reply.status(401).send({ status: 'error', message: 'Authentication required' });
    }

    if (!agent_id) {
      return reply.status(400).send({ status: 'error', message: 'agent_id is required' });
    }

    // Buscar agente
    const { data: agent, error: agentError } = await supabaseAdmin
      .from('agents')
      .select('id, table_leads')
      .eq('id', agent_id)
      .eq('user_id', user_id)
      .single();

    if (agentError || !agent) {
      return reply.status(404).send({ status: 'error', message: 'Agent not found' });
    }

    if (!agent.table_leads) {
      return reply.send({
        status: 'success',
        ai_enabled: true,
        message: 'No leads table - AI enabled by default'
      });
    }

    // Decodificar phone
    const decodedPhone = decodeURIComponent(phone);

    // Buscar status do lead
    const { data: lead, error: leadError } = await supabaseAdmin
      .from(agent.table_leads)
      .select('id, "Atendimento_Finalizado", responsavel')
      .eq('remotejid', decodedPhone)
      .single();

    if (leadError || !lead) {
      // Lead não existe ainda - IA ativa por padrão
      return reply.send({
        status: 'success',
        ai_enabled: true,
        message: 'Lead not found - AI enabled by default'
      });
    }

    // Atendimento_Finalizado = 'true' significa IA pausada
    const aiEnabled = lead.Atendimento_Finalizado !== 'true';

    return reply.send({
      status: 'success',
      ai_enabled: aiEnabled,
      lead_id: lead.id,
      responsavel: lead.responsavel || (aiEnabled ? 'AI' : 'Humano'),
    });
  } catch (error) {
    console.error('[GetAIStatus] Error:', error);
    return reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

// ============================================================================
// GET PROFILE PICTURE (Foto de perfil do WhatsApp)
// ============================================================================

// Cache simples em memória para fotos de perfil (TTL de 24h)
const profilePictureCache = new Map<string, { url: string | null; cachedAt: number }>();
const CACHE_TTL_MS = 24 * 60 * 60 * 1000; // 24 horas

export async function getProfilePictureHandler(
  request: FastifyRequest<{
    Params: { phone: string };
    Querystring: { agent_id: string };
  }>,
  reply: FastifyReply
) {
  try {
    const { phone } = request.params;
    const { agent_id } = request.query;
    const user_id = (request as any).user?.id || request.headers['x-user-id'];

    if (!user_id) {
      return reply.status(401).send({ status: 'error', message: 'Authentication required' });
    }

    if (!agent_id) {
      return reply.status(400).send({ status: 'error', message: 'agent_id is required' });
    }

    // Decodificar phone
    const decodedPhone = decodeURIComponent(phone);
    const cacheKey = `${agent_id}:${decodedPhone}`;

    // Verificar cache
    const cached = profilePictureCache.get(cacheKey);
    if (cached && Date.now() - cached.cachedAt < CACHE_TTL_MS) {
      return reply.send({
        status: 'success',
        profilePictureUrl: cached.url,
        cached: true,
      });
    }

    // Buscar agente para obter credenciais UAZAPI
    const { data: agent, error: agentError } = await supabaseAdmin
      .from('agents')
      .select('id, uazapi_url, uazapi_token')
      .eq('id', agent_id)
      .eq('user_id', user_id)
      .single();

    if (agentError || !agent) {
      return reply.status(404).send({ status: 'error', message: 'Agent not found' });
    }

    if (!agent.uazapi_url || !agent.uazapi_token) {
      return reply.send({
        status: 'success',
        profilePictureUrl: null,
        message: 'Agent has no UAZAPI credentials configured',
      });
    }

    // Criar cliente UAZAPI e buscar foto
    const uazapiClient = createUazapiClient({
      baseUrl: agent.uazapi_url,
      instanceToken: agent.uazapi_token,
    });

    const profilePictureUrl = await uazapiClient.getProfilePicture(decodedPhone);

    // Salvar no cache
    profilePictureCache.set(cacheKey, {
      url: profilePictureUrl,
      cachedAt: Date.now(),
    });

    return reply.send({
      status: 'success',
      profilePictureUrl,
      cached: false,
    });
  } catch (error) {
    console.error('[GetProfilePicture] Error:', error);
    return reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

// Limpar cache expirado periodicamente (a cada hora)
setInterval(() => {
  const now = Date.now();
  for (const [key, value] of profilePictureCache.entries()) {
    if (now - value.cachedAt >= CACHE_TTL_MS) {
      profilePictureCache.delete(key);
    }
  }
}, 60 * 60 * 1000);
