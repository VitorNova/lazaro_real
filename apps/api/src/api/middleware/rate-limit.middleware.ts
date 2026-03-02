// ============================================================================
// RATE LIMIT MIDDLEWARE
// Proteção contra brute force e abuse
// ============================================================================

import { FastifyRequest, FastifyReply } from 'fastify';

// ============================================================================
// TYPES
// ============================================================================

interface RateLimitEntry {
  count: number;
  firstRequest: number;
  blocked: boolean;
  blockedUntil?: number;
}

interface RateLimitConfig {
  windowMs: number;      // Janela de tempo em ms
  maxRequests: number;   // Máximo de requests na janela
  blockDurationMs: number; // Tempo de bloqueio após exceder
  keyGenerator?: (request: FastifyRequest) => string;
}

// ============================================================================
// RATE LIMIT STORE (in-memory)
// ============================================================================

const rateLimitStore = new Map<string, RateLimitEntry>();

// Limpar entradas antigas periodicamente
setInterval(() => {
  const now = Date.now();
  for (const [key, entry] of rateLimitStore.entries()) {
    // Remover entradas mais antigas que 1 hora
    if (now - entry.firstRequest > 60 * 60 * 1000) {
      rateLimitStore.delete(key);
    }
  }
}, 5 * 60 * 1000); // A cada 5 minutos

// ============================================================================
// DEFAULT KEY GENERATOR
// ============================================================================

function defaultKeyGenerator(request: FastifyRequest): string {
  // Usar IP do cliente
  const forwarded = request.headers['x-forwarded-for'];
  const ip = forwarded
    ? (typeof forwarded === 'string' ? forwarded.split(',')[0] : forwarded[0])
    : request.ip;

  return `ratelimit:${ip}`;
}

// ============================================================================
// RATE LIMIT FACTORY
// ============================================================================

export function createRateLimiter(config: RateLimitConfig) {
  const {
    windowMs,
    maxRequests,
    blockDurationMs,
    keyGenerator = defaultKeyGenerator,
  } = config;

  return async function rateLimitMiddleware(
    request: FastifyRequest,
    reply: FastifyReply
  ): Promise<void> {
    const key = keyGenerator(request);
    const now = Date.now();

    let entry = rateLimitStore.get(key);

    // Se não existe, criar nova entrada
    if (!entry) {
      entry = {
        count: 1,
        firstRequest: now,
        blocked: false,
      };
      rateLimitStore.set(key, entry);
      return;
    }

    // Verificar se está bloqueado
    if (entry.blocked && entry.blockedUntil) {
      if (now < entry.blockedUntil) {
        const retryAfter = Math.ceil((entry.blockedUntil - now) / 1000);
        reply.header('Retry-After', retryAfter.toString());
        return reply.status(429).send({
          status: 'error',
          code: 'RATE_LIMIT_EXCEEDED',
          message: `Muitas tentativas. Tente novamente em ${retryAfter} segundos`,
          retryAfter,
        });
      } else {
        // Desbloquear e resetar
        entry.blocked = false;
        entry.blockedUntil = undefined;
        entry.count = 1;
        entry.firstRequest = now;
        return;
      }
    }

    // Verificar se a janela expirou
    if (now - entry.firstRequest > windowMs) {
      entry.count = 1;
      entry.firstRequest = now;
      return;
    }

    // Incrementar contador
    entry.count++;

    // Verificar se excedeu o limite
    if (entry.count > maxRequests) {
      entry.blocked = true;
      entry.blockedUntil = now + blockDurationMs;

      const retryAfter = Math.ceil(blockDurationMs / 1000);
      reply.header('Retry-After', retryAfter.toString());

      console.warn('[RateLimit] IP bloqueado:', {
        key,
        count: entry.count,
        blockedUntil: new Date(entry.blockedUntil).toISOString(),
      });

      return reply.status(429).send({
        status: 'error',
        code: 'RATE_LIMIT_EXCEEDED',
        message: `Muitas tentativas. Tente novamente em ${retryAfter} segundos`,
        retryAfter,
      });
    }
  };
}

// ============================================================================
// PRE-CONFIGURED RATE LIMITERS
// ============================================================================

/**
 * Rate limiter para login
 * 5 tentativas por minuto, bloqueio de 5 minutos
 */
export const loginRateLimiter = createRateLimiter({
  windowMs: 60 * 1000,        // 1 minuto
  maxRequests: 5,             // 5 tentativas
  blockDurationMs: 5 * 60 * 1000, // 5 minutos de bloqueio
  keyGenerator: (request) => {
    const body = request.body as { email?: string } | undefined;
    const email = body?.email?.toLowerCase() || 'unknown';
    const ip = request.ip;
    return `login:${email}:${ip}`;
  },
});

/**
 * Rate limiter para registro
 * 3 tentativas por hora por IP
 */
export const registerRateLimiter = createRateLimiter({
  windowMs: 60 * 60 * 1000,   // 1 hora
  maxRequests: 3,             // 3 registros
  blockDurationMs: 60 * 60 * 1000, // 1 hora de bloqueio
});

/**
 * Rate limiter para forgot password
 * 3 tentativas por hora por email
 */
export const forgotPasswordRateLimiter = createRateLimiter({
  windowMs: 60 * 60 * 1000,   // 1 hora
  maxRequests: 3,             // 3 tentativas
  blockDurationMs: 60 * 60 * 1000, // 1 hora de bloqueio
  keyGenerator: (request) => {
    const body = request.body as { email?: string } | undefined;
    const email = body?.email?.toLowerCase() || 'unknown';
    return `forgot:${email}`;
  },
});

/**
 * Rate limiter genérico para APIs
 * 100 requests por minuto
 */
export const apiRateLimiter = createRateLimiter({
  windowMs: 60 * 1000,        // 1 minuto
  maxRequests: 100,           // 100 requests
  blockDurationMs: 60 * 1000, // 1 minuto de bloqueio
});
