/**
 * Helpers para criar chaves Redis consistentes
 */

const PREFIX = 'agnes:context:';
const AGENT_PREFIX = 'agnes:agent:';
const LEAD_PREFIX = 'agnes:lead:';
const DIRTY_SET = 'agnes:dirty-contexts';
const METRICS_KEY = 'agnes:cache:metrics';

/**
 * Gera chave Redis para contexto de conversa (COM isolamento por agentId)
 *
 * @param agentId - ID do agente (para isolamento multi-tenant)
 * @param remoteJid - ID WhatsApp (ex: "5511999999999@s.whatsapp.net")
 * @returns Chave Redis (ex: "agnes:context:agent123:5511999999999@s.whatsapp.net")
 */
export function getContextKey(agentId: string, remoteJid: string): string {
  return `${PREFIX}${agentId}:${remoteJid}`;
}

/**
 * Gera chave Redis no formato ANTIGO (sem agentId) - para migração/compatibilidade
 *
 * @param remoteJid - ID WhatsApp
 * @returns Chave Redis no formato antigo
 * @deprecated Usar getContextKey com agentId
 */
export function getLegacyContextKey(remoteJid: string): string {
  return `${PREFIX}${remoteJid}`;
}

/**
 * Gera chave Redis para cache de agente
 *
 * @param agentId - ID do agente
 * @returns Chave Redis (ex: "agnes:agent:abc123")
 */
export function getAgentKey(agentId: string): string {
  return `${AGENT_PREFIX}${agentId}`;
}

/**
 * Gera chave Redis para cache de lead
 *
 * @param remoteJid - ID WhatsApp
 * @returns Chave Redis (ex: "agnes:lead:5511999999999@s.whatsapp.net")
 */
export function getLeadKey(remoteJid: string): string {
  return `${LEAD_PREFIX}${remoteJid}`;
}

/**
 * Retorna chave do set de contextos "dirty" (pendentes de sync)
 */
export function getDirtySetKey(): string {
  return DIRTY_SET;
}

/**
 * Retorna chave das metricas de cache
 */
export function getMetricsKey(): string {
  return METRICS_KEY;
}

/**
 * Extrai agentId e remoteJid de uma chave Redis de contexto (NOVO formato)
 *
 * @param key - Chave Redis (ex: "agnes:context:agent123:5511999999999@s.whatsapp.net")
 * @returns Objeto com agentId e remoteJid ou null se chave invalida
 */
export function extractFromContextKey(key: string): { agentId: string; remoteJid: string } | null {
  if (!key.startsWith(PREFIX)) {
    return null;
  }
  const rest = key.substring(PREFIX.length);
  const firstColon = rest.indexOf(':');
  if (firstColon === -1) {
    // Formato antigo (sem agentId) - não podemos extrair agentId
    return null;
  }
  return {
    agentId: rest.substring(0, firstColon),
    remoteJid: rest.substring(firstColon + 1),
  };
}

/**
 * Extrai remoteJid de uma chave Redis de contexto (compatibilidade com formato antigo)
 *
 * @param key - Chave Redis
 * @returns remoteJid ou null se chave invalida
 * @deprecated Usar extractFromContextKey para novo formato
 */
export function extractRemoteJidFromKey(key: string): string | null {
  if (!key.startsWith(PREFIX)) {
    return null;
  }
  // Tentar novo formato primeiro
  const parsed = extractFromContextKey(key);
  if (parsed) {
    return parsed.remoteJid;
  }
  // Fallback para formato antigo
  return key.substring(PREFIX.length);
}
