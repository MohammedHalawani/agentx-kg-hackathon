import type { ApiBrief } from "@/api/contracts";
export type CaseStatus =
  | "queued"
  | "investigating"
  | "human_review"
  | "needs_evidence"
  | "executing"
  | "verifying"
  | "escalated"
  | "resolved";
export type Scenario =
  | "barcode"
  | "weight"
  | "address"
  | "custody"
  | "contractor"
  | "delivery"
  | "failed"
  | "normal";
/** "unknown": the backend has not assigned a priority. Lab fixtures never use it. */
export type Priority = "high" | "medium" | "low" | "unknown";
export interface Shipment {
  id: string;
  packageId: string;
  origin: string;
  destination: string;
  customer: string;
  service: string;
  /** Null when the backend has not supplied a weight for this shipment. */
  weight: number | null;
  promisedAt: string;
}
export interface EvidenceObservation {
  id: string;
  label: string;
  kind: "custody" | "scan" | "gps" | "facility" | "delivery";
  location: [number, number];
  time: string;
  detail: string;
  confidence: "confirmed" | "vehicle_only" | "missing";
  facility: string;
  /** Backend evidence: the ISO time the observation occurred (dataset clock). */
  occurredAt?: string;
  /** When the record was received/visible (receipt time), if the backend served it. */
  recordedAt?: string;
  accuracyM?: number | null;
  speedKmh?: number | null;
  sourceRef?: string;
  vehicleId?: string;
  routeRunId?: string | null;
  tripId?: string | null;
  /** False when the backend point has no evidence id (not selectable as a source). */
  selectable?: boolean;
  /** Backend evidence: recorded after the investigation's evidence snapshot, so it did not see it. */
  afterInvestigation?: boolean;
}
/** What the rules allow for a case right now, as Canopus reports it. It performs nothing. */
export interface CanopusOffer {
  type: string;
  allowed: boolean;
  ruleId: string | null;
  reason: string;
  label: string;
  labelAr: string | null;
  /** The existing endpoint and exact body to send after the operator confirms. */
  confirm: { path: string; body: Record<string, unknown> } | null;
}
/** One answer from Canopus about one case, grounded in that case's records. */
export interface CanopusAnswer {
  /** "canopus_answer": the model's text. "record_answer": built by code from the records. */
  kind: "canopus_answer" | "record_answer";
  text: string;
  textAr: string | null;
  workflowState: string;
  answeredAt: string | null;
  evidenceIds: string[];
  graphNodeIds: string[];
  /** The agents' own recorded messages, copied by the server; never Canopus's words. */
  quotes: {
    role: string;
    text: string;
    recordId: string;
    occurredAt: string | null;
    title: string | null;
  }[];
  offers: CanopusOffer[];
  /** What the rules do not allow now, in plain words; shown only when asked. */
  unavailable: { reason: string; reasonAr: string | null }[];
  model: string | null;
}
/** One stored narration message of a run, as the backend wrote it. */
export interface NarrationEvent {
  id: string;
  sequence: number;
  /** The pipeline step it belongs to, as the rail's index. */
  stage: number;
  phase: string;
  /** Who wrote it: the narrator model, an agent (quoted), or code from a deterministic record. */
  kind: "canopus_summary" | "agent_output" | "system_event";
  title: string;
  titleAr: string | null;
  text: string;
  textAr: string | null;
  evidenceIds: string[];
  /** The cited records that are nodes of the case's evidence graph. */
  graphNodeIds: string[];
  occurredAt: string | null;
  scenarioTime: string | null;
  model: string | null;
  fallback: boolean;
  /** The recorded case state after this message; "resolved" is never inferred from prose. */
  outcomeState: string | null;
}
export interface GraphNode {
  id: string;
  label: string;
  kind:
    | "shipment"
    | "package"
    | "facility"
    | "vehicle"
    | "driver"
    | "contractor"
    | "observation"
    | "recommendation"
    | "outcome";
  detail: string;
  evidenceId?: string;
  /** Backend evidence: when the record occurred (dataset clock). */
  occurredAt?: string;
  /** Backend evidence: the Neo4j label this node was served with. */
  sourceKind?: string;
  /** Backend evidence: a record the diagnosis, recommendation, rule checks or outcome cite. */
  cited?: boolean;
  /** Backend evidence: an image stored with the record (e.g. a proof-of-delivery photo). */
  media?: string;
}
export interface GraphRelationship {
  id: string;
  source: string;
  target: string;
  label: string;
  detail: string;
}
export interface RouteVehicleSegment {
  vehicleId: string;
  routeRunId?: string | null;
  tripId?: string | null;
  points: [number, number][];
}
export interface RouteEvidence {
  expected: [number, number][];
  actual: [number, number][];
  vehicle: [number, number][];
  /** Observed GPS grouped by vehicle/context; paths are not joined across vehicles. */
  vehicleSegments: RouteVehicleSegment[];
  truncated?: Record<string, boolean>;
}
export interface InvestigationStatus {
  caseId: string;
  shipmentId: string;
  workerId: string | null;
  runId: string | null;
  runStatus: string;
  activeStage: string | null;
  workflowState: string;
  startedAt: string | null;
  updatedAt: string | null;
  leaseExpiresAt: string | null;
  asOf: string | null;
  stateVersion: number;
}
export interface RouteEvidenceView {
  schema: string;
  asOf: string;
  sampled: boolean;
  pointsReturned: number;
  /** Chronological extrema from returned observations (UI truth for timelines). */
  firstObservedAt: string | null;
  lastObservedAt: string | null;
  /** Backend summary fields when served; may disagree with observations until data is corrected. */
  summaryFirstObservedAt: string | null;
  summaryLastObservedAt: string | null;
  summaryNote: string | null;
  summaryMismatch: boolean;
  truncated: Record<string, boolean>;
}
export interface Recommendation {
  title: string;
  detail: string;
  authority: "automatic" | "operator" | "evidence";
  risk: "low" | "medium";
  expectedOutcome: string;
  /** Backend recommendation only: false while no reviewed recommendation exists. */
  available?: boolean;
}
export interface AuthorityDecision {
  caseId: string;
  action: string;
  verdict:
    | "approved"
    | "rejected"
    | "escalated"
    | "evidence_requested"
    | "reopened";
  actor: string;
  timestamp: string;
  reason: string;
}
export interface ExecutionReceipt {
  id: string;
  action: string;
  timestamp: string;
  successful: boolean;
  detail: string;
}
export interface VerifiedOutcome {
  id: string;
  timestamp: string;
  successful: boolean;
  evidenceIds: string[];
  detail: string;
}
export interface InvestigationRun {
  id: string;
  stage: number;
  startedAt: string;
  completedAt?: string;
}
export interface OperationalCase {
  id: string;
  shipment: Shipment;
  scenario: Scenario;
  issue: string;
  summary: string;
  diagnosis: string;
  priority: Priority;
  status: CaseStatus;
  openedAt: string;
  evidence: EvidenceObservation[];
  nodes: GraphNode[];
  relationships: GraphRelationship[];
  route: RouteEvidence;
  recommendation: Recommendation;
  run?: InvestigationRun;
  execution?: ExecutionReceipt;
  outcome?: VerifiedOutcome;
  /** Present only for cases served by the Suhail backend (never for lab fixtures). */
  backend?: BackendCaseState;
}
/** Authoritative state the backend served for a case. The browser never derives these. */
export interface BackendCaseState {
  caseId: string;
  shipmentId: string;
  workflowState: string;
  stateVersion: number;
  operationalStatus: string | null;
  symptomCodes: string[];
  causeCodes: string[];
  diagnosisAvailable: boolean;
  /** Why no accepted diagnosis is shown (backend reason code), when there is none. */
  diagnosisReason: string | null;
  /** True once GET /cases/{id} has been loaded; queue rows alone carry no evidence. */
  detailLoaded: boolean;
  detailError?: string;
  /** Operator controls the backend lifecycle accepts for the current state. */
  allowed: {
    investigate: boolean;
    approve: boolean;
    reject: boolean;
    escalate: boolean;
    verify: boolean;
    /** A person may record the finding of a physical or administrative check. */
    humanOutcome: boolean;
  };
  approvalRule?: string;
  approvalReason?: string;
  /** Recorded pipeline stage texts, by UI stage index. */
  stageDetail: Record<number, string>;
  /** Evidence ids the recorded stage cited, by UI stage index. */
  stageEvidence: Record<number, string[]>;
  /** Each stage's latest recorded status (e.g. COMPLETED, DEGRADED). */
  stageStatus?: Record<number, string>;
  /** Seconds into the run at each stage's latest event, as the backend measured them. */
  stageElapsed?: Record<number, number>;
  /** Set while the backend is asking a role again after an invalid model reply. */
  repairing?: string | null;
  /** The finished run's measured timings, from the run record. */
  timing?: {
    totalSeconds: number | null;
    firstConclusionSeconds: number | null;
    modelSeconds: number | null;
    stageSeconds: Record<number, number>;
  };
  pipelineStatus: string;
  /** Investigation waiting for worker capacity; backend queued the case without failing it. */
  investigationQueued?: boolean;
  routeEvidence?: RouteEvidenceView;
  /** Set while a re-investigation is queued: the earlier run, which is no longer current. */
  supersededRunId?: string | null;
  investigationAsOf: string | null;
  evidenceAfterInvestigation: number;
  /** Counts before the graph was bounded for display. */
  graphTotals?: { nodes: number; relationships: number; shown: number };
  review?: {
    verdict: string | null;
    reasonCode: string | null;
    summary: string | null;
    /** False when a deterministic guard, not the independent model reviewer, produced it. */
    byModel: boolean;
  };
  /**
   * The investigator's own findings. `accepted` is false when the independent reviewer did
   * not accept them: they are then shown labelled, never as what happened.
   */
  investigation?: {
    accepted: boolean;
    primaryCause: string | null;
    confidence: string | null;
    summary: string | null;
    toolCalls: number;
    /** The conclusion was reached on the investigator's final allowed turn. */
    forcedFinalTurn: boolean;
    requiresPhysicalCheck: boolean;
    snapshotSuperseded: boolean;
    hypotheses: {
      cause: string;
      status: "supported" | "refuted" | "uncertain";
      assessment: string | null;
      supporting: string[];
      contradicting: string[];
    }[];
    missingEvidence: string[];
  };
  /** What the investigation did, from the run record: every evidence query, the reviews, the budget. */
  investigationLog?: {
    mode: string;
    modelCallsUsed: number | null;
    modelCallCap: number | null;
    capReached: boolean;
    steps: {
      round: number;
      tool: string;
      purpose: string;
      args: string;
      records: number;
      /** Records of other shipments or shared records this query returned. */
      beyondShipment: number;
      failure: string | null;
    }[];
    reviews: {
      round: number;
      verdict: string;
      feedback: string;
      unsupportedClaims: string[];
      unaddressedContradictions: string[];
      alternativesTested: boolean | null;
      byModel: boolean;
    }[];
    citations: { cited: number; valid: number } | null;
    failedChecks: string[];
    nextEvidenceStep: string | null;
    degraded: string[];
    /** The backend's own degraded kinds, e.g. turn_budget_exhausted. */
    degradedKinds: string[];
    /** Why model replies were rejected during the run, as the backend recorded them. */
    rejectedReplies: string[];
  };
  /** The deterministic authority policy's decision on the recommended action. */
  authority?: {
    riskClass: string;
    ruleId: string;
    reason: string;
    closure: string | null;
  };
  /** Deterministic rule checks, labelled: signals for monitoring, never the cause. */
  ruleSignals?: {
    asOf: string;
    signals: { code: string; summary: string; evidenceIds: string[] }[];
  };
  riskClass?: string | null;
  actionType?: string | null;
  outcomeStatus?: string | null;
  /**
   * What the independent verifier (or a person) recorded after the action, as served.
   * "failed": checked and not confirmed. "exception_remains": the action worked but the
   * exception is still there. "finding": a person's finding on record that did not resolve.
   */
  verification?: {
    result:
      | "confirmed"
      | "failed"
      | "exception_remains"
      | "finding"
      /** The request was delivered but no confirming evidence arrived by the deadline. */
      | "unanswered";
    status: string;
    byPerson: boolean;
    reason: string;
    remainingSymptoms: string[];
    verifiedAt: string | null;
  };
  /** Until when the verifier waits for evidence of the executed action. */
  /** The backend's one assessment of the case, composed from its records (API shape). */
  brief?: ApiBrief | null;
  /** Per pipeline step: the backend's short fact for its latest round. */
  stageFacts?: Record<number, { en: string; ar: string | null; status: string }>;
  /** The run's stored narration, oldest first; empty until the backend narrates a run. */
  narration?: { runId: string | null; status: string; events: NarrationEvent[] };
  /** The backend's statement of why the case is unresolved and what it needs next. */
  nextStep?: {
    code: string;
    actor: string;
    text: string;
    textAr: string;
    resolved: boolean;
    blockedBy: {
      ruleId: string;
      reason: string;
      reviewVerdict: string | null;
      reviewFeedback: string | null;
    } | null;
    missingEvidence: string[];
    attempted: {
      actionType: string;
      authority: string;
      status: string;
      verificationStatus: string | null;
      success: boolean | null;
      exceptionCleared: boolean | null;
      reason: string | null;
    }[];
  } | null;
  /** An outcome recorded for an earlier action of this case, superseded by a later cycle. */
  earlierOutcome?: { reason: string; success: boolean } | null;
  verificationDeadline?: string | null;
  /** When an answer to the executed action is scheduled, if the backend says so. */
  expectedResponseAt?: string | null;
  asOf?: string;
}
export type AuditKind =
  | "investigation"
  | "evidence"
  | "recommendation"
  | "policy"
  | "decision"
  | "execution"
  | "verification"
  | "resolution"
  | "intake";
export interface InvestigationStageEvent {
  id: string;
  caseId: string;
  timestamp: string;
  evidenceTimestamp?: string;
  runId?: string;
  evidenceIds?: string[];
  /** "policy": the deterministic authority policy. "system": monitor, ingestion, execution adapter, rule worker. */
  actorRole?:
    | "investigator"
    | "reviewer"
    | "operator"
    | "verifier"
    | "policy"
    | "system";
  kind: AuditKind;
  title: string;
  detail: string;
  actor: string;
  stage?: number;
  /** True for browser lab fixtures; false for events recorded by the backend. */
  simulated: boolean;
  /** Backend audit events: the backend event type, verbatim. */
  eventType?: string;
  shipmentId?: string;
}
export interface CaseQueue {
  cases: OperationalCase[];
  automatic: boolean;
  events: InvestigationStageEvent[];
  decisions: AuthorityDecision[];
  revision: number;
  version: 1;
  /** Backend only: cases a screen holds open that the queue does not (yet) list. Never shown in lists. */
  unlisted?: OperationalCase[];
  /** Present only when the queue is served by the Suhail backend. */
  connection?: BackendConnection;
}
export interface BackendConnection {
  state: "connecting" | "online" | "degraded" | "offline";
  /** The last error the backend or network returned, verbatim where safe. */
  error?: string;
  lastSyncAt?: string;
  /** The backend's logical dataset clock. */
  asOf?: string;
  database?: string;
  synthetic: boolean;
  operator?: { actorId: string; role: string; mode: string };
  worker?: {
    state: string;
    activeCaseId: string | null;
    activeCases: InvestigationStatus[];
    activeCount: number;
    concurrency: number;
    processedCount: number;
    lastCaseId: string | null;
  };
  /** The backend's simulated clock: whether it is advancing, and how fast. */
  clock?: { running: boolean; speed: number };
  /** Shipments in a curated session, when the monitor is limited to a listed set. */
  curatedShipments?: number | null;
  queue?: { total: number; loaded: number; truncated: boolean };
  audit?: { total: number; loaded: number; truncated: boolean; loading: boolean };
  /** Whether operator controls can be sent from this page (same-origin, loopback). */
  controls: "available" | "unavailable" | "unknown";
}
export interface Facility {
  id: string;
  name: string;
  city: string;
  type: string;
  location: [number, number];
}
export interface OperationsCatalog {
  /** "lab": browser fixtures. "backend": the Suhail API. */
  source: "lab" | "backend";
  causes: { value: string; label: string }[];
  operational: { value: string; label: string; arabic: string }[];
  cities: string[];
  cityLocations: Record<string, [number, number]>;
  facilities: Facility[];
}
export type HumanOutcomeType =
  | "parcel_located"
  | "delivered_confirmed_by_person"
  | "returned_to_depot"
  | "parcel_not_found"
  | "data_corrected";
type Result = void | Promise<void>;
export interface OperationsService {
  getSnapshot(): CaseQueue;
  subscribe(listener: () => void): () => void;
  setAutomatic(enabled: boolean): Result;
  investigate(caseId: string): Result;
  decide(
    caseId: string,
    verdict: AuthorityDecision["verdict"],
    reason: string,
  ): Result;
  verify(caseId: string): Result;
  tick(): void;
  addCase(scenario: Scenario): string;
  reset(): void;
  answer(caseId: string, question: string): string;
  catalog(): OperationsCatalog;
  /** Backend only: record a person's finding after a physical or administrative check. */
  recordHumanOutcome?(
    caseId: string,
    finding: {
      outcomeType: HumanOutcomeType;
      finding: string;
      evidenceIds: string[];
    },
  ): Promise<void>;
  /** Backend only: load a case's evidence and follow its live pipeline stream. */
  watchCase?(caseId: string): () => void;
  /** Backend only: start or pause the simulated clock (cases arrive only while it runs). */
  setClock?(running: boolean): Promise<void>;
  /**
   * Backend only: run the clock fast until an awaited result arrives or a new case opens,
   * then return to the current speed. Every other shipment ages by the skipped time.
   */
  skipClock?(): Promise<{
    reason: string;
    simulatedMinutes: number;
    caseIds: string[];
    stillAwaiting: number;
  }>;
  /** Backend only: one question about one case. Read-only; nothing is stored. */
  askCanopus?(
    caseId: string,
    question: string,
    language: "en" | "ar",
    history: { role: "operator" | "canopus"; text: string }[],
  ): Promise<CanopusAnswer>;
  /** Backend only: send an offer's existing request after the operator confirmed it. */
  confirmCanopusOffer?(caseId: string, offer: CanopusOffer): Promise<void>;
  /** Backend only: load evidence for these cases (a screen needs their detail). */
  loadCases?(caseIds: string[]): Promise<void>;
  /** Backend only: re-read the queue and status now. */
  refresh?(): Promise<void>;
  /** Backend only: load the audit ledger (bounded, incremental). */
  loadAudit?(): Promise<void>;
  /** Backend only: load the live graph schema. */
  schema?(): Promise<{
    nodes: { id: string; label: string }[];
    relationships: { id: string; type: string; from: string; to: string }[];
  }>;
}
/** Lab builds only: the fixture narration for a stage. The connected build shows recorded text instead. */
const lab = (text: string) => (import.meta.env.VITE_SUHAIL_DATA === "lab" ? text : "");
export const stages = [
  {
    label: "Collect",
    arabic: "جمع",
    detail: lab("Collecting shipment scans and delivery records."),
    kind: "evidence",
  },
  {
    label: "Graph",
    arabic: "العلاقات",
    detail: lab("Reconstructing the expected journey and linked custody evidence."),
    kind: "evidence",
  },
  {
    label: "Diagnose",
    arabic: "التشخيص",
    detail: lab("Comparing parcel custody observations and manifest contradictions."),
    kind: "investigation",
  },
  {
    label: "Precedent",
    arabic: "السوابق",
    detail: lab("Reviewing similar synthetic cases and recovery outcomes."),
    kind: "investigation",
  },
  {
    label: "Recommend",
    arabic: "التوصية",
    detail: lab("Preparing an evidence-grounded recovery recommendation."),
    kind: "recommendation",
  },
  {
    label: "Review",
    arabic: "المراجعة",
    detail: lab("Checking action risk, policy, and required human authority."),
    kind: "policy",
  },
  {
    label: "Route",
    arabic: "التوجيه",
    detail: lab("Routing the authorized local recovery action for simulated execution."),
    kind: "execution",
  },
  {
    label: "Outcome",
    arabic: "النتيجة",
    detail: lab("Independently checking the new custody observation and result."),
    kind: "verification",
  },
] as const;
export const statusLabels: Record<CaseStatus, string> = {
  queued: "Queued",
  investigating: "Investigating",
  human_review: "Awaiting approval",
  needs_evidence: "Needs evidence",
  executing: "Executing",
  verifying: "Verifying outcome",
  escalated: "Escalated",
  resolved: "Resolved",
};
