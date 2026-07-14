import { useState } from 'react'
import { Box, Share2 } from 'lucide-react'
import type { SubGraph } from '../../types/contract'
import type { LayoutKey } from '../../lib/graphLayouts'
import { cn } from '../../lib/cn'
import { GraphView } from './GraphView'
import { BrainGraph } from './BrainGraph'

const KEY = 'kg-graph-renderer'
type Renderer = 'classic' | 'brain'

interface GraphProps {
  graph: SubGraph
  layout?: LayoutKey
  onLayoutChange?: (layout: LayoutKey) => void
}

// Chooses between the two graph renderers and remembers the pick in localStorage so it's app-wide.
// "2D" is the Neo4j-NVL node-link view; "3D" is the force-directed WebGL view. (Internal keys stay
// 'classic'/'brain'.) Both renderers are prop-compatible, so this wrapper is the only thing that
// knows there are two.
export function Graph(props: GraphProps) {
  const [renderer, setRenderer] = useState<Renderer>(() =>
    typeof localStorage !== 'undefined' && localStorage.getItem(KEY) === 'brain' ? 'brain' : 'classic',
  )
  const pick = (r: Renderer) => {
    setRenderer(r)
    try {
      localStorage.setItem(KEY, r)
    } catch {
      // ignore - a private-mode localStorage failure just means the choice doesn't persist
    }
  }

  return (
    <div className="relative h-full w-full">
      {renderer === 'brain' ? <BrainGraph {...props} /> : <GraphView {...props} />}

      {/* renderer switch, bottom-center to clear the legend (top-left) and layout toggle (top-right) */}
      <div className="absolute bottom-3 left-1/2 z-10 inline-flex -translate-x-1/2 gap-0.5 rounded-lg border border-hairline bg-panel/85 p-0.5 text-[11px] text-muted shadow-sm backdrop-blur">
        <button
          onClick={() => pick('classic')}
          className={cn('inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 transition-colors', renderer === 'classic' ? 'bg-accent text-white' : 'hover:text-ink')}
        >
          <Share2 size={13} />
          2D
        </button>
        <button
          onClick={() => pick('brain')}
          className={cn('inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 transition-colors', renderer === 'brain' ? 'bg-accent text-white' : 'hover:text-ink')}
        >
          <Box size={13} />
          3D
        </button>
      </div>
    </div>
  )
}
