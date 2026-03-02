import api from './api'

export interface BillingStats {
  totalRevenue: number
  totalRevenueChange?: string
  pendingAmount: number
  pendingAmountChange?: string
  overdueAmount: number
  overdueAmountChange?: string
  paidThisMonth: number
  paidThisMonthChange?: string
  tokenUsage: number
  tokenLimit: number
  planName: string
  planAmount: string
  nextInvoiceDate: string
  activeSubscriptions?: number
  pendingPayments?: number
  overduePayments?: number
  recentPayments?: Array<{
    id: string
    customerName: string
    amount: number
    status: string
    dueDate: string
  }>
  revenueByMonth?: Array<{
    month: string
    revenue: number
  }>
}

export interface TokenStatement {
  id: string
  agent: string
  task: string
  amount: string
  time: string
  created_at: string
}

export interface Invoice {
  id: string
  date: string
  amount: string
  status: 'paid' | 'pending' | 'overdue'
  pdf_url?: string
}

interface BillingStatsResponse {
  status: 'success' | 'error'
  data: BillingStats
}

interface TokenStatementResponse {
  status: 'success' | 'error'
  data: {
    statements: TokenStatement[]
    total: number
  }
}

interface InvoicesResponse {
  status: 'success' | 'error'
  data: {
    invoices: Invoice[]
    total: number
  }
}

export const billingService = {
  async getStats(agentId?: string): Promise<BillingStatsResponse> {
    const params = agentId ? { agent_id: agentId } : {}
    const { data } = await api.get<BillingStatsResponse>('/billing/stats', { params })
    return data
  },

  async getTokenStatement(limit = 50, offset = 0): Promise<TokenStatementResponse> {
    const { data } = await api.get<TokenStatementResponse>('/billing/token-statement', {
      params: { limit, offset },
    })
    return data
  },

  async getInvoices(limit = 20, offset = 0): Promise<InvoicesResponse> {
    const { data } = await api.get<InvoicesResponse>('/billing/invoices', {
      params: { limit, offset },
    })
    return data
  },
}

export default billingService
