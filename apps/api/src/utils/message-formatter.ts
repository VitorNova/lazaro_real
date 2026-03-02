/**
 * Utilitarios para formatacao de historico de conversas
 */

export interface ConversationMessage {
  role: 'user' | 'model' | 'assistant';
  content: string;
  timestamp?: string;
  /** Quem enviou a mensagem: 'ai' para IA, 'human' para atendente humano */
  sender?: 'ai' | 'human';
  /** Nome do atendente quando sender é 'human' */
  sender_name?: string | null;
}

export interface DianaContext {
  preQualified?: boolean;
  summary?: string;
  qualificationScore?: number;
  painPoints?: string[];
  buyingSignals?: string[];
  nextStep?: string;
  prospectMessages?: unknown[];
  decisorMessages?: unknown[];
}

export interface ConversationHistory {
  messages: ConversationMessage[];
  lastUpdated?: string;
  dianaContext?: DianaContext; // Contexto da Diana para leads transferidos
}

export interface GeminiMessage {
  role: 'user' | 'model';
  parts: { text: string }[];
}

export interface PipelineStage {
  order: number;
  name: string;
  slug: string;
  icon: string;
  color: string;
  description_for_ai: string;
}

export interface AgentContext {
  name?: string;
  system_prompt?: string | null;
  product_description?: string | null;
  product_value?: number | null;
  pipeline_stages?: PipelineStage[];
  business_hours?: { start: string; end: string };
  timezone?: string;
}

export interface LeadContext {
  id?: number;
  nome?: string | null;
  telefone?: string | null;
  email?: string | null;
  empresa?: string | null;
  pipeline_step?: string;
  status?: string;
  resumo?: string | null;
  ultimo_intent?: string | null;
  follow_count?: number;
}

/**
 * Formata historico de conversas para exibicao em contexto de IA
 */
export function formatConversationHistory(
  history: ConversationHistory | ConversationMessage[] | unknown,
  maxMessages: number = 20
): string {
  let messages: ConversationMessage[] = [];

  if (Array.isArray(history)) {
    messages = history as ConversationMessage[];
  } else if (history && typeof history === 'object' && 'messages' in history) {
    messages = (history as ConversationHistory).messages || [];
  }

  // Limitar quantidade de mensagens
  const recentMessages = messages.slice(-maxMessages);

  if (recentMessages.length === 0) {
    return '';
  }

  return recentMessages
    .map((msg) => {
      const role = msg.role === 'model' || msg.role === 'assistant' ? 'Assistente' : 'Usuario';
      const timestamp = msg.timestamp ? ` [${new Date(msg.timestamp).toLocaleTimeString('pt-BR')}]` : '';
      return `${role}${timestamp}: ${msg.content}`;
    })
    .join('\n');
}

/**
 * Adiciona uma nova mensagem ao historico
 * Mantem as ultimas 100 mensagens (50 trocas de conversa)
 *
 * IMPORTANTE: Se a ultima mensagem tiver o mesmo role, CONCATENA o conteudo
 * para manter a alternancia user/model exigida pelo Gemini
 *
 * @param history - Histórico existente
 * @param message - Conteúdo da mensagem
 * @param role - 'user' ou 'assistant'
 * @param timestamp - Timestamp ISO opcional (usa momento atual se não fornecido)
 * @param sender - Quem enviou: 'ai' ou 'human' (apenas para role 'assistant'/'model')
 * @param senderName - Nome do atendente humano (apenas quando sender é 'human')
 */
export function addMessageToHistory(
  history: ConversationHistory | ConversationMessage[] | unknown,
  message: string,
  role: 'user' | 'assistant',
  timestamp?: string,
  sender?: 'ai' | 'human',
  senderName?: string | null
): ConversationHistory {
  let currentMessages: ConversationMessage[] = [];
  let dianaContext: DianaContext | undefined;

  if (history && typeof history === 'object' && 'messages' in history) {
    const historyObj = history as ConversationHistory;
    currentMessages = [...(historyObj.messages || [])];
    // IMPORTANTE: Preservar dianaContext se existir (para leads transferidos da Diana)
    dianaContext = historyObj.dianaContext;
  } else if (Array.isArray(history)) {
    currentMessages = [...(history as ConversationMessage[])];
  }

  const normalizedRole = role === 'assistant' ? 'model' : role;
  const msgTimestamp = timestamp || new Date().toISOString();

  // Base do resultado (inclui dianaContext se existir)
  const baseResult: ConversationHistory = {
    messages: [],
    lastUpdated: msgTimestamp,
    ...(dianaContext && { dianaContext }),
  };

  // CORREÇÃO: Se a última mensagem tem o mesmo role, CONCATENAR conteúdo
  // Isso evita quebrar a alternância user/model exigida pelo Gemini
  if (currentMessages.length > 0) {
    const lastMessage = currentMessages[currentMessages.length - 1];
    if (lastMessage.role === normalizedRole) {
      // Mesclar: concatena o novo conteúdo à última mensagem
      lastMessage.content = lastMessage.content + '\n' + message;
      lastMessage.timestamp = msgTimestamp;
      // Atualizar sender se fornecido (para mensagens do modelo)
      if (normalizedRole === 'model' && sender) {
        lastMessage.sender = sender;
        if (sender === 'human' && senderName) {
          lastMessage.sender_name = senderName;
        }
      }

      return {
        ...baseResult,
        messages: currentMessages.slice(-100),
      };
    }
  }

  // Se role diferente, adicionar normalmente
  const newMessage: ConversationMessage = {
    role: normalizedRole,
    content: message,
    timestamp: msgTimestamp,
    // Adicionar sender apenas para mensagens do modelo (role 'model')
    ...(normalizedRole === 'model' && sender && { sender }),
    ...(normalizedRole === 'model' && sender === 'human' && senderName && { sender_name: senderName }),
  };

  const updatedMessages = [...currentMessages, newMessage].slice(-100);

  return {
    ...baseResult,
    messages: updatedMessages,
  };
}

/**
 * Trunca historico para manter apenas as ultimas N mensagens
 * Preserva ordem cronologica
 */
export function truncateHistory(
  history: ConversationMessage[] | unknown,
  maxMessages: number = 10
): ConversationMessage[] {
  let messages: ConversationMessage[] = [];

  if (Array.isArray(history)) {
    messages = history as ConversationMessage[];
  } else if (history && typeof history === 'object' && 'messages' in history) {
    messages = (history as ConversationHistory).messages || [];
  }

  // Pega as ultimas N mensagens preservando ordem cronologica
  return messages.slice(-maxMessages);
}

/**
 * Converte historico para formato Gemini
 * role: user ou model
 * parts: [{text: content}]
 */
export function toGeminiHistory(
  messages: ConversationMessage[] | unknown
): GeminiMessage[] {
  let msgArray: ConversationMessage[] = [];

  if (Array.isArray(messages)) {
    msgArray = messages as ConversationMessage[];
  } else if (messages && typeof messages === 'object' && 'messages' in messages) {
    msgArray = (messages as ConversationHistory).messages || [];
  }

  return msgArray.map((msg) => ({
    role: msg.role === 'user' ? 'user' : 'model',
    parts: [{ text: msg.content }],
  }));
}

/**
 * Extrai texto limpo de uma mensagem (remove prefixos de tipo)
 */
export function cleanMessageText(text: string): string {
  // Remove prefixos como [audio], [imagem], etc
  return text
    .replace(/^\[[\w\s]+\]\s*/i, '')
    .trim();
}

/**
 * Interface para padrões de detecção de intent
 */
interface IntentPattern {
  // Regex patterns que indicam este intent (mais específicos)
  patterns: RegExp[];
  // Frases exatas ou quase exatas (alta confiança)
  exactPhrases: string[];
  // Keywords que precisam de contexto (média confiança)
  contextualKeywords: Array<{
    keyword: string;
    // Keywords que INVALIDAM este match se presentes
    invalidators?: string[];
    // Keywords que REFORÇAM este match se presentes
    reinforcers?: string[];
  }>;
  // Peso base do intent (para desempate)
  weight: number;
}

/**
 * Detecta intenção do usuário usando análise contextual avançada
 *
 * MELHORIAS v2.0:
 * - Usa regex para padrões complexos
 * - Considera contexto e negações
 * - Sistema de pesos para desempate
 * - Frases exatas têm prioridade sobre keywords isoladas
 * - Evita falsos positivos com palavras comuns
 *
 * @param text Texto para analisar
 * @returns Intent detectado ou null
 */
export function detectPipelineKeywords(text: string): string | null {
  // Normaliza o texto (lowercase, remove acentos, normaliza espaços)
  const normalizedText = normalizeTextForIntent(text);

  // Define padrões para cada intent (ordem = prioridade)
  const intentPatterns: Record<string, IntentPattern> = {

    // ========================================================================
    // NEGATIVO - Detecta desinteresse CLARO (muito cuidado com falsos positivos!)
    // ========================================================================
    negativo: {
      weight: 100, // Alta prioridade quando detectado
      patterns: [
        /\b(nao|não)\s+(quero|preciso|tenho\s+interesse|me\s+interessa)\b/i,
        /\b(desisto|desistir|desisti)\b/i,
        /\b(cancela|cancelar|cancelei|cancele)\s*(tudo|isso|o\s+pedido|a\s+compra)?\b/i,
        /\bpare?\s+de\s+(me\s+)?(mandar|enviar|contactar|ligar)\b/i,
        /\b(remove|remova|tire|tira)\s+meu\s+(numero|contato|telefone)\b/i,
        /\bnao\s+entre\s+mais\s+em\s+contato\b/i,
        /\bme\s+deixa\s+em\s+paz\b/i,
        /\b(ja|já)\s+(tenho|uso|contratei)\s+(outro|outra)\b/i,
        /\bnao\s+(e|é)\s+pra\s+mim\b/i,
        /\b(obrigad[oa]|valeu),?\s*(mas)?\s*nao\b/i,
      ],
      exactPhrases: [
        'nao quero',
        'nao preciso',
        'nao tenho interesse',
        'sem interesse',
        'nao me interessa',
        'deixa pra la',
        'esquece',
        'nao obrigado',
        'obrigado mas nao',
        'agora nao',
        'nao no momento',
      ],
      contextualKeywords: [
        { keyword: 'cancelar', invalidators: ['como', 'posso', 'da pra', 'consigo'] },
        { keyword: 'parar', invalidators: ['de pagar', 'de gastar'], reinforcers: ['de mandar', 'de enviar', 'mensagem'] },
        { keyword: 'sair', invalidators: ['hora de', 'vou sair', 'preciso sair'], reinforcers: ['da lista', 'do grupo'] },
      ],
    },

    // ========================================================================
    // INTERESSE - Sinais de interesse inicial
    // ========================================================================
    interesse: {
      weight: 30,
      patterns: [
        /\b(estou|to|tou|fico|fiquei)\s+(interessad[oa]|curios[oa])\b/i,
        /\bquero\s+(saber|conhecer|entender)\s+mais\b/i,
        /\b(me\s+)?(conta|explica|fala)\s+(mais|melhor|direito)\b/i,
        /\bcomo\s+(isso\s+)?funciona\??\b/i,
        /\bquero\s+ver\s+(como|a\s+plataforma)\b/i,
        /\bpode\s+me\s+(explicar|mostrar|falar)\b/i,
        /\btenho\s+interesse\b/i,
        /\bparece\s+(bom|interessante|legal)\b/i,
      ],
      exactPhrases: [
        'interessado',
        'interessada',
        'tenho interesse',
        'me interessa',
        'quero saber mais',
        'conta mais',
        'fala mais',
        'como funciona',
        'gostei',
        'achei interessante',
      ],
      contextualKeywords: [
        { keyword: 'quero', invalidators: ['nao', 'não', 'ainda nao'], reinforcers: ['saber', 'conhecer', 'ver'] },
        { keyword: 'interesse', invalidators: ['nao tenho', 'sem', 'perdeu'] },
      ],
    },

    // ========================================================================
    // AGENDAR - Intenção de marcar reunião/demonstração
    // ========================================================================
    agendar: {
      weight: 50,
      patterns: [
        /\b(quero|vamos|bora|pode)\s+(agendar|marcar)\b/i,
        /\b(qual|quando|que)\s+(dia|horario|hora)\s+(posso|podemos|fica\s+bom)?\b/i,
        /\b(tem|teria)\s+horario\s+(disponivel|livre)\b/i,
        /\b(podemos|vamos)\s+(fazer|marcar)\s+(uma\s+)?(reuniao|call|demonstracao|demo)\b/i,
        /\bquando\s+(voce|você|vocês)\s+(pode|podem)\b/i,
        /\bme\s+(passa|manda|envia)\s+(os\s+)?horarios\b/i,
      ],
      exactPhrases: [
        'quero agendar',
        'vamos marcar',
        'pode marcar',
        'qual horario',
        'que dia',
        'quando podemos',
        'me passa os horarios',
        'tem horario',
      ],
      contextualKeywords: [
        { keyword: 'agendar', invalidators: ['nao', 'não', 'como'] },
        { keyword: 'marcar', invalidators: ['nao', 'não', 'desmarcar'] },
        { keyword: 'reuniao', reinforcers: ['fazer', 'marcar', 'agendar'] },
        { keyword: 'demonstracao', reinforcers: ['quero', 'fazer', 'ver'] },
      ],
    },

    // ========================================================================
    // COMPRAR - Intenção clara de compra
    // ========================================================================
    comprar: {
      weight: 70,
      patterns: [
        /\b(quero|vou)\s+(comprar|contratar|assinar|adquirir|fechar)\b/i,
        /\bpode\s+(fechar|fazer)\s+(o\s+)?(contrato|pedido|venda)\b/i,
        /\bvamos\s+(fechar|fazer)\s+(negocio|isso)\b/i,
        /\b(fechado|fechou|fechamos)\s*(negocio|o\s+contrato)?\b/i,
        /\b(vou\s+levar|levo|quero\s+esse)\b/i,
        /\bonde\s+(pago|assino|contrato)\b/i,
      ],
      exactPhrases: [
        'quero comprar',
        'vou comprar',
        'quero contratar',
        'vou contratar',
        'fechado',
        'vamos fechar',
        'pode fechar',
        'vou levar',
        'quero assinar',
      ],
      contextualKeywords: [
        { keyword: 'comprar', invalidators: ['nao', 'não', 'se', 'caso'] },
        { keyword: 'fechar', invalidators: ['nao', 'não', 'posso', 'antes de'], reinforcers: ['vamos', 'pode', 'quero'] },
        { keyword: 'contratar', invalidators: ['nao', 'não', 'antes de'] },
      ],
    },

    // ========================================================================
    // PAGAR - Intenção de pagamento
    // ========================================================================
    pagar: {
      weight: 80,
      patterns: [
        /\b(como|onde|qual)\s+(pago|faco\s+o\s+pagamento)\b/i,
        /\b(aceita|tem|pode\s+ser)\s+(pix|cartao|boleto|credito|debito)\b/i,
        /\b(manda|envia|passa)\s+(o\s+)?(pix|link|boleto)\b/i,
        /\b(vou\s+pagar|ja\s+pago|pago\s+agora)\b/i,
        /\bforma\s+de\s+pagamento\b/i,
        /\b(parcela|parcelamento|parcelo)\s+(em|no)?\s*(\d+)?\b/i,
      ],
      exactPhrases: [
        'como pago',
        'onde pago',
        'manda o pix',
        'envia o pix',
        'qual o pix',
        'pode ser pix',
        'aceita cartao',
        'parcela em quantas',
        'forma de pagamento',
        'vou pagar',
        'ja pago',
      ],
      contextualKeywords: [
        { keyword: 'pix', reinforcers: ['manda', 'envia', 'qual', 'pode'] },
        { keyword: 'boleto', reinforcers: ['manda', 'envia', 'gera', 'tem'] },
        { keyword: 'cartao', reinforcers: ['aceita', 'pode', 'pago no'] },
        { keyword: 'pagamento', invalidators: ['problema', 'erro', 'nao foi'] },
      ],
    },

    // ========================================================================
    // OBJEÇÃO - Resistência mas ainda engajado
    // ========================================================================
    objecao: {
      weight: 40,
      patterns: [
        /\b(ta|está|e|é)\s+(muito\s+)?caro\b/i,
        /\b(nao\s+tenho|sem)\s+(dinheiro|grana|verba|orcamento)\b/i,
        /\b(vou|preciso|deixa\s+eu)\s+pensar\b/i,
        /\b(depois|mais\s+tarde|outra\s+hora)\s+(a\s+gente\s+)?(ve|vemos|conversa|conversamos)\b/i,
        /\bpreciso\s+(falar|consultar|ver)\s+com\s+(meu|minha|o|a)\s+(socio|chefe|esposa|marido)\b/i,
        /\bagora\s+nao\s+(da|posso|consigo)\b/i,
        /\btem\s+(desconto|promocao)\b/i,
        /\bfaz\s+(um\s+)?(desconto|preco\s+melhor)\b/i,
      ],
      exactPhrases: [
        'ta caro',
        'esta caro',
        'muito caro',
        'vou pensar',
        'preciso pensar',
        'deixa eu pensar',
        'depois conversamos',
        'agora nao da',
        'nao tenho dinheiro',
        'sem verba',
        'tem desconto',
        'faz desconto',
      ],
      contextualKeywords: [
        { keyword: 'caro', invalidators: ['nao e', 'não é', 'nem e'] },
        { keyword: 'pensar', invalidators: ['sem', 'nao precisa'] },
        { keyword: 'desconto', reinforcers: ['tem', 'faz', 'da'] },
      ],
    },

    // ========================================================================
    // DÚVIDA - Pedido de esclarecimento
    // ========================================================================
    duvida: {
      weight: 20,
      patterns: [
        /\b(nao\s+entendi|como\s+assim|o\s+que\s+(e|é)\s+isso)\b/i,
        /\b(pode|da\s+pra)\s+(repetir|explicar\s+de\s+novo)\b/i,
        /\btenho\s+(uma\s+)?duvida\b/i,
        /\b(o\s+que|qual)\s+(significa|quer\s+dizer)\b/i,
        /\bnao\s+ficou\s+claro\b/i,
      ],
      exactPhrases: [
        'nao entendi',
        'como assim',
        'pode explicar',
        'tenho uma duvida',
        'o que e isso',
        'nao ficou claro',
      ],
      contextualKeywords: [
        { keyword: 'duvida', reinforcers: ['tenho', 'minha', 'uma'] },
        { keyword: 'entendi', invalidators: ['sim', 'ok', 'certo'], reinforcers: ['nao', 'não'] },
      ],
    },
  };

  // Calcula score para cada intent
  const scores: Record<string, number> = {};

  for (const [intent, pattern] of Object.entries(intentPatterns)) {
    let score = 0;

    // 1. Verifica padrões regex (alta confiança)
    for (const regex of pattern.patterns) {
      if (regex.test(normalizedText)) {
        score += 50;
        break; // Um match de regex é suficiente
      }
    }

    // 2. Verifica frases exatas (muito alta confiança)
    for (const phrase of pattern.exactPhrases) {
      if (normalizedText.includes(phrase)) {
        score += 70;
        break; // Uma frase exata é suficiente
      }
    }

    // 3. Verifica keywords contextuais
    for (const contextual of pattern.contextualKeywords) {
      if (normalizedText.includes(contextual.keyword)) {
        // Verifica invalidadores
        const hasInvalidator = contextual.invalidators?.some(inv =>
          normalizedText.includes(inv)
        );

        if (hasInvalidator) {
          score -= 30; // Penaliza se tiver invalidador
          continue;
        }

        // Verifica reforçadores
        const hasReinforcer = contextual.reinforcers?.some(reinf =>
          normalizedText.includes(reinf)
        );

        if (hasReinforcer) {
          score += 40; // Bonus se tiver reforçador
        } else {
          score += 15; // Score menor sem reforçador
        }
      }
    }

    // Aplica peso base do intent
    if (score > 0) {
      score = score * (pattern.weight / 50);
    }

    scores[intent] = score;
  }

  // Encontra o intent com maior score (mínimo de 30 para ser considerado)
  const minScore = 30;
  let bestIntent: string | null = null;
  let bestScore = minScore;

  for (const [intent, score] of Object.entries(scores)) {
    if (score > bestScore) {
      bestScore = score;
      bestIntent = intent;
    }
  }

  return bestIntent;
}

/**
 * Normaliza texto para análise de intent
 * - Converte para minúsculas
 * - Remove acentos
 * - Normaliza espaços
 */
function normalizeTextForIntent(text: string): string {
  return text
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '') // Remove acentos
    .replace(/\s+/g, ' ') // Normaliza espaços
    .trim();
}

/**
 * Cria resumo das ultimas mensagens
 * Maximo 200 caracteres
 * Foca na ultima intencao
 */
export function createConversationSummary(
  messages: ConversationMessage[] | unknown
): string {
  let msgArray: ConversationMessage[] = [];

  if (Array.isArray(messages)) {
    msgArray = messages as ConversationMessage[];
  } else if (messages && typeof messages === 'object' && 'messages' in messages) {
    msgArray = (messages as ConversationHistory).messages || [];
  }

  if (msgArray.length === 0) {
    return 'Conversa iniciada';
  }

  // Pegar ultimas 3 mensagens do usuario
  const userMessages = msgArray
    .filter((m) => m.role === 'user')
    .slice(-3);

  if (userMessages.length === 0) {
    return 'Aguardando resposta do usuario';
  }

  // Detectar ultima intencao
  const lastUserMessage = userMessages[userMessages.length - 1];
  const intent = detectPipelineKeywords(lastUserMessage.content);

  let summary = '';

  if (intent) {
    summary = `Intencao: ${intent}. `;
  }

  // Adicionar preview da ultima mensagem
  const preview = lastUserMessage.content.substring(0, 150);
  summary += `Ultima msg: "${preview}${lastUserMessage.content.length > 150 ? '...' : ''}"`;

  // Garantir maximo de 200 caracteres
  return summary.substring(0, 200);
}

/**
 * Monta prompt completo com contexto para IA
 * Inclui: system prompt, pipeline stage, info do lead, historico
 */
export function buildAIContext(
  agent: AgentContext,
  lead: LeadContext,
  history: ConversationHistory | ConversationMessage[] | unknown
): string {
  const sections: string[] = [];

  // 1. System Prompt do Agent
  if (agent.system_prompt) {
    sections.push(`=== INSTRUCOES DO SISTEMA ===\n${agent.system_prompt}`);
  }

  // 2. Informacoes do Produto/Servico
  if (agent.product_description || agent.product_value) {
    let productInfo = '=== PRODUTO/SERVICO ===\n';
    if (agent.product_description) {
      productInfo += `Descricao: ${agent.product_description}\n`;
    }
    if (agent.product_value) {
      productInfo += `Valor: R$ ${agent.product_value.toFixed(2)}\n`;
    }
    sections.push(productInfo.trim());
  }

  // 3. Pipeline Stage Atual
  if (lead.pipeline_step && agent.pipeline_stages) {
    const currentStage = agent.pipeline_stages.find(
      (s) => s.slug === lead.pipeline_step || s.name === lead.pipeline_step
    );

    if (currentStage) {
      let stageInfo = '=== ETAPA ATUAL DO PIPELINE ===\n';
      stageInfo += `Nome: ${currentStage.name}\n`;
      stageInfo += `Ordem: ${currentStage.order}\n`;
      if (currentStage.description_for_ai) {
        stageInfo += `Instrucoes para esta etapa: ${currentStage.description_for_ai}\n`;
      }
      sections.push(stageInfo.trim());
    }
  }

  // 4. Informacoes do Lead
  const leadInfo: string[] = [];
  if (lead.nome) leadInfo.push(`Nome: ${lead.nome}`);
  if (lead.telefone) leadInfo.push(`Telefone: ${lead.telefone}`);
  if (lead.email) leadInfo.push(`Email: ${lead.email}`);
  if (lead.empresa) leadInfo.push(`Empresa: ${lead.empresa}`);
  if (lead.pipeline_step) leadInfo.push(`Etapa: ${lead.pipeline_step}`);
  if (lead.status) leadInfo.push(`Status: ${lead.status}`);
  if (lead.ultimo_intent) leadInfo.push(`Ultima intencao: ${lead.ultimo_intent}`);
  if (lead.follow_count !== undefined) leadInfo.push(`Follow-ups enviados: ${lead.follow_count}`);
  if (lead.resumo) leadInfo.push(`Resumo: ${lead.resumo}`);

  if (leadInfo.length > 0) {
    sections.push(`=== INFORMACOES DO LEAD ===\n${leadInfo.join('\n')}`);
  }

  // 5. Horario para Agendamentos (NÃO é horário de funcionamento do agente)
  // A Agnes SDR funciona 24 horas - business_hours é APENAS para agendar reuniões
  if (agent.business_hours) {
    const tz = agent.timezone || 'America/Sao_Paulo';
    sections.push(
      `=== HORARIO DISPONIVEL PARA AGENDAMENTOS ===\nQuando o cliente quiser agendar uma reuniao, os horarios disponiveis sao das ${agent.business_hours.start} as ${agent.business_hours.end} (${tz}).\nIMPORTANTE: Voce deve SEMPRE responder o cliente, independente do horario. Este horario e apenas para agendar reunioes.`
    );
  }

  // 6. Historico da Conversa
  const formattedHistory = formatConversationHistory(history, 15);
  if (formattedHistory) {
    sections.push(`=== HISTORICO DA CONVERSA ===\n${formattedHistory}`);
  }

  // 7. Instrucao Final
  sections.push(
    '=== INSTRUCAO ===\nResponda a proxima mensagem do usuario de forma natural e objetiva, seguindo as instrucoes acima e considerando o contexto da conversa.'
  );

  return sections.join('\n\n');
}
