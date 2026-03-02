// ============================================================================
// AUTH HANDLERS
// Handlers para endpoints de autenticação
// ============================================================================

import { FastifyRequest, FastifyReply } from 'fastify';
import { SupabaseClient } from '@supabase/supabase-js';
import { createAuthService, AuthService, SessionInfo } from '../../services/auth/auth.service';
import { AuthenticatedRequest } from '../middleware/auth.middleware';

// Helper para extrair informações da sessão da request
function extractSessionInfo(request: FastifyRequest): SessionInfo {
  const userAgent = request.headers['user-agent'] || undefined;
  const ip = request.ip ||
    (request.headers['x-forwarded-for'] as string)?.split(',')[0]?.trim() ||
    (request.headers['x-real-ip'] as string) ||
    undefined;

  // Tentar identificar o dispositivo pelo user-agent
  let deviceInfo = 'Desconhecido';
  if (userAgent) {
    if (userAgent.includes('Mobile')) deviceInfo = 'Mobile';
    else if (userAgent.includes('Tablet')) deviceInfo = 'Tablet';
    else if (userAgent.includes('Windows')) deviceInfo = 'Windows PC';
    else if (userAgent.includes('Mac')) deviceInfo = 'Mac';
    else if (userAgent.includes('Linux')) deviceInfo = 'Linux';
    else if (userAgent.includes('Chrome')) deviceInfo = 'Chrome Browser';
    else if (userAgent.includes('Firefox')) deviceInfo = 'Firefox Browser';
    else if (userAgent.includes('Safari')) deviceInfo = 'Safari Browser';
  }

  return {
    deviceInfo,
    ipAddress: ip,
    userAgent,
  };
}

// ============================================================================
// TYPES
// ============================================================================

interface RegisterBody {
  email: string;
  password: string;
  name: string;
}

interface LoginBody {
  email: string;
  password: string;
}

interface RefreshBody {
  refreshToken: string;
}

interface ChangePasswordBody {
  currentPassword: string;
  newPassword: string;
}

interface ForgotPasswordBody {
  email: string;
}

interface ResetPasswordBody {
  token: string;
  newPassword: string;
}

interface LogoutBody {
  refreshToken?: string; // Se fornecido, remove apenas essa sessão
  allDevices?: boolean;  // Se true, remove todas as sessões
}

// ============================================================================
// HANDLER FACTORY
// ============================================================================

export function createAuthHandlers(supabase: SupabaseClient) {
  const authService = createAuthService(supabase);

  return {
    // ========================================================================
    // REGISTER
    // ========================================================================
    register: async (
      request: FastifyRequest<{ Body: RegisterBody }>,
      reply: FastifyReply
    ) => {
      try {
        const { email, password, name } = request.body;

        if (!email || !password || !name) {
          return reply.status(400).send({
            status: 'error',
            code: 'MISSING_FIELDS',
            message: 'Email, senha e nome são obrigatórios',
          });
        }

        // Extrair informações da sessão
        const sessionInfo = extractSessionInfo(request);
        const result = await authService.register({ email, password, name }, sessionInfo);

        if (!result.success) {
          return reply.status(400).send({
            status: 'error',
            code: 'REGISTER_FAILED',
            message: result.error,
          });
        }

        return reply.status(201).send({
          status: 'success',
          message: 'Conta criada com sucesso',
          user: result.user,
          accessToken: result.accessToken,
          refreshToken: result.refreshToken,
        });
      } catch (error) {
        console.error('[AuthHandler] Register error:', error);
        return reply.status(500).send({
          status: 'error',
          code: 'INTERNAL_ERROR',
          message: 'Erro interno ao criar conta',
        });
      }
    },

    // ========================================================================
    // LOGIN
    // ========================================================================
    login: async (
      request: FastifyRequest<{ Body: LoginBody }>,
      reply: FastifyReply
    ) => {
      try {
        const { email, password } = request.body;

        if (!email || !password) {
          return reply.status(400).send({
            status: 'error',
            code: 'MISSING_FIELDS',
            message: 'Email e senha são obrigatórios',
          });
        }

        // Extrair informações da sessão
        const sessionInfo = extractSessionInfo(request);
        const result = await authService.login({ email, password }, sessionInfo);

        if (!result.success) {
          return reply.status(401).send({
            status: 'error',
            code: 'LOGIN_FAILED',
            message: result.error,
          });
        }

        return reply.send({
          status: 'success',
          message: 'Login realizado com sucesso',
          user: result.user,
          accessToken: result.accessToken,
          refreshToken: result.refreshToken,
        });
      } catch (error) {
        console.error('[AuthHandler] Login error:', error);
        return reply.status(500).send({
          status: 'error',
          code: 'INTERNAL_ERROR',
          message: 'Erro interno ao fazer login',
        });
      }
    },

    // ========================================================================
    // LOGOUT
    // ========================================================================
    logout: async (
      request: FastifyRequest<{ Body: LogoutBody }>,
      reply: FastifyReply
    ) => {
      try {
        const authRequest = request as AuthenticatedRequest;
        const userId = authRequest.user?.userId;

        if (!userId) {
          return reply.status(401).send({
            status: 'error',
            code: 'UNAUTHORIZED',
            message: 'Não autenticado',
          });
        }

        const { refreshToken, allDevices } = request.body || {};

        if (allDevices) {
          // Logout de todos os dispositivos
          const result = await authService.logoutAllDevices(userId);
          return reply.send({
            status: 'success',
            message: `Logout realizado em ${result.sessionsRemoved} dispositivo(s)`,
            sessionsRemoved: result.sessionsRemoved,
          });
        }

        // Logout normal (sessão específica se refreshToken fornecido, senão todas)
        await authService.logout(userId, refreshToken);

        return reply.send({
          status: 'success',
          message: 'Logout realizado com sucesso',
        });
      } catch (error) {
        console.error('[AuthHandler] Logout error:', error);
        return reply.status(500).send({
          status: 'error',
          code: 'INTERNAL_ERROR',
          message: 'Erro interno ao fazer logout',
        });
      }
    },

    // ========================================================================
    // GET ACTIVE SESSIONS
    // ========================================================================
    getSessions: async (request: FastifyRequest, reply: FastifyReply) => {
      try {
        const authRequest = request as AuthenticatedRequest;
        const userId = authRequest.user?.userId;

        if (!userId) {
          return reply.status(401).send({
            status: 'error',
            code: 'UNAUTHORIZED',
            message: 'Não autenticado',
          });
        }

        const result = await authService.getActiveSessions(userId);

        if (!result.success) {
          return reply.status(500).send({
            status: 'error',
            code: 'FETCH_SESSIONS_FAILED',
            message: result.error,
          });
        }

        return reply.send({
          status: 'success',
          sessions: result.sessions,
          maxSessions: 5,
        });
      } catch (error) {
        console.error('[AuthHandler] Get sessions error:', error);
        return reply.status(500).send({
          status: 'error',
          code: 'INTERNAL_ERROR',
          message: 'Erro interno ao buscar sessões',
        });
      }
    },

    // ========================================================================
    // LOGOUT ALL DEVICES
    // ========================================================================
    logoutAllDevices: async (request: FastifyRequest, reply: FastifyReply) => {
      try {
        const authRequest = request as AuthenticatedRequest;
        const userId = authRequest.user?.userId;

        if (!userId) {
          return reply.status(401).send({
            status: 'error',
            code: 'UNAUTHORIZED',
            message: 'Não autenticado',
          });
        }

        const result = await authService.logoutAllDevices(userId);

        if (!result.success) {
          return reply.status(500).send({
            status: 'error',
            code: 'LOGOUT_ALL_FAILED',
            message: result.error,
          });
        }

        return reply.send({
          status: 'success',
          message: `Todas as ${result.sessionsRemoved} sessão(ões) foram encerradas`,
          sessionsRemoved: result.sessionsRemoved,
        });
      } catch (error) {
        console.error('[AuthHandler] Logout all devices error:', error);
        return reply.status(500).send({
          status: 'error',
          code: 'INTERNAL_ERROR',
          message: 'Erro interno ao fazer logout de todos os dispositivos',
        });
      }
    },

    // ========================================================================
    // REFRESH TOKEN
    // ========================================================================
    refresh: async (
      request: FastifyRequest<{ Body: RefreshBody }>,
      reply: FastifyReply
    ) => {
      try {
        const { refreshToken } = request.body;

        if (!refreshToken) {
          return reply.status(400).send({
            status: 'error',
            code: 'MISSING_TOKEN',
            message: 'Refresh token é obrigatório',
          });
        }

        // DEBUG: Log do refresh token recebido
        console.log('[AuthHandler] Refresh token received:', {
          tokenLength: refreshToken?.length,
          tokenStart: refreshToken?.substring(0, 20),
          tokenType: typeof refreshToken,
        });

        // Extrair informações da sessão para atualizar
        const sessionInfo = extractSessionInfo(request);
        const result = await authService.refreshAccessToken(refreshToken, sessionInfo);

        if (!result.success) {
          return reply.status(401).send({
            status: 'error',
            code: 'REFRESH_FAILED',
            message: result.error,
          });
        }

        return reply.send({
          status: 'success',
          accessToken: result.accessToken,
          refreshToken: result.refreshToken,
        });
      } catch (error) {
        console.error('[AuthHandler] Refresh error:', error);
        return reply.status(500).send({
          status: 'error',
          code: 'INTERNAL_ERROR',
          message: 'Erro interno ao renovar token',
        });
      }
    },

    // ========================================================================
    // GET CURRENT USER (ME)
    // ========================================================================
    me: async (request: FastifyRequest, reply: FastifyReply) => {
      try {
        const authRequest = request as AuthenticatedRequest;
        const userId = authRequest.user?.userId;

        if (!userId) {
          return reply.status(401).send({
            status: 'error',
            code: 'UNAUTHORIZED',
            message: 'Não autenticado',
          });
        }

        const user = await authService.getUserById(userId);

        if (!user) {
          return reply.status(404).send({
            status: 'error',
            code: 'USER_NOT_FOUND',
            message: 'Usuário não encontrado',
          });
        }

        return reply.send({
          status: 'success',
          user,
        });
      } catch (error) {
        console.error('[AuthHandler] Me error:', error);
        return reply.status(500).send({
          status: 'error',
          code: 'INTERNAL_ERROR',
          message: 'Erro interno ao buscar usuário',
        });
      }
    },

    // ========================================================================
    // CHANGE PASSWORD
    // ========================================================================
    changePassword: async (
      request: FastifyRequest<{ Body: ChangePasswordBody }>,
      reply: FastifyReply
    ) => {
      try {
        const authRequest = request as AuthenticatedRequest;
        const userId = authRequest.user?.userId;

        if (!userId) {
          return reply.status(401).send({
            status: 'error',
            code: 'UNAUTHORIZED',
            message: 'Não autenticado',
          });
        }

        const { currentPassword, newPassword } = request.body;

        if (!currentPassword || !newPassword) {
          return reply.status(400).send({
            status: 'error',
            code: 'MISSING_FIELDS',
            message: 'Senha atual e nova senha são obrigatórias',
          });
        }

        const result = await authService.changePassword(userId, currentPassword, newPassword);

        if (!result.success) {
          return reply.status(400).send({
            status: 'error',
            code: 'CHANGE_PASSWORD_FAILED',
            message: result.error,
          });
        }

        return reply.send({
          status: 'success',
          message: 'Senha alterada com sucesso',
        });
      } catch (error) {
        console.error('[AuthHandler] Change password error:', error);
        return reply.status(500).send({
          status: 'error',
          code: 'INTERNAL_ERROR',
          message: 'Erro interno ao alterar senha',
        });
      }
    },

    // ========================================================================
    // FORGOT PASSWORD
    // ========================================================================
    forgotPassword: async (
      request: FastifyRequest<{ Body: ForgotPasswordBody }>,
      reply: FastifyReply
    ) => {
      try {
        const { email } = request.body;

        if (!email) {
          return reply.status(400).send({
            status: 'error',
            code: 'MISSING_EMAIL',
            message: 'Email é obrigatório',
          });
        }

        await authService.forgotPassword(email);

        // Sempre retorna sucesso (não revelar se email existe)
        return reply.send({
          status: 'success',
          message: 'Se o email existir, você receberá instruções para recuperar a senha',
        });
      } catch (error) {
        console.error('[AuthHandler] Forgot password error:', error);
        return reply.status(500).send({
          status: 'error',
          code: 'INTERNAL_ERROR',
          message: 'Erro interno ao processar solicitação',
        });
      }
    },

    // ========================================================================
    // RESET PASSWORD
    // ========================================================================
    resetPassword: async (
      request: FastifyRequest<{ Body: ResetPasswordBody }>,
      reply: FastifyReply
    ) => {
      try {
        const { token, newPassword } = request.body;

        if (!token || !newPassword) {
          return reply.status(400).send({
            status: 'error',
            code: 'MISSING_FIELDS',
            message: 'Token e nova senha são obrigatórios',
          });
        }

        const result = await authService.resetPassword(token, newPassword);

        if (!result.success) {
          return reply.status(400).send({
            status: 'error',
            code: 'RESET_PASSWORD_FAILED',
            message: result.error,
          });
        }

        return reply.send({
          status: 'success',
          message: 'Senha resetada com sucesso. Faça login com a nova senha',
        });
      } catch (error) {
        console.error('[AuthHandler] Reset password error:', error);
        return reply.status(500).send({
          status: 'error',
          code: 'INTERNAL_ERROR',
          message: 'Erro interno ao resetar senha',
        });
      }
    },
  };
}
