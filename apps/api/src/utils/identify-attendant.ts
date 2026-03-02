// ============================================================================
// IDENTIFICACAO DE ATENDENTE VIA IA
// ============================================================================
//
// Usa IA para identificar nome e cargo do atendente humano quando ele se
// apresenta em uma mensagem.
//
// Exemplo:
// - Mensagem: "Oi, sou o Marcos do financeiro"
// - Resultado: { nome: "Marcos", cargo: "financeiro" }
//
// ============================================================================

import { GoogleGenerativeAI } from '@google/generative-ai';
import Anthropic from '@anthropic-ai/sdk';
import OpenAI from 'openai';

export interface AttendantInfo {
  nome: string | null;
  cargo: string | null;
}

export interface IdentifyParams {
  mensagemAtendente: string;
  nomeLead: string;
  provedor: 'gemini' | 'claude' | 'openai';
  apiKey: string;
}

const log = (msg: string, data?: unknown) => console.info(`[IdentifyAttendant] ${msg}`, data ?? '');

/**
 * Usa IA para identificar nome e cargo do atendente a partir da mensagem
 */
export async function identifyAttendant(params: IdentifyParams): Promise<AttendantInfo> {
  const { mensagemAtendente, nomeLead, provedor, apiKey } = params;

  // Mensagem muito curta provavelmente nao tem apresentacao
  if (!mensagemAtendente || mensagemAtendente.length < 10) {
    return { nome: null, cargo: null };
  }

  const prompt = `Voce esta analisando uma mensagem enviada por um ATENDENTE HUMANO para um cliente.

CONTEXTO IMPORTANTE:
- O nome do CLIENTE e: "${nomeLead}"
- NAO confunda o nome do cliente com o nome do atendente
- Voce esta procurando o nome de quem ENVIOU a mensagem (o ATENDENTE)
- O atendente pode se apresentar de varias formas informais em portugues brasileiro

MENSAGEM DO ATENDENTE:
"${mensagemAtendente}"

TAREFA:
Analise se o atendente se identificou nessa mensagem. Procure por padroes como:
- "meu nome e X" / "meu nome é X"
- "sou o/a X"
- "aqui e/é X"
- "X aqui"
- "fala, X aqui"
- qualquer mencao onde alguem diz seu proprio nome

EXEMPLOS DE IDENTIFICACAO:
- "Oi, sou o Marcos do financeiro" -> {"nome": "Marcos", "cargo": "financeiro"}
- "Aqui e a Ana, gerente comercial" -> {"nome": "Ana", "cargo": "gerente comercial"}
- "E ai! Pedrinho aqui do suporte" -> {"nome": "Pedrinho", "cargo": "suporte"}
- "Fala! Lucas assumindo aqui" -> {"nome": "Lucas", "cargo": null}
- "meu nome e elias vou fazer seu atendimento" -> {"nome": "Elias", "cargo": null}
- "oi sou a maria do comercial" -> {"nome": "Maria", "cargo": "comercial"}
- "Oi ${nomeLead}, como posso ajudar?" -> {"nome": null, "cargo": null}

REGRAS:
1. O nome DEVE ser capitalizado (primeira letra maiuscula)
2. Se encontrar nome, retorne-o mesmo que a frase seja informal
3. NUNCA retorne o nome do cliente (${nomeLead}) como nome do atendente

RESPONDA EXATAMENTE NESTE FORMATO JSON:
{"nome": "NomeOuNull", "cargo": "CargoOuNull"}

Se nao encontrou nome, responda:
{"nome": null, "cargo": null}

Responda APENAS o JSON, nada mais.`;

  try {
    let resposta: string;

    if (provedor === 'gemini') {
      const client = new GoogleGenerativeAI(apiKey);
      const model = client.getGenerativeModel({ model: 'gemini-2.0-flash' });
      const result = await model.generateContent(prompt);
      resposta = result.response.text();
    }
    else if (provedor === 'claude') {
      const client = new Anthropic({ apiKey });
      const result = await client.messages.create({
        model: 'claude-sonnet-4-20250514',
        max_tokens: 100,
        messages: [{ role: 'user', content: prompt }]
      });
      resposta = result.content[0].type === 'text' ? result.content[0].text : '';
    }
    else if (provedor === 'openai') {
      const client = new OpenAI({ apiKey });
      const result = await client.chat.completions.create({
        model: 'gpt-4o-mini',
        max_tokens: 100,
        messages: [{ role: 'user', content: prompt }]
      });
      resposta = result.choices[0].message.content || '';
    }
    else {
      throw new Error(`Provedor desconhecido: ${provedor}`);
    }

    log('Resposta da IA', { provedor, resposta: resposta.substring(0, 100) });

    // Extrair JSON da resposta
    const jsonMatch = resposta.match(/\{[\s\S]*\}/);
    if (jsonMatch) {
      const parsed = JSON.parse(jsonMatch[0]);
      return {
        nome: parsed.nome || null,
        cargo: parsed.cargo || null
      };
    }

    return { nome: null, cargo: null };

  } catch (error) {
    log('Erro ao identificar atendente', { error: error instanceof Error ? error.message : error });
    return { nome: null, cargo: null };
  }
}

/**
 * Verifica se deve tentar identificar o atendente
 *
 * Condicoes:
 * 1. Responsavel deve estar generico (vazio, "Atendente", "human", UUID, etc)
 * 2. Maximo 5 tentativas por lead
 *
 * NOTA: Removida verificacao de Atendimento_Finalizado porque a identificacao
 * deve ocorrer na PRIMEIRA mensagem do atendente, quando ele se apresenta.
 * Se esperarmos o atendimento estar pausado, perdemos a chance de capturar
 * o nome na mensagem de apresentacao (ex: "Oi, sou o Marcos do financeiro").
 */
export function shouldIdentifyAttendant(lead: {
  Atendimento_Finalizado?: string | boolean;
  responsavel?: string | null;
  tentativas_identificacao?: number;
}): boolean {
  // 1. Responsavel deve estar generico
  const responsavel = (lead.responsavel || '').toLowerCase().trim();

  const ehGenerico =
    !responsavel ||
    responsavel === 'atendente' ||
    responsavel === 'human' ||
    responsavel === 'humano' ||
    responsavel === 'ai' ||
    responsavel === 'suporte' ||
    responsavel === 'atendimento' ||
    responsavel === 'leadbox' ||
    responsavel === 'admin' ||
    responsavel === 'sistema' ||
    responsavel === 'operador' ||
    // Nomes de agentes (geralmente começam com letra maiúscula e têm Agent/Bot)
    responsavel.includes('agent') ||
    responsavel.includes('bot') ||
    // UUID pattern (ex: 550e8400-e29b-41d4-a716-446655440000)
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(responsavel);

  if (!ehGenerico) {
    return false;
  }

  // 3. Maximo 5 tentativas
  const tentativas = lead.tentativas_identificacao || 0;
  if (tentativas >= 5) {
    return false;
  }

  return true;
}

/**
 * Retorna o provedor e API key configurados no agente
 * Usa o campo ai_provider do agente para determinar qual provedor usar
 */
export function getAIProvider(agent: {
  ai_provider?: string | null;
  gemini_api_key?: string | null;
  claude_api_key?: string | null;
  openai_api_key?: string | null;
}): { provedor: 'gemini' | 'claude' | 'openai'; apiKey: string } | null {
  const provedor = agent.ai_provider as 'gemini' | 'claude' | 'openai' | null;

  let apiKey: string | null = null;

  if (provedor === 'gemini') {
    apiKey = agent.gemini_api_key || null;
  } else if (provedor === 'claude') {
    apiKey = agent.claude_api_key || null;
  } else if (provedor === 'openai') {
    apiKey = agent.openai_api_key || null;
  }

  if (!provedor || !apiKey) {
    return null;
  }

  return { provedor, apiKey };
}
