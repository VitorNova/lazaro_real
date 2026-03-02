/**
 * Lock Service - Redis
 *
 * Servico de locks distribuidos usando Redis.
 * Previne processamento duplicado em ambiente multi-instancia.
 *
 * Funcionalidades:
 * - Locks distribuidos com TTL
 * - Previne race conditions entre instancias
 * - Auto-release em caso de crash
 */

import { getRedisConnection, isRedisAvailable } from './client';
import type { Redis } from 'ioredis';

// ============================================================================
// CONSTANTS
// ============================================================================

const LOCK_KEY_PREFIX = 'lock:';
const DEFAULT_LOCK_TTL_SECONDS = 200; // 200 segundos (3+ minutos)

// ============================================================================
// LOGGER
// ============================================================================

const Logger = {
  info: (message: string, data?: unknown) => {
    console.log(`[LockService] ${message}`, data ? JSON.stringify(data) : '');
  },
  error: (message: string, error?: unknown) => {
    console.error(`[LockService] ${message}`, error);
  },
  debug: (message: string, data?: unknown) => {
    if (process.env.DEBUG === 'true') {
      console.log(`[LockService:DEBUG] ${message}`, data ? JSON.stringify(data) : '');
    }
  },
};

// ============================================================================
// LOCK SERVICE
// ============================================================================

export class LockService {
  private redis: Redis | null = null;
  private available: boolean = false;
  private instanceId: string;

  constructor() {
    // ID unico para esta instancia (para identificar quem tem o lock)
    this.instanceId = `${process.pid}-${Date.now()}-${Math.random().toString(36).substring(7)}`;
    this.initialize();
  }

  /**
   * Inicializa conexao Redis
   */
  private async initialize(): Promise<void> {
    try {
      this.available = await isRedisAvailable();
      if (this.available) {
        this.redis = getRedisConnection();
        Logger.info('Service initialized', { instanceId: this.instanceId });
      } else {
        Logger.info('Redis not available, service will use fallback');
      }
    } catch (error) {
      Logger.error('Failed to initialize', error);
      this.available = false;
    }
  }

  /**
   * Verifica se o servico esta disponivel
   */
  isAvailable(): boolean {
    return this.available && this.redis !== null;
  }

  /**
   * Gera a chave Redis para um lock
   */
  private getLockKey(key: string): string {
    return `${LOCK_KEY_PREFIX}${key}`;
  }

  /**
   * Tenta adquirir um lock
   *
   * @param key Identificador do recurso (ex: remoteJid)
   * @param ttlSeconds Tempo de vida do lock em segundos
   * @returns true se o lock foi adquirido, false se ja esta bloqueado
   */
  async acquireLock(key: string, ttlSeconds: number = DEFAULT_LOCK_TTL_SECONDS): Promise<boolean> {
    if (!this.redis) {
      Logger.debug('Redis not available, lock granted by default', { key });
      return true; // Fallback: sempre permite (comportamento anterior)
    }

    const lockKey = this.getLockKey(key);
    const lockValue = `${this.instanceId}:${Date.now()}`;

    try {
      // SET key value NX EX ttl
      // NX = apenas se nao existir
      // EX = expira em X segundos
      const result = await this.redis.set(lockKey, lockValue, 'EX', ttlSeconds, 'NX');

      const acquired = result === 'OK';

      Logger.debug(acquired ? 'Lock acquired' : 'Lock already held', {
        key,
        lockKey,
        ttlSeconds,
        acquired
      });

      return acquired;
    } catch (error) {
      Logger.error('Failed to acquire lock', { key, error });
      return true; // Em caso de erro, permite processamento (fallback)
    }
  }

  /**
   * Libera um lock
   *
   * @param key Identificador do recurso
   */
  async releaseLock(key: string): Promise<void> {
    if (!this.redis) {
      return;
    }

    const lockKey = this.getLockKey(key);

    try {
      await this.redis.del(lockKey);
      Logger.debug('Lock released', { key, lockKey });
    } catch (error) {
      Logger.error('Failed to release lock', { key, error });
    }
  }

  /**
   * Verifica se um recurso esta bloqueado
   *
   * @param key Identificador do recurso
   * @returns true se esta bloqueado
   */
  async isLocked(key: string): Promise<boolean> {
    if (!this.redis) {
      return false; // Fallback: nao bloqueado
    }

    const lockKey = this.getLockKey(key);

    try {
      const value = await this.redis.get(lockKey);
      return value !== null;
    } catch (error) {
      Logger.error('Failed to check lock status', { key, error });
      return false;
    }
  }

  /**
   * Obtem informacoes sobre um lock
   *
   * @param key Identificador do recurso
   * @returns Informacoes do lock ou null se nao existir
   */
  async getLockInfo(key: string): Promise<{ holder: string; ttl: number } | null> {
    if (!this.redis) {
      return null;
    }

    const lockKey = this.getLockKey(key);

    try {
      const [value, ttl] = await Promise.all([
        this.redis.get(lockKey),
        this.redis.ttl(lockKey)
      ]);

      if (!value) {
        return null;
      }

      return { holder: value, ttl };
    } catch (error) {
      Logger.error('Failed to get lock info', { key, error });
      return null;
    }
  }

  /**
   * Estende o TTL de um lock existente
   *
   * @param key Identificador do recurso
   * @param ttlSeconds Novo TTL em segundos
   * @returns true se o lock foi estendido
   */
  async extendLock(key: string, ttlSeconds: number = DEFAULT_LOCK_TTL_SECONDS): Promise<boolean> {
    if (!this.redis) {
      return true;
    }

    const lockKey = this.getLockKey(key);

    try {
      const exists = await this.redis.exists(lockKey);
      if (!exists) {
        return false;
      }

      await this.redis.expire(lockKey, ttlSeconds);
      Logger.debug('Lock extended', { key, ttlSeconds });
      return true;
    } catch (error) {
      Logger.error('Failed to extend lock', { key, error });
      return false;
    }
  }

  /**
   * Executa uma funcao com lock automatico
   *
   * @param key Identificador do recurso
   * @param fn Funcao a executar
   * @param ttlSeconds TTL do lock
   * @returns Resultado da funcao ou null se nao conseguiu o lock
   */
  async withLock<T>(
    key: string,
    fn: () => Promise<T>,
    ttlSeconds: number = DEFAULT_LOCK_TTL_SECONDS
  ): Promise<T | null> {
    const acquired = await this.acquireLock(key, ttlSeconds);

    if (!acquired) {
      Logger.info('Could not acquire lock, skipping execution', { key });
      return null;
    }

    try {
      return await fn();
    } finally {
      await this.releaseLock(key);
    }
  }
}

// ============================================================================
// SINGLETON INSTANCE
// ============================================================================

let instance: LockService | null = null;

export function getLockService(): LockService {
  if (!instance) {
    instance = new LockService();
  }
  return instance;
}

export default LockService;
