import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/auth.store'
import { Button } from '@/components/ui/button'
import {
  MessageSquare,
  Users,
  BarChart3,
  Settings,
  LogOut,
  Bot,
  DollarSign,
} from 'lucide-react'

interface SidebarProps {
  activePath?: string
}

const menuItems = [
  { icon: MessageSquare, label: 'Conversas', href: '/conversations' },
  { icon: Users, label: 'Leads', href: '/leads' },
  { icon: Bot, label: 'Agentes', href: '/agents' },
  { icon: BarChart3, label: 'Dashboard', href: '/' },
  { icon: DollarSign, label: 'Billing', href: '/billing' },
  { icon: Settings, label: 'Configuracoes', href: '/settings' },
]

export function Sidebar({ activePath }: SidebarProps) {
  const navigate = useNavigate()
  const { user, logout } = useAuthStore()

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  const handleNavigate = (href: string) => {
    navigate(href)
  }

  return (
    <aside className="w-64 border-r border-[hsl(var(--border))] bg-white flex flex-col">
      <div className="p-6">
        <div className="flex items-center gap-3 mb-8">
          <MessageSquare className="h-8 w-8 text-[#1a6eff]" />
          <span className="text-xl font-bold">Lazaro</span>
        </div>

        <nav className="space-y-1">
          {menuItems.map((item) => {
            const isActive = activePath === item.href
            return (
              <button
                key={item.href}
                onClick={() => handleNavigate(item.href)}
                className={`w-full flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors text-left ${
                  isActive
                    ? 'bg-[#1a6eff]/10 text-[#1a6eff]'
                    : 'text-gray-600 hover:bg-gray-50'
                }`}
              >
                <item.icon className="h-5 w-5" />
                <span>{item.label}</span>
              </button>
            )
          })}
        </nav>
      </div>

      <div className="mt-auto p-6 border-t border-[hsl(var(--border))]">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-full bg-[#1a6eff]/10 flex items-center justify-center">
            <span className="text-[#1a6eff] font-semibold">
              {user?.name?.charAt(0).toUpperCase() || 'U'}
            </span>
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium truncate">{user?.name || 'Usuario'}</p>
            <p className="text-xs text-gray-500 truncate">{user?.email}</p>
          </div>
        </div>
        <Button
          variant="outline"
          size="sm"
          className="w-full"
          onClick={handleLogout}
        >
          <LogOut className="h-4 w-4 mr-2" />
          Sair
        </Button>
      </div>
    </aside>
  )
}

export default Sidebar
