/**
 * Types for Redis Context Cache
 *
 * Sistema de cache de contexto de conversacao usando Redis.
 * Reduz latencia de leitura de 100-500ms (Supabase) para <5ms (Redis).
 */

import { ConversationHistory, DianaContext } from '../../utils/message-formatter';

/**
 * Contexto completo cacheado no Redis
 * Inclui historico + metadados + dados do agente/lead
 */
export interface CachedContext {
  // ============================================================================
  // DADOS DO HISTORICO
  // ============================================================================

  /** Historico de conversa (formato ConversationHistory) */
  history: ConversationHistory;

  // ============================================================================
  // METADADOS DO CACHE
  // ============================================================================

  /** Quando foi criado no cache (ISO timestamp) */
  cachedAt: string;

  /** Ultima vez que foi acessado (ISO timestamp) */
  lastAccessedAt: string;

  /** Quantas vezes foi acessado desde que foi cacheado */
  hitCount: number;

  // ============================================================================
  // DADOS DO AGENTE (evita query adicional)
  // ============================================================================

  /** ID do agente */
  agentId: string;

  /** Nome do agente */
  agentName: string;

  /** Nome da tabela de mensagens */
  tableName: string;

  // ============================================================================
  // DADOS DO LEAD (evita query adicional)
  // ============================================================================

  /** ID do lead */
  leadId: number;

  /** Nome do lead */
  leadName: string | null;

  /** Telefone do lead */
  leadPhone: string | null;

  /** Etapa atual do pipeline */
  pipelineStep: string;

  // ============================================================================
  // CONTROLE DE SINCRONIZACAO
  // ============================================================================

  /** Se true, precisa sincronizar com Supabase */
  isDirty: boolean;

  /** Ultima sincronizacao com Supabase (ISO timestamp) */
  lastSyncedAt: string | null;
}

/**
 * Dados minimos para criar um novo contexto no cache
 */
export interface CreateCachedContext {
  history: ConversationHistory;
  agentId: string;
  agentName: string;
  tableName: string;
  leadId: number;
  leadName: string | null;
  leadPhone: string | null;
  pipelineStep: string;
}

/**
 * Dados para atualizar um contexto existente
 */
export interface UpdateCachedContext {
  history?: ConversationHistory;
  leadName?: string | null;
  leadPhone?: string | null;
  pipelineStep?: string;
  isDirty?: boolean;
  lastSyncedAt?: string | null;
}

/**
 * Metricas do sistema de cache
 */
export interface CacheMetrics {
  /** Total de cache hits */
  hits: number;

  /** Total de cache misses */
  misses: number;

  /** Taxa de hit (hits / (hits + misses)) */
  hitRate: number;

  /** Latencia media de leitura (ms) */
  avgLatencyMs: number;

  /** Contextos pendentes de sincronizacao */
  dirtyContexts: number;

  /** Uso de memoria Redis (bytes) */
  memoryUsage: number;

  /** Timestamp da ultima atualizacao das metricas */
  lastUpdated: string;
}

/**
 * Configuracao do cache
 */
export interface CacheConfig {
  /** TTL padrao em segundos (1 hora = 3600) */
  defaultTTL: number;

  /** Intervalo de sincronizacao em ms (5 segundos = 5000) */
  syncInterval: number;

  /** Limite de memoria para contextos (em MB) */
  maxMemoryMb: number;

  /** Se false, cache desabilitado (fallback para Supabase) */
  enabled: boolean;
}
