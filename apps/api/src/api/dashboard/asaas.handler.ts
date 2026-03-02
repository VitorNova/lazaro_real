import { FastifyRequest, FastifyReply } from 'fastify';
import { supabaseAdmin } from '../../services/supabase/client';
import { AsaasClient } from '../../services/asaas/client';
import { GoogleGenerativeAI } from '@google/generative-ai';

/**
 * GET /api/dashboard/asaas
 *
 * Returns cached Asaas financial data for the Lazaro dashboard.
 * Data is synced from Asaas API to Supabase every 15 minutes by sync-asaas.js cron job.
 */
export async function getAsaasDashboardHandler(
  request: FastifyRequest,
  reply: FastifyReply
) {
  try {
    const user_id = (request as any).user?.id;
    if (!user_id) {
      return reply.status(400).send({ status: 'error', message: 'Authentication required' });
    }

    // Get agentId from query params or find the user's agent with Asaas
    const queryAgentId = (request.query as any)?.agentId;

    let agentId: string;

    let asaasApiKey: string | null = null;

    if (queryAgentId) {
      // Verify the agent belongs to this user and has Asaas configured
      const { data: agent } = await supabaseAdmin
        .from('agents')
        .select('id, asaas_api_key')
        .eq('id', queryAgentId)
        .eq('user_id', user_id)
        .not('asaas_api_key', 'is', null)
        .single();

      if (!agent) {
        return reply.status(404).send({ status: 'error', message: 'Agent not found or no Asaas integration' });
      }
      agentId = agent.id;
      asaasApiKey = agent.asaas_api_key;
    } else {
      // Find the first agent with Asaas for this user
      const { data: agents } = await supabaseAdmin
        .from('agents')
        .select('id, asaas_api_key')
        .eq('user_id', user_id)
        .not('asaas_api_key', 'is', null)
        .limit(1);

      if (!agents || agents.length === 0) {
        return reply.status(404).send({ status: 'error', message: 'No Asaas integration found' });
      }
      agentId = agents[0].id;
      asaasApiKey = agents[0].asaas_api_key;
    }

    // Get agent's table_leads for transfer count
    const { data: agentData } = await supabaseAdmin
      .from('agents')
      .select('table_leads')
      .eq('id', agentId)
      .single();

    // Data filter: only customers created from January 2026 onwards (by dateCreated from Asaas API)
    const DATA_FILTRO_CLIENTES = '2026-01-01';

    // Clientes excluídos do dashboard (não devem aparecer)
    const CLIENTES_EXCLUIDOS = [
      'zedequias rodrigues felício',
      'josé ricardo da rosa dias',
    ];

    // Fetch all customers from Asaas API and filter by dateCreated
    const asaasClient = new AsaasClient({ apiKey: asaasApiKey! });

    let customerIdsFevereiro: Set<string>;
    let customerIdsArray: string[];

    try {
      // Try to fetch from Asaas API
      const allAsaasCustomers = [];
      let customerOffset = 0;
      const customerLimit = 100;

      while (true) {
        const response = await asaasClient.listCustomers({ offset: customerOffset, limit: customerLimit });
        allAsaasCustomers.push(...response.data);

        if (!response.hasMore || response.data.length < customerLimit) {
          break;
        }
        customerOffset += customerLimit;

        // Safety limit
        if (allAsaasCustomers.length >= 1000) {
          console.warn('[AsaasDashboard] Reached 1000 customer limit');
          break;
        }
      }

      // Filter customers by dateCreated >= February 2026 and exclude specific clients
      const customersFevereiro = allAsaasCustomers.filter(c =>
        c.dateCreated &&
        c.dateCreated >= DATA_FILTRO_CLIENTES &&
        !CLIENTES_EXCLUIDOS.includes((c.name || '').toLowerCase().trim())
      );

      customerIdsFevereiro = new Set(customersFevereiro.map(c => c.id).filter(Boolean));
      customerIdsArray = Array.from(customerIdsFevereiro);

    } catch (error) {
      // FALLBACK: Asaas API unavailable (IP blocked or other error), use local cache
      console.warn('[AsaasDashboard] Asaas API unavailable, using local cache from Supabase', error instanceof Error ? error.message : error);

      // Try to get customers from asaas_clientes cache first
      const { data: clientesCache } = await supabaseAdmin
        .from('asaas_clientes')
        .select('id, name')
        .eq('agent_id', agentId)
        .gte('date_created', DATA_FILTRO_CLIENTES)
        .not('name', 'ilike', `%${CLIENTES_EXCLUIDOS[0]}%`)
        .not('name', 'ilike', `%${CLIENTES_EXCLUIDOS[1]}%`);

      if (clientesCache && clientesCache.length > 0) {
        customerIdsFevereiro = new Set(clientesCache.map(c => c.id).filter(Boolean));
        customerIdsArray = Array.from(customerIdsFevereiro);
        console.log(`[AsaasDashboard] Fallback: Using ${customerIdsArray.length} customers from asaas_clientes cache`);
      } else {
        // Secondary fallback: use customer_ids from contracts
        const { data: contratosCache } = await supabaseAdmin
          .from('asaas_contratos')
          .select('customer_id')
          .eq('agent_id', agentId)
          .gte('created_at', DATA_FILTRO_CLIENTES);

        customerIdsFevereiro = new Set(
          (contratosCache || []).map(c => c.customer_id).filter(Boolean)
        );
        customerIdsArray = Array.from(customerIdsFevereiro);
        console.log(`[AsaasDashboard] Fallback: Using ${customerIdsArray.length} customers from asaas_contratos`);
      }
    }

    // Fetch metadata and contracts for these customers
    const [metaRes, contratosRes] = await Promise.all([
      supabaseAdmin.from('asaas_cache_meta').select('*').eq('agent_id', agentId).single(),
      customerIdsArray.length > 0
        ? supabaseAdmin.from('asaas_contratos').select('*').eq('agent_id', agentId).in('customer_id', customerIdsArray).order('created_at', { ascending: false })
        : Promise.resolve({ data: [], error: null }),
    ]);

    const contratosFiltrados = contratosRes.data || [];

    // Now fetch other data filtered by these customer_ids AND due_date >= Feb/2026
    const [cobrancasRes, contractDetailsRes, cobrancasEnviadasRes] = await Promise.all([
      customerIdsArray.length > 0
        ? supabaseAdmin.from('asaas_cobrancas').select('*').eq('agent_id', agentId).in('customer_id', customerIdsArray).gte('due_date', DATA_FILTRO_CLIENTES).order('due_date', { ascending: false })
        : Promise.resolve({ data: [], error: null }),
      customerIdsArray.length > 0
        ? supabaseAdmin.from('contract_details').select('*').eq('agent_id', agentId).in('customer_id', customerIdsArray)
        : Promise.resolve({ data: [], error: null }),
      // billing_notifications: buscar todas as notificações enviadas pelo agente
      // Usa sent_at em vez de due_date pois due_date pode ser NULL em registros antigos
      supabaseAdmin.from('billing_notifications').select('*').eq('agent_id', agentId).eq('status', 'sent').gte('sent_at', DATA_FILTRO_CLIENTES).order('sent_at', { ascending: false }).limit(100),
    ]);

    // Count leads transferred to Leadbox (transfer_reason IS NOT NULL)
    let transferidosLeadbox = 0;
    if (agentData?.table_leads) {
      const { count } = await supabaseAdmin
        .from(agentData.table_leads)
        .select('*', { count: 'exact', head: true })
        .not('transfer_reason', 'is', null);
      transferidosLeadbox = count || 0;
    }

    if (metaRes.error) {
      return reply.status(500).send({
        status: 'error',
        message: 'Cache not available. Run sync job first.',
      });
    }

    const meta = metaRes.data;

    // Build contract_details lookup by subscription_id
    const detailsMap = new Map<string, any>();
    if (contractDetailsRes.data) {
      for (const cd of contractDetailsRes.data) {
        detailsMap.set(cd.subscription_id, cd);
      }
    }

    // Compute real total ARs from contract_details
    let realTotalARs = 0;
    if (contractDetailsRes.data && contractDetailsRes.data.length > 0) {
      realTotalARs = contractDetailsRes.data.reduce(
        (sum: number, cd: any) => sum + (cd.qtd_ars || 0), 0
      );
    }

    // Map contratos with contract_details (usando lista filtrada)
    const contratos = contratosFiltrados.map((sub: any) => {
      const details = detailsMap.get(sub.id);
      return {
        id: sub.id,
        customerId: sub.customer_id,
        customerName: sub.customer_name,
        value: sub.value,
        status: sub.status,
        cycle: sub.cycle,
        nextDueDate: sub.next_due_date,
        description: sub.description,
        billingType: sub.billing_type,
        ars: typeof sub.ars === 'string' ? JSON.parse(sub.ars) : (sub.ars || []),
        qtdARs: details?.qtd_ars ?? sub.qtd_ars ?? 0,
        // Dados do PDF
        contractDetails: details ? {
          numeroContrato: details.numero_contrato,
          equipamentos: details.equipamentos || [],
          enderecoInstalacao: details.endereco_instalacao,
          dataInicio: details.data_inicio,
          dataTermino: details.data_termino,
          prazoMeses: details.prazo_meses,
          proximaManutencao: details.proxima_manutencao,
          fiadorNome: details.fiador_nome,
          valorComercialTotal: details.valor_comercial_total,
          parsedAt: details.parsed_at,
        } : null,
      };
    });

    // Map cobrancas
    const cobrancas = (cobrancasRes.data || []).map((p: any) => ({
      id: p.id,
      customerId: p.customer_id,
      customerName: p.customer_name,
      value: p.value,
      netValue: p.net_value,
      status: p.status,
      billingType: p.billing_type,
      dueDate: p.due_date,
      paymentDate: p.payment_date,
      dateCreated: p.date_created,
      description: p.description,
      invoiceUrl: p.invoice_url,
      bankSlipUrl: p.bank_slip_url,
      subscriptionId: p.subscription_id,
      diasAtraso: p.dias_atraso || 0,
      iaCobrou: p.ia_cobrou || false,
      iaCobrouAt: p.ia_cobrou_at,
      iaRecebeu: p.ia_recebeu || false,
      iaRecebeuAt: p.ia_recebeu_at,
      iaRecebeuStep: p.ia_recebeu_step,
      iaRecebeuDaysFromDue: p.ia_recebeu_days_from_due,
      // Progresso da régua
      iaTotalNotificacoes: p.ia_total_notificacoes || 0,
      iaUltimoStep: p.ia_ultimo_step,
      iaUltimoDaysFromDue: p.ia_ultimo_days_from_due,
      iaUltimaNotificacaoAt: p.ia_ultima_notificacao_at,
    }));

    // Compute alerts from real data
    const hoje = new Date();
    hoje.setHours(0, 0, 0, 0);

    // DUNNING_REQUESTED = cobrança protestada/em cobrança judicial (também é atraso)
    const atrasados5 = cobrancas.filter(
      (c: any) => (c.status === 'OVERDUE' || c.status === 'DUNNING_REQUESTED') && c.diasAtraso >= 5
    );
    const atrasados30 = cobrancas.filter(
      (c: any) => (c.status === 'OVERDUE' || c.status === 'DUNNING_REQUESTED') && c.diasAtraso >= 30
    );

    const amanha = new Date(hoje);
    amanha.setDate(amanha.getDate() + 1);
    const amanhaStr = amanha.toISOString().split('T')[0];
    const vencemAmanha = cobrancas.filter(
      (c: any) => c.status === 'PENDING' && c.dueDate === amanhaStr
    );

    const alerts = [];
    if (atrasados30.length > 0) {
      alerts.push({
        type: 'critical',
        text: `${atrasados30.length} cliente${atrasados30.length > 1 ? 's' : ''} com 30+ dias de atraso`,
        action: 'clientes-atraso',
      });
    }
    if (atrasados5.length > 0) {
      alerts.push({
        type: 'urgent',
        text: `${atrasados5.length} cliente${atrasados5.length > 1 ? 's' : ''} com 5+ dias de atraso`,
        action: 'clientes-atraso',
      });
    }
    if (vencemAmanha.length > 0) {
      alerts.push({
        type: 'warning',
        text: `${vencemAmanha.length} cobranca${vencemAmanha.length > 1 ? 's' : ''} vence${vencemAmanha.length > 1 ? 'm' : ''} amanha`,
        action: 'cobrancas',
      });
    }

    // ========== VALORES A RECEBER DO MÊS ATUAL ==========
    const agora = new Date();
    const mesAtual = agora.getMonth(); // 0-11
    const anoAtual = agora.getFullYear();

    // Primeiro e último dia do mês atual
    const primeiroDiaMes = new Date(anoAtual, mesAtual, 1);
    const ultimoDiaMes = new Date(anoAtual, mesAtual + 1, 0);
    const primeiroDiaMesStr = primeiroDiaMes.toISOString().split('T')[0];
    const ultimoDiaMesStr = ultimoDiaMes.toISOString().split('T')[0];

    // Nome do mês em português
    const nomesMeses = [
      'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
      'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'
    ];
    const mesAtualNome = `${nomesMeses[mesAtual]} ${anoAtual}`;

    // Cobranças pendentes do mês atual
    const cobrancasMesAtual = cobrancas.filter((c: any) =>
      c.status === 'PENDING' &&
      c.dueDate >= primeiroDiaMesStr &&
      c.dueDate <= ultimoDiaMesStr
    );
    const valorReceberMesAtual = cobrancasMesAtual.reduce(
      (sum: number, c: any) => sum + parseFloat(c.value || 0), 0
    );

    // Total de cobranças atrasadas (OVERDUE + DUNNING_REQUESTED)
    const cobrancasAtrasadas = cobrancas.filter((c: any) =>
      c.status === 'OVERDUE' || c.status === 'DUNNING_REQUESTED'
    );
    const valorAtrasadoTotal = cobrancasAtrasadas.reduce(
      (sum: number, c: any) => sum + parseFloat(c.value || 0), 0
    );
    const qtdCobrancasAtrasadas = cobrancasAtrasadas.length;

    // ========== RELATÓRIO DE EQUIPAMENTOS POR BTUs ==========
    interface EquipamentoDetalhe {
      patrimonio: string;
      marca: string;
      modelo: string | null;
      btus: number;
      valorComercial: number;
      cliente: string;
      endereco: string | null;
    }
    const equipamentosPorBTUs: Record<number, { quantidade: number; valorComercialTotal: number; equipamentos: EquipamentoDetalhe[] }> = {};
    let totalEquipamentos = 0;
    let valorComercialTotalGeral = 0;

    // Lista flat de TODOS os equipamentos (para o modal) - fonte única de verdade
    const allEquipamentos: EquipamentoDetalhe[] = [];

    if (contractDetailsRes.data) {
      for (const cd of contractDetailsRes.data) {
        const equipamentos = cd.equipamentos || [];
        for (const eq of equipamentos) {
          const btus = eq.btus || 0;
          const valorComercial = eq.valor_comercial || 0;
          const equipamentoDetalhe: EquipamentoDetalhe = {
            patrimonio: eq.patrimonio || 'N/I',
            marca: eq.marca || 'N/I',
            modelo: eq.modelo || null,
            btus: btus,
            valorComercial: valorComercial,
            cliente: cd.locatario_nome || 'N/I',
            endereco: cd.endereco_instalacao || null,
          };

          // Adicionar à lista flat (todos os equipamentos)
          allEquipamentos.push(equipamentoDetalhe);
          totalEquipamentos += 1;
          valorComercialTotalGeral += valorComercial;

          // Também agrupar por BTUs para o relatório (só se btus > 0)
          if (btus > 0) {
            if (!equipamentosPorBTUs[btus]) {
              equipamentosPorBTUs[btus] = { quantidade: 0, valorComercialTotal: 0, equipamentos: [] };
            }
            equipamentosPorBTUs[btus].quantidade += 1;
            equipamentosPorBTUs[btus].valorComercialTotal += valorComercial;
            equipamentosPorBTUs[btus].equipamentos.push(equipamentoDetalhe);
          }
        }
      }
    }

    // Converter para array ordenado por quantidade (maior primeiro)
    const relatorioBTUs = Object.entries(equipamentosPorBTUs)
      .map(([btus, data]) => ({
        btus: parseInt(btus),
        quantidade: data.quantidade,
        valorComercialTotal: data.valorComercialTotal,
        percentual: totalEquipamentos > 0
          ? Math.round((data.quantidade / totalEquipamentos) * 100 * 10) / 10
          : 0,
        equipamentos: data.equipamentos,
      }))
      .sort((a, b) => b.quantidade - a.quantidade);

    // Totais gerais de equipamentos
    const equipamentosTotais = {
      quantidade: totalEquipamentos,
      valorComercialTotal: valorComercialTotalGeral,
    };

    // Map cobrancas enviadas pela IA (agora de billing_notifications)
    const cobrancasEnviadas = (cobrancasEnviadasRes.data || []).map((ce: any) => ({
      id: ce.id,
      paymentId: ce.payment_id,
      customerId: ce.customer_id,
      customerName: ce.customer_name,
      customerPhone: ce.phone, // billing_notifications usa 'phone'
      valor: ce.valor,
      dueDate: ce.due_date,
      billingType: ce.billing_type,
      subscriptionId: ce.subscription_id,
      messageText: ce.message_text,
      paymentLink: null, // billing_notifications não tem payment_link
      notificationType: ce.notification_type,
      daysFromDue: ce.days_from_due,
      canal: 'whatsapp', // billing_notifications não tem canal, assume whatsapp
      status: ce.status,
      enviadoEm: ce.sent_at, // billing_notifications usa 'sent_at'
    }));

    // ========== CLIENTES DE FEVEREIRO EM DIANTE ==========
    // Contagem de clientes cadastrados no Asaas a partir de fevereiro/2026 (por dateCreated)
    const clientesFevereiro = customerIdsArray.length;

    // ========== RECALCULAR TODOS OS VALORES DOS DADOS FILTRADOS ==========
    // Cobranças pagas (RECEIVED, CONFIRMED, RECEIVED_IN_CASH)
    const cobrancasPagas = cobrancas.filter((c: any) =>
      c.status === 'RECEIVED' || c.status === 'CONFIRMED' || c.status === 'RECEIVED_IN_CASH'
    );
    const faturamentoCalculado = cobrancasPagas.reduce(
      (sum: number, c: any) => sum + parseFloat(c.value || 0), 0
    );
    const faturamentoLiquidoCalculado = cobrancasPagas.reduce(
      (sum: number, c: any) => sum + parseFloat(c.netValue || c.value || 0), 0
    );

    // Cobranças pendentes
    const cobrancasPendentes = cobrancas.filter((c: any) => c.status === 'PENDING');
    const pendentesCalculado = cobrancasPendentes.length;
    const valorPendenteCalculado = cobrancasPendentes.reduce(
      (sum: number, c: any) => sum + parseFloat(c.value || 0), 0
    );

    // Quebras de contrato: clientes unicos com parcelamento (nova regra de negocio)
    // Filtrar apenas parcelamentos criados a partir de marco de 2026
    const { data: parcelamentos } = await supabaseAdmin
      .from('asaas_parcelamentos')
      .select('customer_id')
      .eq('agent_id', agentId)
      .eq('deleted', false)
      .gte('date_created', '2026-03-01');

    // Contar clientes unicos com parcelamento
    const clientesComParcelamento = new Set(
      (parcelamentos || []).map((p: any) => p.customer_id)
    ).size;
    const quebrasContratoCalculado = clientesComParcelamento;

    // ========== CLIENTES SEM CONTRATO ==========
    // Clientes do Asaas (de fevereiro+) que nao tem contract_details associado
    const customerIdsComContrato = new Set(
      (contractDetailsRes.data || []).map((cd: any) => cd.customer_id).filter(Boolean)
    );
    const clientesSemContrato = customerIdsArray.filter(
      (id: string) => !customerIdsComContrato.has(id)
    );

    // Buscar detalhes dos clientes sem contrato (nome, email, cpf)
    let clientesSemContratoDetalhes: Array<{ id: string; name: string; email: string | null; cpf_cnpj: string | null }> = [];
    if (clientesSemContrato.length > 0) {
      const { data: clientesDetalhes } = await supabaseAdmin
        .from('asaas_clientes')
        .select('id, name, email, cpf_cnpj')
        .eq('agent_id', agentId)
        .in('id', clientesSemContrato)
        .eq('deleted_from_asaas', false)
        .order('name', { ascending: true });
      clientesSemContratoDetalhes = clientesDetalhes || [];
    }

    // ========== MÉTRICAS DE IA ==========
    // Calcular métricas de cobrança por IA
    const iaCobradas = cobrancas.filter((c: any) => c.iaCobrou === true);
    const iaRecebidas = cobrancas.filter((c: any) => c.iaRecebeu === true);

    // Valor total cobrado pela IA
    const valorIaCobrou = iaCobradas.reduce((sum: number, c: any) => sum + (c.value || 0), 0);
    // Valor total recebido após IA cobrar
    const valorIaRecebeu = iaRecebidas.reduce((sum: number, c: any) => sum + (c.value || 0), 0);

    // Média de mensagens por cobrança
    const totalMensagens = iaCobradas.reduce((sum: number, c: any) => sum + (c.iaTotalNotificacoes || 0), 0);
    const mediaMensagens = iaCobradas.length > 0 ? Number((totalMensagens / iaCobradas.length).toFixed(1)) : 0;

    // Métricas por mês
    const porMes: Record<string, any> = {};
    iaCobradas.forEach((c: any) => {
      const mes = c.dueDate ? c.dueDate.substring(0, 7) : 'sem-data'; // "2026-02"
      if (!porMes[mes]) {
        porMes[mes] = { cobrados: 0, recebidos: 0, valorCobrado: 0, valorRecebido: 0 };
      }
      porMes[mes].cobrados++;
      porMes[mes].valorCobrado += c.value || 0;
      if (c.iaRecebeu) {
        porMes[mes].recebidos++;
        porMes[mes].valorRecebido += c.value || 0;
      }
    });
    // Adicionar taxa por mês
    Object.keys(porMes).forEach(mes => {
      const m = porMes[mes];
      m.taxa = m.cobrados > 0 ? Number((m.recebidos / m.cobrados * 100).toFixed(1)) : 0;
    });

    // Ranking de leads (agrupar cobranças por customer_name)
    const leadMap: Record<string, any> = {};
    iaCobradas.forEach((c: any) => {
      const nome = c.customerName || 'Desconhecido';
      if (!leadMap[nome]) {
        leadMap[nome] = {
          nome,
          totalCobrancas: 0,
          totalPago: 0,
          valorCobrado: 0,
          valorPago: 0,
          totalMensagens: 0,
          ultimoStep: null,
        };
      }
      const lead = leadMap[nome];
      lead.totalCobrancas++;
      lead.valorCobrado += c.value || 0;
      lead.totalMensagens += c.iaTotalNotificacoes || 0;
      lead.ultimoStep = c.iaUltimoStep;
      if (c.iaRecebeu) {
        lead.totalPago++;
        lead.valorPago += c.value || 0;
      }
    });
    const porLead = Object.values(leadMap).map((lead: any) => ({
      ...lead,
      taxa: lead.totalCobrancas > 0 ? Number((lead.totalPago / lead.totalCobrancas * 100).toFixed(1)) : 0,
      mediaMsg: lead.totalCobrancas > 0 ? Number((lead.totalMensagens / lead.totalCobrancas).toFixed(1)) : 0,
    })).sort((a: any, b: any) => b.valorCobrado - a.valorCobrado);

    // Eficiência por step da régua (onde os clientes pagam)
    const porStep: Record<string, { count: number; valor: number }> = {};
    iaRecebidas.forEach((c: any) => {
      const days = c.iaRecebeuDaysFromDue || 0;
      const stepLabel = days === 0 ? 'No dia (D0)' :
        days > 0 ? `D-${days} (lembrete)` :
        `D+${Math.abs(days)}`;
      if (!porStep[stepLabel]) {
        porStep[stepLabel] = { count: 0, valor: 0 };
      }
      porStep[stepLabel].count++;
      porStep[stepLabel].valor += c.value || 0;
    });

    const iaMetrics = {
      totalCobrados: iaCobradas.length,
      totalRecebidos: iaRecebidas.length,
      valorCobrou: valorIaCobrou,
      valorRecebeu: valorIaRecebeu,
      taxaGeral: iaCobradas.length > 0 ? Number((iaRecebidas.length / iaCobradas.length * 100).toFixed(1)) : 0,
      mediaMensagens,
      porMes,
      porLead,
      porStep,
    };

    return reply.send({
      status: 'success',
      data: {
        cards: {
          contratosAtivos: contratos.filter((c: any) => c.status === 'ACTIVE').length,
          clientesFevereiro, // Clientes cadastrados no Asaas a partir de fevereiro/2026 (por dateCreated)
          clientesSemContrato: clientesSemContrato.length, // Clientes do Asaas sem contract_details
          totalARs: totalEquipamentos, // Usando totalEquipamentos para consistência com allEquipamentos
          faturamento: faturamentoCalculado,
          faturamentoLiquido: faturamentoLiquidoCalculado,
          atrasosMensais: qtdCobrancasAtrasadas,
          valorAtrasado: valorAtrasadoTotal,
          quebrasContrato: quebrasContratoCalculado,
          saldoConta: meta.saldo_conta, // Este vem da conta Asaas, não é filtrado
          pendentes: pendentesCalculado,
          valorPendente: valorPendenteCalculado,
          transferidosLeadbox: transferidosLeadbox,
          ultimaSync: meta.ultima_sync,
          // Novos campos - Valores a Receber
          mesAtualNome,
          valorReceberMesAtual,
          valorAtrasadoTotal,
          qtdCobrancasAtrasadas,
          qtdCobrancasMesAtual: cobrancasMesAtual.length,
        },
        contratos,
        cobrancas,
        cobrancasEnviadas,
        alerts,
        // Novo - Relatório de Equipamentos por BTUs
        relatorioBTUs,
        equipamentosTotais,
        // Lista flat de TODOS os equipamentos (fonte única de verdade para o modal)
        allEquipamentos,
        // Clientes do Asaas sem contrato cadastrado
        clientesSemContratoDetalhes,
        // Métricas de cobrança por IA
        iaMetrics,
      },
    });
  } catch (error) {
    console.error('[AsaasDashboard] Error:', error);
    return reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

/**
 * POST /api/dashboard/asaas/parse-contract/:subscriptionId
 *
 * Downloads PDF from Asaas payment documents, extracts text,
 * sends to Gemini for structured data extraction, saves to contract_details.
 */
export async function parseContractHandler(
  request: FastifyRequest,
  reply: FastifyReply
) {
  try {
    const user_id = (request as any).user?.id;
    if (!user_id) {
      return reply.status(400).send({ status: 'error', message: 'Authentication required' });
    }

    const { subscriptionId } = request.params as { subscriptionId: string };
    if (!subscriptionId) {
      return reply.status(400).send({ status: 'error', message: 'subscriptionId required' });
    }

    // Find the subscription in cache and get the agent's API key
    const { data: contrato } = await supabaseAdmin
      .from('asaas_contratos')
      .select('id, agent_id, customer_id, customer_name')
      .eq('id', subscriptionId)
      .single();

    if (!contrato) {
      return reply.status(404).send({ status: 'error', message: 'Subscription not found' });
    }

    // Verify user owns this agent
    const { data: agent } = await supabaseAdmin
      .from('agents')
      .select('id, asaas_api_key')
      .eq('id', contrato.agent_id)
      .eq('user_id', user_id)
      .not('asaas_api_key', 'is', null)
      .single();

    if (!agent) {
      return reply.status(403).send({ status: 'error', message: 'Unauthorized' });
    }

    const geminiApiKey = process.env.GEMINI_API_KEY;
    if (!geminiApiKey) {
      return reply.status(500).send({ status: 'error', message: 'GEMINI_API_KEY not configured' });
    }

    const asaasClient = new AsaasClient({ apiKey: agent.asaas_api_key });

    // Get payments for this subscription
    // Delay antes da chamada para evitar burst
    await new Promise(resolve => setTimeout(resolve, 200));
    const payments = await asaasClient.listAllPayments({ subscription: subscriptionId, limit: 50 });

    if (!payments || payments.length === 0) {
      return reply.status(404).send({ status: 'error', message: 'No payments found for this subscription' });
    }

    // Collect ALL PDFs from all payments
    const pdfParse = require('pdf-parse');

    interface PdfInfo {
      paymentId: string;
      docId: string;
      docName: string;
      docUrl: string;
    }
    const allPdfInfos: PdfInfo[] = [];
    const allContractData: any[] = [];

    for (const payment of payments) {
      // Delay de 200ms entre cada chamada à API Asaas para evitar rate limiting
      await new Promise(resolve => setTimeout(resolve, 200));
      const docs = await asaasClient.listPaymentDocuments(payment.id);
      const pdfDocs = docs.filter((d: any) => d.name?.toLowerCase().endsWith('.pdf'));

      for (const pdfDoc of pdfDocs) {
        const url = pdfDoc.file?.publicAccessUrl || pdfDoc.file?.downloadUrl;
        if (!url) continue;

        try {
          const buffer = await asaasClient.downloadDocument(url);
          const pdfData = await pdfParse(buffer);
          const pdfText = pdfData.text;

          if (!pdfText || pdfText.trim().length < 50) {
            console.warn(`[ParseContract] PDF ${pdfDoc.name} has no readable text, skipping`);
            continue;
          }

          const extracted = await extractWithGemini(pdfText, geminiApiKey);
          allContractData.push(extracted);
          allPdfInfos.push({
            paymentId: payment.id,
            docId: pdfDoc.id,
            docName: pdfDoc.name,
            docUrl: url,
          });
          console.log(`[ParseContract] Parsed PDF: ${pdfDoc.name} (${extracted.equipamentos?.length || 0} equipamentos)`);
        } catch (err) {
          console.warn(`[ParseContract] Failed to parse ${pdfDoc.name}:`, err);
        }
      }
    }

    if (allPdfInfos.length === 0) {
      return reply.send({
        status: 'success',
        message: 'No PDF documents found for this contract',
        data: null,
      });
    }

    // Merge data from all PDFs
    const contractData = mergeContractData(allContractData);

    // Use first PDF info for reference, store all doc IDs
    const foundPaymentId = allPdfInfos[0].paymentId;
    const foundDocId = allPdfInfos.map(p => p.docId).join(',');
    const foundDocName = allPdfInfos.map(p => p.docName).join(', ');
    const foundDocUrl = allPdfInfos[0].docUrl;

    // Compute derived fields
    const equipamentos = contractData.equipamentos || [];
    const qtdArs = equipamentos.length;
    const valorComercialTotal = equipamentos.reduce(
      (sum: number, eq: any) => sum + (eq.valor_comercial || 0), 0
    );

    console.log(`[ParseContract] Merged ${allPdfInfos.length} PDFs: ${qtdArs} equipamentos, R$ ${valorComercialTotal} valor comercial total`);

    let proximaManutencao: string | null = null;
    if (contractData.data_inicio) {
      const inicio = new Date(contractData.data_inicio);
      inicio.setMonth(inicio.getMonth() + 6);
      proximaManutencao = inicio.toISOString().split('T')[0];
    }

    // Upsert to contract_details
    const record = {
      agent_id: contrato.agent_id,
      subscription_id: subscriptionId,
      customer_id: contrato.customer_id,
      payment_id: foundPaymentId,
      document_id: foundDocId,
      numero_contrato: contractData.numero_contrato || null,
      locatario_nome: contractData.locatario_nome || contrato.customer_name,
      locatario_cpf_cnpj: contractData.locatario_cpf_cnpj || null,
      locatario_telefone: contractData.locatario_telefone || null,
      locatario_endereco: contractData.locatario_endereco || null,
      fiador_nome: contractData.fiador_nome || null,
      fiador_cpf: contractData.fiador_cpf || null,
      fiador_telefone: contractData.fiador_telefone || null,
      equipamentos,
      qtd_ars: qtdArs,
      valor_comercial_total: valorComercialTotal,
      endereco_instalacao: contractData.endereco_instalacao || null,
      prazo_meses: contractData.prazo_meses || null,
      data_inicio: contractData.data_inicio || null,
      data_termino: contractData.data_termino || null,
      dia_vencimento: contractData.dia_vencimento || null,
      valor_mensal: contractData.valor_mensal || null,
      proxima_manutencao: proximaManutencao,
      pdf_url: foundDocUrl,
      pdf_filename: foundDocName,
      parsed_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

    const { error } = await supabaseAdmin
      .from('contract_details')
      .upsert(record, { onConflict: 'subscription_id,agent_id' });

    if (error) {
      console.error('[ParseContract] Upsert error:', error);
      return reply.status(500).send({ status: 'error', message: 'Failed to save contract details' });
    }

    return reply.send({
      status: 'success',
      message: `Contract ${contractData.numero_contrato || subscriptionId} parsed successfully (${allPdfInfos.length} PDFs, ${qtdArs} equipamentos)`,
      data: record,
    });
  } catch (error) {
    console.error('[ParseContract] Error:', error);
    return reply.status(500).send({
      status: 'error',
      message: error instanceof Error ? error.message : 'Internal server error',
    });
  }
}

/**
 * POST /api/dashboard/asaas/parse-all-contracts
 *
 * Processes all contracts that haven't been parsed yet.
 * Downloads PDFs from Asaas, extracts data with Gemini, saves to contract_details.
 */
export async function parseAllContractsHandler(
  request: FastifyRequest,
  reply: FastifyReply
) {
  try {
    const user_id = (request as any).user?.id;
    if (!user_id) {
      return reply.status(400).send({ status: 'error', message: 'Authentication required' });
    }

    // Get agentId from query params or find the user's agent with Asaas
    const queryAgentId = (request.query as any)?.agentId;

    let agent: any;

    if (queryAgentId) {
      const { data } = await supabaseAdmin
        .from('agents')
        .select('id, asaas_api_key')
        .eq('id', queryAgentId)
        .eq('user_id', user_id)
        .not('asaas_api_key', 'is', null)
        .single();
      agent = data;
    } else {
      const { data: agents } = await supabaseAdmin
        .from('agents')
        .select('id, asaas_api_key')
        .eq('user_id', user_id)
        .not('asaas_api_key', 'is', null)
        .limit(1);
      agent = agents?.[0];
    }

    if (!agent) {
      return reply.status(404).send({ status: 'error', message: 'No Asaas integration found' });
    }

    const geminiApiKey = process.env.GEMINI_API_KEY;
    if (!geminiApiKey) {
      return reply.status(500).send({ status: 'error', message: 'GEMINI_API_KEY not configured' });
    }

    // Check if force re-parse is requested
    const forceReparse = (request.query as any)?.force === 'true';

    // Get all contracts that haven't been parsed yet
    const { data: allContracts } = await supabaseAdmin
      .from('asaas_contratos')
      .select('id, customer_id, customer_name')
      .eq('agent_id', agent.id)
      .eq('status', 'ACTIVE');

    const { data: parsedContracts } = await supabaseAdmin
      .from('contract_details')
      .select('subscription_id')
      .eq('agent_id', agent.id);

    const parsedIds = new Set(parsedContracts?.map(c => c.subscription_id) || []);

    // If force=true, process ALL contracts; otherwise only pending ones
    const pendingContracts = forceReparse
      ? (allContracts || [])
      : (allContracts?.filter(c => !parsedIds.has(c.id)) || []);

    console.log(`[ParseAllContracts] Found ${pendingContracts.length} contracts to parse (force=${forceReparse})`);

    if (pendingContracts.length === 0) {
      return reply.send({
        status: 'success',
        message: 'All contracts already parsed',
        data: { total: allContracts?.length || 0, parsed: parsedIds.size, pending: 0 },
      });
    }

    const asaasClient = new AsaasClient({ apiKey: agent.asaas_api_key });
    const pdfParse = require('pdf-parse');

    const results: { success: string[]; failed: string[]; skipped: string[] } = {
      success: [],
      failed: [],
      skipped: [],
    };

    const startTime = Date.now();
    let totalRequests = 0;

    // Process each contract
    for (const contrato of pendingContracts) {
      try {
        console.log(`[ParseAllContracts] Processing ${contrato.id} (${contrato.customer_name})`);

        // Get payments for this subscription
        // Delay antes da chamada para evitar burst
        await new Promise(resolve => setTimeout(resolve, 200));
        totalRequests++;
        const payments = await asaasClient.listAllPayments({ subscription: contrato.id, limit: 50 });

        if (!payments || payments.length === 0) {
          console.log(`[ParseAllContracts] No payments for ${contrato.id}, skipping`);
          results.skipped.push(`${contrato.id} (no payments)`);
          continue;
        }

        console.log(`[ParseAllContracts] Found ${payments.length} payments for ${contrato.id}`);

        // Collect PDFs from all payments
        interface PdfInfo {
          paymentId: string;
          docId: string;
          docName: string;
          docUrl: string;
        }
        const allPdfInfos: PdfInfo[] = [];
        const allContractData: any[] = [];

        for (const payment of payments) {
          // Delay de 200ms entre cada chamada à API Asaas para evitar rate limiting
          await new Promise(resolve => setTimeout(resolve, 200));
          totalRequests++;
          const docs = await asaasClient.listPaymentDocuments(payment.id);
          const pdfDocs = docs.filter((d: any) => d.name?.toLowerCase().endsWith('.pdf'));

          for (const pdfDoc of pdfDocs) {
            const url = pdfDoc.file?.publicAccessUrl || pdfDoc.file?.downloadUrl;
            if (!url) continue;

            try {
              const buffer = await asaasClient.downloadDocument(url);
              const pdfData = await pdfParse(buffer);
              const pdfText = pdfData.text;

              if (!pdfText || pdfText.trim().length < 50) {
                console.warn(`[ParseAllContracts] PDF ${pdfDoc.name} has no readable text, skipping`);
                continue;
              }

              const extracted = await extractWithGemini(pdfText, geminiApiKey);
              allContractData.push(extracted);
              allPdfInfos.push({
                paymentId: payment.id,
                docId: pdfDoc.id,
                docName: pdfDoc.name,
                docUrl: url,
              });

              // Rate limit: wait 500ms between Gemini calls
              await new Promise(resolve => setTimeout(resolve, 500));
            } catch (err) {
              console.warn(`[ParseAllContracts] Failed to parse ${pdfDoc.name}:`, err);
            }
          }
        }

        if (allPdfInfos.length === 0) {
          console.log(`[ParseAllContracts] No PDFs found for ${contrato.id}, skipping`);
          results.skipped.push(`${contrato.id} (no PDFs)`);
          continue;
        }

        // Merge data from all PDFs
        const contractData = mergeContractData(allContractData);

        const foundPaymentId = allPdfInfos[0].paymentId;
        const foundDocId = allPdfInfos.map(p => p.docId).join(',');
        const foundDocName = allPdfInfos.map(p => p.docName).join(', ');
        const foundDocUrl = allPdfInfos[0].docUrl;

        const equipamentos = contractData.equipamentos || [];
        const qtdArs = equipamentos.length;
        const valorComercialTotal = equipamentos.reduce(
          (sum: number, eq: any) => sum + (eq.valor_comercial || 0), 0
        );

        let proximaManutencao: string | null = null;
        if (contractData.data_inicio) {
          const inicio = new Date(contractData.data_inicio);
          inicio.setMonth(inicio.getMonth() + 6);
          proximaManutencao = inicio.toISOString().split('T')[0];
        }

        // Upsert to contract_details
        const record = {
          agent_id: agent.id,
          subscription_id: contrato.id,
          customer_id: contrato.customer_id,
          payment_id: foundPaymentId,
          document_id: foundDocId,
          numero_contrato: contractData.numero_contrato || null,
          locatario_nome: contractData.locatario_nome || contrato.customer_name,
          locatario_cpf_cnpj: contractData.locatario_cpf_cnpj || null,
          locatario_telefone: contractData.locatario_telefone || null,
          locatario_endereco: contractData.locatario_endereco || null,
          fiador_nome: contractData.fiador_nome || null,
          fiador_cpf: contractData.fiador_cpf || null,
          fiador_telefone: contractData.fiador_telefone || null,
          equipamentos,
          qtd_ars: qtdArs,
          valor_comercial_total: valorComercialTotal,
          endereco_instalacao: contractData.endereco_instalacao || null,
          prazo_meses: contractData.prazo_meses || null,
          data_inicio: contractData.data_inicio || null,
          data_termino: contractData.data_termino || null,
          dia_vencimento: contractData.dia_vencimento || null,
          valor_mensal: contractData.valor_mensal || null,
          proxima_manutencao: proximaManutencao,
          pdf_url: foundDocUrl,
          pdf_filename: foundDocName,
          parsed_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        };

        const { error } = await supabaseAdmin
          .from('contract_details')
          .upsert(record, { onConflict: 'subscription_id,agent_id' });

        if (error) {
          console.error(`[ParseAllContracts] Upsert error for ${contrato.id}:`, error);
          results.failed.push(`${contrato.id} (db error)`);
        } else {
          console.log(`[ParseAllContracts] ✓ Parsed ${contrato.id}: ${qtdArs} equipamentos`);
          results.success.push(`${contrato.id} (${qtdArs} equip.)`);
        }

        // Rate limit between contracts
        await new Promise(resolve => setTimeout(resolve, 1000));

      } catch (err) {
        console.error(`[ParseAllContracts] Error processing ${contrato.id}:`, err);
        results.failed.push(`${contrato.id} (${err instanceof Error ? err.message : 'error'})`);
      }
    }

    const elapsedTime = ((Date.now() - startTime) / 1000).toFixed(1);
    const avgTimePerContract = pendingContracts.length > 0
      ? (parseFloat(elapsedTime) / pendingContracts.length).toFixed(1)
      : '0';

    console.log(`[ParseAllContracts] Concluído em ${elapsedTime}s | ${totalRequests} requisições à API Asaas | Média: ${avgTimePerContract}s/contrato`);

    return reply.send({
      status: 'success',
      message: `Processed ${results.success.length} contracts`,
      data: {
        total: allContracts?.length || 0,
        alreadyParsed: parsedIds.size,
        processed: results.success.length,
        failed: results.failed.length,
        skipped: results.skipped.length,
        details: results,
        stats: {
          elapsedSeconds: parseFloat(elapsedTime),
          totalAsaasRequests: totalRequests,
          avgSecondsPerContract: parseFloat(avgTimePerContract),
        },
      },
    });

  } catch (error) {
    console.error('[ParseAllContracts] Error:', error);
    return reply.status(500).send({
      status: 'error',
      message: error instanceof Error ? error.message : 'Internal server error',
    });
  }
}

/**
 * Merges contract data extracted from multiple PDFs into a single record.
 * Scalar fields: takes first non-null value found.
 * Equipamentos: merges all arrays into one.
 */
function mergeContractData(dataList: any[]): any {
  if (dataList.length === 0) return {};
  if (dataList.length === 1) return dataList[0];

  const result: any = {};
  const scalarFields = [
    'numero_contrato', 'locatario_nome', 'locatario_cpf_cnpj',
    'locatario_telefone', 'locatario_endereco', 'fiador_nome',
    'fiador_cpf', 'fiador_telefone', 'endereco_instalacao',
    'prazo_meses', 'data_inicio', 'data_termino',
    'dia_vencimento', 'valor_mensal',
  ];

  for (const field of scalarFields) {
    for (const data of dataList) {
      if (data[field] != null) {
        result[field] = data[field];
        break;
      }
    }
  }

  // Merge all equipment arrays from all PDFs
  const allEquipamentos: any[] = [];
  for (const data of dataList) {
    if (data.equipamentos && Array.isArray(data.equipamentos)) {
      allEquipamentos.push(...data.equipamentos);
    }
  }
  result.equipamentos = allEquipamentos;

  return result;
}

/**
 * Sends extracted PDF text to Gemini and gets structured JSON back
 */
async function extractWithGemini(pdfText: string, apiKey: string): Promise<any> {
  const genAI = new GoogleGenerativeAI(apiKey);
  const model = genAI.getGenerativeModel({ model: 'gemini-2.0-flash' });

  const prompt = `Analise o texto de um contrato de locação de ar-condicionado da ALUGA AR e extraia os dados em JSON.

=== NUMERAÇÃO DE CONTRATOS ===

O número do contrato segue o formato "N-X" (ex: "131-2"), onde:
- N = número sequencial do CLIENTE (identifica o cliente de forma única)
- X = número do contrato ou aditivo daquele cliente

Exemplos:
- "Contrato 131-1" → Cliente nº 131, primeiro contrato
- "Contrato 131-2" → Cliente nº 131, segundo contrato (aditivo)
- "Contrato 45-3" → Cliente nº 45, terceiro contrato

O campo "numero_contrato" deve conter o número completo (ex: "131-2").
O campo "numero_cliente" deve conter apenas o número antes do hífen (ex: 131).
O campo "numero_aditivo" deve conter apenas o número depois do hífen (ex: 2).

Procure por padrões como:
- "CONTRATO DE LOCAÇÃO DE BEM MÓVEL Nº 131-2"
- "ADITIVO AO CONTRATO DE LOCAÇÃO DE BEM MÓVEL Nº 131-2"
- "contrato nº 131-2"
- "contrato nº 131 -2" (pode ter espaço antes do hífen)

=== REGRA DE CONTAGEM DE CLIENTES ===

- O número antes do hífen (N) identifica o cliente de forma ÚNICA
- Contratos 131-1, 131-2 e 131-3 = 1 CLIENTE (nº 131) com 3 contratos
- Para contar total de clientes, conte quantos números N diferentes existem
- Exemplo: contratos 45-1, 45-2, 131-1, 131-2, 200-1 = 3 clientes (45, 131, 200)

=== TIPO DE DOCUMENTO ===

Identifique se é:
- "contrato" → Contrato original (geralmente N-1)
- "aditivo" → Aditivo ao contrato (N-2, N-3, etc.) — pode ser substituição de equipamento, alteração de valor, renovação

Pistas para identificar ADITIVO:
- Título contém "ADITIVO"
- Menciona "substituição do equipamento"
- Referencia um contrato original anterior
- Menciona "Termo de Substituição e Vistoria"

=== TIPOS DE TABELA DE EQUIPAMENTOS ===

TIPO 1: Tabela com coluna "item" (descrição)
Colunas: codigo | item (descrição) | Valor Locacao | Valor Comercial
Exemplo: "000307  PATRIMONIO 0540 - AR CONDICIONADO VG 12.000 BTUS INVERTER   189,00   2.700,00"
- O código "000307" NÃO é o patrimônio
- Extraia "0540" do texto "PATRIMONIO 0540" na descrição
- BTUS: Extraia da descrição do item (ex: "12.000 BTUS" → 12000)
- Cada linha = 1 equipamento

TIPO 2: Tabela com coluna "MARCA" contendo patrimônios
Colunas: MARCA | MODELO | BTUS | VALOR COMERCIAL
Exemplo: "SPRINGER MIDEA, Patrimônios 0329/ 0330/ 0331/ 0332 0333/ 0334  |  CONVENCIONAL  |  9.000 CADA  |  R$2.500,00"
- A marca é "SPRINGER MIDEA"
- Os patrimônios estão após "Patrimônios" separados por "/" ou espaço: 0329, 0330, 0331, 0332, 0333, 0334
- BTUS: Extraia da coluna BTUS (ex: "9.000 CADA" → 9000)
- CADA patrimônio = 1 equipamento separado no JSON
- Se há 11 patrimônios, gere 11 objetos no array "equipamentos"

TIPO 3: Tabela de aditivo (substituição)
Colunas: ITEM | Valor Locação | Valor Comercial
Exemplo: "PATRIMONIO 0345-AR CONDICIONADO FONTAINE 9.000BTUS127VOLTS   R$ 149,00   2.500,00"
- Patrimônio: "0345"
- Marca: "FONTAINE"
- BTUs: 9000
- Voltagem: 127V
- Em aditivos, verifique também o equipamento ANTERIOR que está sendo substituído (ex: "PATRIMONIO 133-AR CONDICIONADO BRITANIA 12.000BTUS 220V")

=== REGRAS DE PATRIMÔNIO ===

- Patrimônio é sempre um código numérico de 3-4 dígitos (ex: "0540", "0329", "155", "0345")
- Se aparecer "PATRI", "Patrimônio", "Patrimônios" ou "PATRIMONIO", extraia os números que seguem
- Nunca use o "codigo" da primeira coluna como patrimônio
- Em aditivos, extraia TANTO o equipamento novo quanto o antigo (campo "equipamento_substituido")

=== EXTRAÇÃO DE DATAS ===

Procure por:
- "firmado em DD/MM/YYYY" → data_inicio
- "com término em DD/MM/YYYY" ou "com termo em DD/MM/YYYY" → data_termino
- "vigência de DD/MM/YYYY a DD/MM/YYYY"
- "prazo de XX meses a partir de DD/MM/YYYY"
- Data de assinatura no final do documento (ex: "Rondonópolis-MT, 06 de dezembro de 2025")

Em ADITIVOS, a frase típica é:
"conforme previsto no contrato nº 131-2, firmado em 14/10/2025, com termo em 14/10/2026"
→ data_inicio: "2025-10-14", data_termino: "2026-10-14"

Converta DD/MM/YYYY para YYYY-MM-DD:
- 14/10/2025 → "2025-10-14"
- 06/12/2025 → "2025-12-06"

=== EXTRAÇÃO DE DADOS DO LOCATÁRIO ===

- Nome completo
- CPF ou CNPJ (limpe formatação: "062.070.951.03" → "06207095103")
- Telefone (se disponível)
- Endereço completo (rua, número, bairro, cidade, CEP)
- Estado civil, profissão (se disponível)

=== EXTRAÇÃO DE FIADOR ===

Se houver fiador no contrato, extraia nome, CPF e telefone.

=== EXTRAÇÃO DE TESTEMUNHAS ===

Se houver testemunhas, extraia nomes e CPFs.

=== DADOS DA ASSINATURA DIGITAL ===

Se o documento tiver assinatura via Autentique ou similar, extraia:
- Plataforma (ex: "Autentique")
- Hash do documento
- Data/hora de cada assinatura
- IP de cada signatário

Texto do contrato:
---
${pdfText.substring(0, 8000)}
---

Retorne APENAS um JSON válido (sem markdown, sem \`\`\`) com esta estrutura:
{
  "tipo_documento": "contrato | aditivo",
  "numero_contrato": "131-2",
  "numero_cliente": 131,
  "numero_aditivo": 2,
  "locatario_nome": "string",
  "locatario_cpf_cnpj": "string ou null",
  "locatario_telefone": "string ou null",
  "locatario_endereco": "string ou null",
  "locatario_estado_civil": "string ou null",
  "locatario_profissao": "string ou null",
  "fiador_nome": "string ou null",
  "fiador_cpf": "string ou null",
  "fiador_telefone": "string ou null",
  "equipamentos": [
    {
      "patrimonio": "0345",
      "marca": "FONTAINE",
      "modelo": "string ou null",
      "btus": 9000,
      "voltagem": "127V ou null",
      "valor_locacao": 149.00,
      "valor_comercial": 2500.00
    }
  ],
  "equipamento_substituido": {
    "patrimonio": "133",
    "marca": "BRITANIA",
    "modelo": "string ou null",
    "btus": 12000,
    "voltagem": "220V ou null"
  },
  "endereco_instalacao": "string ou null",
  "prazo_meses": 12,
  "data_inicio": "2025-10-14",
  "data_termino": "2026-10-14",
  "data_assinatura": "2025-12-06",
  "dia_vencimento": 15,
  "valor_mensal": 149.00,
  "renovacao_automatica": true,
  "aviso_previo_dias": 30,
  "testemunhas": [
    {
      "nome": "TIELI PAULINO DA SILVA PACHECO",
      "cpf": "02101705141"
    }
  ],
  "assinatura_digital": {
    "plataforma": "Autentique",
    "hash": "string ou null",
    "assinaturas": [
      {
        "nome": "string",
        "cpf": "string",
        "data_hora": "2025-12-06T09:53:05",
        "ip": "string"
      }
    ]
  }
}

Se um campo não existir, use null. Se não for aditivo, "equipamento_substituido" = null. Datas em YYYY-MM-DD. Valores em número decimal.`;

  const result = await model.generateContent(prompt);
  const text = result.response.text();
  const cleaned = text.replace(/```json\n?/g, '').replace(/```\n?/g, '').trim();

  try {
    return JSON.parse(cleaned);
  } catch {
    console.error('[Gemini] Invalid JSON response:', cleaned.substring(0, 300));
    throw new Error('Gemini returned invalid JSON');
  }
}

/**
 * POST /api/dashboard/asaas/sync-all
 *
 * Synchronizes ALL data from Asaas API to Supabase cache:
 * - Fetches all customers, subscriptions, and payments from Asaas
 * - Upserts to asaas_contratos and asaas_cobrancas tables
 * - Updates asaas_cache_meta with sync timestamp
 * - Parses pending contracts (without contract_details) via Gemini
 *
 * This endpoint performs the same sync as the cron job sync-asaas.js,
 * but can be triggered manually from the dashboard.
 */
export async function syncAllAsaasHandler(
  request: FastifyRequest,
  reply: FastifyReply
) {
  try {
    const user_id = (request as any).user?.id;
    if (!user_id) {
      return reply.status(400).send({ status: 'error', message: 'Authentication required' });
    }

    // Get agentId from query params or find the user's agent with Asaas
    const queryAgentId = (request.query as any)?.agentId;

    let agent: { id: string; asaas_api_key: string; name?: string } | null = null;

    if (queryAgentId) {
      const { data } = await supabaseAdmin
        .from('agents')
        .select('id, asaas_api_key, name')
        .eq('id', queryAgentId)
        .eq('user_id', user_id)
        .not('asaas_api_key', 'is', null)
        .single();
      agent = data;
    } else {
      const { data: agents } = await supabaseAdmin
        .from('agents')
        .select('id, asaas_api_key, name')
        .eq('user_id', user_id)
        .not('asaas_api_key', 'is', null)
        .limit(1);
      agent = agents?.[0] || null;
    }

    if (!agent) {
      return reply.status(404).send({ status: 'error', message: 'No Asaas integration found' });
    }

    const geminiApiKey = process.env.GEMINI_API_KEY;
    if (!geminiApiKey) {
      console.warn('[SyncAllAsaas] GEMINI_API_KEY not configured. Contract parsing disabled.');
    }

    console.log(`[SyncAllAsaas] Starting sync for agent ${agent.name || agent.id}...`);

    const asaasClient = new AsaasClient({ apiKey: agent.asaas_api_key });

    // 1. Fetch all customers
    console.log('[SyncAllAsaas] Fetching customers...');
    const allCustomers = [];
    let customerOffset = 0;
    const customerLimit = 100;

    while (true) {
      await new Promise(resolve => setTimeout(resolve, 200)); // Rate limit
      const response = await asaasClient.listCustomers({ offset: customerOffset, limit: customerLimit });
      allCustomers.push(...response.data);

      if (!response.hasMore || response.data.length < customerLimit) {
        break;
      }
      customerOffset += customerLimit;

      if (allCustomers.length >= 1000) {
        console.warn('[SyncAllAsaas] Reached 1000 customer limit');
        break;
      }
    }

    console.log(`[SyncAllAsaas] Found ${allCustomers.length} customers`);

    // 1.1 Save customers to asaas_clientes table (backup/cache)
    if (allCustomers.length > 0) {
      console.log('[SyncAllAsaas] Saving customers to asaas_clientes...');
      const customerRecords = allCustomers.map((c: any) => ({
        id: c.id,
        agent_id: agent.id,
        name: c.name || null,
        cpf_cnpj: c.cpfCnpj || null,
        email: c.email || null,
        phone: c.phone || null,
        mobile_phone: c.mobilePhone || null,
        address: c.address || null,
        address_number: c.addressNumber || null,
        complement: c.complement || null,
        province: c.province || null,
        city: c.city || null,
        state: c.state || null,
        postal_code: c.postalCode || null,
        date_created: c.dateCreated || null,
        external_reference: c.externalReference || null,
        observations: c.observations || null,
        updated_at: new Date().toISOString(),
      }));

      await upsertInBatches('asaas_clientes', customerRecords, 50, 'id,agent_id');
      console.log(`[SyncAllAsaas] Saved ${customerRecords.length} customers to cache`);

      // Mark deleted customers (soft delete)
      const customerIds = allCustomers.map((c: any) => c.id).filter(Boolean);
      const deletedCustomers = await markDeletedRecords('asaas_clientes', agent.id, customerIds);
      if (deletedCustomers.marked > 0) {
        console.log(`[SyncAllAsaas] Marked ${deletedCustomers.marked} customers as deleted`);
      }
    }

    // Build customer cache for name resolution (múltiplas fontes)
    const customerCache = new Map<string, string>();

    // 1. Carregar da tabela asaas_clientes (cache persistente)
    const { data: cachedClientes } = await supabaseAdmin
      .from('asaas_clientes')
      .select('id, name')
      .eq('agent_id', agent.id)
      .not('name', 'is', null);

    if (cachedClientes) {
      for (const c of cachedClientes) {
        if (c.id && c.name) {
          customerCache.set(c.id, c.name);
        }
      }
    }

    // 2. Carregar da tabela billing_notifications (fallback - nomes salvos pelo job de cobrança)
    const { data: notifClientes } = await supabaseAdmin
      .from('billing_notifications')
      .select('customer_id, customer_name')
      .eq('agent_id', agent.id)
      .not('customer_name', 'is', null)
      .neq('customer_name', '')
      .neq('customer_name', 'Cliente');

    if (notifClientes) {
      for (const n of notifClientes) {
        if (n.customer_id && n.customer_name && !customerCache.has(n.customer_id)) {
          customerCache.set(n.customer_id, n.customer_name);
        }
      }
    }

    // 3. Sobrescrever com dados mais recentes da API Asaas
    for (const customer of allCustomers) {
      if (customer.id && customer.name) {
        customerCache.set(customer.id, customer.name);
      }
    }

    console.log(`[SyncAllAsaas] CustomerCache loaded: ${customerCache.size} entries (DB + API)`);

    // 2. Fetch all subscriptions (active + inactive)
    console.log('[SyncAllAsaas] Fetching subscriptions...');
    const allSubscriptions = [];
    let subOffset = 0;
    const subLimit = 100;

    // Fetch active
    while (true) {
      await new Promise(resolve => setTimeout(resolve, 200));
      const response = await asaasClient.listPayments({ status: 'ACTIVE', offset: subOffset, limit: subLimit } as any);
      // Note: Using listPayments as a workaround - need to fetch subscriptions properly
      break; // For now, skip - will use direct API call
    }

    // Fetch subscriptions via direct listAllPayments with subscription filter
    // Actually, we need to list subscriptions, not payments
    // Let's use a different approach - fetch all payments and extract subscription data

    // 3. Fetch all payments (all relevant statuses)
    console.log('[SyncAllAsaas] Fetching payments...');
    const paymentStatuses = ['PENDING', 'RECEIVED', 'CONFIRMED', 'OVERDUE', 'REFUNDED', 'RECEIVED_IN_CASH', 'DUNNING_REQUESTED'];
    const allPayments: any[] = [];

    for (const status of paymentStatuses) {
      console.log(`[SyncAllAsaas] Fetching ${status} payments...`);
      await new Promise(resolve => setTimeout(resolve, 200));
      const payments = await asaasClient.listAllPayments({ status, limit: 100 }, 20);
      allPayments.push(...payments);
      console.log(`[SyncAllAsaas] Found ${payments.length} ${status} payments`);
    }

    console.log(`[SyncAllAsaas] Total payments: ${allPayments.length}`);

    // 3.1 Find and fetch missing customers (customers not in cache but present in payments)
    const missingCustomerIds = new Set<string>();
    for (const payment of allPayments) {
      if (payment.customer && !customerCache.has(payment.customer)) {
        missingCustomerIds.add(payment.customer);
      }
    }

    if (missingCustomerIds.size > 0) {
      console.log(`[SyncAllAsaas] Fetching ${missingCustomerIds.size} missing customers individually...`);
      const missingCustomerRecords: any[] = [];
      const failedCustomerIds: string[] = [];

      // Helper function to fetch customer with retry
      const fetchCustomerWithRetry = async (customerId: string, maxRetries = 3): Promise<any | null> => {
        for (let attempt = 1; attempt <= maxRetries; attempt++) {
          try {
            // Exponential backoff: 500ms, 1000ms, 2000ms
            const delay = 500 * Math.pow(2, attempt - 1);
            await new Promise(resolve => setTimeout(resolve, delay));

            const customer = await asaasClient.getCustomer(customerId);
            if (customer?.name) {
              return customer;
            }
            // API returned but no name - don't retry, it's a data issue
            console.warn(`[SyncAllAsaas] Customer ${customerId} has no name in Asaas`);
            return null;
          } catch (err: any) {
            const isLastAttempt = attempt === maxRetries;
            if (isLastAttempt) {
              console.warn(`[SyncAllAsaas] Failed to fetch customer ${customerId} after ${maxRetries} attempts:`, err.message);
              return null;
            }
            console.log(`[SyncAllAsaas] Retry ${attempt}/${maxRetries} for customer ${customerId}`);
          }
        }
        return null;
      };

      for (const customerId of Array.from(missingCustomerIds)) {
        const customer = await fetchCustomerWithRetry(customerId);

        if (customer) {
          customerCache.set(customerId, customer.name);
          missingCustomerRecords.push({
            id: customer.id,
            agent_id: agent.id,
            name: customer.name,
            cpf_cnpj: customer.cpfCnpj || null,
            email: customer.email || null,
            phone: customer.phone || null,
            mobile_phone: customer.mobilePhone || null,
            address: customer.address || null,
            address_number: customer.addressNumber || null,
            complement: customer.complement || null,
            province: customer.province || null,
            city: customer.city || null,
            state: customer.state || null,
            postal_code: customer.postalCode || null,
            date_created: customer.dateCreated || null,
            external_reference: customer.externalReference || null,
            observations: customer.observations || null,
            deleted_from_asaas: false,
            updated_at: new Date().toISOString(),
          });
        } else {
          // Don't save "Desconhecido" to database - just track for this sync session
          // Next sync will try again
          failedCustomerIds.push(customerId);
          // Use customer ID as fallback for display (better than "Desconhecido")
          customerCache.set(customerId, `Cliente ${customerId.slice(-6)}`);
        }
      }

      if (missingCustomerRecords.length > 0) {
        await upsertInBatches('asaas_clientes', missingCustomerRecords, 50, 'id,agent_id');
        console.log(`[SyncAllAsaas] Saved ${missingCustomerRecords.length} missing customers`);
      }

      if (failedCustomerIds.length > 0) {
        console.warn(`[SyncAllAsaas] ${failedCustomerIds.length} customers could not be fetched - will retry on next sync`);
      }
    }

    // 4. Build subscriptions map from payments
    const subscriptionsMap = new Map<string, any>();
    for (const payment of allPayments) {
      if (payment.subscription && !subscriptionsMap.has(payment.subscription)) {
        // We'll need to fetch subscription details
        // For now, create a placeholder
        subscriptionsMap.set(payment.subscription, {
          id: payment.subscription,
          customer: payment.customer,
          customerName: customerCache.get(payment.customer) || `Cliente #${payment.customer?.slice(-6) || '?'}`,
          value: payment.value,
          status: 'ACTIVE', // Assume active if has payments
        });
      }
    }

    // Fetch full subscription details for each unique subscription
    console.log(`[SyncAllAsaas] Fetching ${subscriptionsMap.size} subscription details...`);
    const subscriptionRecords: any[] = [];

    for (const subId of Array.from(subscriptionsMap.keys())) {
      try {
        await new Promise(resolve => setTimeout(resolve, 200));
        const sub = await asaasClient.getSubscription(subId);
        if (sub) {
          subscriptionRecords.push({
            id: sub.id,
            agent_id: agent.id,
            customer_id: sub.customer,
            customer_name: customerCache.get(sub.customer) || `Cliente #${sub.customer?.slice(-6) || '?'}`,
            value: sub.value,
            status: sub.status,
            cycle: sub.cycle,
            next_due_date: sub.nextDueDate || null,
            description: sub.description,
            billing_type: sub.billingType,
            updated_at: new Date().toISOString(),
          });
        }
      } catch (err) {
        console.warn(`[SyncAllAsaas] Failed to fetch subscription ${subId}:`, err);
      }
    }

    console.log(`[SyncAllAsaas] Fetched ${subscriptionRecords.length} subscriptions`);

    // 5. Build payment records
    const paymentRecords = allPayments.map(p => ({
      id: p.id,
      agent_id: agent.id,
      customer_id: p.customer,
      customer_name: customerCache.get(p.customer) || `Cliente #${p.customer?.slice(-6) || '?'}`,
      subscription_id: p.subscription || null,
      value: p.value,
      net_value: p.netValue,
      status: p.status,
      billing_type: p.billingType,
      due_date: p.dueDate || null,
      payment_date: p.paymentDate || null,
      date_created: p.dateCreated || null,
      description: p.description,
      invoice_url: p.invoiceUrl,
      bank_slip_url: p.bankSlipUrl,
      dias_atraso: (p.status === 'OVERDUE' || p.status === 'DUNNING_REQUESTED')
        ? calcDiasAtraso(p.dueDate)
        : 0,
      updated_at: new Date().toISOString(),
    }));

    // 5.1 PROTEÇÃO: Preservar nomes válidos existentes no banco
    // Se o nome proposto é fallback (vazio ou "Cliente #..."), buscar nome atual do banco
    const isInvalidName = (name: string | null | undefined): boolean => {
      if (!name || name.trim() === '') return true;
      const lower = name.toLowerCase().trim();
      return lower === 'sem nome' ||
             lower === 'desconhecido' ||
             lower.startsWith('cliente #') ||
             lower.startsWith('cliente ') && /^cliente [a-f0-9]{6}$/i.test(lower);
    };

    // Identificar registros com nomes inválidos que precisam verificação
    const recordsWithInvalidNames = paymentRecords.filter(p => isInvalidName(p.customer_name));
    if (recordsWithInvalidNames.length > 0) {
      console.log(`[SyncAllAsaas] Checking ${recordsWithInvalidNames.length} payments with fallback names...`);

      // Buscar nomes existentes no banco para esses IDs
      const paymentIds = recordsWithInvalidNames.map(p => p.id);
      const { data: existingPayments } = await supabaseAdmin
        .from('asaas_cobrancas')
        .select('id, customer_name')
        .in('id', paymentIds);

      if (existingPayments && existingPayments.length > 0) {
        const existingNamesMap = new Map(
          existingPayments.map(ep => [ep.id, ep.customer_name])
        );

        let preserved = 0;
        for (const record of paymentRecords) {
          if (isInvalidName(record.customer_name)) {
            const existingName = existingNamesMap.get(record.id);
            if (existingName && !isInvalidName(existingName)) {
              // Nome existente é válido - preservar!
              record.customer_name = existingName;
              preserved++;
            }
          }
        }
        if (preserved > 0) {
          console.log(`[SyncAllAsaas] Preserved ${preserved} valid customer names from database`);
        }
      }
    }

    // Fazer o mesmo para subscriptionRecords (contratos)
    const contractsWithInvalidNames = subscriptionRecords.filter(c => isInvalidName(c.customer_name));
    if (contractsWithInvalidNames.length > 0) {
      console.log(`[SyncAllAsaas] Checking ${contractsWithInvalidNames.length} contracts with fallback names...`);

      const contractIds = contractsWithInvalidNames.map(c => c.id);
      const { data: existingContracts } = await supabaseAdmin
        .from('asaas_contratos')
        .select('id, customer_name')
        .in('id', contractIds);

      if (existingContracts && existingContracts.length > 0) {
        const existingContractNamesMap = new Map(
          existingContracts.map(ec => [ec.id, ec.customer_name])
        );

        let preserved = 0;
        for (const record of subscriptionRecords) {
          if (isInvalidName(record.customer_name)) {
            const existingName = existingContractNamesMap.get(record.id);
            if (existingName && !isInvalidName(existingName)) {
              record.customer_name = existingName;
              preserved++;
            }
          }
        }
        if (preserved > 0) {
          console.log(`[SyncAllAsaas] Preserved ${preserved} valid contract customer names from database`);
        }
      }
    }

    // 5.2 PROTEÇÃO UNIVERSAL: Remover customer_name se ainda for inválido
    // Isso garante que o upsert NÃO sobrescreverá valores existentes no banco
    let paymentNamesRemoved = 0;
    for (const record of paymentRecords as any[]) {
      if (isInvalidName(record.customer_name)) {
        delete record.customer_name;
        paymentNamesRemoved++;
      }
    }
    if (paymentNamesRemoved > 0) {
      console.log(`[SyncAllAsaas] Removed ${paymentNamesRemoved} invalid customer_name fields from payments (will preserve DB values)`);
    }

    let contractNamesRemoved = 0;
    for (const record of subscriptionRecords as any[]) {
      if (isInvalidName(record.customer_name)) {
        delete record.customer_name;
        contractNamesRemoved++;
      }
    }
    if (contractNamesRemoved > 0) {
      console.log(`[SyncAllAsaas] Removed ${contractNamesRemoved} invalid customer_name fields from contracts (will preserve DB values)`);
    }

    // 6. Upsert to Supabase
    console.log(`[SyncAllAsaas] Upserting ${subscriptionRecords.length} contracts...`);
    if (subscriptionRecords.length > 0) {
      await upsertInBatches('asaas_contratos', subscriptionRecords, 50);

      // NOTE: Soft delete DISABLED for contracts (asaas_contratos)
      // The logic was marking 206 of 209 active contracts as deleted incorrectly
      // This happened because the loop fetching subscriptions (lines 1220-1226) had a break
      // that prevented full data collection, resulting in an empty/partial list
      // When markDeletedRecords compared against this incomplete list, it marked valid contracts as deleted
      // Same issue as with payments - the sync loop needs fixing before soft delete can be enabled
      // For now, contracts that no longer exist in Asaas simply won't be updated
    }

    console.log(`[SyncAllAsaas] Upserting ${paymentRecords.length} payments...`);
    if (paymentRecords.length > 0) {
      await upsertInBatches('asaas_cobrancas', paymentRecords, 50);

      // NOTE: Soft delete DISABLED for payments/cobrancas
      // The Asaas API doesn't return all future charges (subscriptions create them near due date)
      // Also, charges change status frequently (PENDING -> RECEIVED -> etc)
      // Soft delete was incorrectly marking valid charges as deleted
      // If a charge truly doesn't exist anymore, it simply won't be updated
    }

    // 7. Parse pending contracts
    console.log('[SyncAllAsaas] Checking for contracts to parse...');
    let contratosParsed = 0;
    let novosParsed = 0;

    if (geminiApiKey) {
      // Get contracts already parsed
      const { data: existingDetails } = await supabaseAdmin
        .from('contract_details')
        .select('subscription_id')
        .eq('agent_id', agent.id);

      const parsedIds = new Set((existingDetails || []).map(d => d.subscription_id));
      const pendingContracts = subscriptionRecords.filter(c =>
        c.status === 'ACTIVE' && !parsedIds.has(c.id)
      );

      console.log(`[SyncAllAsaas] ${pendingContracts.length} contracts pending parse`);

      for (const contrato of pendingContracts.slice(0, 10)) { // Limit to 10 for performance
        try {
          console.log(`[SyncAllAsaas] Parsing contract ${contrato.id}...`);
          const parsed = await parseContractInternal(
            contrato.id,
            contrato.customer_id,
            contrato.customer_name,
            agent.id,
            asaasClient,
            geminiApiKey
          );

          if (parsed) {
            contratosParsed++;
            if (!parsedIds.has(contrato.id)) {
              novosParsed++;
            }
          }

          await new Promise(resolve => setTimeout(resolve, 1000)); // Rate limit
        } catch (err) {
          console.warn(`[SyncAllAsaas] Failed to parse contract ${contrato.id}:`, err);
        }
      }
    }

    // 8. Update cache meta
    console.log('[SyncAllAsaas] Updating cache metadata...');
    await supabaseAdmin
      .from('asaas_cache_meta')
      .upsert({
        agent_id: agent.id,
        ultima_sync: new Date().toISOString(),
        total_contratos_ativos: subscriptionRecords.filter(s => s.status === 'ACTIVE').length,
        total_contratos_inativos: subscriptionRecords.filter(s => s.status !== 'ACTIVE').length,
        updated_at: new Date().toISOString(),
      }, { onConflict: 'agent_id' });

    console.log('[SyncAllAsaas] Sync completed successfully');

    return reply.send({
      status: 'success',
      data: {
        clientes: allCustomers.length,
        contratos: subscriptionRecords.length,
        cobrancas: paymentRecords.length,
        contratosParsed,
        novosParsed,
      },
    });

  } catch (error) {
    console.error('[SyncAllAsaas] Error:', error);
    return reply.status(500).send({
      status: 'error',
      message: error instanceof Error ? error.message : 'Internal server error',
    });
  }
}

/**
 * Helper: Calculate days overdue from due date
 */
function calcDiasAtraso(dueDate: string | null): number {
  if (!dueDate) return 0;
  const hoje = new Date();
  hoje.setHours(0, 0, 0, 0);
  const venc = new Date(dueDate + 'T00:00:00');
  const diff = Math.floor((hoje.getTime() - venc.getTime()) / (1000 * 60 * 60 * 24));
  return diff > 0 ? diff : 0;
}

/**
 * Helper: Upsert records in batches
 * @param table - Table name
 * @param records - Records to upsert
 * @param batchSize - Batch size
 * @param onConflict - Column(s) for conflict resolution (default: 'id')
 */
async function upsertInBatches(table: string, records: any[], batchSize: number, onConflict: string = 'id') {
  for (let i = 0; i < records.length; i += batchSize) {
    const batch = records.slice(i, i + batchSize);
    const { error } = await supabaseAdmin
      .from(table)
      .upsert(batch, { onConflict });

    if (error) {
      console.error(`[UpsertBatch] Error in ${table} batch ${Math.floor(i / batchSize) + 1}:`, error);
      throw error;
    }
  }
}

/**
 * Marca registros como deletados (soft delete) quando não existem mais no Asaas
 * @param table Nome da tabela (asaas_clientes, asaas_contratos, asaas_cobrancas)
 * @param agentId ID do agente
 * @param activeIds IDs dos registros que existem no Asaas
 */
async function markDeletedRecords(table: string, agentId: string, activeIds: string[]) {
  if (activeIds.length === 0) {
    console.warn(`[MarkDeleted] No active IDs provided for ${table}, skipping soft delete check`);
    return { marked: 0 };
  }

  try {
    // Marca como deletado registros que:
    // 1. Pertencem ao agente
    // 2. NÃO estão na lista de IDs ativos vindos do Asaas
    // 3. Ainda não foram marcados como deletados
    const { data, error } = await supabaseAdmin
      .from(table)
      .update({
        deleted_at: new Date().toISOString(),
        deleted_from_asaas: true,
        updated_at: new Date().toISOString(),
      })
      .eq('agent_id', agentId)
      .not('id', 'in', `(${activeIds.map(id => `'${id}'`).join(',')})`)
      .eq('deleted_from_asaas', false)
      .select('id');

    if (error) {
      console.error(`[MarkDeleted] Error marking deleted records in ${table}:`, error);
      throw error;
    }

    const markedCount = data?.length || 0;
    if (markedCount > 0) {
      console.log(`[MarkDeleted] Marked ${markedCount} records as deleted in ${table}`);
    }

    return { marked: markedCount };
  } catch (error) {
    console.error(`[MarkDeleted] Failed to mark deleted records in ${table}:`, error);
    throw error;
  }
}

/**
 * Helper: Parse a single contract (internal version without reply)
 */
async function parseContractInternal(
  subscriptionId: string,
  customerId: string,
  customerName: string,
  agentId: string,
  asaasClient: AsaasClient,
  geminiApiKey: string
): Promise<boolean> {
  const pdfParse = require('pdf-parse');

  // Get payments for this subscription
  await new Promise(resolve => setTimeout(resolve, 200));
  const payments = await asaasClient.listAllPayments({ subscription: subscriptionId, limit: 50 });

  if (!payments || payments.length === 0) {
    return false;
  }

  const allPdfInfos: any[] = [];
  const allContractData: any[] = [];

  for (const payment of payments.slice(0, 5)) { // Limit to 5 payments
    await new Promise(resolve => setTimeout(resolve, 200));
    const docs = await asaasClient.listPaymentDocuments(payment.id);
    const pdfDocs = docs.filter((d: any) => d.name?.toLowerCase().endsWith('.pdf'));

    for (const pdfDoc of pdfDocs) {
      const url = pdfDoc.file?.publicAccessUrl || pdfDoc.file?.downloadUrl;
      if (!url) continue;

      try {
        const buffer = await asaasClient.downloadDocument(url);
        const pdfData = await pdfParse(buffer);
        const pdfText = pdfData.text;

        if (!pdfText || pdfText.trim().length < 50) {
          continue;
        }

        const extracted = await extractWithGemini(pdfText, geminiApiKey);
        if (extracted) {
          allContractData.push(extracted);
          allPdfInfos.push({
            paymentId: payment.id,
            docId: pdfDoc.id,
            docName: pdfDoc.name,
            docUrl: url,
          });
        }
        await new Promise(resolve => setTimeout(resolve, 500));
      } catch (err) {
        // Skip failed PDFs
      }
    }
  }

  if (allPdfInfos.length === 0) {
    return false;
  }

  // Merge data from all PDFs
  const contractData = mergeContractData(allContractData);

  const equipamentos = contractData.equipamentos || [];
  const qtdArs = equipamentos.length;
  const valorComercialTotal = equipamentos.reduce(
    (sum: number, eq: any) => sum + (eq.valor_comercial || 0), 0
  );

  let proximaManutencao: string | null = null;
  if (contractData.data_inicio) {
    const inicio = new Date(contractData.data_inicio);
    inicio.setMonth(inicio.getMonth() + 6);
    proximaManutencao = inicio.toISOString().split('T')[0];
  }

  const record = {
    agent_id: agentId,
    subscription_id: subscriptionId,
    customer_id: customerId,
    payment_id: allPdfInfos[0].paymentId,
    document_id: allPdfInfos.map(p => p.docId).join(','),
    // Novos campos de numeração
    tipo_documento: contractData.tipo_documento || null,
    numero_contrato: contractData.numero_contrato || null,
    numero_cliente: contractData.numero_cliente || null,
    numero_aditivo: contractData.numero_aditivo || null,
    // Dados do locatário
    locatario_nome: contractData.locatario_nome || customerName,
    locatario_cpf_cnpj: contractData.locatario_cpf_cnpj || null,
    locatario_telefone: contractData.locatario_telefone || null,
    locatario_endereco: contractData.locatario_endereco || null,
    locatario_estado_civil: contractData.locatario_estado_civil || null,
    locatario_profissao: contractData.locatario_profissao || null,
    // Fiador
    fiador_nome: contractData.fiador_nome || null,
    fiador_cpf: contractData.fiador_cpf || null,
    fiador_telefone: contractData.fiador_telefone || null,
    // Equipamentos
    equipamentos,
    equipamento_substituido: contractData.equipamento_substituido || null,
    qtd_ars: qtdArs,
    valor_comercial_total: valorComercialTotal,
    endereco_instalacao: contractData.endereco_instalacao || null,
    // Datas e prazos
    prazo_meses: contractData.prazo_meses || null,
    data_inicio: contractData.data_inicio || null,
    data_termino: contractData.data_termino || null,
    data_assinatura: contractData.data_assinatura || null,
    dia_vencimento: contractData.dia_vencimento || null,
    valor_mensal: contractData.valor_mensal || null,
    proxima_manutencao: proximaManutencao,
    // Termos do contrato
    renovacao_automatica: contractData.renovacao_automatica ?? null,
    aviso_previo_dias: contractData.aviso_previo_dias || null,
    // Testemunhas e assinatura digital
    testemunhas: contractData.testemunhas || null,
    assinatura_digital: contractData.assinatura_digital || null,
    // Metadados
    pdf_url: allPdfInfos[0].docUrl,
    pdf_filename: allPdfInfos.map(p => p.docName).join(', '),
    parsed_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };

  const { error } = await supabaseAdmin
    .from('contract_details')
    .upsert(record, { onConflict: 'subscription_id,agent_id' });

  if (error) {
    console.error('[ParseContractInternal] Upsert error:', error);
    return false;
  }

  return true;
}

/**
 * GET /api/dashboard/asaas/customers
 *
 * Returns all customers from Asaas API for the authenticated user's agent.
 */
export async function getAsaasCustomersHandler(
  request: FastifyRequest,
  reply: FastifyReply
) {
  try {
    const user_id = (request as any).user?.id;
    if (!user_id) {
      return reply.status(400).send({ status: 'error', message: 'Authentication required' });
    }

    // Get agentId from query params or find the user's agent with Asaas
    const queryAgentId = (request.query as any)?.agentId;

    let agent: { id: string; asaas_api_key: string } | null = null;

    if (queryAgentId) {
      const { data } = await supabaseAdmin
        .from('agents')
        .select('id, asaas_api_key')
        .eq('id', queryAgentId)
        .eq('user_id', user_id)
        .not('asaas_api_key', 'is', null)
        .single();
      agent = data;
    } else {
      const { data: agents } = await supabaseAdmin
        .from('agents')
        .select('id, asaas_api_key')
        .eq('user_id', user_id)
        .not('asaas_api_key', 'is', null)
        .limit(1);
      agent = agents?.[0] || null;
    }

    if (!agent) {
      return reply.status(404).send({ status: 'error', message: 'No Asaas integration found' });
    }

    // Data filter: only clients created from January 2026 onwards
    const DATA_FILTRO_CLIENTES = '2026-01-01';

    // Fetch all customers from Asaas
    const asaasClient = new AsaasClient({ apiKey: agent.asaas_api_key });
    const allCustomers = [];
    let offset = 0;
    const limit = 100;

    while (true) {
      const response = await asaasClient.listCustomers({ offset, limit });
      allCustomers.push(...response.data);

      if (!response.hasMore || response.data.length < limit) {
        break;
      }
      offset += limit;

      // Safety limit
      if (allCustomers.length >= 1000) {
        console.warn('[AsaasCustomers] Reached 1000 customer limit');
        break;
      }
    }

    // Filter clients by registration date (>= February 2026)
    const filteredCustomers = allCustomers.filter(c =>
      c.dateCreated && c.dateCreated >= DATA_FILTRO_CLIENTES
    );

    return reply.send({
      status: 'success',
      data: filteredCustomers.map(c => ({
        id: c.id,
        name: c.name,
        cpfCnpj: c.cpfCnpj,
        email: c.email,
        phone: c.phone,
        mobilePhone: c.mobilePhone,
        dateCreated: c.dateCreated,
      })),
    });

  } catch (error) {
    console.error('[AsaasCustomers] Error:', error);
    return reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

/**
 * GET /api/dashboard/asaas/parcelamentos
 *
 * Returns all installment customers (quebras de contrato) for the authenticated user's agent.
 * Fetches from the asaas_parcelamentos cache table.
 */
export async function getAsaasParcelamentosHandler(
  request: FastifyRequest,
  reply: FastifyReply
) {
  try {
    const user_id = (request as any).user?.id;
    if (!user_id) {
      return reply.status(400).send({ status: 'error', message: 'Authentication required' });
    }

    // Get agentId from query params or find the user's agent with Asaas
    const queryAgentId = (request.query as any)?.agentId;

    let agent: { id: string } | null = null;

    if (queryAgentId) {
      const { data } = await supabaseAdmin
        .from('agents')
        .select('id')
        .eq('id', queryAgentId)
        .eq('user_id', user_id)
        .single();
      agent = data;
    } else {
      const { data: agents } = await supabaseAdmin
        .from('agents')
        .select('id')
        .eq('user_id', user_id)
        .not('asaas_api_key', 'is', null)
        .limit(1);
      agent = agents?.[0] || null;
    }

    if (!agent) {
      return reply.status(404).send({ status: 'error', message: 'No Asaas integration found' });
    }

    // Fetch parcelamentos from cache table
    const { data: parcelamentos, error } = await supabaseAdmin
      .from('asaas_parcelamentos')
      .select('*')
      .eq('agent_id', agent.id)
      .eq('deleted', false)
      .order('date_created', { ascending: false });

    if (error) {
      console.error('[AsaasParcelamentos] Error fetching:', error);
      return reply.status(500).send({ status: 'error', message: 'Error fetching parcelamentos' });
    }

    // Get unique customers with their parcelamento details
    const customerMap = new Map<string, any>();
    for (const p of parcelamentos || []) {
      if (!customerMap.has(p.customer_id)) {
        customerMap.set(p.customer_id, {
          customer_id: p.customer_id,
          customer_name: p.customer_name,
          parcelamentos: [],
          total_value: 0,
        });
      }
      const customer = customerMap.get(p.customer_id);
      customer.parcelamentos.push({
        id: p.id,
        installment_count: p.installment_count,
        value: p.value,
        billing_type: p.billing_type,
        date_created: p.date_created,
      });
      customer.total_value += Number(p.value) || 0;
    }

    const customers = Array.from(customerMap.values());

    return reply.send({
      status: 'success',
      data: customers,
      total_parcelamentos: parcelamentos?.length || 0,
      total_clientes: customers.length,
    });

  } catch (error) {
    console.error('[AsaasParcelamentos] Error:', error);
    return reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}

/**
 * GET /api/dashboard/asaas/available-months
 *
 * Returns list of months that have charges in asaas_cobrancas table.
 * Used to populate month filter dropdown with real data instead of hardcoded "last 6 months".
 */
export async function getAsaasAvailableMonthsHandler(
  request: FastifyRequest,
  reply: FastifyReply
) {
  try {
    const user_id = (request as any).user?.id;
    if (!user_id) {
      return reply.status(400).send({ status: 'error', message: 'Authentication required' });
    }

    // Get agentId from query params or find the user's agent with Asaas
    const queryAgentId = (request.query as any)?.agentId;

    let agent: { id: string } | null = null;

    if (queryAgentId) {
      const { data } = await supabaseAdmin
        .from('agents')
        .select('id')
        .eq('id', queryAgentId)
        .eq('user_id', user_id)
        .single();
      agent = data;
    } else {
      const { data: agents } = await supabaseAdmin
        .from('agents')
        .select('id')
        .eq('user_id', user_id)
        .not('asaas_api_key', 'is', null)
        .limit(1);
      agent = agents?.[0] || null;
    }

    if (!agent) {
      return reply.status(404).send({ status: 'error', message: 'No Asaas integration found' });
    }

    // Fetch all charges for this agent (non-deleted only)
    // Use due_date (vencimento) instead of date_created for filtering by month
    const { data: cobrancas, error } = await supabaseAdmin
      .from('asaas_cobrancas')
      .select('due_date')
      .eq('agent_id', agent.id)
      .eq('deleted_from_asaas', false)
      .not('due_date', 'is', null);

    if (error) {
      console.error('[AsaasAvailableMonths] Error fetching charges:', error);
      // Fallback: return empty array to allow frontend to use default behavior
      return reply.send({
        status: 'success',
        data: [],
      });
    }

    // Extract unique months and count charges per month
    const monthsMap = new Map<string, number>();

    for (const cobranca of cobrancas || []) {
      const dueDate = cobranca.due_date;
      if (!dueDate) continue;

      // Extract YYYY-MM from due_date (format: YYYY-MM-DD)
      const monthKey = dueDate.substring(0, 7); // Get "YYYY-MM"
      monthsMap.set(monthKey, (monthsMap.get(monthKey) || 0) + 1);
    }

    // Convert to array and sort DESC (most recent first)
    const months = Array.from(monthsMap.entries())
      .map(([monthKey, count]) => {
        const [year, month] = monthKey.split('-');
        const date = new Date(parseInt(year), parseInt(month) - 1, 1);
        const label = date.toLocaleDateString('pt-BR', { month: 'long', year: 'numeric' });
        const labelCapitalized = label.charAt(0).toUpperCase() + label.slice(1);

        return {
          month: monthKey, // YYYY-MM format
          label: labelCapitalized,
          count,
        };
      })
      .sort((a, b) => b.month.localeCompare(a.month)); // Sort DESC

    return reply.send({
      status: 'success',
      data: months,
    });

  } catch (error) {
    console.error('[AsaasAvailableMonths] Error:', error);
    return reply.status(500).send({ status: 'error', message: 'Internal server error' });
  }
}
