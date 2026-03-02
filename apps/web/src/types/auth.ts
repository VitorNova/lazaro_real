export interface User {
  id: string
  email: string
  name: string
  role: string
  created_at: string
}

export interface AuthResponse {
  status: 'success' | 'error'
  message?: string
  user?: User
  accessToken?: string
  refreshToken?: string
}

export interface LoginCredentials {
  email: string
  password: string
}

export interface RegisterCredentials {
  email: string
  password: string
  name: string
}
