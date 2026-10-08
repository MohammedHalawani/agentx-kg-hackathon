import { useLanguage } from '@/components/i18n/LanguageProvider'
import type { CasePriority } from '@/contracts/operations'
import { cn } from '@/lib/cn'

const TONE: Record<CasePriority, string> = {
  high: 'border-danger/40 text-danger bg-danger/5',
  medium: 'border-chart-warning/40 text-chart-warning bg-chart-warning/10',
  low: 'border-border text-muted-foreground bg-muted/30',
  unknown: 'border-border text-muted-foreground bg-card',
}

export function PriorityBadge({ priority, className }: { priority: CasePriority; className?: string }) {
  const { t } = useLanguage()
  if (priority === 'unknown') return null
  return (
    <span className={cn('inline-flex rounded-md border px-2 py-0.5 text-[11px] font-medium', TONE[priority], className)}>
      {t(`ops.priority.${priority}`)}
    </span>
  )
}
