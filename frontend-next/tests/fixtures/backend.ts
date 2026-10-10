/**
 * Test-only payloads in the backend's wire format (property names as the S5 dataset and
 * chat/operations/read_model.py serve them). They exist to exercise the adapters and the
 * service; the application never imports this file.
 */
import type {
  ApiAuditEvent,
  ApiCaseDetail,
  ApiExploreItem,
  ApiPage,
  ApiPipelineEvent,
  ApiQueueCase,
  ApiWorkerStatus,
} from "@/api/contracts";

export const CASE_A = "SYN-CASE-0001";
export const CASE_B = "SYN-CASE-0002";
export const CASE_C = "SYN-CASE-0003";
export const SHIP_A = "SYN-SHP-000101";

export function page<T>(items: T[], next: string | null = null): ApiPage<T> {
  return {
    items,
    filtered_total: items.length,
    next_cursor: next,
    previous_cursor: null,
    metadata: {
      as_of: "2026-09-03T14:00:00+00:00",
      synthetic: true,
      filter_choices: { city: ["Dammam", "Jeddah", "Riyadh"] },
    },
  };
}
export const queueRows: ApiQueueCase[] = [
  {
    case_id: CASE_A,
    shipment_id: SHIP_A,
    issue_summary:
      "Monitor detected an expected-vs-actual divergence in visible evidence; no accepted agent diagnosis.",
    summary_source: "monitor",
    diagnosis_available: false,
    city: "Dammam",
    category: null,
    cause_codes: [],
    symptom_codes: ["SESSION_END_UNRECONCILED", "MILESTONE_OVERDUE"],
    priority: "high",
    workflow_state: "AWAITING_APPROVAL",
    operational_status: "UNRECONCILED_CUSTODY",
    opened_at: "2026-09-03T09:00:00+00:00",
    state_version: 7,
    synthetic: true,
  },
  {
    case_id: CASE_B,
    shipment_id: "SYN-SHP-000102",
    issue_summary: "Buffered scans from one handheld arrived late.",
    summary_source: "agent_diagnosis",
    diagnosis_available: true,
    city: "Jeddah",
    category: "DELAYED_SYNC",
    cause_codes: ["DELAYED_SYNC"],
    symptom_codes: ["MILESTONE_OVERDUE"],
    priority: "medium",
    workflow_state: "RESOLVED",
    operational_status: "RESOLVED",
    opened_at: "2026-09-02T08:00:00+00:00",
    state_version: 12,
    synthetic: true,
  },
  {
    case_id: CASE_C,
    shipment_id: "SYN-SHP-000103",
    issue_summary:
      "Monitor detected an expected-vs-actual divergence in visible evidence; no accepted agent diagnosis.",
    summary_source: "monitor",
    diagnosis_available: false,
    city: "Riyadh",
    symptom_codes: ["RECIPIENT_REPORTED_NOT_RECEIVED"],
    priority: "unknown",
    workflow_state: "OPEN",
    operational_status: "DELIVERY_DISPUTE",
    opened_at: "2026-09-03T11:00:00+00:00",
    state_version: 1,
    synthetic: true,
  },
];
export const exploreItems: ApiExploreItem[] = [
  {
    shipment_id: SHIP_A,
    case_id: CASE_A,
    origin_city: "Riyadh",
    destination_city: "Dammam",
    destination: { lat: 26.445, lng: 50.112 },
    workflow_state: "AWAITING_APPROVAL",
  },
];
export const workerStatus: ApiWorkerStatus = {
  synthetic: true,
  as_of: "2026-09-03T14:00:00+00:00",
  database: "shipments-v2-demo-live",
  worker: {
    state: "paused",
    concurrency: 1,
    processed_count: 3,
    active_case_id: null,
    last_case_id: CASE_A,
  },
};

export const pipelineEvents: ApiPipelineEvent[] = [
  {
    sequence: 1,
    stage: "extract",
    status: "COMPLETED",
    recorded_at: "2026-10-09T10:00:01+00:00",
    evidence_as_of: "2026-09-03T13:00:00+00:00",
    output: { evidence_ids: [`${SHIP_A}-CUST-01-01`, `${SHIP_A}-CUST-02-01`] },
  },
  {
    sequence: 2,
    stage: "retrieve",
    status: "COMPLETED",
    output: { nodes: 41, relationships: 77 },
  },
  {
    sequence: 3,
    stage: "classify",
    status: "COMPLETED",
    output: {
      diagnoses: [
        {
          code: "UNRECONCILED_CUSTODY",
          summary_en: "The parcel was loaded but not reconciled at session end.",
        },
      ],
      evidence_ids: [`${SHIP_A}-CUST-02-01`],
    },
  },
  {
    sequence: 4,
    stage: "retrieve_context",
    status: "COMPLETED",
    output: { verified_precedents: 2 },
  },
  {
    sequence: 5,
    stage: "recommend",
    status: "COMPLETED",
    output: { proposal: { action_en: "Request depot reconciliation scan" } },
  },
  {
    sequence: 6,
    stage: "review",
    status: "COMPLETED",
    output: { verdict: "accept", feedback: "Evidence supports the proposal." },
  },
];

const node = (id: string, kind: string, properties: Record<string, unknown>) => ({
  id,
  kind,
  properties: { entity_id: id, ...properties },
});
/** A reviewed case awaiting an operator's approval, with located evidence. */
export function detailA(overrides: Partial<ApiCaseDetail> = {}): ApiCaseDetail {
  const gps = Array.from({ length: 9 }, (_, index) => ({
    lat: 26.3 + index * 0.01,
    lng: 50.0 + index * 0.01,
    evidence_id: `${SHIP_A}-GPS-${index}`,
    occurred_at: `2026-09-03T0${index}:10:00+00:00`,
    source: "vehicle_telemetry_only",
    vehicle_id: "SYN-VEH-LMV-DMM-0001",
  }));
  return {
    case_id: CASE_A,
    shipment_id: SHIP_A,
    workflow_state: "AWAITING_APPROVAL",
    state_version: 7,
    priority: "high",
    operational_status: "UNRECONCILED_CUSTODY",
    as_of: "2026-09-03T14:00:00+00:00",
    last_run_id: "SYN-RUN-1",
    synthetic: true,
    run: {
      entity_id: "SYN-RUN-1",
      recorded_at: "2026-10-09T10:00:00+00:00",
      mode: "agent_tool_loop",
      status: "REVIEWED",
    },
    evidence: {
      nodes: [
        node(SHIP_A, "Shipment", {
          origin_city: "Riyadh",
          destination_city: "Dammam",
          tracking_id: "SYN-TRACK-000101",
          flow_type: "B2C",
        }),
        node(`${SHIP_A}-PKG-01`, "Package", { weight_kg: 2.23 }),
        node("SYN-BRANCH-RUH-01", "Branch", {
          name: "SYN-BRANCH-RUH-01 synthetic facility",
          city: "Riyadh",
          lat: 24.71,
          lng: 46.67,
        }),
        node("SYN-DEPOT-DMM-01", "DeliveryDepot", {
          name: "SYN-DEPOT-DMM-01 synthetic facility",
          city: "Dammam",
          lat: 26.43,
          lng: 50.1,
        }),
        node("SYN-VEH-LMV-DMM-0001", "Vehicle", {
          ownership: "PRIVATE",
          vehicle_class: "CAR",
          provider_id: "SYN-PROV-3PL-01",
        }),
        node("SYN-DRV-LMV-DMM-0001", "Driver", { employment: "CONTRACTOR" }),
        node("SYN-PROV-3PL-01", "Provider", {
          name: "Synthetic contracted last-mile carrier",
          provider_type: "CONTRACTOR_3PL",
        }),
        node(`${SHIP_A}-CUST-01-01`, "CustodyEvent", {
          event_type: "RECEIVED",
          occurred_at: "2026-09-01T05:00:00+00:00",
          to_id: "SYN-BRANCH-RUH-01",
          source_quality: "CORROBORATED",
        }),
        node(`${SHIP_A}-CUST-02-01`, "CustodyEvent", {
          event_type: "LOADED",
          occurred_at: "2026-09-03T04:00:00+00:00",
          to_id: "SYN-DEPOT-DMM-01",
          source_quality: "CORROBORATED",
        }),
        node(`${SHIP_A}-ATT-01-1`, "DeliveryAttempt", {
          disposition: "FAILED",
          failed_reason: "RECIPIENT_UNAVAILABLE",
          occurred_at: "2026-09-03T08:00:00+00:00",
        }),
        ...gps.map((point) =>
          node(point.evidence_id, "GPSObservation", {
            occurred_at: point.occurred_at,
            position_scope: "VEHICLE_ONLY",
            vehicle_id: point.vehicle_id,
          }),
        ),
        // Plan and catalogue records the graph does not draw as entities.
        node(`${SHIP_A}-SEG-01`, "RouteSegment", { sequence: 1 }),
        node(`${SHIP_A}-EM-01`, "ExpectedMilestone", {}),
        ...Array.from({ length: 80 }, (_, index) =>
          node(`${SHIP_A}-SCAN-${index}`, "ScanEvent", {
            observation_type: "BARCODE_READ",
            occurred_at: `2026-09-02T00:${String(index % 60).padStart(2, "0")}:00+00:00`,
          }),
        ),
      ],
      edges: [
        {
          id: "SYN-EDGE-1",
          kind: "HAS_PACKAGE",
          start: SHIP_A,
          end: `${SHIP_A}-PKG-01`,
        },
        {
          id: "SYN-EDGE-2",
          kind: "HAS_CUSTODY_EVENT",
          start: `${SHIP_A}-PKG-01`,
          end: `${SHIP_A}-CUST-02-01`,
        },
        {
          id: "SYN-EDGE-3",
          kind: "TO_CUSTODIAN",
          start: `${SHIP_A}-CUST-02-01`,
          end: "SYN-DEPOT-DMM-01",
        },
        {
          id: "SYN-EDGE-4",
          kind: "CONTAINS",
          start: SHIP_A,
          end: `${SHIP_A}-SEG-01`,
        },
      ],
    },
    ledger_graph: {
      nodes: [
        node("SYN-REC-1", "OpsRecommendation", {
          action_en: "Request depot reconciliation scan",
        }),
      ],
      edges: [],
    },
    diagnosis: {
      available: true,
      reason: null,
      source: "agent_investigation",
      run_id: "SYN-RUN-1",
      as_of: "2026-09-03T13:00:00+00:00",
      investigated_at: "2026-10-09T10:00:00+00:00",
      primary_cause: "UNRECONCILED_CUSTODY",
      confidence: "medium",
      summary:
        "The parcel was confirmed loaded and has no return or delivery record after the session ended.",
      hypotheses: [
        {
          cause: "UNRECONCILED_CUSTODY",
          status: "supported",
          assessment: "Loaded at the depot; no return, delivery or reconciliation record follows.",
          supporting_evidence_ids: [`${SHIP_A}-CUST-02-01`],
        },
        {
          cause: "DELAYED_SYNC",
          status: "refuted",
          assessment: "Other parcels on the same device synchronised normally.",
          contradicting_evidence_ids: [`${SHIP_A}-SCAN-HIDDEN`],
        },
      ],
      missing_evidence: ["depot reconciliation"],
      requires_physical_check: true,
      tool_calls: 6,
      snapshot_superseded: false,
    },
    pipeline: {
      events: pipelineEvents,
      status: "REVIEWED",
      source: "recorded_stage_events",
      investigation_as_of: "2026-09-03T13:00:00+00:00",
      evidence_after_investigation: 0,
    },
    recommendation: {
      action_en: "Request depot reconciliation scan",
      summary_en: "Ask the depot to scan the parcel if it is on site.",
      evidence_ids: [`${SHIP_A}-CUST-02-01`],
      action_type: "REQUEST_DEPOT_RECONCILIATION",
      risk_class: "APPROVAL_REQUIRED",
      approvable: true,
      approval_rule: "AUTH-10",
      approval_reason: "A person may authorize this evidence-gathering request.",
    },
    review: {
      verdict: "accept",
      model_verdict: "ACCEPT",
      mode: "model_review",
      reason_code: "ACCEPTED",
      summary_en: "Accepted.",
    },
    rule_signals: {
      kind: "rule_signals",
      is_diagnosis: false,
      as_of: "2026-09-03T14:00:00+00:00",
      signals: [
        {
          code: "MISSED_MILESTONE",
          summary_en: "An expected milestone is overdue at the evidence cutoff.",
          evidence_ids: [`${SHIP_A}-EM-01`],
        },
      ],
    },
    outcome: null,
    decisions: [],
    executions: [],
    route_layers: {
      layers: {
        expected_route: [
          {
            segment_id: `${SHIP_A}-SEG-01`,
            sequence: 1,
            points: [
              { lat: 24.71, lng: 46.67, entity_id: "SYN-BRANCH-RUH-01" },
              { lat: 26.445, lng: 50.112, entity_id: `${SHIP_A}-ADDR-01` },
            ],
          },
        ],
        custody_points: [
          {
            lat: 24.71,
            lng: 46.67,
            entity_id: "SYN-BRANCH-RUH-01",
            evidence_id: `${SHIP_A}-CUST-01-01`,
            occurred_at: "2026-09-01T05:00:00+00:00",
            source: "corroborated_custody",
          },
          {
            lat: 26.43,
            lng: 50.1,
            entity_id: "SYN-DEPOT-DMM-01",
            evidence_id: `${SHIP_A}-CUST-02-01`,
            occurred_at: "2026-09-03T04:00:00+00:00",
            source: "corroborated_custody",
          },
        ],
        actual_route: [
          { lat: 24.71, lng: 46.67 },
          { lat: 26.43, lng: 50.1 },
        ],
        vehicle_path: gps,
        delivery_attempts: [
          {
            lat: 26.445,
            lng: 50.112,
            evidence_id: `${SHIP_A}-ATT-01-1`,
            occurred_at: "2026-09-03T08:00:00+00:00",
            source: "attempt_address_reference_not_vehicle_position",
            disposition: "FAILED",
          },
        ],
      },
    },
    ...overrides,
  };
}
/** A resolved case: the independent verifier confirmed the outcome. */
export function detailB(): ApiCaseDetail {
  return {
    ...detailA(),
    case_id: CASE_B,
    shipment_id: "SYN-SHP-000102",
    workflow_state: "RESOLVED",
    state_version: 12,
    operational_status: "RESOLVED",
    recommendation: {
      action_en: "Request device synchronisation",
      action_type: "REQUEST_DEVICE_SYNC",
      risk_class: "AUTO",
      approvable: false,
      approval_rule: "LIFECYCLE-not-awaiting-decision",
      approval_reason: "The case is RESOLVED, not awaiting a decision.",
    },
    executions: [
      {
        entity_id: "SYN-EXEC-1",
        receipt_ref: "SYN-RCPT-1",
        action_type: "REQUEST_DEVICE_SYNC",
        occurred_at: "2026-09-02T09:00:00+00:00",
        status: "ACKNOWLEDGED",
        authority: "AUTOMATIC_POLICY",
        current_cycle: true,
      },
    ],
    outcome: {
      outcome_id: "SYN-OUT-1",
      verification_status: "VERIFIED",
      success: true,
      exception_cleared: true,
      outcome_type: "BUFFERED_SCANS_ARRIVED",
      evidence_ids: ["SYN-SHP-000102-SCAN-9"],
      reason: "Buffered scans from the named device arrived after the request.",
      verified_at: "2026-09-02T10:00:00+00:00",
      current_cycle: true,
      invalidated: false,
    },
    decisions: [],
  };
}
export const auditRows: ApiAuditEvent[] = [
  {
    id: "SYN-AUD-1",
    timestamp: "2026-10-09T09:59:00+00:00",
    scenario_time: "2026-09-03T09:00:00+00:00",
    shipment_id: SHIP_A,
    case_id: CASE_A,
    event_type: "CASE_OPENED",
    actor: "SYN-RULE-WORKER",
    to_state: "OPEN",
  },
  {
    id: "SYN-AUD-2",
    timestamp: "2026-10-09T10:00:06+00:00",
    scenario_time: "2026-09-03T13:00:00+00:00",
    shipment_id: SHIP_A,
    case_id: CASE_A,
    event_type: "PIPELINE_STAGE",
    actor: "SYN-RULE-WORKER",
    model: "gpt-oss:120b",
    stage: "review",
    stage_status: "COMPLETED",
    result: "accept",
  },
  {
    id: "SYN-AUD-3",
    timestamp: "2026-10-09T10:05:00+00:00",
    scenario_time: "2026-09-03T13:00:00+00:00",
    shipment_id: "SYN-SHP-000102",
    case_id: CASE_B,
    event_type: "OPERATOR_DECISION",
    actor: "SYN-OPERATOR-LOCAL",
    decision: "approve",
    from_state: "AWAITING_APPROVAL",
    to_state: "AWAITING_OUTCOME",
  },
  {
    id: "SYN-AUD-4",
    timestamp: "2026-10-09T10:06:00+00:00",
    scenario_time: "2026-09-03T13:00:00+00:00",
    shipment_id: "SYN-SHP-000102",
    case_id: CASE_B,
    event_type: "OUTCOME_VERIFIED",
    actor: "SYN-VERIFIER",
    result: "Buffered scans from the named device arrived after the request.",
  },
];
export const session = {
  token: "test-token-0123456789",
  mode: "synthetic_local_operations",
  synthetic: true,
  actor_id: "SYN-OPERATOR-LOCAL",
  role: "operator",
  scope: ["operator_decision"],
  production_authority: false,
};
export const schema = {
  nodes: [
    { id: "n1", labels: ["Shipment"], caption: "Shipment" },
    { id: "n2", labels: ["Package"], caption: "Package" },
    { id: "n3", labels: ["CustodyEvent"], caption: "CustodyEvent" },
  ],
  relationships: [
    { id: "r1", type: "HAS_PACKAGE", from: "n1", to: "n2" },
    { id: "r2", type: "HAS_CUSTODY_EVENT", from: "n2", to: "n3" },
  ],
  synthetic: true,
};
