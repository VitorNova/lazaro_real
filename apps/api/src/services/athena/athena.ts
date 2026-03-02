import { buscarTudo } from './dados';
import { chamarIA, detectarProvedor } from './provedores';
import { DadosAthena, Provedor, ConfigIA } from './tipos';

const INSTRUCOES = `Você responde perguntas sobre os dados do usuário.

REGRAS:
- Seja direto, dê o número primeiro
- Não enrole, não repita a pergunta
- Use os dados abaixo para responder
- Se não tiver o dado, diga que não tem
- Formate datas em português (dd/mm/aaaa)
- Formate valores em reais (R$ 1.000,00)

Responda em português brasileiro.`;

export interface RespostaAthena {
  sucesso: boolean;
  resposta: string;
  tempoMs: number;
}

export async function perguntar(
  usuarioId: string,
  pergunta: string,
  config?: ConfigIA
): Promise<RespostaAthena> {

  const inicio = Date.now();

  try {
    // 1. Buscar todos os dados
    console.log(`[Athena] Buscando dados do usuário ${usuarioId}`);
    const dados = await buscarTudo(usuarioId);

    if (dados.agentes.length === 0) {
      return {
        sucesso: false,
        resposta: 'Você não tem agentes cadastrados.',
        tempoMs: Date.now() - inicio
      };
    }

    // 2. Detectar provedor de IA
    let provedor: Provedor;
    let apiKey: string;

    if (config?.provedor && config?.apiKey) {
      provedor = config.provedor;
      apiKey = config.apiKey;
    } else {
      const detectado = detectarProvedor(dados.agentes);
      if (!detectado) {
        return {
          sucesso: false,
          resposta: 'Nenhuma API key de IA configurada.',
          tempoMs: Date.now() - inicio
        };
      }
      provedor = detectado.provedor;
      apiKey = detectado.apiKey;
    }

    // 3. Formatar dados como texto
    const contexto = formatarDados(dados);
    console.log(`[Athena] Contexto: ${contexto.length} caracteres`);

    // 4. Chamar IA
    const mensagem = `DADOS:\n${contexto}\n\nPERGUNTA: ${pergunta}`;
    const resposta = await chamarIA(provedor, apiKey, INSTRUCOES, mensagem);

    return {
      sucesso: true,
      resposta,
      tempoMs: Date.now() - inicio
    };

  } catch (error: any) {
    console.error('[Athena] Erro:', error);
    return {
      sucesso: false,
      resposta: `Erro: ${error.message || 'Erro desconhecido'}`,
      tempoMs: Date.now() - inicio
    };
  }
}

function formatarDados(dados: DadosAthena): string {
  let texto = '';

  // === AGENTES ===
  texto += `AGENTES (${dados.agentes.length}):\n`;
  dados.agentes.forEach(a => {
    texto += `- ${a.name} | ${a.type} | ${a.status}\n`;
  });

  // === LEADS ===
  texto += `\nLEADS (${dados.leads.length}):\n`;
  dados.leads.forEach(l => {
    const data = l.created_date
      ? new Date(l.created_date).toLocaleDateString('pt-BR')
      : 'sem data';
    const valor = l.valor ? `R$${l.valor}` : 'sem valor';
    const bant = `B:${l.bant_budget || 0} A:${l.bant_authority || 0} N:${l.bant_need || 0} T:${l.bant_timing || 0}`;

    texto += `- ${l.nome} | ${l.telefone} | ${data} | ${l.pipeline_step || 'sem etapa'} | ${l.lead_temperature || 'frio'} | ${valor} | ${bant}\n`;

    if (l.resumo) {
      texto += `  Resumo: ${l.resumo.substring(0, 100)}${l.resumo.length > 100 ? '...' : ''}\n`;
    }
    if (l.next_appointment_at) {
      texto += `  Próximo agendamento: ${new Date(l.next_appointment_at).toLocaleString('pt-BR')}\n`;
    }
  });

  // === AGENDAMENTOS ===
  texto += `\nAGENDAMENTOS (${dados.agendamentos.length}):\n`;
  dados.agendamentos.forEach(a => {
    const dataHora = new Date(a.scheduled_at).toLocaleString('pt-BR');
    texto += `- ${a.customer_name} | ${dataHora} | ${a.status} | ${a.service_name || 'sem serviço'}\n`;
  });

  // === FOLLOW-UPS ===
  const followupsPendentes = dados.followups.filter(f => f.status === 'pending').length;
  const followupsEnviados = dados.followups.filter(f => f.status === 'sent').length;

  texto += `\nFOLLOW-UPS:\n`;
  texto += `- Total: ${dados.followups.length}\n`;
  texto += `- Pendentes: ${followupsPendentes}\n`;
  texto += `- Enviados: ${followupsEnviados}\n`;

  // === MÉTRICAS ===
  const quentes = dados.leads.filter(l =>
    ['hot', 'quente'].includes((l.lead_temperature || '').toLowerCase())
  ).length;
  const mornos = dados.leads.filter(l =>
    ['warm', 'morno'].includes((l.lead_temperature || '').toLowerCase())
  ).length;
  const frios = dados.leads.length - quentes - mornos;

  const vendas = dados.leads.filter(l => l.venda_realizada).length;
  const faturamento = dados.leads.reduce((soma, l) => soma + (l.valor || 0), 0);

  const agendamentosConfirmados = dados.agendamentos.filter(a => a.status === 'confirmed').length;
  const agendamentosCancelados = dados.agendamentos.filter(a => a.status === 'cancelled').length;

  // Leads por período
  const hoje = new Date();
  hoje.setHours(0, 0, 0, 0);
  const leadsHoje = dados.leads.filter(l =>
    l.created_date && new Date(l.created_date) >= hoje
  ).length;

  const semanaAtras = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000);
  const leadsSemana = dados.leads.filter(l =>
    l.created_date && new Date(l.created_date) >= semanaAtras
  ).length;

  texto += `\nMÉTRICAS:\n`;
  texto += `- Total leads: ${dados.leads.length}\n`;
  texto += `- Leads hoje: ${leadsHoje}\n`;
  texto += `- Leads esta semana: ${leadsSemana}\n`;
  texto += `- Quentes: ${quentes} | Mornos: ${mornos} | Frios: ${frios}\n`;
  texto += `- Vendas realizadas: ${vendas}\n`;
  texto += `- Faturamento total: R$${faturamento.toLocaleString('pt-BR')}\n`;
  texto += `- Taxa de conversão: ${dados.leads.length > 0 ? ((vendas / dados.leads.length) * 100).toFixed(1) : 0}%\n`;
  texto += `- Agendamentos confirmados: ${agendamentosConfirmados}\n`;
  texto += `- Agendamentos cancelados: ${agendamentosCancelados}\n`;

  return texto;
}

// Exports
export { buscarTudo } from './dados';
export { chamarIA, detectarProvedor } from './provedores';
export * from './tipos';
