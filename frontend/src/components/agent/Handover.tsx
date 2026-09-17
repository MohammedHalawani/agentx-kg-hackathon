import { useState } from 'react'
import { motion } from 'motion/react'
import { ChevronDown, Network } from 'lucide-react'
import { Graph } from '../artifacts/Graph'
import { cn } from '../../lib/cn'
import type { SubGraph } from '../../types/contract'

// Which labels to summarise in the header strip, in the order a human reads a case: what it
// is, who it's for, who was carrying it, what happened, what went wrong, what was tried.
const SUMMARY_ORDER = [
  'Shipment',
  'Order',
  'Customer',
  'Address',
  'Courier',
  'Policy',
  'Event',
  'FailureReason',
  'Resolution',
  'Outcome',
]

// The case file attached to an escalated complaint: the shipment's own neighbourhood, drawn
// with the same renderer the Explore tab uses. Collapsed by default - the escalation reason
// is the headline, and the graph is what you open when you start actually working the case.
export function Handover({ graph }: { graph: SubGraph }) {
  const [open, setOpen] = useState(false)

  const counts = new Map<string, number>()
  for (const n of graph.nodes) {
    for (const l of n.labels) counts.set(l, (counts.get(l) ?? 0) + 1)
  }
  const summary = SUMMARY_ORDER.filter((l) => counts.has(l)).map((l) => ({ label: l, count: counts.get(l)! }))

  // The shipment this case file is about - the one node the whole view is anchored on.
  const shipment = graph.nodes.find((n) => n.labels.includes('Shipment'))

  return (
    <div className="ml-[116px] mt-2 overflow-hidden rounded-xl border border-hairline bg-panel">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-2.5 px-3 py-2.5 text-left transition-colors hover:bg-surface"
      >
        <Network size={15} className="shrink-0 text-accent" />
        <span className="min-w-0 flex-1">
          <span className="text-xs font-semibold text-ink">
            Case file{shipment ? ` — ${shipment.caption}` : ''}
          </span>
          <span className="mt-0.5 flex flex-wrap gap-x-2 gap-y-0.5 text-[11px] text-muted">
            {summary.map((s) => (
              <span key={s.label}>
                {s.count} {s.label}
                {s.count === 1 ? '' : 's'}
              </span>
            ))}
          </span>
        </span>
        <motion.span animate={{ rotate: open ? 180 : 0 }} transition={{ duration: 0.2 }} className="shrink-0 text-muted">
          <ChevronDown size={15} />
        </motion.span>
      </button>

      {open && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: 'auto', opacity: 1 }}
          transition={{ duration: 0.25, ease: 'easeOut' }}
          className="border-t border-hairline"
        >
          <p className="px-3 py-2 text-[11px] text-muted">
            Everything the graph holds about this shipment — who it belongs to, where it was going, who was carrying it,
            every scan on its journey, and any fix already attempted. Click a node to inspect its properties.
          </p>
          <div className={cn('h-[420px] w-full border-t border-hairline')}>
            <Graph graph={graph} />
          </div>
        </motion.div>
      )}
    </div>
  )
}
