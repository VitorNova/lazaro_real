import { Search, Bot, User, Loader2 } from 'lucide-react'
import { Input } from '@/components/ui/input'
import type { Conversation } from '@/types/conversations'
import { cn } from '@/lib/utils'

interface ConversationListProps {
  conversations: Conversation[]
  selectedId?: string
  searchQuery: string
  onSearchChange: (query: string) => void
  onSelect: (conversation: Conversation) => void
  isLoading?: boolean
  error?: string
}

function formatTime(dateStr: string): string {
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))

  if (diffDays === 0) {
    return date.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
  } else if (diffDays === 1) {
    return 'Ontem'
  } else if (diffDays < 7) {
    return date.toLocaleDateString('pt-BR', { weekday: 'short' })
  } else {
    return date.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })
  }
}

function formatPhone(phone: string): string {
  // Remove @s.whatsapp.net and format
  const cleaned = phone.replace('@s.whatsapp.net', '').replace(/\D/g, '')
  if (cleaned.length === 13 && cleaned.startsWith('55')) {
    const ddd = cleaned.slice(2, 4)
    const part1 = cleaned.slice(4, 9)
    const part2 = cleaned.slice(9)
    return `(${ddd}) ${part1}-${part2}`
  }
  return phone.replace('@s.whatsapp.net', '')
}

export function ConversationList({
  conversations,
  selectedId,
  searchQuery,
  onSearchChange,
  onSelect,
  isLoading,
  error,
}: ConversationListProps) {
  return (
    <>
      {/* Header */}
      <div className="p-4 border-b border-[hsl(var(--border))]">
        <h2 className="text-lg font-semibold mb-3">Conversas</h2>
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
          <Input
            placeholder="Buscar conversa..."
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            className="pl-9"
          />
        </div>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-blue-600" />
          </div>
        ) : error ? (
          <div className="p-4 text-center text-red-500 text-sm">{error}</div>
        ) : conversations.length === 0 ? (
          <div className="p-4 text-center text-gray-500 text-sm">
            {searchQuery ? 'Nenhuma conversa encontrada' : 'Nenhuma conversa'}
          </div>
        ) : (
          conversations.map((conversation) => (
            <button
              key={conversation.id}
              onClick={() => onSelect(conversation)}
              className={cn(
                'w-full flex items-start gap-3 p-4 hover:bg-gray-50 transition-colors text-left border-b border-gray-100',
                selectedId === conversation.id && 'bg-blue-50 hover:bg-blue-50'
              )}
            >
              {/* Avatar */}
              <div className="relative">
                <div className="w-12 h-12 rounded-full bg-gradient-to-br from-blue-400 to-blue-600 flex items-center justify-center text-white font-medium">
                  {conversation.name.charAt(0).toUpperCase()}
                </div>
                {/* AI Status indicator */}
                <div
                  className={cn(
                    'absolute -bottom-0.5 -right-0.5 w-5 h-5 rounded-full flex items-center justify-center border-2 border-white',
                    conversation.ai_enabled ? 'bg-green-500' : 'bg-gray-400'
                  )}
                  title={conversation.ai_enabled ? 'IA ativa' : 'IA pausada'}
                >
                  {conversation.ai_enabled ? (
                    <Bot className="w-3 h-3 text-white" />
                  ) : (
                    <User className="w-3 h-3 text-white" />
                  )}
                </div>
              </div>

              {/* Content */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between mb-1">
                  <span className="font-medium text-gray-900 truncate">
                    {conversation.name}
                  </span>
                  <span className="text-xs text-gray-500 flex-shrink-0 ml-2">
                    {formatTime(conversation.lastMessageAt)}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <p className="text-sm text-gray-500 truncate pr-2">
                    {conversation.lastMessage || 'Sem mensagens'}
                  </p>
                  {conversation.unreadCount > 0 && (
                    <span className="bg-blue-600 text-white text-xs rounded-full px-2 py-0.5 flex-shrink-0">
                      {conversation.unreadCount}
                    </span>
                  )}
                </div>
                <p className="text-xs text-gray-400 mt-1">
                  {formatPhone(conversation.phone)} • {conversation.agent_name}
                </p>
              </div>
            </button>
          ))
        )}
      </div>
    </>
  )
}

export default ConversationList
