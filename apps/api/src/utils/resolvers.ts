/**
 * Resolvers centralizados para busca de dados com fallback
 *
 * Hierarquia padrao:
 * 1. Redis cache (rapido, volatil)
 * 2. Supabase (persistente)
 * 3. API externa com RETRY (lento, rate limited)
 * 4. Fallback null ou "Desconhecido" (ultimo recurso)
 *
 * IMPORTANTE: O Asaas NAO envia webhooks de CUSTOMER, apenas de PAYMENT e SUBSCRIPTION.
 * Por isso, a busca via API e CRITICA e precisa de retry robusto.
 */

import { getRedisConnection } from '../services/redis/client';
import { supabaseAdmin } from '../services/supabase/client';
import { AsaasClient } from '../services/asaas/client';

const DEFAULT_NAME = 'Desconhecido';
const CACHE_TTL_SECONDS = 86400; // 24 horas

// ============================================================================
// TIPOS
// ============================================================================

export interface ResolveOptions {
  /** Se deve logar cada etapa (default: true para melhor observabilidade) */
  verbose?: boolean;
  /** TTL customizado para cache Redis em segundos */
  cacheTtl?: number;
  /** Numero maximo de tentativas na API (default: 3) */
  maxRetries?: number;
  /** Se deve retornar null em vez de "Desconhecido" quando falha */
  returnNullOnFailure?: boolean;
}

export interface ResolveResult<T> {
  value: T;
  source: 'redis' | 'supabase' | 'api' | 'fallback';
}

// ============================================================================
// HELPER: RETRY COM EXPONENTIAL BACKOFF
// ============================================================================

async function retryWithBackoff<T>(
  fn: () => Promise<T>,
  options: {
    maxRetries: number;
    initialDelayMs: number;
    maxDelayMs: number;
    operationName: string;
  }
): Promise<T | null> {
  const { maxRetries, initialDelayMs, maxDelayMs, operationName } = options;

  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      const result = await fn();
      if (attempt > 1) {
        console.log(`[Resolver] ${operationName} sucesso na tentativa ${attempt}/${maxRetries}`);
      }
      return result;
    } catch (error: any) {
      const isLastAttempt = attempt === maxRetries;
      const delay = Math.min(initialDelayMs * Math.pow(2, attempt - 1), maxDelayMs);

      // Log detalhado do erro
      const errorMsg = error?.message || error?.toString() || 'Erro desconhecido';
      const statusCode = error?.response?.status || error?.statusCode || 'N/A';

      if (isLastAttempt) {
        console.error(
          `[Resolver] ${operationName} FALHOU apos ${maxRetries} tentativas. ` +
          `Ultimo erro: ${errorMsg} (status: ${statusCode})`
        );
        return null;
      }

      console.warn(
        `[Resolver] ${operationName} tentativa ${attempt}/${maxRetries} falhou: ${errorMsg}. ` +
        `Aguardando ${delay}ms antes de retry...`
      );

      await new Promise(resolve => setTimeout(resolve, delay));
    }
  }

  return null;
}

// ============================================================================
// CUSTOMER NAME RESOLVER (COM RETRY) - DEPRECATED
// ============================================================================

/**
 * @deprecated Esta função nunca é chamada no código. A lógica de resolução de
 * customer_name agora está implementada inline em cada módulo:
 * - Python: billing_charge.py e billing_reconciliation.py (_resolve_customer_name)
 * - Node.js: sync-asaas.js (resolveCustomerName local)
 * - TypeScript: asaas.handler.ts (proteção inline antes do upsert)
 *
 * Motivo: A API /payments do Asaas NÃO retorna customerName, apenas customer (ID).
 * Cada módulo precisa resolver o nome consultando asaas_clientes ou /customers/{id}.
 *
 * AVALIAR REMOÇÃO em futuras limpezas de código (após 2026-03-01).
 *
 * Resolve o nome de um cliente Asaas com retry robusto
 *
 * @param customerId - ID do cliente no Asaas (ex: "cus_xxx")
 * @param agentId - ID do agente no PHANT (UUID)
 * @param options - Opcoes de resolucao
 * @returns Nome do cliente, null, ou "Desconhecido" (conforme config)
 *
 * @example
 * // Uso padrao (retorna "Desconhecido" se falhar)
 * const name = await resolveCustomerName('cus_123', 'uuid-agent');
 *
 * // Uso com null (para nao poluir banco com fallback)
 * const name = await resolveCustomerName('cus_123', 'uuid-agent', { returnNullOnFailure: true });
 */
export async function resolveCustomerName(
  customerId: string,
  agentId: string | null,
  options: ResolveOptions = {}
): Promise<string | null> {
  const {
    verbose = true, // Mudado para true por padrao para melhor observabilidade
    cacheTtl = CACHE_TTL_SECONDS,
    maxRetries = 3,
    returnNullOnFailure = false
  } = options;

  const fallback = returnNullOnFailure ? null : DEFAULT_NAME;
  const log = (msg: string) => verbose && console.log(`[Resolver] ${msg}`);

  // Validacao de entrada
  if (!agentId || !customerId) {
    log(`IDs vazios (agentId: ${agentId}, customerId: ${customerId}), retornando fallback`);
    return fallback;
  }

  const cacheKey = `asaas:customer:${agentId}:${customerId}`;
  log(`Resolvendo cliente ${customerId} para agente ${agentId}`);

  // -------------------------------------------------------------------------
  // 1. REDIS CACHE (isolado em try/catch proprio)
  // -------------------------------------------------------------------------
  try {
    const redis = getRedisConnection();
    const cached = await redis.get(cacheKey);
    if (cached) {
      log(`Cache hit Redis: "${cached}"`);
      return cached;
    }
    log('Cache miss Redis');
  } catch (redisError: any) {
    console.warn(`[Resolver] Erro ao acessar Redis (continuando): ${redisError.message}`);
    // Continua para Supabase mesmo se Redis falhar
  }

  // -------------------------------------------------------------------------
  // 2. SUPABASE CACHE (isolado em try/catch proprio)
  // -------------------------------------------------------------------------
  try {
    const { data: localCache, error: supabaseError } = await supabaseAdmin
      .from('asaas_clientes')
      .select('name')
      .eq('id', customerId)
      .eq('agent_id', agentId)
      .maybeSingle();

    if (supabaseError) {
      console.warn(`[Resolver] Erro ao buscar em Supabase: ${supabaseError.message}`);
    } else if (localCache?.name && localCache.name !== DEFAULT_NAME) {
      log(`Cache hit Supabase: "${localCache.name}"`);

      // Propagar para Redis (em background, nao bloqueia)
      try {
        const redis = getRedisConnection();
        await redis.set(cacheKey, localCache.name, 'EX', cacheTtl);
      } catch (e) {
        // Ignora erro de Redis, ja temos o dado
      }

      return localCache.name;
    } else {
      log('Cache miss Supabase');
    }
  } catch (supabaseError: any) {
    console.warn(`[Resolver] Erro ao acessar Supabase (continuando): ${supabaseError.message}`);
    // Continua para API mesmo se Supabase falhar
  }

  // -------------------------------------------------------------------------
  // 3. API ASAAS COM RETRY
  // -------------------------------------------------------------------------
  log(`Buscando cliente via API Asaas (max ${maxRetries} tentativas)...`);

  // Primeiro, buscar a API key do agente
  let apiKey: string | null = null;
  try {
    const { data: agent, error: agentError } = await supabaseAdmin
      .from('agents')
      .select('asaas_api_key')
      .eq('id', agentId)
      .maybeSingle();

    if (agentError || !agent?.asaas_api_key) {
      log(`Agent ${agentId} sem asaas_api_key configurada`);
      return fallback;
    }
    apiKey = agent.asaas_api_key;
  } catch (error: any) {
    console.error(`[Resolver] Erro ao buscar API key do agente: ${error.message}`);
    return fallback;
  }

  // Buscar cliente na API com retry
  const asaasClient = new AsaasClient({ apiKey: apiKey! });

  const customer = await retryWithBackoff(
    async () => {
      const result = await asaasClient.getCustomer(customerId);
      if (!result) {
        throw new Error('Cliente nao encontrado na API');
      }
      return result;
    },
    {
      maxRetries,
      initialDelayMs: 500,
      maxDelayMs: 5000,
      operationName: `getCustomer(${customerId})`
    }
  );

  if (customer?.name) {
    log(`API hit: "${customer.name}"`);

    // Cachear em Redis (em background)
    try {
      const redis = getRedisConnection();
      await redis.set(cacheKey, customer.name, 'EX', cacheTtl);
      log('Cacheado em Redis');
    } catch (e) {
      // Ignora erro de Redis
    }

    // Persistir em Supabase (importante para proximo acesso)
    try {
      const now = new Date().toISOString();
      await supabaseAdmin.from('asaas_clientes').upsert({
        id: customerId,
        agent_id: agentId,
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
        updated_at: now,
      }, { onConflict: 'id,agent_id' });
      log('Persistido em Supabase (asaas_clientes)');
    } catch (upsertError: any) {
      console.warn(`[Resolver] Erro ao persistir cliente em Supabase: ${upsertError.message}`);
      // Continua, ja temos o nome
    }

    return customer.name;
  }

  // -------------------------------------------------------------------------
  // 4. FALLBACK
  // -------------------------------------------------------------------------
  log(`Todas as tentativas falharam para cliente ${customerId}, retornando ${fallback === null ? 'null' : `"${fallback}"`}`);
  return fallback;
}

// ============================================================================
// AGENT NAME RESOLVER
// ============================================================================

/**
 * Resolve o nome de um agente pelo ID de forma SINCRONA
 * Para uso em contextos sincronos como .map()
 *
 * @param agentId - UUID do agente
 * @param agentMap - Map pre-carregado de agentes (OBRIGATORIO)
 * @returns Nome do agente ou "Desconhecido"
 *
 * @example
 * const agents = await supabase.from('agents').select('id, name');
 * const agentMap = new Map(agents.map(a => [a.id, a.name]));
 * const names = ids.map(id => resolveAgentNameSync(id, agentMap));
 */
export function resolveAgentNameSync(
  agentId: string | null | undefined,
  agentMap: Map<string, string>
): string {
  if (!agentId) return DEFAULT_NAME;
  return agentMap.get(agentId) || DEFAULT_NAME;
}

/**
 * Resolve o nome de um agente pelo ID
 *
 * @param agentId - UUID do agente
 * @param agentMap - Map pre-carregado de agentes (opcional, para batch)
 * @returns Nome do agente ou "Desconhecido"
 *
 * @example
 * // Uso simples
 * const name = await resolveAgentName('uuid-agent');
 *
 * // Uso em batch (mais eficiente)
 * const agents = await supabase.from('agents').select('id, name');
 * const agentMap = new Map(agents.map(a => [a.id, a.name]));
 * const name = await resolveAgentName('uuid-agent', agentMap);
 */
export async function resolveAgentName(
  agentId: string,
  agentMap?: Map<string, string>
): Promise<string> {
  if (!agentId) return DEFAULT_NAME;

  // Se temos um Map pre-carregado, usar direto
  if (agentMap) {
    return agentMap.get(agentId) || DEFAULT_NAME;
  }

  // Buscar do banco
  try {
    const { data } = await supabaseAdmin
      .from('agents')
      .select('name')
      .eq('id', agentId)
      .maybeSingle();

    return data?.name || DEFAULT_NAME;
  } catch (error: any) {
    console.error(`[Resolver] Erro ao resolver agente ${agentId}: ${error.message}`);
    return DEFAULT_NAME;
  }
}

// ============================================================================
// PHONE FORMATTER
// ============================================================================

/**
 * Formata numero de telefone para exibicao
 *
 * @param phone - Telefone no formato WhatsApp (ex: "5511999999999@s.whatsapp.net")
 * @returns Telefone formatado ou "Desconhecido" se vazio
 *
 * @example
 * formatPhoneDisplay('5511999999999@s.whatsapp.net')
 * // Retorna: "(11) 99999-9999"
 */
export function formatPhoneDisplay(phone: string | null | undefined): string {
  if (!phone) return DEFAULT_NAME;

  const cleanPhone = phone
    .replace('@s.whatsapp.net', '')
    .replace(/\D/g, '');

  // Formato brasileiro: 55 + DDD + numero
  if (cleanPhone.length === 13 && cleanPhone.startsWith('55')) {
    const ddd = cleanPhone.slice(2, 4);
    const part1 = cleanPhone.slice(4, 9);
    const part2 = cleanPhone.slice(9, 13);
    return `(${ddd}) ${part1}-${part2}`;
  }

  // Formato brasileiro sem codigo do pais
  if (cleanPhone.length === 11) {
    const ddd = cleanPhone.slice(0, 2);
    const part1 = cleanPhone.slice(2, 7);
    const part2 = cleanPhone.slice(7, 11);
    return `(${ddd}) ${part1}-${part2}`;
  }

  // Retorna como esta se nao reconhecer o formato
  return cleanPhone || DEFAULT_NAME;
}

// ============================================================================
// EXPORTS PARA INDEX
// ============================================================================

export { DEFAULT_NAME };
