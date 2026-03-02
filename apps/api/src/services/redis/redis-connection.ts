/**
 * Redis Connection
 *
 * Gerencia conexao unica com Redis para o projeto
 */

import { Redis, RedisOptions } from 'ioredis';

// ============================================================================
// LOGGER
// ============================================================================

const Logger = {
  info: (message: string, data?: unknown) => {
    console.log(`[Redis] ${message}`, data ? JSON.stringify(data, null, 2) : '');
  },
  error: (message: string, error?: unknown) => {
    console.error(`[Redis] ${message}`, error);
  },
  debug: (message: string, data?: unknown) => {
    if (process.env.DEBUG === 'true') {
      console.log(`[Redis:DEBUG] ${message}`, data ? JSON.stringify(data, null, 2) : '');
    }
  },
};

// ============================================================================
// CONNECTION
// ============================================================================

let redisConnection: Redis | null = null;

/**
 * Configuracao do Redis baseada em variaveis de ambiente
 */
function getRedisConfig(): RedisOptions {
  const host = process.env.REDIS_HOST || '127.0.0.1';
  const port = parseInt(process.env.REDIS_PORT || '6379', 10);
  const password = process.env.REDIS_PASSWORD || undefined;
  const db = parseInt(process.env.REDIS_DB || '0', 10);

  return {
    host,
    port,
    password,
    db,
    maxRetriesPerRequest: null,
    enableReadyCheck: false,
    retryStrategy: (times) => {
      if (times > 10) {
        Logger.error('Redis connection failed after 10 retries');
        return null;
      }
      return Math.min(times * 200, 2000);
    },
  };
}

/**
 * Obtem ou cria conexao Redis singleton
 */
export function getRedisConnection(): Redis {
  if (!redisConnection) {
    const config = getRedisConfig();
    redisConnection = new Redis(config);

    redisConnection.on('connect', () => {
      Logger.info('Connected to Redis', { host: config.host, port: config.port });
    });

    redisConnection.on('error', (error) => {
      Logger.error('Redis connection error', error);
    });

    redisConnection.on('close', () => {
      Logger.info('Redis connection closed');
    });
  }

  return redisConnection;
}

/**
 * Cria uma nova conexao Redis (para workers que precisam de conexao separada)
 */
export function createRedisConnection(): Redis {
  const config = getRedisConfig();
  return new Redis(config);
}

/**
 * Fecha a conexao Redis
 */
export async function closeRedisConnection(): Promise<void> {
  if (redisConnection) {
    await redisConnection.quit();
    redisConnection = null;
    Logger.info('Redis connection closed');
  }
}

/**
 * Verifica se Redis esta disponivel
 */
export async function isRedisAvailable(): Promise<boolean> {
  try {
    const redis = getRedisConnection();
    await redis.ping();
    return true;
  } catch {
    return false;
  }
}
