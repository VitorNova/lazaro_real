/**
 * Handler para status de conexão UAZAPI
 */

import { FastifyRequest, FastifyReply } from 'fastify';
import { agentsRepository } from '../../services/supabase/repositories/agents.repository';
import { createUazapiClient } from '../../services/uazapi';

const logger = {
  info: (msg: string, data?: unknown) => console.info(`[UazapiStatus] ${msg}`, data ?? ''),
  warn: (msg: string, data?: unknown) => console.warn(`[UazapiStatus] ${msg}`, data ?? ''),
  error: (msg: string, data?: unknown) => console.error(`[UazapiStatus] ${msg}`, data ?? ''),
};

interface AgentParams {
  agentId: string;
}

/**
 * GET /api/agents/:agentId/uazapi/status
 * Retorna status da conexão UAZAPI com número do WhatsApp
 * Suporta agentes com WhatsApp compartilhado (uses_shared_whatsapp)
 */
export async function getUazapiStatusHandler(
  request: FastifyRequest<{ Params: AgentParams }>,
  reply: FastifyReply
) {
  const { agentId } = request.params;

  try {
    const agent = await agentsRepository.findById(agentId);
    if (!agent) {
      return reply.status(404).send({ error: 'Agent not found' });
    }

    // Verificar se usa UAZAPI
    if (agent.whatsapp_provider !== 'uazapi') {
      return reply.send({
        provider: agent.whatsapp_provider,
        uazapi_configured: false,
        message: 'Agent is not using UAZAPI',
      });
    }

    let uazapiConfig = agent as any;
    let isSharedWhatsApp = false;
    let parentAgentName: string | null = null;

    // Se usa WhatsApp compartilhado, buscar credenciais do parent
    if (uazapiConfig.uses_shared_whatsapp && uazapiConfig.parent_agent_id) {
      logger.info('Agent uses shared WhatsApp, fetching parent credentials', {
        agentId,
        parentId: uazapiConfig.parent_agent_id,
      });

      const parentAgent = await agentsRepository.findById(uazapiConfig.parent_agent_id);
      if (parentAgent) {
        uazapiConfig = {
          ...uazapiConfig,
          uazapi_base_url: (parentAgent as any).uazapi_base_url,
          uazapi_token: (parentAgent as any).uazapi_token,
          uazapi_instance_id: (parentAgent as any).uazapi_instance_id,
          uazapi_instance_name: (parentAgent as any).uazapi_instance_name,
        };
        isSharedWhatsApp = true;
        parentAgentName = parentAgent.name;
      }
    }

    if (!uazapiConfig.uazapi_base_url || !uazapiConfig.uazapi_token) {
      return reply.send({
        provider: 'uazapi',
        uazapi_configured: false,
        message: 'UAZAPI credentials not configured',
        uses_shared_whatsapp: isSharedWhatsApp,
      });
    }

    // Verificar status da conexão
    try {
      const client = createUazapiClient({
        baseUrl: uazapiConfig.uazapi_base_url,
        apiKey: uazapiConfig.uazapi_token,
      });

      const status = await client.getConnectionStatus();

      // Extrair número do telefone do JID
      let phoneNumber = status.phone_number || status.jid || null;
      if (phoneNumber) {
        // Remover sufixo @s.whatsapp.net
        if (phoneNumber.includes('@')) {
          phoneNumber = phoneNumber.split('@')[0];
        }
        // Remover sufixo :XX (device ID)
        if (phoneNumber.includes(':')) {
          phoneNumber = phoneNumber.split(':')[0];
        }
      }

      // Atualizar status no banco se diferente
      const isConnected = status.connected || status.loggedIn;
      if (isConnected !== (agent as any).uazapi_connected) {
        await agentsRepository.update(agentId, {
          uazapi_connected: isConnected,
        } as any);
        logger.info('Updated agent connection status', {
          agentId,
          previousStatus: (agent as any).uazapi_connected,
          newStatus: isConnected,
          isSharedWhatsApp,
        });
      }

      return reply.send({
        provider: 'uazapi',
        uazapi_configured: true,
        instance_id: uazapiConfig.uazapi_instance_id,
        instance_name: uazapiConfig.uazapi_instance_name,
        connection_state: status.status || 'unknown',
        connected: isConnected,
        phone_number: phoneNumber,
        profile_name: status.instance?.profileName || null,
        profile_picture: status.instance?.profilePicUrl || null,
        uses_shared_whatsapp: isSharedWhatsApp,
        parent_agent_name: parentAgentName,
      });
    } catch (error) {
      logger.error('Error getting UAZAPI status', error);
      return reply.send({
        provider: 'uazapi',
        uazapi_configured: true,
        instance_id: uazapiConfig.uazapi_instance_id,
        connection_state: 'error',
        connected: (agent as any).uazapi_connected || false,
        phone_number: null,
        error: error instanceof Error ? error.message : 'Unknown error',
        uses_shared_whatsapp: isSharedWhatsApp,
        parent_agent_name: parentAgentName,
      });
    }
  } catch (error) {
    logger.error('Error getting agent', error);
    return reply.status(500).send({ error: 'Internal server error' });
  }
}
