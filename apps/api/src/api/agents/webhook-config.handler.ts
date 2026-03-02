import { FastifyRequest, FastifyReply } from 'fastify';
import axios from 'axios';
import { agentsRepository } from '../../services/supabase/repositories/agents.repository';
import { getWebhookUrlForAgent } from '../../utils/webhook.utils';

// ============================================================================
// TYPES
// ============================================================================

interface WebhookConfigParams {
  id: string;
}

interface WebhookConfigBody {
  webhook_url?: string;
  events?: string[];
}

interface WebhookConfigResponse {
  success: boolean;
  webhook_configured: boolean;
  url?: string;
  events?: string[];
  error?: string;
}

interface UazapiWebhookResponse {
  webhook?: {
    enabled: boolean;
    url: string;
    events: string[];
  };
  success?: boolean;
}

// ============================================================================
// LOGGER
// ============================================================================

const logger = {
  info: (msg: string, data?: unknown) => console.info(`[WebhookConfig] ${msg}`, data ?? ''),
  warn: (msg: string, data?: unknown) => console.warn(`[WebhookConfig] ${msg}`, data ?? ''),
  error: (msg: string, data?: unknown) => console.error(`[WebhookConfig] ${msg}`, data ?? ''),
  debug: (msg: string, data?: unknown) => console.debug(`[WebhookConfig] ${msg}`, data ?? ''),
};

// ============================================================================
// DEFAULT WEBHOOK EVENTS
// ============================================================================

const DEFAULT_WEBHOOK_EVENTS = [
  'messages.upsert',
  'messages.update',
  'connection.update',
  'qrcode.updated',
];

// ============================================================================
// CONFIGURE WEBHOOK HANDLER
// ============================================================================

export async function configureWebhookHandler(
  request: FastifyRequest<{ Params: WebhookConfigParams; Body: WebhookConfigBody }>,
  reply: FastifyReply
): Promise<FastifyReply> {
  try {
    const { id: agentId } = request.params;
    const body = request.body || {};

    // ========================================================================
    // 1. BUSCAR AGENT NO BANCO
    // ========================================================================

    const agent = await agentsRepository.findById(agentId);

    if (!agent) {
      return reply.status(404).send({
        success: false,
        webhook_configured: false,
        error: 'Agent not found',
      } as WebhookConfigResponse);
    }

    logger.info('Configuring webhook for agent', { agentId, instanceId: agent.uazapi_instance_id });

    // ========================================================================
    // 2. VALIDAR CONFIGURACAO UAZAPI
    // ========================================================================

    if (!agent.uazapi_instance_id || !agent.uazapi_base_url) {
      return reply.status(400).send({
        success: false,
        webhook_configured: false,
        error: 'UAZAPI instance not configured',
      } as WebhookConfigResponse);
    }

    // ========================================================================
    // 3. DETERMINAR URL E EVENTOS
    // ========================================================================

    // URL do webhook - usar fornecida ou gerar baseada no agente (respeita Leadbox)
    let webhookUrl = body.webhook_url;

    if (!webhookUrl) {
      // Usar função centralizada que respeita configuração Leadbox
      webhookUrl = getWebhookUrlForAgent(agent);
      logger.info('Webhook URL auto-detected for agent', {
        agentId: agent.id,
        agentName: agent.name,
        handoffType: agent.handoff_triggers?.type,
        webhookUrl,
      });
    } else {
      logger.info('Using webhook URL from request body', { webhookUrl });
    }

    const events = body.events || DEFAULT_WEBHOOK_EVENTS;

    logger.debug('Webhook configuration', { webhookUrl, events });

    // ========================================================================
    // 4. CONFIGURAR WEBHOOK NA UAZAPI
    // ========================================================================

    try {
      const response = await axios.post<UazapiWebhookResponse>(
        `${agent.uazapi_base_url}/webhook/set/${agent.uazapi_instance_id}`,
        {
          enabled: true,
          url: webhookUrl,
          webhookByEvents: false,
          webhookBase64: false,
          events,
        },
        {
          headers: {
            'Content-Type': 'application/json',
            apikey: agent.uazapi_token || process.env.UAZAPI_API_KEY || '',
          },
          timeout: 15000,
        }
      );

      logger.info('Webhook configured successfully', {
        agentId,
        url: webhookUrl,
        response: response.data,
      });

      return reply.status(200).send({
        success: true,
        webhook_configured: true,
        url: webhookUrl,
        events,
      } as WebhookConfigResponse);

    } catch (error) {
      if (axios.isAxiosError(error)) {
        logger.error('UAZAPI error configuring webhook', {
          status: error.response?.status,
          data: error.response?.data,
        });

        return reply.status(500).send({
          success: false,
          webhook_configured: false,
          error: `UAZAPI error: ${error.response?.data?.message || error.message}`,
        } as WebhookConfigResponse);
      }

      throw error;
    }

  } catch (error) {
    logger.error('Error in configureWebhookHandler', {
      error: error instanceof Error ? error.message : error,
    });

    return reply.status(500).send({
      success: false,
      webhook_configured: false,
      error: error instanceof Error ? error.message : 'Internal server error',
    } as WebhookConfigResponse);
  }
}

// ============================================================================
// GET WEBHOOK CONFIG HANDLER
// ============================================================================

export async function getWebhookConfigHandler(
  request: FastifyRequest<{ Params: WebhookConfigParams }>,
  reply: FastifyReply
): Promise<FastifyReply> {
  try {
    const { id: agentId } = request.params;

    const agent = await agentsRepository.findById(agentId);

    if (!agent) {
      return reply.status(404).send({
        success: false,
        error: 'Agent not found',
      });
    }

    if (!agent.uazapi_instance_id || !agent.uazapi_base_url) {
      return reply.status(400).send({
        success: false,
        error: 'UAZAPI instance not configured',
      });
    }

    try {
      const response = await axios.get(
        `${agent.uazapi_base_url}/webhook/find/${agent.uazapi_instance_id}`,
        {
          headers: {
            apikey: agent.uazapi_token || process.env.UAZAPI_API_KEY || '',
          },
          timeout: 10000,
        }
      );

      return reply.status(200).send({
        success: true,
        webhook: response.data,
      });

    } catch (error) {
      if (axios.isAxiosError(error)) {
        logger.error('UAZAPI error getting webhook config', {
          status: error.response?.status,
          data: error.response?.data,
        });
      }

      return reply.status(200).send({
        success: true,
        webhook: null,
        message: 'No webhook configured',
      });
    }

  } catch (error) {
    logger.error('Error in getWebhookConfigHandler', {
      error: error instanceof Error ? error.message : error,
    });

    return reply.status(500).send({
      success: false,
      error: error instanceof Error ? error.message : 'Internal server error',
    });
  }
}

// ============================================================================
// DELETE WEBHOOK CONFIG HANDLER
// ============================================================================

export async function deleteWebhookConfigHandler(
  request: FastifyRequest<{ Params: WebhookConfigParams }>,
  reply: FastifyReply
): Promise<FastifyReply> {
  try {
    const { id: agentId } = request.params;

    const agent = await agentsRepository.findById(agentId);

    if (!agent) {
      return reply.status(404).send({
        success: false,
        error: 'Agent not found',
      });
    }

    if (!agent.uazapi_instance_id || !agent.uazapi_base_url) {
      return reply.status(400).send({
        success: false,
        error: 'UAZAPI instance not configured',
      });
    }

    try {
      // Desabilitar webhook
      await axios.post(
        `${agent.uazapi_base_url}/webhook/set/${agent.uazapi_instance_id}`,
        {
          enabled: false,
          url: '',
          events: [],
        },
        {
          headers: {
            'Content-Type': 'application/json',
            apikey: agent.uazapi_token || process.env.UAZAPI_API_KEY || '',
          },
          timeout: 10000,
        }
      );

      logger.info('Webhook disabled', { agentId });

      return reply.status(200).send({
        success: true,
        message: 'Webhook disabled',
      });

    } catch (error) {
      if (axios.isAxiosError(error)) {
        logger.error('UAZAPI error deleting webhook', {
          status: error.response?.status,
          data: error.response?.data,
        });
      }

      return reply.status(500).send({
        success: false,
        error: 'Failed to disable webhook',
      });
    }

  } catch (error) {
    logger.error('Error in deleteWebhookConfigHandler', {
      error: error instanceof Error ? error.message : error,
    });

    return reply.status(500).send({
      success: false,
      error: error instanceof Error ? error.message : 'Internal server error',
    });
  }
}
