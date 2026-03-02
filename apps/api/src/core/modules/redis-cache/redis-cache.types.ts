/**
 * Redis Cache Types - SIMPLIFICADO
 */

export interface CacheConfig {
  enabled: boolean;
  ttlSeconds: number;
}

export const DEFAULT_CACHE_CONFIG: CacheConfig = {
  enabled: true,
  ttlSeconds: 3600,
};
