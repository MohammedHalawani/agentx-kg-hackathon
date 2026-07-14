import { useId, useState } from 'react'
import { motion } from 'motion/react'
import type { Datum } from './BarList'

const W = 320
const H = 130
const PAD_X = 10
const PAD_TOP = 14
const PAD_BOTTOM = 22

// Catmull-Rom-to-Bezier: a smooth curve through every point without a charting library. Simpler
// than true monotone-cubic (won't guard against overshoot on sharply non-monotone data), but for
// a monthly incident count that reads as a soft "premium" curve rather than jagged straight segments.
function smoothPath(points: { x: number; y: number }[]): string {
  let d = `M${points[0].x.toFixed(1)},${points[0].y.toFixed(1)}`
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[i - 1] ?? points[i]
    const p1 = points[i]
    const p2 = points[i + 1]
    const p3 = points[i + 2] ?? p2
    const c1x = p1.x + (p2.x - p0.x) / 6
    const c1y = p1.y + (p2.y - p0.y) / 6
    const c2x = p2.x - (p3.x - p1.x) / 6
    const c2y = p2.y - (p3.y - p1.y) / 6
    d += ` C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${p2.x.toFixed(1)},${p2.y.toFixed(1)}`
  }
  return d
}

// A single-series area + line, drawn on mount (the line strokes in, the fill fades up). SVG so it
// scales crisply and themes from tokens; x-axis shows the first/mid/last labels only, to stay clean.
// Hovering a point (or its wider invisible hit-circle) shows its exact label + value in a small tag.
export function AreaChart({ data }: { data: Datum[] }) {
  const gradientId = useId()
  const [hover, setHover] = useState<number | null>(null)
  if (data.length < 2) return null
  const max = Math.max(1, ...data.map((d) => d.value))
  const n = data.length
  const x = (i: number) => PAD_X + (i / (n - 1)) * (W - 2 * PAD_X)
  const y = (v: number) => PAD_TOP + (1 - v / max) * (H - PAD_TOP - PAD_BOTTOM)

  const points = data.map((d, i) => ({ x: x(i), y: y(d.value) }))
  const line = smoothPath(points)
  const area = `${line} L${x(n - 1).toFixed(1)},${H - PAD_BOTTOM} L${x(0).toFixed(1)},${H - PAD_BOTTOM} Z`
  const ticks = [0, Math.floor((n - 1) / 2), n - 1]

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" preserveAspectRatio="none">
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--color-accent)" stopOpacity="0.22" />
          <stop offset="100%" stopColor="var(--color-accent)" stopOpacity="0" />
        </linearGradient>
      </defs>
      <motion.path
        d={area}
        fill={`url(#${gradientId})`}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.5, delay: 0.35 }}
      />
      <motion.path
        d={line}
        fill="none"
        stroke="var(--color-accent)"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.8, ease: 'easeOut' }}
      />
      {hover != null && (
        <line x1={x(hover)} y1={PAD_TOP} x2={x(hover)} y2={H - PAD_BOTTOM} stroke="var(--color-hairline)" strokeWidth="1" />
      )}
      {data.map((d, i) => (
        <g key={i}>
          <motion.circle
            cx={x(i)}
            cy={y(d.value)}
            r={hover === i ? 3.5 : 2.5}
            fill="var(--color-accent)"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.5 + i * 0.05 }}
          />
          {/* wider transparent hit target - the visible dot alone is too small to hover reliably */}
          <circle
            cx={x(i)}
            cy={y(d.value)}
            r="10"
            fill="transparent"
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover((h) => (h === i ? null : h))}
          />
        </g>
      ))}
      {hover != null &&
        (() => {
          const d = data[hover]
          const label = `${d.label}: ${d.value.toLocaleString()}`
          const boxW = label.length * 4.6 + 10
          const boxX = Math.min(Math.max(x(hover) - boxW / 2, 2), W - boxW - 2)
          const boxY = Math.max(y(d.value) - 24, 2)
          return (
            <g pointerEvents="none">
              <rect x={boxX} y={boxY} width={boxW} height={16} rx="4" fill="var(--color-ink)" opacity="0.9" />
              <text x={boxX + boxW / 2} y={boxY + 11} textAnchor="middle" fill="var(--color-surface)" className="text-[9px] font-medium">
                {label}
              </text>
            </g>
          )
        })()}
      {ticks.map((i) => (
        <text
          key={i}
          x={x(i)}
          y={H - 6}
          textAnchor={i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle'}
          style={{ fill: 'var(--color-muted)' }}
          className="text-[9px]"
        >
          {data[i].label}
        </text>
      ))}
    </svg>
  )
}
