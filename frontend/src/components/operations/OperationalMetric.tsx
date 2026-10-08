import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

export function OperationalMetric({
  label,
  value,
  detail,
  icon,
  tone = 'default',
}: {
  label: string
  value: string | number
  detail?: string
  icon?: ReactNode
  tone?: 'default' | 'good' | 'warning' | 'danger'
}) {
  const toneClass =
    tone === 'good'
      ? 'text-chart-good bg-chart-good/10'
      : tone === 'warning'
        ? 'text-chart-warning bg-chart-warning/15'
        : tone === 'danger'
          ? 'text-danger bg-danger/10'
          : 'text-primary bg-primary/10'

  return (
    <div className="rounded-xl border border-border bg-card px-3 py-2.5">
      <div className="flex items-start gap-2">
        {icon && <div className={cn('grid size-8 shrink-0 place-items-center rounded-md', toneClass)}>{icon}</div>}
        <div className="min-w-0">
          <p className="text-xs text-muted-foreground">{label}</p>
          <p className="text-xl font-semibold tabular-nums leading-tight">{value}</p>
          {detail && <p className="text-[11px] text-muted-foreground">{detail}</p>}
        </div>
      </div>
    </div>
  )
}
