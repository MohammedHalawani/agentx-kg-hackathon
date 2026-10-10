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
export type Priority = "high" | "medium" | "low";
export interface Shipment {
  id: string;
  packageId: string;
  origin: string;
  destination: string;
  customer: string;
  service: string;
  weight: number;
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
}
export interface AuthorityDecision {
  caseId: string;
  action: string;
  verdict: "approved" | "rejected" | "escalated";
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
  actorRole?: "investigator" | "reviewer" | "operator" | "verifier";
  kind: AuditKind;
  title: string;
  detail: string;
  actor: string;
  stage?: number;
  simulated: true;
}
export interface CaseQueue {
  cases: OperationalCase[];
  automatic: boolean;
  events: InvestigationStageEvent[];
  decisions: AuthorityDecision[];
  revision: number;
  version: 1;
}
export interface OperationsService {
  getSnapshot(): CaseQueue;
  subscribe(listener: () => void): () => void;
  setAutomatic(enabled: boolean): void;
  investigate(caseId: string): void;
  decide(
    caseId: string,
    verdict: AuthorityDecision["verdict"],
    reason: string,
  ): void;
  verify(caseId: string): void;
  tick(): void;
  addCase(scenario: Scenario): string;
  reset(): void;
  answer(caseId: string, question: string): string;
}
export const stages = [
  {
    label: "Collect",
    arabic: "جمع",
    detail: "Collecting shipment scans and delivery records.",
    kind: "evidence",
  },
  {
    label: "Graph",
    arabic: "العلاقات",
    detail: "Reconstructing the expected journey and linked custody evidence.",
    kind: "evidence",
  },
  {
    label: "Diagnose",
    arabic: "التشخيص",
    detail:
      "Comparing parcel custody observations and manifest contradictions.",
    kind: "investigation",
  },
  {
    label: "Precedent",
    arabic: "السوابق",
    detail: "Reviewing similar synthetic cases and recovery outcomes.",
    kind: "investigation",
  },
  {
    label: "Recommend",
    arabic: "التوصية",
    detail: "Preparing an evidence-grounded recovery recommendation.",
    kind: "recommendation",
  },
  {
    label: "Review",
    arabic: "المراجعة",
    detail: "Checking action risk, policy, and required human authority.",
    kind: "policy",
  },
  {
    label: "Route",
    arabic: "التوجيه",
    detail:
      "Routing the authorized local recovery action for simulated execution.",
    kind: "execution",
  },
  {
    label: "Outcome",
    arabic: "النتيجة",
    detail: "Independently checking the new custody observation and result.",
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
