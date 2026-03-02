/**
 * ContextCacheService - Gerenciamento de cache de contextos
 *
 * RESPONSABILIDADES:
 * 1. Buscar contexto do Redis (cache hit)
 * 2. Fallback para Supabase se nao encontrar (cache miss)
 * 3. Salvar contexto no Redis apos modificacoes
 * 4. Marcar contextos como "dirty" para sincronizacao assincrona
 * 5. Sincronizar contextos dirty com Supabase
 *
 * ESTRATEGIA:
 * - Leitura: Cache-Aside (Redis primeiro, fallback Supabase)
 * - Escrita: Write-Behind (Redis imediato, Supabase assincrono)
 */

import { Redis } from 'ioredis';
import { getRedisConnection } from '../redis/redis-connection';
import { dynamicRepository } from '../supabase/repositories/dynamic.repository';
import { ConversationHistory } from '../../utils/message-formatter';
import {
  CachedContext,
  CreateCachedContext,
  UpdateCachedContext,
  CacheConfig,
  CacheMetrics,
} from './types';
import {
  getContextKey,
  getLegacyContextKey,
  getDirtySetKey,
  getMetricsKey,
  extractFromContextKey,
} from './cache-keys';

// ============================================================================
// LOGGER
// ============================================================================

const Logger = {
  info: (message: string, data?: unknown) => {
    console.log(`[ContextCache] ${message}`, data ? JSON.stringify(data, null, 2) : '');
  },
  warn: (message: string, data?: unknown) => {
    console.warn(`[ContextCache:WARN] ${message}`, data ? JSON.stringify(data, null, 2) : '');
  },
  error: (message: string, error?: unknown) => {
    console.error(`[ContextCache] ${message}`, error);
  },
  debug: (message: string, data?: unknown) => {
    if (process.env.DEBUG === 'true') {
      console.log(`[ContextCache:DEBUG] ${message}`, data ? JSON.stringify(data, null, 2) : '');
    }
  },
};

// ============================================================================
// CONFIGURACAO
// ============================================================================

const DEFAULT_CONFIG: CacheConfig = {
  defaultTTL: parseInt(process.env.CONTEXT_CACHE_TTL || '3600', 10), // 1 hora
  syncInterval: parseInt(process.env.CONTEXT_CACHE_SYNC_INTERVAL || '5000', 10), // 5 segundos
  maxMemoryMb: parseInt(process.env.CONTEXT_CACHE_MAX_MEMORY || '256', 10), // 256 MB
  enabled: process.env.CONTEXT_CACHE_ENABLED !== 'false', // true por padrao
};

// ============================================================================
// SERVICO
// ============================================================================

export class ContextCacheService {
  private redis: Redis;
  private config: CacheConfig;
  private metrics: CacheMetrics;

  constructor(config?: Partial<CacheConfig>) {
    this.redis = getRedisConnection();
    this.config = { ...DEFAULT_CONFIG, ...config };
    this.metrics = {
      hits: 0,
      misses: 0,
      hitRate: 0,
      avgLatencyMs: 0,
      dirtyContexts: 0,
      memoryUsage: 0,
      lastUpdated: new Date().toISOString(),
    };
  }

  // ==========================================================================
  // GETTERS
  // ==========================================================================

  /**
   * Busca contexto do cache ou fallback para Supabase
   *
   * FLUXO:
   * 1. Tenta buscar no Redis (com isolamento por agentId)
   * 2. Se encontrou: atualiza lastAccessedAt e hitCount
   * 3. Se nao encontrou: busca no Supabase e salva no Redis
   *
   * @param agentId - ID do agente (para isolamento multi-tenant)
   * @param remoteJid - ID WhatsApp
   * @param tableName - Nome da tabela de mensagens
   * @returns Contexto cacheado ou null
   */
  async getContext(
    agentId: string,
    remoteJid: string,
    tableName: string
  ): Promise<CachedContext | null> {
    const startTime = Date.now();

    // Se cache desabilitado, ir direto para Supabase
    if (!this.config.enabled) {
      Logger.debug('Cache disabled, loading from Supabase');
      return this.loadFromSupabase(remoteJid, tableName);
    }

    try {
      // 1. Tentar buscar do Redis (com agentId para isolamento)
      const key = getContextKey(agentId, remoteJid);
      const cached = await this.redis.get(key);

      if (cached) {
        // CACHE HIT
        this.metrics.hits++;
        const context: CachedContext = JSON.parse(cached);

        // Atualizar lastAccessedAt e hitCount
        context.lastAccessedAt = new Date().toISOString();
        context.hitCount++;

        // Salvar de volta no Redis com TTL renovado
        await this.redis.setex(key, this.config.defaultTTL, JSON.stringify(context));

        const latency = Date.now() - startTime;
        Logger.debug(`Cache HIT for ${remoteJid} (${latency}ms)`);

        // Atualizar metricas
        this.updateMetrics(latency);

        return context;
      }

      // CACHE MISS
      this.metrics.misses++;
      Logger.debug(`Cache MISS for ${remoteJid}, loading from Supabase`);

      // 2. Buscar do Supabase
      const context = await this.loadFromSupabase(remoteJid, tableName);

      if (context) {
        // 3. Salvar no Redis para proximas leituras
        await this.redis.setex(key, this.config.defaultTTL, JSON.stringify(context));
        Logger.debug(`Context cached for ${remoteJid}`);
      }

      const latency = Date.now() - startTime;
      this.updateMetrics(latency);

      return context;
    } catch (error) {
      // Erro no Redis, fallback para Supabase
      Logger.error('Redis error, falling back to Supabase', error);
      return this.loadFromSupabase(remoteJid, tableName);
    }
  }

  /**
   * Carrega contexto do Supabase e monta CachedContext
   *
   * @param remoteJid - ID WhatsApp
   * @param tableName - Nome da tabela de mensagens
   * @returns Contexto cacheado ou null
   */
  private async loadFromSupabase(
    remoteJid: string,
    tableName: string
  ): Promise<CachedContext | null> {
    try {
      // Buscar historico de mensagens
      const historyRecord = await dynamicRepository.getConversationHistory(
        tableName,
        remoteJid
      );

      if (!historyRecord || !historyRecord.conversation_history) {
        Logger.debug(`No history found in Supabase for ${remoteJid}`);
        return null;
      }

      // Buscar dados do lead
      const leadsTable = tableName.replace('leadbox_messages_', 'LeadboxCRM_');
      const lead = await dynamicRepository.findLeadByRemoteJid(leadsTable, remoteJid);

      if (!lead) {
        Logger.debug(`No lead found in Supabase for ${remoteJid}`);
        return null;
      }

      // Extrair agentId do tableName (formato: leadbox_messages_AGENTID)
      const agentId = tableName.replace('leadbox_messages_', '');

      // Montar contexto
      const context: CachedContext = {
        history: historyRecord.conversation_history as ConversationHistory,
        cachedAt: new Date().toISOString(),
        lastAccessedAt: new Date().toISOString(),
        hitCount: 0,
        agentId,
        agentName: lead.responsavel || 'AI',
        tableName,
        leadId: lead.id,
        leadName: lead.nome,
        leadPhone: lead.telefone,
        pipelineStep: lead.pipeline_step,
        isDirty: false,
        lastSyncedAt: new Date().toISOString(),
      };

      return context;
    } catch (error) {
      Logger.error('Error loading from Supabase', error);
      return null;
    }
  }

  // ==========================================================================
  // SETTERS
  // ==========================================================================

  /**
   * Salva contexto no cache e marca como dirty para sincronizacao
   *
   * FLUXO:
   * 1. Atualiza contexto no Redis (imediato, com isolamento por agentId)
   * 2. Marca como dirty
   * 3. Adiciona ao set de contextos pendentes de sync
   * 4. Worker assincrono sincroniza com Supabase depois
   *
   * FALLBACK:
   * Se contexto nao existe no Redis e tableName fornecido,
   * salva direto no Supabase (para novos leads / primeira mensagem)
   *
   * @param agentId - ID do agente (para isolamento multi-tenant)
   * @param remoteJid - ID WhatsApp
   * @param update - Dados a atualizar
   * @param tableName - Nome da tabela (opcional, para fallback ao Supabase)
   */
  async saveContext(
    agentId: string,
    remoteJid: string,
    update: UpdateCachedContext,
    tableName?: string
  ): Promise<void> {
    // Se cache desabilitado, salva direto no Supabase
    if (!this.config.enabled) {
      if (tableName && update.history) {
        Logger.debug('Cache disabled, saving directly to Supabase');
        await dynamicRepository.upsertConversationHistory(
          tableName,
          remoteJid,
          update.history
        );
      }
      return;
    }

    try {
      const key = getContextKey(agentId, remoteJid);

      // Buscar contexto atual
      const cached = await this.redis.get(key);

      // Se contexto nao existe no cache
      if (!cached) {
        // FALLBACK: Salvar direto no Supabase se tableName fornecido
        if (tableName && update.history) {
          Logger.info(`Context not in cache, saving directly to Supabase: ${remoteJid}`);
          await dynamicRepository.upsertConversationHistory(
            tableName,
            remoteJid,
            update.history
          );
          return;
        }

        Logger.warn(`Cannot update context that doesn't exist and no tableName provided: ${remoteJid}`);
        return;
      }

      const context: CachedContext = JSON.parse(cached);

      // Atualizar campos
      if (update.history) context.history = update.history;
      if (update.leadName !== undefined) context.leadName = update.leadName;
      if (update.leadPhone !== undefined) context.leadPhone = update.leadPhone;
      if (update.pipelineStep !== undefined) context.pipelineStep = update.pipelineStep;
      if (update.isDirty !== undefined) context.isDirty = update.isDirty;
      if (update.lastSyncedAt !== undefined) context.lastSyncedAt = update.lastSyncedAt;

      // Marcar como dirty
      context.isDirty = true;

      // Salvar no Redis
      await this.redis.setex(key, this.config.defaultTTL, JSON.stringify(context));

      // Adicionar ao set de contextos dirty (formato: agentId:remoteJid)
      await this.redis.sadd(getDirtySetKey(), `${agentId}:${remoteJid}`);

      Logger.debug(`Context updated and marked dirty: ${agentId}:${remoteJid}`);
    } catch (error) {
      Logger.error(`Error saving context for ${remoteJid}`, error);

      // FALLBACK em caso de erro: salvar direto no Supabase
      if (tableName && update.history) {
        Logger.info(`Redis error, falling back to Supabase: ${remoteJid}`);
        await dynamicRepository.upsertConversationHistory(
          tableName,
          remoteJid,
          update.history
        );
      }
    }
  }

  /**
   * Atualiza apenas o historico de mensagens
   *
   * @param agentId - ID do agente (para isolamento multi-tenant)
   * @param remoteJid - ID WhatsApp
   * @param history - Novo historico
   * @param tableName - Nome da tabela (opcional, para fallback direto ao Supabase)
   */
  async updateHistory(
    agentId: string,
    remoteJid: string,
    history: ConversationHistory,
    tableName?: string
  ): Promise<void> {
    await this.saveContext(agentId, remoteJid, { history }, tableName);
  }

  /**
   * Cria novo contexto no cache
   *
   * @param agentId - ID do agente (para isolamento multi-tenant)
   * @param remoteJid - ID WhatsApp
   * @param data - Dados do contexto
   */
  async createContext(
    agentId: string,
    remoteJid: string,
    data: CreateCachedContext
  ): Promise<void> {
    if (!this.config.enabled) {
      return;
    }

    try {
      const now = new Date().toISOString();
      const context: CachedContext = {
        ...data,
        cachedAt: now,
        lastAccessedAt: now,
        hitCount: 0,
        isDirty: true,
        lastSyncedAt: null,
      };

      const key = getContextKey(agentId, remoteJid);
      await this.redis.setex(key, this.config.defaultTTL, JSON.stringify(context));
      await this.redis.sadd(getDirtySetKey(), `${agentId}:${remoteJid}`);

      Logger.debug(`New context created: ${agentId}:${remoteJid}`);
    } catch (error) {
      Logger.error(`Error creating context for ${remoteJid}`, error);
    }
  }

  // ==========================================================================
  // INVALIDACAO
  // ==========================================================================

  /**
   * Invalida cache (forca reload do Supabase na proxima leitura)
   *
   * @param agentId - ID do agente (para isolamento multi-tenant)
   * @param remoteJid - ID WhatsApp
   */
  async invalidate(agentId: string, remoteJid: string): Promise<void> {
    if (!this.config.enabled) {
      return;
    }

    try {
      const key = getContextKey(agentId, remoteJid);
      await this.redis.del(key);
      await this.redis.srem(getDirtySetKey(), `${agentId}:${remoteJid}`);

      Logger.info(`Context invalidated: ${agentId}:${remoteJid}`);
    } catch (error) {
      Logger.error(`Error invalidating context for ${remoteJid}`, error);
    }
  }

  // ==========================================================================
  // SINCRONIZACAO
  // ==========================================================================

  /**
   * Sincroniza contextos dirty com Supabase
   *
   * FLUXO:
   * 1. Busca todos os entries do set "dirty" (formato: agentId:remoteJid)
   * 2. Para cada um:
   *    a. Parseia agentId e remoteJid
   *    b. Busca contexto do Redis
   *    c. Salva historico no Supabase
   *    d. Marca como synced (isDirty = false)
   *    e. Remove do set dirty
   *
   * @returns Numero de contextos sincronizados
   */
  async syncDirtyContexts(): Promise<number> {
    if (!this.config.enabled) {
      return 0;
    }

    try {
      const dirtySetKey = getDirtySetKey();
      const dirtyEntries = await this.redis.smembers(dirtySetKey);

      if (dirtyEntries.length === 0) {
        Logger.debug('No dirty contexts to sync');
        return 0;
      }

      Logger.info(`Syncing ${dirtyEntries.length} dirty contexts...`);

      let syncedCount = 0;

      for (const dirtyEntry of dirtyEntries) {
        try {
          // Parsear agentId:remoteJid do novo formato
          const colonIdx = dirtyEntry.indexOf(':');
          if (colonIdx === -1) {
            // Formato antigo (apenas remoteJid) - remover do set
            Logger.warn(`Legacy dirty entry found (no agentId): ${dirtyEntry}`);
            await this.redis.srem(dirtySetKey, dirtyEntry);
            continue;
          }

          const agentId = dirtyEntry.substring(0, colonIdx);
          const remoteJid = dirtyEntry.substring(colonIdx + 1);

          // Buscar contexto do Redis
          const key = getContextKey(agentId, remoteJid);
          const cached = await this.redis.get(key);

          if (!cached) {
            // Contexto nao existe mais, remover do set dirty
            await this.redis.srem(dirtySetKey, dirtyEntry);
            continue;
          }

          const context: CachedContext = JSON.parse(cached);

          // Salvar historico no Supabase
          await dynamicRepository.upsertConversationHistory(
            context.tableName,
            remoteJid,
            context.history,
            'model' // Ultima acao foi do modelo
          );

          // Marcar como sincronizado
          context.isDirty = false;
          context.lastSyncedAt = new Date().toISOString();

          // Atualizar no Redis
          await this.redis.setex(key, this.config.defaultTTL, JSON.stringify(context));

          // Remover do set dirty
          await this.redis.srem(dirtySetKey, dirtyEntry);

          syncedCount++;
          Logger.debug(`Synced context: ${agentId}:${remoteJid}`);
        } catch (error) {
          Logger.error(`Error syncing context ${dirtyEntry}`, error);
          // Continua com os proximos
        }
      }

      Logger.info(`Synced ${syncedCount} contexts successfully`);
      return syncedCount;
    } catch (error) {
      Logger.error('Error in syncDirtyContexts', error);
      return 0;
    }
  }

  // ==========================================================================
  // PRE-CARREGAMENTO
  // ==========================================================================

  /**
   * Pre-carrega contexto no cache (para conversas ativas)
   *
   * @param agentId - ID do agente (para isolamento multi-tenant)
   * @param remoteJid - ID WhatsApp
   * @param tableName - Nome da tabela de mensagens
   */
  async warmup(agentId: string, remoteJid: string, tableName: string): Promise<void> {
    if (!this.config.enabled) {
      return;
    }

    try {
      // Se ja existe no cache, nao fazer nada
      const key = getContextKey(agentId, remoteJid);
      const exists = await this.redis.exists(key);

      if (exists) {
        Logger.debug(`Context already cached: ${agentId}:${remoteJid}`);
        return;
      }

      // Carregar do Supabase e cachear
      const context = await this.loadFromSupabase(remoteJid, tableName);

      if (context) {
        await this.redis.setex(key, this.config.defaultTTL, JSON.stringify(context));
        Logger.info(`Context warmed up: ${agentId}:${remoteJid}`);
      }
    } catch (error) {
      Logger.error(`Error warming up context for ${remoteJid}`, error);
    }
  }

  // ==========================================================================
  // METRICAS
  // ==========================================================================

  /**
   * Atualiza metricas de performance
   *
   * @param latencyMs - Latencia da operacao
   */
  private updateMetrics(latencyMs: number): void {
    const total = this.metrics.hits + this.metrics.misses;
    this.metrics.hitRate = total > 0 ? this.metrics.hits / total : 0;

    // Calcular media movel de latencia (ultimas 100 operacoes)
    const alpha = 0.1; // Peso para nova medida
    this.metrics.avgLatencyMs = this.metrics.avgLatencyMs * (1 - alpha) + latencyMs * alpha;

    this.metrics.lastUpdated = new Date().toISOString();
  }

  /**
   * Retorna metricas atuais do cache
   */
  async getMetrics(): Promise<CacheMetrics> {
    try {
      // Atualizar contagem de contextos dirty
      const dirtyCount = await this.redis.scard(getDirtySetKey());
      this.metrics.dirtyContexts = dirtyCount;

      // Obter uso de memoria do Redis
      const info = await this.redis.info('memory');
      const match = info.match(/used_memory:(\d+)/);
      if (match) {
        this.metrics.memoryUsage = parseInt(match[1], 10);
      }

      return { ...this.metrics };
    } catch (error) {
      Logger.error('Error getting metrics', error);
      return { ...this.metrics };
    }
  }

  /**
   * Reseta metricas
   */
  resetMetrics(): void {
    this.metrics = {
      hits: 0,
      misses: 0,
      hitRate: 0,
      avgLatencyMs: 0,
      dirtyContexts: 0,
      memoryUsage: 0,
      lastUpdated: new Date().toISOString(),
    };
  }

  // ==========================================================================
  // VERIFICACAO DE SAUDE
  // ==========================================================================

  /**
   * Verifica se Redis esta disponivel
   */
  async isHealthy(): Promise<boolean> {
    try {
      const result = await this.redis.ping();
      return result === 'PONG';
    } catch (error) {
      Logger.error('Redis health check failed', error);
      return false;
    }
  }
}

// ============================================================================
// SINGLETON
// ============================================================================

let contextCacheInstance: ContextCacheService | null = null;

/**
 * Retorna instancia singleton do ContextCacheService
 */
export function getContextCacheService(): ContextCacheService {
  if (!contextCacheInstance) {
    contextCacheInstance = new ContextCacheService();
  }
  return contextCacheInstance;
}

/**
 * Inicializa o servico de cache
 * Chamado no startup da aplicacao
 */
export async function initializeContextCache(config?: Partial<CacheConfig>): Promise<boolean> {
  try {
    contextCacheInstance = new ContextCacheService(config);
    const healthy = await contextCacheInstance.isHealthy();

    if (!healthy) {
      console.error('[ContextCache] Redis not available, cache disabled');
      return false;
    }

    console.log('[ContextCache] Initialized successfully');
    return true;
  } catch (error) {
    console.error('[ContextCache] Initialization failed', error);
    return false;
  }
}
