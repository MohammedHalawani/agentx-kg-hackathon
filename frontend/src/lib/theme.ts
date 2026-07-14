// Resolve a CSS custom property to a concrete color string. Leaflet and NVL render to
// canvas/WebGL and need real colors, not `var()` references — so colors stay in the token
// layer (index.css) and the renderers read the resolved value here.

export function cssVar(name: string, fallback = '#888888'): string {
  if (typeof document === 'undefined') return fallback
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return v || fallback
}

const PALETTE = ['--graph-1', '--graph-2', '--graph-3', '--graph-4', '--graph-5', '--graph-6', '--graph-7', '--graph-8']

// Strict per-label colours for the core entity types (exact hexes, defined in index.css). A label
// listed here is ALWAYS this colour, in the graph and the legend alike.
const SEMANTIC: Record<string, string> = {
  Observation: '--node-observation',
  Category: '--node-category',
  Incident: '--node-incident',
  Municipality: '--node-municipality',
  Source: '--node-source',
  DataEntry: '--node-data-entry',
  Track: '--node-track',
  TrackObjective: '--node-track-objective',
  Person: '--node-person',
  SteerCoSession: '--node-steerco-session',
}

// Semantic colour first; any other label falls back to the shared palette in appearance order
// (the fallback counter only advances for unlisted labels, so they stay distinct from each other).
export function buildLabelColors(labels: string[]): Record<string, string> {
  const out: Record<string, string> = {}
  let fallback = 0
  for (const label of labels) {
    out[label] = cssVar(SEMANTIC[label] ?? PALETTE[fallback++ % PALETTE.length])
  }
  return out
}
