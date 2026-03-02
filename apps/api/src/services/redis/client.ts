/**
 * Redis Client Singleton
 *
 * Exporta conexao Redis para uso no projeto
 */

export {
  getRedisConnection,
  createRedisConnection,
  closeRedisConnection,
  isRedisAvailable
} from './redis-connection';
