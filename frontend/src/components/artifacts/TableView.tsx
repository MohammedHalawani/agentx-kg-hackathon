import { useState } from 'react'
import * as RD from '@radix-ui/react-dialog'
import { AnimatePresence, motion } from 'motion/react'
import { X } from 'lucide-react'

// A Cypher map (e.g. Q20's {order, text} highlight or {title, format, date} source) has no
// generic display prop the way registry nodes do - fall back to its own values, in the order
// the query declared them, dropping empties rather than showing "[object Object]".
const fmtObject = (o: Record<string, unknown>): string =>
  Object.values(o)
    .filter((x) => x != null && x !== '')
    .map(String)
    .join(' — ')

const fmt = (v: unknown): string => {
  if (v == null) return ''
  if (Array.isArray(v)) {
    return v
      .filter((x) => x != null && x !== '')
      .map((x) => (typeof x === 'object' ? fmtObject(x as Record<string, unknown>) : String(x)))
      .join('; ')
  }
  // thousands separators for real magnitudes, but leave years (e.g. 2025) and ratios (0.18) alone
  if (typeof v === 'number') return Math.abs(v) >= 10000 ? v.toLocaleString('en-US') : String(v)
  if (typeof v === 'object') return fmtObject(v as Record<string, unknown>)
  return String(v)
}

// Full text of one clicked cell, in a modal - a long Arabic narrative isn't comfortable to
// read either wrapped inline (drags the row tall again) or squeezed into a title tooltip.
function CellModal({ cell, onClose }: { cell: { col: string; text: string } | null; onClose: () => void }) {
  return (
    <RD.Root open={cell != null} onOpenChange={(open) => !open && onClose()}>
      <AnimatePresence>
        {cell && (
          <RD.Portal forceMount>
            <RD.Overlay asChild forceMount>
              <motion.div
                className="fixed inset-0 z-[1100] bg-ink/30 backdrop-blur-sm"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
              />
            </RD.Overlay>
            <RD.Content asChild forceMount aria-describedby={undefined}>
              <motion.div
                className="fixed left-1/2 top-1/2 z-[1110] max-h-[70vh] w-[min(560px,90vw)] -translate-x-1/2 -translate-y-1/2 overflow-auto rounded-2xl border border-hairline bg-surface p-4 shadow-2xl focus:outline-none"
                initial={{ opacity: 0, scale: 0.97 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.98 }}
                transition={{ duration: 0.2, ease: 'easeOut' }}
              >
                <div className="mb-2 flex items-center justify-between gap-4">
                  <RD.Title className="font-mono text-[11px] font-semibold uppercase tracking-[0.14em] text-ink">
                    {cell.col}
                  </RD.Title>
                  <RD.Close
                    aria-label="Close"
                    className="rounded-md p-1 text-muted transition-colors hover:bg-panel hover:text-ink"
                  >
                    <X size={18} />
                  </RD.Close>
                </div>
                <div dir="auto" className="whitespace-pre-wrap text-sm leading-relaxed text-ink">
                  {cell.text}
                </div>
              </motion.div>
            </RD.Content>
          </RD.Portal>
        )}
      </AnimatePresence>
    </RD.Root>
  )
}

export function TableView({ rows }: { rows: Record<string, unknown>[] }) {
  const [cell, setCell] = useState<{ col: string; text: string } | null>(null)

  const allEmpty = rows.every((r) => Object.values(r).every((v) => v == null || v === ''))
  if (!rows.length || allEmpty) {
    return <div className="grid h-full place-items-center p-6 text-sm text-muted">No matching rows.</div>
  }
  const cols = Object.keys(rows[0])
  return (
    <div className="h-full overflow-auto">
      <table className="w-full border-collapse text-sm">
        <thead className="sticky top-0 bg-panel">
          <tr className="border-b border-hairline text-left text-xs uppercase tracking-wide text-muted">
            {cols.map((c) => (
              <th key={c} className="whitespace-nowrap px-3 py-2 font-medium">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {/* rows are a static, read-only snapshot — never sorted or reordered — so index keys are safe */}
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-hairline/60 transition-colors hover:bg-surface">
              {cols.map((c) => {
                const text = fmt(r[c])
                return (
                  // dir="auto" per cell (not a blanket rtl on the table) - some columns are
                  // Arabic prose, others are ids/counts/dates, and content decides direction
                  // and alignment on its own rather than us guessing per column name.
                  // max-w + truncate keeps every row one line tall instead of long text
                  // (text_ar/narrative_ar) stretching the row vertically; click opens the
                  // full value in CellModal instead of relying on a title-attribute hover.
                  <td
                    key={c}
                    dir="auto"
                    title={text}
                    onClick={() => text && setCell({ col: c, text })}
                    className="max-w-[280px] cursor-pointer truncate px-3 py-1.5 text-ink"
                  >
                    {text}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <CellModal cell={cell} onClose={() => setCell(null)} />
    </div>
  )
}
