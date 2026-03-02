import api from './api'

// ============================================================================
// TYPES
// ============================================================================

export interface DashboardStats {
  // Métricas principais
  totalLeads: number
  totalLeadsChange: string
  // Métricas secundárias
  conversionRate: number
  conversionRateChange: string
  schedulesTotal: number
  schedulesTotalChange: string
  leadsOutsideHours: number
  leadsOutsideHoursChange: string
  // Métricas financeiras (Asaas)
  recoveredAmount: number
  recoveredAmountChange: string
  pendingAmount: number
  overdueAmount: number
  // Métricas de follow-up
  followUpsSent: number
  followUpResponseRate: number
  leadsReengaged: number
  // Métricas operacionais
  handoffsTotal: number
  leadsInAI: number
  // Funil detalhado
  pipelineFunnel: Array<{ etapa: string; quantidade: number; percentual: number }>
  // Dados visuais
  leadsByTemperature: { hot: number; warm: number; cold: number }
  leadsOverTime: Array<{ name: string; leads: number }>
  leadSources: Array<{
    name: string
    originKey: string
    count: number
    value: number
    color: string
    icon: string
  }>
  agentsPerformance: AgentPerformance[]
  // Período selecionado
  period: 'day' | 'week' | 'month' | 'total'
}

export interface AgentPerformance {
  id: string
  name: string
  type: string
  color: string
  status: 'online' | 'offline'
  metrics: Record<string, string | number | unknown[]>
  pipelineCards: Array<{ etapa: string; quantidade: number }>
  lastActivity: string
}

export type Period = 'day' | 'week' | 'month' | 'total'

interface StatsResponse {
  status: 'success' | 'error'
  data: DashboardStats
}

// ============================================================================
// SERVICE
// ============================================================================

export const dashboardService = {
  async getStats(period: Period = 'week'): Promise<StatsResponse> {
    const { data } = await api.get<StatsResponse>('/dashboard/stats', {
      params: { period },
    })
    return data
  },

  async getLeadsByCategory(
    category: 'total' | 'hot' | 'schedules' | 'outside_hours',
    period: Period = 'week'
  ) {
    const { data } = await api.get('/dashboard/stats/leads', {
      params: { category, period },
    })
    return data
  },

  async getLeadsByOrigin(origin: string, limit = 100) {
    const { data } = await api.get('/dashboard/stats/leads-by-origin', {
      params: { origin, limit },
    })
    return data
  },
}

export default dashboardService
