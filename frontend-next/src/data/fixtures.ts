import {
  stages,
  type CaseQueue,
  type CaseStatus,
  type OperationalCase,
  type Priority,
  type Scenario,
  type InvestigationStageEvent,
} from "@/domain/types";

export const facilities = [
  {
    id: "riyadh",
    name: "Riyadh sorting hub",
    city: "Riyadh",
    type: "Sorting hub",
    location: [24.7136, 46.6753] as [number, number],
    capacity: "64%",
    shipments: 328,
  },
  {
    id: "dammam",
    name: "Dammam gateway",
    city: "Dammam",
    type: "Gateway",
    location: [26.4207, 50.0888] as [number, number],
    capacity: "72%",
    shipments: 186,
  },
  {
    id: "hofuf",
    name: "Al Ahsa warehouse",
    city: "Al Hofuf",
    type: "Warehouse",
    location: [25.3646, 49.5876] as [number, number],
    capacity: "48%",
    shipments: 94,
  },
  {
    id: "jeddah",
    name: "Jeddah gateway",
    city: "Jeddah",
    type: "Gateway",
    location: [21.5433, 39.1728] as [number, number],
    capacity: "61%",
    shipments: 242,
  },
  {
    id: "qassim",
    name: "Qassim delivery depot",
    city: "Buraydah",
    type: "Delivery depot",
    location: [26.3592, 43.9818] as [number, number],
    capacity: "39%",
    shipments: 76,
  },
];
export const scenarioInfo: Record<
  Scenario,
  {
    issue: string;
    summary: string;
    diagnosis: string;
    action: string;
    actionDetail: string;
    authority: "automatic" | "operator" | "evidence";
    expected: string;
  }
> = {
  barcode: {
    issue: "Barcode mismatch",
    summary:
      "A duplicate label at Dammam gateway interrupted the expected custody chain. The parcel remains inside the facility.",
    diagnosis:
      "The intake scanner read a legacy secondary barcode. Package weight and the sealed-container scan independently match this shipment.",
    action: "Reconcile the package barcode",
    actionDetail:
      "Link the verified container scan to the correct shipment record and request a fresh outbound custody scan. No address or recipient data will change.",
    authority: "automatic",
    expected:
      "A matching outbound scan independently confirms recovered custody.",
  },
  weight: {
    issue: "Weight discrepancy",
    summary:
      "Measured package weight differs by 1.3 kg between the origin hub and destination gateway.",
    diagnosis:
      "The destination scale recorded 3.7 kg against a 2.4 kg origin record. The seal is intact; a supervised reweigh is required.",
    action: "Request a supervised reweigh",
    actionDetail:
      "Hold the parcel at Dammam gateway and ask a facility supervisor to capture a calibrated weight and seal photograph.",
    authority: "operator",
    expected: "A supervised reweigh reconciles the package record.",
  },
  address: {
    issue: "Address conflict",
    summary:
      "The recipient address and sorting destination disagree. Delivery is paused until an operator confirms the correct destination.",
    diagnosis:
      "The national address points to Dammam, while the label routes to Al Ahsa. Neither the latest GPS point nor a delivery attempt validates an address change.",
    action: "Request recipient address confirmation",
    actionDetail:
      "Create a local simulated recipient confirmation task. Keep the parcel at the current confirmed facility until a verified address is supplied.",
    authority: "operator",
    expected:
      "Verified recipient confirmation permits the corrected delivery route.",
  },
  custody: {
    issue: "Missing custody observation",
    summary:
      "A vehicle departed Riyadh but the parcel handover scan is absent. Vehicle telemetry cannot confirm package custody.",
    diagnosis:
      "The expected departure handover is missing. GPS places the vehicle near Al Ahsa, but the last confirmed parcel observation remains at Riyadh.",
    action: "Request the missing handover scan",
    actionDetail:
      "Ask the Riyadh facility supervisor for a parcel-level outbound handover observation before any custody reconciliation.",
    authority: "evidence",
    expected: "A parcel-level scan closes the missing custody handover.",
  },
  contractor: {
    issue: "Contractor reconciliation",
    summary:
      "A parcel was observed at Al Ahsa after being assigned to a direct Riyadh–Dammam service. The contractor manifest needs review.",
    diagnosis:
      "Confirmed parcel custody at Al Ahsa contradicts the direct route assignment. The contractor vehicle changed manifests at the warehouse; operator authorization is required.",
    action: "Authorize custody reconciliation",
    actionDetail:
      "Reconcile the contractor manifest using the confirmed Al Ahsa parcel scan, then request a supervised transfer to Dammam gateway. This changes the recorded custody assignment.",
    authority: "operator",
    expected: "A fresh Dammam inbound scan verifies the supervised transfer.",
  },
  delivery: {
    issue: "Delivery confirmation dispute",
    summary:
      "The recipient disputes the delivery record. The submitted delivery proof is incomplete.",
    diagnosis:
      "The delivery attempt has a timestamp and vehicle position but no recipient signature or parcel-level proof. The shipment cannot be declared delivered.",
    action: "Request independent delivery proof",
    actionDetail:
      "Request a signed proof of delivery or independently confirmed return-to-depot scan. Do not mark this shipment delivered.",
    authority: "evidence",
    expected: "Independent delivery proof establishes the actual outcome.",
  },
  failed: {
    issue: "Failed automated intervention",
    summary:
      "A recovery instruction was executed, but the expected destination scan never appeared. The exception remains open.",
    diagnosis:
      "The contractor accepted the transfer instruction but produced no verified package scan. The automated intervention did not establish recovered custody.",
    action: "Escalate to the dispatch supervisor",
    actionDetail:
      "Route the failed recovery and all custody evidence to dispatch supervision for manual follow-up.",
    authority: "operator",
    expected: "A supervisor supplies a new confirmed parcel observation.",
  },
  normal: {
    issue: "Normal shipment journey",
    summary:
      "All planned custody observations match the expected route and the recipient delivery confirmation.",
    diagnosis:
      "The route, sealed-container handovers, and signed delivery observation agree. No unresolved contradictions remain.",
    action: "Verify the normal journey",
    actionDetail:
      "Compare independent parcel custody observations with the signed recipient delivery confirmation.",
    authority: "automatic",
    expected: "Independent delivery confirmation matches the full journey.",
  },
};

export function makeCase(
  id: string,
  scenario: Scenario,
  openedAt: string,
  status: CaseStatus = "queued",
  priority: Priority = "medium",
): OperationalCase {
  const info = scenarioInfo[scenario];
  const evidence = [
    {
      id: "origin",
      label: "Origin custody confirmed",
      kind: "custody" as const,
      location: [24.7136, 46.6753] as [number, number],
      time: "07:42",
      detail:
        "Parcel-level intake scan at Riyadh sorting hub. Sealed container C-208 and package weight recorded.",
      confidence: "confirmed" as const,
      facility: "Riyadh sorting hub",
    },
    {
      id: "handover",
      label:
        scenario === "custody"
          ? "Missing departure scan"
          : "Departure handover",
      kind: "scan" as const,
      location: [24.846, 46.807] as [number, number],
      time: "08:16",
      detail:
        scenario === "custody"
          ? "Expected outbound parcel handover has no matching scan. This position indicates the expected handover facility, not confirmed custody."
          : "Outbound package barcode and sealed container scanned by the origin facility supervisor.",
      confidence:
        scenario === "custody" ? ("missing" as const) : ("confirmed" as const),
      facility: "Riyadh outbound depot",
    },
    {
      id: "gps",
      label: "Contractor vehicle position",
      kind: "gps" as const,
      location: [25.197, 49.12] as [number, number],
      time: "09:34",
      detail:
        "GPS ping from vehicle SPL-2048. Confirms vehicle position only; this is not evidence of the parcel’s exact location.",
      confidence: "vehicle_only" as const,
      facility: "Route 40 · vehicle telemetry",
    },
    {
      id: "warehouse",
      label: "Al Ahsa parcel scan",
      kind: "custody" as const,
      location: [25.3646, 49.5876] as [number, number],
      time: "10:08",
      detail:
        "Inbound parcel scan at Al Ahsa warehouse. The package-level observation independently confirms custody here.",
      confidence: "confirmed" as const,
      facility: "Al Ahsa warehouse",
    },
    {
      id: "destination",
      label: "Dammam gateway",
      kind: "facility" as const,
      location: [26.4207, 50.0888] as [number, number],
      time: "11:20",
      detail:
        "Expected destination gateway. A planned route location is not a confirmed parcel observation.",
      confidence: "missing" as const,
      facility: "Dammam gateway",
    },
    {
      id: "delivery",
      label: "Delivery attempt",
      kind: "delivery" as const,
      location: [26.435, 50.105] as [number, number],
      time: "13:15",
      detail:
        scenario === "normal"
          ? "Recipient signature and parcel barcode independently confirm delivery."
          : "Planned delivery depot. Delivery remains unconfirmed; no valid recipient signature is available.",
      confidence:
        scenario === "normal" ? ("confirmed" as const) : ("missing" as const),
      facility: "Dammam delivery depot",
    },
  ];
  if (scenario === "custody") evidence.splice(3, 1);
  if (
    scenario === "barcode" ||
    scenario === "weight" ||
    scenario === "address"
  ) {
    evidence[3] = {
      ...evidence[3],
      location: [26.4207, 50.0888],
      label: "Dammam parcel scan",
      facility: "Dammam gateway",
      detail: `Confirmed inbound package scan at Dammam gateway. ${info.summary}`,
    };
  }
  const nodes = [
    {
      id: "shipment",
      label: id,
      kind: "shipment" as const,
      detail: info.summary,
    },
    {
      id: "package",
      label: `PKG-${id.slice(-5)}`,
      kind: "package" as const,
      detail: "2.4 kg · sealed parcel · Express domestic service",
    },
    {
      id: "vehicle",
      label: "SPL-2048",
      kind: "vehicle" as const,
      detail: "Contractor vehicle. Its GPS does not establish parcel custody.",
      evidenceId: "gps",
    },
    {
      id: "driver",
      label: "Omar Al-Harbi",
      kind: "driver" as const,
      detail: "Synthetic driver · assigned to contractor vehicle SPL-2048",
    },
    {
      id: "contractor",
      label: "Eastern Logistics",
      kind: "contractor" as const,
      detail:
        "Synthetic transport contractor · custody reconciliation requires approval",
    },
    {
      id: "facility-origin",
      label: "Riyadh hub",
      kind: "facility" as const,
      detail: "Origin sorting and sealed-container handover facility",
      evidenceId: "origin",
    },
    {
      id: "facility-destination",
      label: "Dammam gateway",
      kind: "facility" as const,
      detail: "Expected destination gateway",
      evidenceId: "destination",
    },
    ...evidence
      .filter((e) => e.kind !== "facility")
      .map((e) => ({
        id: e.id,
        label: e.label,
        kind: "observation" as const,
        detail: e.detail,
        evidenceId: e.id,
      })),
    {
      id: "recommendation",
      label: "Recovery action",
      kind: "recommendation" as const,
      detail: info.actionDetail,
    },
  ];
  const relationships = [
    {
      id: "contains",
      source: "shipment",
      target: "package",
      label: "CONTAINS",
      detail: "Shipment record identifies one sealed package.",
    },
    {
      id: "assigned",
      source: "package",
      target: "vehicle",
      label: "ASSIGNED_TO",
      detail:
        "Manifest assignment alone does not prove current parcel custody.",
    },
    {
      id: "drives",
      source: "driver",
      target: "vehicle",
      label: "DRIVES",
      detail: "Driver assignment recorded on the contractor manifest.",
    },
    {
      id: "operates",
      source: "contractor",
      target: "vehicle",
      label: "OPERATES",
      detail: "Eastern Logistics operates this vehicle.",
    },
    {
      id: "route",
      source: "facility-origin",
      target: "facility-destination",
      label: "EXPECTED_ROUTE",
      detail:
        "Direct Riyadh → Dammam route; Al Ahsa is not a planned handover.",
    },
    {
      id: "origin-place",
      source: "origin",
      target: "facility-origin",
      label: "OBSERVED_AT",
      detail:
        "Origin package-level scan identifies the Riyadh sorting facility.",
    },
    ...evidence
      .filter((e) => e.kind !== "facility")
      .map((e) => ({
        id: `e-${e.id}`,
        source: e.kind === "gps" ? "vehicle" : "package",
        target: e.id,
        label:
          e.confidence === "missing"
            ? "EXPECTED_SCAN"
            : e.kind === "gps"
              ? "GPS_POSITION"
              : "CUSTODY_SCAN",
        detail: e.detail,
      })),
    {
      id: "recommends",
      source: "shipment",
      target: "recommendation",
      label: "RECOMMENDED_ACTION",
      detail: info.actionDetail,
    },
  ];
  const result: OperationalCase = {
    id,
    scenario,
    openedAt,
    status,
    priority,
    issue: info.issue,
    summary: info.summary,
    diagnosis: info.diagnosis,
    shipment: {
      id,
      packageId: `PKG-${id.slice(-5)}`,
      origin: "Riyadh",
      destination: "Dammam",
      customer: "Domestic express",
      service: "Express · next day",
      weight: 2.4,
      promisedAt: "2026-10-09T16:00:00+03:00",
    },
    evidence,
    nodes,
    relationships,
    route: {
      expected: [
        [24.7136, 46.6753],
        [25.315, 47.691],
        [25.903, 49.127],
        [26.4207, 50.0888],
      ],
      actual: [
        [24.7136, 46.6753],
        [24.846, 46.807],
        [25.3646, 49.5876],
        [26.4207, 50.0888],
      ],
      vehicle: [
        [24.7136, 46.6753],
        [24.983, 47.84],
        [25.197, 49.12],
        [25.3646, 49.5876],
      ],
    },
    recommendation: {
      title: info.action,
      detail: info.actionDetail,
      authority: info.authority,
      risk: info.authority === "automatic" ? "low" : "medium",
      expectedOutcome: info.expected,
    },
  };
  if (
    ["human_review", "needs_evidence", "escalated", "resolved"].includes(status)
  )
    result.run = {
      id: `RUN-${id}`,
      stage: status === "resolved" ? 7 : 5,
      startedAt: openedAt,
      completedAt: openedAt,
    };
  if (status === "resolved") {
    const completed = new Date(Date.parse(openedAt) + 8 * 60000).toISOString();
    for (const e of result.evidence) {
      if (e.id === "destination") {
        e.confidence = "confirmed";
        e.detail =
          "A fresh parcel-level destination scan independently confirms the recovery outcome.";
      }
      const offset =
        {
          origin: -90,
          handover: -65,
          gps: -50,
          warehouse: -20,
          destination: 7,
          delivery: 8,
        }[e.id] ?? 0;
      e.time = new Date(
        Date.parse(openedAt) + offset * 60000,
      ).toLocaleTimeString("en-GB", {
        timeZone: "Asia/Riyadh",
        hour: "2-digit",
        minute: "2-digit",
      });
    }
    result.nodes = result.nodes.map((n) => {
      const e = result.evidence.find((e) => e.id === n.evidenceId);
      return e ? { ...n, detail: e.detail } : n;
    });
    result.run = { ...result.run!, completedAt: completed };
    result.execution = {
      id: `EX-${id}`,
      action: info.action,
      timestamp: new Date(Date.parse(openedAt) + 7 * 60000).toISOString(),
      successful: true,
      detail: "Local action completed.",
    };
    result.outcome = {
      id: `OUT-${id}`,
      timestamp: completed,
      successful: true,
      evidenceIds:
        scenario === "normal"
          ? ["origin", "delivery"]
          : ["origin", "destination"],
      detail: info.expected,
    };
    result.nodes.push({
      id: "outcome",
      label: "Verified outcome",
      kind: "outcome",
      detail: info.expected,
    });
    result.relationships.push({
      id: "verified",
      source: "recommendation",
      target: "outcome",
      label: "VERIFIED_BY",
      detail: info.expected,
    });
  }
  if (status === "escalated" && scenario === "failed") {
    result.run = { ...result.run!, stage: 7 };
    result.execution = {
      id: `EX-${id}`,
      action: info.action,
      timestamp: new Date(Date.parse(openedAt) + 7 * 60000).toISOString(),
      successful: false,
      detail:
        "Simulated recovery instruction timed out. No new parcel observation arrived.",
    };
    result.outcome = {
      id: `OUT-${id}`,
      timestamp: new Date(Date.parse(openedAt) + 8 * 60000).toISOString(),
      successful: false,
      evidenceIds: [],
      detail:
        "Verification failed: no independent parcel custody scan confirms recovery.",
    };
  }
  return result;
}
export function initialSnapshot(): CaseQueue {
  const cases = [
    makeCase(
      "SHP-10491",
      "address",
      "2026-10-09T10:42:00+03:00",
      "queued",
      "high",
    ),
    makeCase(
      "SHP-10490",
      "weight",
      "2026-10-09T10:36:00+03:00",
      "queued",
      "medium",
    ),
    makeCase(
      "SHP-10489",
      "custody",
      "2026-10-09T10:29:00+03:00",
      "queued",
      "high",
    ),
    makeCase(
      "SHP-10488",
      "delivery",
      "2026-10-09T10:18:00+03:00",
      "needs_evidence",
      "high",
    ),
    makeCase(
      "SHP-10487",
      "barcode",
      "2026-10-09T10:12:00+03:00",
      "queued",
      "low",
    ),
    makeCase(
      "SHP-10486",
      "failed",
      "2026-10-09T10:05:00+03:00",
      "escalated",
      "high",
    ),
    makeCase(
      "SHP-10482",
      "contractor",
      "2026-10-09T09:56:00+03:00",
      "human_review",
      "high",
    ),
    makeCase(
      "SHP-10479",
      "weight",
      "2026-10-09T09:40:00+03:00",
      "human_review",
      "medium",
    ),
    makeCase(
      "SHP-10471",
      "barcode",
      "2026-10-09T09:22:00+03:00",
      "queued",
      "low",
    ),
    makeCase(
      "SHP-10468",
      "barcode",
      "2026-10-09T09:08:00+03:00",
      "resolved",
      "low",
    ),
    makeCase(
      "SHP-10465",
      "normal",
      "2026-10-09T08:54:00+03:00",
      "resolved",
      "low",
    ),
    makeCase(
      "SHP-10461",
      "normal",
      "2026-10-09T08:41:00+03:00",
      "resolved",
      "low",
    ),
    reroute(
      makeCase(
        "SHP-10498",
        "custody",
        "2026-10-09T11:02:00+03:00",
        "queued",
        "high",
      ),
      "Riyadh",
      "Khobar",
    ),
    reroute(
      makeCase(
        "SHP-10497",
        "barcode",
        "2026-10-09T10:55:00+03:00",
        "queued",
        "low",
      ),
      "Riyadh",
      "Khobar",
    ),
    reroute(
      makeCase(
        "SHP-10453",
        "barcode",
        "2026-10-08T15:10:00+03:00",
        "resolved",
        "low",
      ),
      "Jeddah",
      "Riyadh",
    ),
    reroute(
      makeCase(
        "SHP-10442",
        "normal",
        "2026-10-02T10:10:00+03:00",
        "resolved",
        "low",
      ),
      "Dammam",
      "Riyadh",
    ),
    reroute(
      makeCase(
        "SHP-10433",
        "failed",
        "2026-09-27T09:20:00+03:00",
        "escalated",
        "high",
      ),
      "Dammam",
      "Riyadh",
    ),
    ...Array.from({ length: 12 }, (_, i) =>
      reroute(
        makeCase(
          `SHP-${10301 + i}`,
          i % 2 === 0 ? "normal" : "barcode",
          `2026-${i < 4 ? "10" : "09"}-${String(i < 4 ? 8 - i : 30 - (i - 4)).padStart(2, "0")}T08:00:00+03:00`,
          "resolved",
          "low",
        ),
        i % 2 === 0 ? "Dammam" : "Riyadh",
        i % 2 === 0 ? "Riyadh" : "Khobar",
      ),
    ),
  ];
  return {
    version: 1,
    cases,
    automatic: false,
    revision: 0,
    decisions: [],
    events: [
      ...seedCaseEvents(cases),
      {
        id: "seed-1",
        caseId: "SHP-10482",
        timestamp: "2026-10-09T10:36:00+03:00",
        kind: "policy",
        title: "Operator authorization required",
        detail:
          "Custody reassignment requires explicit operator approval under policy C-04.",
        actor: "Suhail · policy",
        stage: 5,
        simulated: true,
      },
      {
        id: "seed-2",
        caseId: "SHP-10488",
        timestamp: "2026-10-09T10:29:00+03:00",
        kind: "evidence",
        title: "Independent delivery proof requested",
        detail: "Vehicle GPS is insufficient to verify parcel delivery.",
        actor: "Suhail · evidence",
        stage: 2,
        simulated: true,
      },
      {
        id: "seed-3",
        caseId: "SHP-10486",
        timestamp: "2026-10-09T10:18:00+03:00",
        kind: "verification",
        title: "Recovery verification failed",
        detail:
          "Expected parcel scan is absent. Case escalated; no successful resolution recorded.",
        actor: "Suhail · verifier",
        stage: 7,
        simulated: true,
      },
      {
        id: "seed-4",
        caseId: "SHP-10468",
        timestamp: "2026-10-09T10:12:00+03:00",
        kind: "resolution",
        title: "Barcode recovery independently verified",
        detail: "Fresh destination package scan matches the corrected barcode.",
        actor: "Suhail · verifier",
        stage: 7,
        simulated: true,
      },
      {
        id: "seed-5",
        caseId: "SHP-10482",
        timestamp: "2026-10-09T10:08:00+03:00",
        kind: "evidence",
        title: "Custody contradiction detected",
        detail:
          "Al Ahsa package scan contradicts the direct Riyadh–Dammam manifest.",
        actor: "Suhail · custody",
        stage: 2,
        simulated: true,
      },
    ],
  };
}

function reroute(
  c: OperationalCase,
  origin: string,
  destination: string,
): OperationalCase {
  const locations: Record<string, [number, number]> = {
    Riyadh: [24.7136, 46.6753],
    Dammam: [26.4207, 50.0888],
    Khobar: [26.2794, 50.2083],
    Jeddah: [21.5433, 39.1728],
  };
  const start = locations[origin],
    end = locations[destination];
  const localize = (text: string) =>
    text.replace(/Riyadh|Dammam/g, (city) =>
      city === "Riyadh" ? origin : destination,
    );
  c.shipment = { ...c.shipment, origin, destination };
  c.summary = localize(c.summary);
  c.diagnosis = localize(c.diagnosis);
  c.recommendation = {
    ...c.recommendation,
    detail: localize(c.recommendation.detail),
    expectedOutcome: localize(c.recommendation.expectedOutcome),
  };
  if (c.outcome)
    c.outcome = { ...c.outcome, detail: localize(c.outcome.detail) };
  c.evidence = c.evidence.map((e) =>
    e.id === "origin"
      ? {
          ...e,
          location: start,
          facility: `${origin} sorting hub`,
          detail: `Confirmed parcel-level intake observation at ${origin} sorting hub.`,
        }
      : e.id === "handover"
        ? {
            ...e,
            location: [start[0] + 0.04, start[1] + 0.04],
            facility: `${origin} outbound depot`,
            detail: localize(e.detail),
          }
        : e.id === "gps"
          ? {
              ...e,
              location: [(start[0] + end[0]) / 2, (start[1] + end[1]) / 2],
              facility: `${origin} → ${destination} · vehicle telemetry`,
            }
          : e.id === "destination"
            ? {
                ...e,
                location: end,
                facility: `${destination} gateway`,
                label: `${destination} gateway`,
              }
            : e.id === "delivery"
              ? {
                  ...e,
                  location: [end[0] + 0.018, end[1] + 0.02],
                  facility: `${destination} delivery depot`,
                }
              : e.id === "warehouse" && c.status === "resolved"
                ? {
                    ...e,
                    location: end,
                    facility: `${destination} gateway`,
                    label: `${destination} parcel scan`,
                    detail: `Confirmed parcel-level scan at ${destination} gateway.`,
                  }
                : e,
  );
  c.nodes = c.nodes.map((n) =>
    n.id === "facility-origin"
      ? { ...n, label: `${origin} hub`, detail: localize(n.detail) }
      : n.id === "facility-destination"
        ? { ...n, label: `${destination} gateway`, detail: localize(n.detail) }
        : n.evidenceId
          ? {
              ...n,
              label:
                c.evidence.find((e) => e.id === n.evidenceId)?.label ?? n.label,
              detail:
                c.evidence.find((e) => e.id === n.evidenceId)?.detail ??
                n.detail,
            }
          : { ...n, detail: localize(n.detail) },
  );
  c.relationships = c.relationships.map((relationship) => ({
    ...relationship,
    detail: localize(relationship.detail),
  }));
  c.route = {
    expected: [start, end],
    actual: c.evidence
      .filter((e) => e.confidence === "confirmed")
      .map((e) => e.location),
    vehicle: [start, [(start[0] + end[0]) / 2, (start[1] + end[1]) / 2], end],
  };
  return c;
}

function seedCaseEvents(cases: OperationalCase[]): InvestigationStageEvent[] {
  return cases.flatMap((c) => {
    const start = Date.parse(c.openedAt);
    const count = c.status === "resolved" || c.outcome ? 8 : c.run ? 6 : 0;
    const records: InvestigationStageEvent[] = Array.from(
      { length: count },
      (_, i) => ({
        id: `fixture-${c.id}-stage-${i}`,
        caseId: c.id,
        runId: c.run?.id ?? `RUN-${c.id}`,
        timestamp: new Date(start + (i + 1) * 60000).toISOString(),
        evidenceTimestamp: new Date(start - 60000 + i * 45000).toISOString(),
        evidenceIds:
          i === 2
            ? ["origin", "handover"]
            : i === 7
              ? c.outcome?.evidenceIds
              : ["origin"],
        kind: stages[i].kind,
        title:
          i === 7 && c.outcome?.successful === false
            ? "Outcome verification failed"
            : stages[i].label,
        detail:
          i === 7 && c.outcome?.successful === false
            ? c.outcome.detail
            : i === 4
              ? c.diagnosis
              : i === 5
                ? c.recommendation.detail
                : stages[i].detail,
        actor:
          i === 5
            ? "Suhail · reviewer"
            : i === 7
              ? "Suhail · verifier"
              : "Suhail · investigator",
        actorRole: i === 5 ? "reviewer" : i === 7 ? "verifier" : "investigator",
        stage: i,
        simulated: true,
      }),
    );
    records.unshift({
      id: `fixture-${c.id}-intake`,
      caseId: c.id,
      timestamp: c.openedAt,
      evidenceTimestamp: new Date(start - 120000).toISOString(),
      kind: "intake",
      title: "Shipment exception recorded",
      detail: c.summary,
      actor: "Suhail · monitor",
      actorRole: "investigator",
      simulated: true,
    });
    if (c.status === "resolved")
      records.push({
        id: `fixture-${c.id}-resolved`,
        caseId: c.id,
        runId: c.run?.id,
        timestamp: new Date(start + 9 * 60000).toISOString(),
        evidenceTimestamp: new Date(start + 8 * 60000).toISOString(),
        evidenceIds: c.outcome?.evidenceIds,
        kind: "resolution",
        title: "Case independently verified and resolved",
        detail: c.outcome!.detail,
        actor: "Suhail · verifier",
        actorRole: "verifier",
        stage: 7,
        simulated: true,
      });
    return records;
  });
}
