import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb'
import { Separator } from '@/components/ui/separator'
import { SidebarTrigger } from '@/components/ui/sidebar'
import { Skeleton } from '@/components/ui/skeleton'
import { LanguageToggle } from '@/components/i18n/LanguageToggle'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { ThemeToggle } from '@/components/theme/ThemeToggle'
import type { ViewKey } from './types'

const VIEW_KEYS: Record<ViewKey, string> = {
  intake: 'nav.intake',
  decisions: 'nav.decisions',
  explore: 'nav.explore',
  audit: 'nav.audit',
}

export function AppHeader({
  view,
  scopeLoading,
}: {
  view: ViewKey
  scope: string
  scopeLoading?: boolean
}) {
  const { t } = useLanguage()

  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border bg-card px-4 sm:px-6">
      <SidebarTrigger
        className="-ms-1 text-foreground"
        aria-label={t('common.toggleSidebar')}
        title={t('common.toggleSidebar')}
      />
      <Separator orientation="vertical" className="h-6" />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <Breadcrumb>
          <BreadcrumbList className="text-xs sm:text-sm">
            <BreadcrumbItem className="hidden sm:inline-flex">
              <span className="text-muted-foreground">{t('common.application')}</span>
            </BreadcrumbItem>
            <BreadcrumbSeparator className="hidden sm:block [&>svg]:rtl:rotate-180" />
            <BreadcrumbItem>
              <BreadcrumbPage className="font-semibold">{t(VIEW_KEYS[view])}</BreadcrumbPage>
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>
        {scopeLoading ? (
          <Skeleton className="h-3 w-full max-w-lg" aria-hidden="true" />
        ) : (
          <p className="line-clamp-1 text-xs text-muted-foreground">{t('scope')}</p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <LanguageToggle />
        <ThemeToggle />
      </div>
    </header>
  )
}
