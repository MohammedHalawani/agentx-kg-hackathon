import type { CaseWorkflowState } from './operations'
import type { SubGraph } from '@/types/contract'

export interface EvidenceNode { id: string; kind: string; properties: Record<string, unknown> }
export interface EvidenceEdge { id: string; kind: string; start: string; end: string; properties: Record<string, unknown> }
export interface LayerPoint { lat: number; lng: number; entity_id?: string; occurred_at?: string; source?: string; vehicle_id?: string }
export interface RouteSegment { segment_id: string; sequence?: number; points: LayerPoint[] }
export type RouteLayers = Partial<Record<Exclude<RouteLayerKey, 'expected_route'>, LayerPoint[]>> & { expected_route?: (LayerPoint | RouteSegment)[] }
export type RouteLayerKey = 'expected_route' | 'actual_route' | 'vehicle_path' | 'custody_points' | 'hub_stops' | 'delivery_attempts'
export interface ShipmentDetail {
  shipment_id: string; case_id?: string; workflow_state?: CaseWorkflowState; state_version?: number; version?: number; as_of?: string; synthetic?: boolean
  evidence: { nodes: EvidenceNode[]; edges: EvidenceEdge[] }
  recommendation_id?: string | null
  recommendation?: { action?: string; action_en?: string; action_ar?: string; summary_en?: string; summary_ar?: string; evidence_ids?: string[] } | null
  review?: { verdict?: string; feedback?: string; summary_en?: string; summary_ar?: string } | null
  outcome?: { outcome_id?: string; id?: string; invalidated?: boolean; verification_status?: string; success?: boolean | null; outcome_type?: string; evidence_ids?: string[] } | null
  decisions?: { decision?: string; occurred_at?: string }[]
  executions?: { receipt_ref?: string; action_type?: string; occurred_at?: string }[]
  precedents?: { shipment_id: string; action: string; success: boolean | null; verified_at?: string; evidence_ids?: string[]; synthetic?: boolean }[]
  reasoning?: { precedents?: ShipmentDetail['precedents']; workflow_state?: CaseWorkflowState | 'NO_EXCEPTION'; assessment?: { operational_status?: string; needs_attention?: boolean; cause_codes?: string[] }; recommendations?: { action?: string; action_en?: string; action_ar?: string; rationale?: string; explanation_en?: string; explanation_ar?: string }[]; diagnoses?: { code?: string; category?: string; summary?: string; summary_en?: string; summary_ar?: string; evidence_ids?: string[]; explanation_en?: string; explanation_ar?: string }[]; warnings?: string[] }
  route_layers?: { layers: RouteLayers; truncated?: Record<string, boolean> }
}
export function evidenceGraph(detail: ShipmentDetail): SubGraph {
  return { nodes: detail.evidence.nodes.map(n => ({ id: n.id, labels: [n.kind], caption: String(n.properties.shipment_id ?? n.properties.name ?? n.id), properties: n.properties })), relationships: detail.evidence.edges.map(e => ({ id: e.id, type: e.kind, from: e.start, to: e.end })) }
}
