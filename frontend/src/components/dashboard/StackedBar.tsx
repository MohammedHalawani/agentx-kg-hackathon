import type { ReactNode } from 'react'
import { cn } from '../../lib/cn'

export interface Segment {
  key: string
  label: string
  value: number
  colorClass: string // a bg-* utility, e.g. 'bg-chart-blue' - used for both the fill and its legend swatch
  icon?: ReactNode // required in practice for status colors (good/warning) - never color alone
}

// A part-to-whole horizontal stacked bar: one baseline, ≤24px thick, 4px-rounded outer ends
// (square internal joins - the 2px surface gap between segments does the separating, not a
// stroke). Legend is always present (≥2 series) and doubles as the direct label, since a
// value squeezed inside a narrow segment would frequently fail to fit.
export function StackedBar({ segments, unit = '' }: { segments: Segment[]; unit?: string }) {
  const total = segments.reduce((sum, s) => sum + s.value, 0) || 1
  const visible = segments.filter((s) => s.value > 0)

  return (
    <div>
      <div
        className="flex h-6 w-full overflow-hidden rounded bg-surface"
        role="img"
        aria-label={segments.map((s) => `${s.label}: ${s.value}${unit}`).join(', ')}
      >
        {visible.map((seg, i) => (
          <div
            key={seg.key}
            tabIndex={0}
            className={cn('group/seg relative h-full outline-none', seg.colorClass, i > 0 && 'ml-0.5')}
            style={{ width: `${(seg.value / total) * 100}%` }}
          >
            <div className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-2 -translate-x-1/2 whitespace-nowrap rounded-md border border-hairline bg-panel px-2 py-1 text-xs opacity-0 shadow-lg transition-opacity group-hover/seg:opacity-100 group-focus/seg:opacity-100">
              <span className="font-semibold text-ink">{seg.value}{unit}</span>{' '}
              <span className="text-muted">{seg.label}</span>
            </div>
          </div>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5">
        {segments.map((seg) => (
          <div key={seg.key} className="flex items-center gap-1.5 text-xs">
            {seg.icon ?? <span className={cn('h-2.5 w-2.5 shrink-0 rounded-sm', seg.colorClass)} />}
            <span className="text-ink">{seg.label}</span>
            <span className="text-muted">
              {seg.value}{unit}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
