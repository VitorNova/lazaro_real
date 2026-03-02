import api from './api'
import type { AuthResponse, LoginCredentials, RegisterCredentials, User } from '@/types/auth'

export const authService = {
  async login(credentials: LoginCredentials): Promise<AuthResponse> {
    const { data } = await api.post<AuthResponse>('/auth/login', credentials)
    if (data.accessToken && data.refreshToken) {
      localStorage.setItem('accessToken', data.accessToken)
      localStorage.setItem('refreshToken', data.refreshToken)
    }
    return data
  },

  async register(credentials: RegisterCredentials): Promise<AuthResponse> {
    const { data } = await api.post<AuthResponse>('/auth/register', credentials)
    if (data.accessToken && data.refreshToken) {
      localStorage.setItem('accessToken', data.accessToken)
      localStorage.setItem('refreshToken', data.refreshToken)
    }
    return data
  },

  async logout(): Promise<void> {
    const refreshToken = localStorage.getItem('refreshToken')
    try {
      await api.post('/auth/logout', { refreshToken })
    } finally {
      localStorage.removeItem('accessToken')
      localStorage.removeItem('refreshToken')
    }
  },

  async getMe(): Promise<User> {
    const { data } = await api.get<{ status: string; user: User }>('/auth/me')
    return data.user
  },

  async refreshToken(): Promise<AuthResponse> {
    const refreshToken = localStorage.getItem('refreshToken')
    const { data } = await api.post<AuthResponse>('/auth/refresh', { refreshToken })
    if (data.accessToken && data.refreshToken) {
      localStorage.setItem('accessToken', data.accessToken)
      localStorage.setItem('refreshToken', data.refreshToken)
    }
    return data
  },

  isAuthenticated(): boolean {
    return !!localStorage.getItem('accessToken')
  },
}

export default authService
