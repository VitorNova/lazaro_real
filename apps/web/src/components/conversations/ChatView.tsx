import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { conversationsService } from '@/services/conversations.service'
import type { Conversation, Message } from '@/types/conversations'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import {
  ArrowLeft,
  Bot,
  User,
  Phone,
  MoreVertical,
  FileText,
  Volume2,
  Loader2,
  Power,
  PowerOff,
} from 'lucide-react'

interface ChatViewProps {
  conversation: Conversation
  onAIToggled?: () => void
  onBack?: () => void
  showBackButton?: boolean
}

function formatTime(dateStr: string): string {
  const date = new Date(dateStr)
  return date.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
}

function formatPhone(phone: string): string {
  const cleaned = phone.replace('@s.whatsapp.net', '').replace(/\D/g, '')
  if (cleaned.length === 13 && cleaned.startsWith('55')) {
    const ddd = cleaned.slice(2, 4)
    const part1 = cleaned.slice(4, 9)
    const part2 = cleaned.slice(9)
    return `(${ddd}) ${part1}-${part2}`
  }
  return phone.replace('@s.whatsapp.net', '')
}

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.sender === 'user'

  const renderMedia = () => {
    switch (message.messageType) {
      case 'image':
        return (
          <div className="mb-2">
            <img
              src={message.mediaUrl}
              alt="Imagem"
              className="max-w-xs rounded-lg"
              loading="lazy"
            />
          </div>
        )
      case 'audio':
        return (
          <div className="flex items-center gap-2 mb-2">
            <Volume2 className="w-5 h-5" />
            <audio src={message.mediaUrl} controls className="max-w-[200px]" />
            {message.duration && (
              <span className="text-xs text-gray-500">
                {Math.floor(message.duration / 60)}:{String(message.duration % 60).padStart(2, '0')}
              </span>
            )}
          </div>
        )
      case 'video':
        return (
          <div className="mb-2">
            <video
              src={message.mediaUrl}
              controls
              className="max-w-xs rounded-lg"
            />
          </div>
        )
      case 'document':
        return (
          <a
            href={message.mediaUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 mb-2 p-2 bg-white/10 rounded-lg hover:bg-white/20"
          >
            <FileText className="w-5 h-5" />
            <span className="text-sm truncate">{message.fileName || 'Documento'}</span>
          </a>
        )
      default:
        return null
    }
  }

  return (
    <div className={cn('flex mb-4', isUser ? 'justify-start' : 'justify-end')}>
      <div
        className={cn(
          'max-w-[70%] px-4 py-2 shadow-sm',
          isUser
            ? 'bg-white text-[#1a1a2e] rounded-[16px_16px_16px_4px]'
            : 'bg-[#1a6eff] text-white rounded-[16px_16px_4px_16px]'
        )}
      >
        {/* Sender name for assistant messages */}
        {!isUser && message.sender_name && (
          <p className="text-xs opacity-75 mb-1">{message.sender_name}</p>
        )}

        {/* Media content */}
        {renderMedia()}

        {/* Text content */}
        {message.content && (
          <p className="text-sm whitespace-pre-wrap break-words">{message.content}</p>
        )}

        {/* Timestamp */}
        <p
          className={cn(
            'text-xs mt-1',
            isUser ? 'text-[#8a8fa3]' : 'text-white/70'
          )}
        >
          {formatTime(message.timestamp)}
        </p>
      </div>
    </div>
  )
}

export function ChatView({ conversation, onAIToggled, onBack, showBackButton }: ChatViewProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const [isTogglingAI, setIsTogglingAI] = useState(false)

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['messages', conversation.phone],
    queryFn: () => conversationsService.getMessages(conversation.phone, conversation.agent_id),
    refetchInterval: 10000,
  })

  const messages = data?.data?.messages || []
  const aiEnabled = data?.data?.lead?.ai_enabled ?? conversation.ai_enabled

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleToggleAI = async () => {
    setIsTogglingAI(true)
    try {
      await conversationsService.toggleAI(conversation.phone)
      refetch()
      onAIToggled?.()
    } catch (err) {
      console.error('Error toggling AI:', err)
    } finally {
      setIsTogglingAI(false)
    }
  }

  return (
    <>
      {/* Header */}
      <div className="flex items-center justify-between px-4 md:px-6 py-4 bg-white border-b border-[hsl(var(--border))]">
        <div className="flex items-center gap-3 md:gap-4">
          {/* Back button - only on mobile */}
          {showBackButton && (
            <button
              onClick={onBack}
              className="md:hidden p-2 -ml-2 hover:bg-gray-100 rounded-full transition-colors"
              aria-label="Voltar"
            >
              <ArrowLeft className="w-5 h-5 text-gray-600" />
            </button>
          )}

          {/* Avatar */}
          <div className="relative">
            <div className="w-10 h-10 md:w-12 md:h-12 rounded-full bg-gradient-to-br from-[#1a6eff] to-[#0052cc] flex items-center justify-center text-white font-medium text-base md:text-lg">
              {conversation.name.charAt(0).toUpperCase()}
            </div>
            <div
              className={cn(
                'absolute -bottom-0.5 -right-0.5 w-4 h-4 md:w-5 md:h-5 rounded-full flex items-center justify-center border-2 border-white',
                aiEnabled ? 'bg-[#15803d]' : 'bg-[#64748b]'
              )}
            >
              {aiEnabled ? (
                <Bot className="w-2.5 h-2.5 md:w-3 md:h-3 text-white" />
              ) : (
                <User className="w-2.5 h-2.5 md:w-3 md:h-3 text-white" />
              )}
            </div>
          </div>

          {/* Info */}
          <div className="min-w-0">
            <h3 className="font-semibold text-gray-900 truncate">{conversation.name}</h3>
            <p className="text-xs md:text-sm text-gray-500 flex items-center gap-1 md:gap-2">
              <Phone className="w-3 h-3 hidden md:inline" />
              <span className="truncate">{formatPhone(conversation.phone)}</span>
              <span className="text-gray-300 hidden md:inline">•</span>
              <span
                className={cn(
                  'hidden md:inline px-1.5 py-0.5 rounded text-xs font-medium',
                  aiEnabled ? 'bg-[#dcfce7] text-[#15803d]' : 'bg-[#f1f5f9] text-[#64748b]'
                )}
              >
                {aiEnabled ? 'IA ativa' : 'Humano'}
              </span>
            </p>
          </div>
        </div>

        <div className="flex items-center gap-1 md:gap-2">
          <Button
            variant={aiEnabled ? 'outline' : 'default'}
            size="sm"
            onClick={handleToggleAI}
            disabled={isTogglingAI}
            className="hidden md:flex"
          >
            {isTogglingAI ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : aiEnabled ? (
              <>
                <PowerOff className="w-4 h-4 mr-2" />
                Pausar IA
              </>
            ) : (
              <>
                <Power className="w-4 h-4 mr-2" />
                Ativar IA
              </>
            )}
          </Button>
          {/* Mobile toggle button */}
          <Button
            variant={aiEnabled ? 'outline' : 'default'}
            size="icon"
            onClick={handleToggleAI}
            disabled={isTogglingAI}
            className="md:hidden"
          >
            {isTogglingAI ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : aiEnabled ? (
              <PowerOff className="w-4 h-4" />
            ) : (
              <Power className="w-4 h-4" />
            )}
          </Button>
          <Button variant="ghost" size="icon">
            <MoreVertical className="w-5 h-5" />
          </Button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 md:p-6 bg-[#e8ecf1]">
        {isLoading ? (
          <div className="flex items-center justify-center h-full">
            <Loader2 className="w-8 h-8 animate-spin text-[#1a6eff]" />
          </div>
        ) : error ? (
          <div className="flex items-center justify-center h-full text-red-500">
            Erro ao carregar mensagens
          </div>
        ) : messages.length === 0 ? (
          <div className="flex items-center justify-center h-full text-gray-400">
            Nenhuma mensagem ainda
          </div>
        ) : (
          <>
            {messages.map((message, index) => (
              <MessageBubble key={message.id || index} message={message} />
            ))}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* Footer */}
      <div className="px-4 md:px-6 py-3 bg-white border-t border-[hsl(var(--border))] text-center text-xs md:text-sm text-gray-500 pb-[env(safe-area-inset-bottom)]">
        <p>
          Agente: <span className="font-medium">{conversation.agent_name}</span>
          {conversation.lead_id && (
            <>
              <span className="mx-2">•</span>
              Lead ID: <span className="font-medium">#{conversation.lead_id}</span>
            </>
          )}
        </p>
      </div>
    </>
  )
}

export default ChatView
