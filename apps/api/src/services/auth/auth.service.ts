// ============================================================================
// AUTH SERVICE
// Serviço de autenticação com JWT e bcrypt
// ============================================================================

import { SupabaseClient } from '@supabase/supabase-js';
import * as bcrypt from 'bcrypt';
import * as jwt from 'jsonwebtoken';
import * as crypto from 'crypto';
import { getEmailService } from '../email/email.service';

// ============================================================================
// TYPES
// ============================================================================

export interface User {
  id: string;
  email: string;
  name: string;
  avatar_url?: string;
  google_id?: string;
  password_hash?: string;
  email_verified: boolean;
  failed_login_attempts: number;
  locked_until?: string;
  created_at: string;
  last_login?: string;
}

export interface JWTPayload {
  userId: string;
  email: string;
  name: string;
  iat?: number;
  exp?: number;
}

export interface SafeUser {
  id: string;
  email: string;
  name: string;
  avatar_url?: string;
  email_verified: boolean;
  created_at: string;
  last_login?: string;
}

export interface AuthResult {
  success: boolean;
  user?: SafeUser;
  accessToken?: string;
  refreshToken?: string;
  error?: string;
}

export interface RegisterData {
  email: string;
  password: string;
  name: string;
}

export interface LoginData {
  email: string;
  password: string;
}

// ============================================================================
// CONSTANTS
// ============================================================================

const SALT_ROUNDS = 12;
const ACCESS_TOKEN_EXPIRY = '1h';
const REFRESH_TOKEN_EXPIRY = '7d';
const MAX_LOGIN_ATTEMPTS = 5;
const LOCK_DURATION_MINUTES = 30;
const MAX_CONCURRENT_SESSIONS = 5; // Máximo de sessões simultâneas por usuário

// Interface para informações da sessão
export interface SessionInfo {
  deviceInfo?: string;
  ipAddress?: string;
  userAgent?: string;
}

// ============================================================================
// AUTH SERVICE CLASS
// ============================================================================

export class AuthService {
  private supabase: SupabaseClient;
  private jwtSecret: string;
  private jwtRefreshSecret: string;

  constructor(supabase: SupabaseClient) {
    this.supabase = supabase;

    // Use environment variables for JWT secrets
    this.jwtSecret = process.env.JWT_SECRET || 'agnes-agent-jwt-secret-change-in-production';
    this.jwtRefreshSecret = process.env.JWT_REFRESH_SECRET || 'agnes-agent-refresh-secret-change-in-production';

    if (process.env.NODE_ENV === 'production' && !process.env.JWT_SECRET) {
      console.warn('[AuthService] WARNING: Using default JWT secret in production!');
    }
  }

  // ==========================================================================
  // REGISTER
  // ==========================================================================

  async register(data: RegisterData, sessionInfo?: SessionInfo): Promise<AuthResult> {
    try {
      const { email, password, name } = data;

      // Validar email
      if (!this.isValidEmail(email)) {
        return { success: false, error: 'Email inválido' };
      }

      // Validar senha
      const passwordValidation = this.validatePassword(password);
      if (!passwordValidation.valid) {
        return { success: false, error: passwordValidation.error };
      }

      // Verificar se email já existe
      const { data: existingUser } = await this.supabase
        .from('users')
        .select('id')
        .eq('email', email.toLowerCase())
        .single();

      if (existingUser) {
        return { success: false, error: 'Este email já está cadastrado' };
      }

      // Hash da senha
      const passwordHash = await bcrypt.hash(password, SALT_ROUNDS);

      // Gerar token de verificação
      const verificationToken = this.generateToken();
      const verificationExpires = new Date(Date.now() + 24 * 60 * 60 * 1000); // 24h

      // Criar usuário
      const { data: newUser, error: createError } = await this.supabase
        .from('users')
        .insert({
          id: crypto.randomUUID(),
          email: email.toLowerCase(),
          name,
          password_hash: passwordHash,
          email_verified: false,
          verification_token: verificationToken,
          verification_token_expires: verificationExpires.toISOString(),
          failed_login_attempts: 0,
          created_at: new Date().toISOString(),
        })
        .select('id, email, name, avatar_url, email_verified, created_at')
        .single();

      if (createError) {
        console.error('[AuthService] Register error:', createError);
        return { success: false, error: 'Erro ao criar conta' };
      }

      // Criar plano free para novo usuário
      await this.supabase
        .from('user_plans')
        .insert({
          user_id: newUser.id,
          plan: 'free',
          max_agents: 2,
        });

      // Gerar tokens
      const accessToken = this.generateAccessToken(newUser);
      const refreshToken = this.generateRefreshToken(newUser.id);

      // Salvar refresh token (com informações da sessão)
      await this.saveRefreshToken(newUser.id, refreshToken, sessionInfo);

      // Enviar email de boas-vindas (async, não bloqueia)
      const emailService = getEmailService();
      emailService.sendWelcomeEmail(email, name, verificationToken).catch((err) => {
        console.error('[AuthService] Failed to send welcome email:', err);
      });

      return {
        success: true,
        user: newUser,
        accessToken,
        refreshToken,
      };
    } catch (error) {
      console.error('[AuthService] Register exception:', error);
      return { success: false, error: 'Erro interno ao criar conta' };
    }
  }

  // ==========================================================================
  // LOGIN
  // ==========================================================================

  async login(data: LoginData, sessionInfo?: SessionInfo): Promise<AuthResult> {
    try {
      const { email, password } = data;

      // Buscar usuário
      const { data: user, error: userError } = await this.supabase
        .from('users')
        .select('*')
        .eq('email', email.toLowerCase())
        .single();

      if (userError || !user) {
        return { success: false, error: 'Email ou senha incorretos' };
      }

      // Verificar se conta está ativa
      if (user.is_active === false) {
        return {
          success: false,
          error: 'Conta desativada. Entre em contato com o administrador.',
        };
      }

      // Se usuário não tem senha (login via Google), não pode fazer login com senha
      if (!user.password_hash) {
        return {
          success: false,
          error: 'Esta conta usa login via Google. Use o botão "Entrar com Google"',
        };
      }

      // Verificar senha
      const isValidPassword = await bcrypt.compare(password, user.password_hash);

      if (!isValidPassword) {
        return { success: false, error: 'Email ou senha incorretos' };
      }

      // Atualizar último login
      await this.supabase
        .from('users')
        .update({
          last_login: new Date().toISOString(),
        })
        .eq('id', user.id);

      // Gerar tokens
      const accessToken = this.generateAccessToken(user);
      const refreshToken = this.generateRefreshToken(user.id);

      // Salvar refresh token (com informações da sessão)
      await this.saveRefreshToken(user.id, refreshToken, sessionInfo);

      // Retornar sem dados sensíveis
      const { password_hash, refresh_token, ...safeUser } = user;

      return {
        success: true,
        user: safeUser,
        accessToken,
        refreshToken,
      };
    } catch (error) {
      console.error('[AuthService] Login exception:', error);
      return { success: false, error: 'Erro interno ao fazer login' };
    }
  }

  // ==========================================================================
  // LOGOUT
  // ==========================================================================

  /**
   * Logout - Remove sessão específica ou todas as sessões do usuário
   * @param userId - ID do usuário
   * @param refreshToken - Se fornecido, remove apenas essa sessão. Se não, remove todas.
   */
  async logout(userId: string, refreshToken?: string): Promise<{ success: boolean; error?: string }> {
    try {
      if (refreshToken) {
        // Logout específico: remover apenas a sessão com este refresh token
        await this.supabase
          .from('user_sessions')
          .delete()
          .eq('user_id', userId)
          .eq('refresh_token', refreshToken);

        console.log(`[AuthService] Logged out specific session for user ${userId}`);
      } else {
        // Logout de todas as sessões
        await this.supabase
          .from('user_sessions')
          .delete()
          .eq('user_id', userId);

        console.log(`[AuthService] Logged out ALL sessions for user ${userId}`);
      }

      // Manter compatibilidade com campo antigo
      await this.supabase
        .from('users')
        .update({
          refresh_token: null,
          refresh_token_expires: null,
        })
        .eq('id', userId);

      return { success: true };
    } catch (error) {
      console.error('[AuthService] Logout exception:', error);
      return { success: false, error: 'Erro ao fazer logout' };
    }
  }

  /**
   * Logout de todos os dispositivos
   */
  async logoutAllDevices(userId: string): Promise<{ success: boolean; sessionsRemoved: number; error?: string }> {
    try {
      // Contar sessões antes de remover
      const { data: sessions } = await this.supabase
        .from('user_sessions')
        .select('id')
        .eq('user_id', userId);

      const sessionsCount = sessions?.length || 0;

      // Remover todas as sessões
      await this.supabase
        .from('user_sessions')
        .delete()
        .eq('user_id', userId);

      // Limpar campo legado
      await this.supabase
        .from('users')
        .update({
          refresh_token: null,
          refresh_token_expires: null,
        })
        .eq('id', userId);

      console.log(`[AuthService] Removed all ${sessionsCount} sessions for user ${userId}`);

      return { success: true, sessionsRemoved: sessionsCount };
    } catch (error) {
      console.error('[AuthService] Logout all devices exception:', error);
      return { success: false, sessionsRemoved: 0, error: 'Erro ao fazer logout de todos os dispositivos' };
    }
  }

  /**
   * Listar sessões ativas do usuário
   */
  async getActiveSessions(userId: string): Promise<{
    success: boolean;
    sessions?: Array<{
      id: string;
      deviceInfo: string | null;
      ipAddress: string | null;
      createdAt: string;
      lastUsedAt: string;
    }>;
    error?: string;
  }> {
    try {
      const { data: sessions, error } = await this.supabase
        .from('user_sessions')
        .select('id, device_info, ip_address, user_agent, created_at, last_used_at')
        .eq('user_id', userId)
        .gt('expires_at', new Date().toISOString())
        .order('last_used_at', { ascending: false });

      if (error) {
        return { success: false, error: 'Erro ao buscar sessões' };
      }

      return {
        success: true,
        sessions: (sessions || []).map(s => ({
          id: s.id,
          deviceInfo: s.device_info,
          ipAddress: s.ip_address,
          userAgent: s.user_agent,
          createdAt: s.created_at,
          lastUsedAt: s.last_used_at,
        })),
      };
    } catch (error) {
      console.error('[AuthService] Get active sessions exception:', error);
      return { success: false, error: 'Erro ao buscar sessões' };
    }
  }

  // ==========================================================================
  // REFRESH TOKEN
  // ==========================================================================

  async refreshAccessToken(refreshToken: string, sessionInfo?: SessionInfo): Promise<AuthResult> {
    try {
      // Verificar refresh token
      const decoded = jwt.verify(refreshToken, this.jwtRefreshSecret) as { userId: string };

      // NOVO: Primeiro tentar buscar na tabela de sessões
      const { data: session, error: sessionError } = await this.supabase
        .from('user_sessions')
        .select('id, user_id, expires_at')
        .eq('refresh_token', refreshToken)
        .eq('user_id', decoded.userId)
        .single();

      let user;

      if (session) {
        // Sessão encontrada na nova tabela
        // Verificar se sessão expirou
        if (new Date(session.expires_at) < new Date()) {
          // Remover sessão expirada
          await this.supabase.from('user_sessions').delete().eq('id', session.id);
          return { success: false, error: 'Token expirado, faça login novamente' };
        }

        // Buscar dados do usuário
        const { data: userData, error: userError } = await this.supabase
          .from('users')
          .select('*')
          .eq('id', session.user_id)
          .single();

        if (userError || !userData) {
          return { success: false, error: 'Usuário não encontrado' };
        }

        user = userData;

        // Atualizar last_used_at da sessão
        await this.supabase
          .from('user_sessions')
          .update({ last_used_at: new Date().toISOString() })
          .eq('id', session.id);

        // Gerar novos tokens
        const newAccessToken = this.generateAccessToken(user);
        const newRefreshToken = this.generateRefreshToken(user.id);

        // Atualizar sessão existente com novo refresh token (em vez de criar nova)
        const expires = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000);
        await this.supabase
          .from('user_sessions')
          .update({
            refresh_token: newRefreshToken,
            expires_at: expires.toISOString(),
            last_used_at: new Date().toISOString(),
            device_info: sessionInfo?.deviceInfo || null,
            ip_address: sessionInfo?.ipAddress || null,
            user_agent: sessionInfo?.userAgent || null,
          })
          .eq('id', session.id);

        // Manter compatibilidade com campo antigo
        await this.supabase
          .from('users')
          .update({
            refresh_token: newRefreshToken,
            refresh_token_expires: expires.toISOString(),
          })
          .eq('id', user.id);

        const { password_hash, refresh_token, ...safeUser } = user;

        return {
          success: true,
          user: safeUser,
          accessToken: newAccessToken,
          refreshToken: newRefreshToken,
        };
      }

      // FALLBACK: Buscar na tabela users (para tokens antigos)
      const { data: legacyUser, error } = await this.supabase
        .from('users')
        .select('*')
        .eq('id', decoded.userId)
        .eq('refresh_token', refreshToken)
        .single();

      if (error || !legacyUser) {
        return { success: false, error: 'Token inválido ou expirado' };
      }

      // Verificar se refresh token expirou
      if (legacyUser.refresh_token_expires && new Date(legacyUser.refresh_token_expires) < new Date()) {
        return { success: false, error: 'Token expirado, faça login novamente' };
      }

      user = legacyUser;

      // Gerar novos tokens
      const newAccessToken = this.generateAccessToken(user);
      const newRefreshToken = this.generateRefreshToken(user.id);

      // Migrar para novo sistema: criar sessão na tabela user_sessions
      await this.saveRefreshToken(user.id, newRefreshToken, sessionInfo);

      const { password_hash, refresh_token, ...safeUser } = user;

      return {
        success: true,
        user: safeUser,
        accessToken: newAccessToken,
        refreshToken: newRefreshToken,
      };
    } catch (error) {
      console.error('[AuthService] Refresh token exception:', error);
      return { success: false, error: 'Token inválido' };
    }
  }

  // ==========================================================================
  // VERIFY ACCESS TOKEN
  // ==========================================================================

  verifyAccessToken(token: string): JWTPayload | null {
    try {
      const decoded = jwt.verify(token, this.jwtSecret) as JWTPayload;
      return decoded;
    } catch {
      return null;
    }
  }

  // ==========================================================================
  // GET USER BY ID
  // ==========================================================================

  async getUserById(userId: string): Promise<User | null> {
    try {
      const { data: user, error } = await this.supabase
        .from('users')
        .select('id, email, name, avatar_url, email_verified, created_at, last_login')
        .eq('id', userId)
        .single();

      if (error || !user) {
        return null;
      }

      return user as User;
    } catch {
      return null;
    }
  }

  // ==========================================================================
  // CHANGE PASSWORD
  // ==========================================================================

  async changePassword(
    userId: string,
    currentPassword: string,
    newPassword: string
  ): Promise<{ success: boolean; error?: string }> {
    try {
      // Buscar usuário
      const { data: user, error } = await this.supabase
        .from('users')
        .select('password_hash')
        .eq('id', userId)
        .single();

      if (error || !user) {
        return { success: false, error: 'Usuário não encontrado' };
      }

      if (!user.password_hash) {
        return { success: false, error: 'Conta usa login via Google' };
      }

      // Verificar senha atual
      const isValid = await bcrypt.compare(currentPassword, user.password_hash);
      if (!isValid) {
        return { success: false, error: 'Senha atual incorreta' };
      }

      // Validar nova senha
      const validation = this.validatePassword(newPassword);
      if (!validation.valid) {
        return { success: false, error: validation.error };
      }

      // Hash da nova senha
      const newPasswordHash = await bcrypt.hash(newPassword, SALT_ROUNDS);

      // Atualizar
      await this.supabase
        .from('users')
        .update({ password_hash: newPasswordHash })
        .eq('id', userId);

      // Buscar email e nome do usuário para enviar notificação
      const { data: userData } = await this.supabase
        .from('users')
        .select('email, name')
        .eq('id', userId)
        .single();

      if (userData) {
        const emailService = getEmailService();
        emailService.sendPasswordChangedEmail(userData.email, userData.name).catch((err) => {
          console.error('[AuthService] Failed to send password changed email:', err);
        });
      }

      return { success: true };
    } catch (error) {
      console.error('[AuthService] Change password exception:', error);
      return { success: false, error: 'Erro ao alterar senha' };
    }
  }

  // ==========================================================================
  // FORGOT PASSWORD
  // ==========================================================================

  async forgotPassword(email: string): Promise<{ success: boolean; error?: string }> {
    try {
      // Buscar usuário
      const { data: user } = await this.supabase
        .from('users')
        .select('id, password_hash')
        .eq('email', email.toLowerCase())
        .single();

      // Sempre retornar sucesso para não revelar se email existe
      if (!user || !user.password_hash) {
        return { success: true };
      }

      // Gerar token de reset
      const resetToken = this.generateToken();
      const resetExpires = new Date(Date.now() + 60 * 60 * 1000); // 1 hora

      // Buscar nome do usuário
      const { data: userData } = await this.supabase
        .from('users')
        .select('name')
        .eq('id', user.id)
        .single();

      await this.supabase
        .from('users')
        .update({
          reset_password_token: resetToken,
          reset_password_expires: resetExpires.toISOString(),
        })
        .eq('id', user.id);

      // Enviar email com link de reset
      const emailService = getEmailService();
      emailService.sendPasswordResetEmail(email, userData?.name || 'Usuário', resetToken).catch((err) => {
        console.error('[AuthService] Failed to send reset email:', err);
      });

      return { success: true };
    } catch (error) {
      console.error('[AuthService] Forgot password exception:', error);
      return { success: false, error: 'Erro ao processar solicitação' };
    }
  }

  // ==========================================================================
  // RESET PASSWORD
  // ==========================================================================

  async resetPassword(
    token: string,
    newPassword: string
  ): Promise<{ success: boolean; error?: string }> {
    try {
      // Buscar usuário pelo token
      const { data: user, error } = await this.supabase
        .from('users')
        .select('id, reset_password_expires')
        .eq('reset_password_token', token)
        .single();

      if (error || !user) {
        return { success: false, error: 'Token inválido ou expirado' };
      }

      // Verificar se token expirou
      if (user.reset_password_expires && new Date(user.reset_password_expires) < new Date()) {
        return { success: false, error: 'Token expirado' };
      }

      // Validar nova senha
      const validation = this.validatePassword(newPassword);
      if (!validation.valid) {
        return { success: false, error: validation.error };
      }

      // Hash da nova senha
      const passwordHash = await bcrypt.hash(newPassword, SALT_ROUNDS);

      // Atualizar senha e limpar token
      await this.supabase
        .from('users')
        .update({
          password_hash: passwordHash,
          reset_password_token: null,
          reset_password_expires: null,
          failed_login_attempts: 0,
          locked_until: null,
        })
        .eq('id', user.id);

      return { success: true };
    } catch (error) {
      console.error('[AuthService] Reset password exception:', error);
      return { success: false, error: 'Erro ao resetar senha' };
    }
  }

  // ==========================================================================
  // HELPER METHODS
  // ==========================================================================

  private generateAccessToken(user: { id: string; email: string; name: string }): string {
    return jwt.sign(
      {
        userId: user.id,
        email: user.email,
        name: user.name,
      },
      this.jwtSecret,
      { expiresIn: ACCESS_TOKEN_EXPIRY }
    );
  }

  private generateRefreshToken(userId: string): string {
    return jwt.sign(
      { userId },
      this.jwtRefreshSecret,
      { expiresIn: REFRESH_TOKEN_EXPIRY }
    );
  }

  private async saveRefreshToken(
    userId: string,
    refreshToken: string,
    sessionInfo?: SessionInfo
  ): Promise<void> {
    const expires = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000); // 7 dias

    // Inserir nova sessão na tabela user_sessions
    await this.supabase
      .from('user_sessions')
      .insert({
        user_id: userId,
        refresh_token: refreshToken,
        device_info: sessionInfo?.deviceInfo || null,
        ip_address: sessionInfo?.ipAddress || null,
        user_agent: sessionInfo?.userAgent || null,
        expires_at: expires.toISOString(),
        created_at: new Date().toISOString(),
        last_used_at: new Date().toISOString(),
      });

    // Verificar e limitar a 5 sessões simultâneas
    // Buscar todas as sessões do usuário ordenadas por last_used_at (mais antigas primeiro)
    const { data: sessions } = await this.supabase
      .from('user_sessions')
      .select('id')
      .eq('user_id', userId)
      .order('last_used_at', { ascending: true });

    if (sessions && sessions.length > MAX_CONCURRENT_SESSIONS) {
      // Remover as sessões mais antigas que excedem o limite
      const sessionsToRemove = sessions.slice(0, sessions.length - MAX_CONCURRENT_SESSIONS);
      const idsToRemove = sessionsToRemove.map(s => s.id);

      await this.supabase
        .from('user_sessions')
        .delete()
        .in('id', idsToRemove);

      console.log(`[AuthService] Removed ${idsToRemove.length} oldest sessions for user ${userId}`);
    }

    // Também manter compatibilidade com campo antigo na tabela users (para migração gradual)
    await this.supabase
      .from('users')
      .update({
        refresh_token: refreshToken,
        refresh_token_expires: expires.toISOString(),
      })
      .eq('id', userId);
  }

  private async incrementFailedAttempts(userId: string, currentAttempts: number): Promise<void> {
    const newAttempts = currentAttempts + 1;

    const update: Record<string, any> = {
      failed_login_attempts: newAttempts,
    };

    // Bloquear conta se excedeu tentativas
    if (newAttempts >= MAX_LOGIN_ATTEMPTS) {
      update.locked_until = new Date(
        Date.now() + LOCK_DURATION_MINUTES * 60 * 1000
      ).toISOString();
    }

    await this.supabase.from('users').update(update).eq('id', userId);
  }

  private generateToken(): string {
    return crypto.randomBytes(32).toString('hex');
  }

  private isValidEmail(email: string): boolean {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email);
  }

  private validatePassword(password: string): { valid: boolean; error?: string } {
    if (password.length < 8) {
      return { valid: false, error: 'Senha deve ter pelo menos 8 caracteres' };
    }
    if (!/[A-Z]/.test(password)) {
      return { valid: false, error: 'Senha deve ter pelo menos uma letra maiúscula' };
    }
    if (!/[a-z]/.test(password)) {
      return { valid: false, error: 'Senha deve ter pelo menos uma letra minúscula' };
    }
    if (!/[0-9]/.test(password)) {
      return { valid: false, error: 'Senha deve ter pelo menos um número' };
    }
    return { valid: true };
  }
}

// ============================================================================
// FACTORY FUNCTION
// ============================================================================

export function createAuthService(supabase: SupabaseClient): AuthService {
  return new AuthService(supabase);
}
