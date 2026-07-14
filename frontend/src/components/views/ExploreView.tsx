import { useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { BrainCircuit, Map as MapIcon, Workflow } from 'lucide-react'
import { cn } from '../../lib/cn'
import { BrainView } from './BrainView'
import { MapAllView } from './MapAllView'
import { SchemaView } from './SchemaView'

type Lens = 'graph' | 'map' | 'schema'

const LENSES: { key: Lens; label: string; icon: typeof BrainCircuit; hint: string }[] = [
  { key: 'graph', label: 'Graph', icon: BrainCircuit, hint: 'A sample of the whole knowledge graph - the entities and how they connect.' },
  { key: 'map', label: 'Map', icon: MapIcon, hint: 'Incidents and real track-status field photos, plotted geographically.' },
  { key: 'schema', label: 'Schema', icon: Workflow, hint: 'The data model itself - the types of things in the graph and how they relate.' },
]

// The three read-only lenses on the data — graph, map, schema — behind one nav entry, switched by a
// segmented control so they stay one click away without each taking a full slot in the app rail.
export function ExploreView() {
  const [lens, setLens] = useState<Lens>('graph')

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 justify-center border-b border-hairline bg-panel px-4 py-2.5">
        <div className="inline-flex gap-0.5 rounded-lg border border-hairline bg-surface p-0.5 text-sm">
          {LENSES.map(({ key, label, icon: Icon, hint }) => (
            <button
              key={key}
              onClick={() => setLens(key)}
              title={hint}
              className={cn(
                'relative inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 font-medium transition-colors',
                lens === key ? 'text-white' : 'text-muted hover:text-ink',
              )}
            >
              {lens === key && (
                <motion.span
                  layoutId="explore-lens"
                  className="absolute inset-0 rounded-md bg-accent"
                  transition={{ type: 'spring', stiffness: 400, damping: 32 }}
                />
              )}
              <Icon size={15} className="relative z-10" />
              <span className="relative z-10">{label}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={lens}
            className="h-full"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15, ease: 'easeOut' }}
          >
            {lens === 'graph' && <BrainView />}
            {lens === 'map' && <MapAllView />}
            {lens === 'schema' && <SchemaView />}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  )
}
