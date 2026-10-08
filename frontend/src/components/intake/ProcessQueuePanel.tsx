import { Pause, Play } from 'lucide-react'
import { useLanguage } from '@/components/i18n/LanguageProvider'

export function ProcessQueuePanel({
  running,
  onToggle,
  concurrency,
  processingId,
  queueDepth,
  needsReview,
  simulation,
  disabled,
  onStep,
}: {
  running: boolean
  onToggle: () => void
  concurrency: number
  processingId: string | null
  queueDepth: number
  needsReview: number
  simulation?: boolean
  disabled?: boolean
  onStep?: () => void
}) {
  const { t } = useLanguage()
  return (
    <section className="rounded-xl border border-border bg-card p-3" aria-label={t('ops.queue.processTitle')}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold">{t('ops.queue.processTitle')}</h3>
          {simulation && (
            <p className="text-[11px] font-medium uppercase tracking-wide text-chart-warning">{t('ops.simulation.label')}</p>
          )}
        </div>
        <button
          type="button"
          onClick={onToggle}
          disabled={disabled}
          className="inline-flex items-center gap-2 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground disabled:opacity-40"
        >
          {running ? <Pause size={14} /> : <Play size={14} />}
          {running ? t('ops.queue.pause') : t('ops.queue.start')}
        </button>
      </div>
      {onStep && <button type="button" disabled={disabled || running} onClick={onStep} className="mt-2 rounded-lg border border-border px-3 py-1.5 text-xs disabled:opacity-40">{t('ops.queue.step')}</button>}
      <dl className="mt-3 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
        <div>
          <dt className="text-muted-foreground">{t('ops.queue.concurrency')}</dt>
          <dd className="font-medium tabular-nums" dir="ltr">{concurrency}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t('ops.queue.processing')}</dt>
          <dd className="font-mono text-xs" dir="ltr">{processingId ?? '—'}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t('ops.queue.depth')}</dt>
          <dd className="font-medium tabular-nums" dir="ltr">{queueDepth}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t('ops.queue.needsReview')}</dt>
          <dd className="font-medium tabular-nums" dir="ltr">{needsReview}</dd>
        </div>
      </dl>
      <p className="mt-2 text-[11px] text-muted-foreground">{t('ops.queue.futureSettings')}</p>
    </section>
  )
}
