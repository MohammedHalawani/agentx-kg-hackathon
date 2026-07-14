import { useState } from 'react'
import { motion } from 'motion/react'
import { cn } from '../../lib/cn'
import { buildLabelColors } from '../../lib/theme'
import type { Datum } from './BarList'

const R = 42
const C = 2 * Math.PI * R

// A donut built from stacked stroked circles (one arc per segment), with a legend. The ring scales
// in on mount; segment colors come from the shared label palette so they match the graph + legend.
// Hovering a segment (arc or legend row) dims the rest and swaps the center label to its value.
export function Donut({ data, unit = 'total' }: { data: Datum[]; unit?: string }) {
  const [hover, setHover] = useState<number | null>(null)
  const total = data.reduce((s, d) => s + d.value, 0) || 1
  const colors = buildLabelColors(data.map((d) => d.label))

  let offset = 0
  const segments = data.map((d) => {
    const frac = d.value / total
    const seg = { ...d, color: colors[d.label], dash: frac * C, off: offset * C, pct: frac }
    offset += frac
    return seg
  })
  const active = hover != null ? segments[hover] : null

  return (
    <div className="flex items-center gap-4">
      <motion.svg
        width="116"
        height="116"
        viewBox="0 0 120 120"
        className="shrink-0"
        initial={{ opacity: 0, scale: 0.92, rotate: -8 }}
        animate={{ opacity: 1, scale: 1, rotate: 0 }}
        transition={{ duration: 0.4, ease: 'easeOut' }}
        onMouseLeave={() => setHover(null)}
      >
        <g transform="rotate(-90 60 60)">
          <circle cx="60" cy="60" r={R} fill="none" stroke="var(--color-surface)" strokeWidth="16" />
          {segments.map((s, i) => (
            <circle
              key={i}
              cx="60"
              cy="60"
              r={R}
              fill="none"
              stroke={s.color}
              strokeWidth="16"
              strokeDasharray={`${s.dash} ${C - s.dash}`}
              strokeDashoffset={-s.off}
              opacity={hover == null || hover === i ? 1 : 0.3}
              className="cursor-pointer transition-opacity"
              onMouseEnter={() => setHover(i)}
            />
          ))}
        </g>
        {active ? (
          <>
            <text x="60" y="57" textAnchor="middle" style={{ fill: 'var(--color-ink)' }} className="font-display text-lg font-semibold">
              {active.value.toLocaleString()}
            </text>
            <text x="60" y="72" textAnchor="middle" style={{ fill: 'var(--color-muted)' }} className="text-[9px] tracking-wider">
              {active.label.length > 14 ? `${active.label.slice(0, 13)}…` : active.label}
            </text>
          </>
        ) : (
          <>
            <text x="60" y="57" textAnchor="middle" style={{ fill: 'var(--color-ink)' }} className="font-display text-lg font-semibold">
              {total.toLocaleString()}
            </text>
            <text x="60" y="72" textAnchor="middle" style={{ fill: 'var(--color-muted)' }} className="text-[9px] uppercase tracking-wider">
              {unit}
            </text>
          </>
        )}
      </motion.svg>
      <ul className="min-w-0 flex-1 space-y-1.5 text-xs">
        {segments.map((s, i) => (
          <li
            key={i}
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover(null)}
            className={cn(
              '-mx-1 flex cursor-default items-center gap-2 rounded px-1 py-0.5 transition-colors',
              hover === i && 'bg-surface',
            )}
          >
            <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: s.color }} />
            <span className="min-w-0 flex-1 truncate text-ink" title={s.label}>
              {s.label}
            </span>
            <span className="shrink-0 tabular-nums text-ink">{s.value.toLocaleString()}</span>
            <span className="shrink-0 tabular-nums text-muted">{Math.round(s.pct * 100)}%</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
