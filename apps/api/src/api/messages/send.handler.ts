import { FastifyRequest, FastifyReply } from 'fastify';
import { supabaseAdmin } from '../../services/supabase/client';
import { createUazapiClient } from '../../services/uazapi';
import { markAsHumanTakeover } from '../webhooks/human-takeover';
import { identifyAttendant, shouldIdentifyAttendant, getAIProvider } from '../../utils/identify-attendant';

// ============================================================================
// LOGGER
// ============================================================================

const Logger = {
  info: (msg: string, data?: unknown) => console.info(`[SendMessage] ${msg}`, data ?? ''),
  warn: (msg: string, data?: unknown) => console.warn(`[SendMessage] ${msg}`, data ?? ''),
  error: (msg: string, data?: unknown) => console.error(`[SendMessage] ${msg}`, data ?? ''),
};

// ============================================================================
// TYPES
// ============================================================================

export interface SendMessageBody {
  agentId: string;
  leadId: string;
  remoteJid: string;
  message: string;
  messageType?: 'text' | 'image' | 'document' | 'audio' | 'video';
  mediaUrl?: string;
  fileName?: string;
}

export interface SendMessageResponse {
  success: boolean;
  messageId?: string;
  error?: string;
}

// ============================================================================
// HANDLER
// ============================================================================

export async function sendMessageHandler(
  request: FastifyRequest<{ Body: SendMessageBody }>,
  reply: FastifyReply
) {
  const userId = (request as any).user?.id || request.headers['x-user-id'] as string;
  const { agentId, leadId, remoteJid, message, messageType = 'text', mediaUrl, fileName } = request.body;

  if (!userId) {
    return reply.status(401).send({
      success: false,
      error: 'Unauthorized: Authentication required',
    });
  }

  if (!agentId || !remoteJid || !message) {
    return reply.status(400).send({
      success: false,
      error: 'Missing required fields: agentId, remoteJid, message',
    });
  }

  Logger.info('Enviando mensagem', { agentId, leadId, remoteJid, messageType });

  try {
    // ========================================================================
    // 1. BUSCAR AGENTE E VERIFICAR PERMISSAO
    // ========================================================================

    const { data: agent, error: agentError } = await supabaseAdmin
      .from('agents')
      .select('*')
      .eq('id', agentId)
      .eq('user_id', userId)
      .single();

    if (agentError || !agent) {
      Logger.error('Agente nao encontrado', { agentId, userId });
      return reply.status(404).send({
        success: false,
        error: 'Agente nao encontrado',
      });
    }

    // ========================================================================
    // 2. ENVIAR MENSAGEM VIA UAZAPI
    // ========================================================================

    if (!agent.uazapi_base_url || !agent.uazapi_token) {
      return reply.status(400).send({
        success: false,
        error: 'Credenciais UAZAPI não configuradas',
      });
    }

    const uazapiClient = createUazapiClient({
      baseUrl: agent.uazapi_base_url || process.env.UAZAPI_BASE_URL || '',
      apiKey: agent.uazapi_token || '',
    });

    // Verificar se esta conectado
    const isConnected = await uazapiClient.isConnected();
    if (!isConnected) {
      return reply.status(503).send({
        success: false,
        error: 'WhatsApp nao conectado. Verifique a conexao na aba de configuracoes.',
      });
    }

    // Enviar mensagem baseado no tipo
    let response;
    let messageId: string | undefined;
    switch (messageType) {
      case 'image':
        if (!mediaUrl) throw new Error('mediaUrl required for image');
        response = await uazapiClient.sendImage(remoteJid, mediaUrl, message);
        break;
      case 'video':
        if (!mediaUrl) throw new Error('mediaUrl required for video');
        response = await uazapiClient.sendVideo(remoteJid, mediaUrl, message);
        break;
      case 'document':
        if (!mediaUrl || !fileName) throw new Error('mediaUrl and fileName required for document');
        response = await uazapiClient.sendDocument(remoteJid, mediaUrl, fileName, message);
        break;
      case 'audio':
        if (!mediaUrl) throw new Error('mediaUrl required for audio');

        // Recording simulation: usar delay nativo da UAZAPI que mostra "Gravando áudio..."
        const recordingSimulation = agent.recording_simulation !== false; // default: true
        const recordingDelay = recordingSimulation ? (agent.recording_delay || 3000) : 0; // 3 segundos default

        Logger.info('Sending audio with recording delay', { remoteJid, recordingDelay });

        response = await uazapiClient.sendAudio(remoteJid, mediaUrl, true, recordingDelay);
        break;
      default:
        response = await uazapiClient.sendText(remoteJid, message);
    }

    messageId = response.messageid;
    Logger.info('Mensagem enviada via UAZAPI', { messageId });

    // ========================================================================
    // 3. PAUSAR IA E SALVAR MENSAGEM NO HISTORICO
    // ========================================================================
    // Quando humano envia mensagem pela aba Conversas, devemos:
    // - Pausar a IA (Atendimento_Finalizado = 'true')
    // - Registrar timestamp e responsável
    // - Salvar mensagem no histórico com sender: 'human'
    // - Tentar identificar o atendente via IA
    // ========================================================================

    const agora = new Date().toISOString();

    // Buscar nome do usuario que esta enviando
    let senderName = 'Atendente';
    try {
      const { data: userData } = await supabaseAdmin
        .from('users')
        .select('name')
        .eq('id', userId)
        .single();
      if (userData?.name) senderName = userData.name;
    } catch {
      // Ignorar erro - usar nome padrão
    }

    // Buscar tabela de leads do agente
    const tableLeads = agent.table_leads;
    const tableMessages = agent.table_messages;

    if (tableLeads) {
      try {
        // Buscar lead pelo remotejid
        const { data: lead } = await supabaseAdmin
          .from(tableLeads)
          .select('id, nome, responsavel, Atendimento_Finalizado, tentativas_identificacao')
          .eq('remotejid', remoteJid)
          .single();

        if (lead) {
          let cargoIdentificado: string | null = null;

          // Tentar identificar atendente via IA
          if (message && shouldIdentifyAttendant(lead)) {
            const tentativaAtual = (lead.tentativas_identificacao || 0) + 1;
            Logger.info(`Identificando atendente via IA (tentativa ${tentativaAtual}/5)`);

            // Incrementar tentativas
            await supabaseAdmin
              .from(tableLeads)
              .update({ tentativas_identificacao: tentativaAtual })
              .eq('id', lead.id);

            const aiProvider = getAIProvider(agent);
            if (aiProvider) {
              const info = await identifyAttendant({
                mensagemAtendente: message,
                nomeLead: lead.nome || 'Cliente',
                provedor: aiProvider.provedor,
                apiKey: aiProvider.apiKey
              });

              if (info.nome) {
                Logger.info(`Atendente identificado: ${info.nome} (${info.cargo || 'sem cargo'})`);
                senderName = info.nome;
                cargoIdentificado = info.cargo;
              }
            }
          }

          // Pausar IA no banco
          const updateData: Record<string, unknown> = {
            Atendimento_Finalizado: 'true',
            responsavel: senderName,
            pausado_em: agora,
          };
          if (cargoIdentificado) {
            updateData.responsavel_cargo = cargoIdentificado;
          }

          const { error: updateError } = await supabaseAdmin
            .from(tableLeads)
            .update(updateData)
            .eq('id', lead.id);

          if (updateError) {
            // Fallback sem pausado_em (coluna pode não existir)
            delete updateData.pausado_em;
            await supabaseAdmin
              .from(tableLeads)
              .update(updateData)
              .eq('id', lead.id);
          }

          // Marcar no cache em memória também
          await markAsHumanTakeover(remoteJid, agentId);

          Logger.info('IA pausada', {
            leadId: lead.id,
            responsavel: senderName,
            cargo: cargoIdentificado
          });

          // Salvar no histórico de conversas
          if (tableMessages) {
            try {
              const { data: msgRecord } = await supabaseAdmin
                .from(tableMessages)
                .select('id, conversation_history')
                .eq('remotejid', remoteJid)
                .order('creat', { ascending: false })
                .limit(1)
                .single();

              if (msgRecord) {
                const history = msgRecord.conversation_history || { messages: [] };
                const messages = history.messages || [];

                // Montar objeto da mensagem com suporte a mídia
                const msgObj: Record<string, unknown> = {
                  role: 'model',
                  content: message,
                  timestamp: agora,
                  sender: 'human',
                  sender_name: senderName,
                };

                // Incluir dados de mídia se existirem
                if (messageType !== 'text') {
                  msgObj.type = messageType;
                  if (mediaUrl) {
                    msgObj.mediaUrl = mediaUrl;
                  }
                  if (fileName) {
                    msgObj.fileName = fileName;
                  }
                }

                messages.push(msgObj);

                await supabaseAdmin
                  .from(tableMessages)
                  .update({ conversation_history: { messages } })
                  .eq('id', msgRecord.id);

                Logger.info('Mensagem salva no historico', { sender: 'human', senderName });
              }
            } catch (histErr) {
              Logger.warn('Erro ao salvar no historico', histErr);
            }
          }
        } else {
          Logger.warn('Lead nao encontrado para pausar IA', { remoteJid });
        }
      } catch (pauseErr) {
        Logger.warn('Erro ao pausar IA (nao critico)', pauseErr);
      }
    }

    // ========================================================================
    // 4. RETORNAR SUCESSO
    // ========================================================================

    return reply.send({
      success: true,
      messageId,
    });

  } catch (error) {
    Logger.error('Erro ao enviar mensagem', error);
    return reply.status(500).send({
      success: false,
      error: error instanceof Error ? error.message : 'Erro desconhecido ao enviar mensagem',
    });
  }
}

// ============================================================================
// GET MESSAGES HANDLER - Buscar mensagens de um lead
// ============================================================================

export interface GetMessagesParams {
  agentId: string;
  leadId: string;
}

export async function getMessagesHandler(
  request: FastifyRequest<{ Params: GetMessagesParams }>,
  reply: FastifyReply
) {
  const userId = (request as any).user?.id || request.headers['x-user-id'] as string;
  const { agentId, leadId } = request.params;

  if (!userId) {
    return reply.status(401).send({
      success: false,
      error: 'Unauthorized',
    });
  }

  try {
    // Verificar permissao do agente
    const { data: agent, error: agentError } = await supabaseAdmin
      .from('agents')
      .select('id, type, short_id')
      .eq('id', agentId)
      .eq('user_id', userId)
      .single();

    if (agentError || !agent) {
      return reply.status(404).send({
        success: false,
        error: 'Agente nao encontrado',
      });
    }

    let messages;

    if (agent.type === 'leadbox') {
      // Buscar da tabela dinamica
      const shortId = agent.short_id || agentId.substring(0, 8);
      const messagesTable = `leadbox_messages_${shortId}`;

      const { data, error } = await supabaseAdmin
        .from(messagesTable)
        .select('*')
        .eq('lead_id', leadId)
        .order('created_at', { ascending: true });

      if (error) throw error;
      messages = data;
    } else {
      // Buscar da tabela padrao
      const { data, error } = await supabaseAdmin
        .from('messages')
        .select('*')
        .eq('lead_id', leadId)
        .order('created_at', { ascending: true });

      if (error) throw error;
      messages = data;
    }

    return reply.send({
      success: true,
      messages: messages || [],
    });

  } catch (error) {
    Logger.error('Erro ao buscar mensagens', error);
    return reply.status(500).send({
      success: false,
      error: error instanceof Error ? error.message : 'Erro desconhecido',
    });
  }
}
