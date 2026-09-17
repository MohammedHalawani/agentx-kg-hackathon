import type { ReactNode } from 'react'
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar'
import { TooltipProvider } from '@/components/ui/tooltip'
import { AppHeader } from './AppHeader'
import { AppSidebar } from './AppSidebar'
import type { ViewKey } from './types'

export function AppShell({
  view,
  onViewChange,
  scope,
  children,
}: {
  view: ViewKey
  onViewChange: (view: ViewKey) => void
  scope: string
  children: ReactNode
}) {
  return (
    <TooltipProvider delay={200}>
      <SidebarProvider defaultOpen className="!min-h-0 h-full">
        <AppSidebar active={view} onSelect={onViewChange} />
        <SidebarInset className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <AppHeader view={view} scope={scope} />
          <div className="min-h-0 flex-1 overflow-hidden">{children}</div>
        </SidebarInset>
      </SidebarProvider>
    </TooltipProvider>
  )
}
