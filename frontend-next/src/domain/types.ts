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
  /** Backend evidence: the Neo4j label this node was served with. */
  sourceKind?: string;
}
export interface GraphRelationship {
  id: string;
  source: string;
  target: string;
  label: string;
  detail: string;
}
export interface RouteEvidence {
  expected: [number, number][];
  actual: [number, number][];
  vehicle: [number, number][];
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
  };
  approvalRule?: string;
  approvalReason?: string;
  /** Recorded pipeline stage texts, by UI stage index. */
  stageDetail: Record<number, string>;
  /** Evidence ids the recorded stage cited, by UI stage index. */
  stageEvidence: Record<number, string[]>;
  pipelineStatus: string;
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
  /** Deterministic rule checks, labelled: signals for monitoring, never the cause. */
  ruleSignals?: {
    asOf: string;
    signals: { code: string; summary: string; evidenceIds: string[] }[];
  };
  riskClass?: string | null;
  actionType?: string | null;
  outcomeStatus?: string | null;
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
    processedCount: number;
    lastCaseId: string | null;
  };
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
  /** Backend only: load a case's evidence and follow its live pipeline stream. */
  watchCase?(caseId: string): () => void;
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
