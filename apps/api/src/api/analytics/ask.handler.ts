// ============================================================================
// ATHENA - ASK HANDLER (Simplificado)
// ============================================================================

import { FastifyRequest, FastifyReply } from 'fastify';
import { perguntar, Provedor, ConfigIA } from '../../services/athena/athena';

// ============================================================================
// TYPES
// ============================================================================

interface AskRequest {
  Body: {
    question: string;
    pergunta?: string; // Alias para compatibilidade
    ai_provider?: Provedor;
    provedor?: Provedor; // Alias para compatibilidade
    ai_api_key?: string;
    api_key?: string; // Alias para compatibilidade
  };
  Querystring: {
    user_id?: string;
  };
}

// ============================================================================
// HANDLER
// ============================================================================

/**
 * POST /api/analytics/ask
 *
 * Recebe uma pergunta em linguagem natural e retorna a resposta
 * baseada nos dados reais do sistema.
 */
export async function askAnalyticsHandler(
  request: FastifyRequest<AskRequest>,
  reply: FastifyReply
) {
  try {
    const usuarioId = (request as any).user?.id || request.query.user_id;

    if (!usuarioId) {
      return reply.status(401).send({
        sucesso: false,
        success: false,
        erro: 'Autenticação necessária',
        error: 'Autenticação necessária',
      });
    }

    const {
      question,
      pergunta,
      ai_provider,
      provedor,
      ai_api_key,
      api_key
    } = request.body;

    const perguntaFinal = question || pergunta;

    if (!perguntaFinal || perguntaFinal.trim().length === 0) {
      return reply.status(400).send({
        sucesso: false,
        success: false,
        erro: 'Pergunta não pode ser vazia',
        error: 'Pergunta não pode ser vazia',
      });
    }

    const provedorFinal = ai_provider || provedor;
    const apiKeyFinal = ai_api_key || api_key;

    const config: ConfigIA | undefined = provedorFinal && apiKeyFinal
      ? { provedor: provedorFinal, apiKey: apiKeyFinal }
      : undefined;

    const resultado = await perguntar(usuarioId, perguntaFinal.trim(), config);

    return reply.send({
      sucesso: resultado.sucesso,
      success: resultado.sucesso,
      resposta: resultado.resposta,
      answer: resultado.resposta,
      tempo_ms: resultado.tempoMs,
      execution_time_ms: resultado.tempoMs,
    });

  } catch (error: any) {
    console.error('[Athena Handler] Erro:', error);
    return reply.status(500).send({
      sucesso: false,
      success: false,
      erro: 'Erro interno',
      error: 'Erro interno',
    });
  }
}

// ============================================================================
// QUICK STATS HANDLER
// ============================================================================

/**
 * GET /api/analytics/quick-stats
 *
 * Retorna estatísticas rápidas sem precisar de pergunta
 */
export async function quickStatsHandler(
  request: FastifyRequest<{
    Querystring: {
      user_id?: string;
      ai_provider?: Provedor;
      ai_api_key?: string;
    }
  }>,
  reply: FastifyReply
) {
  try {
    const usuarioId = (request as any).user?.id || request.query.user_id;

    if (!usuarioId) {
      return reply.status(401).send({
        sucesso: false,
        success: false,
        erro: 'Autenticação necessária',
        error: 'Autenticação necessária',
      });
    }

    const config: ConfigIA | undefined = request.query.ai_api_key && request.query.ai_provider
      ? { provedor: request.query.ai_provider, apiKey: request.query.ai_api_key }
      : undefined;

    const resultado = await perguntar(
      usuarioId,
      'Dê um resumo rápido: quantos leads, agendamentos e qual a taxa de conversão dessa semana?',
      config
    );

    return reply.send({
      sucesso: resultado.sucesso,
      success: resultado.sucesso,
      summary: resultado.resposta,
      execution_time_ms: resultado.tempoMs,
    });
  } catch (error) {
    console.error('[Athena] Erro no quick-stats:', error);

    return reply.status(500).send({
      sucesso: false,
      success: false,
      erro: 'Erro interno',
      error: 'Erro interno',
    });
  }
}

// ============================================================================
// MODELS HANDLER
// ============================================================================

const PROVIDER_INFO = {
  claude: { name: 'Claude', company: 'Anthropic' },
  openai: { name: 'GPT-4o', company: 'OpenAI' },
  gemini: { name: 'Gemini', company: 'Google' },
};

const AI_MODELS = {
  claude: ['claude-sonnet-4-20250514'],
  openai: ['gpt-4o'],
  gemini: ['gemini-2.0-flash'],
};

/**
 * GET /api/analytics/models
 *
 * Retorna os modelos de IA disponíveis para cada provider
 */
export async function modelsHandler(
  request: FastifyRequest,
  reply: FastifyReply
) {
  return reply.send({
    success: true,
    providers: PROVIDER_INFO,
    models: AI_MODELS,
  });
}

// ============================================================================
// SUGGESTED QUESTIONS
// ============================================================================

/**
 * GET /api/analytics/suggestions
 *
 * Retorna sugestões de perguntas que o usuário pode fazer.
 */
export async function suggestionsHandler(
  request: FastifyRequest,
  reply: FastifyReply
) {
  const suggestions = [
    // ROI e Financeiro
    {
      category: 'Financeiro',
      icon: '💰',
      questions: [
        'Quanto faturei esse mês?',
        'Qual o ticket médio?',
        'Quantos links de pagamento foram pagos?',
      ],
    },
    // Leads
    {
      category: 'Leads',
      icon: '👥',
      questions: [
        'Quantos leads entraram essa semana?',
        'De onde vêm meus melhores leads?',
        'Quantos leads quentes tenho?',
        'Qual a taxa de conversão?',
      ],
    },
    // Funil
    {
      category: 'Funil',
      icon: '📊',
      questions: [
        'Onde estou perdendo mais leads?',
        'Qual etapa do pipeline tem mais leads?',
        'Qual o gargalo do meu funil?',
      ],
    },
    // Agendamentos
    {
      category: 'Agendamentos',
      icon: '📅',
      questions: [
        'Quantas reuniões tenho marcadas?',
        'Qual a taxa de no-show?',
        'Quais reuniões são hoje?',
      ],
    },
    // Follow-up
    {
      category: 'Follow-up',
      icon: '🔄',
      questions: [
        'O follow-up está funcionando?',
        'Qual mensagem tem melhor resposta?',
        'Quantos leads reengajaram?',
      ],
    },
    // IA e Eficiência
    {
      category: 'Performance IA',
      icon: '🤖',
      questions: [
        'A IA está respondendo bem?',
        'Quantos pediram atendente humano?',
        'A IA está qualificando corretamente?',
      ],
    },
    // Problemas
    {
      category: 'Problemas',
      icon: '⚠️',
      questions: [
        'Tem algum problema urgente?',
        'Quais leads estão sem resposta?',
        'O WhatsApp está conectado?',
      ],
    },
    // Comparativos
    {
      category: 'Comparativos',
      icon: '📈',
      questions: [
        'Estou melhor que semana passada?',
        'Como foi o mês comparado ao anterior?',
        'Qual tendência dos leads?',
      ],
    },
  ];

  return reply.send({
    success: true,
    agent: {
      name: 'Athena',
      description: 'Assistente de Analytics - Deusa da sabedoria e estratégia',
      avatar: '🦉',
    },
    suggestions,
  });
}
