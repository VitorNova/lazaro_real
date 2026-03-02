import { FastifyRequest, FastifyReply } from 'fastify';
import axios from 'axios';
import { AgentsRepository, agentsRepository } from '../../services/supabase/repositories/agents.repository';
import { supabaseAdmin } from '../../services/supabase/client';
import { UazapiClient, createUazapiClient } from '../../services/uazapi';
import { createEvolutionClient } from '../../services/evolution';
import {
  getCachedQRCode,
  isConnectionStale,
  forceInvalidateCache,
  getCacheDebugInfo,
} from '../../utils/qr-cache';
import { getWebhookUrlForAgent } from '../../utils/webhook.utils';
import { config } from '../../config';
import { WhatsAppProvider } from '../../services/supabase/types';

// ============================================================================
// LIMPEZA DE PROVEDOR ANTERIOR
// ============================================================================
// Quando um agente troca de provedor WhatsApp (UAZAPI → Evolution ou vice-versa),
// esta função limpa a configuração antiga e deleta a instância do provedor anterior.
// ============================================================================

interface CleanupResult {
  success: boolean;
  previousProvider?: WhatsAppProvider;
  deletedInstance?: string;
  error?: string;
}

/**
 * Limpa configuração do provedor anterior quando troca de provedor
 * @param agent - Dados do agente
 * @param newProvider - Novo provedor que será usado
 * @returns Resultado da limpeza
 */
async function cleanupPreviousProvider(
  agent: any,
  newProvider: WhatsAppProvider
): Promise<CleanupResult> {
  const cleanupLogger = {
    info: (msg: string, data?: unknown) => console.info(`[ProviderCleanup] ${msg}`, data ?? ''),
    warn: (msg: string, data?: unknown) => console.warn(`[ProviderCleanup] ${msg}`, data ?? ''),
    error: (msg: string, data?: unknown) => console.error(`[ProviderCleanup] ${msg}`, data ?? ''),
  };

  const currentProvider = agent.whatsapp_provider || 'uazapi';

  // Se está trocando para o mesmo provedor ou não tem provedor anterior configurado
  if (currentProvider === newProvider) {
    return { success: true };
  }

  cleanupLogger.info('Iniciando limpeza de provedor anterior', {
    agentId: agent.id,
    currentProvider,
    newProvider,
  });

  try {
    // ========================================================================
    // LIMPEZA UAZAPI → EVOLUTION
    // ========================================================================
    if (currentProvider === 'uazapi' && newProvider === 'evolution') {
      const uazapiInstanceId = agent.uazapi_instance_id;
      const uazapiToken = agent.uazapi_token;
      const uazapiBaseUrl = agent.uazapi_base_url;

      // Tentar deletar instância UAZAPI se existir
      if (uazapiInstanceId && uazapiToken && uazapiBaseUrl && !uazapiInstanceId.startsWith('CREATING:')) {
        cleanupLogger.info('Deletando instância UAZAPI', { instanceId: uazapiInstanceId });

        try {
          const uazapiClient = createUazapiClient({
            baseUrl: uazapiBaseUrl,
            instanceToken: uazapiToken,
          });

          // Tentar desconectar primeiro
          try {
            await uazapiClient.disconnect();
          } catch (disconnectError) {
            // Ignorar erro de desconexão
          }

          // Tentar deletar instância
          try {
            await uazapiClient.deleteInstance();
            cleanupLogger.info('Instância UAZAPI deletada com sucesso', { instanceId: uazapiInstanceId });
          } catch (deleteError) {
            cleanupLogger.warn('Não foi possível deletar instância UAZAPI (pode já não existir)', {
              instanceId: uazapiInstanceId,
              error: deleteError instanceof Error ? deleteError.message : deleteError,
            });
          }
        } catch (clientError) {
          cleanupLogger.warn('Erro ao criar cliente UAZAPI para limpeza', {
            error: clientError instanceof Error ? clientError.message : clientError,
          });
        }
      }

      // Limpar campos UAZAPI no banco
      await supabaseAdmin
        .from('agents')
        .update({
          uazapi_instance_id: null,
          uazapi_token: null,
          uazapi_base_url: null,
          uazapi_connected: false,
        })
        .eq('id', agent.id);

      cleanupLogger.info('Campos UAZAPI limpos no banco', { agentId: agent.id });

      return {
        success: true,
        previousProvider: 'uazapi',
        deletedInstance: uazapiInstanceId || undefined,
      };
    }

    // ========================================================================
    // LIMPEZA EVOLUTION → UAZAPI
    // ========================================================================
    if (currentProvider === 'evolution' && newProvider === 'uazapi') {
      const evolutionInstanceName = agent.evolution_instance_name;
      const evolutionBaseUrl = agent.evolution_base_url;
      const evolutionApiKey = agent.evolution_api_key;

      // Tentar deletar instância Evolution se existir
      if (evolutionInstanceName && evolutionBaseUrl && evolutionApiKey) {
        cleanupLogger.info('Deletando instância Evolution', { instanceName: evolutionInstanceName });

        try {
          const evolutionClient = createEvolutionClient({
            baseUrl: evolutionBaseUrl,
            apiKey: evolutionApiKey,
            instanceName: evolutionInstanceName,
          });

          // Tentar fazer logout primeiro
          try {
            await evolutionClient.logout(evolutionInstanceName);
          } catch (logoutError) {
            // Ignorar erro de logout
          }

          // Deletar instância
          try {
            await evolutionClient.deleteInstance(evolutionInstanceName);
            cleanupLogger.info('Instância Evolution deletada com sucesso', { instanceName: evolutionInstanceName });
          } catch (deleteError) {
            cleanupLogger.warn('Não foi possível deletar instância Evolution (pode já não existir)', {
              instanceName: evolutionInstanceName,
              error: deleteError instanceof Error ? deleteError.message : deleteError,
            });
          }
        } catch (clientError) {
          cleanupLogger.warn('Erro ao criar cliente Evolution para limpeza', {
            error: clientError instanceof Error ? clientError.message : clientError,
          });
        }
      }

      // Limpar campos Evolution no banco
      await supabaseAdmin
        .from('agents')
        .update({
          evolution_instance_name: null,
          evolution_base_url: null,
          evolution_api_key: null,
          evolution_connected: false,
        })
        .eq('id', agent.id);

      cleanupLogger.info('Campos Evolution limpos no banco', { agentId: agent.id });

      return {
        success: true,
        previousProvider: 'evolution',
        deletedInstance: evolutionInstanceName || undefined,
      };
    }

    return { success: true };

  } catch (error) {
    cleanupLogger.error('Erro durante limpeza de provedor', {
      agentId: agent.id,
      error: error instanceof Error ? error.message : error,
    });

    return {
      success: false,
      error: error instanceof Error ? error.message : 'Unknown error',
    };
  }
}

// ============================================================================
// LOCK ATÔMICO NO BANCO DE DADOS - "PAREDE" CONTRA DUPLICAÇÃO (v2)
// ============================================================================
//
// Estratégia com verificação dupla e requestId único:
// 1. SELECT para ver estado atual
// 2. Se tem lock ativo não expirado → 429
// 3. Se tem instância real → usar existente
// 4. Se livre → UPDATE com requestId único → SELECT para confirmar
// 5. Se confirmado → lock adquirido
//
// ============================================================================

import { randomUUID } from 'crypto';

const LOCK_PREFIX = 'CREATING:';
const LOCK_TIMEOUT_MS = 45000; // 45 segundos

/**
 * Verifica se uma instância está em processo de criação (lock ativo)
 */
function isCreatingLock(instanceId: string | null | undefined): boolean {
  return !!instanceId && instanceId.startsWith(LOCK_PREFIX);
}

/**
 * Extrai timestamp do lock
 */
function getLockTimestamp(instanceId: string): number {
  // Formato: CREATING:{timestamp}:{requestId}
  const parts = instanceId.replace(LOCK_PREFIX, '').split(':');
  return parseInt(parts[0], 10) || 0;
}

/**
 * Verifica se o lock expirou
 */
function isLockExpired(instanceId: string | null | undefined): boolean {
  if (!instanceId || !instanceId.startsWith(LOCK_PREFIX)) {
    return false;
  }
  const timestamp = getLockTimestamp(instanceId);
  if (isNaN(timestamp)) return true;
  return (Date.now() - timestamp) > LOCK_TIMEOUT_MS;
}

/**
 * Gera valor único do lock com timestamp E requestId
 */
function generateLockValue(): string {
  const requestId = randomUUID().split('-')[0]; // Só primeiros 8 chars
  return `${LOCK_PREFIX}${Date.now()}:${requestId}`;
}

/**
 * Tenta adquirir lock no banco de dados com verificação dupla
 */
async function tryAcquireDatabaseLock(agentId: string): Promise<{
  acquired: boolean;
  existingInstanceId?: string;
  existingToken?: string;
  baseUrl?: string;
}> {
  const logger = {
    info: (msg: string, data?: unknown) => console.info(`[LockDB] ${msg}`, data ?? ''),
    warn: (msg: string, data?: unknown) => console.warn(`[LockDB] ${msg}`, data ?? ''),
  };

  // PASSO 1: Verificar estado atual
  const { data: currentAgent, error: selectError } = await supabaseAdmin
    .from('agents')
    .select('uazapi_instance_id, uazapi_token, uazapi_base_url')
    .eq('id', agentId)
    .single();

  if (selectError) {
    logger.warn('Erro ao buscar agente', { agentId, error: selectError.message });
    return { acquired: false };
  }

  const currentInstanceId = currentAgent?.uazapi_instance_id;

  // PASSO 2: Se já tem instância REAL (não é lock), usar existente
  if (currentInstanceId && !isCreatingLock(currentInstanceId)) {
    logger.info('Instância real já existe', { agentId, instanceId: currentInstanceId });
    return {
      acquired: false,
      existingInstanceId: currentInstanceId,
      existingToken: currentAgent.uazapi_token,
      baseUrl: currentAgent.uazapi_base_url
    };
  }

  // PASSO 3: Se tem lock ATIVO (não expirado), bloquear
  if (currentInstanceId && isCreatingLock(currentInstanceId) && !isLockExpired(currentInstanceId)) {
    logger.warn('Lock ativo de outra requisição', { agentId, lockValue: currentInstanceId });
    return { acquired: false };
  }

  // PASSO 4: Tentar adquirir lock com valor único
  const myLockValue = generateLockValue();
  logger.info('Tentando adquirir lock', { agentId, myLockValue });

  await supabaseAdmin
    .from('agents')
    .update({ uazapi_instance_id: myLockValue })
    .eq('id', agentId);

  // PASSO 5: Verificar se FOI NOSSO LOCK que ficou (verificação dupla)
  // Pequeno delay para garantir consistência
  await new Promise(resolve => setTimeout(resolve, 100));

  const { data: verifyAgent } = await supabaseAdmin
    .from('agents')
    .select('uazapi_instance_id')
    .eq('id', agentId)
    .single();

  if (verifyAgent?.uazapi_instance_id === myLockValue) {
    logger.info('✅ Lock adquirido com sucesso!', { agentId, myLockValue });
    return { acquired: true };
  } else {
    logger.warn('❌ Lock perdido para outra requisição', {
      agentId,
      myLockValue,
      actualValue: verifyAgent?.uazapi_instance_id
    });
    return { acquired: false };
  }
}

/**
 * Libera o lock no banco (usado em caso de erro)
 */
async function releaseDatabaseLock(agentId: string): Promise<void> {
  console.info('[LockDB] Liberando lock', { agentId });
  await supabaseAdmin
    .from('agents')
    .update({ uazapi_instance_id: null })
    .eq('id', agentId)
    .like('uazapi_instance_id', `${LOCK_PREFIX}%`);
}

// ============================================================================
// TYPES
// ============================================================================

interface QRCodeParams {
  id: string;
}

interface QRCodeQuerystring {
  provider?: WhatsAppProvider;
}

interface QRCodeResponse {
  status: 'pending' | 'connected' | 'initializing' | 'error';
  qr_code?: string;
  qr_code_url?: string;
  phone_number?: string;
  retry_after?: number;
  error?: string;
}

interface ConnectionResponse {
  connected: boolean;
  phone_number?: string;
  instance_status: string;
  instance_name?: string;
}

interface UazapiQRResponse {
  qrcode?: string;
  base64?: string;
  code?: string;
  pairingCode?: string;
}

interface UazapiConnectionResponse {
  instance?: {
    instanceName: string;
    state: 'open' | 'close' | 'connecting';
    profilePictureUrl?: string;
    phoneNumber?: string;
  };
  state?: string;
}

// ============================================================================
// LOGGER
// ============================================================================

const logger = {
  info: (msg: string, data?: unknown) => console.info(`[QRCode] ${msg}`, data ?? ''),
  warn: (msg: string, data?: unknown) => console.warn(`[QRCode] ${msg}`, data ?? ''),
  error: (msg: string, data?: unknown) => console.error(`[QRCode] ${msg}`, data ?? ''),
  debug: (msg: string, data?: unknown) => console.debug(`[QRCode] ${msg}`, data ?? ''),
};

// ============================================================================
// EVOLUTION QR CODE HANDLER (internal)
// ============================================================================

async function handleEvolutionQRCode(
  agent: any,
  agentId: string,
  reply: FastifyReply
): Promise<FastifyReply> {
  const evolutionConfig = agent as any;

  logger.info('Handling Evolution QR code', { agentId });

  // ========================================================================
  // LIMPEZA: Se o agente estava usando UAZAPI, limpar configuração anterior
  // ========================================================================
  if (agent.whatsapp_provider === 'uazapi' || (agent.uazapi_instance_id && !agent.evolution_instance_name)) {
    logger.info('Detectada troca de provedor UAZAPI → Evolution, limpando configuração anterior', { agentId });
    const cleanupResult = await cleanupPreviousProvider(agent, 'evolution');
    if (cleanupResult.deletedInstance) {
      logger.info('Instância UAZAPI anterior removida', { deletedInstance: cleanupResult.deletedInstance });
    }
  }

  // Verificar se tem credenciais Evolution configuradas
  let evolutionBaseUrl = evolutionConfig.evolution_base_url;
  let evolutionApiKey = evolutionConfig.evolution_api_key;
  let evolutionInstanceName = evolutionConfig.evolution_instance_name;

  // Se não tem credenciais, usar as globais do config
  if (!evolutionBaseUrl || !evolutionApiKey) {
    evolutionBaseUrl = process.env.EVOLUTION_BASE_URL || '';
    evolutionApiKey = process.env.EVOLUTION_API_KEY || '';

    if (!evolutionBaseUrl || !evolutionApiKey) {
      logger.error('Evolution API credentials not configured');
      return reply.status(500).send({
        status: 'error',
        error: 'Evolution API not configured on server',
      } as QRCodeResponse);
    }
  }

  const client = createEvolutionClient({
    baseUrl: evolutionBaseUrl,
    apiKey: evolutionApiKey,
    instanceName: evolutionInstanceName || undefined,
  });

  try {
    // Se já tem instância, verificar status
    if (evolutionInstanceName) {
      try {
        const status = await client.getConnectionState(evolutionInstanceName);
        logger.info('Evolution instance status', { instanceName: evolutionInstanceName, state: status.instance?.state });

        if (status.instance?.state === 'open') {
          // Já está conectado
          await agentsRepository.update(agentId, { evolution_connected: true } as any);
          return reply.status(200).send({
            status: 'connected',
            phone_number: status.instance?.owner || '',
          } as QRCodeResponse);
        }

        // Precisa de QR code - gerar
        const qrResponse = await client.connect(evolutionInstanceName);

        if (qrResponse.base64 || qrResponse.code) {
          return reply.status(200).send({
            status: 'pending',
            qr_code: qrResponse.base64 || qrResponse.code,
            qr_code_url: `/api/agents/${agentId}/qr/image`,
          } as QRCodeResponse);
        }

        return reply.status(200).send({
          status: 'initializing',
          retry_after: 3,
        } as QRCodeResponse);

      } catch (statusError) {
        logger.warn('Error checking Evolution instance, will try to create new', {
          error: statusError instanceof Error ? statusError.message : statusError
        });
        // Instância pode não existir, continuar para criar
      }
    }

    // Criar nova instância Evolution
    const shortId = agentId.split('-')[0];
    const instanceName = `Agent_${shortId}`;
    const webhookUrl = `${process.env.WEBHOOK_BASE_URL || process.env.API_BASE_URL || 'https://ia.phant.com.br'}/webhooks/dynamic`;

    logger.info('Creating new Evolution instance', { instanceName, webhookUrl });

    try {
      const createResult = await client.createInstance({
        instanceName,
        qrcode: true,
        integration: 'WHATSAPP-BAILEYS',
        webhook: webhookUrl,
        webhookByEvents: false,
        webhookBase64: false,
        webhookEvents: ['MESSAGES_UPSERT', 'MESSAGES_UPDATE', 'CONNECTION_UPDATE', 'QRCODE_UPDATED'],
      });

      // Salvar dados da instância
      await agentsRepository.update(agentId, {
        whatsapp_provider: 'evolution',
        evolution_base_url: evolutionBaseUrl,
        evolution_api_key: evolutionApiKey,
        evolution_instance_name: instanceName,
        evolution_connected: false,
      } as any);

      logger.info('Evolution instance created', { instanceName, hasQR: !!createResult.qrcode });

      if (createResult.qrcode?.base64 || createResult.qrcode?.code) {
        return reply.status(200).send({
          status: 'pending',
          qr_code: createResult.qrcode.base64 || createResult.qrcode.code,
          qr_code_url: `/api/agents/${agentId}/qr/image`,
        } as QRCodeResponse);
      }

      return reply.status(200).send({
        status: 'initializing',
        retry_after: 3,
      } as QRCodeResponse);

    } catch (createError) {
      const errorMessage = createError instanceof Error ? createError.message : String(createError);
      logger.error('Error creating Evolution instance', { error: errorMessage });

      // Se instância já existe, tentar usar
      if (errorMessage.includes('already') || errorMessage.includes('exists')) {
        // Atualizar nome e tentar gerar QR
        await agentsRepository.update(agentId, {
          whatsapp_provider: 'evolution',
          evolution_base_url: evolutionBaseUrl,
          evolution_api_key: evolutionApiKey,
          evolution_instance_name: instanceName,
          evolution_connected: false,
        } as any);

        const qrResponse = await client.connect(instanceName);

        if (qrResponse.base64 || qrResponse.code) {
          return reply.status(200).send({
            status: 'pending',
            qr_code: qrResponse.base64 || qrResponse.code,
            qr_code_url: `/api/agents/${agentId}/qr/image`,
          } as QRCodeResponse);
        }
      }

      return reply.status(500).send({
        status: 'error',
        error: 'Failed to create Evolution instance: ' + errorMessage,
      } as QRCodeResponse);
    }

  } catch (error) {
    logger.error('Error in Evolution QR handler', {
      error: error instanceof Error ? error.message : error,
    });

    return reply.status(500).send({
      status: 'error',
      error: error instanceof Error ? error.message : 'Evolution API error',
    } as QRCodeResponse);
  }
}

// ============================================================================
// GET QR CODE HANDLER
// ============================================================================

export async function getQRCodeHandler(
  request: FastifyRequest<{ Params: QRCodeParams; Querystring: QRCodeQuerystring }>,
  reply: FastifyReply
): Promise<FastifyReply> {
  try {
    const { id: agentId } = request.params;
    const { provider: requestedProvider } = request.query;

    // ========================================================================
    // 1. BUSCAR AGENT NO BANCO
    // ========================================================================

    const agent = await agentsRepository.findById(agentId);

    if (!agent) {
      return reply.status(404).send({
        status: 'error',
        error: 'Agent not found',
      } as QRCodeResponse);
    }

    // Determinar provider (do agente ou da query)
    const provider: WhatsAppProvider = requestedProvider || agent.whatsapp_provider || 'uazapi';

    logger.info('Provider determination', {
      agentId,
      requestedProvider,
      agentProvider: agent.whatsapp_provider,
      finalProvider: provider
    });

    // ========================================================================
    // EVOLUTION API
    // ========================================================================
    if (provider === 'evolution') {
      return handleEvolutionQRCode(agent, agentId, reply);
    }

    // ========================================================================
    // UAZAPI (default)
    // ========================================================================
    let instanceId = agent.uazapi_instance_id;
    let baseUrl = agent.uazapi_base_url;
    let token = agent.uazapi_token;
    const isConnected = agent.uazapi_connected;

    // 🧱 [PAREDE] Se instanceId começa com 'CREATING:', tratar como se não existisse
    // Isso significa que outra requisição está criando a instância
    if (instanceId && isCreatingLock(instanceId)) {
      if (isLockExpired(instanceId)) {
        logger.warn('🧱 [PAREDE] Lock expirado encontrado, será limpo', { agentId, instanceId });
        instanceId = null as unknown as string;
        token = null as unknown as string;
      } else {
        logger.warn('🧱 [PAREDE] Lock ativo encontrado, outra requisição está criando', { agentId, instanceId });
        return reply.status(429).send({
          status: 'pending',
          error: 'Criação de instância em andamento. Aguarde alguns segundos.',
          retry_after: 3,
        } as QRCodeResponse);
      }
    }

    logger.info('Getting QR code for agent', { agentId, instanceId, provider: 'uazapi' });

    // ========================================================================
    // 2. VERIFICAR SE JA ESTA CONECTADO
    // ========================================================================

    if (isConnected) {
      try {
        if (baseUrl) {
          const uazapiClient = createUazapiClient({
            baseUrl,
            instanceToken: token || '',
          });

          const status = await uazapiClient.getConnectionStatus();

          // IMPORTANTE: Verificar loggedIn, não apenas connected
          // UAZAPI retorna connected=true mesmo quando está apenas "connecting" (gerando QR)
          // Só está realmente conectado quando loggedIn=true ou status='open'
          if (status.loggedIn || (status.connected && status.status === 'open')) {
            return reply.status(200).send({
              status: 'connected',
              phone_number: status.phone_number || '',
            } as QRCodeResponse);
          }

          await agentsRepository.update(agentId, { uazapi_connected: false });
        }
      } catch (error) {
        logger.warn('Error checking connection status', {
          error: error instanceof Error ? error.message : error,
        });
      }
    }

    // ========================================================================
    // 3. VALIDAR INSTANCIA UAZAPI EXISTENTE (se houver)
    // ========================================================================

    // Se tem instancia UAZAPI configurada, verificar se ainda é válida
    if (instanceId && baseUrl && token) {
      logger.info('Validating existing UAZAPI instance...', { instanceId, token: token.substring(0, 8) + '...' });

      try {
        const testClient = createUazapiClient({
          baseUrl,
          instanceToken: token,
        });

        // Tentar obter info da instância para validar token
        // NOTA: getInstanceInfo() agora usa POST /instance/connect e:
        // - Retorna null APENAS para 404/401/403 (instância realmente não existe)
        // - Lança exceção para erros de rede/timeout (evita recriação acidental)
        const instanceInfo = await testClient.getInstanceInfo();

        if (!instanceInfo) {
          // getInstanceInfo() retornou null = instância confirmadamente não existe (404/401/403)
          logger.warn('Instance confirmed as non-existent (getInstanceInfo returned null)');

          // Limpar dados da instância inválida para forçar criação de nova
          instanceId = null as unknown as string;
          token = null as unknown as string;

          // Atualizar banco para limpar dados inválidos
          await agentsRepository.update(agentId, {
            uazapi_instance_id: null,
            uazapi_token: null,
            uazapi_connected: false,
          });
        } else {
          logger.info('UAZAPI instance is valid', { instanceId, status: instanceInfo.status });
        }
      } catch (validationError) {
        // getInstanceInfo() lançou exceção = erro de rede/timeout
        // NÃO limpar a instância! Pode ser problema temporário de conectividade
        const errorMessage = validationError instanceof Error ? validationError.message : String(validationError);

        logger.warn('Error validating instance (network/timeout - keeping existing instance)', {
          instanceId,
          error: errorMessage
        });

        // IMPORTANTE: Manter instanceId e token como estão
        // Isso evita duplicação por erro de rede
        // A instância pode estar funcionando, apenas a verificação falhou
      }
    }

    // ========================================================================
    // 4. GERAR QR CODE (criar instancia se necessario)
    // ========================================================================

    // Se nao tem instancia configurada, criar uma nova
    // ========================================================================
    // PAREDE: LOCK ATÔMICO NO BANCO DE DADOS
    // ========================================================================
    if (!instanceId || !baseUrl || !token) {
      logger.info('🧱 [PAREDE] Iniciando processo de criação de instância UAZAPI', { agentId });

      // ========================================================================
      // LIMPEZA: Se o agente estava usando Evolution, limpar configuração anterior
      // ========================================================================
      const agentConfig = agent as any;
      if (agentConfig.whatsapp_provider === 'evolution' || agentConfig.evolution_instance_name) {
        logger.info('Detectada troca de provedor Evolution → UAZAPI, limpando configuração anterior', { agentId });
        const cleanupResult = await cleanupPreviousProvider(agent, 'uazapi');
        if (cleanupResult.deletedInstance) {
          logger.info('Instância Evolution anterior removida', { deletedInstance: cleanupResult.deletedInstance });
        }
      }

      // PASSO 1: Tentar adquirir lock ATÔMICO no banco de dados
      const lockResult = await tryAcquireDatabaseLock(agentId);

      if (!lockResult.acquired) {
        // Lock não adquirido - verificar se já existe instância real
        if (lockResult.existingInstanceId && lockResult.existingToken) {
          logger.info('🧱 [PAREDE] Instância já existe, usando existente', {
            agentId,
            instanceId: lockResult.existingInstanceId
          });
          instanceId = lockResult.existingInstanceId;
          token = lockResult.existingToken;
          baseUrl = config.uazapi.baseUrl || process.env.UAZAPI_BASE_URL || '';
        } else {
          // Outra requisição está criando - retornar 429
          logger.warn('🧱 [PAREDE] BLOQUEADO - Criação já em andamento por outra requisição', { agentId });
          return reply.status(429).send({
            status: 'pending',
            error: 'Criação de instância já em andamento. Aguarde alguns segundos.',
            retry_after: 5,
          } as QRCodeResponse);
        }
      } else {
        // PASSO 2: Lock adquirido! Agora criar a instância
        logger.info('🧱 [PAREDE] Lock adquirido no banco, criando instância...', { agentId });

        try {
          const uazapiBaseUrl = config.uazapi.baseUrl || process.env.UAZAPI_BASE_URL || '';
          const uazapiAdminToken = config.uazapi.adminToken || process.env.UAZAPI_ADMIN_TOKEN || '';

          if (!uazapiBaseUrl || !uazapiAdminToken) {
            logger.error('🧱 [PAREDE] UAZAPI credentials not configured');
            await releaseDatabaseLock(agentId);
            return reply.status(500).send({
              status: 'error',
              error: 'UAZAPI not configured on server',
            } as QRCodeResponse);
          }

          const uazapiClient = createUazapiClient({
            baseUrl: uazapiBaseUrl,
            adminToken: uazapiAdminToken,
          });

          // Gerar nome da instancia baseado no ID do agente
          const shortId = agentId.split('-')[0];
          const instanceName = `Agent_${shortId}`;

          // Usar função centralizada para determinar URL de webhook (respeita Leadbox)
          const webhookUrl = getWebhookUrlForAgent(agent);

          logger.info('🧱 [PAREDE] Chamando UAZAPI para criar instância', { instanceName, webhookUrl });

          // PASSO 3: Criar instancia na UAZAPI
          const instanceResponse = await uazapiClient.createInstanceWithWebhook(
            instanceName,
            webhookUrl,
            ['messages', 'connection']
          );

          const newInstanceId = instanceResponse.instance.id;
          const newToken = instanceResponse.token;

          logger.info('🧱 [PAREDE] Instância criada na UAZAPI com sucesso', {
            instanceId: newInstanceId,
            hasToken: !!newToken,
            webhookConfigured: instanceResponse.webhookConfigured,
          });

          // PASSO 4: Atualizar banco com dados reais (substitui o lock)
          await agentsRepository.update(agentId, {
            whatsapp_provider: 'uazapi',
            uazapi_instance_id: newInstanceId,  // Substitui 'CREATING:xxx' pelo ID real
            uazapi_base_url: uazapiBaseUrl,
            uazapi_token: newToken,
            uazapi_connected: false,
          });

          // Atualizar variaveis locais
          instanceId = newInstanceId;
          baseUrl = uazapiBaseUrl;
          token = newToken;

          logger.info('🧱 [PAREDE] ✅ Processo completo - instância salva no banco', {
            agentId,
            instanceId: newInstanceId
          });

        } catch (createError) {
          // ERRO: Liberar lock no banco
          logger.error('🧱 [PAREDE] ❌ Erro ao criar instância, liberando lock', {
            agentId,
            error: createError instanceof Error ? createError.message : String(createError)
          });
          await releaseDatabaseLock(agentId);

          const errorMessage = createError instanceof Error ? createError.message : String(createError);

          if (errorMessage.includes('Maximum number of instances') || errorMessage.includes('429')) {
            return reply.status(503).send({
              status: 'error',
              error: 'Limite de instancias UAZAPI atingido. Delete agentes antigos para liberar espaco.',
            } as QRCodeResponse);
          }

          return reply.status(500).send({
            status: 'error',
            error: 'Falha ao criar instancia UAZAPI: ' + errorMessage,
          } as QRCodeResponse);
        }
      }
    }

    // Se ainda nao tem instancia, retornar erro
    if (!instanceId || !baseUrl) {
      return reply.status(400).send({
        status: 'error',
        error: 'Agent WhatsApp instance not configured',
      } as QRCodeResponse);
    }

    try {
      {
        // UazapiGo

        // Primeiro, verificar se temos QR code no cache (vindo do webhook)
        if (token) {
          // Debug: logar informações do cache
          const debugInfo = getCacheDebugInfo(token);
          if (debugInfo?.exists) {
            logger.debug('Cache debug info', {
              agentId,
              status: debugInfo.status,
              ageMs: debugInfo.ageMs,
              connectingDurationMs: debugInfo.connectingDurationMs,
              qrRefreshCount: debugInfo.qrRefreshCount,
              isStale: debugInfo.isStale,
            });
          }

          // Verificar se a conexão está estagnada ANTES de usar o cache
          if (isConnectionStale(token)) {
            logger.warn('⚠️ Stale connection detected, invalidating cache', { agentId });
            forceInvalidateCache(token);

            // Retornar initializing para forçar nova tentativa
            return reply.status(200).send({
              status: 'initializing',
              retry_after: 3,
              error: 'Conexão estava travada. Tentando reconectar...',
            } as QRCodeResponse);
          }

          const cachedQR = getCachedQRCode(token);

          if (cachedQR) {
            logger.debug('Found cached QR code', { status: cachedQR.status });

            // Se o cache retornou 'disconnected', significa que detectou conexão estagnada
            if (cachedQR.status === 'disconnected') {
              logger.warn('Cache returned disconnected status (stale detection)', { agentId });
              forceInvalidateCache(token);

              return reply.status(200).send({
                status: 'initializing',
                retry_after: 3,
                error: 'Reconectando instância...',
              } as QRCodeResponse);
            }

            if (cachedQR.status === 'connected') {
              await agentsRepository.update(agentId, { uazapi_connected: true });
              return reply.status(200).send({
                status: 'connected',
                phone_number: '',
              } as QRCodeResponse);
            }

            if (cachedQR.qrcode) {
              logger.info('Returning cached QR code (UazapiGo)', { agentId });
              return reply.status(200).send({
                status: 'pending',
                qr_code: cachedQR.qrcode,
                qr_code_url: `/api/agents/${agentId}/qr/image`,
              } as QRCodeResponse);
            }
          }
        }

        // Se não tem cache, tentar via API
        const uazapiClient = createUazapiClient({
          baseUrl,
          instanceToken: token || '',
        });

        const qrResult = await uazapiClient.getQRCode();

        if (qrResult?.status === 'connected') {
          await agentsRepository.update(agentId, { uazapi_connected: true });
          return reply.status(200).send({
            status: 'connected',
            phone_number: '',
          } as QRCodeResponse);
        }

        if (qrResult?.qr_code || qrResult?.base64) {
          logger.info('QR code generated (UazapiGo)', { agentId });

          return reply.status(200).send({
            status: 'pending',
            qr_code: qrResult.base64 || qrResult.qr_code,
            qr_code_url: `/api/agents/${agentId}/qr/image`,
          } as QRCodeResponse);
        }

        return reply.status(200).send({
          status: 'initializing',
          retry_after: 5,
        } as QRCodeResponse);
      }

    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status === 400) {
        // Pode significar que esta conectado
        try {
          if (baseUrl) {
            const uazapiClient = createUazapiClient({
              baseUrl,
              instanceToken: token || '',
            });

            const status = await uazapiClient.getConnectionStatus();

            if (status.connected) {
              await agentsRepository.update(agentId, { uazapi_connected: true });
              return reply.status(200).send({
                status: 'connected',
                phone_number: status.phone_number || '',
              } as QRCodeResponse);
            }
          }
        } catch {
          // Ignorar erro secundario
        }
      }

      logger.error('Error getting QR code', {
        status: axios.isAxiosError(error) ? error.response?.status : undefined,
        data: axios.isAxiosError(error) ? error.response?.data : undefined,
      });

      return reply.status(200).send({
        status: 'initializing',
        retry_after: 5,
      } as QRCodeResponse);
    }

  } catch (error) {
    logger.error('Error in getQRCodeHandler', {
      error: error instanceof Error ? error.message : error,
    });

    return reply.status(500).send({
      status: 'error',
      error: error instanceof Error ? error.message : 'Internal server error',
    } as QRCodeResponse);
  }
}

// ============================================================================
// CHECK CONNECTION HANDLER
// ============================================================================

export async function checkConnectionHandler(
  request: FastifyRequest<{ Params: QRCodeParams }>,
  reply: FastifyReply
): Promise<FastifyReply> {
  try {
    const { id: agentId } = request.params;

    // ========================================================================
    // 1. BUSCAR AGENT NO BANCO
    // ========================================================================

    const agent = await agentsRepository.findById(agentId);

    if (!agent) {
      return reply.status(404).send({
        connected: false,
        instance_status: 'not_found',
      } as ConnectionResponse);
    }

    // Determinar provider
    const provider: WhatsAppProvider = agent.whatsapp_provider || 'uazapi';

    logger.debug('Checking connection for agent', { agentId, provider });

    // ========================================================================
    // EVOLUTION API
    // ========================================================================
    if (provider === 'evolution') {
      const evolutionConfig = agent as any;
      const evolutionInstanceName = evolutionConfig.evolution_instance_name;
      const evolutionBaseUrl = evolutionConfig.evolution_base_url;
      const evolutionApiKey = evolutionConfig.evolution_api_key;

      if (!evolutionInstanceName || !evolutionBaseUrl || !evolutionApiKey) {
        return reply.status(200).send({
          connected: false,
          instance_status: 'not_configured',
        } as ConnectionResponse);
      }

      try {
        const client = createEvolutionClient({
          baseUrl: evolutionBaseUrl,
          apiKey: evolutionApiKey,
          instanceName: evolutionInstanceName,
        });

        const status = await client.getConnectionState(evolutionInstanceName);
        const isConnected = status.instance?.state === 'open';

        if (isConnected !== evolutionConfig.evolution_connected) {
          await agentsRepository.update(agentId, { evolution_connected: isConnected } as any);
        }

        return reply.status(200).send({
          connected: isConnected,
          phone_number: status.instance?.owner || '',
          instance_status: status.instance?.state || 'unknown',
          instance_name: evolutionInstanceName,
        } as ConnectionResponse);

      } catch (error) {
        logger.error('Error checking Evolution connection', {
          error: error instanceof Error ? error.message : error
        });
        return reply.status(200).send({
          connected: false,
          instance_status: 'error',
        } as ConnectionResponse);
      }
    }

    // ========================================================================
    // UAZAPI (default)
    // ========================================================================
    const instanceId = agent.uazapi_instance_id;
    const baseUrl = agent.uazapi_base_url;
    const token = agent.uazapi_token;

    // ========================================================================
    // 2. VERIFICAR STATUS DA CONEXAO
    // ========================================================================

    if (!instanceId || !baseUrl) {
      return reply.status(200).send({
        connected: false,
        instance_status: 'not_configured',
      } as ConnectionResponse);
    }

    try {
      let isConnectedResult = false;
      let phoneNumber = '';
      let instanceState = 'unknown';

      // UazapiGo - Primeiro, verificar o cache (webhook é fonte mais confiável)
      if (token) {
        // Verificar se a conexão está estagnada
        if (isConnectionStale(token)) {
          logger.warn('⚠️ Stale connection detected in checkConnection', { agentId });
          forceInvalidateCache(token);
          instanceState = 'stale';
        }

        const cachedStatus = getCachedQRCode(token);
        if (cachedStatus) {
          logger.debug('Using cached connection status', { status: cachedStatus.status });

          // Se retornou 'disconnected' pode ser stale detection
          if (cachedStatus.status === 'disconnected') {
            instanceState = 'disconnected';
            isConnectedResult = false;
          } else {
            isConnectedResult = cachedStatus.status === 'connected';
            instanceState = cachedStatus.status;
          }

          // Se o cache diz conectado, confiar nisso
          if (isConnectedResult) {
            phoneNumber = '';
            // Pular a chamada da API, usar o cache
          }
        }
      }

      // Fallback: Se não tem cache mas banco diz conectado, confiar no banco
      if (!isConnectedResult && agent.uazapi_connected) {
        logger.debug('Using database connection status (cache empty but DB says connected)');
        isConnectedResult = true;
        instanceState = 'connected';
      }

      // Se não temos status do cache ou banco, tentar API
      if (!isConnectedResult && instanceState !== 'connected') {
        try {
          const uazapiClient = createUazapiClient({
            baseUrl,
            instanceToken: token || '',
          });

          const status = await uazapiClient.getConnectionStatus();

          instanceState = status.status || 'unknown';
          // IMPORTANTE: Verificar loggedIn, não apenas connected
          // UAZAPI retorna connected=true mesmo quando está apenas "connecting" (gerando QR)
          isConnectedResult = status.loggedIn || (status.connected && status.status === 'open');
          phoneNumber = status.phone_number || '';
        } catch (apiError) {
          // Se a API falhar mas o banco disse conectado, manter conectado
          if (agent.uazapi_connected) {
            logger.debug('API failed but DB says connected, trusting DB');
            isConnectedResult = true;
            instanceState = 'connected';
          } else {
            logger.warn('API call failed, no cached status', {
              error: apiError instanceof Error ? apiError.message : apiError,
            });
          }
        }
      }

      // ========================================================================
      // 3. ATUALIZAR BANCO SE MUDOU
      // ========================================================================

      const previousConnected = agent.uazapi_connected;
      if (isConnectedResult !== previousConnected) {
        await agentsRepository.update(agentId, { uazapi_connected: isConnectedResult });
        logger.info('Connection status updated', { agentId, connected: isConnectedResult });
      }

      // ========================================================================
      // 4. RETORNAR STATUS
      // ========================================================================

      return reply.status(200).send({
        connected: isConnectedResult,
        phone_number: phoneNumber,
        instance_status: instanceState,
        instance_name: instanceId,
      } as ConnectionResponse);

    } catch (error) {
      logger.error('Error checking connection', {
        error: error instanceof Error ? error.message : error,
      });

      return reply.status(200).send({
        connected: false,
        instance_status: 'error',
      } as ConnectionResponse);
    }

  } catch (error) {
    logger.error('Error in checkConnectionHandler', {
      error: error instanceof Error ? error.message : error,
    });

    return reply.status(500).send({
      connected: false,
      instance_status: 'internal_error',
    } as ConnectionResponse);
  }
}

// ============================================================================
// GET QR CODE IMAGE HANDLER
// ============================================================================

export async function getQRCodeImageHandler(
  request: FastifyRequest<{ Params: QRCodeParams }>,
  reply: FastifyReply
): Promise<FastifyReply> {
  try {
    const { id: agentId } = request.params;

    const agent = await agentsRepository.findById(agentId);

    if (!agent) {
      return reply.status(404).send({ error: 'Agent not found' });
    }

    // Determinar provider
    const provider: WhatsAppProvider = agent.whatsapp_provider || 'uazapi';

    // ========================================================================
    // EVOLUTION API
    // ========================================================================
    if (provider === 'evolution') {
      const evolutionConfig = agent as any;
      const evolutionInstanceName = evolutionConfig.evolution_instance_name;
      const evolutionBaseUrl = evolutionConfig.evolution_base_url;
      const evolutionApiKey = evolutionConfig.evolution_api_key;

      if (!evolutionInstanceName || !evolutionBaseUrl || !evolutionApiKey) {
        return reply.status(400).send({ error: 'Evolution instance not configured' });
      }

      try {
        const client = createEvolutionClient({
          baseUrl: evolutionBaseUrl,
          apiKey: evolutionApiKey,
          instanceName: evolutionInstanceName,
        });

        const qrResponse = await client.connect(evolutionInstanceName);

        if (qrResponse.base64 || qrResponse.code) {
          const base64Data = qrResponse.base64 || qrResponse.code || '';
          const cleanBase64 = base64Data.replace(/^data:image\/\w+;base64,/, '');
          const imageBuffer = Buffer.from(cleanBase64, 'base64');

          return reply
            .header('Content-Type', 'image/png')
            .header('Cache-Control', 'no-cache, no-store, must-revalidate')
            .send(imageBuffer);
        }

        return reply.status(503).send({ error: 'QR code not available' });
      } catch (error) {
        logger.error('Error getting Evolution QR image', {
          error: error instanceof Error ? error.message : error
        });
        return reply.status(503).send({ error: 'QR code not available' });
      }
    }

    // ========================================================================
    // UAZAPI (default)
    // ========================================================================
    const instanceId = agent.uazapi_instance_id;
    const baseUrl = agent.uazapi_base_url;
    const token = agent.uazapi_token;

    if (!instanceId || !baseUrl) {
      return reply.status(400).send({ error: 'WhatsApp instance not configured' });
    }

    // Buscar QR como imagem
    try {
      const uazapiClient = createUazapiClient({
        baseUrl,
        instanceToken: token || '',
      });

      const qrResult = await uazapiClient.getQRCode();

      if (qrResult?.base64 || qrResult?.qr_code) {
        const base64Data = qrResult.base64 || qrResult.qr_code || '';
        const cleanBase64 = base64Data.replace(/^data:image\/\w+;base64,/, '');
        const imageBuffer = Buffer.from(cleanBase64, 'base64');

        return reply
          .header('Content-Type', 'image/png')
          .header('Cache-Control', 'no-cache, no-store, must-revalidate')
          .send(imageBuffer);
      }

      return reply.status(503).send({ error: 'QR code not available' });

    } catch (error) {
      logger.error('Error getting QR image', {
        error: error instanceof Error ? error.message : error,
      });

      return reply.status(503).send({ error: 'QR code not available' });
    }

  } catch (error) {
    logger.error('Error in getQRCodeImageHandler', {
      error: error instanceof Error ? error.message : error,
    });

    return reply.status(500).send({ error: 'Internal server error' });
  }
}

// ============================================================================
// DISCONNECT HANDLER
// ============================================================================

export async function disconnectHandler(
  request: FastifyRequest<{ Params: QRCodeParams }>,
  reply: FastifyReply
): Promise<FastifyReply> {
  try {
    const { id: agentId } = request.params;

    const agent = await agentsRepository.findById(agentId);

    if (!agent) {
      return reply.status(404).send({ success: false, error: 'Agent not found' });
    }

    // Determinar provider
    const provider: WhatsAppProvider = agent.whatsapp_provider || 'uazapi';

    // ========================================================================
    // EVOLUTION API
    // ========================================================================
    if (provider === 'evolution') {
      const evolutionConfig = agent as any;
      const evolutionInstanceName = evolutionConfig.evolution_instance_name;
      const evolutionBaseUrl = evolutionConfig.evolution_base_url;
      const evolutionApiKey = evolutionConfig.evolution_api_key;

      if (!evolutionInstanceName || !evolutionBaseUrl || !evolutionApiKey) {
        return reply.status(400).send({ success: false, error: 'Evolution instance not configured' });
      }

      try {
        const client = createEvolutionClient({
          baseUrl: evolutionBaseUrl,
          apiKey: evolutionApiKey,
          instanceName: evolutionInstanceName,
        });

        await client.logout(evolutionInstanceName);
        await agentsRepository.update(agentId, { evolution_connected: false } as any);

        logger.info('Agent disconnected from Evolution', { agentId });

        return reply.status(200).send({ success: true, message: 'Disconnected successfully' });
      } catch (error) {
        logger.error('Error disconnecting Evolution', {
          error: error instanceof Error ? error.message : error
        });
        await agentsRepository.update(agentId, { evolution_connected: false } as any);
        return reply.status(200).send({ success: true, message: 'Marked as disconnected' });
      }
    }

    // ========================================================================
    // UAZAPI (default)
    // ========================================================================
    const instanceId = agent.uazapi_instance_id;
    const baseUrl = agent.uazapi_base_url;
    const token = agent.uazapi_token;

    if (!instanceId || !baseUrl) {
      return reply.status(400).send({ success: false, error: 'WhatsApp instance not configured' });
    }

    try {
      const uazapiClient = createUazapiClient({
        baseUrl,
        instanceToken: token || '',
      });

      await uazapiClient.disconnect();
      await agentsRepository.update(agentId, { uazapi_connected: false });

      logger.info('Agent disconnected', { agentId, provider: 'uazapi' });

      return reply.status(200).send({ success: true, message: 'Disconnected successfully' });

    } catch (error) {
      logger.error('Error disconnecting', {
        error: error instanceof Error ? error.message : error,
      });

      // Mesmo com erro, marcar como desconectado
      await agentsRepository.update(agentId, { uazapi_connected: false });

      return reply.status(200).send({ success: true, message: 'Marked as disconnected' });
    }

  } catch (error) {
    logger.error('Error in disconnectHandler', {
      error: error instanceof Error ? error.message : error,
    });

    return reply.status(500).send({ success: false, error: 'Internal server error' });
  }
}
