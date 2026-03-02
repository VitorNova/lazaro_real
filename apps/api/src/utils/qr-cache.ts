/**
 * Cache otimizado para QR codes recebidos via webhook do UazapiGo
 *
 * Melhorias implementadas:
 * 1. TTL reduzido para 45s (QR codes UAZAPI expiram em ~60s)
 * 2. Detecção de conexão estagnada (>2 min em "connecting")
 * 3. Timestamp separado para início do estado "connecting"
 * 4. Método para invalidar QR codes expirados/estagnados
 */

interface QRCodeEntry {
  qrcode: string;
  timestamp: number;
  status: 'connecting' | 'connected' | 'disconnected';
  instanceName: string;
  /** Timestamp de quando entrou em "connecting" pela primeira vez */
  connectingStartedAt?: number;
  /** Contador de quantas vezes o QR foi atualizado enquanto "connecting" */
  qrRefreshCount?: number;
}

// Cache em memória
const qrCodeCache = new Map<string, QRCodeEntry>();

// ============================================================================
// CONFIGURAÇÕES DE TIMEOUT
// ============================================================================

/** TTL do cache de QR code - 45 segundos (UAZAPI expira em ~60s) */
const CACHE_TTL_MS = 45 * 1000;

/** Timeout máximo para estado "connecting" - 2 minutos */
const CONNECTING_TIMEOUT_MS = 2 * 60 * 1000;

/** Máximo de refreshes de QR antes de considerar estagnado */
const MAX_QR_REFRESH_COUNT = 5;

/**
 * Armazena QR code no cache
 * @param token Token da instância (chave única)
 * @param qrcode QR code em base64
 * @param instanceName Nome da instância
 * @param status Status da conexão
 */
export function cacheQRCode(
  token: string,
  qrcode: string,
  instanceName: string,
  status: 'connecting' | 'connected' | 'disconnected' = 'connecting'
): void {
  const existingEntry = qrCodeCache.get(token);
  const now = Date.now();

  // Rastrear tempo em "connecting" e contagem de refreshes
  let connectingStartedAt = existingEntry?.connectingStartedAt;
  let qrRefreshCount = existingEntry?.qrRefreshCount || 0;

  if (status === 'connecting') {
    // Se é novo "connecting" ou estava em outro estado, iniciar contador
    if (!connectingStartedAt || existingEntry?.status !== 'connecting') {
      connectingStartedAt = now;
      qrRefreshCount = 0;
    }

    // Se QR code mudou, incrementar contador de refresh
    if (existingEntry?.qrcode && existingEntry.qrcode !== qrcode) {
      qrRefreshCount++;
      console.log(`[QRCache] QR refreshed for ${instanceName.substring(0, 15)}... (refresh #${qrRefreshCount})`);
    }
  } else {
    // Se conectou ou desconectou, resetar contadores
    connectingStartedAt = undefined;
    qrRefreshCount = 0;
  }

  qrCodeCache.set(token, {
    qrcode,
    timestamp: now,
    status,
    instanceName,
    connectingStartedAt,
    qrRefreshCount,
  });

  console.log(`[QRCache] QR code cached for ${instanceName.substring(0, 15)}... (status: ${status})`);
}

/**
 * Obtém QR code do cache
 * @param token Token da instância
 * @returns QR code entry ou null se não existe, expirou, ou está estagnado
 */
export function getCachedQRCode(token: string): QRCodeEntry | null {
  const entry = qrCodeCache.get(token);

  if (!entry) {
    return null;
  }

  const now = Date.now();

  // Verificar TTL básico do cache
  if (now - entry.timestamp > CACHE_TTL_MS) {
    qrCodeCache.delete(token);
    console.log(`[QRCache] QR code expired (TTL) for ${entry.instanceName.substring(0, 15)}...`);
    return null;
  }

  // Se está em "connecting", verificar se não está estagnado
  if (entry.status === 'connecting') {
    // Verificar timeout de conexão (>2 min tentando conectar)
    if (entry.connectingStartedAt && (now - entry.connectingStartedAt > CONNECTING_TIMEOUT_MS)) {
      console.warn(`[QRCache] ⚠️ Connection STALE for ${entry.instanceName.substring(0, 15)}... (${Math.round((now - entry.connectingStartedAt) / 1000)}s in connecting)`);

      // Marcar como stale mas retornar para que o handler possa tomar ação
      return {
        ...entry,
        status: 'disconnected', // Sinalizar que precisa reconectar
      };
    }

    // Verificar se teve muitos refreshes de QR (sinal de problema)
    if (entry.qrRefreshCount && entry.qrRefreshCount >= MAX_QR_REFRESH_COUNT) {
      console.warn(`[QRCache] ⚠️ Too many QR refreshes for ${entry.instanceName.substring(0, 15)}... (${entry.qrRefreshCount} refreshes)`);

      // Retornar como stale
      return {
        ...entry,
        status: 'disconnected',
      };
    }
  }

  return entry;
}

/**
 * Verifica se uma conexão está estagnada (muito tempo em "connecting")
 * @param token Token da instância
 * @returns true se estagnada, false caso contrário
 */
export function isConnectionStale(token: string): boolean {
  const entry = qrCodeCache.get(token);

  if (!entry || entry.status !== 'connecting') {
    return false;
  }

  const now = Date.now();

  // Timeout de conexão
  if (entry.connectingStartedAt && (now - entry.connectingStartedAt > CONNECTING_TIMEOUT_MS)) {
    return true;
  }

  // Muitos refreshes de QR
  if (entry.qrRefreshCount && entry.qrRefreshCount >= MAX_QR_REFRESH_COUNT) {
    return true;
  }

  return false;
}

/**
 * Obtém informações de diagnóstico do cache
 * @param token Token da instância
 */
export function getCacheDebugInfo(token: string): {
  exists: boolean;
  status?: string;
  ageMs?: number;
  connectingDurationMs?: number;
  qrRefreshCount?: number;
  isStale?: boolean;
} | null {
  const entry = qrCodeCache.get(token);

  if (!entry) {
    return { exists: false };
  }

  const now = Date.now();

  return {
    exists: true,
    status: entry.status,
    ageMs: now - entry.timestamp,
    connectingDurationMs: entry.connectingStartedAt ? now - entry.connectingStartedAt : undefined,
    qrRefreshCount: entry.qrRefreshCount,
    isStale: isConnectionStale(token),
  };
}

/**
 * Atualiza status no cache (quando conecta/desconecta)
 * @param token Token da instância
 * @param status Novo status
 */
export function updateCacheStatus(
  token: string,
  status: 'connecting' | 'connected' | 'disconnected'
): void {
  const entry = qrCodeCache.get(token);

  if (entry) {
    const now = Date.now();
    entry.status = status;
    entry.timestamp = now;

    // Se conectou, limpar QR e resetar contadores
    if (status === 'connected') {
      entry.qrcode = '';
      entry.connectingStartedAt = undefined;
      entry.qrRefreshCount = 0;
      console.log(`[QRCache] ✅ Connected! Status updated for ${entry.instanceName.substring(0, 15)}...`);
    }
    // Se desconectou, resetar contadores
    else if (status === 'disconnected') {
      entry.connectingStartedAt = undefined;
      entry.qrRefreshCount = 0;
      console.log(`[QRCache] ❌ Disconnected. Status updated for ${entry.instanceName.substring(0, 15)}...`);
    }
    // Se voltou a connecting, iniciar contador
    else if (status === 'connecting') {
      if (!entry.connectingStartedAt) {
        entry.connectingStartedAt = now;
      }
      console.log(`[QRCache] Status updated for ${entry.instanceName.substring(0, 15)}... -> ${status}`);
    }
  }
}

/**
 * Remove QR code do cache
 * @param token Token da instância
 */
export function clearCachedQRCode(token: string): void {
  qrCodeCache.delete(token);
}

/**
 * Limpa entradas expiradas e estagnadas do cache
 */
export function cleanupExpiredCache(): void {
  const now = Date.now();
  let cleanedExpired = 0;
  let cleanedStale = 0;

  for (const [key, entry] of qrCodeCache.entries()) {
    // Limpar por TTL expirado
    if (now - entry.timestamp > CACHE_TTL_MS) {
      qrCodeCache.delete(key);
      cleanedExpired++;
      continue;
    }

    // Limpar conexões estagnadas (>2 min em connecting)
    if (entry.status === 'connecting' && entry.connectingStartedAt) {
      if (now - entry.connectingStartedAt > CONNECTING_TIMEOUT_MS) {
        console.warn(`[QRCache] Cleaning stale connection for ${entry.instanceName.substring(0, 15)}... (${Math.round((now - entry.connectingStartedAt) / 1000)}s)`);
        qrCodeCache.delete(key);
        cleanedStale++;
        continue;
      }
    }

    // Limpar por excesso de refreshes
    if (entry.qrRefreshCount && entry.qrRefreshCount >= MAX_QR_REFRESH_COUNT) {
      console.warn(`[QRCache] Cleaning due to excessive refreshes for ${entry.instanceName.substring(0, 15)}... (${entry.qrRefreshCount} refreshes)`);
      qrCodeCache.delete(key);
      cleanedStale++;
    }
  }

  if (cleanedExpired > 0 || cleanedStale > 0) {
    console.log(`[QRCache] Cleanup: ${cleanedExpired} expired, ${cleanedStale} stale entries removed`);
  }
}

/**
 * Força limpeza do cache para um token específico
 * Útil quando detectamos que a instância precisa ser recriada
 */
export function forceInvalidateCache(token: string): boolean {
  const entry = qrCodeCache.get(token);
  if (entry) {
    console.log(`[QRCache] Force invalidating cache for ${entry.instanceName.substring(0, 15)}...`);
    qrCodeCache.delete(token);
    return true;
  }
  return false;
}

/**
 * Retorna estatísticas do cache (para monitoramento)
 */
export function getCacheStats(): {
  totalEntries: number;
  connecting: number;
  connected: number;
  disconnected: number;
  staleConnections: number;
} {
  let connecting = 0;
  let connected = 0;
  let disconnected = 0;
  let staleConnections = 0;

  for (const [token, entry] of qrCodeCache.entries()) {
    switch (entry.status) {
      case 'connecting':
        connecting++;
        if (isConnectionStale(token)) {
          staleConnections++;
        }
        break;
      case 'connected':
        connected++;
        break;
      case 'disconnected':
        disconnected++;
        break;
    }
  }

  return {
    totalEntries: qrCodeCache.size,
    connecting,
    connected,
    disconnected,
    staleConnections,
  };
}

// Limpeza automática a cada 30 segundos (mais frequente que antes)
setInterval(cleanupExpiredCache, 30 * 1000);
