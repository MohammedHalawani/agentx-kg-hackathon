import { useFetch } from '../../hooks/useFetch'
import type { SubGraph } from '../../types/contract'
import { Graph } from '../artifacts/Graph'
import { Skeleton } from '../ui/Skeleton'
import { Center, Frame } from './shell'

// The data model itself: node labels + relationship types as a graph. Switch to Tree layout to
// read it as a blueprint.
export function SchemaView() {
  const { data, loading } = useFetch<SubGraph>('/schema')
  return (
    <Frame>
      {loading ? (
        <Skeleton className="h-full w-full rounded-none" />
      ) : data?.nodes?.length ? (
        <Graph graph={data} />
      ) : (
        <Center>Schema unavailable.</Center>
      )}
    </Frame>
  )
}
