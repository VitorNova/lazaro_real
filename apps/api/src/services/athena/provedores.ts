import Anthropic from '@anthropic-ai/sdk';
import OpenAI from 'openai';
import { GoogleGenerativeAI } from '@google/generative-ai';
import { Provedor } from './tipos';

export async function chamarIA(
  provedor: Provedor,
  apiKey: string,
  instrucoes: string,
  mensagem: string
): Promise<string> {

  console.log(`[Athena] Chamando provedor: ${provedor}`);

  try {
    if (provedor === 'claude') {
      const cliente = new Anthropic({ apiKey });
      const resposta = await cliente.messages.create({
        model: 'claude-sonnet-4-20250514',
        max_tokens: 2000,
        system: instrucoes,
        messages: [{ role: 'user', content: mensagem }]
      });
      const content = resposta.content[0];
      if (content.type === 'text') {
        return content.text;
      }
      return '';
    }

    if (provedor === 'openai') {
      const cliente = new OpenAI({ apiKey });
      const resposta = await cliente.chat.completions.create({
        model: 'gpt-4o',
        max_tokens: 2000,
        messages: [
          { role: 'system', content: instrucoes },
          { role: 'user', content: mensagem }
        ]
      });
      return resposta.choices[0].message.content || '';
    }

    if (provedor === 'gemini') {
      const cliente = new GoogleGenerativeAI(apiKey);
      const modelo = cliente.getGenerativeModel({
        model: 'gemini-2.0-flash',
        systemInstruction: instrucoes
      });
      const resposta = await modelo.generateContent(mensagem);
      return resposta.response.text();
    }

    throw new Error(`Provedor desconhecido: ${provedor}`);

  } catch (error: any) {
    console.error(`[Athena] Erro ao chamar ${provedor}:`, error);

    if (error?.status === 401 || error?.message?.includes('API key')) {
      throw new Error('API key inválida. Verifique sua chave.');
    }

    if (error?.status === 429) {
      throw new Error('Limite de requisições atingido. Aguarde.');
    }

    throw error;
  }
}

export function detectarProvedor(agentes: any[]): { provedor: Provedor; apiKey: string } | null {
  for (const agente of agentes) {
    if (agente.gemini_api_key) {
      return { provedor: 'gemini', apiKey: agente.gemini_api_key };
    }
    if (agente.claude_api_key) {
      return { provedor: 'claude', apiKey: agente.claude_api_key };
    }
    if (agente.openai_api_key) {
      return { provedor: 'openai', apiKey: agente.openai_api_key };
    }
  }
  return null;
}
