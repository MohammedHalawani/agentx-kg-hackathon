import { SidebarTrigger } from '@/components/ui/sidebar'
import { LanguageToggle } from '@/components/i18n/LanguageToggle'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { ThemeToggle } from '@/components/theme/ThemeToggle'
import type { ViewKey } from './types'

const VIEW_KEYS: Record<ViewKey, string> = {
  intake: 'nav.intake',
  decisions: 'nav.decisions',
  explore: 'nav.explore',
}

export function AppHeader({ view, scope: _scope }: { view: ViewKey; scope: string }) {
  const { t } = useLanguage()

  return (
    <header className="flex h-14 shrink-0 items-center gap-4 border-b border-border bg-card px-4">
      <SidebarTrigger
        className="-ml-1 text-foreground"
        aria-label={t('common.toggleSidebar')}
        title={t('common.toggleSidebar')}
      />
      <h1 className="text-sm font-semibold text-foreground">{t(VIEW_KEYS[view])}</h1>
      <div className="ml-auto flex items-center gap-2">
        <span className="hidden max-w-md truncate text-xs text-muted-foreground sm:inline">
          {t('scope')}
        </span>
        <LanguageToggle />
        <ThemeToggle />
      </div>
    </header>
  )
}
