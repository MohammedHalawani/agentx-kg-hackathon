import { ClipboardList, Compass, FlaskConical, GitBranch, Inbox } from 'lucide-react'
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  useSidebar,
} from '@/components/ui/sidebar'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import type { ViewKey } from './types'

const NAV: { key: ViewKey; labelKey: string; icon: typeof Inbox }[] = [
  { key: 'intake', labelKey: 'nav.intake', icon: Inbox },
  { key: 'decisions', labelKey: 'nav.decisions', icon: GitBranch },
  { key: 'explore', labelKey: 'nav.explore', icon: Compass },
  { key: 'audit', labelKey: 'nav.audit', icon: ClipboardList },
]
// Development tooling, separated from the operator views.
const DEV_NAV: typeof NAV = [{ key: 'simulation', labelKey: 'nav.simulation', icon: FlaskConical }]

export function AppSidebar({
  active,
  onSelect,
}: {
  active: ViewKey
  onSelect: (view: ViewKey) => void
}) {
  const { t, isArabic } = useLanguage()
  const { setOpenMobile } = useSidebar()

  return (
    <Sidebar collapsible="icon" variant="sidebar" side={isArabic ? 'right' : 'left'} dir={isArabic ? 'rtl' : 'ltr'}>
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
                    onClick={() => { onSelect(key); setOpenMobile(false) }}
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
        <SidebarGroup className="mt-auto border-t border-sidebar-border">
          <SidebarGroupLabel>{t('nav.development')}</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {DEV_NAV.map(({ key, labelKey, icon: Icon }) => (
                <SidebarMenuItem key={key}>
                  <SidebarMenuButton
                    isActive={active === key}
                    tooltip={t(labelKey)}
                    onClick={() => { onSelect(key); setOpenMobile(false) }}
                    className="text-muted-foreground [&_svg]:text-current"
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
