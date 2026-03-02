/**
 * Redis Cache Module - SIMPLIFICADO
 * Wrapper do ContextCacheService existente
 */

import { IModule, ModuleStatus, ModuleHealth } from '../base/module.interface';
import { CacheConfig, DEFAULT_CACHE_CONFIG } from './redis-cache.types';
import { getRedisConnection } from '../../../services/redis/redis-connection';
import type { Redis } from 'ioredis';

export class RedisCacheModule implements IModule {
  readonly name = 'redis-cache';
  status: ModuleStatus = 'idle';

  private redis: Redis | null = null;
  private config: CacheConfig;

  constructor(config?: Partial<CacheConfig>) {
    this.config = { ...DEFAULT_CACHE_CONFIG, ...config };
  }

  async initialize(): Promise<void> {
    if (!this.config.enabled) {
      this.status = 'ready';
      return;
    }

    try {
      this.redis = getRedisConnection();
      await this.redis.ping();
      this.status = 'ready';
    } catch (error) {
      console.error('[RedisCacheModule] Failed to connect:', error);
      this.status = 'error';
    }
  }

  async shutdown(): Promise<void> {
    this.redis = null;
    this.status = 'idle';
  }

  async healthCheck(): Promise<ModuleHealth> {
    if (!this.config.enabled) {
      return { healthy: true, message: 'Disabled' };
    }

    try {
      if (this.redis) {
        await this.redis.ping();
        return { healthy: true };
      }
      return { healthy: false, message: 'Not connected' };
    } catch {
      return { healthy: false, message: 'Ping failed' };
    }
  }

  async get(key: string): Promise<string | null> {
    if (!this.redis) return null;
    return this.redis.get(key);
  }

  async set(key: string, value: string, ttl?: number): Promise<void> {
    if (!this.redis) return;
    const seconds = ttl ?? this.config.ttlSeconds;
    await this.redis.setex(key, seconds, value);
  }

  async del(key: string): Promise<void> {
    if (!this.redis) return;
    await this.redis.del(key);
  }

  async getJson<T>(key: string): Promise<T | null> {
    const value = await this.get(key);
    if (!value) return null;
    try {
      return JSON.parse(value) as T;
    } catch {
      return null;
    }
  }

  async setJson<T>(key: string, value: T, ttl?: number): Promise<void> {
    await this.set(key, JSON.stringify(value), ttl);
  }
}

let instance: RedisCacheModule | null = null;
let initializePromise: Promise<void> | null = null;

export function getRedisCacheModule(): RedisCacheModule {
  if (!instance) {
    instance = new RedisCacheModule();
    // Auto-initialize on first access
    initializePromise = instance.initialize();
  }
  return instance;
}

export async function getInitializedRedisCacheModule(): Promise<RedisCacheModule> {
  const cache = getRedisCacheModule();
  if (initializePromise) {
    await initializePromise;
  }
  return cache;
}
