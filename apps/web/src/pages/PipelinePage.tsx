import { useState, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Sidebar } from '@/components/Sidebar'
import { leadsService } from '@/services/leads.service'
import type { Lead, AgentWithLeads, PipelineStage } from '@/types/leads'
import { cn } from '@/lib/utils'
import {
  Loader2,
  RefreshCw,
  Bot,
  User,
  Phone,
  Building2,
  Clock,
  GripVertical,
  MoreVertical,
  Power,
  PowerOff,
  Trash2,
  MessageSquare,
  ChevronDown,
} from 'lucide-react'

// ============================================================================
// CONSTANTS
// ============================================================================

const STAGE_COLORS: Record<string, string> = {
  gray: 'bg-gray-100 border-gray-300 text-gray-700',
  blue: 'bg-blue-100 border-blue-300 text-blue-700',
  amber: 'bg-amber-100 border-amber-300 text-amber-700',
  violet: 'bg-violet-100 border-violet-300 text-violet-700',
  green: 'bg-green-100 border-green-300 text-green-700',
  red: 'bg-red-100 border-red-300 text-red-700',
  orange: 'bg-orange-100 border-orange-300 text-orange-700',
  cyan: 'bg-cyan-100 border-cyan-300 text-cyan-700',
  pink: 'bg-pink-100 border-pink-300 text-pink-700',
}

const STAGE_HEADER_COLORS: Record<string, string> = {
  gray: 'bg-gray-500',
  blue: 'bg-blue-500',
  amber: 'bg-amber-500',
  violet: 'bg-violet-500',
  green: 'bg-green-500',
  red: 'bg-red-500',
  orange: 'bg-orange-500',
  cyan: 'bg-cyan-500',
  pink: 'bg-pink-500',
}

// ============================================================================
// LEAD CARD COMPONENT
// ============================================================================

interface LeadCardProps {
  lead: Lead
  agentId: string
  onDragStart: (e: React.DragEvent, lead: Lead) => void
  onToggleAI: (leadId: number, enabled: boolean) => void
  onDelete: (leadId: number) => void
  isUpdating?: boolean
}

function LeadCard({
  lead,
  agentId,
  onDragStart,
  onToggleAI,
  onDelete,
  isUpdating,
}: LeadCardProps) {
  const [showMenu, setShowMenu] = useState(false)

  const formatPhone = (phone: string | null) => {
    if (!phone) return '-'
    const cleaned = phone.replace(/\D/g, '')
    if (cleaned.length === 11) {
      return `(${cleaned.slice(0, 2)}) ${cleaned.slice(2, 7)}-${cleaned.slice(7)}`
    }
    if (cleaned.length === 13 && cleaned.startsWith('55')) {
      return `(${cleaned.slice(2, 4)}) ${cleaned.slice(4, 9)}-${cleaned.slice(9)}`
    }
    return phone
  }

  const formatTimeAgo = (date: string | null) => {
    if (!date) return 'Nunca'
    const now = new Date()
    const then = new Date(date)
    const diffMs = now.getTime() - then.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffMins < 1) return 'Agora'
    if (diffMins < 60) return `${diffMins}min`
    if (diffHours < 24) return `${diffHours}h`
    return `${diffDays}d`
  }

  const getSentimentColor = (sentiment?: string) => {
    switch (sentiment) {
      case 'positivo':
        return 'text-green-600'
      case 'negativo':
        return 'text-red-600'
      default:
        return 'text-gray-500'
    }
  }

  return (
    <div
      draggable
      onDragStart={(e) => onDragStart(e, lead)}
      className={cn(
        'bg-white rounded-lg border border-gray-200 p-3 cursor-grab active:cursor-grabbing',
        'hover:shadow-md transition-shadow relative group',
        isUpdating && 'opacity-50 pointer-events-none'
      )}
    >
      {/* Drag handle */}
      <div className="absolute left-1 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-50 transition-opacity">
        <GripVertical className="w-4 h-4 text-gray-400" />
      </div>

      {/* Header */}
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2 flex-1 min-w-0">
          {/* AI Status */}
          <div
            className={cn(
              'w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0',
              lead.ia_ativa ? 'bg-green-100' : 'bg-gray-100'
            )}
          >
            {lead.ia_ativa ? (
              <Bot className="w-3.5 h-3.5 text-green-600" />
            ) : (
              <User className="w-3.5 h-3.5 text-gray-500" />
            )}
          </div>
          <span className="font-medium text-gray-900 truncate">
            {lead.nome || 'Sem nome'}
          </span>
        </div>

        {/* Menu */}
        <div className="relative">
          <button
            onClick={() => setShowMenu(!showMenu)}
            className="p-1 rounded hover:bg-gray-100 opacity-0 group-hover:opacity-100 transition-opacity"
          >
            <MoreVertical className="w-4 h-4 text-gray-500" />
          </button>
          {showMenu && (
            <>
              <div
                className="fixed inset-0 z-10"
                onClick={() => setShowMenu(false)}
              />
              <div className="absolute right-0 top-6 bg-white border border-gray-200 rounded-lg shadow-lg z-20 py-1 min-w-[140px]">
                <button
                  onClick={() => {
                    onToggleAI(lead.id, !lead.ia_ativa)
                    setShowMenu(false)
                  }}
                  className="w-full px-3 py-2 text-left text-sm hover:bg-gray-50 flex items-center gap-2"
                >
                  {lead.ia_ativa ? (
                    <>
                      <PowerOff className="w-4 h-4 text-red-500" />
                      Pausar IA
                    </>
                  ) : (
                    <>
                      <Power className="w-4 h-4 text-green-500" />
                      Ativar IA
                    </>
                  )}
                </button>
                <button
                  onClick={() => {
                    if (confirm('Tem certeza que deseja excluir este lead?')) {
                      onDelete(lead.id)
                    }
                    setShowMenu(false)
                  }}
                  className="w-full px-3 py-2 text-left text-sm hover:bg-gray-50 flex items-center gap-2 text-red-600"
                >
                  <Trash2 className="w-4 h-4" />
                  Excluir
                </button>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Contact Info */}
      <div className="space-y-1 text-sm">
        {lead.telefone && (
          <div className="flex items-center gap-2 text-gray-600">
            <Phone className="w-3.5 h-3.5" />
            <span className="truncate">{formatPhone(lead.telefone)}</span>
          </div>
        )}
        {lead.empresa && (
          <div className="flex items-center gap-2 text-gray-600">
            <Building2 className="w-3.5 h-3.5" />
            <span className="truncate">{lead.empresa}</span>
          </div>
        )}
      </div>

      {/* Summary / Insights */}
      {(lead.resumo || lead.insights?.summary) && (
        <p className="text-xs text-gray-500 mt-2 line-clamp-2">
          {lead.insights?.summary || lead.resumo}
        </p>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between mt-3 pt-2 border-t border-gray-100">
        <div className="flex items-center gap-2">
          {lead.insights?.sentiment && (
            <span
              className={cn('text-xs font-medium', getSentimentColor(lead.insights.sentiment))}
            >
              {lead.insights.sentiment === 'positivo' && '😊'}
              {lead.insights.sentiment === 'negativo' && '😟'}
              {lead.insights.sentiment === 'neutro' && '😐'}
            </span>
          )}
          {lead.lead_origin && (
            <span className="text-xs text-gray-400 truncate max-w-[80px]">
              {lead.lead_origin}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1 text-xs text-gray-400">
          <Clock className="w-3 h-3" />
          {formatTimeAgo(lead.updated_date)}
        </div>
      </div>
    </div>
  )
}

// ============================================================================
// PIPELINE COLUMN COMPONENT
// ============================================================================

interface PipelineColumnProps {
  stage: PipelineStage
  leads: Lead[]
  agentId: string
  onDragStart: (e: React.DragEvent, lead: Lead) => void
  onDragOver: (e: React.DragEvent) => void
  onDrop: (e: React.DragEvent, stageSlug: string) => void
  onToggleAI: (leadId: number, enabled: boolean) => void
  onDelete: (leadId: number) => void
  updatingLeadId?: number
}

function PipelineColumn({
  stage,
  leads,
  agentId,
  onDragStart,
  onDragOver,
  onDrop,
  onToggleAI,
  onDelete,
  updatingLeadId,
}: PipelineColumnProps) {
  const [isDragOver, setIsDragOver] = useState(false)

  return (
    <div
      className={cn(
        'flex-shrink-0 w-72 bg-gray-50 rounded-xl flex flex-col max-h-full',
        isDragOver && 'ring-2 ring-blue-400 ring-opacity-50'
      )}
      onDragOver={(e) => {
        e.preventDefault()
        setIsDragOver(true)
        onDragOver(e)
      }}
      onDragLeave={() => setIsDragOver(false)}
      onDrop={(e) => {
        setIsDragOver(false)
        onDrop(e, stage.slug)
      }}
    >
      {/* Header */}
      <div className="p-3 border-b border-gray-200">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div
              className={cn('w-3 h-3 rounded-full', STAGE_HEADER_COLORS[stage.color] || 'bg-gray-500')}
            />
            <h3 className="font-medium text-gray-900">{stage.name}</h3>
          </div>
          <span
            className={cn(
              'px-2 py-0.5 rounded-full text-xs font-medium',
              STAGE_COLORS[stage.color] || STAGE_COLORS.gray
            )}
          >
            {leads.length}
          </span>
        </div>
      </div>

      {/* Cards */}
      <div className="flex-1 overflow-y-auto p-2 space-y-2">
        {leads.map((lead) => (
          <LeadCard
            key={lead.id}
            lead={lead}
            agentId={agentId}
            onDragStart={onDragStart}
            onToggleAI={onToggleAI}
            onDelete={onDelete}
            isUpdating={updatingLeadId === lead.id}
          />
        ))}
        {leads.length === 0 && (
          <div className="text-center py-8 text-gray-400 text-sm">
            Nenhum lead nesta etapa
          </div>
        )}
      </div>
    </div>
  )
}

// ============================================================================
// MAIN PAGE
// ============================================================================

export function PipelinePage() {
  const queryClient = useQueryClient()
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null)
  const [draggedLead, setDraggedLead] = useState<Lead | null>(null)
  const [updatingLeadId, setUpdatingLeadId] = useState<number | undefined>()

  // Fetch agents with leads
  const { data: response, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ['agents-with-leads'],
    queryFn: () => leadsService.getAgentsWithLeads(),
    refetchInterval: 30000, // Refresh every 30 seconds
  })

  const agents = response?.data?.agents || []
  const selectedAgent = selectedAgentId
    ? agents.find((a) => a.id === selectedAgentId)
    : agents[0]

  // Update pipeline mutation
  const updatePipelineMutation = useMutation({
    mutationFn: ({
      leadId,
      agentId,
      pipelineStep,
    }: {
      leadId: number
      agentId: string
      pipelineStep: string
    }) => leadsService.updatePipelineStep(leadId, agentId, pipelineStep),
    onMutate: ({ leadId }) => {
      setUpdatingLeadId(leadId)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agents-with-leads'] })
    },
    onSettled: () => {
      setUpdatingLeadId(undefined)
    },
  })

  // Toggle AI mutation
  const toggleAIMutation = useMutation({
    mutationFn: ({
      leadId,
      agentId,
      enabled,
    }: {
      leadId: number
      agentId: string
      enabled: boolean
    }) => leadsService.toggleAI(leadId, agentId, enabled),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agents-with-leads'] })
    },
  })

  // Delete lead mutation
  const deleteLeadMutation = useMutation({
    mutationFn: ({ leadId, agentId }: { leadId: number; agentId: string }) =>
      leadsService.deleteLead(leadId, agentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agents-with-leads'] })
    },
  })

  // Drag handlers
  const handleDragStart = useCallback((e: React.DragEvent, lead: Lead) => {
    setDraggedLead(lead)
    e.dataTransfer.effectAllowed = 'move'
  }, [])

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
  }, [])

  const handleDrop = useCallback(
    (e: React.DragEvent, stageSlug: string) => {
      e.preventDefault()
      if (!draggedLead || !selectedAgent) return

      // Don't update if dropping in same stage
      if (draggedLead.pipeline_step === stageSlug) {
        setDraggedLead(null)
        return
      }

      updatePipelineMutation.mutate({
        leadId: draggedLead.id,
        agentId: selectedAgent.id,
        pipelineStep: stageSlug,
      })

      setDraggedLead(null)
    },
    [draggedLead, selectedAgent, updatePipelineMutation]
  )

  const handleToggleAI = useCallback(
    (leadId: number, enabled: boolean) => {
      if (!selectedAgent) return
      toggleAIMutation.mutate({
        leadId,
        agentId: selectedAgent.id,
        enabled,
      })
    },
    [selectedAgent, toggleAIMutation]
  )

  const handleDelete = useCallback(
    (leadId: number) => {
      if (!selectedAgent) return
      deleteLeadMutation.mutate({
        leadId,
        agentId: selectedAgent.id,
      })
    },
    [selectedAgent, deleteLeadMutation]
  )

  // Group leads by pipeline step
  const getLeadsByStage = (agent: AgentWithLeads) => {
    const stages = agent.pipeline_stages || []
    const leadsByStage: Record<string, Lead[]> = {}

    // Initialize all stages
    stages.forEach((stage) => {
      leadsByStage[stage.slug] = []
    })

    // Group leads
    agent.leads.forEach((lead) => {
      const stageSlug = lead.pipeline_step || 'novo-lead'
      if (!leadsByStage[stageSlug]) {
        leadsByStage[stageSlug] = []
      }
      leadsByStage[stageSlug].push(lead)
    })

    return leadsByStage
  }

  return (
    <div className="flex h-screen bg-gray-100">
      <Sidebar activePath="/leads" />

      <main className="flex-1 flex flex-col overflow-hidden">
        {/* Header */}
        <div className="bg-white border-b border-gray-200 px-6 py-4">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold text-gray-900">Pipeline</h1>
              <p className="text-gray-600">
                {response?.data?.total_leads || 0} leads em{' '}
                {response?.data?.total_agents || 0} agentes
              </p>
            </div>

            <div className="flex items-center gap-4">
              {/* Agent Selector */}
              {agents.length > 1 && (
                <div className="relative">
                  <select
                    value={selectedAgent?.id || ''}
                    onChange={(e) => setSelectedAgentId(e.target.value)}
                    className="appearance-none bg-white border border-gray-300 rounded-lg px-4 py-2 pr-8 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    {agents.map((agent) => (
                      <option key={agent.id} value={agent.id}>
                        {agent.name} ({agent.total_leads})
                      </option>
                    ))}
                  </select>
                  <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500 pointer-events-none" />
                </div>
              )}

              {/* Refresh */}
              <button
                onClick={() => refetch()}
                disabled={isFetching}
                className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
              >
                <RefreshCw className={cn('w-5 h-5', isFetching && 'animate-spin')} />
              </button>
            </div>
          </div>
        </div>

        {/* Content */}
        {isLoading ? (
          <div className="flex-1 flex items-center justify-center">
            <Loader2 className="w-8 h-8 animate-spin text-blue-600" />
          </div>
        ) : error ? (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center">
              <p className="text-red-600 mb-2">Erro ao carregar leads</p>
              <button
                onClick={() => refetch()}
                className="text-blue-600 hover:underline"
              >
                Tentar novamente
              </button>
            </div>
          </div>
        ) : !selectedAgent ? (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center text-gray-500">
              <MessageSquare className="w-12 h-12 mx-auto mb-4 opacity-50" />
              <p>Nenhum agente encontrado</p>
              <p className="text-sm">Crie um agente para começar</p>
            </div>
          </div>
        ) : (
          <div className="flex-1 overflow-x-auto p-6">
            <div className="flex gap-4 h-full">
              {selectedAgent.pipeline_stages.map((stage) => {
                const leadsByStage = getLeadsByStage(selectedAgent)
                return (
                  <PipelineColumn
                    key={stage.slug}
                    stage={stage}
                    leads={leadsByStage[stage.slug] || []}
                    agentId={selectedAgent.id}
                    onDragStart={handleDragStart}
                    onDragOver={handleDragOver}
                    onDrop={handleDrop}
                    onToggleAI={handleToggleAI}
                    onDelete={handleDelete}
                    updatingLeadId={updatingLeadId}
                  />
                )
              })}
            </div>
          </div>
        )}
      </main>
    </div>
  )
}

export default PipelinePage
