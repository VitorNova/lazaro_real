import { FastifyRequest, FastifyReply } from 'fastify';
import { google } from 'googleapis';
import { SupabaseClient } from '@supabase/supabase-js';

// ============================================================================
// TYPES
// ============================================================================

interface GoogleOAuthStartRequest {
  Querystring: {
    agent_id: string;
    redirect_uri?: string;
  };
}

interface GoogleOAuthCallbackRequest {
  Querystring: {
    code: string;
    state: string;
    error?: string;
  };
}

interface GoogleOAuthStatusRequest {
  Params: {
    agentId: string;
  };
}

interface GoogleOAuthDisconnectRequest {
  Params: {
    agentId: string;
  };
}

// ============================================================================
// CONFIG
// ============================================================================

const GOOGLE_SCOPES = [
  'https://www.googleapis.com/auth/calendar',
  'https://www.googleapis.com/auth/calendar.events',
];

function getGoogleOAuth2Client(redirectUri?: string) {
  const clientId = process.env.GOOGLE_CLIENT_ID;
  const clientSecret = process.env.GOOGLE_CLIENT_SECRET;

  if (!clientId || !clientSecret) {
    throw new Error('GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET devem estar configurados');
  }

  return new google.auth.OAuth2(
    clientId,
    clientSecret,
    redirectUri
  );
}

// ============================================================================
// HANDLERS
// ============================================================================

/**
 * Inicia o fluxo OAuth2 - redireciona para Google
 * Aceita agent_id como UUID válido ou "pending" para fluxo de wizard
 */
export async function googleOAuthStartHandler(
  request: FastifyRequest<GoogleOAuthStartRequest>,
  reply: FastifyReply
) {
  try {
    const { agent_id, redirect_uri } = request.query;
    // Prioridade: 1) request.user do JWT middleware, 2) x-user-id header (legado)
    const userId = (request as any).user?.id || request.headers['x-user-id'] as string;

    // agent_id pode ser um UUID válido ou "pending" para wizard
    if (!agent_id) {
      return reply.status(400).send({
        status: 'error',
        message: 'agent_id é obrigatório (use "pending" para wizard)',
      });
    }

    if (!userId) {
      return reply.status(401).send({
        status: 'error',
        message: 'Usuário não autenticado',
      });
    }

    // Definir redirect URI (sempre usar o callback do backend)
    const callbackUrl = `${process.env.API_BASE_URL}/api/google/oauth/callback`;
    const oauth2Client = getGoogleOAuth2Client(callbackUrl);

    // Criar state com informações para o callback
    const state = Buffer.from(JSON.stringify({
      agent_id, // Pode ser UUID ou "pending"
      user_id: userId,
      redirect_uri: redirect_uri || request.headers.referer || process.env.FRONTEND_URL || 'http://localhost:3000',
    })).toString('base64');

    // Gerar URL de autorização
    const authUrl = oauth2Client.generateAuthUrl({
      access_type: 'offline',
      scope: GOOGLE_SCOPES,
      state,
      prompt: 'consent', // Forçar consent para obter refresh_token
      include_granted_scopes: true,
    });

    return reply.send({
      status: 'success',
      auth_url: authUrl,
    });
  } catch (error) {
    console.error('[GoogleOAuth] Start error:', error);
    return reply.status(500).send({
      status: 'error',
      message: error instanceof Error ? error.message : 'Erro ao iniciar autenticação',
    });
  }
}

/**
 * Callback do OAuth2 - recebe código e troca por tokens
 * Suporta dois modos:
 * 1. Com agent_id: salva tokens diretamente no agente
 * 2. Sem agent_id (pending): retorna tokens para o frontend salvar temporariamente
 */
export function createGoogleOAuthCallbackHandler(supabase: SupabaseClient) {
  return async function googleOAuthCallbackHandler(
    request: FastifyRequest<GoogleOAuthCallbackRequest>,
    reply: FastifyReply
  ) {
    try {
      const { code, state, error } = request.query;

      // Verificar se houve erro na autorização
      if (error) {
        console.error('[GoogleOAuth] Authorization error:', error);
        return reply.redirect(
          `${process.env.FRONTEND_URL}?google_error=${encodeURIComponent(error)}`
        );
      }

      if (!code || !state) {
        return reply.redirect(
          `${process.env.FRONTEND_URL}?google_error=missing_code_or_state`
        );
      }

      // Decodificar state
      let stateData: { agent_id: string; user_id: string; redirect_uri: string };
      try {
        stateData = JSON.parse(Buffer.from(state, 'base64').toString());
      } catch {
        return reply.redirect(
          `${process.env.FRONTEND_URL}?google_error=invalid_state`
        );
      }

      const { agent_id, user_id, redirect_uri } = stateData;

      // Configurar OAuth2 client com redirect URI
      const callbackUrl = `${process.env.API_BASE_URL}/api/google/oauth/callback`;
      const oauth2Client = getGoogleOAuth2Client(callbackUrl);

      // Trocar código por tokens
      const { tokens } = await oauth2Client.getToken(code);

      if (!tokens.refresh_token) {
        console.error('[GoogleOAuth] No refresh_token received');
        return reply.redirect(
          `${redirect_uri}?google_error=no_refresh_token`
        );
      }

      // Configurar client com tokens para buscar informações do calendário
      oauth2Client.setCredentials(tokens);
      const calendar = google.calendar({ version: 'v3', auth: oauth2Client });

      // Buscar calendário primário para obter o email
      const calendarInfo = await calendar.calendarList.get({ calendarId: 'primary' });
      const calendarId = calendarInfo.data.id || 'primary';
      const calendarEmail = calendarInfo.data.summary || '';

      // Criar objeto de credenciais
      const googleCredentials = {
        refresh_token: tokens.refresh_token,
        access_token: tokens.access_token,
        expiry_date: tokens.expiry_date,
        token_type: tokens.token_type,
        scope: tokens.scope,
        calendar_email: calendarEmail,
      };

      // Modo 1: Se temos agent_id válido, salvar no banco
      if (agent_id && agent_id !== 'pending') {
        const { error: updateError } = await supabase
          .from('agents')
          .update({
            google_calendar_enabled: true,
            google_credentials: googleCredentials,
            google_calendar_id: calendarId,
            updated_at: new Date().toISOString(),
          })
          .eq('id', agent_id)
          .eq('user_id', user_id);

        if (updateError) {
          console.error('[GoogleOAuth] Failed to save credentials:', updateError);
          return reply.redirect(
            `${redirect_uri}?google_error=save_failed`
          );
        }

        console.log('[GoogleOAuth] Successfully connected Google Calendar', {
          agentId: agent_id,
          calendarId,
          calendarEmail,
        });

        // Redirecionar de volta ao frontend com sucesso
        return reply.redirect(
          `${redirect_uri}?google_connected=true&calendar_email=${encodeURIComponent(calendarEmail)}`
        );
      }

      // Modo 2: Sem agent_id - retornar tokens para frontend armazenar temporariamente
      // Encodar credenciais em base64 para passar via URL (seguro pois é mesmo domínio)
      const encodedCredentials = Buffer.from(JSON.stringify({
        credentials: googleCredentials,
        calendar_id: calendarId,
        calendar_email: calendarEmail,
      })).toString('base64');

      console.log('[GoogleOAuth] Returning tokens for pending agent', {
        calendarEmail,
      });

      // Redirecionar com tokens encodados (usando hash para não ir ao servidor em requests subsequentes)
      return reply.redirect(
        `${redirect_uri}?google_pending=true&calendar_email=${encodeURIComponent(calendarEmail)}#google_data=${encodedCredentials}`
      );
    } catch (error) {
      console.error('[GoogleOAuth] Callback error:', error);
      return reply.redirect(
        `${process.env.FRONTEND_URL}?google_error=${encodeURIComponent(
          error instanceof Error ? error.message : 'unknown_error'
        )}`
      );
    }
  };
}

/**
 * Verifica status da conexão Google Calendar
 */
export function createGoogleOAuthStatusHandler(supabase: SupabaseClient) {
  return async function googleOAuthStatusHandler(
    request: FastifyRequest<GoogleOAuthStatusRequest>,
    reply: FastifyReply
  ) {
    try {
      const { agentId } = request.params;
      // Prioridade: 1) request.user do JWT middleware, 2) x-user-id header (legado)
      const userId = (request as any).user?.id || request.headers['x-user-id'] as string;

      if (!userId) {
        return reply.status(401).send({
          status: 'error',
          message: 'Usuário não autenticado',
        });
      }

      const { data: agent, error } = await supabase
        .from('agents')
        .select('google_calendar_enabled, google_credentials, google_calendar_id')
        .eq('id', agentId)
        .eq('user_id', userId)
        .single();

      if (error || !agent) {
        return reply.status(404).send({
          status: 'error',
          message: 'Agente não encontrado',
        });
      }

      const credentials = agent.google_credentials as any;

      return reply.send({
        status: 'success',
        connected: agent.google_calendar_enabled || false,
        calendar_id: agent.google_calendar_id || null,
        calendar_email: credentials?.calendar_email || null,
      });
    } catch (error) {
      console.error('[GoogleOAuth] Status error:', error);
      return reply.status(500).send({
        status: 'error',
        message: error instanceof Error ? error.message : 'Erro ao verificar status',
      });
    }
  };
}

/**
 * Desconecta Google Calendar do agente
 */
export function createGoogleOAuthDisconnectHandler(supabase: SupabaseClient) {
  return async function googleOAuthDisconnectHandler(
    request: FastifyRequest<GoogleOAuthDisconnectRequest>,
    reply: FastifyReply
  ) {
    try {
      const { agentId } = request.params;
      // Prioridade: 1) request.user do JWT middleware, 2) x-user-id header (legado)
      const userId = (request as any).user?.id || request.headers['x-user-id'] as string;

      if (!userId) {
        return reply.status(401).send({
          status: 'error',
          message: 'Usuário não autenticado',
        });
      }

      // Buscar credenciais atuais para revogar
      const { data: agent } = await supabase
        .from('agents')
        .select('google_credentials')
        .eq('id', agentId)
        .eq('user_id', userId)
        .single();

      // Tentar revogar token no Google
      if (agent?.google_credentials) {
        try {
          const credentials = agent.google_credentials as any;
          if (credentials.refresh_token) {
            const oauth2Client = getGoogleOAuth2Client();
            await oauth2Client.revokeToken(credentials.refresh_token);
          }
        } catch (revokeError) {
          console.warn('[GoogleOAuth] Failed to revoke token:', revokeError);
          // Continuar mesmo se falhar a revogação
        }
      }

      // Limpar credenciais no banco
      const { error: updateError } = await supabase
        .from('agents')
        .update({
          google_calendar_enabled: false,
          google_credentials: null,
          google_calendar_id: 'primary',
          updated_at: new Date().toISOString(),
        })
        .eq('id', agentId)
        .eq('user_id', userId);

      if (updateError) {
        return reply.status(500).send({
          status: 'error',
          message: 'Falha ao desconectar Google Calendar',
        });
      }

      return reply.send({
        status: 'success',
        message: 'Google Calendar desconectado com sucesso',
      });
    } catch (error) {
      console.error('[GoogleOAuth] Disconnect error:', error);
      return reply.status(500).send({
        status: 'error',
        message: error instanceof Error ? error.message : 'Erro ao desconectar',
      });
    }
  };
}

/**
 * Lista calendários disponíveis do usuário
 */
export function createGoogleCalendarsListHandler(supabase: SupabaseClient) {
  return async function googleCalendarsListHandler(
    request: FastifyRequest<GoogleOAuthStatusRequest>,
    reply: FastifyReply
  ) {
    try {
      const { agentId } = request.params;
      // Prioridade: 1) request.user do JWT middleware, 2) x-user-id header (legado)
      const userId = (request as any).user?.id || request.headers['x-user-id'] as string;

      if (!userId) {
        return reply.status(401).send({
          status: 'error',
          message: 'Usuário não autenticado',
        });
      }

      const { data: agent, error } = await supabase
        .from('agents')
        .select('google_credentials')
        .eq('id', agentId)
        .eq('user_id', userId)
        .single();

      if (error || !agent || !agent.google_credentials) {
        return reply.status(400).send({
          status: 'error',
          message: 'Google Calendar não conectado',
        });
      }

      const credentials = agent.google_credentials as any;

      // Configurar OAuth2 client
      const oauth2Client = getGoogleOAuth2Client();
      oauth2Client.setCredentials({
        refresh_token: credentials.refresh_token,
      });

      // Listar calendários
      const calendar = google.calendar({ version: 'v3', auth: oauth2Client });
      const response = await calendar.calendarList.list();

      const calendars = (response.data.items || []).map((cal) => ({
        id: cal.id,
        summary: cal.summary,
        description: cal.description,
        primary: cal.primary || false,
        accessRole: cal.accessRole,
      }));

      return reply.send({
        status: 'success',
        calendars,
      });
    } catch (error) {
      console.error('[GoogleOAuth] List calendars error:', error);
      return reply.status(500).send({
        status: 'error',
        message: error instanceof Error ? error.message : 'Erro ao listar calendários',
      });
    }
  };
}

/**
 * Lista calendários usando credenciais passadas diretamente (para wizard sem agente)
 */
export async function googleCalendarsFromCredentialsHandler(
  request: FastifyRequest<{
    Body: { credentials: any };
  }>,
  reply: FastifyReply
) {
  try {
    const { credentials } = request.body as { credentials: any };

    if (!credentials || !credentials.refresh_token) {
      return reply.status(400).send({
        status: 'error',
        message: 'Credenciais inválidas',
      });
    }

    // Configurar OAuth2 client
    const oauth2Client = getGoogleOAuth2Client();
    oauth2Client.setCredentials({
      refresh_token: credentials.refresh_token,
      access_token: credentials.access_token,
    });

    // Listar calendários
    const calendar = google.calendar({ version: 'v3', auth: oauth2Client });
    const response = await calendar.calendarList.list();

    const calendars = (response.data.items || []).map((cal) => ({
      id: cal.id,
      summary: cal.summary,
      description: cal.description,
      primary: cal.primary || false,
      backgroundColor: cal.backgroundColor,
      accessRole: cal.accessRole,
    }));

    return reply.send({
      status: 'success',
      calendars,
    });
  } catch (error) {
    console.error('[GoogleOAuth] List calendars from credentials error:', error);
    return reply.status(500).send({
      status: 'error',
      message: error instanceof Error ? error.message : 'Erro ao listar calendários',
    });
  }
}

/**
 * Atualiza calendário selecionado
 */
export function createGoogleCalendarSelectHandler(supabase: SupabaseClient) {
  return async function googleCalendarSelectHandler(
    request: FastifyRequest<{
      Params: { agentId: string };
      Body: { calendar_id: string };
    }>,
    reply: FastifyReply
  ) {
    try {
      const { agentId } = request.params;
      const { calendar_id } = request.body as { calendar_id: string };
      // Prioridade: 1) request.user do JWT middleware, 2) x-user-id header (legado)
      const userId = (request as any).user?.id || request.headers['x-user-id'] as string;

      if (!userId) {
        return reply.status(401).send({
          status: 'error',
          message: 'Usuário não autenticado',
        });
      }

      if (!calendar_id) {
        return reply.status(400).send({
          status: 'error',
          message: 'calendar_id é obrigatório',
        });
      }

      const { error: updateError } = await supabase
        .from('agents')
        .update({
          google_calendar_id: calendar_id,
          updated_at: new Date().toISOString(),
        })
        .eq('id', agentId)
        .eq('user_id', userId);

      if (updateError) {
        return reply.status(500).send({
          status: 'error',
          message: 'Falha ao selecionar calendário',
        });
      }

      return reply.send({
        status: 'success',
        message: 'Calendário selecionado com sucesso',
        calendar_id,
      });
    } catch (error) {
      console.error('[GoogleOAuth] Select calendar error:', error);
      return reply.status(500).send({
        status: 'error',
        message: error instanceof Error ? error.message : 'Erro ao selecionar calendário',
      });
    }
  };
}
