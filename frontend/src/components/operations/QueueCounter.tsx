import { useLanguage } from '@/components/i18n/LanguageProvider'
import type { QueueBucketCounts } from '@/contracts/operations'
import { cn } from '@/lib/cn'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

type BucketKey = keyof QueueBucketCounts

const BUCKETS: { key: BucketKey; labelKey: string; hintKey: string }[] = [
  { key: 'open', labelKey: 'ops.queue.open', hintKey: 'ops.stateHelp.QUEUED' },
  { key: 'investigating', labelKey: 'ops.queue.investigating', hintKey: 'ops.stateHelp.INVESTIGATING' },
  { key: 'human', labelKey: 'ops.attention.title', hintKey: 'ops.attention.counterHint' },
  { key: 'awaitingOutcome', labelKey: 'ops.queue.awaitingOutcome', hintKey: 'ops.stateHelp.AWAITING_OUTCOME' },
  { key: 'resolved', labelKey: 'ops.queue.resolved', hintKey: 'ops.stateHelp.RESOLVED' },
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
      {BUCKETS.map(({ key, labelKey, hintKey }) => {
        const value = counts[key] ?? 0
        const dimmed = value === 0
        return (
          <Tooltip key={key}>
          <TooltipTrigger render={<button
            type="button"
            disabled={!onSelect}
            onClick={() => onSelect?.(key)}
            aria-pressed={active === key}
            className={cn(
              'min-w-0 sm:min-w-[7rem] rounded-xl border px-3 py-2 text-start transition-colors duration-300 focus-visible:outline-2 focus-visible:outline-ring',
              active === key ? 'border-primary bg-primary/10' : 'border-border bg-card',
              dimmed && 'opacity-60',
            )}
          >
            <p className="text-[11px] text-muted-foreground">{t(labelKey)}</p>
            <p className="text-lg font-semibold tabular-nums text-foreground" dir="ltr">{value}</p>
          </button>} />
          <TooltipContent side="bottom" className="max-w-xs">{t(hintKey)}</TooltipContent>
          </Tooltip>
        )
      })}
    </div>
  )
}
