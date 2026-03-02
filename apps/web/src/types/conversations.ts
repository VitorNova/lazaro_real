export interface Conversation {
  id: string
  phone: string
  name: string
  lastMessage: string
  lastMessageAt: string
  unreadCount: number
  agent_id: string
  agent_name: string
  ai_enabled: boolean
  lead_id?: number
}

export interface Message {
  id: string
  content: string
  sender: 'user' | 'assistant'
  timestamp: string
  type: string
  messageType?: 'text' | 'image' | 'audio' | 'document' | 'video'
  mediaUrl?: string
  fileName?: string
  mimeType?: string
  duration?: number
  sender_name?: string | null
}

export interface ConversationsResponse {
  status: 'success' | 'error'
  data: {
    conversations: Conversation[]
    total: number
    limit: number
    offset: number
    hasMore: boolean
  }
}

export interface MessagesResponse {
  status: 'success' | 'error'
  data: {
    messages: Message[]
    lead?: {
      id: number
      nome: string
      phone: string
      ai_enabled: boolean
    }
  }
}

export interface AIStatusResponse {
  status: 'success' | 'error'
  ai_enabled: boolean
}
