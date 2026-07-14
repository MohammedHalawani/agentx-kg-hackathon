import { useCallback, useEffect, useMemo, useRef, useState, type ComponentRef } from 'react'
import { InteractiveNvlWrapper } from '@neo4j-nvl/react'
import type { Node as NvlNode, Relationship as NvlRel } from '@neo4j-nvl/base'
import { AnimatePresence, motion } from 'motion/react'
import { X } from 'lucide-react'
import type { GraphNode, SubGraph } from '../../types/contract'
import { buildLabelColors } from '../../lib/theme'
import { useEntityInfo } from '../../lib/entityInfo'
import { cn } from '../../lib/cn'
import { LAYOUTS, type LayoutKey } from '../../lib/graphLayouts'
import { humanizeKey } from '../../lib/humanizeKey'
import { Skeleton } from '../ui/Skeleton'

const labelOf = (n: GraphNode): string => n.labels[0] ?? 'Node'

// NVL only draws node labels + arrowheads on the canvas renderer (WebGL shows neither); canvas is
// CPU-drawn, so fall back to WebGL past a node count where labels would be a soup anyway.
const CANVAS_MAX_NODES = 300
const MIN_NODE_SIZE = 12
const MAX_NODE_SIZE = 46
// show captions only once zoomed in enough to read them — declutters the fitted whole-graph view
const CAPTION_ZOOM = 0.65
const EMPTY = new Set<string>()

interface GraphViewProps {
  graph: SubGraph
  // when both are given, the layout toggle is controlled by the caller (e.g. ArtifactRenderer's
  // consolidated control bar) and GraphView's own floating toggle is hidden. Standalone callers
  // (SchemaView, BrainView) omit these and keep the built-in toggle - fully backward compatible.
  layout?: LayoutKey
  onLayoutChange?: (layout: LayoutKey) => void
}

// the graph renders on the app's warm-light surface; nodes carry the color, edges stay quiet
export function GraphView({ graph, layout: layoutProp, onLayoutChange }: GraphViewProps) {
  const [internalLayout, setInternalLayout] = useState<LayoutKey>('forceDirected')
  const controlled = layoutProp !== undefined && onLayoutChange !== undefined
  const layout = controlled ? layoutProp : internalLayout
  const setLayout = controlled ? onLayoutChange : setInternalLayout
  const [selected, setSelected] = useState<GraphNode | null>(null)
  const entityInfo = useEntityInfo() // label -> description, fetched from the backend ontology

  const orderedLabels = useMemo(() => {
    const seen = new Set<string>()
    for (const n of graph.nodes) seen.add(labelOf(n))
    return [...seen]
  }, [graph])

  const labelCounts = useMemo(() => {
    const c = new Map<string, number>()
    for (const n of graph.nodes) c.set(labelOf(n), (c.get(labelOf(n)) ?? 0) + 1)
    return c
  }, [graph])

  // degree drives node size (hub emphasis); adjacency drives hover focus + click-to-frame
  const { degree, adjacency } = useMemo(() => {
    const degree = new Map<string, number>()
    const adjacency = new Map<string, Set<string>>()
    for (const r of graph.relationships) {
      degree.set(r.from, (degree.get(r.from) ?? 0) + 1)
      degree.set(r.to, (degree.get(r.to) ?? 0) + 1)
      ;(adjacency.get(r.from) ?? adjacency.set(r.from, new Set()).get(r.from)!).add(r.to)
      ;(adjacency.get(r.to) ?? adjacency.set(r.to, new Set()).get(r.to)!).add(r.from)
    }
    return { degree, adjacency }
  }, [graph])

  const colors = useMemo(() => buildLabelColors(orderedLabels), [orderedLabels])
  const byId = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n])), [graph])
  const sizeById = useMemo(() => {
    const m = new Map<string, number>()
    for (const n of graph.nodes) {
      m.set(n.id, Math.min(MAX_NODE_SIZE, MIN_NODE_SIZE + 6 * Math.sqrt(degree.get(n.id) ?? 0)))
    }
    return m
  }, [graph, degree])

  // captions start hidden (the fitted view is zoomed out); the zoom sync reveals them past CAPTION_ZOOM
  const nodes: NvlNode[] = useMemo(
    () =>
      graph.nodes.map((n) => ({
        id: n.id,
        captions: [],
        color: colors[labelOf(n)],
        size: sizeById.get(n.id),
      })),
    [graph, colors, sizeById],
  )
  // no edge captions: on the canvas renderer they'd clutter a dense graph — arrows carry direction
  const rels: NvlRel[] = useMemo(
    () => graph.relationships.map((r) => ({ id: r.id, from: r.from, to: r.to })),
    [graph],
  )

  const renderer = graph.nodes.length > CANVAS_MAX_NODES ? 'webgl' : 'canvas'

  const nvlRef = useRef<ComponentRef<typeof InteractiveNvlWrapper>>(null)
  const [ready, setReady] = useState(false)
  const labelsRef = useRef(false) // are captions currently shown?
  const focusRef = useRef<string | null>(null) // hovered/focused node for the spotlight

  // One full-style restyle for every node, so caption-toggling and hover-dimming compose cleanly
  // regardless of how updateElementsInGraph merges. Non-neighbours of the focus node are dimmed.
  const restyle = useCallback(() => {
    const focus = focusRef.current
    const keep = focus ? adjacency.get(focus) ?? EMPTY : null
    nvlRef.current?.updateElementsInGraph(
      graph.nodes.map((n) => ({
        id: n.id,
        color: colors[labelOf(n)],
        size: sizeById.get(n.id),
        captions: labelsRef.current ? [{ value: n.caption }] : [],
        disabled: keep ? !(n.id === focus || keep.has(n.id)) : false,
      })),
      [],
    )
  }, [graph, colors, sizeById, adjacency])

  const setLabels = useCallback(
    (show: boolean) => {
      if (labelsRef.current === show) return
      labelsRef.current = show
      restyle()
    },
    [restyle],
  )
  // getScale isn't fired by programmatic fit, so read it directly after fit/zoom transitions
  const syncCaptions = useCallback(() => {
    const scale = nvlRef.current?.getScale?.()
    setLabels(typeof scale === 'number' ? scale >= CAPTION_ZOOM : graph.nodes.length <= 30)
  }, [setLabels, graph])

  useEffect(() => {
    setReady(false)
    labelsRef.current = false
    focusRef.current = null
  }, [graph])

  const onLayoutDone = useCallback(() => {
    nvlRef.current?.fit(graph.nodes.map((n) => n.id))
    syncCaptions()
    setReady(true)
  }, [graph, syncCaptions])

  // hover a node → spotlight it + neighbours (dim the rest); restore off-node
  const setFocus = useCallback(
    (id: string | null) => {
      if (focusRef.current === id) return
      focusRef.current = id
      restyle()
    },
    [restyle],
  )

  return (
    <div className="relative h-full w-full overflow-hidden bg-surface" onMouseLeave={() => setFocus(null)}>
      <div className={`h-full w-full transition-opacity duration-500 ${ready ? 'opacity-100' : 'opacity-0'}`}>
        <InteractiveNvlWrapper
          ref={nvlRef}
          nodes={nodes}
          rels={rels}
          layout={layout}
          nvlOptions={{ disableTelemetry: true, renderer }}
          nvlCallbacks={{ onLayoutDone, onZoomTransitionDone: syncCaptions }}
          mouseEventCallbacks={{
            onNodeClick: (node) => {
              setSelected(byId.get(node.id) ?? null)
              const keep = adjacency.get(node.id) ?? EMPTY
              nvlRef.current?.fit([node.id, ...keep], { animated: true, maxZoom: 1.75 })
            },
            onCanvasClick: () => {
              setSelected(null)
              setFocus(null)
            },
            onHover: (el?: { id: string }) => setFocus(el?.id && byId.has(el.id) ? el.id : null),
            onZoom: (scale: number) => setLabels(scale >= CAPTION_ZOOM),
            onPan: true,
            onDrag: true,
          }}
          className="h-full w-full"
        />
      </div>

      {!ready && (
        <div className="absolute inset-0 grid place-items-center overflow-hidden bg-surface">
          <Skeleton className="absolute inset-0 h-full w-full rounded-none" />
          <span className="relative shimmer text-xs font-medium">Laying out the graph…</span>
        </div>
      )}

      <div className="pointer-events-none absolute left-3 top-3 flex max-w-[55%] flex-wrap gap-x-3 gap-y-1 rounded-lg border border-hairline bg-panel/80 px-2.5 py-1.5 text-[11px] text-ink backdrop-blur">
        {orderedLabels.map((l) => (
          <span
            key={l}
            title={entityInfo(l)}
            className="pointer-events-auto inline-flex cursor-help items-center gap-1"
          >
            <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: colors[l] }} />
            {l}
            <span className="font-mono tabular-nums text-muted">{labelCounts.get(l)}</span>
          </span>
        ))}
      </div>

      {!controlled && (
        <div className="absolute right-3 top-3 inline-flex gap-0.5 rounded-lg border border-hairline bg-panel/80 p-0.5 text-[11px] text-muted backdrop-blur">
          {LAYOUTS.map((l) => (
            <button
              key={l.key}
              onClick={() => setLayout(l.key)}
              title={l.hint}
              className={cn(
                'rounded-md px-2 py-0.5 transition-colors',
                layout === l.key ? 'bg-accent text-white' : 'hover:text-ink',
              )}
            >
              {l.label}
            </button>
          ))}
        </div>
      )}

      <AnimatePresence>
        {selected && (
          <motion.div
            key={selected.id}
            initial={{ opacity: 0, x: 12 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 12 }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
            className="absolute bottom-3 right-3 max-h-[72%] w-64 overflow-auto rounded-xl border border-hairline bg-panel/95 p-3.5 text-xs shadow-lg backdrop-blur-md"
          >
            <div className="mb-2.5 flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="inline-flex items-center gap-1.5">
                  <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: colors[labelOf(selected)] }} />
                  <span className="truncate text-[10px] font-semibold uppercase tracking-wider text-muted">
                    {selected.labels.join(' · ')}
                  </span>
                </div>
                <div className="mt-0.5 truncate font-display text-sm font-semibold text-ink">{selected.caption}</div>
              </div>
              <button
                onClick={() => setSelected(null)}
                aria-label="Close"
                className="shrink-0 rounded-md p-0.5 text-muted transition-colors hover:text-ink"
              >
                <X size={14} />
              </button>
            </div>
            {entityInfo(labelOf(selected)) && (
              <p className="mb-2.5 leading-relaxed text-muted">{entityInfo(labelOf(selected))}</p>
            )}
            <dl className="divide-y divide-hairline">
              {Object.entries(selected.properties)
                .slice(0, 12)
                .map(([k, v]) => (
                  <div key={k} className="flex items-center justify-between gap-3 py-1.5">
                    <dt className="shrink-0 text-muted">{humanizeKey(k)}</dt>
                    <dd className="truncate rounded-md bg-surface px-1.5 py-0.5 font-mono text-[11px] text-ink">
                      {String(v)}
                    </dd>
                  </div>
                ))}
            </dl>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
