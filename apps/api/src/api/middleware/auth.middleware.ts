// ============================================================================
// AUTH MIDDLEWARE
// Middleware para proteção de rotas com JWT
// ============================================================================

import { FastifyRequest, FastifyReply } from 'fastify';
import * as jwt from 'jsonwebtoken';

// ============================================================================
// TYPES
// ============================================================================

export interface JWTPayload {
  userId: string;
  email: string;
  name: string;
  iat?: number;
  exp?: number;
}

export interface AuthenticatedRequest extends FastifyRequest {
  user: JWTPayload;
}

// ============================================================================
// JWT SECRET
// ============================================================================

const getJwtSecret = (): string => {
  return process.env.JWT_SECRET || 'agnes-agent-jwt-secret-change-in-production';
};

// ============================================================================
// AUTH MIDDLEWARE
// ============================================================================

/**
 * Middleware que verifica o token JWT no header Authorization
 * Requer: Authorization: Bearer <token>
 */
export async function authMiddleware(
  request: FastifyRequest,
  reply: FastifyReply
): Promise<void> {
  try {
    const authHeader = request.headers.authorization;

    if (!authHeader) {
      return reply.status(401).send({
        status: 'error',
        code: 'MISSING_TOKEN',
        message: 'Token de autenticação não fornecido',
      });
    }

    // Verificar formato Bearer token
    const parts = authHeader.split(' ');
    if (parts.length !== 2 || parts[0] !== 'Bearer') {
      return reply.status(401).send({
        status: 'error',
        code: 'INVALID_TOKEN_FORMAT',
        message: 'Formato de token inválido. Use: Bearer <token>',
      });
    }

    const token = parts[1];

    // Verificar e decodificar token
    try {
      const decoded = jwt.verify(token, getJwtSecret()) as JWTPayload;

      // Anexar dados do usuário à request
      (request as AuthenticatedRequest).user = decoded;
    } catch (jwtError: any) {
      if (jwtError.name === 'TokenExpiredError') {
        return reply.status(401).send({
          status: 'error',
          code: 'TOKEN_EXPIRED',
          message: 'Token expirado. Faça login novamente',
        });
      }

      return reply.status(401).send({
        status: 'error',
        code: 'INVALID_TOKEN',
        message: 'Token inválido',
      });
    }
  } catch (error) {
    console.error('[AuthMiddleware] Error:', error);
    return reply.status(500).send({
      status: 'error',
      code: 'AUTH_ERROR',
      message: 'Erro interno de autenticação',
    });
  }
}

// ============================================================================
// OPTIONAL AUTH MIDDLEWARE
// ============================================================================

/**
 * Middleware que tenta verificar o token, mas não bloqueia se não houver
 * Útil para rotas que funcionam com ou sem autenticação
 */
export async function optionalAuthMiddleware(
  request: FastifyRequest,
  _reply: FastifyReply
): Promise<void> {
  try {
    const authHeader = request.headers.authorization;

    if (!authHeader) {
      return; // Sem token, mas OK
    }

    const parts = authHeader.split(' ');
    if (parts.length !== 2 || parts[0] !== 'Bearer') {
      return; // Formato errado, mas OK
    }

    const token = parts[1];

    try {
      const decoded = jwt.verify(token, getJwtSecret()) as JWTPayload;
      (request as AuthenticatedRequest).user = decoded;
    } catch {
      // Token inválido, mas OK para optional
    }
  } catch {
    // Erro, mas OK para optional
  }
}

// ============================================================================
// LEGACY MIDDLEWARE (x-user-id header)
// ============================================================================

/**
 * Middleware legado que aceita x-user-id header
 * DEPRECADO: Use authMiddleware com JWT
 * Mantido para compatibilidade durante migração
 */
export async function legacyAuthMiddleware(
  request: FastifyRequest,
  reply: FastifyReply
): Promise<void> {
  // Primeiro, tentar JWT
  const authHeader = request.headers.authorization;

  if (authHeader && authHeader.startsWith('Bearer ')) {
    try {
      const token = authHeader.split(' ')[1];
      const decoded = jwt.verify(token, getJwtSecret()) as JWTPayload;
      (request as AuthenticatedRequest).user = decoded;
      return; // Autenticado via JWT
    } catch {
      // Falha no JWT, tentar header legado
    }
  }

  // Fallback para x-user-id (legado)
  const userId = request.headers['x-user-id'] as string;

  if (!userId) {
    return reply.status(401).send({
      status: 'error',
      code: 'UNAUTHORIZED',
      message: 'Token de autenticação ou x-user-id não fornecido',
    });
  }

  // Criar payload fake para compatibilidade
  (request as AuthenticatedRequest).user = {
    userId,
    email: '',
    name: '',
  };
}

// ============================================================================
// HELPER: Get User from Request
// ============================================================================

/**
 * Helper para extrair dados do usuário da request
 */
export function getUserFromRequest(request: FastifyRequest): JWTPayload | null {
  const authRequest = request as AuthenticatedRequest;
  return authRequest.user || null;
}

/**
 * Helper para extrair userId da request (compatível com legado)
 */
export function getUserIdFromRequest(request: FastifyRequest): string | null {
  const authRequest = request as AuthenticatedRequest;

  // Primeiro, tentar do JWT
  if (authRequest.user?.userId) {
    return authRequest.user.userId;
  }

  // Fallback para header legado
  return (request.headers['x-user-id'] as string) || null;
}
