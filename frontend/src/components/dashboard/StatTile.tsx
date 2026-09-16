import type { ReactNode } from 'react'
import { cn } from '../../lib/cn'

type Tone = 'default' | 'good' | 'warning' | 'critical'

// Icon chip background per tone - critical/good/warning reuse the app's own danger token or the
// chart status colors (see index.css), never a color invented just for this tile.
const TONE_CLASS: Record<Tone, string> = {
  default: 'bg-accent-soft text-accent',
  good: 'bg-chart-good/10 text-chart-good',
  warning: 'bg-chart-warning/15 text-chart-warning',
  critical: 'bg-danger/10 text-danger',
}

// Stat-tile contract per the dataviz skill: label (sentence case, no colon) + value (proportional
// figures, not tabular - this is a standalone number, not a table column) + an icon carrying tone.
export function StatTile({ label, value, icon, tone = 'default' }: { label: string; value: string | number; icon: ReactNode; tone?: Tone }) {
  return (
    <div className="flex items-center gap-3 rounded-2xl border border-hairline bg-panel p-4">
      <div className={cn('grid h-10 w-10 shrink-0 place-items-center rounded-xl', TONE_CLASS[tone])}>{icon}</div>
      <div className="min-w-0">
        <p className="truncate text-xs text-muted">{label}</p>
        <p className="text-2xl font-semibold text-ink">{value}</p>
      </div>
    </div>
  )
}
