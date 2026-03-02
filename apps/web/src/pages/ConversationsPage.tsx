import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { conversationsService } from '@/services/conversations.service'
import { ConversationList } from '@/components/conversations/ConversationList'
import { ChatView } from '@/components/conversations/ChatView'
import { Sidebar } from '@/components/Sidebar'
import type { Conversation } from '@/types/conversations'
import { MessageSquare } from 'lucide-react'

export function ConversationsPage() {
  const [selectedConversation, setSelectedConversation] = useState<Conversation | null>(null)
  const [searchQuery, setSearchQuery] = useState('')

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['conversations'],
    queryFn: () => conversationsService.getConversations({ limit: 100 }),
    refetchInterval: 30000,
  })

  const conversations = data?.data?.conversations || []

  const filteredConversations = conversations.filter(
    (conv) =>
      conv.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      conv.phone.includes(searchQuery) ||
      conv.lastMessage.toLowerCase().includes(searchQuery.toLowerCase())
  )

  const handleSelectConversation = (conversation: Conversation) => {
    setSelectedConversation(conversation)
  }

  const handleBack = () => {
    setSelectedConversation(null)
  }

  const handleAIToggled = () => {
    refetch()
  }

  return (
    <div className="flex h-screen bg-[hsl(var(--background))]">
      {/* Sidebar - hidden on mobile */}
      <div className="hidden md:block">
        <Sidebar activePath="/conversations" />
      </div>

      {/* Main content area */}
      <div className="flex-1 flex relative">
        {/*
          Mobile: Lista ou Chat (não ambos)
          Desktop: Split-view (lista + chat lado a lado)
        */}

        {/* Conversations List */}
        <div
          className={`
            ${selectedConversation ? 'hidden md:flex' : 'flex'}
            w-full md:w-[380px] border-r border-[hsl(var(--border))] flex-col bg-white
            pt-[env(safe-area-inset-top)]
          `}
        >
          <ConversationList
            conversations={filteredConversations}
            selectedId={selectedConversation?.id}
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
            onSelect={handleSelectConversation}
            isLoading={isLoading}
            error={error?.message}
          />
        </div>

        {/* Chat View */}
        <div
          className={`
            ${selectedConversation ? 'flex' : 'hidden md:flex'}
            flex-1 flex-col bg-[#e8ecf1]
            pt-[env(safe-area-inset-top)]
            pb-[env(safe-area-inset-bottom)]
          `}
        >
          {selectedConversation ? (
            <ChatView
              conversation={selectedConversation}
              onAIToggled={handleAIToggled}
              onBack={handleBack}
              showBackButton={true}
            />
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-gray-400">
              <MessageSquare className="w-16 h-16 mb-4" />
              <h3 className="text-xl font-medium mb-2">Selecione uma conversa</h3>
              <p className="text-sm">Escolha uma conversa da lista para visualizar</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default ConversationsPage
