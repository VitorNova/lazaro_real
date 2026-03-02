import { FastifyRequest, FastifyReply } from 'fastify';
import { supabaseAdmin } from '../../services/supabase/client';

// ============================================================================
// TYPES
// ============================================================================

export type LearningEntryStatus = 'pending' | 'approved' | 'rejected' | 'applied';

const VALID_STATUSES: LearningEntryStatus[] = ['pending', 'approved', 'rejected', 'applied'];

function isValidStatus(status: string): status is LearningEntryStatus {
  return VALID_STATUSES.includes(status as LearningEntryStatus);
}

interface LearningEntry {
  id: string;
  agent_id: string;
  agent_name?: string;
  lead_id?: string;
  user_question: string;
  ai_response: string;
  correct_response?: string;
  status: LearningEntryStatus;
  created_by?: string;
  reviewed_by?: string;
  reviewed_at?: string;
  applied_at?: string;
  knowledge_base_id?: string;
  tags?: string[];
  metadata?: any;
  created_at: string;
  updated_at: string;
}

interface LearningEntriesResponse {
  entries: LearningEntry[];
  total: number;
  page: number;
  limit: number;
  by_status: Record<LearningEntryStatus, number>;
}

// ============================================================================
// HANDLERS
// ============================================================================

/**
 * GET /api/learning-entries - Lista entradas de curadoria de conhecimento
 */
export async function getLearningEntriesHandler(
  request: FastifyRequest<{
    Querystring: {
      agent_id?: string;
      status?: string;
      page?: string;
      limit?: string;
    };
  }>,
  reply: FastifyReply
): Promise<void> {
  try {
    const userId = (request as any).user?.id;
    const { agent_id, status, page = '1', limit = '50' } = request.query;

    if (!userId) {
      reply.status(401).send({ status: 'error', message: 'Authentication required' });
      return;
    }

    const pageNum = parseInt(page, 10);
    const limitNum = Math.min(parseInt(limit, 10), 100);
    const offset = (pageNum - 1) * limitNum;

    // Buscar agentes do usuário
    const { data: userAgents } = await supabaseAdmin
      .from('agents')
      .select('id, name')
      .eq('user_id', userId);

    if (!userAgents || userAgents.length === 0) {
      reply.send({
        status: 'success',
        data: {
          entries: [],
          total: 0,
          page: pageNum,
          limit: limitNum,
          by_status: { pending: 0, approved: 0, rejected: 0, applied: 0 },
        },
      });
      return;
    }

    const agentIds = userAgents.map(a => a.id);
    const agentMap = new Map(userAgents.map(a => [a.id, a.name]));

    // Construir query
    let query = supabaseAdmin
      .from('learning_entries')
      .select('*', { count: 'exact' })
      .in('agent_id', agentIds)
      .order('created_at', { ascending: false })
      .range(offset, offset + limitNum - 1);

    // Aplicar filtros
    if (agent_id) {
      query = query.eq('agent_id', agent_id);
    }
    if (status) {
      query = query.eq('status', status);
    }

    const { data: entries, error, count } = await query;

    if (error) {
      console.error('[LearningEntries] Error fetching entries:', error);
      reply.status(500).send({ status: 'error', message: 'Failed to fetch learning entries' });
      return;
    }

    // Adicionar nome do agente
    const entriesWithAgentName = (entries || []).map(entry => ({
      ...entry,
      agent_name: agentMap.get(entry.agent_id) || 'Unknown',
    }));

    // Contar por status
    const { data: statusCounts } = await supabaseAdmin
      .from('learning_entries')
      .select('status')
      .in('agent_id', agentIds);

    const byStatus: Record<LearningEntryStatus, number> = {
      pending: 0,
      approved: 0,
      rejected: 0,
      applied: 0,
    };

    (statusCounts || []).forEach(s => {
      if (s.status in byStatus) {
        byStatus[s.status as LearningEntryStatus]++;
      }
    });

    reply.send({
      status: 'success',
      data: {
        entries: entriesWithAgentName,
        total: count || 0,
        page: pageNum,
        limit: limitNum,
        by_status: byStatus,
      },
    });
  } catch (error) {
    console.error('[LearningEntries] Error:', error);
    reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

/**
 * POST /api/learning-entries - Criar nova entrada de curadoria
 */
export async function createLearningEntryHandler(
  request: FastifyRequest<{
    Body: {
      agent_id: string;
      lead_id?: string;
      user_question: string;
      ai_response: string;
      correct_response?: string;
      tags?: string[];
      metadata?: any;
    };
  }>,
  reply: FastifyReply
): Promise<void> {
  try {
    const userId = (request as any).user?.id;
    const body = request.body;

    if (!userId) {
      reply.status(401).send({ status: 'error', message: 'Authentication required' });
      return;
    }

    // Verificar se agente pertence ao usuário
    const { data: agent } = await supabaseAdmin
      .from('agents')
      .select('id')
      .eq('id', body.agent_id)
      .eq('user_id', userId)
      .single();

    if (!agent) {
      reply.status(404).send({ status: 'error', message: 'Agent not found' });
      return;
    }

    // Criar entrada
    const { data: entry, error } = await supabaseAdmin
      .from('learning_entries')
      .insert({
        agent_id: body.agent_id,
        lead_id: body.lead_id,
        user_question: body.user_question,
        ai_response: body.ai_response,
        correct_response: body.correct_response,
        status: 'pending',
        created_by: userId,
        tags: body.tags || [],
        metadata: body.metadata || {},
      })
      .select()
      .single();

    if (error) {
      console.error('[LearningEntries] Error creating entry:', error);
      reply.status(500).send({ status: 'error', message: 'Failed to create learning entry' });
      return;
    }

    reply.send({ status: 'success', data: entry });
  } catch (error) {
    console.error('[LearningEntries] Error:', error);
    reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

/**
 * PATCH /api/learning-entries/:id - Atualizar entrada (revisar, aprovar, rejeitar)
 */
export async function updateLearningEntryHandler(
  request: FastifyRequest<{
    Params: { id: string };
    Body: {
      status?: string;
      correct_response?: string;
      tags?: string[];
    };
  }>,
  reply: FastifyReply
): Promise<void> {
  try {
    const userId = (request as any).user?.id;
    const { id } = request.params;
    const body = request.body;

    if (!userId) {
      reply.status(401).send({ status: 'error', message: 'Authentication required' });
      return;
    }

    // Buscar entrada e verificar permissão
    const { data: entry, error: fetchError } = await supabaseAdmin
      .from('learning_entries')
      .select('*, agents!inner(user_id)')
      .eq('id', id)
      .single();

    if (fetchError || !entry) {
      reply.status(404).send({ status: 'error', message: 'Learning entry not found' });
      return;
    }

    if ((entry.agents as any).user_id !== userId) {
      reply.status(403).send({ status: 'error', message: 'Access denied' });
      return;
    }

    const now = new Date().toISOString();
    const updateData: Record<string, any> = {
      updated_at: now,
    };

    if (body.status) {
      updateData.status = body.status;
      updateData.reviewed_by = userId;
      updateData.reviewed_at = now;

      if (body.status === 'applied') {
        updateData.applied_at = now;
      }
    }

    if (body.correct_response !== undefined) {
      updateData.correct_response = body.correct_response;
    }

    if (body.tags) {
      updateData.tags = body.tags;
    }

    const { data: updated, error: updateError } = await supabaseAdmin
      .from('learning_entries')
      .update(updateData)
      .eq('id', id)
      .select()
      .single();

    if (updateError) {
      console.error('[LearningEntries] Error updating entry:', updateError);
      reply.status(500).send({ status: 'error', message: 'Failed to update learning entry' });
      return;
    }

    reply.send({ status: 'success', data: updated });
  } catch (error) {
    console.error('[LearningEntries] Error:', error);
    reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

/**
 * DELETE /api/learning-entries/:id - Deletar entrada
 */
export async function deleteLearningEntryHandler(
  request: FastifyRequest<{ Params: { id: string } }>,
  reply: FastifyReply
): Promise<void> {
  try {
    const userId = (request as any).user?.id;
    const { id } = request.params;

    if (!userId) {
      reply.status(401).send({ status: 'error', message: 'Authentication required' });
      return;
    }

    // Buscar entrada e verificar permissão
    const { data: entry, error: fetchError } = await supabaseAdmin
      .from('learning_entries')
      .select('*, agents!inner(user_id)')
      .eq('id', id)
      .single();

    if (fetchError || !entry) {
      reply.status(404).send({ status: 'error', message: 'Learning entry not found' });
      return;
    }

    if ((entry.agents as any).user_id !== userId) {
      reply.status(403).send({ status: 'error', message: 'Access denied' });
      return;
    }

    const { error: deleteError } = await supabaseAdmin
      .from('learning_entries')
      .delete()
      .eq('id', id);

    if (deleteError) {
      console.error('[LearningEntries] Error deleting entry:', deleteError);
      reply.status(500).send({ status: 'error', message: 'Failed to delete learning entry' });
      return;
    }

    reply.send({ status: 'success', message: 'Learning entry deleted' });
  } catch (error) {
    console.error('[LearningEntries] Error:', error);
    reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

/**
 * POST /api/learning-entries/:id/apply - Aplicar correção à base de conhecimento
 */
export async function applyLearningEntryHandler(
  request: FastifyRequest<{
    Params: { id: string };
    Body: { knowledge_base_id: string };
  }>,
  reply: FastifyReply
): Promise<void> {
  try {
    const userId = (request as any).user?.id;
    const { id } = request.params;
    const { knowledge_base_id } = request.body;

    if (!userId) {
      reply.status(401).send({ status: 'error', message: 'Authentication required' });
      return;
    }

    // Buscar entrada
    const { data: entry, error: fetchError } = await supabaseAdmin
      .from('learning_entries')
      .select('*, agents!inner(user_id)')
      .eq('id', id)
      .single();

    if (fetchError || !entry) {
      reply.status(404).send({ status: 'error', message: 'Learning entry not found' });
      return;
    }

    if ((entry.agents as any).user_id !== userId) {
      reply.status(403).send({ status: 'error', message: 'Access denied' });
      return;
    }

    if (!entry.correct_response) {
      reply.status(400).send({ status: 'error', message: 'No correct response to apply' });
      return;
    }

    // Verificar se knowledge_base existe e pertence ao usuário
    const { data: kb, error: kbError } = await supabaseAdmin
      .from('knowledge_bases')
      .select('id, agent_id')
      .eq('id', knowledge_base_id)
      .single();

    if (kbError || !kb) {
      reply.status(404).send({ status: 'error', message: 'Knowledge base not found' });
      return;
    }

    // TODO: Adicionar lógica para inserir na knowledge base
    // Por enquanto, apenas marcamos como aplicado

    const now = new Date().toISOString();
    const { data: updated, error: updateError } = await supabaseAdmin
      .from('learning_entries')
      .update({
        status: 'applied',
        applied_at: now,
        knowledge_base_id,
        reviewed_by: userId,
        reviewed_at: now,
        updated_at: now,
      })
      .eq('id', id)
      .select()
      .single();

    if (updateError) {
      console.error('[LearningEntries] Error applying entry:', updateError);
      reply.status(500).send({ status: 'error', message: 'Failed to apply learning entry' });
      return;
    }

    reply.send({
      status: 'success',
      message: 'Learning entry applied to knowledge base',
      data: updated,
    });
  } catch (error) {
    console.error('[LearningEntries] Error:', error);
    reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

/**
 * GET /api/learning-entries/:id - Buscar entrada específica
 */
export async function getEntryByIdHandler(
  request: FastifyRequest<{ Params: { id: string } }>,
  reply: FastifyReply
): Promise<void> {
  try {
    const userId = (request as any).user?.id;
    const { id } = request.params;

    if (!userId) {
      reply.status(401).send({ status: 'error', message: 'Authentication required' });
      return;
    }

    // Buscar entrada com nome do agente
    const { data: entry, error } = await supabaseAdmin
      .from('learning_entries')
      .select('*, agents!inner(user_id, name)')
      .eq('id', id)
      .single();

    if (error || !entry) {
      reply.status(404).send({ status: 'error', message: 'Learning entry not found' });
      return;
    }

    // Verificar permissão
    if ((entry.agents as any).user_id !== userId) {
      reply.status(403).send({ status: 'error', message: 'Access denied' });
      return;
    }

    // Adicionar agent_name ao resultado
    const entryWithAgentName = {
      ...entry,
      agent_name: (entry.agents as any).name || 'Unknown',
      agents: undefined, // Remover objeto agents do resultado
    };

    reply.send({ status: 'success', data: entryWithAgentName });
  } catch (error) {
    console.error('[LearningEntries] Error:', error);
    reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

/**
 * POST /api/learning-entries/:id/teach - Ensinar IA com resposta correta
 */
export async function teachHandler(
  request: FastifyRequest<{
    Params: { id: string };
    Body: { correct_response: string };
  }>,
  reply: FastifyReply
): Promise<void> {
  try {
    const userId = (request as any).user?.id;
    const { id } = request.params;
    const { correct_response } = request.body;

    if (!userId) {
      reply.status(401).send({ status: 'error', message: 'Authentication required' });
      return;
    }

    if (!correct_response || correct_response.trim() === '') {
      reply.status(400).send({ status: 'error', message: 'correct_response is required' });
      return;
    }

    // Buscar entrada e verificar permissão
    const { data: entry, error: fetchError } = await supabaseAdmin
      .from('learning_entries')
      .select('*, agents!inner(user_id, name)')
      .eq('id', id)
      .single();

    if (fetchError || !entry) {
      reply.status(404).send({ status: 'error', message: 'Learning entry not found' });
      return;
    }

    if ((entry.agents as any).user_id !== userId) {
      reply.status(403).send({ status: 'error', message: 'Access denied' });
      return;
    }

    // Atualizar entrada: correct_response, status=approved, reviewed_by, reviewed_at
    const now = new Date().toISOString();
    const { data: updated, error: updateError } = await supabaseAdmin
      .from('learning_entries')
      .update({
        correct_response,
        status: 'approved',
        reviewed_by: userId,
        reviewed_at: now,
        updated_at: now,
      })
      .eq('id', id)
      .select()
      .single();

    if (updateError) {
      console.error('[LearningEntries] Error teaching entry:', updateError);
      reply.status(500).send({ status: 'error', message: 'Failed to teach entry' });
      return;
    }

    reply.send({ status: 'success', data: updated });
  } catch (error) {
    console.error('[LearningEntries] Error:', error);
    reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

/**
 * POST /api/learning-entries/:id/approve - Aprovar entrada
 */
export async function approveHandler(
  request: FastifyRequest<{ Params: { id: string } }>,
  reply: FastifyReply
): Promise<void> {
  try {
    const userId = (request as any).user?.id;
    const { id } = request.params;

    if (!userId) {
      reply.status(401).send({ status: 'error', message: 'Authentication required' });
      return;
    }

    // Buscar entrada e verificar permissão
    const { data: entry, error: fetchError } = await supabaseAdmin
      .from('learning_entries')
      .select('*, agents!inner(user_id, name)')
      .eq('id', id)
      .single();

    if (fetchError || !entry) {
      reply.status(404).send({ status: 'error', message: 'Learning entry not found' });
      return;
    }

    if ((entry.agents as any).user_id !== userId) {
      reply.status(403).send({ status: 'error', message: 'Access denied' });
      return;
    }

    // Atualizar status para approved
    const now = new Date().toISOString();
    const { data: updated, error: updateError } = await supabaseAdmin
      .from('learning_entries')
      .update({
        status: 'approved',
        reviewed_by: userId,
        reviewed_at: now,
        updated_at: now,
      })
      .eq('id', id)
      .select()
      .single();

    if (updateError) {
      console.error('[LearningEntries] Error approving entry:', updateError);
      reply.status(500).send({ status: 'error', message: 'Failed to approve entry' });
      return;
    }

    reply.send({ status: 'success', data: updated });
  } catch (error) {
    console.error('[LearningEntries] Error:', error);
    reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

/**
 * POST /api/learning-entries/:id/reject - Rejeitar entrada
 */
export async function rejectHandler(
  request: FastifyRequest<{
    Params: { id: string };
    Body: { reason?: string };
  }>,
  reply: FastifyReply
): Promise<void> {
  try {
    const userId = (request as any).user?.id;
    const { id } = request.params;
    const { reason } = request.body;

    if (!userId) {
      reply.status(401).send({ status: 'error', message: 'Authentication required' });
      return;
    }

    // Buscar entrada e verificar permissão
    const { data: entry, error: fetchError } = await supabaseAdmin
      .from('learning_entries')
      .select('*, agents!inner(user_id, name)')
      .eq('id', id)
      .single();

    if (fetchError || !entry) {
      reply.status(404).send({ status: 'error', message: 'Learning entry not found' });
      return;
    }

    if ((entry.agents as any).user_id !== userId) {
      reply.status(403).send({ status: 'error', message: 'Access denied' });
      return;
    }

    // Preparar metadata com reason
    const metadata = entry.metadata || {};
    if (reason) {
      metadata.rejection_reason = reason;
    }

    // Atualizar status para rejected
    const now = new Date().toISOString();
    const { data: updated, error: updateError } = await supabaseAdmin
      .from('learning_entries')
      .update({
        status: 'rejected',
        reviewed_by: userId,
        reviewed_at: now,
        metadata,
        updated_at: now,
      })
      .eq('id', id)
      .select()
      .single();

    if (updateError) {
      console.error('[LearningEntries] Error rejecting entry:', updateError);
      reply.status(500).send({ status: 'error', message: 'Failed to reject entry' });
      return;
    }

    reply.send({ status: 'success', data: updated });
  } catch (error) {
    console.error('[LearningEntries] Error:', error);
    reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

/**
 * GET /api/learning-entries/stats - Estatísticas de aprendizado
 */
export async function getStatsHandler(
  request: FastifyRequest<{
    Querystring: { agent_id?: string };
  }>,
  reply: FastifyReply
): Promise<void> {
  try {
    const userId = (request as any).user?.id;
    const { agent_id } = request.query;

    if (!userId) {
      reply.status(401).send({ status: 'error', message: 'Authentication required' });
      return;
    }

    // Buscar agentes do usuário
    const { data: userAgents } = await supabaseAdmin
      .from('agents')
      .select('id')
      .eq('user_id', userId);

    if (!userAgents || userAgents.length === 0) {
      reply.send({
        status: 'success',
        data: {
          pending: 0,
          approved: 0,
          applied: 0,
          rejected: 0,
          categories: [],
        },
      });
      return;
    }

    const agentIds = userAgents.map(a => a.id);

    // Filtrar por agent_id se fornecido
    let query = supabaseAdmin
      .from('learning_entries')
      .select('status')
      .in('agent_id', agentIds);

    if (agent_id) {
      query = query.eq('agent_id', agent_id);
    }

    const { data: entries } = await query;

    // Contar por status
    const stats = {
      pending: 0,
      approved: 0,
      applied: 0,
      rejected: 0,
    };

    (entries || []).forEach(entry => {
      if (entry.status in stats) {
        stats[entry.status as keyof typeof stats]++;
      }
    });

    reply.send({
      status: 'success',
      data: {
        ...stats,
        categories: [], // Campo category não existe no banco
      },
    });
  } catch (error) {
    console.error('[LearningEntries] Error:', error);
    reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

/**
 * POST /api/learning-entries/bulk-apply - Aplicar em lote
 */
export async function bulkApplyHandler(
  request: FastifyRequest<{
    Body: { ids: string[] };
  }>,
  reply: FastifyReply
): Promise<void> {
  try {
    const userId = (request as any).user?.id;
    const { ids } = request.body;

    if (!userId) {
      reply.status(401).send({ status: 'error', message: 'Authentication required' });
      return;
    }

    if (!ids || !Array.isArray(ids) || ids.length === 0) {
      reply.status(400).send({ status: 'error', message: 'ids array is required' });
      return;
    }

    let successCount = 0;
    let failedCount = 0;

    // Processar cada entrada
    for (const id of ids) {
      try {
        // Buscar entrada e verificar permissão
        const { data: entry, error: fetchError } = await supabaseAdmin
          .from('learning_entries')
          .select('*, agents!inner(user_id)')
          .eq('id', id)
          .single();

        if (fetchError || !entry) {
          failedCount++;
          continue;
        }

        if ((entry.agents as any).user_id !== userId) {
          failedCount++;
          continue;
        }

        if (!entry.correct_response) {
          failedCount++;
          continue;
        }

        // Aplicar entrada
        const now = new Date().toISOString();
        const { error: updateError } = await supabaseAdmin
          .from('learning_entries')
          .update({
            status: 'applied',
            applied_at: now,
            reviewed_by: userId,
            reviewed_at: now,
            updated_at: now,
          })
          .eq('id', id);

        if (updateError) {
          failedCount++;
        } else {
          successCount++;
        }
      } catch (err) {
        console.error(`[LearningEntries] Error applying entry ${id}:`, err);
        failedCount++;
      }
    }

    reply.send({
      status: 'success',
      data: {
        success: successCount,
        failed: failedCount,
      },
    });
  } catch (error) {
    console.error('[LearningEntries] Error:', error);
    reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}
