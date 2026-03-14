# COMPONENTS.md — Catálogo de Componentes lazaro-real

> Gerado em: 2026-03-14
> Regra: antes de criar qualquer componente novo, consulte este catálogo.
> Ao criar ou modificar um componente, atualize este arquivo na mesma sessão.

## Resumo

- **Total de componentes:** 16
  - Arquivos separados: 4
  - Inline em páginas: 12
- **Duplicados encontrados:** 2
- **Componentes faltando:** 0

---

## Índice

- [UI Primitivos](#ui-primitivos)
- [Layout](#layout)
- [Cards de Estatísticas](#cards-de-estatísticas)
- [Modais](#modais)
- [Pipeline/Kanban](#pipelinekanban)
- [Formulários/Seções](#formuláriosseções)
- [Duplicados](#-duplicados)
- [Faltando](#-faltando)

---

## UI Primitivos

### Button

- **Arquivo:** `apps/web/src/components/ui/button.tsx`
- **Props:**
  ```typescript
  interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
    variant?: 'default' | 'destructive' | 'outline' | 'secondary' | 'ghost' | 'link'  // opcional — default: 'default'
    size?: 'default' | 'sm' | 'lg' | 'icon'  // opcional — default: 'default'
    isLoading?: boolean  // opcional — exibe spinner Loader2 e desabilita o botão
  }
  ```
- **Variantes:**
  - `default`: bg primary, texto branco
  - `destructive`: bg vermelho
  - `outline`: borda, bg transparente
  - `secondary`: bg secundário
  - `ghost`: sem bg, hover cinza
  - `link`: apenas texto com underline no hover
- **Uso básico:**
  ```tsx
  <Button variant="outline" size="sm" isLoading={isPending}>
    Salvar
  </Button>
  ```
- **Depende de:** `cn` de `@/lib/utils`, `Loader2` de `lucide-react`
- **Observações:** Usa `forwardRef`. Estilo inspirado em shadcn/ui mas implementado manualmente.

---

### Input

- **Arquivo:** `apps/web/src/components/ui/input.tsx`
- **Props:**
  ```typescript
  interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
    error?: string  // opcional — exibe mensagem de erro e borda vermelha
  }
  ```
- **Variantes:** Nenhuma
- **Uso básico:**
  ```tsx
  <Input
    type="email"
    placeholder="seu@email.com"
    error={formErrors.email}
  />
  ```
- **Depende de:** `cn` de `@/lib/utils`
- **Observações:** Usa `forwardRef`. Envolve o input em `<div>` para exibir erro abaixo.

---

## Layout

### Sidebar

- **Arquivo:** `apps/web/src/components/Sidebar.tsx`
- **Props:**
  ```typescript
  interface SidebarProps {
    activePath?: string  // opcional — rota ativa para highlight no menu
  }
  ```
- **Variantes:** Nenhuma
- **Uso básico:**
  ```tsx
  <Sidebar activePath="/agents" />
  ```
- **Depende de:** `useNavigate` de `react-router-dom`, `useAuthStore`, `Button`, ícones lucide
- **Observações:** Menu fixo lateral com navegação, avatar do usuário e botão de logout. Rotas hardcoded: `/`, `/leads`, `/agents`, `/billing`, `/settings`

---

### ProtectedRoute

- **Arquivo:** `apps/web/src/components/ProtectedRoute.tsx`
- **Props:**
  ```typescript
  interface ProtectedRouteProps {
    children: ReactNode  // obrigatória — conteúdo a ser protegido
  }
  ```
- **Variantes:** Nenhuma
- **Uso básico:**
  ```tsx
  <ProtectedRoute>
    <DashboardPage />
  </ProtectedRoute>
  ```
- **Depende de:** `useAuthStore`, `Navigate` e `useLocation` de `react-router-dom`
- **Observações:** Redireciona para `/login` se não autenticado.

---

## Cards de Estatísticas

### StatCard (DashboardPage)

- **Arquivo:** `apps/web/src/pages/DashboardPage.tsx` (inline, linhas 25-92)
- **Props:**
  ```typescript
  {
    label: string           // obrigatória — título do card
    value: string | number  // obrigatória — valor principal
    change?: string         // opcional — variação (ex: "+12%")
    icon: React.ElementType // obrigatória — ícone lucide
    color: 'blue' | 'purple' | 'green' | 'yellow' | 'red' | 'orange'  // obrigatória
    isLoading?: boolean     // opcional — exibe skeleton
  }
  ```
- **Variantes:** 6 cores disponíveis
- **Uso básico:**
  ```tsx
  <StatCard
    label="Total de Leads"
    value={123}
    change="+12%"
    icon={Users}
    color="blue"
    isLoading={false}
  />
  ```
- **Depende de:** `cn`, `Loader2`, `ArrowUpRight`, `ArrowDownRight`
- **Observações:** Exibe seta verde para valores positivos, vermelha para negativos.

---

### StatCard (BillingPage)

- **Arquivo:** `apps/web/src/pages/BillingPage.tsx` (inline, linhas 20-84)
- **Props:**
  ```typescript
  {
    label: string           // obrigatória
    value: string           // obrigatória (note: só string, diferente da Dashboard)
    change?: string         // opcional
    icon: React.ElementType // obrigatória
    color: 'blue' | 'green' | 'yellow' | 'red'  // obrigatória (4 cores apenas)
    isLoading?: boolean     // opcional
  }
  ```
- **Observações:** Ver seção [Duplicados](#-duplicados)

---

### AgentCard (DashboardPage)

- **Arquivo:** `apps/web/src/pages/DashboardPage.tsx` (inline, linhas 94-150)
- **Props:**
  ```typescript
  {
    agent: DashboardStats['agentsPerformance'][0]  // obrigatória — dados do agente
  }
  ```
- **Uso básico:**
  ```tsx
  <AgentCard agent={agentData} />
  ```
- **Depende de:** `cn`
- **Observações:** Exibe avatar, nome, tipo, status online/offline e métricas.

---

### AgentCard (AgentsPage)

- **Arquivo:** `apps/web/src/pages/AgentsPage.tsx` (inline, linhas 28-189)
- **Props:**
  ```typescript
  {
    agent: Agent              // obrigatória
    onToggleAI: (id: string, enabled: boolean) => void  // obrigatória
    onDelete: (id: string) => void  // obrigatória
    onEdit: (agent: Agent) => void  // obrigatória
    onShowQRCode: (agent: Agent) => void  // obrigatória
    isUpdating: boolean       // obrigatória — desabilita interações
  }
  ```
- **Observações:** Card completo com menu dropdown (editar, QR Code, toggle IA, excluir), badges de status e contadores.

---

### InvoiceRow

- **Arquivo:** `apps/web/src/pages/BillingPage.tsx` (inline, linhas 86-113)
- **Props:**
  ```typescript
  {
    invoice: {
      id: string
      date: string
      amount: string
      status: 'paid' | 'pending' | 'overdue'
    }
  }
  ```
- **Uso básico:**
  ```tsx
  <InvoiceRow invoice={invoiceData} />
  ```
- **Depende de:** `FileText`, `Clock`, `CheckCircle2`, `XCircle`
- **Observações:** Linha de tabela com ícone de status colorido.

---

### PeriodSelector

- **Arquivo:** `apps/web/src/pages/DashboardPage.tsx` (inline, linhas 152-184)
- **Props:**
  ```typescript
  {
    value: 'day' | 'week' | 'month' | 'total'  // obrigatória
    onChange: (period: Period) => void          // obrigatória
  }
  ```
- **Uso básico:**
  ```tsx
  <PeriodSelector value="week" onChange={setPeriod} />
  ```
- **Observações:** Grupo de botões de seleção de período com estilo pill.

---

## Modais

### CreateAgentModal

- **Arquivo:** `apps/web/src/pages/AgentsPage.tsx` (inline, linhas 191-275)
- **Props:**
  ```typescript
  {
    isOpen: boolean              // obrigatória
    onClose: () => void          // obrigatória
    onCreate: (data: { name: string; type: string }) => void  // obrigatória
    isCreating: boolean          // obrigatória
  }
  ```
- **Uso básico:**
  ```tsx
  <CreateAgentModal
    isOpen={showModal}
    onClose={() => setShowModal(false)}
    onCreate={handleCreate}
    isCreating={isPending}
  />
  ```
- **Depende de:** `Input`, `Button`, `X`
- **Observações:** Modal com backdrop escuro, formulário de nome e tipo (select).

---

### EditAgentModal

- **Arquivo:** `apps/web/src/pages/AgentsPage.tsx` (inline, linhas 277-361)
- **Props:**
  ```typescript
  {
    agent: Agent | null          // obrigatória — null fecha o modal
    onClose: () => void          // obrigatória
    onSave: (id: string, data: { name: string; type: string }) => void  // obrigatória
    isSaving: boolean            // obrigatória
  }
  ```
- **Observações:** Similar ao CreateAgentModal mas para edição.

---

### QRCodeModal

- **Arquivo:** `apps/web/src/pages/AgentsPage.tsx` (inline, linhas 363-497)
- **Props:**
  ```typescript
  {
    agent: Agent | null  // obrigatória — null fecha o modal
    onClose: () => void  // obrigatória
  }
  ```
- **Depende de:** `agentsService.getQRCode`, `Smartphone`, `Loader2`, `CheckCircle2`, `Button`
- **Observações:** Polling automático a cada 15s para atualizar QR Code. Exibe instruções de conexão.

---

## Pipeline/Kanban

### LeadCard

- **Arquivo:** `apps/web/src/pages/PipelinePage.tsx` (inline, linhas 56-249)
- **Props:**
  ```typescript
  interface LeadCardProps {
    lead: Lead                   // obrigatória
    agentId: string              // obrigatória
    onDragStart: (e: React.DragEvent, lead: Lead) => void  // obrigatória
    onToggleAI: (leadId: number, enabled: boolean) => void  // obrigatória
    onDelete: (leadId: number) => void  // obrigatória
    isUpdating?: boolean         // opcional
  }
  ```
- **Uso básico:**
  ```tsx
  <LeadCard
    lead={leadData}
    agentId="uuid"
    onDragStart={handleDragStart}
    onToggleAI={handleToggle}
    onDelete={handleDelete}
  />
  ```
- **Depende de:** `cn`, `GripVertical`, `MoreVertical`, `Bot`, `User`, `Phone`, `Building2`, `Clock`, `Power`, `PowerOff`, `Trash2`
- **Observações:** Card draggable com menu dropdown, ícone de status IA, informações de contato, sentimento emoji, timestamp relativo.

---

### PipelineColumn

- **Arquivo:** `apps/web/src/pages/PipelinePage.tsx` (inline, linhas 255-338)
- **Props:**
  ```typescript
  interface PipelineColumnProps {
    stage: PipelineStage         // obrigatória
    leads: Lead[]                // obrigatória
    agentId: string              // obrigatória
    onDragStart: (e: React.DragEvent, lead: Lead) => void  // obrigatória
    onDragOver: (e: React.DragEvent) => void  // obrigatória
    onDrop: (e: React.DragEvent, stageSlug: string) => void  // obrigatória
    onToggleAI: (leadId: number, enabled: boolean) => void  // obrigatória
    onDelete: (leadId: number) => void  // obrigatória
    updatingLeadId?: number      // opcional
  }
  ```
- **Depende de:** `LeadCard`, `cn`, constantes `STAGE_COLORS` e `STAGE_HEADER_COLORS`
- **Observações:** Coluna do kanban com header colorido, scroll vertical, drop zone com highlight.

---

## Formulários/Seções

### SettingSection

- **Arquivo:** `apps/web/src/pages/SettingsPage.tsx` (inline, linhas 18-45)
- **Props:**
  ```typescript
  {
    icon: React.ElementType  // obrigatória — ícone lucide
    title: string            // obrigatória
    description: string      // obrigatória
    children: React.ReactNode  // obrigatória — conteúdo da seção
  }
  ```
- **Uso básico:**
  ```tsx
  <SettingSection icon={User} title="Perfil" description="Suas informações">
    <Input ... />
  </SettingSection>
  ```
- **Observações:** Card com header (ícone + título + descrição) e área de conteúdo.

---

## Duplicados

### StatCard

**Existem 2 implementações diferentes:**

| Localização | Cores suportadas | Tipo de `value` |
|-------------|------------------|-----------------|
| `DashboardPage.tsx:25-92` | 6 cores (blue, purple, green, yellow, red, orange) | `string \| number` |
| `BillingPage.tsx:20-84` | 4 cores (blue, green, yellow, red) | `string` |

**Recomendação:** Extrair para `components/ui/stat-card.tsx` com a versão mais completa (Dashboard).

---

### AgentCard

**Existem 2 implementações completamente diferentes:**

| Localização | Propósito |
|-------------|-----------|
| `DashboardPage.tsx:94-150` | Card simples para exibir performance (somente leitura) |
| `AgentsPage.tsx:28-189` | Card completo com menu de ações (CRUD) |

**Recomendação:** Renomear para clarificar:
- `AgentPerformanceCard` (Dashboard)
- `AgentManagementCard` (Agents)

---

## Faltando

Nenhum componente referenciado no JSX sem arquivo correspondente.

---

## Notas Técnicas

### shadcn/ui

**Status:** NÃO instalado formalmente via CLI.

O projeto usa o **estilo shadcn** (helper `cn`, variantes via objetos, `forwardRef`, CSS variables HSL) mas os componentes são implementados manualmente.

**Dependências relacionadas instaladas:**
- `clsx` — concatenação de classes
- `tailwind-merge` — merge inteligente de classes Tailwind
- `lucide-react` — ícones

### Estrutura de Pastas

```
apps/web/src/
├── components/
│   ├── ui/           # Primitivos reutilizáveis (Button, Input)
│   ├── Sidebar.tsx   # Layout
│   └── ProtectedRoute.tsx  # Auth wrapper
├── pages/            # Componentes inline (não extraídos)
├── lib/
│   └── utils.ts      # Helper cn()
└── stores/           # Zustand stores
```

### Próximos Passos Sugeridos

1. Extrair `StatCard` para `components/ui/stat-card.tsx`
2. Renomear e extrair os dois `AgentCard` distintos
3. Criar `components/ui/modal.tsx` genérico (base para os modais)
4. Mover `SettingSection` para `components/ui/setting-section.tsx`
5. Considerar instalar shadcn/ui CLI para consistência futura
