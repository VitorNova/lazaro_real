import { useState } from 'react'
import { Sidebar } from '@/components/Sidebar'
import { useAuthStore } from '@/stores/auth.store'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  User,
  Mail,
  Lock,
  Bell,
  Moon,
  Globe,
  Shield,
  Loader2,
  CheckCircle,
} from 'lucide-react'

function SettingSection({
  icon: Icon,
  title,
  description,
  children,
}: {
  icon: React.ElementType
  title: string
  description: string
  children: React.ReactNode
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm">
      <div className="p-6 border-b border-gray-100">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-gray-50">
            <Icon className="w-5 h-5 text-gray-600" />
          </div>
          <div>
            <h3 className="font-semibold text-gray-900">{title}</h3>
            <p className="text-sm text-gray-500">{description}</p>
          </div>
        </div>
      </div>
      <div className="p-6">{children}</div>
    </div>
  )
}

export function SettingsPage() {
  const { user } = useAuthStore()
  const [isSaving, setIsSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  const [formData, setFormData] = useState({
    name: user?.name || '',
    email: user?.email || '',
    currentPassword: '',
    newPassword: '',
    confirmPassword: '',
  })

  const handleSaveProfile = async () => {
    setIsSaving(true)
    // Simulate API call
    await new Promise((resolve) => setTimeout(resolve, 1000))
    setIsSaving(false)
    setSaved(true)
    setTimeout(() => setSaved(false), 3000)
  }

  const handleChangePassword = async () => {
    if (formData.newPassword !== formData.confirmPassword) {
      alert('As senhas não coincidem')
      return
    }
    setIsSaving(true)
    await new Promise((resolve) => setTimeout(resolve, 1000))
    setIsSaving(false)
    setFormData((prev) => ({
      ...prev,
      currentPassword: '',
      newPassword: '',
      confirmPassword: '',
    }))
    alert('Senha alterada com sucesso!')
  }

  return (
    <div className="flex h-screen bg-gray-50">
      <div className="hidden md:block">
        <Sidebar activePath="/settings" />
      </div>

      <main className="flex-1 overflow-auto p-4 md:p-8">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-gray-900">Configurações</h1>
          <p className="text-gray-600">Gerencie suas preferências e conta</p>
        </div>

        <div className="max-w-2xl space-y-6">
          {/* Profile */}
          <SettingSection
            icon={User}
            title="Perfil"
            description="Suas informações pessoais"
          >
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Nome
                </label>
                <Input
                  value={formData.name}
                  onChange={(e) => setFormData((prev) => ({ ...prev, name: e.target.value }))}
                  placeholder="Seu nome"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Email
                </label>
                <Input
                  type="email"
                  value={formData.email}
                  onChange={(e) => setFormData((prev) => ({ ...prev, email: e.target.value }))}
                  placeholder="seu@email.com"
                />
              </div>
              <div className="flex items-center gap-3">
                <Button onClick={handleSaveProfile} disabled={isSaving}>
                  {isSaving ? (
                    <Loader2 className="w-4 h-4 animate-spin mr-2" />
                  ) : saved ? (
                    <CheckCircle className="w-4 h-4 mr-2 text-green-500" />
                  ) : null}
                  {saved ? 'Salvo!' : 'Salvar alterações'}
                </Button>
              </div>
            </div>
          </SettingSection>

          {/* Security */}
          <SettingSection
            icon={Lock}
            title="Segurança"
            description="Altere sua senha"
          >
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Senha atual
                </label>
                <Input
                  type="password"
                  value={formData.currentPassword}
                  onChange={(e) =>
                    setFormData((prev) => ({ ...prev, currentPassword: e.target.value }))
                  }
                  placeholder="••••••••"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Nova senha
                </label>
                <Input
                  type="password"
                  value={formData.newPassword}
                  onChange={(e) =>
                    setFormData((prev) => ({ ...prev, newPassword: e.target.value }))
                  }
                  placeholder="••••••••"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Confirmar nova senha
                </label>
                <Input
                  type="password"
                  value={formData.confirmPassword}
                  onChange={(e) =>
                    setFormData((prev) => ({ ...prev, confirmPassword: e.target.value }))
                  }
                  placeholder="••••••••"
                />
              </div>
              <Button
                onClick={handleChangePassword}
                disabled={!formData.currentPassword || !formData.newPassword}
              >
                Alterar senha
              </Button>
            </div>
          </SettingSection>

          {/* Preferences */}
          <SettingSection
            icon={Bell}
            title="Preferências"
            description="Notificações e aparência"
          >
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-medium text-gray-900">Notificações por email</p>
                  <p className="text-sm text-gray-500">Receba atualizações por email</p>
                </div>
                <label className="relative inline-flex items-center cursor-pointer">
                  <input type="checkbox" className="sr-only peer" defaultChecked />
                  <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-100 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-[#1a6eff]"></div>
                </label>
              </div>

              <div className="flex items-center justify-between">
                <div>
                  <p className="font-medium text-gray-900">Notificações push</p>
                  <p className="text-sm text-gray-500">Notificações no navegador</p>
                </div>
                <label className="relative inline-flex items-center cursor-pointer">
                  <input type="checkbox" className="sr-only peer" />
                  <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-100 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-[#1a6eff]"></div>
                </label>
              </div>

              <div className="flex items-center justify-between opacity-50">
                <div>
                  <p className="font-medium text-gray-900">Modo escuro</p>
                  <p className="text-sm text-gray-500">Em breve</p>
                </div>
                <label className="relative inline-flex items-center cursor-not-allowed">
                  <input type="checkbox" className="sr-only peer" disabled />
                  <div className="w-11 h-6 bg-gray-200 rounded-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5"></div>
                </label>
              </div>
            </div>
          </SettingSection>

          {/* Account info */}
          <SettingSection
            icon={Shield}
            title="Conta"
            description="Informações da conta"
          >
            <div className="space-y-3 text-sm">
              <div className="flex justify-between py-2 border-b border-gray-100">
                <span className="text-gray-500">ID do usuário</span>
                <span className="font-mono text-gray-900">{user?.id?.slice(0, 8) || '-'}</span>
              </div>
              <div className="flex justify-between py-2 border-b border-gray-100">
                <span className="text-gray-500">Criado em</span>
                <span className="text-gray-900">-</span>
              </div>
              <div className="flex justify-between py-2">
                <span className="text-gray-500">Último acesso</span>
                <span className="text-gray-900">Agora</span>
              </div>
            </div>
          </SettingSection>
        </div>
      </main>
    </div>
  )
}

export default SettingsPage
