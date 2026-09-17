import { Compass, GitBranch, Inbox } from 'lucide-react'
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from '@/components/ui/sidebar'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import type { ViewKey } from './types'

const NAV: { key: ViewKey; labelKey: string; icon: typeof Inbox }[] = [
  { key: 'intake', labelKey: 'nav.intake', icon: Inbox },
  { key: 'decisions', labelKey: 'nav.decisions', icon: GitBranch },
  { key: 'explore', labelKey: 'nav.explore', icon: Compass },
]

export function AppSidebar({
  active,
  onSelect,
}: {
  active: ViewKey
  onSelect: (view: ViewKey) => void
}) {
  const { t } = useLanguage()

  return (
    <Sidebar collapsible="icon" variant="sidebar">
      <SidebarHeader className="border-b border-sidebar-border px-3 py-3">
        <div className="flex h-8 items-center gap-2 overflow-hidden group-data-[collapsible=icon]:justify-center">
          <img src="/favicon.svg" alt={t('common.application')} className="size-7 shrink-0" />
        </div>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {NAV.map(({ key, labelKey, icon: Icon }) => (
                <SidebarMenuItem key={key}>
                  <SidebarMenuButton
                    isActive={active === key}
                    tooltip={t(labelKey)}
                    onClick={() => onSelect(key)}
                    className="text-sidebar-foreground [&_svg]:text-current"
                  >
                    <Icon />
                    <span>{t(labelKey)}</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarRail />
    </Sidebar>
  )
}
