import type { CaseWorkflowState } from './operations'
import type { SubGraph } from '@/types/contract'

/**
 * Case detail contract served by GET /cases/{case_id} (and, without the ledger fields, by
 * GET /shipments/{shipment_id}/context). See docs/api/case-detail.md.
 *
 * Two fields are easy to confuse and must stay separate:
 * - `diagnosis` is the current run's agent investigation that the independent reviewer accepted (primary cause,
 *   hypotheses, confidence, run id, as-of, review), or explicitly absent with a reason. It is never filled from rule
 *   output. An investigation the reviewer did not accept is absent (`review_not_accepted`) and its findings are served
 *   apart in `unaccepted_investigation`, labelled, never as what happened.
 * - `rule_signals` are deterministic rule checks over the evidence visible at their own `as_of` (the live
 *   clock). They are monitoring/fact-check signals, labelled `is_diagnosis: false`, never "what happened".
 */
export interface EvidenceNode { id: string; kind: string; properties: Record<string, unknown> }
export interface EvidenceEdge { id: string; kind: string; start: string; end: string; properties: Record<string, unknown> }
export interface LayerPoint { lat: number; lng: number; entity_id?: string; evidence_id?:string; occurred_at?: string; source?: string; vehicle_id?: string; package_id?:string }
export interface RouteSegment { segment_id: string; sequence?: number; points: LayerPoint[] }
export type RouteLayers = Partial<Record<Exclude<RouteLayerKey, 'expected_route'>, LayerPoint[]>> & { expected_route?: (LayerPoint | RouteSegment)[] }
export type RouteLayerKey = 'expected_route' | 'actual_route' | 'vehicle_path' | 'custody_points' | 'hub_stops' | 'delivery_attempts' | 'traffic'
export type PipelineStage = 'extract' | 'retrieve' | 'classify' | 'retrieve_context' | 'recommend' | 'review' | 'writeback' | 'escalate'
/** Recorded graph stages plus the operational outcome gate, which is not a LangGraph node. */
export type InspectStage = PipelineStage | 'outcome'

/** A diagnosis recorded by a pipeline stage (agent hypotheses for agent runs; rule output for rules-only runs). */
export interface StageDiagnosis { code?: string; status?: string; summary?: string; summary_en?: string; summary_ar?: string | null; evidence_ids?: string[]; certainty?: string; requires_human_review?: boolean }
export interface PipelineEvent { sequence: number; stage: PipelineStage; status: string; iteration: number; recorded_at: string; evidence_as_of: string; output: { evidence_ids?: string[]; edge_ids?: string[]; nodes?: number; relationships?: number; categories?: Record<string,number>; verified_precedents?: number; verdict?: string; feedback?: string; reason_code?: string; summary_ar?: string; workflow_state?: string; diagnoses?: StageDiagnosis[]; proposal?: ShipmentDetail['recommendation'] } }
export interface Pipeline { topology: { nodes: PipelineStage[]; edges: { source:string; target:string; conditional:boolean }[]; engine:string; mode:string; retry_limit:number }; events: PipelineEvent[]; source: string; status: string; investigation_as_of?: string | null; evidence_after_investigation?: number }

export type DiagnosisAbsentReason = 'not_a_case' | 'no_operations_ledger' | 'not_investigated' | 'investigation_in_progress' | 'reinvestigation_pending' | 'investigation_incomplete' | 'no_agent_investigation' | 'investigation_unavailable' | 'review_not_accepted'
export interface DiagnosisHypothesis { cause: string; status: 'supported' | 'refuted' | 'uncertain'; assessment?: string | null; supporting_evidence_ids?: string[]; contradicting_evidence_ids?: string[] }
/** What the independent reviewer decided about the investigation (its final round). */
export interface DiagnosisReview { verdict: string | null; model_verdict: string | null; reason_code: string; accepted: boolean }
/** An investigation the independent reviewer did not accept: the investigator's findings, labelled, never "what happened". */
export interface UnacceptedInvestigation {
  accepted: false
  review: DiagnosisReview | null
  run_id: string | null
  as_of: string | null
  investigated_at: string | null
  primary_cause: string | null
  confidence: 'low' | 'medium' | 'high' | null
  summary: string | null
  hypotheses: DiagnosisHypothesis[]
  missing_evidence: string[]
  requires_physical_check: boolean | null
  tool_calls: number
  snapshot_superseded: boolean
  language: 'en' | null
}
/** The current run's accepted agent investigation. `available: false` carries `reason` and no cause. */
export interface Diagnosis {
  available: boolean
  reason: DiagnosisAbsentReason | null
  source: 'agent_investigation' | null
  /** The run this diagnosis came from (null when absent, except while a run is in progress). */
  run_id: string | null
  /** The earlier run that a queued re-investigation superseded. */
  superseded_run_id?: string | null
  /** The investigation's evidence snapshot time (not the live clock). */
  as_of: string | null
  investigated_at: string | null
  primary_cause: string | null
  confidence: 'low' | 'medium' | 'high' | null
  /** The investigator's own text, untranslated (`language`). */
  summary: string | null
  hypotheses: DiagnosisHypothesis[]
  missing_evidence: string[]
  requires_physical_check: boolean | null
  tool_calls: number
  /** Evidence kept arriving during the investigation; the case went to a person. */
  snapshot_superseded: boolean
  language: 'en' | null
  /** The reviewer's decision on the current run (accepted when the diagnosis is available); null when no run was reviewed. */
  review?: DiagnosisReview | null
  /** With `review_not_accepted` only: the findings the reviewer did not accept. */
  unaccepted_investigation?: UnacceptedInvestigation | null
}
export interface ExpectedVsActual { milestone_id?: string; location_id?: string; latest_at?: string; actual_at?: string; late?: boolean; missing_due?: boolean }
export interface RuleSignal { code: string; summary_en?: string; summary_ar?: string; evidence_ids?: string[]; certainty?: string; requires_human_review?: boolean }
export interface Precedent { shipment_id: string; action: string; success: boolean | null; verified_at?: string; evidence_ids?: string[]; synthetic?: boolean }
/** Deterministic rule checks at `as_of` (the live clock). Never a diagnosis. */
export interface RuleSignals {
  kind: 'rule_signals'
  is_diagnosis: false
  source: 'deterministic_evidence_rules'
  as_of: string
  signals: RuleSignal[]
  expected_vs_actual: ExpectedVsActual[]
  operational_labels?: string[]
  journey_forecast?: Record<string, unknown>
  /** Verified precedents retrieved for the rule signal codes. */
  precedents?: Precedent[]
  note?: string
}
export interface AuthorityDecision { rule_id?: string; risk_class?: string; reason?: string; action_type?: string | null; closure?: string }
type RunRecord = { entity_id?: string; recorded_at?: string; mode?: string; status?: string; result?: { authority?: AuthorityDecision | null; trace?: { iteration: number; mode: string; review: { verdict: string; feedback?: string; reason_code?: string; summary_ar?: string }; proposal?: { action?: string; action_en?: string; action_ar?: string } }[] } }
export interface ShipmentDetail {
  shipment_id: string; case_id?: string; workflow_state?: CaseWorkflowState; state_version?: number; version?: number; as_of?: string; investigated_at?: string; synthetic?: boolean; priority?: string; operational_status?: string
  last_run_id?: string | null
  /** The current investigation run; null while a new one is queued (the earlier run is then `previous_run`). */
  run?: RunRecord | null
  /** While a re-investigation is queued: the earlier run, superseded. Not the current investigation, review or pipeline. */
  previous_run?: (RunRecord & { superseded: true }) | null
  evidence: { nodes: EvidenceNode[]; edges: EvidenceEdge[] }
  diagnosis?: Diagnosis
  rule_signals?: RuleSignals
  pipeline?: Pipeline
  ledger_graph?: { nodes: EvidenceNode[]; edges: EvidenceEdge[] }
  recommendation_id?: string | null
  recommendation?: { action?: string; action_en?: string; action_ar?: string; summary_en?: string; summary_ar?: string; evidence_ids?: string[]; action_type?: string; risk_class?: string; approvable?: boolean; approval_rule?: string; approval_reason?: string; approval_context_stale?: boolean } | null
  review?: { verdict?: string; reason_code?: string; feedback?: string; summary_en?: string; summary_ar?: string; model_verdict?: string | null; degraded?: boolean; mode?: string } | null
  /** The latest outcome. `current_cycle` is false when it belongs to an earlier investigation cycle (history only). */
  outcome?: { outcome_id?: string; id?: string; invalidated?: boolean; verification_status?: string; success?: boolean | null; outcome_type?: string; evidence_ids?: string[]; rule_id?: string; reason?: string; verifier_id?: string; exception_cleared?: boolean | null; remaining_symptoms?: string[]; run_id?: string | null; current_cycle?: boolean } | null
  decisions?: { decision?: string; occurred_at?: string }[]
  executions?: { receipt_ref?: string; action_type?: string; occurred_at?: string; status?: string; authority?: string; adapter_result_json?: string; deadline_at?: string; closure?: string; permission_rule?: string; decided_risk?: string; recommendation_id?: string | null; run_id?: string | null; current_cycle?: boolean }[]
  precedents?: Precedent[]
  route_layers?: { layers: RouteLayers; truncated?: Record<string, boolean> }
}
export function evidenceGraph(detail: Pick<ShipmentDetail, 'evidence' | 'ledger_graph'>): SubGraph {
  return { nodes: [...detail.evidence.nodes,...(detail.ledger_graph?.nodes ?? [])].map(n => ({ id: n.id, labels: [n.kind], caption: String(n.properties.name ?? n.id), properties: n.properties })), relationships: [...detail.evidence.edges,...(detail.ledger_graph?.edges ?? [])].map(e => ({ id: e.id, type: e.kind, from: e.start, to: e.end })) }
}
