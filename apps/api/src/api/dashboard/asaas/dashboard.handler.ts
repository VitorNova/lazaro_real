import { FastifyRequest, FastifyReply } from 'fastify';
import { supabaseAdmin } from '../../../services/supabase/client';
import { AsaasClient } from '../../../services/asaas/client';

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
