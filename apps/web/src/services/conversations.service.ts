import api from './api'
import type {
  ConversationsResponse,
  MessagesResponse,
  AIStatusResponse,
} from '@/types/conversations'

export interface GetConversationsParams {
  agent_id?: string
  limit?: number
  offset?: number
}

export const conversationsService = {
  async getConversations(params?: GetConversationsParams): Promise<ConversationsResponse> {
    const { data } = await api.get<ConversationsResponse>('/conversations', { params })
    return data
  },

  async getMessages(phone: string, agent_id?: string): Promise<MessagesResponse> {
    const { data } = await api.get<MessagesResponse>(`/conversations/${phone}/messages`, {
      params: { agent_id },
    })
    return data
  },

  async toggleAI(phone: string): Promise<AIStatusResponse> {
    const { data } = await api.post<AIStatusResponse>(`/conversations/${phone}/toggle-ai`)
    return data
  },

  async getAIStatus(phone: string): Promise<AIStatusResponse> {
    const { data } = await api.get<AIStatusResponse>(`/conversations/${phone}/ai-status`)
    return data
  },

  async getProfilePicture(phone: string): Promise<string | null> {
    try {
      const { data } = await api.get<{ status: string; url?: string }>(
        `/conversations/${phone}/profile-picture`
      )
      return data.url || null
    } catch {
      return null
    }
  },
}

export default conversationsService
