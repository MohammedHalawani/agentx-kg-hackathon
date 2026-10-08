import { AlertTriangle } from 'lucide-react'
import { useLanguage } from '@/components/i18n/LanguageProvider'

export function ErrorState({ message, onRetry }: { message?: string; onRetry?: () => void }) {
  const { t } = useLanguage()
  return (
    <div role="alert" className="rounded-xl border border-danger/40 bg-danger/5 px-4 py-6 text-center">
      <AlertTriangle size={20} className="mx-auto mb-2 text-danger" aria-hidden="true" />
      <p className="text-sm text-danger">{message ?? t('ops.error.generic')}</p>
      {onRetry && (
        <button type="button" onClick={onRetry} className="mt-3 rounded-lg border border-border px-3 py-1.5 text-xs">
          {t('explore.retry')}
        </button>
      )}
    </div>
  )
}
