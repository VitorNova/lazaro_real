/**
 * Lazaro API - Backend independente
 *
 * Todas as rotas são registradas via registerAgentRoutes e registerAuthRoutes
 * para evitar duplicação.
 */

import 'dotenv/config';
import Fastify from 'fastify';
import cors from '@fastify/cors';
import { config } from './config';
import { supabaseAdmin } from './services/supabase/client';

// Route registrars
import { registerAgentRoutes } from './api/agents';
import { registerAuthRoutes } from './api/auth';

// Logger
const logger = {
  info: (msg: string, data?: unknown) => console.info(`[Lazaro-API] ${msg}`, data ?? ''),
  error: (msg: string, data?: unknown) => console.error(`[Lazaro-API] ${msg}`, data ?? ''),
  warn: (msg: string, data?: unknown) => console.warn(`[Lazaro-API] ${msg}`, data ?? ''),
};

// Fastify instance
const fastify = Fastify({
  logger: config.nodeEnv !== 'production',
  bodyLimit: 50 * 1024 * 1024, // 50MB
});

async function bootstrap() {
  try {
    logger.info('Starting Lazaro API...', { environment: config.nodeEnv });

    // CORS
    await fastify.register(cors, { origin: true });

    // Health check
    fastify.get('/health', async () => ({
      status: 'ok',
      service: 'lazaro-api',
      version: '1.0.0',
      timestamp: new Date().toISOString(),
    }));

    // ========================================================================
    // AUTH ROUTES (login, logout, refresh, me, sessions)
    // ========================================================================
    logger.info('Registering auth routes...');
    await registerAuthRoutes(fastify, supabaseAdmin);

    // ========================================================================
    // ALL OTHER ROUTES (agents, dashboard, analytics, conversations, etc.)
    // registerAgentRoutes registra internamente:
    // - /api/agents/*
    // - /api/dashboard/*
    // - /api/conversations/*
    // - /api/analytics/*
    // - /api/leads/*
    // - /api/google/*
    // ========================================================================
    logger.info('Registering all routes...');
    await registerAgentRoutes(fastify);

    // ========================================================================
    // GRACEFUL SHUTDOWN
    // ========================================================================
    const shutdown = async (signal: string) => {
      logger.info(`Received ${signal}, shutting down gracefully...`);
      await fastify.close();
      process.exit(0);
    };

    process.on('SIGTERM', () => shutdown('SIGTERM'));
    process.on('SIGINT', () => shutdown('SIGINT'));

    // ========================================================================
    // START SERVER
    // ========================================================================
    await fastify.listen({
      port: config.port,
      host: '0.0.0.0',
    });

    logger.info('='.repeat(50));
    logger.info('Lazaro API started successfully!');
    logger.info('='.repeat(50));
    logger.info(`Server: http://0.0.0.0:${config.port}`);
    logger.info(`Environment: ${config.nodeEnv}`);
    logger.info(`Health: GET /health`);
    logger.info('='.repeat(50));
  } catch (error) {
    logger.error('Failed to start', { error });
    process.exit(1);
  }
}

bootstrap();
