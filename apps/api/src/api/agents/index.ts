/**
 * Agent Routes - Main Entry Point
 *
 * Refactored from monolithic index.ts (1781 lines) - Phase 9.11
 *
 * Route groups extracted:
 * - crud.routes.ts: Agent CRUD operations (create, get, update, delete, list)
 * - connection.routes.ts: QR Code, webhook config, Evolution, UAZAPI
 * - dashboard.routes.ts: Dashboard stats, Asaas, Maintenance, Agent Metrics
 * - leads.routes.ts: Leads API, Conversations, Toggle AI
 * - user-settings.routes.ts: User configuration (logo, company name)
 * - google-calendar.routes.ts: Google Calendar OAuth
 * - billing-audit.routes.ts: Billing, Audit Logs, Interventions, Integrations
 * - learning.routes.ts: Learning Entries (AI curation)
 * - messages-media.routes.ts: Messages, Media, Avatar
 *
 * Remaining routes in index.legacy.ts (to be extracted incrementally).
 */

import { FastifyInstance } from 'fastify';
import { registerCrudRoutes } from './crud.routes';
import { registerConnectionRoutes } from './connection.routes';
import { registerDashboardRoutes } from './dashboard.routes';
import { registerLeadsRoutes } from './leads.routes';
import { registerUserSettingsRoutes } from './user-settings.routes';
import { registerGoogleCalendarRoutes } from './google-calendar.routes';
import { registerBillingAuditRoutes } from './billing-audit.routes';
import { registerLearningRoutes } from './learning.routes';
import { registerMessagesMediaRoutes } from './messages-media.routes';

// Re-export handlers for external use
export { createAgentHandler, CreateAgentRequest, CreateAgentBody } from './create.handler';
export { deleteAgentHandler } from './delete.handler';
export { updateAgentHandler, getAgentHandler, UpdateAgentBody } from './update.handler';
export {
  getQRCodeHandler,
  checkConnectionHandler,
  getQRCodeImageHandler,
  disconnectHandler,
} from './qrcode.handler';
export {
  configureWebhookHandler,
  getWebhookConfigHandler,
  deleteWebhookConfigHandler,
} from './webhook-config.handler';
export { getAgentStatsHandler } from './stats.handler';
export {
  getEvolutionStatusHandler,
  connectEvolutionHandler,
  getEvolutionQRCodeHandler,
  disconnectEvolutionHandler,
  listEvolutionInstancesHandler,
} from './evolution.handler';
export { getUazapiStatusHandler } from './uazapi-status.handler';
export { getSchedulesHandler, deleteScheduleHandler } from './schedules.handler';
export {
  uploadMediaHandler,
  listMediasHandler,
  deleteMediaHandler,
  uploadAvatarHandler,
  deleteAvatarHandler,
} from './media.handler';

/**
 * Register all agent routes on the Fastify instance.
 *
 * This function orchestrates route registration from multiple modules.
 */
export async function registerAgentRoutes(fastify: FastifyInstance): Promise<void> {
  console.info('[AgentRoutes] Registering agent routes (refactored)...');

  // Register extracted route groups (in parallel where possible)
  await Promise.all([
    registerCrudRoutes(fastify),
    registerConnectionRoutes(fastify),
    registerDashboardRoutes(fastify),
    registerLeadsRoutes(fastify),
    registerUserSettingsRoutes(fastify),
    registerGoogleCalendarRoutes(fastify),
    registerBillingAuditRoutes(fastify),
    registerLearningRoutes(fastify),
    registerMessagesMediaRoutes(fastify),
  ]);

  // Import remaining routes from legacy file
  // These will be progressively migrated to separate files
  const { registerLegacyRoutes } = await import('./index.legacy');
  await registerLegacyRoutes(fastify);

  console.info('[AgentRoutes] All agent routes registered.');
}
