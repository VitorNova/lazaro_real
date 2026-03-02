import { FastifyRequest, FastifyReply } from 'fastify';
import { supabaseAdmin } from '../../services/supabase/client';
import { DynamicRepository } from '../../services/supabase/repositories/dynamic.repository';
import { google } from 'googleapis';

// ============================================================================
// LOGGER
// ============================================================================

const Logger = {
  info: (msg: string, data?: unknown) => console.info(`[DeleteAgent] ${msg}`, data ?? ''),
  warn: (msg: string, data?: unknown) => console.warn(`[DeleteAgent] ${msg}`, data ?? ''),
  error: (msg: string, data?: unknown) => console.error(`[DeleteAgent] ${msg}`, data ?? ''),
};

// ============================================================================
// TYPES
// ============================================================================

export interface DeleteAgentRequest {
  Params: {
    id: string;
  };
}

// ============================================================================
// HANDLER
// ============================================================================

/**
 * Handler para exclusao completa de um agente
 * Remove TUDO que foi criado junto com o agente:
 * - Dados Diana (diana_mensagens, diana_prospects)
 * - Dados em tabelas dinamicas (leads, messages, controle)
 * - Tabelas dinamicas do agente
 * - Agendamentos (schedules)
 * - Tokens Google Calendar (revoga)
 * - Instancia WhatsApp na UAZAPI
 * - Registro do agente
 */
export async function deleteAgentHandler(
  request: FastifyRequest<DeleteAgentRequest>,
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

  Logger.info(`Iniciando exclusao completa do agente ${agentId}`);

  try {
    // ========================================================================
    // 1. BUSCAR DADOS DO AGENTE
    // ========================================================================

    const { data: agent, error: fetchError } = await supabaseAdmin
      .from('agents')
      .select('*')
      .eq('id', agentId)
      .eq('user_id', userId)
      .single();

    if (fetchError || !agent) {
      Logger.error('Agente nao encontrado', { agentId, userId, error: fetchError });
      return reply.status(404).send({
        status: 'error',
        message: 'Agente nao encontrado',
      });
    }

    Logger.info('Agente encontrado', {
      name: agent.name,
      type: agent.type,
      uazapi_instance_id: agent.uazapi_instance_id,
      table_leads: agent.table_leads,
      table_messages: agent.table_messages,
    });

    const errors: string[] = [];
    const dynamicRepo = new DynamicRepository(supabaseAdmin);

    // ========================================================================
    // 2. DELETAR DADOS DIANA (se existirem)
    // ========================================================================

    try {
      Logger.info('Deletando dados Diana...');

      // Primeiro deletar diana_mensagens (tem FK para diana_prospects)
      const { error: dianaMessagesError } = await supabaseAdmin
        .from('diana_mensagens')
        .delete()
        .eq('agent_id', agentId);

      if (dianaMessagesError && !dianaMessagesError.message.includes('does not exist')) {
        Logger.warn('Erro ao deletar diana_mensagens', dianaMessagesError);
      } else {
        Logger.info('diana_mensagens deletadas');
      }

      // Depois deletar diana_prospects
      const { error: dianaProspectsError } = await supabaseAdmin
        .from('diana_prospects')
        .delete()
        .eq('agent_id', agentId);

      if (dianaProspectsError && !dianaProspectsError.message.includes('does not exist')) {
        Logger.warn('Erro ao deletar diana_prospects', dianaProspectsError);
      } else {
        Logger.info('diana_prospects deletados');
      }
    } catch (dianaError) {
      Logger.warn('Erro ao processar dados Diana (tabelas podem nao existir)', dianaError);
    }

    // ========================================================================
    // 3. DELETAR AGENDAMENTOS (schedules)
    // ========================================================================

    try {
      Logger.info('Deletando agendamentos...');

      const { error: schedulesError } = await supabaseAdmin
        .from('schedules')
        .delete()
        .eq('agent_id', agentId);

      if (schedulesError && !schedulesError.message.includes('does not exist')) {
        Logger.warn('Erro ao deletar schedules', schedulesError);
      } else {
        Logger.info('Agendamentos deletados');
      }
    } catch (schedulesDeleteError) {
      Logger.warn('Erro ao deletar agendamentos', schedulesDeleteError);
    }

    // ========================================================================
    // 4. DROPAR TABELAS DINAMICAS DO AGENTE
    // ========================================================================

    try {
      // SEGURANÇA CRÍTICA: Agentes filhos (Salvador, type='salvador') compartilham
      // as tabelas do agente pai (Agnes). Nunca dropar tabelas de agentes filhos,
      // pois isso destruiria os dados do agente pai.
      // Só dropar tabelas de agentes que são donos exclusivos das suas tabelas
      // (agentes sem parent_agent_id).
      const isChildAgent = !!(agent as any).parent_agent_id;

      if (isChildAgent) {
        Logger.info('Agente filho (Salvador/shared) - tabelas compartilhadas com pai, NAO serao dropadas', {
          agentId,
          parentAgentId: (agent as any).parent_agent_id,
          table_leads: agent.table_leads,
          table_messages: agent.table_messages,
        });
      } else {
        Logger.info('Dropando tabelas dinamicas...');

        const tablesToDrop: string[] = [];

        // Usar nomes salvos no agente
        if (agent.table_leads) tablesToDrop.push(agent.table_leads);
        if (agent.table_messages) tablesToDrop.push(agent.table_messages);
        if ((agent as any).table_msg_temp) tablesToDrop.push((agent as any).table_msg_temp);

        // Também tentar formatos alternativos baseados no ID
        const shortId = agentId.split('-')[0];
        const altLeads = `LeadboxCRM_${shortId}`;
        const altMessages = `leadbox_messages_${shortId}`;
        const altMsgTemp = `msg_temp_${shortId}`;

        if (!tablesToDrop.includes(altLeads)) tablesToDrop.push(altLeads);
        if (!tablesToDrop.includes(altMessages)) tablesToDrop.push(altMessages);
        if (!tablesToDrop.includes(altMsgTemp)) tablesToDrop.push(altMsgTemp);

        Logger.info('Tabelas para dropar', { tables: tablesToDrop });

        for (const table of tablesToDrop) {
          if (!table) continue;

          try {
            const dropSQL = `DROP TABLE IF EXISTS "${table}" CASCADE;`;
            const { error } = await dynamicRepo.executeRawSQL(dropSQL);

            if (error) {
              Logger.warn(`Erro ao dropar tabela ${table}`, error);
            } else {
              Logger.info(`Tabela ${table} dropada`);
            }
          } catch (tableError) {
            Logger.warn(`Erro ao dropar tabela ${table}`, tableError);
          }
        }
      }
    } catch (tablesError) {
      Logger.error('Erro ao processar tabelas dinamicas', tablesError);
      errors.push('Falha ao remover algumas tabelas dinamicas');
    }

    // ========================================================================
    // 5. REVOGAR TOKENS GOOGLE CALENDAR
    // ========================================================================

    if (agent.google_credentials) {
      try {
        Logger.info('Revogando tokens Google...');
        const credentials = agent.google_credentials as { refresh_token?: string };

        if (credentials.refresh_token) {
          const oauth2Client = new google.auth.OAuth2(
            process.env.GOOGLE_CLIENT_ID,
            process.env.GOOGLE_CLIENT_SECRET
          );

          try {
            await oauth2Client.revokeToken(credentials.refresh_token);
            Logger.info('Tokens Google revogados');
          } catch (revokeError) {
            Logger.warn('Erro ao revogar tokens Google (pode ja estar expirado)', revokeError);
          }
        }
      } catch (googleError) {
        Logger.error('Erro ao processar Google', googleError);
        errors.push('Erro ao revogar tokens Google');
      }
    }

    // ========================================================================
    // 6. DELETAR INSTANCIA WHATSAPP (UAZAPI ou EVOLUTION)
    // ========================================================================

    // Só deletar se NÃO usa WhatsApp compartilhado
    if (!agent.uses_shared_whatsapp) {
      const whatsappProvider = agent.whatsapp_provider || 'uazapi';

      // ---- EVOLUTION API ----
      if (whatsappProvider === 'evolution') {
        const evolutionInstanceName = agent.evolution_instance_name;
        const evolutionBaseUrl = agent.evolution_base_url || process.env.EVOLUTION_BASE_URL;
        const evolutionApiKey = agent.evolution_api_key || process.env.EVOLUTION_API_KEY;

        if (evolutionInstanceName && evolutionBaseUrl && evolutionApiKey) {
          try {
            Logger.info('[DELETE] Deletando instancia Evolution', {
              instanceName: evolutionInstanceName,
              baseUrl: evolutionBaseUrl
            });

            const { createEvolutionClient } = await import('../../services/evolution/client');
            const evolutionClient = createEvolutionClient({
              baseUrl: evolutionBaseUrl,
              apiKey: evolutionApiKey,
              instanceName: evolutionInstanceName,
            });

            // Primeiro desconectar/logout
            try {
              await evolutionClient.logout(evolutionInstanceName);
              Logger.info('[DELETE] Instancia Evolution desconectada');
            } catch (logoutError) {
              Logger.warn('[DELETE] Erro ao desconectar Evolution (pode ja estar desconectada)', logoutError);
            }

            // Depois deletar a instância
            try {
              await evolutionClient.deleteInstance(evolutionInstanceName);
              Logger.info('[DELETE] Instancia Evolution deletada com sucesso');
            } catch (deleteError) {
              Logger.error('[DELETE] Erro ao deletar instancia Evolution', deleteError);
              errors.push('Falha ao deletar instancia Evolution');
            }
          } catch (evolutionError) {
            Logger.error('[DELETE] Erro ao processar Evolution', evolutionError);
            errors.push('Erro ao processar Evolution API');
          }
        } else {
          Logger.info('[DELETE] Evolution: Agente sem instancia configurada', { evolutionInstanceName });
        }
      }
      // ---- UAZAPI ----
      else {
        const instanceId = agent.uazapi_instance_id;
        const baseUrl = agent.uazapi_base_url;
        const token = agent.uazapi_token;

        if (instanceId && baseUrl && token && !instanceId.startsWith('mock_') && !instanceId.startsWith('CREATING:')) {
          try {
            Logger.info('[DELETE] Deletando instancia UAZAPI', { instanceId, baseUrl });

            const { createUazapiClient } = await import('../../services/uazapi');
            const uazapiClient = createUazapiClient({
              baseUrl,
              instanceToken: token,
            });

            // Primeiro desconectar
            try {
              await uazapiClient.disconnect();
              Logger.info('[DELETE] Instancia UAZAPI desconectada');
            } catch (logoutError) {
              Logger.warn('[DELETE] Erro ao desconectar UAZAPI (pode ja estar desconectada)', logoutError);
            }

            // Depois deletar a instância
            try {
              await uazapiClient.deleteInstance();
              Logger.info('[DELETE] Instancia UAZAPI deletada com sucesso');
            } catch (deleteError) {
              Logger.error('[DELETE] Erro ao deletar instancia UAZAPI', deleteError);
              errors.push('Falha ao deletar instancia UAZAPI');
            }
          } catch (whatsappError) {
            Logger.error('[DELETE] Erro ao processar UAZAPI', whatsappError);
            errors.push('Erro ao processar UAZAPI');
          }
        } else {
          Logger.info('[DELETE] UAZAPI: Agente sem instancia configurada', { instanceId });
        }
      }
    } else {
      Logger.info('[DELETE] Agente usa WhatsApp compartilhado, nao deletando instancia', {
        parentAgentId: agent.parent_agent_id,
      });
    }

    // ========================================================================
    // 7. DELETAR REGISTRO DO AGENTE
    // ========================================================================

    Logger.info('Deletando registro do agente...');

    const { error: deleteError } = await supabaseAdmin
      .from('agents')
      .delete()
      .eq('id', agentId)
      .eq('user_id', userId);

    if (deleteError) {
      Logger.error('Erro ao deletar agente', deleteError);
      return reply.status(500).send({
        status: 'error',
        message: 'Falha ao deletar agente do banco de dados',
        details: deleteError.message,
      });
    }

    Logger.info(`Agente ${agentId} deletado com sucesso!`);

    // ========================================================================
    // 8. RETORNAR SUCESSO
    // ========================================================================

    // Determinar qual instância WhatsApp foi deletada
    const whatsappProvider = agent.whatsapp_provider || 'uazapi';
    const whatsappInstance = agent.uses_shared_whatsapp
      ? null
      : whatsappProvider === 'evolution'
        ? agent.evolution_instance_name
        : agent.uazapi_instance_id;

    return reply.send({
      status: 'success',
      message: 'Agente excluido com sucesso',
      deleted: {
        agent: agentId,
        tables: [agent.table_leads, agent.table_messages, agent.table_msg_temp].filter(Boolean),
        whatsapp_provider: whatsappProvider,
        whatsapp_instance: whatsappInstance,
        diana_data: agent.type === 'diana',
      },
      warnings: errors.length > 0 ? errors : undefined,
    });

  } catch (error) {
    Logger.error('Erro ao excluir agente', error);
    return reply.status(500).send({
      status: 'error',
      message: error instanceof Error ? error.message : 'Erro desconhecido ao excluir agente',
    });
  }
}
