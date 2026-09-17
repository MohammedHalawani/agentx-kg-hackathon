import type { GraphNode, GraphRel } from './contract'

// Mirrors the payloads chat/llm/pipeline/graph.py's stream_complaint() emits over SSE.
// The vocabulary (lane, arabic, is_agent) comes from that file's STAGE_META, which in turn
// comes from the architecture diagram - so a stage renamed there flows through to the UI.

export interface Precedent {
  failure_id: string
  category: string
  action: string
  success: boolean
  score: number
  case_summary?: string
  resolution_id?: string
  city?: string
  courier?: string
}

export interface StageDetail {
  // extract
  shipment_id?: string
  tracking_id?: string
  city?: string
  district?: string
  courier?: string
  category_hint?: string
  // retrieve
  similar_cases?: number
  live_failure_id?: string | null
  precedent?: Precedent[]
  // classify
  category?: string
  confidence?: number
  priority?: 'low' | 'medium' | 'high'
  rationale?: string
  // recommend
  action?: string
  grounded_in?: string[]
  candidates?: { action: string; success_rate?: number; used?: number }[]
  // review
  verdict?: 'accept' | 'reject'
  score?: number
  reason?: string
  checked_against?: string[]
  // writeback
  resolution_id?: string | null
}

export interface Stage {
  stage: 'extract' | 'retrieve' | 'classify' | 'recommend' | 'review' | 'writeback' | 'escalate'
  label: string
  lane: string
  arabic: string
  is_agent: boolean
  loop: number
  verdict?: 'accept' | 'reject'
  detail?: StageDetail
}

export interface RoutePoint {
  lat: number
  lng: number
  kind: 'warehouse' | 'delivery' | 'home'
  city?: string
  district?: string
  full?: string
  // Warehouses are placed at a city centroid: the graph holds no facility coordinates.
  approximate?: boolean
}

// The shipment's own evidence. Streamed as its own event as soon as retrieval resolves the
// shipment, roughly a second in, rather than waiting for the run to finish.
export interface CaseFile {
  graph: { nodes: GraphNode[]; relationships: GraphRel[] } | null
  route: { origin: RoutePoint | null; points: RoutePoint[] } | null
}

export interface FinalResult {

  disposition: 'execute' | 'escalate' | null
  resolution_id: string | null
  loops: number
  classification?: StageDetail
  recommendation?: StageDetail
  review?: StageDetail
}

export interface CaseRow {
  failure_id: string
  category: string
  description?: string
  city?: string
  district?: string
  courier?: string
  shipment_id?: string
}

export interface EscalatedCase {
  escalation_id: string
  complaint: string
  created_at: string
  status: string
  team: string
  reason: string
  category: string | null
  priority: string | null
  shipment_id: string | null
  loops: number
  attempted_actions: string[]
  failure_id: string | null
}

export interface CasesOverview {
  escalations: EscalatedCase[]
  escalations_by_team: { team: string; cases: number }[]
  coverage: { resolved: number; unresolved: number; total: number }
  by_category: { category: string; cases: number; succeeded: number; success_rate: number }[]
  by_action: { action: string; used: number; succeeded: number; success_rate: number }[]
  writebacks: { by_agent: number; seeded: number; pending: number; total: number }
  queue: CaseRow[]
}
