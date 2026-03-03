import { FastifyRequest, FastifyReply } from 'fastify';
import { supabaseAdmin } from '../../../services/supabase/client';
import { AsaasClient } from '../../../services/asaas/client';
import { parseContractInternal } from './contract-parser.handler';

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
export function calcDiasAtraso(dueDate: string | null): number {
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
export async function upsertInBatches(table: string, records: any[], batchSize: number, onConflict: string = 'id') {
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
export async function markDeletedRecords(table: string, agentId: string, activeIds: string[]) {
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
