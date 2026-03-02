/**
 * ContextSyncWorker - Worker para sincronizacao assincrona
 *
 * RESPONSABILIDADE:
 * Executar periodicamente (a cada 5 segundos) a sincronizacao de
 * contextos modificados (dirty) do Redis para o Supabase.
 *
 * BENEFICIO:
 * Permite que escrita no cache seja instantanea (<2ms) sem bloquear
 * a resposta do webhook. O sync com Supabase acontece em background.
 */

import { getContextCacheService } from './context-cache.service';

// ============================================================================
// LOGGER
// ============================================================================

const Logger = {
  info: (message: string, data?: unknown) => {
    console.log(`[ContextSyncWorker] ${message}`, data ? JSON.stringify(data, null, 2) : '');
  },
  error: (message: string, error?: unknown) => {
    console.error(`[ContextSyncWorker] ${message}`, error);
  },
  debug: (message: string, data?: unknown) => {
    if (process.env.DEBUG === 'true') {
      console.log(`[ContextSyncWorker:DEBUG] ${message}`, data ? JSON.stringify(data, null, 2) : '');
    }
  },
};

// ============================================================================
// WORKER
// ============================================================================

export class ContextSyncWorker {
  private intervalId: NodeJS.Timeout | null = null;
  private readonly syncInterval: number;
  private isRunning: boolean = false;

  constructor(syncInterval: number = 5000) {
    this.syncInterval = syncInterval;
  }

  /**
   * Inicia o worker de sincronizacao
   */
  start(): void {
    if (this.isRunning) {
      Logger.info('Sync worker already running');
      return;
    }

    this.isRunning = true;

    Logger.info(`Starting sync worker (interval: ${this.syncInterval}ms)`);

    this.intervalId = setInterval(async () => {
      await this.processSync();
    }, this.syncInterval);

    Logger.info('Sync worker started');
  }

  /**
   * Para o worker de sincronizacao
   */
  stop(): void {
    if (!this.isRunning) {
      Logger.info('Sync worker is not running');
      return;
    }

    if (this.intervalId) {
      clearInterval(this.intervalId);
      this.intervalId = null;
    }

    this.isRunning = false;

    Logger.info('Sync worker stopped');
  }

  /**
   * Verifica se o worker esta rodando
   */
  isActive(): boolean {
    return this.isRunning;
  }

  /**
   * Processa sincronizacao de contextos dirty
   *
   * FLUXO:
   * 1. Busca todos os contextos marcados como dirty no Redis
   * 2. Para cada um, salva o historico no Supabase
   * 3. Marca como sincronizado (isDirty = false)
   * 4. Remove do set de contextos dirty
   */
  private async processSync(): Promise<void> {
    try {
      const cacheService = getContextCacheService();

      // Verificar saude do Redis
      const healthy = await cacheService.isHealthy();
      if (!healthy) {
        Logger.error('Redis unhealthy, skipping sync');
        return;
      }

      // Sincronizar contextos dirty
      const syncedCount = await cacheService.syncDirtyContexts();

      if (syncedCount > 0) {
        Logger.info(`Synced ${syncedCount} dirty contexts with Supabase`);
      }
    } catch (error) {
      Logger.error('Error processing sync', error);
    }
  }

  /**
   * Forca execucao imediata de sync (util para testes)
   */
  async syncNow(): Promise<number> {
    Logger.info('Manual sync triggered');
    const cacheService = getContextCacheService();
    return cacheService.syncDirtyContexts();
  }
}

// ============================================================================
// SINGLETON
// ============================================================================

let syncWorkerInstance: ContextSyncWorker | null = null;

/**
 * Retorna instancia singleton do worker
 */
export function getSyncWorker(): ContextSyncWorker {
  if (!syncWorkerInstance) {
    const syncInterval = parseInt(process.env.CONTEXT_CACHE_SYNC_INTERVAL || '5000', 10);
    syncWorkerInstance = new ContextSyncWorker(syncInterval);
  }
  return syncWorkerInstance;
}

/**
 * Inicia worker de sincronizacao
 */
export function startSyncWorker(): void {
  const worker = getSyncWorker();
  worker.start();
}

/**
 * Para worker de sincronizacao
 */
export function stopSyncWorker(): void {
  const worker = getSyncWorker();
  worker.stop();
}

/**
 * Forca sincronizacao imediata
 */
export async function syncNow(): Promise<number> {
  const worker = getSyncWorker();
  return worker.syncNow();
}
