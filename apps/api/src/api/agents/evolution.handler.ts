/**
 * Handler para operações com Evolution API
 * Endpoints para conectar, desconectar e gerenciar instâncias Evolution
 */

import { FastifyRequest, FastifyReply } from 'fastify';
import { agentsRepository } from '../../services/supabase/repositories/agents.repository';
import { createEvolutionClient, EvolutionClient } from '../../services/evolution';

// ============================================================================
// LOGGER
// ============================================================================

const logger = {
  info: (msg: string, data?: unknown) => console.info(`[Evolution] ${msg}`, data ?? ''),
  warn: (msg: string, data?: unknown) => console.warn(`[Evolution] ${msg}`, data ?? ''),
  error: (msg: string, data?: unknown) => console.error(`[Evolution] ${msg}`, data ?? ''),
};

// ============================================================================
// TYPES
// ============================================================================

interface ConnectEvolutionBody {
  evolution_base_url: string;
  evolution_api_key: string;
  instance_name?: string; // Se não fornecido, cria um novo
  webhook_url?: string;
}

interface AgentParams {
  agentId: string;
}

// ============================================================================
// HELPERS
// ============================================================================

function generateInstanceName(agentId: string): string {
  const shortId = agentId.substring(0, 8);
  return `Agent_${shortId}`;
}

// ============================================================================
// HANDLERS
// ============================================================================

/**
 * GET /api/agents/:agentId/evolution/status
 * Retorna status da conexão Evolution
 */
export async function getEvolutionStatusHandler(
  request: FastifyRequest<{ Params: AgentParams }>,
  reply: FastifyReply
) {
  const { agentId } = request.params;

  try {
    const agent = await agentsRepository.findById(agentId);
    if (!agent) {
      return reply.status(404).send({ error: 'Agent not found' });
    }

    // Verificar se usa Evolution
    if (agent.whatsapp_provider !== 'evolution') {
      return reply.send({
        provider: agent.whatsapp_provider,
        evolution_configured: false,
        message: 'Agent is not using Evolution API',
      });
    }

    const evolutionConfig = agent as any;
    if (!evolutionConfig.evolution_base_url || !evolutionConfig.evolution_api_key) {
      return reply.send({
        provider: 'evolution',
        evolution_configured: false,
        message: 'Evolution credentials not configured',
      });
    }

    // Verificar status da conexão
    const client = createEvolutionClient({
      baseUrl: evolutionConfig.evolution_base_url,
      apiKey: evolutionConfig.evolution_api_key,
      instanceName: evolutionConfig.evolution_instance_name,
    });

    try {
      const status = await client.getConnectionState(evolutionConfig.evolution_instance_name);
      return reply.send({
        provider: 'evolution',
        evolution_configured: true,
        instance_name: evolutionConfig.evolution_instance_name,
        connection_state: status.instance?.state || 'unknown',
        connected: status.instance?.state === 'open',
        phone_number: status.instance?.owner || null,
        profile_name: status.instance?.profileName || null,
        profile_picture: status.instance?.profilePictureUrl || null,
      });
    } catch (error) {
      return reply.send({
        provider: 'evolution',
        evolution_configured: true,
        instance_name: evolutionConfig.evolution_instance_name,
        connection_state: 'error',
        connected: false,
        phone_number: null,
        error: error instanceof Error ? error.message : 'Unknown error',
      });
    }
  } catch (error) {
    logger.error('Error getting Evolution status', error);
    return reply.status(500).send({ error: 'Internal server error' });
  }
}

/**
 * POST /api/agents/:agentId/evolution/connect
 * Conecta agente à Evolution API
 */
export async function connectEvolutionHandler(
  request: FastifyRequest<{ Params: AgentParams; Body: ConnectEvolutionBody }>,
  reply: FastifyReply
) {
  const { agentId } = request.params;
  const { evolution_base_url, evolution_api_key, instance_name, webhook_url } = request.body;

  logger.info('Connecting agent to Evolution', { agentId, evolution_base_url, instance_name });

  try {
    const agent = await agentsRepository.findById(agentId);
    if (!agent) {
      return reply.status(404).send({ error: 'Agent not found' });
    }

    // Criar cliente Evolution
    const client = createEvolutionClient({
      baseUrl: evolution_base_url,
      apiKey: evolution_api_key,
    });

    // Verificar se a instância já existe
    let targetInstanceName = instance_name || generateInstanceName(agentId);
    let qrcode = null;
    let needsQRCode = true;

    try {
      const instances = await client.listInstances();
      const existingInstance = instances.find(i => i.instanceName === targetInstanceName);

      if (existingInstance) {
        logger.info('Instance already exists', { instanceName: targetInstanceName });

        // Verificar se está conectada
        const status = await client.getConnectionState(targetInstanceName);
        if (status.instance?.state === 'open') {
          needsQRCode = false;
          logger.info('Instance already connected');
        } else {
          // Gerar QR Code
          const qrResponse = await client.connect(targetInstanceName);
          qrcode = qrResponse;
        }
      } else {
        // Criar nova instância
        logger.info('Creating new instance', { instanceName: targetInstanceName });

        const webhookEvents = [
          'MESSAGES_UPSERT',
          'MESSAGES_UPDATE',
          'CONNECTION_UPDATE',
          'QRCODE_UPDATED',
        ];

        const createResult = await client.createInstance({
          instanceName: targetInstanceName,
          qrcode: true,
          integration: 'WHATSAPP-BAILEYS',
          webhook: webhook_url || `https://ia.phant.com.br/webhooks/dynamic`,
          webhookByEvents: false,
          webhookBase64: false,
          webhookEvents,
        });

        qrcode = createResult.qrcode;
      }
    } catch (error) {
      logger.error('Error with Evolution instance', error);
      return reply.status(500).send({
        error: 'Failed to setup Evolution instance',
        details: error instanceof Error ? error.message : 'Unknown error',
      });
    }

    // Atualizar agente no banco
    await agentsRepository.update(agentId, {
      whatsapp_provider: 'evolution',
      evolution_base_url,
      evolution_api_key,
      evolution_instance_name: targetInstanceName,
      evolution_connected: !needsQRCode,
    } as any);

    // Configurar webhook se a instância já existia
    if (webhook_url) {
      try {
        await client.setWebhook({
          url: webhook_url,
          webhook_by_events: false,
          webhook_base64: false,
          events: ['MESSAGES_UPSERT', 'MESSAGES_UPDATE', 'CONNECTION_UPDATE'],
        }, targetInstanceName);
        logger.info('Webhook configured', { url: webhook_url });
      } catch (error) {
        logger.warn('Failed to configure webhook', error);
      }
    }

    return reply.send({
      success: true,
      instance_name: targetInstanceName,
      needs_qrcode: needsQRCode,
      qrcode: qrcode?.base64 || qrcode?.code,
      pairing_code: qrcode?.pairingCode,
      message: needsQRCode
        ? 'Scan the QR code to connect WhatsApp'
        : 'Already connected to WhatsApp',
    });
  } catch (error) {
    logger.error('Error connecting to Evolution', error);
    return reply.status(500).send({ error: 'Internal server error' });
  }
}

/**
 * GET /api/agents/:agentId/evolution/qrcode
 * Obtém QR code para conexão Evolution
 */
export async function getEvolutionQRCodeHandler(
  request: FastifyRequest<{ Params: AgentParams }>,
  reply: FastifyReply
) {
  const { agentId } = request.params;

  try {
    const agent = await agentsRepository.findById(agentId);
    if (!agent) {
      return reply.status(404).send({ error: 'Agent not found' });
    }

    const evolutionConfig = agent as any;
    if (!evolutionConfig.evolution_base_url || !evolutionConfig.evolution_api_key) {
      return reply.status(400).send({ error: 'Evolution not configured for this agent' });
    }

    const client = createEvolutionClient({
      baseUrl: evolutionConfig.evolution_base_url,
      apiKey: evolutionConfig.evolution_api_key,
      instanceName: evolutionConfig.evolution_instance_name,
    });

    // Verificar status atual
    try {
      const status = await client.getConnectionState(evolutionConfig.evolution_instance_name);
      if (status.instance?.state === 'open') {
        return reply.send({
          connected: true,
          message: 'Already connected',
        });
      }
    } catch (error) {
      // Instância pode não existir ainda
    }

    // Gerar QR Code
    const qrResponse = await client.connect(evolutionConfig.evolution_instance_name);

    return reply.send({
      connected: false,
      qrcode: qrResponse.base64 || qrResponse.code,
      pairing_code: qrResponse.pairingCode,
    });
  } catch (error) {
    logger.error('Error getting Evolution QR code', error);
    return reply.status(500).send({
      error: 'Failed to get QR code',
      details: error instanceof Error ? error.message : 'Unknown error',
    });
  }
}

/**
 * POST /api/agents/:agentId/evolution/disconnect
 * Desconecta instância Evolution
 */
export async function disconnectEvolutionHandler(
  request: FastifyRequest<{ Params: AgentParams }>,
  reply: FastifyReply
) {
  const { agentId } = request.params;

  try {
    const agent = await agentsRepository.findById(agentId);
    if (!agent) {
      return reply.status(404).send({ error: 'Agent not found' });
    }

    const evolutionConfig = agent as any;
    if (!evolutionConfig.evolution_base_url || !evolutionConfig.evolution_api_key) {
      return reply.status(400).send({ error: 'Evolution not configured for this agent' });
    }

    const client = createEvolutionClient({
      baseUrl: evolutionConfig.evolution_base_url,
      apiKey: evolutionConfig.evolution_api_key,
      instanceName: evolutionConfig.evolution_instance_name,
    });

    await client.logout(evolutionConfig.evolution_instance_name);

    // Atualizar status no banco
    await agentsRepository.update(agentId, {
      evolution_connected: false,
    } as any);

    return reply.send({
      success: true,
      message: 'Disconnected from WhatsApp',
    });
  } catch (error) {
    logger.error('Error disconnecting Evolution', error);
    return reply.status(500).send({ error: 'Failed to disconnect' });
  }
}

/**
 * GET /api/evolution/instances
 * Lista todas as instâncias Evolution disponíveis
 */
export async function listEvolutionInstancesHandler(
  request: FastifyRequest<{ Querystring: { base_url: string; api_key: string } }>,
  reply: FastifyReply
) {
  const { base_url, api_key } = request.query;

  if (!base_url || !api_key) {
    return reply.status(400).send({ error: 'base_url and api_key are required' });
  }

  try {
    const client = createEvolutionClient({
      baseUrl: base_url,
      apiKey: api_key,
    });

    const instances = await client.listInstances();

    // Obter status de cada instância
    const instancesWithStatus = await Promise.all(
      instances.map(async (inst) => {
        try {
          const status = await client.getConnectionState(inst.instanceName);
          return {
            ...inst,
            state: status.instance?.state || 'unknown',
            connected: status.instance?.state === 'open',
          };
        } catch {
          return {
            ...inst,
            state: 'unknown',
            connected: false,
          };
        }
      })
    );

    return reply.send({
      total: instancesWithStatus.length,
      instances: instancesWithStatus,
    });
  } catch (error) {
    logger.error('Error listing Evolution instances', error);
    return reply.status(500).send({
      error: 'Failed to list instances',
      details: error instanceof Error ? error.message : 'Unknown error',
    });
  }
}
