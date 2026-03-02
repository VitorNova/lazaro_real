import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { User } from '@/types/auth'
import authService from '@/services/auth.service'

interface AuthState {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  error: string | null

  // Actions
  login: (email: string, password: string) => Promise<boolean>
  register: (email: string, password: string, name: string) => Promise<boolean>
  logout: () => Promise<void>
  checkAuth: () => Promise<void>
  clearError: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      isAuthenticated: false,
      isLoading: false,
      error: null,

      login: async (email: string, password: string) => {
        set({ isLoading: true, error: null })
        try {
          const response = await authService.login({ email, password })
          if (response.status === 'success' && response.user) {
            set({
              user: response.user,
              isAuthenticated: true,
              isLoading: false,
            })
            return true
          }
          set({ error: response.message || 'Login failed', isLoading: false })
          return false
        } catch (err: unknown) {
          const error = err as { response?: { data?: { message?: string } } }
          set({
            error: error.response?.data?.message || 'Login failed',
            isLoading: false,
          })
          return false
        }
      },

      register: async (email: string, password: string, name: string) => {
        set({ isLoading: true, error: null })
        try {
          const response = await authService.register({ email, password, name })
          if (response.status === 'success' && response.user) {
            set({
              user: response.user,
              isAuthenticated: true,
              isLoading: false,
            })
            return true
          }
          set({ error: response.message || 'Registration failed', isLoading: false })
          return false
        } catch (err: unknown) {
          const error = err as { response?: { data?: { message?: string } } }
          set({
            error: error.response?.data?.message || 'Registration failed',
            isLoading: false,
          })
          return false
        }
      },

      logout: async () => {
        set({ isLoading: true })
        try {
          await authService.logout()
        } finally {
          set({
            user: null,
            isAuthenticated: false,
            isLoading: false,
            error: null,
          })
        }
      },

      checkAuth: async () => {
        if (!authService.isAuthenticated()) {
          set({ isAuthenticated: false, user: null })
          return
        }

        set({ isLoading: true })
        try {
          const user = await authService.getMe()
          set({ user, isAuthenticated: true, isLoading: false })
        } catch {
          set({ user: null, isAuthenticated: false, isLoading: false })
        }
      },

      clearError: () => set({ error: null }),
    }),
    {
      name: 'auth-storage',
      partialize: (state) => ({
        user: state.user,
        isAuthenticated: state.isAuthenticated,
      }),
    }
  )
)
