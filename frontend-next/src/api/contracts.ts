/**
 * Suhail backend contracts as served today (backend/operations_api.py, chat/operations/read_model.py,
 * docs/api/case-detail.md). These types describe the wire format; they are never widened to make a
 * screen easier to build. Anything the backend does not serve stays absent in the UI.
 */
export interface ApiPage<T> {
  items: T[];
  filtered_total: number;
  next_cursor: string | null;
  previous_cursor: string | null;
  metadata?: {
    as_of?: string;
    execution_as_of?: string;
    synthetic?: boolean;
    limit?: number;
    buckets?: Record<string, number>;
    filter_choices?: Record<string, string[]>;
  };
}
export type WorkflowState =
  | "OPEN"
  | "INVESTIGATING"
  | "NEEDS_EVIDENCE"
  | "RECOMMENDATION_READY"
  | "AWAITING_APPROVAL"
  | "ACTION_INITIATED"
  | "REJECTED"
  | "HUMAN_REVIEW"
  | "AWAITING_OUTCOME"
  | "ESCALATED"
  | "REOPENED"
  | "RESOLVED";
export interface ApiQueueCase {
  case_id: string;
  shipment_id: string;
  source_case_id?: string | null;
  issue_summary: string;
  summary_source?: "agent_diagnosis" | "monitor";
  diagnosis_available?: boolean;
  city?: string | null;
  category?: string | null;
  cause_codes?: string[];
  rule_signal_codes?: string[];
  symptom_codes?: string[];
  priority: "low" | "medium" | "high" | "unknown";
  workflow_state: WorkflowState;
  operational_status?: string | null;
  opened_at?: string | null;
  as_of?: string | null;
  state_version?: number;
  synthetic?: boolean;
}
export interface ApiAuditEvent {
  id: string;
  timestamp: string;
  scenario_time?: string | null;
  shipment_id: string;
  case_id?: string | null;
  event_type: string;
  actor: string;
  decision?: string | null;
  result?: string | null;
  from_state?: string | null;
  to_state?: string | null;
  model?: string | null;
  stage?: string | null;
  stage_status?: string | null;
  sequence?: number | null;
  synthetic?: boolean;
}
export interface ApiGeoPoint {
  lat: number;
  lng: number;
  entity_id?: string;
  source?: string;
}
export interface ApiExploreItem {
  shipment_id: string;
  city?: string | null;
  status?: string;
  origin_city?: string | null;
  destination_city?: string | null;
  flow_type?: string | null;
  origin?: ApiGeoPoint | null;
  destination?: ApiGeoPoint | null;
  operational_status?: string | null;
  cause_codes?: string[];
  diagnosis_available?: boolean;
  symptom_codes?: string[];
  priority?: string;
  case_id?: string | null;
  workflow_state?: WorkflowState | null;
  as_of?: string;
}
export interface ApiEvidenceNode {
  id: string;
  kind: string;
  properties: Record<string, unknown>;
  after_investigation?: boolean;
}
export interface ApiEvidenceEdge {
  id: string;
  kind: string;
  start: string;
  end: string;
  properties?: Record<string, unknown>;
}
export interface ApiLayerPoint {
  lat: number;
  lng: number;
  entity_id?: string;
  evidence_id?: string;
  occurred_at?: string | null;
  source?: string;
  vehicle_id?: string;
  package_id?: string;
  disposition?: string;
}
export interface ApiRouteSegment {
  segment_id: string;
  sequence?: number;
  points: ApiLayerPoint[];
}
export type PipelineStage =
  | "extract"
  | "retrieve"
  | "classify"
  | "retrieve_context"
  | "recommend"
  | "review"
  | "writeback"
  | "escalate";
export interface ApiPipelineEvent {
  sequence: number;
  stage: PipelineStage | string;
  status: string;
  iteration?: number;
  recorded_at?: string;
  evidence_as_of?: string;
  output?: {
    evidence_ids?: string[];
    edge_ids?: string[];
    nodes?: number;
    relationships?: number;
    verified_precedents?: number;
    verdict?: string;
    feedback?: string;
    reason_code?: string;
    workflow_state?: string;
    diagnoses?: { code?: string; summary?: string; summary_en?: string }[];
    proposal?: { action?: string; action_en?: string } | null;
  };
}
export interface ApiPipelineState {
  workflow_state: WorkflowState;
  state_version: number;
  run_id: string | null;
  previous_run_id?: string | null;
  status: string;
  events: ApiPipelineEvent[];
}
export interface ApiDiagnosisHypothesis {
  cause: string;
  status: "supported" | "refuted" | "uncertain";
  assessment?: string | null;
  supporting_evidence_ids?: string[];
  contradicting_evidence_ids?: string[];
}
export interface ApiDiagnosis {
  available: boolean;
  reason: string | null;
  source: "agent_investigation" | null;
  run_id: string | null;
  as_of: string | null;
  investigated_at: string | null;
  primary_cause: string | null;
  confidence: "low" | "medium" | "high" | null;
  summary: string | null;
  hypotheses: ApiDiagnosisHypothesis[];
  missing_evidence: string[];
  requires_physical_check: boolean | null;
  tool_calls: number;
  snapshot_superseded: boolean;
  review?: {
    verdict: string | null;
    model_verdict: string | null;
    reason_code: string;
    accepted: boolean;
  } | null;
  unaccepted_investigation?: {
    primary_cause: string | null;
    summary: string | null;
    confidence: string | null;
  } | null;
}
export interface ApiRecommendation {
  action?: string;
  action_en?: string;
  action_ar?: string;
  summary_en?: string;
  summary_ar?: string;
  evidence_ids?: string[];
  action_type?: string | null;
  risk_class?: string | null;
  approvable?: boolean;
  approval_rule?: string;
  approval_reason?: string;
  approval_context_stale?: boolean;
}
export interface ApiExecution {
  entity_id?: string;
  receipt_ref?: string;
  action_type?: string;
  occurred_at?: string;
  recorded_at?: string;
  status?: string;
  authority?: string;
  closure?: string;
  current_cycle?: boolean;
}
export interface ApiOutcome {
  outcome_id?: string;
  entity_id?: string;
  invalidated?: boolean;
  verification_status?: string;
  success?: boolean | null;
  outcome_type?: string;
  evidence_ids?: string[];
  reason?: string;
  verified_at?: string;
  recorded_at?: string;
  exception_cleared?: boolean | null;
  remaining_symptoms?: string[];
  current_cycle?: boolean;
}
export interface ApiDecisionRecord {
  entity_id?: string;
  decision?: string;
  occurred_at?: string;
  actor_id?: string;
}
export interface ApiCaseDetail {
  case_id: string;
  shipment_id: string;
  workflow_state: WorkflowState;
  state_version: number;
  priority?: string;
  operational_status?: string | null;
  as_of?: string;
  investigated_at?: string | null;
  last_run_id?: string | null;
  synthetic?: boolean;
  run?: {
    entity_id?: string;
    recorded_at?: string;
    mode?: string;
    status?: string;
  } | null;
  evidence: { nodes: ApiEvidenceNode[]; edges: ApiEvidenceEdge[] };
  ledger_graph?: { nodes: ApiEvidenceNode[]; edges: ApiEvidenceEdge[] };
  diagnosis?: ApiDiagnosis;
  pipeline?: {
    events: ApiPipelineEvent[];
    status: string;
    source?: string;
    investigation_as_of?: string | null;
    evidence_after_investigation?: number;
  };
  recommendation?: ApiRecommendation | null;
  review?: {
    verdict?: string;
    reason_code?: string;
    feedback?: string;
    summary_en?: string;
  } | null;
  outcome?: ApiOutcome | null;
  decisions?: ApiDecisionRecord[];
  executions?: ApiExecution[];
  route_layers?: {
    layers: {
      expected_route?: (ApiLayerPoint | ApiRouteSegment)[];
      actual_route?: ApiLayerPoint[];
      vehicle_path?: ApiLayerPoint[];
      custody_points?: ApiLayerPoint[];
      hub_stops?: ApiLayerPoint[];
      delivery_attempts?: ApiLayerPoint[];
      traffic?: ApiLayerPoint[];
    };
    truncated?: Record<string, boolean>;
  };
}
export interface ApiWorkerStatus {
  synthetic: boolean;
  as_of: string;
  database?: string;
  worker: {
    state: string;
    concurrency: number;
    processed_count?: number;
    active_case_id?: string | null;
    active_shipment_id?: string | null;
    last_case_id?: string | null;
    last_workflow_state?: string | null;
  };
  session?: {
    monitor_pending?: number;
    monitor_checked?: number;
    monitor_opened?: number;
  };
  simulator?: { state: string; speed: number };
}
export interface ApiSession {
  token: string;
  mode: string;
  synthetic: boolean;
  actor_id: string;
  role: string;
  scope: string[];
  production_authority: boolean;
}
export interface ApiSchema {
  nodes: { id: string; labels: string[]; caption: string }[];
  relationships: { id: string; type: string; from: string; to: string }[];
  synthetic: boolean;
}
export interface ApiDecisionResult {
  case_id: string;
  workflow_state: WorkflowState;
  state_version: number;
  decision_id?: string;
  execution_id?: string | null;
  idempotent?: boolean;
}
