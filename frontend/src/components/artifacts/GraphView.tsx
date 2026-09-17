import { useCallback, useEffect, useMemo, useRef, useState, type ComponentRef } from 'react'
import { InteractiveNvlWrapper } from '@neo4j-nvl/react'
import type { Node as NvlNode, Relationship as NvlRel } from '@neo4j-nvl/base'
import { AnimatePresence, motion } from 'motion/react'
import { Maximize2, Minus, Plus, X } from 'lucide-react'
import type { GraphNode, SubGraph } from '../../types/contract'
import { buildLabelColors } from '../../lib/theme'
import { useEntityInfo } from '../../lib/entityInfo'
import { cn } from '../../lib/cn'
import { LAYOUTS, type LayoutKey } from '../../lib/graphLayouts'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { useTheme } from '../theme/ThemeProvider'
import { Skeleton } from '../ui/skeleton'

const LAYOUT_LABEL_KEYS: Record<LayoutKey, { label: string; hint: string }> = {
  forceDirected: { label: 'explore.layoutForce', hint: 'explore.layoutForceHint' },
  hierarchical: { label: 'explore.layoutTree', hint: 'explore.layoutTreeHint' },
}

const labelOf = (n: GraphNode): string => n.labels[0] ?? 'Node'

// NVL only draws node labels + arrowheads on the canvas renderer (WebGL shows neither); canvas is
// CPU-drawn, so fall back to WebGL past a node count where labels would be a soup anyway.
const CANVAS_MAX_NODES = 300
const MIN_NODE_SIZE = 12
const MAX_NODE_SIZE = 46
// show captions only once zoomed in enough to read them — declutters the fitted whole-graph view
const CAPTION_ZOOM = 0.65
// Ceiling for a fitted view: past this a small graph stops looking like a graph and starts
// looking like three circles.
const FIT_MAX_ZOOM = 1.1
// How far the zoom buttons and a node click may go. 3 is enough to read a caption on a dense
// cluster without losing the neighbours that give it meaning.
const MAX_ZOOM = 3
const MIN_ZOOM = 0.2
const ZOOM_STEP = 1.4
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
  const { t, entityLabel, propertyLabel } = useLanguage()
  const { resolvedTheme } = useTheme()
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

  const colors = useMemo(() => buildLabelColors(orderedLabels), [orderedLabels, resolvedTheme])
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

  // Refresh NVL node colours when theme tokens change without remounting the graph.
  useEffect(() => {
    if (ready) restyle()
  }, [resolvedTheme, ready, restyle])

  const onLayoutDone = useCallback(() => {
    // Cap the initial fit. Without a maxZoom a small graph - the 13-16 node case file beside
    // a complaint run - is scaled up until a handful of nodes fill the pane and every edge
    // runs off the edge of it. FIT_MAX_ZOOM keeps the whole shape on screen at a readable
    // size, which is the point of fitting rather than zooming.
    nvlRef.current?.fit(graph.nodes.map((n) => n.id), { maxZoom: FIT_MAX_ZOOM })
    syncCaptions()
    setReady(true)
  }, [graph, syncCaptions])

  // Explicit zoom, because the alternatives are all worse in a side panel: scroll-wheel zoom
  // fights the page scroll, and pinch needs a trackpad. Steps are multiplicative so each
  // press covers the same proportion of the range whatever the current scale.
  const zoomBy = useCallback((factor: number) => {
    const nvl = nvlRef.current
    const current = nvl?.getScale?.()
    if (!nvl || typeof current !== 'number') return
    nvl.setZoom?.(Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, current * factor)))
    syncCaptions()
  }, [syncCaptions])

  const fitAll = useCallback(() => {
    nvlRef.current?.fit(graph.nodes.map((n) => n.id), { animated: true, maxZoom: FIT_MAX_ZOOM })
    syncCaptions()
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
          // The same bounds the buttons use, so scroll-wheel zoom and the controls agree on
          // how far in and out the view can go.
          nvlOptions={{ disableTelemetry: true, renderer, minZoom: MIN_ZOOM, maxZoom: MAX_ZOOM }}
          nvlCallbacks={{ onLayoutDone, onZoomTransitionDone: syncCaptions }}
          mouseEventCallbacks={{
            onNodeClick: (node) => {
              setSelected(byId.get(node.id) ?? null)
              const keep = adjacency.get(node.id) ?? EMPTY
              // Zoom to the node AND its neighbours: a node alone tells you nothing about
              // why it is there. Allowed closer than the old 1.75, which left a two-neighbour
              // selection sitting small in the middle of an empty canvas.
              nvlRef.current?.fit([node.id, ...keep], { animated: true, maxZoom: MAX_ZOOM })
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

      {/* Zoom controls, bottom-right - clear of the legend (top-left) and the layout toggle
          (top-right), and out of the way of the renderer switch at bottom-centre. */}
      {ready && (
        <div className="absolute bottom-3 right-3 z-10 flex flex-col gap-0.5 rounded-lg border border-border bg-card/90 p-0.5 shadow-sm backdrop-blur">
          <button
            onClick={() => zoomBy(ZOOM_STEP)}
            aria-label={t('explore.zoomIn')}
            className="grid size-7 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <Plus size={14} />
          </button>
          <button
            onClick={() => zoomBy(1 / ZOOM_STEP)}
            aria-label={t('explore.zoomOut')}
            className="grid size-7 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <Minus size={14} />
          </button>
          <button
            onClick={fitAll}
            aria-label={t('explore.fitGraph')}
            className="grid size-7 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <Maximize2 size={13} />
          </button>
        </div>
      )}

      {!ready && (
        <div className="absolute inset-0 grid place-items-center overflow-hidden bg-background">
          <Skeleton className="absolute inset-0 h-full w-full rounded-none" />
          <span className="relative shimmer text-xs font-medium">{t('explore.layingOut')}</span>
        </div>
      )}

      <div className="pointer-events-none absolute left-3 top-3 flex max-w-[55%] flex-wrap gap-x-3 gap-y-1 rounded-lg border border-border bg-card/90 px-2.5 py-1.5 text-[11px] text-foreground backdrop-blur">
        {orderedLabels.map((l) => (
          <span
            key={l}
            title={entityInfo(l)}
            className="pointer-events-auto inline-flex cursor-help items-center gap-1"
          >
            <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: colors[l] }} />
            {entityLabel(l)}
            <span className="font-mono tabular-nums text-muted-foreground">{labelCounts.get(l)}</span>
          </span>
        ))}
      </div>

      {!controlled && (
        <div className="absolute right-3 top-3 inline-flex gap-0.5 rounded-lg border border-border bg-card/90 p-0.5 text-[11px] text-muted-foreground backdrop-blur">
          {LAYOUTS.map((l) => (
            <button
              key={l.key}
              onClick={() => setLayout(l.key)}
              title={t(LAYOUT_LABEL_KEYS[l.key].hint)}
              className={cn(
                'rounded-md px-2 py-0.5 transition-colors',
                layout === l.key ? 'bg-primary text-primary-foreground' : 'hover:text-foreground',
              )}
            >
              {t(LAYOUT_LABEL_KEYS[l.key].label)}
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
            className="absolute bottom-3 right-3 max-h-[72%] w-64 overflow-auto rounded-xl border border-border bg-card/95 p-3.5 text-xs text-card-foreground shadow-lg backdrop-blur-md"
          >
            <div className="mb-2.5 flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="inline-flex items-center gap-1.5">
                  <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: colors[labelOf(selected)] }} />
                  <span className="truncate text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    {selected.labels.map(entityLabel).join(' · ')}
                  </span>
                </div>
                <div className="mt-0.5 truncate font-display text-sm font-semibold text-foreground">{selected.caption}</div>
              </div>
              <button
                onClick={() => setSelected(null)}
                aria-label={t('common.close')}
                className="shrink-0 rounded-md p-0.5 text-muted-foreground transition-colors hover:text-foreground"
              >
                <X size={14} />
              </button>
            </div>
            {entityInfo(labelOf(selected)) && (
              <p className="mb-2.5 leading-relaxed text-muted-foreground">{entityInfo(labelOf(selected))}</p>
            )}
            <dl className="divide-y divide-border">
              {Object.entries(selected.properties)
                .slice(0, 12)
                .map(([k, v]) => (
                  <div key={k} className="flex items-center justify-between gap-3 py-1.5">
                    <dt className="shrink-0 text-muted-foreground">{propertyLabel(k)}</dt>
                    <dd className="truncate rounded-md bg-muted px-1.5 py-0.5 font-mono text-[11px] text-foreground">
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
