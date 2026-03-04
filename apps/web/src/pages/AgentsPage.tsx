import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Sidebar } from '@/components/Sidebar'
import { agentsService, type Agent } from '@/services/agents.service'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import {
  Bot,
  Plus,
  MoreVertical,
  Power,
  PowerOff,
  Trash2,
  Edit2,
  Loader2,
  RefreshCw,
  Wifi,
  WifiOff,
  MessageSquare,
  Users,
  X,
  QrCode,
  Smartphone,
  CheckCircle2,
} from 'lucide-react'

function AgentCard({
  agent,
  onToggleAI,
  onDelete,
  onEdit,
  onShowQRCode,
  isUpdating,
}: {
  agent: Agent
  onToggleAI: (id: string, enabled: boolean) => void
  onDelete: (id: string) => void
  onEdit: (agent: Agent) => void
  onShowQRCode: (agent: Agent) => void
  isUpdating: boolean
}) {
  const [showMenu, setShowMenu] = useState(false)

  const statusColor = {
    online: 'bg-green-500',
    offline: 'bg-gray-400',
    connecting: 'bg-yellow-500 animate-pulse',
  }

  return (
    <div className={cn(
      'bg-white rounded-xl border border-gray-100 shadow-sm p-6 relative',
      isUpdating && 'opacity-50 pointer-events-none'
    )}>
      {/* Menu button */}
      <div className="absolute top-4 right-4">
        <button
          onClick={() => setShowMenu(!showMenu)}
          className="p-1.5 hover:bg-gray-100 rounded-lg transition-colors"
        >
          <MoreVertical className="w-4 h-4 text-gray-400" />
        </button>
        {showMenu && (
          <>
            <div className="fixed inset-0 z-10" onClick={() => setShowMenu(false)} />
            <div className="absolute right-0 top-8 bg-white border border-gray-200 rounded-lg shadow-lg z-20 py-1 min-w-[160px]">
              <button
                onClick={() => {
                  onEdit(agent)
                  setShowMenu(false)
                }}
                className="w-full px-3 py-2 text-left text-sm hover:bg-gray-50 flex items-center gap-2"
              >
                <Edit2 className="w-4 h-4 text-gray-500" />
                Editar
              </button>
              <button
                onClick={() => {
                  onShowQRCode(agent)
                  setShowMenu(false)
                }}
                className="w-full px-3 py-2 text-left text-sm hover:bg-gray-50 flex items-center gap-2"
              >
                <QrCode className="w-4 h-4 text-gray-500" />
                Conectar WhatsApp
              </button>
              <button
                onClick={() => {
                  onToggleAI(agent.id, !agent.ai_enabled)
                  setShowMenu(false)
                }}
                className="w-full px-3 py-2 text-left text-sm hover:bg-gray-50 flex items-center gap-2"
              >
                {agent.ai_enabled ? (
                  <>
                    <PowerOff className="w-4 h-4 text-red-500" />
                    Desativar IA
                  </>
                ) : (
                  <>
                    <Power className="w-4 h-4 text-green-500" />
                    Ativar IA
                  </>
                )}
              </button>
              <div className="border-t border-gray-100 my-1" />
              <button
                onClick={() => {
                  if (confirm(`Tem certeza que deseja excluir o agente "${agent.name}"?`)) {
                    onDelete(agent.id)
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

      {/* Avatar */}
      <div className="flex items-center gap-4 mb-4">
        <div className="relative">
          <div className="w-14 h-14 rounded-full bg-gradient-to-br from-[#1a6eff] to-[#0052cc] flex items-center justify-center text-white text-xl font-medium">
            {agent.avatar_url ? (
              <img src={agent.avatar_url} alt={agent.name} className="w-full h-full rounded-full object-cover" />
            ) : (
              agent.name.charAt(0).toUpperCase()
            )}
          </div>
          <div className={cn('absolute -bottom-0.5 -right-0.5 w-4 h-4 rounded-full border-2 border-white', statusColor[agent.status])} />
        </div>
        <div>
          <h3 className="font-semibold text-gray-900">{agent.name}</h3>
          <p className="text-sm text-gray-500">{agent.type}</p>
        </div>
      </div>

      {/* Status badges */}
      <div className="flex flex-wrap gap-2 mb-4">
        <span
          className={cn(
            'inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium',
            agent.status === 'online' ? 'bg-green-50 text-green-700' : 'bg-gray-100 text-gray-600'
          )}
        >
          {agent.status === 'online' ? <Wifi className="w-3 h-3" /> : <WifiOff className="w-3 h-3" />}
          {agent.status === 'online' ? 'Conectado' : 'Desconectado'}
        </span>
        <span
          className={cn(
            'inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium',
            agent.ai_enabled ? 'bg-[#dcfce7] text-[#15803d]' : 'bg-[#f1f5f9] text-[#64748b]'
          )}
        >
          <Bot className="w-3 h-3" />
          {agent.ai_enabled ? 'IA Ativa' : 'IA Pausada'}
        </span>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-3 pt-4 border-t border-gray-100">
        <div className="flex items-center gap-2">
          <Users className="w-4 h-4 text-gray-400" />
          <span className="text-sm text-gray-600">
            <span className="font-medium text-gray-900">{agent.total_leads || 0}</span> leads
          </span>
        </div>
        <div className="flex items-center gap-2">
          <MessageSquare className="w-4 h-4 text-gray-400" />
          <span className="text-sm text-gray-600">
            <span className="font-medium text-gray-900">{agent.total_conversations || 0}</span> conversas
          </span>
        </div>
      </div>

      {/* Phone */}
      {agent.phone && (
        <p className="text-xs text-gray-400 mt-3">
          {agent.phone.replace('@s.whatsapp.net', '')}
        </p>
      )}
    </div>
  )
}

function CreateAgentModal({
  isOpen,
  onClose,
  onCreate,
  isCreating,
}: {
  isOpen: boolean
  onClose: () => void
  onCreate: (data: { name: string; type: string }) => void
  isCreating: boolean
}) {
  const [name, setName] = useState('')
  const [type, setType] = useState('vendas')

  useEffect(() => {
    if (isOpen) {
      setName('')
      setType('vendas')
    }
  }, [isOpen])

  if (!isOpen) return null

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    onCreate({ name: name.trim(), type })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative bg-white rounded-xl shadow-xl w-full max-w-md mx-4 p-6">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 p-1 hover:bg-gray-100 rounded-lg"
        >
          <X className="w-5 h-5 text-gray-400" />
        </button>

        <h2 className="text-xl font-semibold text-gray-900 mb-6">Criar novo agente</h2>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Nome do agente
            </label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Ex: Ana Vendas"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Tipo
            </label>
            <select
              value={type}
              onChange={(e) => setType(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#1a6eff] focus:border-transparent"
            >
              <option value="vendas">Vendas</option>
              <option value="suporte">Suporte</option>
              <option value="cobranca">Cobrança</option>
              <option value="agendamento">Agendamento</option>
              <option value="geral">Geral</option>
            </select>
          </div>

          <div className="flex gap-3 pt-4">
            <Button type="button" variant="outline" className="flex-1" onClick={onClose}>
              Cancelar
            </Button>
            <Button type="submit" className="flex-1" disabled={isCreating || !name.trim()}>
              {isCreating ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Criar'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}

function EditAgentModal({
  agent,
  onClose,
  onSave,
  isSaving,
}: {
  agent: Agent | null
  onClose: () => void
  onSave: (id: string, data: { name: string; type: string }) => void
  isSaving: boolean
}) {
  const [name, setName] = useState('')
  const [type, setType] = useState('vendas')

  useEffect(() => {
    if (agent) {
      setName(agent.name)
      setType(agent.type)
    }
  }, [agent])

  if (!agent) return null

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    onSave(agent.id, { name: name.trim(), type })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative bg-white rounded-xl shadow-xl w-full max-w-md mx-4 p-6">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 p-1 hover:bg-gray-100 rounded-lg"
        >
          <X className="w-5 h-5 text-gray-400" />
        </button>

        <h2 className="text-xl font-semibold text-gray-900 mb-6">Editar agente</h2>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Nome do agente
            </label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Ex: Ana Vendas"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Tipo
            </label>
            <select
              value={type}
              onChange={(e) => setType(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#1a6eff] focus:border-transparent"
            >
              <option value="vendas">Vendas</option>
              <option value="suporte">Suporte</option>
              <option value="cobranca">Cobrança</option>
              <option value="agendamento">Agendamento</option>
              <option value="geral">Geral</option>
            </select>
          </div>

          <div className="flex gap-3 pt-4">
            <Button type="button" variant="outline" className="flex-1" onClick={onClose}>
              Cancelar
            </Button>
            <Button type="submit" className="flex-1" disabled={isSaving || !name.trim()}>
              {isSaving ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Salvar'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}

function QRCodeModal({
  agent,
  onClose,
}: {
  agent: Agent | null
  onClose: () => void
}) {
  const [qrCode, setQrCode] = useState<string | null>(null)
  const [isConnected, setIsConnected] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!agent) return

    let intervalId: NodeJS.Timeout | null = null
    let mounted = true

    const fetchQRCode = async () => {
      try {
        setIsLoading(true)
        setError(null)
        const response = await agentsService.getQRCode(agent.id)

        if (!mounted) return

        if (response.connected) {
          setIsConnected(true)
          setQrCode(null)
          if (intervalId) clearInterval(intervalId)
        } else if (response.qrcode) {
          setQrCode(response.qrcode)
          setIsConnected(false)
        }
      } catch (err) {
        if (!mounted) return
        setError('Erro ao carregar QR Code')
      } finally {
        if (mounted) setIsLoading(false)
      }
    }

    fetchQRCode()
    intervalId = setInterval(fetchQRCode, 15000) // Refresh every 15 seconds

    return () => {
      mounted = false
      if (intervalId) clearInterval(intervalId)
    }
  }, [agent])

  if (!agent) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative bg-white rounded-xl shadow-xl w-full max-w-md mx-4 p-6">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 p-1 hover:bg-gray-100 rounded-lg"
        >
          <X className="w-5 h-5 text-gray-400" />
        </button>

        <div className="text-center">
          <div className="w-16 h-16 rounded-full bg-gradient-to-br from-[#1a6eff] to-[#0052cc] flex items-center justify-center text-white mx-auto mb-4">
            <Smartphone className="w-8 h-8" />
          </div>
          <h2 className="text-xl font-semibold text-gray-900 mb-2">Conectar WhatsApp</h2>
          <p className="text-gray-500 text-sm mb-6">
            {isConnected
              ? `${agent.name} está conectado ao WhatsApp`
              : `Escaneie o QR Code para conectar ${agent.name}`
            }
          </p>

          <div className="flex items-center justify-center min-h-[280px]">
            {isLoading ? (
              <div className="flex flex-col items-center gap-3">
                <Loader2 className="w-10 h-10 animate-spin text-[#1a6eff]" />
                <p className="text-sm text-gray-500">Carregando QR Code...</p>
              </div>
            ) : error ? (
              <div className="text-center">
                <p className="text-red-500 mb-4">{error}</p>
                <Button variant="outline" onClick={() => window.location.reload()}>
                  Tentar novamente
                </Button>
              </div>
            ) : isConnected ? (
              <div className="flex flex-col items-center gap-4">
                <div className="w-20 h-20 rounded-full bg-green-100 flex items-center justify-center">
                  <CheckCircle2 className="w-10 h-10 text-green-600" />
                </div>
                <p className="text-green-600 font-medium">WhatsApp conectado</p>
                {agent.phone && (
                  <p className="text-gray-500 text-sm">
                    {agent.phone.replace('@s.whatsapp.net', '')}
                  </p>
                )}
              </div>
            ) : qrCode ? (
              <div className="p-4 bg-white border border-gray-200 rounded-xl">
                <img
                  src={qrCode.startsWith('data:') ? qrCode : `data:image/png;base64,${qrCode}`}
                  alt="QR Code WhatsApp"
                  className="w-64 h-64"
                />
              </div>
            ) : (
              <div className="text-center">
                <p className="text-gray-500 mb-4">QR Code não disponível</p>
                <Button variant="outline" onClick={() => window.location.reload()}>
                  Tentar novamente
                </Button>
              </div>
            )}
          </div>

          {!isConnected && !isLoading && (
            <div className="mt-6 p-4 bg-gray-50 rounded-lg text-left">
              <p className="text-sm font-medium text-gray-700 mb-2">Como conectar:</p>
              <ol className="text-sm text-gray-500 space-y-1 list-decimal list-inside">
                <li>Abra o WhatsApp no seu celular</li>
                <li>Vá em Configurações &gt; Aparelhos conectados</li>
                <li>Toque em "Conectar um aparelho"</li>
                <li>Escaneie o QR Code acima</li>
              </ol>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export function AgentsPage() {
  const queryClient = useQueryClient()
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [editingAgent, setEditingAgent] = useState<Agent | null>(null)
  const [qrCodeAgent, setQrCodeAgent] = useState<Agent | null>(null)

  const { data: response, isLoading, refetch, isFetching } = useQuery({
    queryKey: ['agents'],
    queryFn: () => agentsService.getAll(),
  })

  const agents = response?.data?.agents || []

  const toggleAIMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      agentsService.toggleAI(id, enabled),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agents'] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => agentsService.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agents'] })
    },
  })

  const createMutation = useMutation({
    mutationFn: (data: { name: string; type: string }) => agentsService.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agents'] })
      setShowCreateModal(false)
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: { name: string; type: string } }) =>
      agentsService.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agents'] })
      setEditingAgent(null)
    },
  })

  return (
    <div className="flex h-screen bg-gray-50">
      <div className="hidden md:block">
        <Sidebar activePath="/agents" />
      </div>

      <main className="flex-1 overflow-auto p-4 md:p-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Agentes</h1>
            <p className="text-gray-600">{agents.length} agentes cadastrados</p>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => refetch()}
              disabled={isFetching}
              className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
            >
              <RefreshCw className={cn('w-5 h-5', isFetching && 'animate-spin')} />
            </button>
            <Button onClick={() => setShowCreateModal(true)}>
              <Plus className="w-4 h-4 mr-2" />
              Novo agente
            </Button>
          </div>
        </div>

        {/* Content */}
        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="w-8 h-8 animate-spin text-[#1a6eff]" />
          </div>
        ) : agents.length === 0 ? (
          <div className="text-center py-12">
            <Bot className="w-16 h-16 mx-auto mb-4 text-gray-300" />
            <h3 className="text-lg font-medium text-gray-900 mb-2">Nenhum agente</h3>
            <p className="text-gray-500 mb-6">Crie seu primeiro agente para começar</p>
            <Button onClick={() => setShowCreateModal(true)}>
              <Plus className="w-4 h-4 mr-2" />
              Criar agente
            </Button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {agents.map((agent) => (
              <AgentCard
                key={agent.id}
                agent={agent}
                onToggleAI={(id, enabled) => toggleAIMutation.mutate({ id, enabled })}
                onDelete={(id) => deleteMutation.mutate(id)}
                onEdit={(agent) => setEditingAgent(agent)}
                onShowQRCode={(agent) => setQrCodeAgent(agent)}
                isUpdating={toggleAIMutation.isPending || deleteMutation.isPending}
              />
            ))}
          </div>
        )}
      </main>

      <CreateAgentModal
        isOpen={showCreateModal}
        onClose={() => setShowCreateModal(false)}
        onCreate={(data) => createMutation.mutate(data)}
        isCreating={createMutation.isPending}
      />

      <EditAgentModal
        agent={editingAgent}
        onClose={() => setEditingAgent(null)}
        onSave={(id, data) => updateMutation.mutate({ id, data })}
        isSaving={updateMutation.isPending}
      />

      <QRCodeModal
        agent={qrCodeAgent}
        onClose={() => setQrCodeAgent(null)}
      />
    </div>
  )
}

export default AgentsPage
