import { Loader2 } from 'lucide-react'
import { useLanguage } from '@/components/i18n/LanguageProvider'

export function LoadingState({ label }: { label?: string }) {
  const { t } = useLanguage()
  return (
    <div role="status" className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
      <Loader2 size={16} className="animate-spin" aria-hidden="true" />
      {label ?? t('ops.loading')}
    </div>
  )
}
