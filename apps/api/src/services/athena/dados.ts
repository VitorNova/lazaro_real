import { supabaseAdmin } from '../supabase/client';
import { Lead, Agendamento, Followup, Agente, DadosAthena } from './tipos';

export async function buscarTudo(usuarioId: string): Promise<DadosAthena> {
  const agentes = await buscarAgentes(usuarioId);
  const leads = await buscarLeads(agentes);
  const agendamentos = await buscarAgendamentos(agentes);
  const followups = await buscarFollowups(agentes);

  return { leads, agendamentos, followups, agentes };
}

async function buscarAgentes(usuarioId: string): Promise<Agente[]> {
  const { data, error } = await supabaseAdmin
    .from('agents')
    .select('*')
    .eq('user_id', usuarioId);

  if (error) {
    console.error('[Athena] Erro ao buscar agentes:', error);
    return [];
  }

  return data || [];
}

async function buscarLeads(agentes: Agente[]): Promise<Lead[]> {
  const todosLeads: Lead[] = [];

  for (const agente of agentes) {
    if (!agente.table_leads) continue;

    try {
      const { data, error } = await supabaseAdmin
        .from(agente.table_leads)
        .select('*')
        .order('created_date', { ascending: false })
        .limit(200);

      if (error) {
        console.error(`[Athena] Erro ao buscar leads de ${agente.name}:`, error);
        continue;
      }

      if (data) {
        // Adiciona nome do agente em cada lead para referência
        const leadsComAgente = data.map(lead => ({
          ...lead,
          _agente: agente.name
        }));
        todosLeads.push(...leadsComAgente);
      }
    } catch (err) {
      console.error(`[Athena] Erro ao buscar leads:`, err);
    }
  }

  return todosLeads;
}

async function buscarAgendamentos(agentes: Agente[]): Promise<Agendamento[]> {
  const ids = agentes.map(a => a.id);

  if (ids.length === 0) return [];

  const { data, error } = await supabaseAdmin
    .from('schedules')
    .select('*')
    .in('agent_id', ids)
    .order('scheduled_at', { ascending: false })
    .limit(100);

  if (error) {
    console.error('[Athena] Erro ao buscar agendamentos:', error);
    return [];
  }

  return data || [];
}

async function buscarFollowups(agentes: Agente[]): Promise<Followup[]> {
  const ids = agentes.map(a => a.id);

  if (ids.length === 0) return [];

  const { data, error } = await supabaseAdmin
    .from('salvador_scheduled_followups')
    .select('*')
    .in('parent_agent_id', ids);

  if (error) {
    console.error('[Athena] Erro ao buscar followups:', error);
    return [];
  }

  return data || [];
}
