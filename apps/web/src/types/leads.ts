// ============================================================================
// PIPELINE TYPES
// ============================================================================

export interface PipelineStage {
  slug: string
  name: string
  color: string
  order: number
  description_for_ai?: string
}

export interface LeadInsights {
  summary?: string
  sentiment?: 'positivo' | 'neutro' | 'negativo'
  suggested_stage?: string
  auto_moved?: boolean
  ad_urls?: string[]
  origin?: string
  origin_reason?: string
  speakers?: {
    lead?: string
    human?: { name?: string; role?: string }
  }
}

export interface Lead {
  id: number
  nome: string | null
  telefone: string | null
  email: string | null
  empresa: string | null
  remotejid: string | null
  pipeline_step: string | null
  resumo: string | null
  Atendimento_Finalizado: string | null
  responsavel: string | null
  updated_date: string | null
  lead_origin: string | null
  ad_url: string | null
  transfer_reason: string | null
  handoff_at: string | null
  current_state: string | null
  insights: LeadInsights | null
  ia_ativa?: boolean
  // Qualification fields
  qualification_score?: number
  lead_temperature?: 'hot' | 'warm' | 'cold'
  bant_budget?: boolean
  bant_authority?: boolean
  bant_need?: boolean
  bant_timing?: boolean
}

export interface AgentWithLeads {
  id: string
  name: string
  table_leads: string
  agent_type?: string
  type?: string
  avatar_url?: string
  pipeline_stages: PipelineStage[]
  leads: Lead[]
  total_leads: number
  leads_attended_by_ai?: number
  uazapi_connected?: boolean
  uses_shared_whatsapp?: boolean
  parent_agent_id?: string | null
}

// ============================================================================
// API RESPONSE TYPES
// ============================================================================

export interface AgentsWithLeadsResponse {
  status: 'success' | 'error'
  data: {
    agents: AgentWithLeads[]
    total_agents: number
    total_leads: number
  }
}

export interface UpdatePipelineResponse {
  status: 'success' | 'error'
  data?: Lead
}

export interface ToggleAIResponse {
  status: 'success' | 'error'
  data?: Lead
  ai_enabled?: boolean
}
