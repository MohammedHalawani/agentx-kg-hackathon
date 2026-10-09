import { useLanguage } from '@/components/i18n/LanguageProvider'
import type { QueueBucketCounts } from '@/contracts/operations'
import { cn } from '@/lib/cn'

type BucketKey = keyof QueueBucketCounts

const BUCKETS: { key: BucketKey; labelKey: string }[] = [
  { key: 'open', labelKey: 'ops.queue.open' },
  { key: 'investigating', labelKey: 'ops.queue.investigating' },
  { key: 'needsReview', labelKey: 'ops.queue.needsReview' },
  { key: 'needsEvidence', labelKey: 'ops.queue.needsEvidence' },
  { key: 'awaitingApproval', labelKey: 'ops.queue.awaitingApproval' },
  { key: 'awaitingOutcome', labelKey: 'ops.queue.awaitingOutcome' },
  { key: 'resolved', labelKey: 'ops.queue.resolved' },
]

export function QueueCounter({
  counts,
  active,
  onSelect,
}: {
  counts: QueueBucketCounts
  active?: BucketKey
  onSelect?: (key: BucketKey) => void
}) {
  const { t } = useLanguage()
  return (
    <div className="grid grid-cols-3 gap-2 sm:flex sm:flex-wrap" role="group" aria-label={t('ops.queue.title')}>
      {BUCKETS.map(({ key, labelKey }) => {
        const value = counts[key] ?? 0
        const dimmed = value === 0
        return (
          <button
            key={key}
            type="button"
            disabled={!onSelect}
            onClick={() => onSelect?.(key)}
            aria-pressed={active === key}
            className={cn(
              'min-w-0 sm:min-w-[7rem] rounded-xl border px-3 py-2 text-start transition-colors focus-visible:outline-2 focus-visible:outline-ring',
              active === key ? 'border-primary bg-primary/10' : 'border-border bg-card',
              dimmed && 'opacity-60',
            )}
          >
            <p className="text-[11px] text-muted-foreground">{t(labelKey)}</p>
            <p className="text-lg font-semibold tabular-nums text-foreground" dir="ltr">{value}</p>

          </button>
        )
      })}
    </div>
  )
}
