export interface Lead {
  id: number;
  nome: string;
  telefone: string;
  email: string;
  empresa: string;
  cidade: string;
  status: string;
  pipeline_step: string;
  lead_temperature: string;
  lead_origin: string;
  source: string;
  valor: number;
  bant_budget: number;
  bant_authority: number;
  bant_need: number;
  bant_timing: number;
  bant_total: number;
  bant_notes: string;
  resumo: string;
  ultimo_intent: string;
  responsavel: string;
  venda_realizada: boolean;
  next_appointment_at: string;
  next_appointment_link: string;
  follow_count: number;
  journey_stage: string;
  created_date: string;
  updated_date: string;
}

export interface Agendamento {
  id: string;
  agent_id: string;
  customer_name: string;
  company_name: string;
  scheduled_at: string;
  ends_at: string;
  status: string;
  meeting_link: string;
  service_name: string;
  created_at: string;
}

export interface Followup {
  id: string;
  parent_agent_id: string;
  status: string;
  sent_at: string;
}

export interface Agente {
  id: string;
  name: string;
  type: string;
  status: string;
  table_leads: string;
  table_messages: string;
  system_prompt: string;
  gemini_api_key: string;
  claude_api_key: string;
  openai_api_key: string;
}

export interface DadosAthena {
  leads: Lead[];
  agendamentos: Agendamento[];
  followups: Followup[];
  agentes: Agente[];
}

export type Provedor = 'claude' | 'openai' | 'gemini';

export interface ConfigIA {
  provedor: Provedor;
  apiKey: string;
}
