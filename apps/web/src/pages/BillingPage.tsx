import { useQuery } from '@tanstack/react-query'
import { Sidebar } from '@/components/Sidebar'
import { billingService } from '@/services/billing.service'
import { cn } from '@/lib/utils'
import {
  DollarSign,
  TrendingUp,
  Clock,
  AlertCircle,
  CreditCard,
  FileText,
  Loader2,
  RefreshCw,
  ArrowUpRight,
  ArrowDownRight,
  CheckCircle2,
  XCircle,
} from 'lucide-react'

function StatCard({
  label,
  value,
  change,
  icon: Icon,
  color,
  isLoading,
}: {
  label: string
  value: string
  change?: string
  icon: React.ElementType
  color: 'blue' | 'green' | 'yellow' | 'red'
  isLoading?: boolean
}) {
  const colorMap = {
    blue: 'text-[#1a6eff] bg-blue-50',
    green: 'text-green-600 bg-green-50',
    yellow: 'text-yellow-600 bg-yellow-50',
    red: 'text-red-600 bg-red-50',
  }

  const isPositive = change?.startsWith('+')
  const isNegative = change?.startsWith('-')

  return (
    <div className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm">
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
          <p className="text-2xl font-bold text-gray-900">{value}</p>
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
            </div>
          )}
        </>
      )}
    </div>
  )
}

function InvoiceRow({ invoice }: { invoice: { id: string; date: string; amount: string; status: string } }) {
  const statusConfig = {
    paid: { icon: CheckCircle2, color: 'text-green-600 bg-green-50', label: 'Pago' },
    pending: { icon: Clock, color: 'text-yellow-600 bg-yellow-50', label: 'Pendente' },
    overdue: { icon: XCircle, color: 'text-red-600 bg-red-50', label: 'Vencido' },
  }

  const config = statusConfig[invoice.status as keyof typeof statusConfig] || statusConfig.pending
  const StatusIcon = config.icon

  return (
    <div className="flex items-center justify-between py-3 border-b border-gray-100 last:border-0">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-lg bg-gray-50 flex items-center justify-center">
          <FileText className="w-5 h-5 text-gray-400" />
        </div>
        <div>
          <p className="font-medium text-gray-900">{invoice.amount}</p>
          <p className="text-sm text-gray-500">{invoice.date}</p>
        </div>
      </div>
      <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full ${config.color}`}>
        <StatusIcon className="w-3.5 h-3.5" />
        <span className="text-xs font-medium">{config.label}</span>
      </div>
    </div>
  )
}

export function BillingPage() {
  const {
    data: statsResponse,
    isLoading: statsLoading,
    refetch: refetchStats,
    isFetching: statsFetching,
  } = useQuery({
    queryKey: ['billing-stats'],
    queryFn: () => billingService.getStats(),
  })

  const { data: invoicesResponse, isLoading: invoicesLoading } = useQuery({
    queryKey: ['billing-invoices'],
    queryFn: () => billingService.getInvoices(10),
  })

  const stats = statsResponse?.data
  const invoices = invoicesResponse?.data?.invoices || []

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
      <div className="hidden md:block">
        <Sidebar activePath="/billing" />
      </div>

      <main className="flex-1 overflow-auto p-4 md:p-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Billing</h1>
            <p className="text-gray-600">Acompanhe cobranças e pagamentos</p>
          </div>
          <button
            onClick={() => refetchStats()}
            disabled={statsFetching}
            className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
          >
            <RefreshCw className={cn('w-5 h-5', statsFetching && 'animate-spin')} />
          </button>
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
          <StatCard
            label="Receita Total"
            value={stats ? formatCurrency(stats.totalRevenue || 0) : '-'}
            change={stats?.totalRevenueChange}
            icon={DollarSign}
            color="green"
            isLoading={statsLoading}
          />
          <StatCard
            label="A Receber"
            value={stats ? formatCurrency(stats.pendingAmount || 0) : '-'}
            change={stats?.pendingAmountChange}
            icon={Clock}
            color="yellow"
            isLoading={statsLoading}
          />
          <StatCard
            label="Vencido"
            value={stats ? formatCurrency(stats.overdueAmount || 0) : '-'}
            change={stats?.overdueAmountChange}
            icon={AlertCircle}
            color="red"
            isLoading={statsLoading}
          />
          <StatCard
            label="Pago este mês"
            value={stats ? formatCurrency(stats.paidThisMonth || 0) : '-'}
            change={stats?.paidThisMonthChange}
            icon={TrendingUp}
            color="blue"
            isLoading={statsLoading}
          />
        </div>

        {/* Two columns */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Plan Info */}
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm">
            <div className="p-6 border-b border-gray-100">
              <h2 className="text-lg font-semibold text-gray-900">Seu Plano</h2>
            </div>
            <div className="p-6">
              {statsLoading ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="w-6 h-6 animate-spin text-[#1a6eff]" />
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <span className="text-gray-500">Plano atual</span>
                    <span className="font-semibold text-gray-900">{stats?.planName || 'Gratuito'}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-gray-500">Valor mensal</span>
                    <span className="font-semibold text-gray-900">{stats?.planAmount || 'R$ 0'}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-gray-500">Próxima cobrança</span>
                    <span className="font-semibold text-gray-900">{stats?.nextInvoiceDate || '-'}</span>
                  </div>
                  <div className="pt-4 border-t border-gray-100">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-gray-500">Uso de tokens</span>
                      <span className="text-sm text-gray-600">
                        {stats?.tokenUsage?.toLocaleString() || 0} / {stats?.tokenLimit?.toLocaleString() || 0}
                      </span>
                    </div>
                    <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-[#1a6eff] rounded-full transition-all"
                        style={{
                          width: `${Math.min(((stats?.tokenUsage || 0) / (stats?.tokenLimit || 1)) * 100, 100)}%`,
                        }}
                      />
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Recent Invoices */}
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm">
            <div className="p-6 border-b border-gray-100 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-gray-900">Faturas Recentes</h2>
              <CreditCard className="w-5 h-5 text-gray-400" />
            </div>
            <div className="p-6">
              {invoicesLoading ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="w-6 h-6 animate-spin text-[#1a6eff]" />
                </div>
              ) : invoices.length === 0 ? (
                <div className="text-center py-8 text-gray-400">
                  <FileText className="w-12 h-12 mx-auto mb-3 opacity-50" />
                  <p>Nenhuma fatura encontrada</p>
                </div>
              ) : (
                <div>
                  {invoices.slice(0, 5).map((invoice) => (
                    <InvoiceRow key={invoice.id} invoice={invoice} />
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}

export default BillingPage
