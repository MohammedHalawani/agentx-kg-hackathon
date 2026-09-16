import { useState } from 'react'
import * as RD from '@radix-ui/react-dialog'
import { AnimatePresence, motion } from 'motion/react'
import { Download, Maximize2, X } from 'lucide-react'
import { cn } from '../../lib/cn'

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

// Same shape as fmt() but skips the thousands-separator formatting - a quoted "1,234" reads
// as text, not a number, to a spreadsheet, so raw numbers must stay comma-free in the export.
const csvCell = (v: unknown): string => {
  if (v == null) return ''
  if (Array.isArray(v)) {
    return v
      .filter((x) => x != null && x !== '')
      .map((x) => (typeof x === 'object' ? fmtObject(x as Record<string, unknown>) : String(x)))
      .join('; ')
  }
  if (typeof v === 'object') return fmtObject(v as Record<string, unknown>)
  return String(v)
}

const csvEscape = (s: string): string => (/[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s)

const toCsv = (cols: string[], rows: Record<string, unknown>[]): string => {
  const lines = [cols.map(csvEscape).join(',')]
  for (const r of rows) lines.push(cols.map((c) => csvEscape(csvCell(r[c]))).join(','))
  return lines.join('\r\n')
}

const slugify = (s: string): string => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'table'

function downloadCsv(title: string | undefined, cols: string[], rows: Record<string, unknown>[]): void {
  const blob = new Blob([toCsv(cols, rows)], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${slugify(title ?? 'table')}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

// The actual grid, shared between the inline (truncated, one-line rows) and fullscreen (wrapped,
// nothing hidden) presentations - same data, same click-to-expand-a-cell behaviour either way.
function DataTable({
  cols,
  rows,
  truncate,
  onCellClick,
}: {
  cols: string[]
  rows: Record<string, unknown>[]
  truncate: boolean
  onCellClick: (col: string, text: string) => void
}) {
  return (
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
                <td
                  key={c}
                  dir="auto"
                  title={truncate ? text : undefined}
                  onClick={() => text && onCellClick(c, text)}
                  className={cn(
                    'cursor-pointer px-3 py-1.5 text-ink',
                    // inline: max-w + truncate keeps every row one line tall, full value on click
                    // (via CellModal). Fullscreen: there's room, so wrap instead of hiding anything.
                    truncate ? 'max-w-[280px] truncate' : 'whitespace-normal break-words',
                  )}
                >
                  {text}
                </td>
              )
            })}
          </tr>
        ))}
      </tbody>
    </table>
  )
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

// The whole table, near-fullscreen, with nothing truncated - for when the inline card is too
// small to see every column at once. z-[1000]/[1010], one tier below CellModal's 1100/1110, so
// a cell clicked from inside here still opens its modal on top rather than behind it.
function FullscreenModal({
  open,
  onClose,
  title,
  cols,
  rows,
  onCellClick,
}: {
  open: boolean
  onClose: () => void
  title: string | undefined
  cols: string[]
  rows: Record<string, unknown>[]
  onCellClick: (col: string, text: string) => void
}) {
  return (
    <RD.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <AnimatePresence>
        {open && (
          <RD.Portal forceMount>
            <RD.Overlay asChild forceMount>
              <motion.div
                className="fixed inset-0 z-[1000] bg-ink/30 backdrop-blur-sm"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
              />
            </RD.Overlay>
            <RD.Content asChild forceMount aria-describedby={undefined}>
              <motion.div
                className="fixed inset-4 z-[1010] flex flex-col rounded-2xl border border-hairline bg-surface p-4 shadow-2xl focus:outline-none md:inset-8"
                initial={{ opacity: 0, scale: 0.97 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.98 }}
                transition={{ duration: 0.2, ease: 'easeOut' }}
              >
                <div className="mb-2 flex shrink-0 items-center justify-between gap-4">
                  <RD.Title className="font-display text-sm font-bold text-ink">{title ?? 'Table'}</RD.Title>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => downloadCsv(title, cols, rows)}
                      aria-label="Download as CSV"
                      title="Download as CSV"
                      className="rounded-md p-1.5 text-muted transition-colors hover:bg-panel hover:text-ink"
                    >
                      <Download size={16} />
                    </button>
                    <RD.Close
                      aria-label="Close"
                      className="rounded-md p-1.5 text-muted transition-colors hover:bg-panel hover:text-ink"
                    >
                      <X size={18} />
                    </RD.Close>
                  </div>
                </div>
                <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-hairline">
                  <DataTable cols={cols} rows={rows} truncate={false} onCellClick={onCellClick} />
                </div>
              </motion.div>
            </RD.Content>
          </RD.Portal>
        )}
      </AnimatePresence>
    </RD.Root>
  )
}

export function TableView({ rows, title }: { rows: Record<string, unknown>[]; title?: string }) {
  const [cell, setCell] = useState<{ col: string; text: string } | null>(null)
  const [fullscreen, setFullscreen] = useState(false)

  const allEmpty = rows.every((r) => Object.values(r).every((v) => v == null || v === ''))
  if (!rows.length || allEmpty) {
    return <div className="grid h-full place-items-center p-6 text-sm text-muted">No matching rows.</div>
  }
  const cols = Object.keys(rows[0])
  const openCell = (col: string, text: string) => setCell({ col, text })

  return (
    <>
      <div className="flex h-full flex-col">
        <div className="flex shrink-0 items-center justify-end gap-1 border-b border-hairline bg-panel px-2 py-1">
          <button
            onClick={() => setFullscreen(true)}
            aria-label="View fullscreen"
            title="View fullscreen"
            className="rounded-md p-1 text-muted transition-colors hover:bg-surface hover:text-ink"
          >
            <Maximize2 size={14} />
          </button>
          <button
            onClick={() => downloadCsv(title, cols, rows)}
            aria-label="Download as CSV"
            title="Download as CSV"
            className="rounded-md p-1 text-muted transition-colors hover:bg-surface hover:text-ink"
          >
            <Download size={14} />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-auto">
          <DataTable cols={cols} rows={rows} truncate onCellClick={openCell} />
        </div>
      </div>

      <FullscreenModal
        open={fullscreen}
        onClose={() => setFullscreen(false)}
        title={title}
        cols={cols}
        rows={rows}
        onCellClick={openCell}
      />
      <CellModal cell={cell} onClose={() => setCell(null)} />
    </>
  )
}
