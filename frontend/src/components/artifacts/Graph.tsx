import { useState } from 'react'
import { Box, Share2 } from 'lucide-react'
import type { SubGraph } from '../../types/contract'
import type { LayoutKey } from '../../lib/graphLayouts'
import { useLanguage } from '@/components/i18n/LanguageProvider'
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

export function Graph(props: GraphProps) {
  const { t } = useLanguage()
  const [renderer, setRenderer] = useState<Renderer>(() =>
    typeof localStorage !== 'undefined' && localStorage.getItem(KEY) === 'brain' ? 'brain' : 'classic',
  )
  const pick = (r: Renderer) => {
    setRenderer(r)
    try {
      localStorage.setItem(KEY, r)
    } catch {
      // ignore
    }
  }

  return (
    <div className="relative h-full w-full">
      {renderer === 'brain' ? <BrainGraph {...props} /> : <GraphView {...props} />}

      <div className="absolute bottom-3 left-1/2 z-10 inline-flex -translate-x-1/2 gap-0.5 rounded-lg border border-border bg-card/90 p-0.5 text-[11px] text-muted-foreground shadow-sm backdrop-blur">
        <button
          onClick={() => pick('classic')}
          className={cn(
            'inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 transition-colors',
            renderer === 'classic' ? 'bg-primary text-primary-foreground' : 'hover:text-foreground',
          )}
        >
          <Share2 size={13} />
          {t('explore.renderer2d')}
        </button>
        <button
          onClick={() => pick('brain')}
          className={cn(
            'inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 transition-colors',
            renderer === 'brain' ? 'bg-primary text-primary-foreground' : 'hover:text-foreground',
          )}
        >
          <Box size={13} />
          {t('explore.renderer3d')}
        </button>
      </div>
    </div>
  )
}
