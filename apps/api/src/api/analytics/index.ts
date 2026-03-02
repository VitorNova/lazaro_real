// ============================================================================
// ATHENA - ANALYTICS API ROUTES
// ============================================================================

import { FastifyInstance } from 'fastify';
import {
  askAnalyticsHandler,
  quickStatsHandler,
  suggestionsHandler,
  modelsHandler,
} from './ask.handler';
import {
  transcribeHandler,
  speakHandler,
  voicesHandler,
} from './voice.handler';

export async function analyticsRoutes(fastify: FastifyInstance) {
  // POST /api/analytics/ask - Perguntar algo à Athena
  fastify.post('/ask', askAnalyticsHandler);

  // GET /api/analytics/quick-stats - Estatísticas rápidas
  fastify.get('/quick-stats', quickStatsHandler);

  // GET /api/analytics/suggestions - Sugestões de perguntas
  fastify.get('/suggestions', suggestionsHandler);

  // GET /api/analytics/models - Modelos de IA disponíveis
  fastify.get('/models', modelsHandler);

  // ============================================================================
  // VOICE ENDPOINTS (STT & TTS)
  // ============================================================================

  // POST /api/analytics/transcribe - Transcrever áudio para texto (Whisper)
  fastify.post('/transcribe', transcribeHandler);

  // POST /api/analytics/speak - Sintetizar texto para áudio (OpenAI TTS)
  fastify.post('/speak', speakHandler);

  // GET /api/analytics/voices - Listar vozes disponíveis
  fastify.get('/voices', voicesHandler);
}

export default analyticsRoutes;
