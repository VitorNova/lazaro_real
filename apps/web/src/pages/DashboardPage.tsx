import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAuthStore } from '@/stores/auth.store'
import { Sidebar } from '@/components/Sidebar'
import { dashboardService, type Period, type DashboardStats } from '@/services/dashboard.service'
import {
  MessageSquare,
  Users,
  Calendar,
  Clock,
  TrendingUp,
  ArrowUpRight,
  ArrowDownRight,
  Loader2,
  Bot,
  DollarSign,
  RefreshCw,
} from 'lucide-react'
import { cn } from '@/lib/utils'

// ============================================================================
// COMPONENTS
// ============================================================================

function StatCard({
  label,
  value,
  change,
  icon: Icon,
  color,
  isLoading,
}: {
  label: string
  value: string | number
  change?: string
  icon: React.ElementType
  color: 'blue' | 'purple' | 'green' | 'yellow' | 'red' | 'orange'
  isLoading?: boolean
}) {
  const colorMap = {
    blue: 'text-blue-600 bg-blue-50',
    purple: 'text-purple-600 bg-purple-50',
    green: 'text-green-600 bg-green-50',
    yellow: 'text-yellow-600 bg-yellow-50',
    red: 'text-red-600 bg-red-50',
    orange: 'text-orange-600 bg-orange-50',
  }

  const isPositive = change?.startsWith('+')
  const isNegative = change?.startsWith('-')

  return (
    <div className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm hover:shadow-md transition-shadow">
      <div className="flex items-center justify-between mb-4">
        <span className="text-gray-500 text-sm font-medium">{label}</span>
        <div className={`p-2 rounded-lg ${colorMap[color]}`}>
          <Icon className="h-5 w-5" />
        </div>
      </div>
      {isLoading ? (
        <div className="flex items-center gap-2">
          <Loader2 className="w-5 h-5 animate-spin text-gray-400" />
          <span className="text-gray-400">Carregando...</span>
        </div>
      ) : (
        <>
          <p className="text-3xl font-bold text-gray-900">{value}</p>
          {change && (
            <div className="flex items-center gap-1 mt-2">
              {isPositive ? (
                <ArrowUpRight className="w-4 h-4 text-green-500" />
              ) : isNegative ? (
                <ArrowDownRight className="w-4 h-4 text-red-500" />
              ) : null}
              <span
                className={cn(
                  'text-sm font-medium',
                  isPositive && 'text-green-600',
                  isNegative && 'text-red-600',
                  !isPositive && !isNegative && 'text-gray-500'
                )}
              >
                {change}
              </span>
              <span className="text-sm text-gray-400">vs período anterior</span>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function AgentCard({
  agent,
}: {
  agent: DashboardStats['agentsPerformance'][0]
}) {
  const colorMap: Record<string, string> = {
    violet: 'from-violet-400 to-violet-600',
    amber: 'from-amber-400 to-amber-600',
    blue: 'from-blue-400 to-blue-600',
    gray: 'from-gray-400 to-gray-600',
  }

  return (
    <div className="bg-white rounded-xl border border-gray-100 p-4">
      <div className="flex items-center gap-3 mb-3">
        <div
          className={cn(
            'w-10 h-10 rounded-full flex items-center justify-center text-white font-medium bg-gradient-to-br',
            colorMap[agent.color] || colorMap.gray
          )}
        >
          {agent.name.charAt(0)}
        </div>
        <div className="flex-1">
          <h4 className="font-medium text-gray-900">{agent.name}</h4>
          <p className="text-xs text-gray-500">{agent.type}</p>
        </div>
        <div
          className={cn(
            'px-2 py-1 rounded-full text-xs font-medium',
            agent.status === 'online'
              ? 'bg-green-100 text-green-700'
              : 'bg-gray-100 text-gray-500'
          )}
        >
          {agent.status === 'online' ? 'Online' : 'Offline'}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 text-sm">
        {Object.entries(agent.metrics)
          .filter(([_, v]) => typeof v === 'number' || typeof v === 'string')
          .slice(0, 4)
          .map(([key, value]) => (
            <div key={key} className="bg-gray-50 rounded-lg p-2">
              <p className="text-gray-500 text-xs capitalize">
                {key.replace(/([A-Z])/g, ' $1').trim()}
              </p>
              <p className="font-medium text-gray-900">{String(value)}</p>
            </div>
          ))}
      </div>

      <p className="text-xs text-gray-400 mt-3">{agent.lastActivity}</p>
    </div>
  )
}

function PeriodSelector({
  value,
  onChange,
}: {
  value: Period
  onChange: (period: Period) => void
}) {
  const options: { value: Period; label: string }[] = [
    { value: 'day', label: 'Hoje' },
    { value: 'week', label: 'Semana' },
    { value: 'month', label: 'Mês' },
    { value: 'total', label: 'Total' },
  ]

  return (
    <div className="flex bg-gray-100 rounded-lg p-1">
      {options.map((opt) => (
        <button
          key={opt.value}
          onClick={() => onChange(opt.value)}
          className={cn(
            'px-3 py-1.5 text-sm font-medium rounded-md transition-colors',
            value === opt.value
              ? 'bg-white text-gray-900 shadow-sm'
              : 'text-gray-600 hover:text-gray-900'
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}

// ============================================================================
// MAIN PAGE
// ============================================================================

export function DashboardPage() {
  const { user } = useAuthStore()
  const [period, setPeriod] = useState<Period>('week')

  const {
    data: statsResponse,
    isLoading,
    error,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ['dashboard-stats', period],
    queryFn: () => dashboardService.getStats(period),
    refetchInterval: 60000, // Refresh every minute
  })

  const stats = statsResponse?.data

  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat('pt-BR', {
      style: 'currency',
      currency: 'BRL',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value)
  }

  return (
    <div className="flex h-screen bg-gray-50">
      <Sidebar activePath="/" />

      <main className="flex-1 overflow-auto p-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
            <p className="text-gray-600">Bem-vindo, {user?.name || 'Usuário'}!</p>
          </div>
          <div className="flex items-center gap-4">
            <button
              onClick={() => refetch()}
              disabled={isFetching}
              className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
            >
              <RefreshCw className={cn('w-5 h-5', isFetching && 'animate-spin')} />
            </button>
            <PeriodSelector value={period} onChange={setPeriod} />
          </div>
        </div>

        {error ? (
          <div className="bg-red-50 text-red-600 p-4 rounded-lg mb-8">
            Erro ao carregar dados do dashboard. Tente novamente.
          </div>
        ) : null}

        {/* Main Stats Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
          <StatCard
            label="Total de Leads"
            value={stats?.totalLeads ?? '-'}
            change={stats?.totalLeadsChange}
            icon={Users}
            color="blue"
            isLoading={isLoading}
          />
          <StatCard
            label="Taxa de Conversão"
            value={stats ? `${stats.conversionRate}%` : '-'}
            change={stats?.conversionRateChange}
            icon={TrendingUp}
            color="green"
            isLoading={isLoading}
          />
          <StatCard
            label="Agendamentos"
            value={stats?.schedulesTotal ?? '-'}
            change={stats?.schedulesTotalChange}
            icon={Calendar}
            color="purple"
            isLoading={isLoading}
          />
          <StatCard
            label="Fora do Horário"
            value={stats?.leadsOutsideHours ?? '-'}
            change={stats?.leadsOutsideHoursChange}
            icon={Clock}
            color="orange"
            isLoading={isLoading}
          />
        </div>

        {/* Financial & Follow-up Row */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
          <StatCard
            label="Valor Recuperado"
            value={stats ? formatCurrency(stats.recoveredAmount) : '-'}
            change={stats?.recoveredAmountChange}
            icon={DollarSign}
            color="green"
            isLoading={isLoading}
          />
          <StatCard
            label="A Receber"
            value={stats ? formatCurrency(stats.pendingAmount) : '-'}
            icon={DollarSign}
            color="yellow"
            isLoading={isLoading}
          />
          <StatCard
            label="Follow-ups Enviados"
            value={stats?.followUpsSent ?? '-'}
            icon={MessageSquare}
            color="blue"
            isLoading={isLoading}
          />
          <StatCard
            label="Leads em IA"
            value={stats?.leadsInAI ?? '-'}
            icon={Bot}
            color="purple"
            isLoading={isLoading}
          />
        </div>

        {/* Two Column Layout */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
          {/* Lead Sources */}
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm">
            <div className="p-6 border-b border-gray-100">
              <h2 className="text-lg font-semibold text-gray-900">Origem dos Leads</h2>
            </div>
            <div className="p-6">
              {isLoading ? (
                <div className="flex items-center justify-center h-48">
                  <Loader2 className="w-8 h-8 animate-spin text-blue-600" />
                </div>
              ) : stats?.leadSources && stats.leadSources.length > 0 ? (
                <div className="space-y-4">
                  {stats.leadSources.slice(0, 5).map((source) => (
                    <div key={source.originKey} className="flex items-center gap-3">
                      <div
                        className="w-3 h-3 rounded-full"
                        style={{ backgroundColor: source.color }}
                      />
                      <span className="flex-1 text-sm text-gray-700">{source.name}</span>
                      <span className="text-sm font-medium text-gray-900">
                        {source.count}
                      </span>
                      <span className="text-sm text-gray-500">{source.value}%</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="flex items-center justify-center h-48 text-gray-400">
                  <p>Nenhum lead registrado</p>
                </div>
              )}
            </div>
          </div>

          {/* Temperature Distribution */}
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm">
            <div className="p-6 border-b border-gray-100">
              <h2 className="text-lg font-semibold text-gray-900">Temperatura dos Leads</h2>
            </div>
            <div className="p-6">
              {isLoading ? (
                <div className="flex items-center justify-center h-48">
                  <Loader2 className="w-8 h-8 animate-spin text-blue-600" />
                </div>
              ) : stats?.leadsByTemperature ? (
                <div className="space-y-4">
                  <div className="flex items-center gap-3">
                    <div className="w-3 h-3 rounded-full bg-red-500" />
                    <span className="flex-1 text-sm text-gray-700">Quente</span>
                    <span className="text-sm font-medium text-gray-900">
                      {stats.leadsByTemperature.hot}
                    </span>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="w-3 h-3 rounded-full bg-yellow-500" />
                    <span className="flex-1 text-sm text-gray-700">Morno</span>
                    <span className="text-sm font-medium text-gray-900">
                      {stats.leadsByTemperature.warm}
                    </span>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="w-3 h-3 rounded-full bg-blue-500" />
                    <span className="flex-1 text-sm text-gray-700">Frio</span>
                    <span className="text-sm font-medium text-gray-900">
                      {stats.leadsByTemperature.cold}
                    </span>
                  </div>

                  {/* Visual bar */}
                  <div className="mt-4 h-4 rounded-full overflow-hidden flex bg-gray-100">
                    {(() => {
                      const total =
                        stats.leadsByTemperature.hot +
                        stats.leadsByTemperature.warm +
                        stats.leadsByTemperature.cold
                      if (total === 0) return null
                      const hotPct = (stats.leadsByTemperature.hot / total) * 100
                      const warmPct = (stats.leadsByTemperature.warm / total) * 100
                      const coldPct = (stats.leadsByTemperature.cold / total) * 100
                      return (
                        <>
                          <div
                            className="bg-red-500 h-full"
                            style={{ width: `${hotPct}%` }}
                          />
                          <div
                            className="bg-yellow-500 h-full"
                            style={{ width: `${warmPct}%` }}
                          />
                          <div
                            className="bg-blue-500 h-full"
                            style={{ width: `${coldPct}%` }}
                          />
                        </>
                      )
                    })()}
                  </div>
                </div>
              ) : (
                <div className="flex items-center justify-center h-48 text-gray-400">
                  <p>Nenhum dado disponível</p>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Pipeline Funnel */}
        {stats?.pipelineFunnel && stats.pipelineFunnel.length > 0 && (
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm mb-8">
            <div className="p-6 border-b border-gray-100">
              <h2 className="text-lg font-semibold text-gray-900">Funil de Pipeline</h2>
            </div>
            <div className="p-6">
              <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
                {stats.pipelineFunnel.map((stage) => (
                  <div
                    key={stage.etapa}
                    className="text-center p-4 bg-gray-50 rounded-lg"
                  >
                    <p className="text-2xl font-bold text-gray-900">
                      {stage.quantidade}
                    </p>
                    <p className="text-sm text-gray-500 truncate" title={stage.etapa}>
                      {stage.etapa}
                    </p>
                    <p className="text-xs text-gray-400">{stage.percentual}%</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Agents Performance */}
        {stats?.agentsPerformance && stats.agentsPerformance.length > 0 && (
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm">
            <div className="p-6 border-b border-gray-100">
              <h2 className="text-lg font-semibold text-gray-900">
                Performance dos Agentes
              </h2>
            </div>
            <div className="p-6">
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {stats.agentsPerformance.map((agent) => (
                  <AgentCard key={agent.id} agent={agent} />
                ))}
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}

export default DashboardPage
