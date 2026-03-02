import { FastifyRequest, FastifyReply } from 'fastify';
import { supabaseAdmin } from '../../services/supabase/client';
import { z } from 'zod';

// ============================================================================
// TYPES
// ============================================================================

interface Manutencao {
  id: string;
  subscription_id: string;
  customer_id: string;
  proxima_manutencao: string | null;
  maintenance_status: string | null;
  notificacao_enviada_at: string | null;
  endereco_instalacao: string | null;
  equipamentos: any[] | null;
  cliente_nome: string | null;
  cliente_telefone: string | null;
  valor_mensal: number | null;
  data_inicio: string | null;
  data_termino: string | null;
}

interface ManutencaoDashboard {
  id: string;
  customer_name: string;
  phone: string | null;
  equipamentos: string;
  endereco_instalacao: string | null;
  proxima_manutencao: string;
  maintenance_status: string;
  maintenance_type: string | null;
  atrasado: boolean;
  dias_atraso: number;
  // Timeline fields
  notificacao_enviada_at: string | null;
  cliente_respondeu_at: string | null;
  transferido_at: string | null;
  agendamento_confirmado_at: string | null;
  // Extra info
  problema_relatado: string | null;
  observacoes: string | null;
}

interface ManutencaoFeita {
  id: string;
  customer_name: string;
  phone: string | null;
  equipamentos: string;
  endereco_instalacao: string | null;
  manutencao_vencimento_original: string | null;
  manutencao_concluida_at: string;
  manutencao_concluida_por: string;
}

interface ManutencoesDashboardResponse {
  resumo: {
    a_fazer: number;
    feitas: number;
    // Detailed counts
    notificados: number;
    transferidos: number;
    agendados: number;
    corretivas: number;
  };
  contratos: ManutencaoDashboard[];
  contratos_feitos?: ManutencaoFeita[];
}

// ============================================================================
// VALIDATION SCHEMAS
// ============================================================================

const UpdateMaintenanceStatusSchema = z.object({
  status: z.enum(['pending', 'notified', 'contacted', 'transferred', 'scheduled', 'completed', 'skipped']),
});

type UpdateMaintenanceStatusBody = z.infer<typeof UpdateMaintenanceStatusSchema>;

// ============================================================================
// GET ALL MANUTENCOES
// ============================================================================

export async function getManutencoesHandler(
  request: FastifyRequest<{ Querystring: { user_id?: string; agent_id?: string; status?: string } }>,
  reply: FastifyReply
) {
  try {
    const { agent_id, status } = request.query;
    const user_id = (request as any).user?.id || request.query.user_id;

    if (!user_id) {
      return reply.status(400).send({
        success: false,
        error: 'Authentication required',
        statusCode: 400,
      });
    }

    // Buscar agentes do usuario
    let agentsQuery = supabaseAdmin
      .from('agents')
      .select('id')
      .eq('user_id', user_id);

    if (agent_id) {
      agentsQuery = agentsQuery.eq('id', agent_id);
    }

    const { data: agents, error: agentsError } = await agentsQuery;

    if (agentsError) {
      console.error('[ManutencoesHandler] Error fetching agents:', agentsError);
      return reply.status(500).send({
        success: false,
        error: 'Error fetching agents',
        statusCode: 500,
      });
    }

    if (!agents || agents.length === 0) {
      return reply.send({
        success: true,
        data: {
          manutencoes: [],
          total: 0,
        },
      });
    }

    const agentIds = agents.map(a => a.id);

    // Buscar manutenções (sem join - asaas_clientes tem PK composta)
    let manutencoesQuery = supabaseAdmin
      .from('contract_details')
      .select(`
        id,
        agent_id,
        subscription_id,
        customer_id,
        proxima_manutencao,
        maintenance_status,
        notificacao_enviada_at,
        endereco_instalacao,
        equipamentos,
        valor_mensal,
        data_inicio,
        data_termino
      `)
      .in('agent_id', agentIds)
      .not('proxima_manutencao', 'is', null);

    // Filtrar por status se fornecido
    if (status) {
      manutencoesQuery = manutencoesQuery.eq('maintenance_status', status);
    }

    manutencoesQuery = manutencoesQuery.order('proxima_manutencao', { ascending: true });

    const { data: manutencoes, error: manutencoesError } = await manutencoesQuery;

    if (manutencoesError) {
      console.error('[ManutencoesHandler] Error fetching manutencoes:', manutencoesError);
      return reply.status(500).send({
        success: false,
        error: 'Error fetching maintenance records',
        statusCode: 500,
      });
    }

    // Buscar dados dos clientes separadamente (PK composta: id + agent_id)
    const customerIds = [...new Set((manutencoes || [])
      .filter((m: any) => m.customer_id)
      .map((m: any) => m.customer_id))];

    let clientesMap: Record<string, { name: string; mobile_phone: string }> = {};

    if (customerIds.length > 0) {
      const { data: clientes, error: clientesError } = await supabaseAdmin
        .from('asaas_clientes')
        .select('id, agent_id, name, mobile_phone')
        .in('id', customerIds)
        .in('agent_id', agentIds);

      if (!clientesError && clientes) {
        // Criar mapa por customer_id (pode haver duplicatas por agent, usar o primeiro)
        for (const c of clientes) {
          if (!clientesMap[c.id]) {
            clientesMap[c.id] = { name: c.name, mobile_phone: c.mobile_phone };
          }
        }
      }
    }

    // Formatar resposta
    const formattedManutencoes: Manutencao[] = (manutencoes || []).map((m: any) => {
      const cliente = m.customer_id ? clientesMap[m.customer_id] : null;
      return {
        id: m.id,
        subscription_id: m.subscription_id,
        customer_id: m.customer_id,
        proxima_manutencao: m.proxima_manutencao,
        maintenance_status: m.maintenance_status || 'pending',
        notificacao_enviada_at: m.notificacao_enviada_at,
        endereco_instalacao: m.endereco_instalacao,
        equipamentos: m.equipamentos,
        cliente_nome: cliente?.name || null,
        cliente_telefone: cliente?.mobile_phone || null,
        valor_mensal: m.valor_mensal ? parseFloat(m.valor_mensal) : null,
        data_inicio: m.data_inicio,
        data_termino: m.data_termino,
      };
    });

    return reply.send({
      success: true,
      data: {
        manutencoes: formattedManutencoes,
        total: formattedManutencoes.length,
      },
    });
  } catch (error) {
    console.error('[ManutencoesHandler] Error:', error);
    return reply.status(500).send({
      success: false,
      error: 'Internal server error',
      statusCode: 500,
    });
  }
}

// ============================================================================
// UPDATE MAINTENANCE STATUS
// ============================================================================

export async function updateMaintenanceStatusHandler(
  request: FastifyRequest<{
    Params: { id: string };
    Body: any;
  }>,
  reply: FastifyReply
) {
  try {
    const { id } = request.params;
    const user_id = (request as any).user?.id;

    if (!user_id) {
      return reply.status(401).send({
        success: false,
        error: 'Authentication required',
        statusCode: 401,
      });
    }

    // Validar body
    const validation = UpdateMaintenanceStatusSchema.safeParse(request.body);
    if (!validation.success) {
      return reply.status(400).send({
        success: false,
        error: validation.error.errors.map(e => e.message).join(', '),
        statusCode: 400,
      });
    }

    const { status } = validation.data;

    // Buscar contrato para verificar ownership
    const { data: contract, error: contractError } = await supabaseAdmin
      .from('contract_details')
      .select('id, agent_id, proxima_manutencao, notificacao_enviada_at')
      .eq('id', id)
      .single();

    if (contractError || !contract) {
      console.error('[ManutencoesHandler] Contract not found:', contractError);
      return reply.status(404).send({
        success: false,
        error: 'Maintenance record not found',
        statusCode: 404,
      });
    }

    // Verificar se o agente pertence ao usuario
    const { data: agent, error: agentError } = await supabaseAdmin
      .from('agents')
      .select('id')
      .eq('id', contract.agent_id)
      .eq('user_id', user_id)
      .single();

    if (agentError || !agent) {
      return reply.status(403).send({
        success: false,
        error: 'Access denied',
        statusCode: 403,
      });
    }

    // Preparar dados de atualização
    const now = new Date();
    const updateData: Record<string, any> = {
      maintenance_status: status,
      updated_at: now.toISOString(),
    };

    // Se status = 'completed', recalcular próxima manutenção (+6 meses)
    if (status === 'completed') {
      const proximaManutencao = new Date(now);
      proximaManutencao.setMonth(proximaManutencao.getMonth() + 6);

      updateData.proxima_manutencao = proximaManutencao.toISOString().split('T')[0];
      updateData.maintenance_status = 'pending';
      updateData.notificacao_enviada_at = null;

      console.info('[ManutencoesHandler] Maintenance completed, next maintenance scheduled for:', updateData.proxima_manutencao);
    }

    // Se status = 'notified', registrar quando foi notificado
    if (status === 'notified' && !contract.notificacao_enviada_at) {
      updateData.notificacao_enviada_at = now.toISOString();
    }

    // Atualizar no banco
    const { data: updatedContract, error: updateError } = await supabaseAdmin
      .from('contract_details')
      .update(updateData)
      .eq('id', id)
      .select()
      .single();

    if (updateError) {
      console.error('[ManutencoesHandler] Error updating maintenance:', updateError);
      return reply.status(500).send({
        success: false,
        error: 'Error updating maintenance status',
        statusCode: 500,
      });
    }

    console.info(`[ManutencoesHandler] Maintenance ${id} updated to status: ${status}`);

    return reply.send({
      success: true,
      data: updatedContract,
    });
  } catch (error) {
    console.error('[ManutencoesHandler] Error:', error);
    return reply.status(500).send({
      success: false,
      error: 'Internal server error',
      statusCode: 500,
    });
  }
}

// ============================================================================
// GET MANUTENCOES DASHBOARD (com filtro por mês)
// ============================================================================

export async function getManutencoesDashboardHandler(
  request: FastifyRequest<{ Querystring: { user_id?: string; agent_id?: string; month?: string } }>,
  reply: FastifyReply
) {
  try {
    const { agent_id, month } = request.query;
    const user_id = (request as any).user?.id || request.query.user_id;

    if (!user_id) {
      return reply.status(400).send({
        success: false,
        error: 'Authentication required',
        statusCode: 400,
      });
    }

    // Buscar agentes do usuario
    let agentsQuery = supabaseAdmin
      .from('agents')
      .select('id')
      .eq('user_id', user_id);

    if (agent_id) {
      agentsQuery = agentsQuery.eq('id', agent_id);
    }

    const { data: agents, error: agentsError } = await agentsQuery;

    if (agentsError) {
      console.error('[ManutencoesDashboard] Error fetching agents:', agentsError);
      return reply.status(500).send({
        success: false,
        error: 'Error fetching agents',
        statusCode: 500,
      });
    }

    if (!agents || agents.length === 0) {
      return reply.send({
        success: true,
        data: {
          resumo: { a_fazer: 0, feitas: 0, notificados: 0, transferidos: 0, agendados: 0, corretivas: 0 },
          contratos: [],
        } as ManutencoesDashboardResponse,
      });
    }

    const agentIds = agents.map(a => a.id);

    // Determinar período de filtro
    const hoje = new Date();
    const hojeStr = hoje.toISOString().split('T')[0];

    let mesInicio: string;
    let mesFim: string;
    let isMesAtual = false;

    if (month) {
      // Formato esperado: 2026-02
      const [year, monthNum] = month.split('-').map(Number);
      mesInicio = `${year}-${String(monthNum).padStart(2, '0')}-01`;
      const ultimoDia = new Date(year, monthNum, 0).getDate();
      mesFim = `${year}-${String(monthNum).padStart(2, '0')}-${ultimoDia}`;

      // Verificar se é o mês atual
      const mesAtual = `${hoje.getFullYear()}-${String(hoje.getMonth() + 1).padStart(2, '0')}`;
      isMesAtual = month === mesAtual;
    } else {
      // Mês atual por padrão
      const year = hoje.getFullYear();
      const monthNum = hoje.getMonth() + 1;
      mesInicio = `${year}-${String(monthNum).padStart(2, '0')}-01`;
      const ultimoDia = new Date(year, monthNum, 0).getDate();
      mesFim = `${year}-${String(monthNum).padStart(2, '0')}-${ultimoDia}`;
      isMesAtual = true;
    }

    // Buscar manutenções A FAZER
    // Se mês atual: TODOS atrasados (datas < hoje) + do mês atual
    // Se mês futuro: só do mês selecionado
    let aFazerQuery = supabaseAdmin
      .from('contract_details')
      .select(`
        id,
        agent_id,
        customer_id,
        proxima_manutencao,
        maintenance_status,
        maintenance_type,
        notificacao_enviada_at,
        cliente_respondeu_at,
        transferido_at,
        agendamento_confirmado_at,
        problema_relatado,
        observacoes,
        endereco_instalacao,
        equipamentos
      `)
      .in('agent_id', agentIds)
      .not('proxima_manutencao', 'is', null)
      .in('maintenance_status', ['pending', 'notified', 'contacted', 'transferred', 'scheduled']);

    if (isMesAtual) {
      // Mês atual: atrasados OU do mês
      aFazerQuery = aFazerQuery.or(`proxima_manutencao.lt.${hojeStr},and(proxima_manutencao.gte.${mesInicio},proxima_manutencao.lte.${mesFim})`);
    } else {
      // Mês específico
      aFazerQuery = aFazerQuery.gte('proxima_manutencao', mesInicio).lte('proxima_manutencao', mesFim);
    }

    aFazerQuery = aFazerQuery.order('proxima_manutencao', { ascending: true });

    const { data: aFazerData, error: aFazerError } = await aFazerQuery;

    if (aFazerError) {
      console.error('[ManutencoesDashboard] Error fetching a_fazer:', aFazerError);
      return reply.status(500).send({
        success: false,
        error: 'Error fetching maintenance records',
        statusCode: 500,
      });
    }

    // Buscar manutenções FEITAS no mês selecionado
    // Filtra por manutencao_concluida_at (data que foi marcada como feita)
    let feitasQuery = supabaseAdmin
      .from('contract_details')
      .select(`
        id,
        agent_id,
        customer_id,
        equipamentos,
        endereco_instalacao,
        manutencao_vencimento_original,
        manutencao_concluida_at,
        manutencao_concluida_por
      `)
      .in('agent_id', agentIds)
      .eq('maintenance_status', 'completed')
      .not('manutencao_concluida_at', 'is', null);

    // Aplicar filtro de mês nas feitas
    feitasQuery = feitasQuery
      .gte('manutencao_concluida_at', `${mesInicio}T00:00:00`)
      .lt('manutencao_concluida_at', `${mesFim}T23:59:59`)
      .order('manutencao_concluida_at', { ascending: false });

    const { data: feitasData, error: feitasError } = await feitasQuery;

    if (feitasError) {
      console.error('[ManutencoesDashboard] Error fetching feitas:', feitasError);
    }

    // Buscar dados dos clientes (incluindo das feitas)
    const allContracts = [...(aFazerData || []), ...(feitasData || [])];
    const customerIds = [...new Set(allContracts
      .filter((m: any) => m.customer_id)
      .map((m: any) => m.customer_id))];

    let clientesMap: Record<string, { name: string; mobile_phone: string }> = {};

    if (customerIds.length > 0) {
      const { data: clientes, error: clientesError } = await supabaseAdmin
        .from('asaas_clientes')
        .select('id, agent_id, name, mobile_phone')
        .in('id', customerIds)
        .in('agent_id', agentIds);

      if (!clientesError && clientes) {
        for (const c of clientes) {
          if (!clientesMap[c.id]) {
            clientesMap[c.id] = { name: c.name, mobile_phone: c.mobile_phone };
          }
        }
      }
    }

    // Formatar equipamentos como string legível
    const formatEquipamentos = (equipamentos: any[]): string => {
      if (!equipamentos || !Array.isArray(equipamentos) || equipamentos.length === 0) {
        return 'Não informado';
      }
      return equipamentos.map(e => {
        const marca = e.marca || 'Ar';
        const btus = e.btus ? `${Math.round(e.btus / 1000)}k` : '';
        return `${marca} ${btus}`.trim();
      }).join(', ');
    };

    // Calcular dias de atraso
    const calcularDiasAtraso = (proximaManutencao: string): number => {
      const dataManut = new Date(proximaManutencao);
      const diffTime = hoje.getTime() - dataManut.getTime();
      const diffDays = Math.floor(diffTime / (1000 * 60 * 60 * 24));
      return diffDays > 0 ? diffDays : 0;
    };

    // Formatar resposta
    const contratos: ManutencaoDashboard[] = (aFazerData || []).map((m: any) => {
      const cliente = m.customer_id ? clientesMap[m.customer_id] : null;
      const diasAtraso = calcularDiasAtraso(m.proxima_manutencao);

      return {
        id: m.id,
        customer_name: cliente?.name || 'Cliente não identificado',
        phone: cliente?.mobile_phone || null,
        equipamentos: formatEquipamentos(m.equipamentos),
        endereco_instalacao: m.endereco_instalacao,
        proxima_manutencao: m.proxima_manutencao,
        maintenance_status: m.maintenance_status || 'pending',
        maintenance_type: m.maintenance_type || 'preventiva',
        atrasado: diasAtraso > 0,
        dias_atraso: diasAtraso,
        // Timeline fields
        notificacao_enviada_at: m.notificacao_enviada_at,
        cliente_respondeu_at: m.cliente_respondeu_at,
        transferido_at: m.transferido_at,
        agendamento_confirmado_at: m.agendamento_confirmado_at,
        // Extra info
        problema_relatado: m.problema_relatado,
        observacoes: m.observacoes,
      };
    });

    // Calcular contagens detalhadas
    const notificados = contratos.filter(c => c.maintenance_status === 'notified').length;
    const transferidos = contratos.filter(c => c.maintenance_status === 'transferred').length;
    const agendados = contratos.filter(c => c.maintenance_status === 'scheduled').length;
    const corretivas = contratos.filter(c => c.maintenance_type === 'corretiva').length;

    // Ordenar: atrasados primeiro (maior atraso primeiro), depois por data
    contratos.sort((a, b) => {
      if (a.atrasado && !b.atrasado) return -1;
      if (!a.atrasado && b.atrasado) return 1;
      if (a.atrasado && b.atrasado) return b.dias_atraso - a.dias_atraso;
      return new Date(a.proxima_manutencao).getTime() - new Date(b.proxima_manutencao).getTime();
    });

    // Formatar lista de feitas
    const contratosFeitos = (feitasData || []).map((m: any) => {
      const cliente = m.customer_id ? clientesMap[m.customer_id] : null;
      return {
        id: m.id,
        customer_name: cliente?.name || 'Cliente não identificado',
        phone: cliente?.mobile_phone || null,
        equipamentos: formatEquipamentos(m.equipamentos),
        endereco_instalacao: m.endereco_instalacao,
        manutencao_vencimento_original: m.manutencao_vencimento_original,
        manutencao_concluida_at: m.manutencao_concluida_at,
        manutencao_concluida_por: m.manutencao_concluida_por || 'sistema',
      };
    });

    const response: ManutencoesDashboardResponse = {
      resumo: {
        a_fazer: contratos.length,
        feitas: feitasData?.length || 0,
        // Detailed counts
        notificados,
        transferidos,
        agendados,
        corretivas,
      },
      contratos,
      contratos_feitos: contratosFeitos,
    };

    return reply.send({
      success: true,
      data: response,
    });
  } catch (error) {
    console.error('[ManutencoesDashboard] Error:', error);
    return reply.status(500).send({
      success: false,
      error: 'Internal server error',
      statusCode: 500,
    });
  }
}

// ============================================================================
// POST CONCLUIR MANUTENCAO (botão "Feito" - recicla para próximo ciclo)
// ============================================================================

export async function concluirManutencaoHandler(
  request: FastifyRequest<{ Params: { id: string } }>,
  reply: FastifyReply
) {
  try {
    const { id } = request.params;
    const user_id = (request as any).user?.id;

    if (!user_id) {
      return reply.status(401).send({
        success: false,
        error: 'Authentication required',
        statusCode: 401,
      });
    }

    // Buscar contrato para verificar ownership E pegar histórico existente
    const { data: contract, error: contractError } = await supabaseAdmin
      .from('contract_details')
      .select('id, agent_id, proxima_manutencao, manutencoes_realizadas')
      .eq('id', id)
      .single();

    if (contractError || !contract) {
      console.error('[ConcluirManutencao] Contract not found:', contractError);
      return reply.status(404).send({
        success: false,
        error: 'Maintenance record not found',
        statusCode: 404,
      });
    }

    // Verificar se o agente pertence ao usuario
    const { data: agent, error: agentError } = await supabaseAdmin
      .from('agents')
      .select('id')
      .eq('id', contract.agent_id)
      .eq('user_id', user_id)
      .single();

    if (agentError || !agent) {
      return reply.status(403).send({
        success: false,
        error: 'Access denied',
        statusCode: 403,
      });
    }

    // RECICLAR MANUTENÇÃO (não remover da fila)
    // 1. Salvar registro atual no histórico (manutencoes_realizadas)
    // 2. Definir nova proxima_manutencao = hoje + 6 meses
    // 3. Resetar status para 'pending'
    const now = new Date();
    const nowIso = now.toISOString();

    // Preparar novo registro de manutenção realizada
    const novaManutencaoRealizada = {
      vencimento: contract.proxima_manutencao,
      concluida_em: nowIso,
      concluida_por: 'dashboard',
    };

    // Append ao histórico existente (ou criar array novo)
    const historicoExistente = Array.isArray(contract.manutencoes_realizadas)
      ? contract.manutencoes_realizadas
      : [];
    const novoHistorico = [...historicoExistente, novaManutencaoRealizada];

    // Calcular próxima manutenção: hoje + 6 meses
    const proximaManutencao = new Date(now);
    proximaManutencao.setMonth(proximaManutencao.getMonth() + 6);
    const proximaManutencaoStr = proximaManutencao.toISOString().split('T')[0];

    const updateData = {
      // Salvar histórico
      manutencoes_realizadas: novoHistorico,
      // Reciclar para próximo ciclo
      proxima_manutencao: proximaManutencaoStr,
      maintenance_status: 'pending',
      // Limpar timestamps de notificação (novo ciclo)
      notificacao_enviada_at: null,
      cliente_respondeu_at: null,
      transferido_at: null,
      agendamento_confirmado_at: null,
      // Metadata
      manutencao_concluida_at: nowIso,
      manutencao_concluida_por: 'dashboard',
      updated_at: nowIso,
    };

    const { data: updatedContract, error: updateError } = await supabaseAdmin
      .from('contract_details')
      .update(updateData)
      .eq('id', id)
      .select()
      .single();

    if (updateError) {
      console.error('[ConcluirManutencao] Error updating:', updateError);
      return reply.status(500).send({
        success: false,
        error: 'Error completing maintenance',
        statusCode: 500,
      });
    }

    console.info(
      `[ConcluirManutencao] Maintenance ${id} completed and recycled. ` +
      `Vencimento original: ${contract.proxima_manutencao} -> Próxima: ${proximaManutencaoStr}. ` +
      `Histórico agora tem ${novoHistorico.length} registro(s).`
    );

    return reply.send({
      success: true,
      data: updatedContract,
    });
  } catch (error) {
    console.error('[ConcluirManutencao] Error:', error);
    return reply.status(500).send({
      success: false,
      error: 'Internal server error',
      statusCode: 500,
    });
  }
}
