/**
 * Human Takeover via Redis
 * Gerencia leads que estão em atendimento humano usando Redis
 *
 * MIGRADO DE: dynamic/caches/human-takeover.cache.ts
 * MOTIVO: Map() não funciona em PM2 cluster mode
 *
 * Garante que a IA não responda mesmo antes do lead existir no banco
 * TTL de 24 horas - depois disso, se o lead não existir, permite criar normalmente
 */

import { getRedisCacheModule } from '../../core/modules/redis-cache/redis-cache.module';

const HUMAN_TAKEOVER_TTL_MS = 24 * 60 * 60 * 1000; // 24 horas
const HUMAN_TAKEOVER_TTL_SECONDS = 24 * 60 * 60; // 24 horas em segundos

interface HumanTakeoverEntry {
  timestamp: number;
  agentId: string;
}

/**
 * Marca um remoteJid como em atendimento humano
 * Usado quando detectamos fromMe: true
 */
export async function markAsHumanTakeover(remoteJid: string, agentId: string): Promise<void> {
  try {
    const redis = getRedisCacheModule();
    const key = `pause:${agentId}:${remoteJid}`;
    const data: HumanTakeoverEntry = {
      timestamp: Date.now(),
      agentId,
    };

    await redis.setJson(key, data, HUMAN_TAKEOVER_TTL_SECONDS);

    console.log('[HumanTakeover] RemoteJid marked as human takeover', {
      remoteJid,
      agentId,
      ttlMs: HUMAN_TAKEOVER_TTL_MS,
      key,
    });
  } catch (error) {
    console.error('[HumanTakeover] Failed to mark as human takeover', {
      remoteJid,
      agentId,
      error: error instanceof Error ? error.message : String(error),
    });
    // Não lança erro - falha no Redis não deve bloquear o fluxo
  }
}

/**
 * Verifica se um remoteJid está em atendimento humano (via Redis)
 * Retorna true se deve pausar a IA
 */
export async function isInHumanTakeoverCache(remoteJid: string, agentId?: string): Promise<boolean> {
  try {
    const redis = getRedisCacheModule();
    const key = `pause:${agentId || '*'}:${remoteJid}`;

    // Se agentId foi especificado, buscar chave exata
    if (agentId) {
      const data = await redis.getJson<HumanTakeoverEntry>(key);
      if (data) {
        const now = Date.now();
        const ageMs = now - data.timestamp;

        console.log('[HumanTakeover] RemoteJid is in human takeover cache', {
          remoteJid,
          agentId: data.agentId,
          ageMs,
        });
        return true;
      }
    } else {
      // Se agentId não foi especificado, buscar qualquer chave que contenha o remoteJid
      // Isso é necessário para casos onde não sabemos o agentId mas queremos verificar
      // se o lead está pausado em ALGUM agente
      // Como não temos scan disponível, tentamos a convenção de chave pause:*:remoteJid
      // Fallback: retornar false (assumir que não está pausado)
      console.warn('[HumanTakeover] Cannot check without agentId in Redis mode', { remoteJid });
      return false;
    }

    return false;
  } catch (error) {
    console.error('[HumanTakeover] Failed to check human takeover cache', {
      remoteJid,
      agentId,
      error: error instanceof Error ? error.message : String(error),
    });
    // Em caso de erro no Redis, assumir que NÃO está pausado (fail-safe)
    return false;
  }
}

/**
 * Remove um remoteJid do cache de human takeover
 * Usado quando a IA é reativada manualmente
 */
export async function removeFromHumanTakeoverCache(remoteJid: string, agentId?: string): Promise<void> {
  try {
    const redis = getRedisCacheModule();

    if (agentId) {
      // Se temos o agentId, deletar chave específica
      const key = `pause:${agentId}:${remoteJid}`;
      await redis.del(key);
      console.log('[HumanTakeover] RemoteJid removed from human takeover cache', { remoteJid, agentId, key });
    } else {
      // Se não temos agentId, não podemos deletar sem saber a chave exata
      console.warn('[HumanTakeover] Cannot remove without agentId in Redis mode', { remoteJid });
    }
  } catch (error) {
    console.error('[HumanTakeover] Failed to remove from human takeover cache', {
      remoteJid,
      agentId,
      error: error instanceof Error ? error.message : String(error),
    });
    // Não lança erro - falha no Redis não deve bloquear o fluxo
  }
}

/**
 * Retorna estatísticas do cache
 * Nota: No Redis mode, não podemos contar facilmente o total de chaves
 */
export async function getHumanTakeoverStats(): Promise<{ ttlMs: number; mode: string }> {
  return {
    ttlMs: HUMAN_TAKEOVER_TTL_MS,
    mode: 'redis',
  };
}

/**
 * Limpa todo o cache (útil para testes)
 * Nota: No Redis mode, precisaríamos de scan() para deletar todas as chaves pause:*
 * Por enquanto, retorna warning
 */
export async function clearHumanTakeoverCache(): Promise<void> {
  console.warn('[HumanTakeover] clearHumanTakeoverCache not implemented in Redis mode');
}
