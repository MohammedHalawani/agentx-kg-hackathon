import { motion } from 'motion/react'

export interface Datum {
  label: string
  value: number
}

// Horizontal bars, each growing from zero on mount. `format` controls the trailing value display.
export function BarList({
  data,
  format = (n) => n.toLocaleString(),
  color = 'var(--color-accent)',
}: {
  data: Datum[]
  format?: (n: number) => string
  color?: string
}) {
  const max = Math.max(1, ...data.map((d) => d.value))
  return (
    <div className="space-y-2">
      {data.map((d, i) => (
        <div
          key={d.label}
          className="-mx-1.5 flex items-center gap-3 rounded-md px-1.5 py-0.5 transition-colors hover:bg-surface"
        >
          <span className="w-28 shrink-0 truncate text-xs text-muted" title={d.label}>
            {d.label}
          </span>
          <div className="h-5 flex-1 overflow-hidden rounded-full bg-surface">
            <motion.div
              className="h-full rounded-full"
              style={{ background: color }}
              initial={{ width: 0 }}
              animate={{ width: `${(d.value / max) * 100}%` }}
              transition={{ duration: 0.7, ease: 'easeOut', delay: i * 0.05 }}
            />
          </div>
          <span className="w-20 shrink-0 text-right text-xs tabular-nums text-ink">{format(d.value)}</span>
        </div>
      ))}
    </div>
  )
}
