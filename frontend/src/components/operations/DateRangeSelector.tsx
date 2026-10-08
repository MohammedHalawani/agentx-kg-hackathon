import { useLanguage } from '@/components/i18n/LanguageProvider'
import type { TimeRangePreset } from '@/contracts/operations'
import { cn } from '@/lib/cn'

const PRESETS: (TimeRangePreset | 'all')[] = ['all', 'today', '24h', 'week', 'month', 'custom']

export function DateRangeSelector({
  value,
  onChange,
  unsupported,
}: {
  value: TimeRangePreset | 'all'
  onChange: (preset: TimeRangePreset | 'all') => void
  /** When true, presets are visible but disabled (no V2 timestamps yet). */
  unsupported?: boolean
}) {
  const { t } = useLanguage()
  return (
    <div className="flex flex-wrap gap-1" role="group" aria-label={t('ops.filters.timeRange')}>
      {PRESETS.map((preset) => (
        <button
          key={preset}
          type="button"
          disabled={unsupported}
          onClick={() => onChange(preset)}
          aria-pressed={value === preset}
          className={cn(
            'rounded-lg border px-2.5 py-1.5 text-xs focus-visible:outline-2 focus-visible:outline-ring disabled:cursor-not-allowed disabled:opacity-50',
            value === preset ? 'border-primary bg-primary text-primary-foreground' : 'border-border bg-card text-muted-foreground',
          )}
        >
          {t(`ops.time.${preset}`)}
        </button>
      ))}
      {unsupported && <span className="self-center text-[11px] text-muted-foreground">{t('ops.filters.timeUnsupported')}</span>}
    </div>
  )
}
