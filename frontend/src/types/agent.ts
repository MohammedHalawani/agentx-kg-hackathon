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

export interface FinalResult {
  // Only on escalation, and only when the complaint resolved to a real shipment: that
  // shipment's neighbourhood, for the human who inherits the case.
  handover?: { nodes: GraphNode[]; relationships: GraphRel[] } | null
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

export interface CasesOverview {
  coverage: { resolved: number; unresolved: number; total: number }
  by_category: { category: string; cases: number; succeeded: number; success_rate: number }[]
  by_action: { action: string; used: number; succeeded: number; success_rate: number }[]
  writebacks: { by_agent: number; seeded: number; total: number }
  queue: CaseRow[]
}
