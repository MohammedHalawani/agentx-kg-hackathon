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
  /** Seconds since the investigation graph started, on the backend's clock. */
  elapsed_seconds?: number;
  output?: {
    /** Which component produced the stage: e.g. evidence_rules, deterministic_guard, or an agent. */
    agent?: string | null;
    /** "tool_call": one evidence query of the investigator, as it happened (a classify RUNNING event). */
    kind?: string;
    /** With kind "invalid_output_repair": which role is being asked again, and the backend's message. */
    role?: string;
    attempt?: number;
    message?: string;
    tool?: string;
    purpose?: string;
    round?: number;
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
    hypotheses?: ApiDiagnosisHypothesis[];
    missing_evidence?: string[];
    requires_physical_check?: boolean | null;
    tool_calls?: number;
    snapshot_superseded?: boolean;
    forced_final_turn?: boolean;
  } | null;
  /** True when the conclusion was reached on the investigator's final allowed turn. */
  forced_final_turn?: boolean;
}
export interface ApiRecommendation {
  action?: string;
  action_en?: string;
  action_ar?: string;
  summary_en?: string;
  summary_ar?: string;
  authority_reason?: string;
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
  /** When the request was delivered, and until when the verifier waits for evidence. */
  executed_at?: string;
  deadline_at?: string;
  /** When the simulator has scheduled an answer (never what the answer is). May be absent. */
  expected_response_at?: string | null;
  expected_result?: string;
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
  /** "evidence_verifier" or a person's finding. */
  source?: string;
  current_cycle?: boolean;
}
export interface ApiDecisionRecord {
  entity_id?: string;
  decision?: string;
  occurred_at?: string;
  actor_id?: string;
}
/** One stored message of a run's narration (docs/api/narration.md). */
export interface ApiNarrationEvent {
  id: string;
  run_id?: string;
  sequence: number;
  stage: string;
  phase?: string;
  kind: "canopus_summary" | "agent_output" | "system_event";
  iteration?: number;
  title_en?: string | null;
  title_ar?: string | null;
  text_en?: string | null;
  text_ar?: string | null;
  evidence_ids?: string[];
  graph_node_ids?: string[];
  occurred_at?: string | null;
  scenario_time?: string | null;
  created_at?: string | null;
  model?: string | null;
  grounded?: boolean | null;
  fallback?: boolean;
  outcome_state?: string | null;
}
export interface ApiNarration {
  run_id?: string | null;
  status?: "idle" | "narrating" | "complete" | string;
  model_calls?: number;
  events?: ApiNarrationEvent[];
}
/** What an unresolved case needs next, computed by the backend from recorded fields only. */
export interface ApiNextStep {
  code: string;
  actor: "none" | "system" | "operator" | string;
  text_en?: string;
  text_ar?: string;
  resolved?: boolean;
  blocked_by?: {
    rule_id?: string | null;
    reason?: string | null;
    risk_class?: string | null;
    review_verdict?: string | null;
    review_feedback?: string | null;
    approval_rule?: string | null;
    approval_reason?: string | null;
  } | null;
  missing_evidence?: string[];
  attempted?: {
    action_type?: string;
    authority?: string;
    status?: string;
    verification_status?: string | null;
    success?: boolean | null;
    outcome_type?: string | null;
    exception_cleared?: boolean | null;
    reason?: string | null;
  }[];
}
export interface ApiCaseDetail {
  next_step?: ApiNextStep | null;
  narration?: ApiNarration | null;
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
    /** The run record (docs/api/investigation-run.md). No truth, gold or chain-of-thought is in it. */
    result?: ApiRunResult | null;
  } | null;
  /** While a re-investigation is queued: the earlier run, superseded. Never the current run. */
  previous_run?: { entity_id?: string; recorded_at?: string; superseded?: boolean } | null;
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
  /** Deterministic rule checks at their own as-of time. Never a diagnosis. */
  rule_signals?: {
    kind: "rule_signals";
    is_diagnosis: false;
    as_of: string;
    signals: {
      code: string;
      summary_en?: string;
      evidence_ids?: string[];
      certainty?: string;
    }[];
  };
  recommendation?: ApiRecommendation | null;
  review?: {
    verdict?: string;
    model_verdict?: string | null;
    mode?: string;
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
export interface ApiToolCall {
  round?: number;
  tool: string;
  args?: Record<string, unknown>;
  purpose?: string;
  evidence_ids?: string[];
  computed_ids?: string[];
  failure?: string | null;
}
export interface ApiRunResult {
  mode?: string;
  /** Where the run's time went (measurement only; present once the run has finished). */
  latency?: {
    total_seconds?: number;
    first_conclusion_seconds?: number;
    first_review_seconds?: number;
    final_seconds?: number;
    stages?: Record<string, number>;
    model?: {
      calls?: number;
      seconds?: number;
      /** One entry per model call; invalid_kind says why a reply was rejected. */
      turns?: { role?: string; invalid_kind?: string | null }[];
    };
    tools?: { calls?: number; seconds?: number };
  } | null;
  investigation?: {
    next_evidence_step?: string | null;
    recommended_action?: string | null;
    steps?: ApiToolCall[];
  } | null;
  authority?: {
    risk_class?: string;
    reason?: string;
    rule_id?: string;
    action_type?: string | null;
    closure?: string;
  } | null;
  degraded?: { role?: string; error?: string; kind?: string }[];
  investigation_log?: {
    snapshot_as_of?: string | null;
    model_calls_used?: number;
    model_call_cap?: number;
    model_calls_by_role?: Record<string, number>;
    cap_reached?: boolean;
    disabled_tools?: string[];
    rounds?: {
      round: number;
      tool_calls?: ApiToolCall[];
      citation_validity?: { cited?: number; valid?: number; all_valid?: boolean } | null;
      fact_checks?: { check: string; passed: boolean; detail?: string }[];
      review?: {
        verdict?: string;
        model_verdict?: string | null;
        reason_code?: string;
        feedback?: string;
        unsupported_claims?: string[];
        unaddressed_contradictions?: string[];
        alternatives_tested?: boolean | null;
        mode?: string;
        degraded?: boolean;
      } | null;
    }[];
    evidence_index?: Record<string, { kind?: string; scope?: string }>;
  } | null;
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
    /** A curated session: the monitor opens cases only for a listed set of shipments. */
    demo_shipments?: { enabled?: boolean; count?: number };
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
