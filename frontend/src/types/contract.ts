// The presentation-free artifact contract the backend emits, mirrored 1:1. Renderers
// dispatch on `tool`; unknown fields are ignored, so the contract can grow without breaking.

export interface GraphNode {
  id: string
  labels: string[]
  caption: string
  properties: Record<string, unknown>
}

export interface GraphRel {
  id: string
  type: string
  from: string
  to: string
}

export interface SubGraph {
  nodes: GraphNode[]
  relationships: GraphRel[]
}

// A mappable point: a deduped pollution Incident (no real photo) or a real field-visit
// TrackStatus (DataEntry), which can carry one or more real photos. One shape, one MapView -
// renderers just show whichever fields are present.
export interface Incident {
  key?: number | string
  lat: number
  lon: number
  categories?: string[]
  frames?: number
  trip_id?: string
  first_seen?: string
  recurring?: boolean
  image?: string
  // track-status fields (real field visits with real photos)
  images?: string[]
  track?: string
  status?: string
  status_norm?: string
  entry_action?: string
  notes?: string
  date?: string
  [k: string]: unknown
}

export interface Timing {
  total_ms?: number
  agent_llm_ms?: number
  cypher_gen_ms?: number
  db_ms?: number
  llm_tokens?: number
}

export interface TraceStep {
  tool: string
  args: Record<string, unknown>
}

export interface Artifact {
  tool: string | null
  rows?: Record<string, unknown>[] | null
  incidents?: Incident[]
  graph?: SubGraph | null
  cypher?: string | null
  repairs?: number | null
  trace?: string | null // JSON string of TraceStep[]
  confidence?: number | null
  reason?: string | null
  timing?: Timing | null
}

// Discovery chips from GET /samples, grouped by dataset
export interface SampleGroup {
  label: string
  questions: string[]
}

// A live agent step (a tool call) surfaced while the answer is being produced
export interface Step {
  tool: string
  label: string
  detail?: string
}
