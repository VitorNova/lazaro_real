import api from './api'
import type {
  AgentsWithLeadsResponse,
  UpdatePipelineResponse,
  ToggleAIResponse,
} from '@/types/leads'

// ============================================================================
// LEADS SERVICE
// ============================================================================

export const leadsService = {
  /**
   * Get all agents with their leads and pipeline stages
   */
  async getAgentsWithLeads(): Promise<AgentsWithLeadsResponse> {
    const { data } = await api.get<AgentsWithLeadsResponse>('/dashboard/leads')
    return data
  },

  /**
   * Update lead pipeline step (for drag and drop)
   */
  async updatePipelineStep(
    leadId: number,
    agentId: string,
    pipelineStep: string
  ): Promise<UpdatePipelineResponse> {
    const { data } = await api.patch<UpdatePipelineResponse>(
      `/dashboard/leads/${leadId}/pipeline`,
      {
        agent_id: agentId,
        pipeline_step: pipelineStep,
      }
    )
    return data
  },

  /**
   * Toggle AI status for a lead
   */
  async toggleAI(
    leadId: number,
    agentId: string,
    enabled: boolean
  ): Promise<ToggleAIResponse> {
    const { data } = await api.patch<ToggleAIResponse>(
      `/dashboard/leads/${leadId}/toggle-ai`,
      {
        agent_id: agentId,
        enabled,
      }
    )
    return data
  },

  /**
   * Update lead details
   */
  async updateDetails(
    leadId: number,
    agentId: string,
    details: { nome?: string; telefone?: string; resumo?: string }
  ): Promise<UpdatePipelineResponse> {
    const { data } = await api.patch<UpdatePipelineResponse>(
      `/dashboard/leads/${leadId}/details`,
      {
        agent_id: agentId,
        ...details,
      }
    )
    return data
  },

  /**
   * Delete a lead
   */
  async deleteLead(leadId: number, agentId: string): Promise<{ status: string }> {
    const { data } = await api.delete(`/dashboard/leads/${leadId}`, {
      data: { agent_id: agentId },
    })
    return data
  },
}

export default leadsService
