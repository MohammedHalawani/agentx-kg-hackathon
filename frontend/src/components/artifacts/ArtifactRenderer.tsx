import { useState, type ReactNode } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { BrainCircuit, Map as MapTabIcon, Maximize2, Table2 } from 'lucide-react'
import type { Artifact } from '../../types/contract'
import { cn } from '../../lib/cn'
import { Graph } from './Graph'
import { LAYOUTS, type LayoutKey } from '../../lib/graphLayouts'
import { MapView } from './MapView'
import { TableView } from './TableView'

interface Tab {
  key: string
  label: string
  icon?: ReactNode
  render: () => ReactNode
}

interface ArtifactRendererProps {
  artifact: Artifact
  onExpand?: () => void // when set, shows an expand affordance (used by the inline card)
}

// A single segmented-control visual language, reused for both groups in the control bar.
const segment = (active: boolean) =>
  cn(
    'inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors',
    active ? 'bg-panel text-ink shadow-sm' : 'text-muted hover:text-ink',
  )

// Tabbed surface: each view fills the pane. The graph (the "brain") is listed first, so it's the
// default lens. Tabs are built from what the artifact carries — add a viz = one more push().
export function ArtifactRenderer({ artifact, onExpand }: ArtifactRendererProps) {
  const [graphLayout, setGraphLayout] = useState<LayoutKey>('forceDirected')

  const tabs: Tab[] = []
  if (artifact.graph?.nodes?.length) {
    tabs.push({
      key: 'graph',
      label: 'Graph',
      icon: <BrainCircuit size={14} />,
      render: () => <Graph graph={artifact.graph!} layout={graphLayout} onLayoutChange={setGraphLayout} />,
    })
  }
  if (artifact.incidents?.length) {
    tabs.push({
      key: 'map',
      label: 'Map',
      icon: <MapTabIcon size={14} />,
      render: () => <MapView incidents={artifact.incidents ?? []} />,
    })
  }
  if (artifact.rows?.length) {
    tabs.push({ key: 'table', label: 'Table', icon: <Table2 size={14} />, render: () => <TableView rows={artifact.rows ?? []} /> })
  }

  const [active, setActive] = useState(tabs[0]?.key)

  if (!tabs.length) {
    return (
      <div className="grid h-full place-items-center p-6 text-center text-sm text-muted">
        This answer didn't run a query. Ask a data, map, or graph question to see something here.
      </div>
    )
  }

  const current = tabs.find((t) => t.key === active) ?? tabs[0]

  return (
    <div className="flex h-full flex-col">
      {/* one consolidated control bar: view tabs, the graph-only layout toggle, then expand */}
      <div className="mb-2.5 flex shrink-0 flex-wrap items-center gap-2">
        <div className="inline-flex gap-0.5 rounded-lg border border-hairline bg-surface p-0.5">
          {tabs.map((t) => (
            <button key={t.key} onClick={() => setActive(t.key)} className={segment(t.key === current.key)}>
              {t.icon}
              {t.label}
            </button>
          ))}
        </div>

        {current.key === 'graph' && (
          <div className="inline-flex gap-0.5 rounded-lg border border-hairline bg-surface p-0.5">
            {LAYOUTS.map((l) => (
              <button key={l.key} onClick={() => setGraphLayout(l.key)} title={l.hint} className={segment(graphLayout === l.key)}>
                {l.label}
              </button>
            ))}
          </div>
        )}

        {onExpand && (
          <button
            onClick={onExpand}
            aria-label="Expand"
            className="ml-auto rounded-md border border-hairline p-1.5 text-muted transition-colors hover:border-accent hover:text-ink"
          >
            <Maximize2 size={14} />
          </button>
        )}
      </div>
      <section className="relative min-h-0 flex-1 overflow-hidden rounded-xl border border-hairline bg-surface">
        <AnimatePresence mode="wait">
          <motion.div
            key={current.key}
            className="h-full"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
          >
            {current.render()}
          </motion.div>
        </AnimatePresence>
      </section>
    </div>
  )
}
