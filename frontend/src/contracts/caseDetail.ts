import type { CaseWorkflowState } from './operations'
import type { SubGraph } from '@/types/contract'

export interface EvidenceNode { id: string; kind: string; properties: Record<string, unknown> }
export interface EvidenceEdge { id: string; kind: string; start: string; end: string; properties: Record<string, unknown> }
export interface LayerPoint { lat: number; lng: number; entity_id?: string; evidence_id?:string; occurred_at?: string; source?: string; vehicle_id?: string; package_id?:string }
export interface RouteSegment { segment_id: string; sequence?: number; points: LayerPoint[] }
export type RouteLayers = Partial<Record<Exclude<RouteLayerKey, 'expected_route'>, LayerPoint[]>> & { expected_route?: (LayerPoint | RouteSegment)[] }
export type RouteLayerKey = 'expected_route' | 'actual_route' | 'vehicle_path' | 'custody_points' | 'hub_stops' | 'delivery_attempts' | 'traffic'
export type PipelineStage = 'extract' | 'retrieve' | 'classify' | 'retrieve_context' | 'recommend' | 'review' | 'writeback' | 'escalate'
/** Recorded graph stages plus the operational outcome gate, which is not a LangGraph node. */
export type InspectStage = PipelineStage | 'outcome'
export interface PipelineEvent { sequence: number; stage: PipelineStage; status: string; iteration: number; recorded_at: string; evidence_as_of: string; output: { evidence_ids?: string[]; edge_ids?: string[]; nodes?: number; relationships?: number; categories?: Record<string,number>; verified_precedents?: number; verdict?: string; feedback?: string; workflow_state?: string; diagnoses?: NonNullable<ShipmentDetail['reasoning']>['diagnoses']; proposal?: ShipmentDetail['recommendation'] } }
export interface Pipeline { topology: { nodes: PipelineStage[]; edges: { source:string; target:string; conditional:boolean }[]; engine:string; mode:string; retry_limit:number }; events: PipelineEvent[]; source: string; status: string; investigation_as_of?: string | null; evidence_after_investigation?: number }
export interface ShipmentDetail {
  shipment_id: string; case_id?: string; workflow_state?: CaseWorkflowState; state_version?: number; version?: number; as_of?: string; investigated_at?: string; synthetic?: boolean; priority?: string; operational_status?: string
  run?: { recorded_at?: string; mode?: string; result?: { trace?: { iteration: number; mode: string; review: { verdict: string; feedback?: string }; proposal?: { action?: string; action_en?: string; action_ar?: string } }[] } } | null
  evidence: { nodes: EvidenceNode[]; edges: EvidenceEdge[] }
  pipeline?: Pipeline
  ledger_graph?: { nodes: EvidenceNode[]; edges: EvidenceEdge[] }
  recommendation_id?: string | null
  recommendation?: { action?: string; action_en?: string; action_ar?: string; summary_en?: string; summary_ar?: string; evidence_ids?: string[]; action_type?: string; risk_class?: string; approvable?: boolean; approval_rule?: string } | null
  review?: { verdict?: string; feedback?: string; summary_en?: string; summary_ar?: string; model_verdict?: string | null; degraded?: boolean; mode?: string } | null
  outcome?: { outcome_id?: string; id?: string; invalidated?: boolean; verification_status?: string; success?: boolean | null; outcome_type?: string; evidence_ids?: string[]; rule_id?: string; reason?: string; verifier_id?: string; exception_cleared?: boolean | null; remaining_symptoms?: string[] } | null
  decisions?: { decision?: string; occurred_at?: string }[]
  executions?: { receipt_ref?: string; action_type?: string; occurred_at?: string; status?: string; authority?: string; adapter_result_json?: string; deadline_at?: string; closure?: string }[]
  precedents?: { shipment_id: string; action: string; success: boolean | null; verified_at?: string; evidence_ids?: string[]; synthetic?: boolean }[]
  reasoning?: { as_of?: string; precedents?: ShipmentDetail['precedents']; workflow_state?: CaseWorkflowState | 'NO_EXCEPTION'; assessment?: { operational_status?: string; needs_attention?: boolean; cause_codes?: string[]; expected_vs_actual?: { milestone_id?: string; latest_at?: string; actual_at?: string; late?: boolean; missing_due?: boolean }[] }; recommendations?: { action?: string; action_en?: string; action_ar?: string; rationale?: string; explanation_en?: string; explanation_ar?: string }[]; diagnoses?: { code?: string; category?: string; summary?: string; summary_en?: string; summary_ar?: string; evidence_ids?: string[]; certainty?: string; requires_human_review?: boolean; explanation_en?: string; explanation_ar?: string }[]; warnings?: string[] }
  route_layers?: { layers: RouteLayers; truncated?: Record<string, boolean> }
}
export function evidenceGraph(detail: Pick<ShipmentDetail, 'evidence' | 'ledger_graph'>): SubGraph {
  return { nodes: [...detail.evidence.nodes,...(detail.ledger_graph?.nodes ?? [])].map(n => ({ id: n.id, labels: [n.kind], caption: String(n.properties.name ?? n.id), properties: n.properties })), relationships: [...detail.evidence.edges,...(detail.ledger_graph?.edges ?? [])].map(e => ({ id: e.id, type: e.kind, from: e.start, to: e.end })) }
}
