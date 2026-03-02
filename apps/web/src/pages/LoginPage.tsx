import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/auth.store'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Eye, EyeOff, MessageSquare } from 'lucide-react'

export function LoginPage() {
  const navigate = useNavigate()
  const { login, isLoading, error, clearError } = useAuthStore()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    clearError()

    const success = await login(email, password)
    if (success) {
      navigate('/')
    }
  }

  return (
    <div className="flex min-h-screen">
      {/* Left Panel - Branding */}
      <div className="hidden lg:flex lg:w-1/2 bg-gradient-to-br from-blue-600 to-blue-800 text-white p-12 flex-col justify-between">
        <div>
          <div className="flex items-center gap-3 mb-8">
            <MessageSquare className="h-10 w-10" />
            <span className="text-2xl font-bold">Lazaro</span>
          </div>
          <h1 className="text-4xl font-bold mb-4">
            Gerencie suas conversas com inteligencia
          </h1>
          <p className="text-blue-100 text-lg">
            Automatize atendimentos, acompanhe leads e aumente suas vendas com IA.
          </p>
        </div>

        <div className="space-y-6">
          <div className="flex items-start gap-4">
            <div className="w-10 h-10 rounded-full bg-white/10 flex items-center justify-center flex-shrink-0">
              <span className="text-lg">1</span>
            </div>
            <div>
              <h3 className="font-semibold">Atendimento 24/7</h3>
              <p className="text-blue-100 text-sm">IA responde seus clientes a qualquer hora</p>
            </div>
          </div>
          <div className="flex items-start gap-4">
            <div className="w-10 h-10 rounded-full bg-white/10 flex items-center justify-center flex-shrink-0">
              <span className="text-lg">2</span>
            </div>
            <div>
              <h3 className="font-semibold">Dashboard completo</h3>
              <p className="text-blue-100 text-sm">Metricas e insights em tempo real</p>
            </div>
          </div>
          <div className="flex items-start gap-4">
            <div className="w-10 h-10 rounded-full bg-white/10 flex items-center justify-center flex-shrink-0">
              <span className="text-lg">3</span>
            </div>
            <div>
              <h3 className="font-semibold">Integracao WhatsApp</h3>
              <p className="text-blue-100 text-sm">Conecte seu numero em minutos</p>
            </div>
          </div>
        </div>

        <p className="text-blue-200 text-sm">
          &copy; 2026 Lazaro. Todos os direitos reservados.
        </p>
      </div>

      {/* Right Panel - Login Form */}
      <div className="w-full lg:w-1/2 flex items-center justify-center p-8">
        <div className="w-full max-w-md space-y-8">
          {/* Mobile Logo */}
          <div className="lg:hidden flex items-center justify-center gap-3 mb-8">
            <MessageSquare className="h-8 w-8 text-blue-600" />
            <span className="text-xl font-bold">Lazaro</span>
          </div>

          <div className="text-center">
            <h2 className="text-2xl font-bold">Bem-vindo de volta</h2>
            <p className="text-[hsl(var(--muted-foreground))] mt-2">
              Entre com suas credenciais para acessar
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-6">
            {error && (
              <div className="p-3 rounded-md bg-red-50 border border-red-200 text-red-700 text-sm">
                {error}
              </div>
            )}

            <div className="space-y-2">
              <label htmlFor="email" className="text-sm font-medium">
                Email
              </label>
              <Input
                id="email"
                type="email"
                placeholder="seu@email.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoComplete="email"
              />
            </div>

            <div className="space-y-2">
              <label htmlFor="password" className="text-sm font-medium">
                Senha
              </label>
              <div className="relative">
                <Input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  placeholder="********"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  autoComplete="current-password"
                  className="pr-10"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
                >
                  {showPassword ? (
                    <EyeOff className="h-4 w-4" />
                  ) : (
                    <Eye className="h-4 w-4" />
                  )}
                </button>
              </div>
            </div>

            <div className="flex items-center justify-between">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="rounded border-[hsl(var(--input))]"
                />
                Lembrar de mim
              </label>
              <a
                href="/forgot-password"
                className="text-sm text-blue-600 hover:underline"
              >
                Esqueceu a senha?
              </a>
            </div>

            <Button
              type="submit"
              className="w-full"
              size="lg"
              isLoading={isLoading}
            >
              Entrar
            </Button>
          </form>

          <p className="text-center text-sm text-[hsl(var(--muted-foreground))]">
            Nao tem uma conta?{' '}
            <a href="/register" className="text-blue-600 hover:underline">
              Cadastre-se
            </a>
          </p>
        </div>
      </div>
    </div>
  )
}

export default LoginPage
