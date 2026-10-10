import type {
  ApiAuditEvent,
  ApiCaseDetail,
  ApiEvidenceNode,
  ApiExploreItem,
  ApiLayerPoint,
  ApiPipelineEvent,
  ApiPipelineState,
  ApiQueueCase,
  ApiRouteSegment,
  WorkflowState,
} from "@/api/contracts";
import type {
  AuditKind,
  AuthorityDecision,
  BackendCaseState,
  CaseStatus,
  EvidenceObservation,
  Facility,
  GraphNode,
  GraphRelationship,
  InvestigationStageEvent,
  OperationalCase,
  Priority,
  Recommendation,
} from "@/domain/types";

/**
 * Pure mappings from backend payloads to the screens' view model. Nothing here decides a
 * diagnosis, an authority, an execution result or an outcome: those are copied from the
 * backend or left absent. Where the backend serves nothing, the view model says so.
 */

/** Backend pipeline stage -> the UI's eight-step rail. The outcome gate (7) is not a graph node. */
export const STAGE_INDEX: Record<string, number> = {
  extract: 0,
  retrieve: 1,
  classify: 2,
  retrieve_context: 3,
  recommend: 4,
  review: 5,
  writeback: 6,
  escalate: 6,
};

const STATUS: Record<WorkflowState, CaseStatus> = {
  OPEN: "queued",
  REOPENED: "queued",
  INVESTIGATING: "investigating",
  NEEDS_EVIDENCE: "needs_evidence",
  REJECTED: "needs_evidence",
  RECOMMENDATION_READY: "human_review",
  AWAITING_APPROVAL: "human_review",
  HUMAN_REVIEW: "human_review",
  ACTION_INITIATED: "executing",
  AWAITING_OUTCOME: "verifying",
  ESCALATED: "escalated",
  RESOLVED: "resolved",
};
export function statusOf(workflow: string): CaseStatus {
  return STATUS[workflow as WorkflowState] ?? "queued";
}

/** The backend lifecycle (chat/operations/lifecycle.py). The backend re-checks every request. */
const DECISION_SOURCES = {
  reject: ["AWAITING_APPROVAL", "HUMAN_REVIEW", "RECOMMENDATION_READY"],
  escalate: [
    "OPEN",
    "AWAITING_APPROVAL",
    "HUMAN_REVIEW",
    "NEEDS_EVIDENCE",
    "RECOMMENDATION_READY",
  ],
};
function allowedFor(
  workflow: string,
  approvable: boolean,
): BackendCaseState["allowed"] {
  return {
    investigate: workflow === "OPEN" || workflow === "REOPENED",
    approve: approvable,
    reject: DECISION_SOURCES.reject.includes(workflow),
    escalate: DECISION_SOURCES.escalate.includes(workflow),
    verify: workflow === "AWAITING_OUTCOME",
  };
}

export function humanize(code: string | null | undefined) {
  if (!code) return "";
  const text = code.replaceAll("_", " ").toLowerCase();
  return text.charAt(0).toUpperCase() + text.slice(1);
}
const shortId = (id: string) => id.replace(/^SYN-/, "");
const text = (value: unknown) =>
  value === null || value === undefined || value === "None" ? "" : String(value);
const number = (value: unknown) => {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};
function riyadhTime(timestamp: string | null | undefined) {
  if (!timestamp) return "—";
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("en-GB", {
    timeZone: "Asia/Riyadh",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}
function priorityOf(value: string | undefined): Priority {
  return value === "high" || value === "medium" || value === "low"
    ? value
    : "unknown";
}

const ABSENT_DIAGNOSIS: Record<string, string> = {
  not_investigated:
    "Not investigated yet. The monitor opened this case from observed symptoms; no cause has been established.",
  investigation_in_progress:
    "An investigation is running now. No diagnosis is shown until the independent reviewer accepts it.",
  reinvestigation_pending:
    "Queued for re-investigation. The earlier run is superseded and is not shown as the current diagnosis.",
  investigation_incomplete:
    "The investigation did not complete. No diagnosis is available.",
  investigation_unavailable:
    "The investigator did not produce a valid conclusion. No diagnosis is available.",
  no_agent_investigation:
    "This run used deterministic rule checks only. Rule signals are not a diagnosis.",
  review_not_accepted:
    "The independent reviewer did not accept the investigation. Its findings are not presented as what happened.",
  no_operations_ledger: "No operations ledger is available for this case.",
  not_a_case: "This shipment has no investigation case.",
};
export function absentDiagnosis(reason: string | null | undefined) {
  return (
    ABSENT_DIAGNOSIS[reason ?? "not_investigated"] ??
    "No accepted diagnosis is available."
  );
}

const NO_RECOMMENDATION: Recommendation = {
  title: "No recommendation yet",
  detail:
    "The backend has not recorded a reviewed recommendation for this case.",
  authority: "evidence",
  risk: "medium",
  expectedOutcome:
    "A case resolves only when the independent verifier confirms the outcome from evidence recorded after the action.",
  available: false,
};

function issueOf(row: ApiQueueCase) {
  if (row.diagnosis_available) {
    const cause = row.category ?? row.cause_codes?.[0];
    if (cause) return humanize(cause);
  }
  const symptoms = row.symptom_codes ?? [];
  if (symptoms.length)
    return `${humanize(symptoms[0])}${symptoms.length > 1 ? ` +${symptoms.length - 1}` : ""}`;
  return "Exception detected";
}

function emptyBackend(row: ApiQueueCase): BackendCaseState {
  return {
    caseId: row.case_id,
    shipmentId: row.shipment_id,
    workflowState: row.workflow_state,
    stateVersion: row.state_version ?? 0,
    operationalStatus: row.operational_status ?? null,
    symptomCodes: row.symptom_codes ?? [],
    causeCodes: row.diagnosis_available ? (row.cause_codes ?? []) : [],
    diagnosisAvailable: row.diagnosis_available === true,
    diagnosisReason: row.diagnosis_available ? null : "not_loaded",
    detailLoaded: false,
    allowed: allowedFor(row.workflow_state, false),
    stageDetail: {},
    stageEvidence: {},
    pipelineStatus: "UNKNOWN",
    investigationAsOf: null,
    evidenceAfterInvestigation: 0,
    asOf: row.as_of ?? undefined,
  };
}

/**
 * A queue row as a case. Evidence, graph, route, recommendation and outcome stay empty until
 * the case detail is loaded; a loaded detail of the same version is kept.
 */
export function caseFromQueue(
  row: ApiQueueCase,
  previous?: OperationalCase,
  explore?: ApiExploreItem,
): OperationalCase {
  const keep =
    previous?.backend?.detailLoaded &&
    previous.backend.stateVersion === (row.state_version ?? 0)
      ? previous
      : undefined;
  const origin =
    explore?.origin_city ?? previous?.shipment.origin ?? "";
  const destination =
    row.city ??
    explore?.destination_city ??
    previous?.shipment.destination ??
    "";
  const base: OperationalCase = {
    id: row.case_id,
    shipment: {
      id: row.shipment_id,
      packageId: previous?.shipment.packageId ?? "",
      origin: origin || "—",
      destination: destination || "—",
      customer: "",
      service: previous?.shipment.service ?? "",
      weight: previous?.shipment.weight ?? null,
      promisedAt: previous?.shipment.promisedAt ?? "",
    },
    scenario: "normal",
    issue: issueOf(row),
    summary: row.issue_summary,
    diagnosis: row.diagnosis_available
      ? row.issue_summary
      : "No accepted diagnosis is shown for this case yet.",
    priority: priorityOf(row.priority),
    status: statusOf(row.workflow_state),
    openedAt: row.opened_at ?? row.as_of ?? "",
    evidence: previous?.evidence ?? [],
    nodes: previous?.nodes ?? [],
    relationships: previous?.relationships ?? [],
    route: previous?.route ?? { expected: [], actual: [], vehicle: [] },
    recommendation: previous?.recommendation ?? NO_RECOMMENDATION,
    run: previous?.run,
    execution: previous?.execution,
    outcome: previous?.outcome,
    backend: {
      ...(previous?.backend ?? emptyBackend(row)),
      workflowState: row.workflow_state,
      operationalStatus: row.operational_status ?? null,
      symptomCodes: row.symptom_codes ?? [],
      diagnosisAvailable: row.diagnosis_available === true,
      causeCodes: row.diagnosis_available ? (row.cause_codes ?? []) : [],
      // A version the browser has not loaded yet: the detail is refetched by the service.
      detailLoaded: !!keep,
      stateVersion: keep ? keep.backend!.stateVersion : (row.state_version ?? 0),
      allowed: keep
        ? keep.backend!.allowed
        : allowedFor(row.workflow_state, false),
    },
  };
  if (keep) base.diagnosis = keep.diagnosis;
  return base;
}

/** A case reached by a direct link before (or without) its queue row. */
export function placeholderCase(caseId: string): OperationalCase {
  return caseFromQueue({
    case_id: caseId,
    shipment_id: "",
    issue_summary: "",
    priority: "unknown",
    workflow_state: "OPEN",
    state_version: -1,
  });
}

const FACILITY_KINDS = new Set([
  "Hub",
  "SortingCenter",
  "DeliveryDepot",
  "Branch",
  "FulfillmentWarehouse",
  "OrganizationWarehouse",
]);
const OBSERVATION_RANK: Record<string, number> = {
  CustodyEvent: 0,
  DeliveryAttempt: 1,
  DeliveryProof: 1,
  RecipientReport: 1,
  DepotReconciliation: 1,
  HandoffEvidence: 2,
  Manifest: 2,
  StatusEvent: 3,
  ScanEvent: 4,
  ContactAttempt: 4,
  AuthenticationEvidence: 5,
  SignatureEvidence: 5,
  PhotoEvidence: 5,
  GPSObservation: 6,
  TrafficObservation: 6,
  LocationPin: 6,
};
/** How many of a case's recorded nodes the graph draws (cited evidence first). The total is always stated. */
export const GRAPH_LIMIT = 48;

function graphKind(kind: string): GraphNode["kind"] | null {
  if (kind === "Shipment") return "shipment";
  if (kind === "Package") return "package";
  if (FACILITY_KINDS.has(kind)) return "facility";
  if (kind === "Vehicle") return "vehicle";
  if (kind === "Driver") return "driver";
  if (kind === "Provider" || kind === "Organization") return "contractor";
  if (kind in OBSERVATION_RANK) return "observation";
  // Scanners and driver apps are where observations come from; drawn with the observations.
  if (kind === "Device") return "observation";
  if (kind === "OpsRecommendation") return "recommendation";
  if (kind === "OpsOutcome") return "outcome";
  return null;
}
function nodeLabel(node: ApiEvidenceNode) {
  const p = node.properties;
  const kind = node.kind;
  if (kind === "Shipment") return text(p.tracking_id) || shortId(node.id);
  if (kind === "Package") return shortId(node.id).split("-").slice(-2).join("-");
  if (kind === "Provider") return text(p.name) || shortId(node.id);
  if (kind === "CustodyEvent") return `Custody · ${humanize(text(p.event_type))}`;
  if (kind === "ScanEvent")
    return `Scan · ${humanize(text(p.observation_type))}`;
  if (kind === "DeliveryAttempt")
    return `Attempt · ${humanize(text(p.disposition))}`;
  if (kind === "StatusEvent") return `Status · ${humanize(text(p.status))}`;
  if (kind === "GPSObservation") return "Vehicle GPS";
  if (kind === "Device")
    return `Device · ${humanize(text(p.device_kind)) || shortId(node.id)}`;
  if (kind === "OpsRecommendation")
    return text(p.action_en) || text(p.action) || "Recommendation";
  if (kind === "OpsOutcome")
    return `Outcome · ${humanize(text(p.verification_status)) || "recorded"}`;
  if (graphKind(kind) === "observation")
    return kind.replace(/([a-z])([A-Z])/g, "$1 $2");
  return shortId(node.id);
}
const DETAIL_KEYS = [
  "event_type",
  "observation_type",
  "disposition",
  "failed_reason",
  "status",
  "source_quality",
  "position_scope",
  "facility_id",
  "from_id",
  "to_id",
  "vehicle_id",
  "driver_id",
  "provider_id",
  "device_ref",
  "city",
  "ownership",
  "vehicle_class",
  "employment",
  "provider_type",
  "device_kind",
  "report_code",
  "result",
  "verification_status",
  "success",
  "decision",
];
function nodeDetail(node: ApiEvidenceNode) {
  const p = node.properties;
  const facts = DETAIL_KEYS.filter((key) => text(p[key]) !== "").map(
    (key) => `${key.replaceAll("_", " ")}: ${text(p[key])}`,
  );
  const when = text(p.occurred_at);
  return [
    `${node.kind} ${node.id}`,
    when ? `occurred ${riyadhTime(when)} AST` : "",
    ...facts,
    node.after_investigation
      ? "recorded after the investigation's evidence snapshot"
      : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

function isSegment(
  item: ApiLayerPoint | ApiRouteSegment,
): item is ApiRouteSegment {
  return "points" in item;
}
const position = (point: ApiLayerPoint): [number, number] => [
  point.lat,
  point.lng,
];

function stageSummary(event: ApiPipelineEvent): string {
  const out = event.output ?? {};
  // Rule output and deterministic guards are named as such, never as an agent's finding.
  const rules = out.agent === "evidence_rules";
  switch (event.stage) {
    case "extract":
      return out.evidence_ids
        ? `Collected ${out.evidence_ids.length} evidence items visible at the snapshot.`
        : `Evidence collection ${event.status.toLowerCase()}.`;
    case "retrieve":
      return out.nodes !== undefined
        ? `Graph context retrieved: ${out.nodes} nodes, ${out.relationships ?? 0} relationships.`
        : `Graph retrieval ${event.status.toLowerCase()}.`;
    case "classify": {
      const first = out.diagnoses?.[0];
      const summary = first?.summary_en ?? first?.summary;
      return summary
        ? `${rules ? "Rule check, not a diagnosis · " : ""}${humanize(first?.code)}: ${summary}`
        : out.diagnoses
          ? `${out.diagnoses.length} hypotheses recorded.`
          : `Hypothesis stage ${event.status.toLowerCase()}.`;
    }
    case "retrieve_context":
      return out.verified_precedents !== undefined
        ? `${out.verified_precedents} verified precedents retrieved.`
        : `Precedent retrieval ${event.status.toLowerCase()}.`;
    case "recommend":
      return out.proposal?.action_en || out.proposal?.action
        ? `${rules ? "Rule-derived proposal · " : ""}${out.proposal.action_en ?? out.proposal.action}`
        : `Recommendation stage ${event.status.toLowerCase()}.`;
    case "review":
      return out.verdict
        ? `${out.agent === "deterministic_guard" ? "Deterministic evidence guard (no model review)" : "Reviewer verdict"}: ${out.verdict}${out.feedback ? `. ${out.feedback}` : ""}`
        : `Review ${event.status.toLowerCase()}.`;
    default:
      return out.workflow_state
        ? `Recorded. Case state: ${humanize(out.workflow_state)}.`
        : `${humanize(String(event.stage))} ${event.status.toLowerCase()}.`;
  }
}

/** Recorded pipeline events as the UI rail's furthest stage and per-stage texts. */
export function pipelineView(events: ApiPipelineEvent[]) {
  const stageDetail: Record<number, string> = {};
  const stageEvidence: Record<number, string[]> = {};
  let stage = -1;
  for (const event of [...events].sort((a, b) => a.sequence - b.sequence)) {
    const index = STAGE_INDEX[event.stage];
    if (index === undefined) continue;
    stage = Math.max(stage, index);
    stageDetail[index] = stageSummary(event);
    if (event.output?.evidence_ids?.length)
      stageEvidence[index] = event.output.evidence_ids;
  }
  return { stage, stageDetail, stageEvidence };
}

const VERDICTS: Record<string, AuthorityDecision["verdict"]> = {
  approve: "approved",
  reject: "rejected",
  escalate: "escalated",
  request_evidence: "evidence_requested",
  reopen: "reopened",
};
export const DECISION_BY_VERDICT: Record<string, string> = {
  approved: "approve",
  rejected: "reject",
  escalated: "escalate",
};
export function verdictOf(decision: string | null | undefined) {
  return VERDICTS[decision ?? ""] ?? null;
}

function recommendationOf(detail: ApiCaseDetail): Recommendation {
  const r = detail.recommendation;
  if (!r) return NO_RECOMMENDATION;
  const risk = r.risk_class ?? "";
  return {
    title: r.action_en ?? r.action ?? humanize(r.action_type) ?? "Recommendation",
    detail:
      r.summary_en ??
      r.authority_reason ??
      (r.action_type ? `Action type: ${humanize(r.action_type)}.` : ""),
    authority:
      risk === "AUTO"
        ? "automatic"
        : risk === "APPROVAL_REQUIRED"
          ? "operator"
          : "evidence",
    risk: risk === "AUTO" ? "low" : "medium",
    expectedOutcome: NO_RECOMMENDATION.expectedOutcome,
    available: true,
  };
}

/** The investigator's findings: accepted ones, or (labelled) ones the reviewer did not accept. */
function investigationOf(
  detail: ApiCaseDetail,
): BackendCaseState["investigation"] {
  const d = detail.diagnosis;
  if (!d) return undefined;
  const hypotheses = (list: typeof d.hypotheses | undefined) =>
    (list ?? []).map((h) => ({
      cause: h.cause,
      status: h.status,
      assessment: h.assessment ?? null,
      supporting: h.supporting_evidence_ids ?? [],
      contradicting: h.contradicting_evidence_ids ?? [],
    }));
  if (d.available)
    return {
      accepted: true,
      primaryCause: d.primary_cause,
      confidence: d.confidence,
      summary: d.summary,
      toolCalls: d.tool_calls ?? 0,
      requiresPhysicalCheck: d.requires_physical_check === true,
      snapshotSuperseded: d.snapshot_superseded === true,
      hypotheses: hypotheses(d.hypotheses),
      missingEvidence: d.missing_evidence ?? [],
    };
  const u = d.unaccepted_investigation;
  if (!u) return undefined;
  return {
    accepted: false,
    primaryCause: u.primary_cause,
    confidence: u.confidence,
    summary: u.summary,
    toolCalls: u.tool_calls ?? 0,
    requiresPhysicalCheck: u.requires_physical_check === true,
    snapshotSuperseded: u.snapshot_superseded === true,
    hypotheses: hypotheses(u.hypotheses),
    missingEvidence: u.missing_evidence ?? [],
  };
}

/** GET /cases/{id} merged into the case. Stored workflow, review, execution and outcome are authoritative. */
export function applyDetail(
  base: OperationalCase,
  detail: ApiCaseDetail,
): OperationalCase {
  const nodes = detail.evidence?.nodes ?? [];
  const edges = detail.evidence?.edges ?? [];
  const ledger = detail.ledger_graph ?? { nodes: [], edges: [] };
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const nameOf = (id: string | undefined) => {
    const node = id ? byId.get(id) : undefined;
    if (!node) return id ? shortId(id) : "—";
    // A delivered custody point is placed at its bound delivery proof, not at a facility.
    if (node.kind === "DeliveryProof") return "Delivery proof location";
    return (
      text(node.properties.name).replace(/ synthetic facility$/, "") ||
      shortId(node.id)
    );
  };
  const layers = detail.route_layers?.layers ?? {};

  // Map observations: only what the backend located. Vehicle GPS never stands in for custody.
  const evidence: EvidenceObservation[] = [];
  const seen = new Set<string>();
  const push = (item: EvidenceObservation) => {
    if (seen.has(item.id)) return;
    seen.add(item.id);
    evidence.push(item);
  };
  for (const point of layers.custody_points ?? []) {
    const id = point.evidence_id ?? `${point.entity_id}@${point.occurred_at}`;
    const event = byId.get(id);
    push({
      id,
      label: event ? nodeLabel(event) : "Custody observation",
      kind: "custody",
      location: position(point),
      time: riyadhTime(point.occurred_at),
      occurredAt: point.occurred_at ?? undefined,
      detail:
        `Corroborated custody at ${nameOf(point.entity_id)}.` +
        (event ? ` ${nodeDetail(event)}` : ""),
      confidence: "confirmed",
      facility: nameOf(point.entity_id),
    });
  }
  for (const point of layers.delivery_attempts ?? []) {
    const id = point.evidence_id ?? `attempt@${point.occurred_at}`;
    const event = byId.get(id);
    push({
      id,
      label: `Delivery attempt · ${humanize(point.disposition) || "recorded"}`,
      kind: "delivery",
      location: position(point),
      time: riyadhTime(point.occurred_at),
      occurredAt: point.occurred_at ?? undefined,
      detail:
        "Shown at the attempt's address reference, not a parcel or vehicle position. A recorded attempt is not proof of delivery." +
        (event ? ` ${nodeDetail(event)}` : ""),
      confidence: "missing",
      facility: "Address reference",
    });
  }
  for (const point of (layers.vehicle_path ?? []).slice(-6)) {
    const id = point.evidence_id ?? `gps@${point.occurred_at}`;
    push({
      id,
      label: "Vehicle GPS",
      kind: "gps",
      location: position(point),
      time: riyadhTime(point.occurred_at),
      occurredAt: point.occurred_at ?? undefined,
      detail: `Vehicle telemetry for ${point.vehicle_id ? shortId(point.vehicle_id) : "the assigned vehicle"}. It shows where the vehicle was, not where the parcel is.`,
      confidence: "vehicle_only",
      facility: point.vehicle_id ? shortId(point.vehicle_id) : "Vehicle",
    });
  }
  const expected = (layers.expected_route ?? [])
    .filter(isSegment)
    .sort((a, b) => (a.sequence ?? 0) - (b.sequence ?? 0))
    .flatMap((segment) => segment.points);
  const planned = expected.at(-1);
  if (planned && !evidence.some((e) => e.kind === "custody" && e.location[0] === planned.lat && e.location[1] === planned.lng))
    push({
      id: `planned:${planned.entity_id ?? "destination"}`,
      label: "Planned destination",
      kind: "facility",
      location: position(planned),
      time: "—",
      detail:
        "The end of the planned route. No custody observation is recorded here.",
      confidence: "missing",
      facility: nameOf(planned.entity_id),
    });
  evidence.sort((a, b) =>
    (a.occurredAt ?? "9999").localeCompare(b.occurredAt ?? "9999"),
  );

  // Graph: real nodes and relationships, bounded for display. Cited evidence is always kept.
  const pipeline = pipelineView(detail.pipeline?.events ?? []);
  // Citations that must survive the bound: what the diagnosis, recommendation, review and
  // outcome point at. The collection stages (extract, retrieve) list everything they read,
  // so they are not citations.
  const cited = new Set<string>([
    ...Object.entries(pipeline.stageEvidence)
      .filter(([stage]) => Number(stage) >= 2)
      .flatMap(([, ids]) => ids),
    ...(detail.rule_signals?.signals ?? []).flatMap(
      (signal) => signal.evidence_ids ?? [],
    ),
    ...(detail.recommendation?.evidence_ids ?? []),
    ...(detail.outcome?.evidence_ids ?? []),
    ...[
      ...(detail.diagnosis?.hypotheses ?? []),
      ...(detail.diagnosis?.unaccepted_investigation?.hypotheses ?? []),
    ].flatMap((h) => [
      ...(h.supporting_evidence_ids ?? []),
      ...(h.contradicting_evidence_ids ?? []),
    ]),
  ]);
  const located = new Set(evidence.map((e) => e.id));
  const candidates = [...nodes, ...ledger.nodes]
    .map((node) => ({ node, kind: graphKind(node.kind) }))
    .filter((item): item is { node: ApiEvidenceNode; kind: GraphNode["kind"] } =>
      item.kind !== null,
    );
  const rank = ({ node, kind }: (typeof candidates)[number]) => {
    if (kind === "shipment") return 0;
    if (kind === "package") return 1;
    if (kind === "recommendation" || kind === "outcome") return 2;
    if (cited.has(node.id)) return 3;
    if (located.has(node.id)) return 4;
    if (kind !== "observation") return 5;
    return 6 + (OBSERVATION_RANK[node.kind] ?? 6);
  };
  const ordered = [...candidates].sort(
    (a, b) =>
      rank(a) - rank(b) ||
      text(b.node.properties.occurred_at).localeCompare(
        text(a.node.properties.occurred_at),
      ),
  );
  const shown = ordered.slice(0, GRAPH_LIMIT);
  const shownIds = new Set(shown.map((item) => item.node.id));
  const graphNodes: GraphNode[] = shown.map(({ node, kind }) => ({
    id: node.id,
    label: nodeLabel(node),
    kind,
    detail: nodeDetail(node),
    evidenceId: located.has(node.id) ? node.id : undefined,
    sourceKind: node.kind,
  }));
  const allEdges = [...edges, ...ledger.edges];
  const relationships: GraphRelationship[] = allEdges
    .filter((edge) => shownIds.has(edge.start) && shownIds.has(edge.end))
    .map((edge) => ({
      id: edge.id,
      source: edge.start,
      target: edge.end,
      label: edge.kind,
      detail: `${shortId(edge.start)} ${edge.kind} ${shortId(edge.end)}`,
    }));

  const shipmentNode = nodes.find((node) => node.kind === "Shipment");
  const packageNode = nodes.find((node) => node.kind === "Package");
  const service = nodes.find((node) => node.kind === "ServiceLevel");

  const workflow = detail.workflow_state;
  const diagnosis = detail.diagnosis;
  const recommendation = recommendationOf(detail);
  const execution = (detail.executions ?? []).find(
    (item) => item.current_cycle !== false,
  );
  const outcome =
    detail.outcome &&
    detail.outcome.current_cycle !== false &&
    detail.outcome.invalidated !== true
      ? detail.outcome
      : null;
  const verified =
    !!outcome &&
    ["VERIFIED", "HUMAN_VERIFIED"].includes(outcome.verification_status ?? "");
  const approvable = detail.recommendation?.approvable === true;
  // Furthest recorded step; execution and the verified outcome extend the rail past the graph.
  const stage = verified || workflow === "AWAITING_OUTCOME"
    ? 7
    : execution
      ? Math.max(pipeline.stage, 6)
      : pipeline.stage;

  return {
    ...base,
    shipment: {
      ...base.shipment,
      id: detail.shipment_id,
      packageId: packageNode ? packageNode.id : base.shipment.packageId,
      origin:
        text(shipmentNode?.properties.origin_city) || base.shipment.origin,
      destination:
        text(shipmentNode?.properties.destination_city) ||
        base.shipment.destination,
      service:
        text(service?.properties.name) ||
        text(shipmentNode?.properties.flow_type) ||
        base.shipment.service,
      weight: number(packageNode?.properties.weight_kg),
    },
    priority:
      priorityOf(detail.priority) === "unknown"
        ? base.priority
        : priorityOf(detail.priority),
    status: statusOf(workflow),
    // With an accepted diagnosis the case is described by it; otherwise by what the monitor observed.
    issue: diagnosis?.available && diagnosis.primary_cause
      ? humanize(diagnosis.primary_cause)
      : base.issue,
    summary:
      diagnosis?.available && diagnosis.summary
        ? diagnosis.summary
        : base.summary,
    diagnosis: diagnosis?.available
      ? (diagnosis.summary ?? humanize(diagnosis.primary_cause))
      : absentDiagnosis(diagnosis?.reason),
    evidence,
    nodes: graphNodes,
    relationships,
    route: {
      expected: expected.map(position),
      actual: (layers.actual_route ?? []).map(position),
      vehicle: (layers.vehicle_path ?? []).map(position),
    },
    recommendation,
    run:
      detail.run || stage >= 0
        ? {
            id: detail.run?.entity_id ?? detail.last_run_id ?? "",
            stage: Math.max(stage, 0),
            startedAt: detail.run?.recorded_at ?? "",
            completedAt:
              detail.pipeline?.status && detail.pipeline.status !== "RUNNING"
                ? (detail.run?.recorded_at ?? undefined)
                : undefined,
          }
        : undefined,
    execution: execution
      ? {
          id: execution.receipt_ref ?? execution.entity_id ?? "",
          action: humanize(execution.action_type),
          timestamp: execution.occurred_at ?? execution.recorded_at ?? "",
          successful: !/FAIL|REFUS|TIMEOUT|ERROR/i.test(execution.status ?? ""),
          detail: `Execution ${humanize(execution.status) || "recorded"}${execution.authority ? ` under ${humanize(execution.authority)}` : ""}${execution.receipt_ref ? ` · receipt ${execution.receipt_ref}` : ""}. A receipt is not an outcome.`,
        }
      : undefined,
    outcome:
      verified && outcome
        ? {
            id: outcome.outcome_id ?? outcome.entity_id ?? "",
            timestamp: outcome.verified_at ?? outcome.recorded_at ?? "",
            successful:
              outcome.success === true && outcome.exception_cleared !== false,
            evidenceIds: outcome.evidence_ids ?? [],
            detail:
              outcome.reason ??
              `${humanize(outcome.verification_status)}${outcome.outcome_type ? ` · ${humanize(outcome.outcome_type)}` : ""}${outcome.remaining_symptoms?.length ? ` · remaining: ${outcome.remaining_symptoms.map(humanize).join(", ")}` : ""}`,
          }
        : undefined,
    backend: {
      ...(base.backend ?? emptyBackend({
        case_id: detail.case_id,
        shipment_id: detail.shipment_id,
        issue_summary: "",
        priority: "unknown",
        workflow_state: workflow,
      })),
      caseId: detail.case_id,
      shipmentId: detail.shipment_id,
      workflowState: workflow,
      stateVersion: detail.state_version,
      operationalStatus:
        detail.operational_status ?? base.backend?.operationalStatus ?? null,
      diagnosisAvailable: diagnosis?.available === true,
      diagnosisReason: diagnosis?.available ? null : (diagnosis?.reason ?? null),
      detailLoaded: true,
      detailError: undefined,
      allowed: allowedFor(workflow, approvable),
      approvalRule: detail.recommendation?.approval_rule,
      approvalReason: detail.recommendation?.approval_reason,
      stageDetail: pipeline.stageDetail,
      stageEvidence: pipeline.stageEvidence,
      pipelineStatus: detail.pipeline?.status ?? "UNKNOWN",
      supersededRunId: detail.previous_run?.entity_id ?? null,
      investigationAsOf: detail.pipeline?.investigation_as_of ?? null,
      evidenceAfterInvestigation:
        detail.pipeline?.evidence_after_investigation ?? 0,
      graphTotals: {
        nodes: nodes.length + ledger.nodes.length,
        relationships: allEdges.length,
        shown: graphNodes.length,
      },
      review: detail.review
        ? {
            verdict: detail.review.verdict ?? null,
            reasonCode: detail.review.reason_code ?? null,
            summary: detail.review.summary_en ?? detail.review.feedback ?? null,
            byModel:
              !!detail.review.model_verdict &&
              detail.review.mode !== "deterministic_evidence_guard",
          }
        : undefined,
      investigation: investigationOf(detail),
      ruleSignals: detail.rule_signals
        ? {
            asOf: detail.rule_signals.as_of,
            signals: (detail.rule_signals.signals ?? []).map((signal) => ({
              code: signal.code,
              summary: signal.summary_en ?? "",
              evidenceIds: signal.evidence_ids ?? [],
            })),
          }
        : undefined,
      riskClass: detail.recommendation?.risk_class ?? null,
      actionType: detail.recommendation?.action_type ?? null,
      outcomeStatus: detail.outcome?.verification_status ?? null,
      asOf: detail.as_of,
    },
  };
}

/** A live pipeline stream frame applied to the case's rail. Evidence is refetched separately. */
export function applyPipeline(
  base: OperationalCase,
  state: ApiPipelineState,
): OperationalCase {
  if (!base.backend) return base;
  const view = pipelineView(state.events);
  const queued = state.status === "QUEUED" && !state.events.length;
  return {
    ...base,
    status: statusOf(state.workflow_state),
    run: queued
      ? undefined
      : {
          id: state.run_id ?? base.run?.id ?? "",
          startedAt: base.run?.startedAt ?? "",
          stage: Math.max(view.stage, 0),
          completedAt: base.run?.completedAt,
        },
    backend: {
      ...base.backend,
      workflowState: state.workflow_state,
      pipelineStatus: state.status,
      supersededRunId: queued ? (state.previous_run_id ?? null) : null,
      stageDetail: queued ? {} : { ...base.backend.stageDetail, ...view.stageDetail },
      stageEvidence: queued
        ? {}
        : { ...base.backend.stageEvidence, ...view.stageEvidence },
      allowed: allowedFor(
        state.workflow_state,
        // Approval eligibility is only known from the case detail.
        state.state_version === base.backend.stateVersion
          ? base.backend.allowed.approve
          : false,
      ),
    },
  };
}

const AUDIT_KIND: Record<string, AuditKind> = {
  CASE_OPENED: "intake",
  CASE_CLAIMED: "investigation",
  ANALYSIS_STARTED: "investigation",
  CLAIM_RELEASED: "investigation",
  REANALYSIS_REQUESTED: "investigation",
  AFL_RETRY: "investigation",
  CLASSIFICATION: "investigation",
  EVIDENCE_RETRIEVED: "evidence",
  SIMULATION_EVENT: "evidence",
  RECOMMENDATION: "recommendation",
  RECOMMENDATION_READY: "recommendation",
  REVIEW_VERDICT: "policy",
  APPROVAL_CONTEXT_CHECKED: "policy",
  APPROVAL_CONTEXT_STALE: "policy",
  APPROVAL_REFUSED: "policy",
  OPERATOR_DECISION: "decision",
  CASE_REOPENED: "decision",
  HUMAN_OUTCOME_RECORDED: "decision",
  // The deterministic authority policy's own records: never an operator's decision.
  AUTHORITY_DECISION: "policy",
  ACTION_AUTHORIZED: "policy",
  EXECUTION_CONTEXT_CHECKED: "policy",
  EXECUTION_REFUSED: "policy",
  ACTION_EXECUTED: "execution",
  ACTION_NOT_ACKNOWLEDGED: "execution",
  NOTIFICATION_QUEUED: "execution",
  OUTCOME_FAILED: "verification",
  OUTCOME_VERIFIED_EXCEPTION_REMAINS: "verification",
  OUTCOME_VERIFIED_HUMAN_CLOSURE: "verification",
  OTHER_OPEN_CASES: "verification",
  SYMPTOMS_UPDATED: "intake",
  SNAPSHOT_SUPERSEDED: "investigation",
  MODEL_DEGRADED: "investigation",
  ACTION_INITIATED: "execution",
  EXECUTION_REQUESTED: "execution",
  EXECUTION_ACKNOWLEDGED: "execution",
  NOTIFICATION_RESULT: "execution",
  VERIFICATION_REQUESTED: "verification",
  OUTCOME_OBSERVED: "verification",
  OUTCOME_VERIFIED: "verification",
  CASE_RESOLVED: "resolution",
};
const STAGE_KIND: AuditKind[] = [
  "evidence",
  "evidence",
  "investigation",
  "investigation",
  "recommendation",
  "policy",
  "investigation",
  "verification",
];
function auditKind(row: ApiAuditEvent): AuditKind {
  if (row.event_type === "PIPELINE_STAGE" && row.stage)
    return STAGE_KIND[STAGE_INDEX[row.stage] ?? 2] ?? "investigation";
  const known = AUDIT_KIND[row.event_type];
  if (known) return known;
  if (/OUTCOME|VERIF/.test(row.event_type)) return "verification";
  if (/EXECUT|ACTION/.test(row.event_type)) return "execution";
  if (/APPROV|REVIEW|AUTH/.test(row.event_type)) return "policy";
  // Only an operator's own record is a decision.
  if (/DECISION/.test(row.event_type) && /OPERATOR/.test(row.actor))
    return "decision";
  return "investigation";
}
/** The role is read from the recorded actor, never guessed from the kind of event. */
function actorRole(row: ApiAuditEvent): InvestigationStageEvent["actorRole"] {
  const actor = row.actor.toUpperCase();
  if (actor.includes("OPERATOR")) return "operator";
  if (actor.includes("AUTHORITY-POLICY")) return "policy";
  if (actor.includes("OUTCOME-VERIFIER")) return "verifier";
  if (actor.includes("REVIEWER")) return "reviewer";
  if (actor.includes("INVESTIGATOR")) return "investigator";
  // Workers record model-backed stages with the model's name; the review stage is the reviewer's.
  if (row.model) return row.stage === "review" ? "reviewer" : "investigator";
  return "system";
}
export function auditEvent(row: ApiAuditEvent): InvestigationStageEvent {
  const kind = auditKind(row);
  const stage = row.stage ? STAGE_INDEX[row.stage] : undefined;
  return {
    id: row.id,
    // Events without a case (replayed observations) keep their shipment identity.
    caseId: row.case_id ?? "",
    shipmentId: row.shipment_id,
    timestamp: row.timestamp,
    evidenceTimestamp: row.scenario_time ?? undefined,
    actorRole: actorRole(row),
    kind,
    title:
      row.event_type === "PIPELINE_STAGE"
        ? `${humanize(row.stage)} · ${humanize(row.stage_status) || "recorded"}`
        : `${humanize(row.event_type)}${row.decision ? ` · ${humanize(row.decision)}` : ""}`,
    detail:
      row.result ||
      (row.from_state || row.to_state
        ? `${humanize(row.from_state) || "—"} → ${humanize(row.to_state) || "—"}`
        : "No further detail was recorded for this event."),
    actor: `${row.actor}${row.model ? ` · ${row.model}` : ""}`,
    stage,
    simulated: false,
    eventType: row.event_type,
  };
}
export function decisionFromAudit(
  row: ApiAuditEvent,
  action: string,
): AuthorityDecision | null {
  const verdict = verdictOf(row.decision);
  if (row.event_type !== "OPERATOR_DECISION" || !verdict || !row.case_id)
    return null;
  return {
    caseId: row.case_id,
    action,
    verdict,
    actor: row.actor,
    timestamp: row.timestamp,
    reason: "",
  };
}

/** Facilities the backend located in the loaded evidence (never a fixture network). */
export function facilitiesOf(detail: ApiCaseDetail): Facility[] {
  return (detail.evidence?.nodes ?? [])
    .filter((node) => FACILITY_KINDS.has(node.kind))
    .map((node) => {
      const lat = number(node.properties.lat);
      const lng = number(node.properties.lng);
      return lat === null || lng === null
        ? null
        : {
            id: node.id,
            name:
              text(node.properties.name).replace(/ synthetic facility$/, "") ||
              shortId(node.id),
            city: text(node.properties.city),
            type: node.kind.replace(/([a-z])([A-Z])/g, "$1 $2"),
            location: [lat, lng] as [number, number],
          };
    })
    .filter((item): item is Facility => item !== null);
}
