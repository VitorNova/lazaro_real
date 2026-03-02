import api from './api'

export interface Agent {
  id: string
  name: string
  type: string
  phone?: string
  status: 'online' | 'offline' | 'connecting'
  ai_enabled: boolean
  avatar_url?: string
  created_at: string
  updated_at: string
  total_leads?: number
  total_conversations?: number
  settings?: {
    work_hours_start?: string
    work_hours_end?: string
    timezone?: string
    language?: string
  }
}

export interface CreateAgentData {
  name: string
  type: string
  phone?: string
  settings?: Record<string, unknown>
}

export interface UpdateAgentData {
  name?: string
  type?: string
  ai_enabled?: boolean
  settings?: Record<string, unknown>
}

interface AgentsResponse {
  status: 'success' | 'error'
  data: {
    agents: Agent[]
    total: number
  }
}

interface AgentResponse {
  status: 'success' | 'error'
  data: Agent
}

export const agentsService = {
  async getAll(): Promise<AgentsResponse> {
    const { data } = await api.get<AgentsResponse>('/agents')
    return data
  },

  async getById(id: string): Promise<AgentResponse> {
    const { data } = await api.get<AgentResponse>(`/agents/${id}`)
    return data
  },

  async create(agentData: CreateAgentData): Promise<AgentResponse> {
    const { data } = await api.post<AgentResponse>('/agents', agentData)
    return data
  },

  async update(id: string, agentData: UpdateAgentData): Promise<AgentResponse> {
    const { data } = await api.put<AgentResponse>(`/agents/${id}`, agentData)
    return data
  },

  async delete(id: string): Promise<{ status: string }> {
    const { data } = await api.delete<{ status: string }>(`/agents/${id}`)
    return data
  },

  async toggleAI(id: string, enabled: boolean): Promise<AgentResponse> {
    const { data } = await api.put<AgentResponse>(`/agents/${id}`, { ai_enabled: enabled })
    return data
  },

  async getQRCode(id: string): Promise<{ status: string; qrcode?: string; connected?: boolean }> {
    const { data } = await api.post<{ status: string; qrcode?: string; connected?: boolean }>(
      `/agents/${id}/qrcode`
    )
    return data
  },

  async getStatus(id: string): Promise<{ status: string; connected?: boolean; phone?: string }> {
    const { data } = await api.get<{ status: string; connected?: boolean; phone?: string }>(
      `/agents/${id}/status`
    )
    return data
  },
}

export default agentsService
