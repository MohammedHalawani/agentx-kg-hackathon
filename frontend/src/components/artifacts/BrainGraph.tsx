import { useEffect, useMemo, useRef, useState } from 'react'
import ForceGraph3D, { type ForceGraphMethods } from 'react-force-graph-3d'
import { AnimatePresence, motion } from 'motion/react'
import { X } from 'lucide-react'
import type { GraphNode, Incident, SubGraph } from '../../types/contract'
import { buildLabelColors, cssVar } from '../../lib/theme'
import { useEntityInfo } from '../../lib/entityInfo'
import { humanizeKey } from '../../lib/humanizeKey'
import { LAYOUTS, type LayoutKey } from '../../lib/graphLayouts'
import { cn } from '../../lib/cn'
import { MapView } from './MapView'

const labelOf = (n: GraphNode): string => n.labels[0] ?? 'Node'

// Resolve a CSS custom property (an oklch() string) to a hex three.js can use, via a 1px canvas -
// so the 3D scene's background + edges are the app's real light-theme tokens, not hardcoded values.
function tokenHex(varName: string): string {
  const c = document.createElement('canvas')
  c.width = c.height = 1
  const ctx = c.getContext('2d')
  if (!ctx) return '#000000'
  ctx.fillStyle = cssVar(varName)
  ctx.fillRect(0, 0, 1, 1)
  const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data
  return '#' + [r, g, b].map((x) => x.toString(16).padStart(2, '0')).join('')
}

// Linear blend of two #rrggbb colors. On the light surface, blending a node's own colour toward
// the background reads like lowering opacity but stays crisp - so recede == wash out, keep the hue.
function mix(a: string, b: string, t: number): string {
  const pa = parseInt(a.slice(1), 16)
  const pb = parseInt(b.slice(1), 16)
  const lerp = (shift: number) => {
    const x = (pa >> shift) & 255
    const y = (pb >> shift) & 255
    return Math.round(x + (y - x) * t)
  }
  return '#' + ((1 << 24) | (lerp(16) << 16) | (lerp(8) << 8) | lerp(0)).toString(16).slice(1)
}

// A node's photo path, if any: the graph stores an absolute local path; the backend serves it by
// basename under /images/ (mirrors query._image_url), so nothing outside data/images/ is reachable.
function toImageUrl(path: unknown): string | null {
  return typeof path === 'string' && path ? `/images/${path.split('/').pop()}` : null
}
function nodeImageUrl(props: Record<string, unknown>): string | null {
  return toImageUrl(props.image_path)
}
// A node's coordinate, if any: stored as [lon, lat]; MapView wants {lat, lon}. Also forwards a
// DataEntry's own real photo(s) (its `photos` property) and status fields, so its mini-map popup
// shows the same real detail the standalone Track Status map does - Observation/Incident nodes
// have no `photos` property, so they're unaffected (Incidents never show a photo, by design).
function nodeCoord(props: Record<string, unknown>): Incident | null {
  const loc = props.location
  if (!(Array.isArray(loc) && loc.length === 2 && typeof loc[0] === 'number' && typeof loc[1] === 'number')) {
    return null
  }
  const photos = props.photos
  return {
    lat: loc[1],
    lon: loc[0],
    categories: [],
    images: Array.isArray(photos) ? photos.map(toImageUrl).filter((u): u is string => u !== null) : undefined,
    status: typeof props.status === 'string' ? props.status : undefined,
    entry_action: typeof props.entry_action === 'string' ? props.entry_action : undefined,
    notes: typeof props.notes === 'string' ? props.notes : undefined,
    date: typeof props.date === 'string' ? props.date : undefined,
  }
}
// keys already shown visually (thumbnail / mini-map) or just noise - kept out of the property list
const HIDDEN_PROPS = new Set(['image_path', 'image_format', 'location', 'maps_url'])

// react-force-graph resolves link.source/target from ids to node objects after the first tick,
// and mutates each node with x/y/z once the layout runs.
interface BNode {
  id: string
  label: string
  caption: string
  color: string
  val: number
  node: GraphNode
  x?: number
  y?: number
  z?: number
}
interface BLink {
  source: string | BNode
  target: string | BNode
  curvature: number // bow each edge into an arc so the web reads like synapses, not a wiring diagram
  rotation: number // the arc's plane around the source->target axis (3D), spread so arcs don't stack
}
const endId = (e: string | BNode): string => (typeof e === 'string' ? e : e.id)

interface BrainGraphProps {
  graph: SubGraph
  layout?: LayoutKey
  onLayoutChange?: (layout: LayoutKey) => void
}

// A 3D force-directed rendering of the same subgraph GraphView draws, on the app's LIGHT surface
// with the same node palette and visible edges. Cinematic on-scheme touches: the layout springs
// out on load; clicking a node glides the camera to it, pins focus (unrelated nodes dim + shrink),
// and fires signal particles down its links; the detail card renders the node's photo + a mini map.
export function BrainGraph({ graph, layout: layoutProp, onLayoutChange }: BrainGraphProps) {
  const entityInfo = useEntityInfo()
  const fgRef = useRef<ForceGraphMethods<BNode, BLink> | undefined>(undefined)
  const wrapRef = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ w: 0, h: 0 })
  const [hoverId, setHoverId] = useState<string | null>(null)
  const [selected, setSelected] = useState<GraphNode | null>(null)

  const scene = useMemo(
    () => ({
      bg: tokenHex('--color-surface'),
      link: tokenHex('--color-muted'), // neutral fallback for a link whose endpoint colour is unknown
      signal: cssVar('--marker'),
    }),
    [],
  )

  const [internalLayout, setInternalLayout] = useState<LayoutKey>('forceDirected')
  const controlled = layoutProp !== undefined && onLayoutChange !== undefined
  const layout = controlled ? layoutProp : internalLayout
  const setLayout = controlled ? onLayoutChange : setInternalLayout

  const orderedLabels = useMemo(() => {
    const seen = new Set<string>()
    for (const n of graph.nodes) seen.add(labelOf(n))
    return [...seen]
  }, [graph])
  const colors = useMemo(() => buildLabelColors(orderedLabels), [orderedLabels])
  // id -> node colour, so a link can inherit the tint of the two nodes it joins (no more grey lines)
  const nodeColorById = useMemo(() => {
    const m = new Map<string, string>()
    for (const n of graph.nodes) m.set(n.id, colors[labelOf(n)])
    return m
  }, [graph, colors])
  const labelCounts = useMemo(() => {
    const c = new Map<string, number>()
    for (const n of graph.nodes) c.set(labelOf(n), (c.get(labelOf(n)) ?? 0) + 1)
    return c
  }, [graph])

  const { degree, adjacency } = useMemo(() => {
    const degree = new Map<string, number>()
    const adjacency = new Map<string, Set<string>>()
    const link = (a: string, b: string) => {
      degree.set(a, (degree.get(a) ?? 0) + 1)
      ;(adjacency.get(a) ?? adjacency.set(a, new Set()).get(a)!).add(b)
    }
    for (const r of graph.relationships) {
      link(r.from, r.to)
      link(r.to, r.from)
    }
    return { degree, adjacency }
  }, [graph])

  const data = useMemo(
    () => ({
      nodes: graph.nodes.map<BNode>((n) => ({
        id: n.id,
        label: labelOf(n),
        caption: n.caption,
        color: colors[labelOf(n)],
        val: 1 + Math.sqrt(degree.get(n.id) ?? 0) * 2,
        node: n,
      })),
      links: graph.relationships.map<BLink>((r, i) => ({
        source: r.from,
        target: r.to,
        curvature: 0.2 + (i % 4) * 0.08, // 0.2..0.44, stable per link (no per-render jitter)
        rotation: (i * 2.399963) % (Math.PI * 2), // golden-angle spread of arc planes
      })),
    }),
    [graph, colors, degree],
  )

  useEffect(() => {
    setSelected(null)
    setHoverId(null)
  }, [graph])

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: e.contentRect.height }))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // hover takes precedence for transient exploration; otherwise the clicked node stays in focus
  const focusId = hoverId ?? selected?.id ?? null
  const neighbours = focusId ? adjacency.get(focusId) : undefined
  const isLit = (id: string): boolean => !focusId || id === focusId || Boolean(neighbours?.has(id))
  const linkOn = (l: BLink): boolean => endId(l.source) === focusId || endId(l.target) === focusId
  // a link's own colour = the blend of the two nodes it connects (two-tone web, not uniform grey)
  const linkBase = (l: BLink): string =>
    mix(nodeColorById.get(endId(l.source)) ?? scene.link, nodeColorById.get(endId(l.target)) ?? scene.link, 0.5)

  // glide + center the camera on a node (its data carries x/y/z once the layout has run)
  const flyTo = (node: BNode) => {
    const { x = 0, y = 0, z = 0 } = node
    const h = Math.hypot(x, y, z)
    const ratio = h > 0 ? 1 + 110 / h : 1
    const pos = h > 0 ? { x: x * ratio, y: y * ratio, z: z * ratio } : { x, y, z: 110 }
    fgRef.current?.cameraPosition(pos, { x, y, z }, 900) // eased tween
  }

  return (
    <div ref={wrapRef} className="relative h-full w-full overflow-hidden bg-surface">
      {size.w > 0 && (
        <ForceGraph3D
          ref={fgRef}
          width={size.w}
          height={size.h}
          graphData={data}
          backgroundColor={scene.bg}
          showNavInfo={false}
          controlType="orbit"
          warmupTicks={0} // watch the layout spring outward on load instead of appearing pre-settled
          dagMode={layout === 'hierarchical' ? 'td' : undefined}
          dagLevelDistance={60}
          nodeLabel={(n) => (n as BNode).caption}
          nodeVal={(n) => {
            const node = n as BNode
            if (node.id === focusId) return node.val * 1.6 // ~1.15x radius pop on the focused node
            return isLit(node.id) ? node.val : node.val * 0.7 // unrelated nodes recede
          }}
          nodeColor={(n) => {
            const node = n as BNode
            // focus + neighbours keep full colour; everything else recedes toward the surface
            return isLit(node.id) ? node.color : mix(node.color, scene.bg, 0.82)
          }}
          nodeOpacity={1}
          nodeResolution={14}
          linkColor={(l) => {
            const link = l as BLink
            const base = linkBase(link)
            if (!focusId) return mix(base, scene.bg, 0.35) // calm tinted web at rest
            return linkOn(link) ? scene.signal : mix(base, scene.bg, 0.85) // active path pops; rest recede
          }}
          linkWidth={(l) => (focusId && linkOn(l as BLink) ? 1.4 : 0.6)}
          linkCurvature={(l) => (l as BLink).curvature}
          linkCurveRotation={(l) => (l as BLink).rotation}
          linkOpacity={0.65}
          linkDirectionalParticles={(l) => (focusId && linkOn(l as BLink) ? 4 : 1)}
          linkDirectionalParticleWidth={1.6}
          linkDirectionalParticleSpeed={0.01}
          linkDirectionalParticleColor={() => scene.signal}
          onNodeHover={(n) => {
            setHoverId((n as BNode | null)?.id ?? null)
            if (wrapRef.current) wrapRef.current.style.cursor = n ? 'pointer' : 'grab'
          }}
          onNodeClick={(n) => {
            const node = n as BNode
            setSelected(node.node)
            flyTo(node)
          }}
          onBackgroundClick={() => {
            setSelected(null)
            setHoverId(null)
          }}
          onEngineStop={() => fgRef.current?.zoomToFit(600, 60)}
        />
      )}

      <div className="pointer-events-none absolute left-3 top-3 flex max-w-[55%] flex-wrap gap-x-3 gap-y-1 rounded-lg border border-hairline bg-panel/80 px-2.5 py-1.5 text-[11px] text-ink backdrop-blur">
        {orderedLabels.map((l) => (
          <span key={l} title={entityInfo(l)} className="pointer-events-auto inline-flex cursor-help items-center gap-1">
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
              className={cn('rounded-md px-2 py-0.5 transition-colors', layout === l.key ? 'bg-accent text-white' : 'hover:text-ink')}
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
            // top edge inherits the clicked node's colour, tying the card back to the graph
            style={{ borderTopColor: colors[labelOf(selected)], borderTopWidth: 2 }}
            className="absolute bottom-3 right-3 max-h-[80%] w-72 overflow-auto rounded-xl border border-hairline bg-panel/95 p-3.5 text-xs shadow-lg backdrop-blur-md"
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

            {/* visual data: the node's photo and where it is, rendered rather than dumped as text */}
            {nodeImageUrl(selected.properties) && (
              <img
                src={nodeImageUrl(selected.properties)!}
                alt={selected.caption}
                loading="lazy"
                className="mb-2.5 h-28 w-full rounded-lg border border-hairline object-cover"
              />
            )}
            {nodeCoord(selected.properties) && (
              <div className="mb-2.5 h-28 w-full overflow-hidden rounded-lg border border-hairline">
                <MapView incidents={[nodeCoord(selected.properties)!]} />
              </div>
            )}

            {entityInfo(labelOf(selected)) && <p className="mb-2.5 leading-relaxed text-muted">{entityInfo(labelOf(selected))}</p>}
            <dl className="divide-y divide-hairline">
              {Object.entries(selected.properties)
                .filter(([k, v]) => !HIDDEN_PROPS.has(k) && v !== '' && v != null)
                .slice(0, 12)
                .map(([k, v]) => (
                  <div key={k} className="flex items-center justify-between gap-3 py-1.5">
                    <dt className="shrink-0 text-muted">{humanizeKey(k)}</dt>
                    <dd className="truncate rounded-md bg-surface px-1.5 py-0.5 font-mono text-[11px] text-ink">{String(v)}</dd>
                  </div>
                ))}
            </dl>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
