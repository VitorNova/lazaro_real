/**
 * Logger interno do módulo
 */
const Logger = {
  info: (msg: string, data?: unknown) => console.info(`[WebhookUtils] ${msg}`, data ?? ''),
  warn: (msg: string, data?: unknown) => console.warn(`[WebhookUtils] ${msg}`, data ?? ''),
  error: (msg: string, data?: unknown) => console.error(`[WebhookUtils] ${msg}`, data ?? ''),
};

/**
 * Interface para configuração de handoff do agente
 */
export interface HandoffConfig {
  type?: string;
  api_url?: string;
  api_uuid?: string;
  api_token?: string;
}

/**
 * Interface para agente com handoff_triggers
 */
export interface AgentWithHandoff {
  id?: string;
  name?: string;
  handoff_triggers?: HandoffConfig | null;
}

/**
 * Retorna a URL de webhook correta para um agente
 *
 * IMPORTANTE: SEMPRE retorna /webhooks/dynamic para processamento de mensagens.
 * O Leadbox é usado apenas para VISUALIZAÇÃO e TRANSFERÊNCIAS, não para
 * interceptar mensagens do UAZAPI.
 *
 * @param agent - Agente com configuração de handoff_triggers
 * @returns URL de webhook (sempre /webhooks/dynamic)
 *
 * @example
 * const agent = { handoff_triggers: { type: 'leadbox', ... } };
 * const url = getWebhookUrlForAgent(agent);
 * // url = "https://ia.phant.com.br/webhooks/dynamic"
 */
export function getWebhookUrlForAgent(agent: AgentWithHandoff): string {
  // SEMPRE retornar /webhooks/dynamic para processamento de mensagens pelo Python
  // O Leadbox NÃO deve estar no caminho das mensagens do UAZAPI
  const defaultUrl = `${process.env.WEBHOOK_BASE_URL || process.env.API_BASE_URL || 'https://ia.phant.com.br'}/webhooks/dynamic`;

  Logger.info('Webhook URL resolved to Python dynamic webhook', {
    agentId: agent.id,
    agentName: agent.name,
    handoffType: agent.handoff_triggers?.type || 'none',
    webhookUrl: defaultUrl,
    reason: 'leadbox_only_for_visualization_not_message_processing',
  });

  return defaultUrl;
}

/**
 * Valida se a configuração do Leadbox está completa
 *
 * @param handoff - Configuração de handoff do agente
 * @returns true se a configuração está completa e válida
 */
export function isLeadboxConfigValid(handoff?: HandoffConfig | null): boolean {
  if (!handoff) return false;

  const usesLeadbox = handoff.type === 'leadbox' || handoff.type === 'leadbox_api';
  if (!usesLeadbox) return false;

  return !!(handoff.api_url && handoff.api_uuid && handoff.api_token);
}
