import { RefreshCw } from 'lucide-react'
import { useFetch } from '../../hooks/useFetch'
import type { SubGraph } from '../../types/contract'
import { Graph } from '../artifacts/Graph'
import { Skeleton } from '../ui/Skeleton'
import { Center, Frame } from './shell'

// The domain graph is far too large to render in full (tens of thousands of nodes), so this shows
// a fresh connected slice - random seed nodes plus their neighbourhood, not scoped to the chat.
// "Show another part" reseeds to a different region. Click a node for its properties; toggle
// Force/Tree layout in the corner.
export function BrainView() {
  const { data, loading, refetch } = useFetch<SubGraph>('/graph')
  return (
    <Frame>
      <div className="relative h-full w-full">
        {loading ? (
          <Skeleton className="h-full w-full rounded-none" />
        ) : data?.nodes?.length ? (
          <Graph graph={data} />
        ) : (
          <Center>No graph data available.</Center>
        )}
        <button
          onClick={refetch}
          disabled={loading}
          className="absolute bottom-3 left-3 z-10 inline-flex items-center gap-1.5 rounded-lg border border-hairline bg-panel/90 px-2.5 py-1.5 text-[11px] font-medium text-muted backdrop-blur transition-colors hover:text-ink disabled:opacity-50"
        >
          <RefreshCw size={12} className={loading ? 'animate-spin' : undefined} />
          Show another part of the graph
        </button>
      </div>
    </Frame>
  )
}
