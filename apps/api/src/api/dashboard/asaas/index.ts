/**
 * Asaas Dashboard Handlers
 *
 * Este módulo re-exporta todos os handlers do dashboard Asaas.
 * Equivalente ao antigo asaas.handler.ts monolítico (2401 linhas).
 */

// Dashboard principal
export { getAsaasDashboardHandler } from './dashboard.handler';

// Parsing de contratos
export {
  parseContractHandler,
  parseAllContractsHandler,
  mergeContractData,
  extractWithGemini,
  parseContractInternal,
} from './contract-parser.handler';

// Sincronização com Asaas
export {
  syncAllAsaasHandler,
  calcDiasAtraso,
  upsertInBatches,
  markDeletedRecords,
} from './sync.handler';

// Clientes e dados auxiliares
export {
  getAsaasCustomersHandler,
  getAsaasParcelamentosHandler,
  getAsaasAvailableMonthsHandler,
} from './customers.handler';
