/**
 * ============================================================================
 * CLEAR HISTORY HANDLER
 * ============================================================================
 * Limpa completamente o histórico de conversa de um lead.
 *
 * Remove dados de 3 lugares:
 * 1. Tabela de mensagens (leadbox_messages_{agent})
 * 2. Tabela de leads (LeadboxCRM_{agent})
 * 3. Cache Redis (ContextCacheService)
 *
 * @author Claude AI
 * @date 2026-01-26
 */

import { FastifyRequest, FastifyReply } from 'fastify';
import { supabaseAdmin } from '../../services/supabase/client';
import { getContextCacheService } from '../../services/context-cache/context-cache.service';

// ============================================================================
// LOGGER
// ============================================================================

const Logger = {
  info: (msg: string, data?: unknown) => console.info(`[ClearHistory] ${msg}`, data ?? ''),
  warn: (msg: string, data?: unknown) => console.warn(`[ClearHistory] ${msg}`, data ?? ''),
  error: (msg: string, data?: unknown) => console.error(`[ClearHistory] ${msg}`, data ?? ''),
};

// ============================================================================
// TYPES
// ============================================================================

export interface ClearHistoryBody {
  /**
   * Sufixo do agente (ex: "Ana_0c514c4c")
   * Usado para montar nomes das tabelas:
   * - leadbox_messages_{agent}
   * - LeadboxCRM_{agent}
   */
  agent: string;

  /**
   * ID WhatsApp do lead (ex: "556697194084@s.whatsapp.net")
   */
  remotejid: string;

  /**
   * ID do agente (UUID completo) - opcional
   * Se fornecido, valida permissão do usuário
   */
  agentId?: string;
}

export interface ClearHistoryResponse {
  success: boolean;
  message?: string;
  error?: string;
  details?: {
    messagesCleared: boolean;
    leadCleared: boolean;
    cacheInvalidated: boolean;
  };
}

// ============================================================================
// HANDLER
// ============================================================================

/**
 * POST /api/leads/clear-history
 *
 * Limpa completamente o histórico de conversa de um lead.
 *
 * @example
 * POST /api/leads/clear-history
 * {
 *   "agent": "Ana_0c514c4c",
 *   "remotejid": "556697194084@s.whatsapp.net"
 * }
 */
export async function clearHistoryHandler(
  request: FastifyRequest<{ Body: ClearHistoryBody }>,
  reply: FastifyReply
): Promise<FastifyReply> {
  const { agent, remotejid, agentId } = request.body;

  // Validar parâmetros obrigatórios
  if (!agent || !remotejid) {
    return reply.status(400).send({
      success: false,
      error: 'Parâmetros obrigatórios: agent, remotejid',
    } as ClearHistoryResponse);
  }

  // Validar formato do remotejid
  if (!remotejid.includes('@')) {
    return reply.status(400).send({
      success: false,
      error: 'remotejid deve estar no formato: numero@s.whatsapp.net',
    } as ClearHistoryResponse);
  }

  Logger.info('Limpando histórico', { agent, remotejid });

  const details = {
    messagesCleared: false,
    leadCleared: false,
    cacheInvalidated: false,
  };

  try {
    // ========================================================================
    // 1. LIMPAR TABELA DE MENSAGENS (leadbox_messages_{agent})
    // ========================================================================
    const messagesTable = `leadbox_messages_${agent}`;

    try {
      const { error: msgError } = await supabaseAdmin
        .from(messagesTable)
        .update({
          conversation_history: { messages: [] },
          Msg_model: null,
          Msg_user: null,
          creat: new Date().toISOString(),
        })
        .eq('remotejid', remotejid);

      if (msgError) {
        Logger.warn(`Erro ao limpar ${messagesTable}`, msgError);
      } else {
        details.messagesCleared = true;
        Logger.info(`Histórico limpo em ${messagesTable}`);
      }
    } catch (e) {
      Logger.warn(`Tabela ${messagesTable} pode não existir`, e);
    }

    // ========================================================================
    // 2. LIMPAR TABELA DE LEADS (LeadboxCRM_{agent})
    // ========================================================================
    const leadsTable = `LeadboxCRM_${agent}`;

    try {
      const { error: leadError } = await supabaseAdmin
        .from(leadsTable)
        .update({
          conversation_history: null,
          resumo: null,
          ultimo_intent: null,
        })
        .eq('remotejid', remotejid);

      if (leadError) {
        Logger.warn(`Erro ao limpar ${leadsTable}`, leadError);
      } else {
        details.leadCleared = true;
        Logger.info(`Histórico limpo em ${leadsTable}`);
      }
    } catch (e) {
      Logger.warn(`Tabela ${leadsTable} pode não existir`, e);
    }

    // ========================================================================
    // 3. INVALIDAR CACHE REDIS
    // ========================================================================
    try {
      // Precisamos do agentId para invalidar o cache
      // Se não foi passado, buscar pelo nome do agente
      let resolvedAgentId = agentId;

      if (!resolvedAgentId) {
        // Tentar extrair o ID do sufixo (último segmento após _)
        const parts = agent.split('_');
        const shortId = parts[parts.length - 1];

        // Buscar agente pelo short_id ou nome
        const { data: agentData } = await supabaseAdmin
          .from('agents')
          .select('id')
          .or(`id.ilike.%${shortId}%,name.eq.${parts[0]}`)
          .limit(1)
          .single();

        if (agentData) {
          resolvedAgentId = agentData.id;
        }
      }

      if (resolvedAgentId) {
        const cacheService = getContextCacheService();
        await cacheService.invalidate(resolvedAgentId, remotejid);
        details.cacheInvalidated = true;
        Logger.info('Cache Redis invalidado', { agentId: resolvedAgentId, remotejid });
      } else {
        Logger.warn('agentId não encontrado, cache pode não ter sido invalidado');
      }
    } catch (e) {
      Logger.warn('Erro ao invalidar cache Redis', e);
    }

    // ========================================================================
    // 4. RETORNAR RESULTADO
    // ========================================================================
    const allCleared = details.messagesCleared || details.leadCleared;

    return reply.send({
      success: allCleared,
      message: allCleared
        ? 'Histórico limpo com sucesso'
        : 'Nenhum registro encontrado para limpar',
      details,
    } as ClearHistoryResponse);

  } catch (error) {
    Logger.error('Erro ao limpar histórico', error);
    return reply.status(500).send({
      success: false,
      error: error instanceof Error ? error.message : 'Erro desconhecido',
      details,
    } as ClearHistoryResponse);
  }
}

// ============================================================================
// HANDLER COM AUTENTICAÇÃO (opcional - para uso via CRM)
// ============================================================================

/**
 * POST /api/leads/clear-history/secure
 *
 * Versão com autenticação - valida se o usuário tem acesso ao agente
 */
export async function clearHistorySecureHandler(
  request: FastifyRequest<{ Body: ClearHistoryBody }>,
  reply: FastifyReply
): Promise<FastifyReply> {
  const userId = (request as any).user?.id || request.headers['x-user-id'] as string;
  const { agent, remotejid, agentId } = request.body;

  if (!userId) {
    return reply.status(401).send({
      success: false,
      error: 'Unauthorized: Authentication required',
    } as ClearHistoryResponse);
  }

  // Validar parâmetros
  if (!agent || !remotejid) {
    return reply.status(400).send({
      success: false,
      error: 'Parâmetros obrigatórios: agent, remotejid',
    } as ClearHistoryResponse);
  }

  // Se agentId fornecido, validar permissão
  if (agentId) {
    const { data: agentData, error: agentError } = await supabaseAdmin
      .from('agents')
      .select('id')
      .eq('id', agentId)
      .eq('user_id', userId)
      .single();

    if (agentError || !agentData) {
      return reply.status(403).send({
        success: false,
        error: 'Forbidden: Você não tem acesso a este agente',
      } as ClearHistoryResponse);
    }
  }

  // Chamar handler principal
  return clearHistoryHandler(request, reply);
}
