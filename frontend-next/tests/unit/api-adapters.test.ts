import { describe, expect, it } from "vitest";
import { applyNarration, narrationEvent } from "@/api/adapters";
import {
  GRAPH_LIMIT,
  applyDetail,
  applyPipeline,
  auditEvent,
  caseFromQueue,
  decisionFromAudit,
  pipelineView,
  shouldApplyPipeline,
  statusOf,
} from "@/api/adapters";
import { controls, displayId, operationalOf } from "@/domain/case-view";
import {
  CASE_A,
  SHIP_A,
  auditRows,
  detailA,
  detailB,
  exploreItems,
  pipelineEvents,
  queueRows,
  detailV3Route,
} from "../fixtures/backend";

describe("backend queue rows", () => {
  it("keeps case and shipment identities apart and never shows a cause without an accepted diagnosis", () => {
    const c = caseFromQueue(queueRows[0], undefined, exploreItems[0]);
    expect(c.id).toBe(CASE_A);
    expect(c.shipment.id).toBe(SHIP_A);
    expect(displayId(c)).toBe(SHIP_A);
    expect(c.shipment.origin).toBe("Riyadh");
    expect(c.shipment.destination).toBe("Dammam");
    // The monitor's observed symptom, not a diagnosis.
    expect(c.issue).toBe("Session end unreconciled +1");
    expect(c.backend?.diagnosisAvailable).toBe(false);
    expect(c.backend?.causeCodes).toEqual([]);
    expect(c.diagnosis).toMatch(/No accepted diagnosis/);
    // A queue row alone carries no evidence, recommendation or outcome.
    expect(c.evidence).toEqual([]);
    expect(c.recommendation.available).toBe(false);
    expect(c.outcome).toBeUndefined();
    expect(operationalOf(c)[0]).toBe("UNRECONCILED_CUSTODY");
  });

  it("maps every backend workflow state without inventing a resolution", () => {
    expect(statusOf("OPEN")).toBe("queued");
    expect(statusOf("REOPENED")).toBe("queued");
    expect(statusOf("INVESTIGATING")).toBe("investigating");
    expect(statusOf("AWAITING_APPROVAL")).toBe("human_review");
    expect(statusOf("HUMAN_REVIEW")).toBe("human_review");
    expect(statusOf("ACTION_INITIATED")).toBe("executing");
    expect(statusOf("AWAITING_OUTCOME")).toBe("verifying");
    expect(statusOf("ESCALATED")).toBe("escalated");
    expect(statusOf("RESOLVED")).toBe("resolved");
    // An unknown state is shown as queued, never as resolved.
    expect(statusOf("SOMETHING_NEW")).toBe("queued");
    const unknownPriority = caseFromQueue(queueRows[2]);
    expect(unknownPriority.priority).toBe("unknown");
    expect(controls(unknownPriority).investigate).toBe(true);
    expect(controls(unknownPriority).approve).toBe(false);
  });
});

describe("backend case detail", () => {
  const base = caseFromQueue(queueRows[0], undefined, exploreItems[0]);
  const c = applyDetail(base, detailA());

  it("keeps vehicle GPS apart from parcel custody on the map", () => {
    const custody = c.evidence.filter((e) => e.kind === "custody");
    const gps = c.evidence.filter((e) => e.kind === "gps");
    const attempts = c.evidence.filter((e) => e.kind === "delivery");
    expect(custody).toHaveLength(2);
    expect(custody.every((e) => e.confidence === "confirmed")).toBe(true);
    // Vehicle telemetry is bounded and is never a confirmed parcel observation.
    expect(gps).toHaveLength(9);
    expect(gps.every((e) => e.confidence === "vehicle_only")).toBe(true);
    // A recorded attempt is not proof of delivery.
    expect(attempts).toHaveLength(1);
    expect(attempts[0].confidence).toBe("missing");
    expect(attempts[0].detail).toMatch(/not proof of delivery/);
    // The last confirmed custody is the depot, not the vehicle's later positions.
    const last = c.evidence
      .filter((e) => e.confidence === "confirmed" && e.kind !== "gps")
      .at(-1);
    expect(last?.facility).toBe("SYN-DEPOT-DMM-01");
    expect(c.route.expected).toHaveLength(2);
    expect(c.route.vehicle).toHaveLength(9);
  });

  it("draws a bounded graph of real nodes and only real relationships", () => {
    expect(c.nodes.length).toBeLessThanOrEqual(GRAPH_LIMIT);
    expect(c.backend?.graphTotals?.nodes).toBeGreaterThan(GRAPH_LIMIT);
    const kinds = new Set(c.nodes.map((n) => n.kind));
    for (const kind of ["shipment", "package", "facility", "vehicle", "driver", "contractor", "observation", "recommendation"])
      expect(kinds.has(kind as never), kind).toBe(true);
    // Cited evidence survives the bound.
    expect(c.nodes.some((n) => n.id === `${SHIP_A}-CUST-02-01`)).toBe(true);
    // Plan bookkeeping is not drawn, so its edge is not either; nothing is synthesised.
    const ids = new Set(c.nodes.map((n) => n.id));
    expect(c.relationships.map((r) => r.id).sort()).toEqual([
      "SYN-EDGE-1",
      "SYN-EDGE-2",
      "SYN-EDGE-3",
    ]);
    expect(c.relationships.every((r) => ids.has(r.source) && ids.has(r.target))).toBe(true);
  });

  it("shows the accepted diagnosis, the recorded stages and what the backend allows", () => {
    expect(c.diagnosis).toMatch(/confirmed loaded/);
    expect(c.issue).toBe("Unreconciled custody");
    expect(c.summary).toMatch(/confirmed loaded/);
    expect(c.run?.stage).toBe(5);
    expect(c.backend?.stageDetail[5]).toMatch(/Reviewer verdict: accept/);
    expect(c.backend?.stageEvidence[2]).toEqual([`${SHIP_A}-CUST-02-01`]);
    expect(c.recommendation.title).toBe("Request depot reconciliation scan");
    expect(c.recommendation.authority).toBe("operator");
    expect(controls(c)).toEqual({
      investigate: false,
      approve: true,
      reject: true,
      escalate: true,
      verify: false,
      humanOutcome: true,
    });
    expect(c.shipment.weight).toBe(2.23);
    expect(c.execution).toBeUndefined();
    expect(c.outcome).toBeUndefined();
  });

  it("does not offer approval the backend did not grant, and explains why", () => {
    const refused = applyDetail(
      base,
      detailA({
        workflow_state: "HUMAN_REVIEW",
        recommendation: {
          action_en: "Reroute to the confirmed destination",
          risk_class: "HUMAN_REVIEW",
          approvable: false,
          approval_rule: "AUTH-21-human-investigation-required",
          approval_reason: "Only evidence-gathering requests may be approved on a human-investigation case.",
        },
      }),
    );
    expect(controls(refused).approve).toBe(false);
    expect(refused.backend?.approvalReason).toMatch(/evidence-gathering/);
    expect(refused.status).toBe("human_review");
  });

  it("treats a receipt, an unverified outcome and a verified outcome as three different things", () => {
    const executed = applyDetail(
      base,
      detailA({
        workflow_state: "AWAITING_OUTCOME",
        executions: [
          { receipt_ref: "SYN-RCPT-9", action_type: "REQUEST_DEPOT_RECONCILIATION", status: "ACKNOWLEDGED", current_cycle: true },
        ],
        outcome: { outcome_id: "SYN-OUT-9", verification_status: "PENDING", success: null, current_cycle: true },
      }),
    );
    expect(executed.status).toBe("verifying");
    expect(executed.execution?.detail).toMatch(/A receipt is not an outcome/);
    // An outcome the verifier has not confirmed is not shown as an outcome.
    expect(executed.outcome).toBeUndefined();
    expect(controls(executed).verify).toBe(true);

    const earlier = applyDetail(
      base,
      detailA({
        outcome: { outcome_id: "SYN-OUT-1", verification_status: "VERIFIED", success: true, current_cycle: false },
      }),
    );
    // An earlier cycle's outcome is history, not the reason the case is where it is.
    expect(earlier.outcome).toBeUndefined();

    const partial = applyDetail(
      base,
      detailA({
        workflow_state: "HUMAN_REVIEW",
        outcome: { verification_status: "VERIFIED", success: true, exception_cleared: false, remaining_symptoms: ["SESSION_END_UNRECONCILED"], current_cycle: true },
      }),
    );
    // A verified partial effect is not a resolution.
    expect(partial.outcome?.successful).toBe(false);
    expect(partial.status).not.toBe("resolved");

    const resolved = applyDetail(caseFromQueue(queueRows[1]), detailB());
    expect(resolved.status).toBe("resolved");
    expect(resolved.outcome?.successful).toBe(true);
    expect(resolved.run?.stage).toBe(7);
    expect(controls(resolved)).toEqual({ investigate: false, approve: false, reject: false, escalate: false, verify: false, humanOutcome: false });
  });

  it("serves the investigator's hypotheses with their evidence, and rule checks as labelled signals", () => {
    const found = c.backend!.investigation!;
    expect(found.accepted).toBe(true);
    expect(found.primaryCause).toBe("UNRECONCILED_CUSTODY");
    expect(found.toolCalls).toBe(6);
    expect(found.requiresPhysicalCheck).toBe(true);
    expect(found.hypotheses.map((h) => [h.cause, h.status])).toEqual([
      ["UNRECONCILED_CUSTODY", "supported"],
      ["DELAYED_SYNC", "refuted"],
    ]);
    expect(found.hypotheses[0].supporting).toEqual([`${SHIP_A}-CUST-02-01`]);
    expect(found.missingEvidence).toEqual(["depot reconciliation"]);
    // Rule checks are kept apart from the diagnosis and never become the case's cause.
    expect(c.backend!.ruleSignals?.signals[0].code).toBe("MISSED_MILESTONE");
    expect(c.issue).toBe("Unreconciled custody");
    expect(c.backend!.causeCodes).not.toContain("MISSED_MILESTONE");
  });

  it("lists the investigation as the run record has it: queries, budget, reviews, authority", () => {
    const log = c.backend!.investigationLog!;
    expect(log.modelCallsUsed).toBe(6);
    expect(log.modelCallCap).toBe(12);
    expect(log.steps.map((step) => step.tool)).toEqual(["custody_chain", "same_device_activity", "facility_window"]);
    expect(log.steps[0].purpose).toBe("Trace who last held the parcel");
    // Records of other shipments are counted as cross-shipment evidence.
    expect(log.steps[1].beyondShipment).toBe(2);
    expect(log.steps[0].beyondShipment).toBe(0);
    // A failed query is a failure, never an absence of evidence.
    expect(log.steps[2].failure).toBe("query_failed");
    expect(log.reviews[0]).toMatchObject({ verdict: "ACCEPT", byModel: true, unaddressedContradictions: ["The failed attempt is not explained."] });
    expect(log.citations).toEqual({ cited: 2, valid: 2 });
    expect(log.failedChecks).toEqual(["Alternative explanation recorded"]);
    expect(c.backend!.authority).toMatchObject({ riskClass: "APPROVAL_REQUIRED", ruleId: "AUTH-11-approval-required" });
    // A live tool-call event reads as the investigator's own query.
    expect(
      pipelineView([{ sequence: 1, stage: "classify", status: "RUNNING", output: { kind: "tool_call", tool: "custody_chain", purpose: "Trace who last held the parcel" } }]).stageDetail[2],
    ).toBe("Investigator queried custody chain: Trace who last held the parcel");
  });

  it("does not present an unacknowledged execution as carried out", () => {
    const sent = applyDetail(
      base,
      detailA({
        workflow_state: "HUMAN_REVIEW",
        executions: [{ receipt_ref: "no_adapter:SYN-EXEC-1", action_type: "REQUEST_RESCAN", status: "NOT_ACKNOWLEDGED", authority: "AUTO_POLICY", current_cycle: true }],
      }),
    );
    expect(sent.execution?.successful).toBe(false);
    expect(sent.execution?.detail).toMatch(/nothing was carried out/);
    // The three end states of an authorized action stay distinct.
    const answered = applyDetail(base, detailA({ workflow_state: "HUMAN_REVIEW", outcome: { verification_status: "VERIFIED", success: false, outcome_type: "parcel_not_found", exception_cleared: false, reason: "The facility did not find the parcel.", evidence_ids: ["x"], current_cycle: true } }));
    expect(answered.backend?.verification?.result).toBe("failed");
    const silent = applyDetail(base, detailA({ workflow_state: "HUMAN_REVIEW", outcome: { verification_status: "VERIFIED", success: false, outcome_type: "no_confirming_evidence", exception_cleared: false, reason: "No causally relevant confirming evidence arrived before the action deadline.", evidence_ids: [], current_cycle: true } }));
    expect(silent.backend?.verification?.result).toBe("unanswered");
    // No conclusion within the turn budget is its own state, not an invalid model reply.
    const seed = detailA();
    const spent = applyDetail(base, detailA({ workflow_state: "HUMAN_REVIEW", run: { ...seed.run!, result: { ...seed.run!.result!, mode: "turn_budget_exhausted", degraded: [{ role: "investigator", kind: "turn_budget_exhausted", error: "turn budget exhausted without a valid conclusion" }], latency: { total_seconds: 90.9, model: { turns: [{ role: "investigator", invalid_kind: "empty_reply" }] } } } } }));
    expect(spent.backend?.investigationLog?.degradedKinds).toEqual(["turn_budget_exhausted"]);
    expect(spent.backend?.investigationLog?.degraded[0]).toMatch(/no valid conclusion within its turn budget/);
    expect(spent.backend?.investigationLog?.degraded[0]).not.toMatch(/not valid, so nothing/);
    expect(spent.backend?.investigationLog?.rejectedReplies).toEqual(["empty reply"]);
    expect(spent.backend?.timing?.totalSeconds).toBe(90.9);
    // The backend's next step is carried as stated; nothing is derived in the browser.
    const held = applyDetail(base, detailA({ workflow_state: "HUMAN_REVIEW", next_step: { code: "INVESTIGATE_AND_RECORD_FINDING", actor: "operator", text_en: "A person must investigate.", text_ar: "", resolved: false, blocked_by: { rule_id: "AUTH-06-evidence-conflict", reason: "Evidence conflicts.", review_verdict: "ACCEPT" }, missing_evidence: ["a later scan"], attempted: [{ action_type: "REQUEST_DEVICE_SYNC", authority: "OPERATOR_APPROVAL", status: "ACKNOWLEDGED", verification_status: "VERIFIED", success: false, reason: "No confirming evidence." }] } }));
    expect(held.backend?.nextStep?.blockedBy?.ruleId).toBe("AUTH-06-evidence-conflict");
    expect(held.backend?.nextStep?.missingEvidence).toEqual(["a later scan"]);
    expect(held.backend?.nextStep?.attempted[0].success).toBe(false);
    expect(applyDetail(base, detailA()).backend?.nextStep).toBeNull();
    // Narration is carried as stored: labelled by who wrote it, placed on its step, appended once.
    const told = { id: "SYN-OPS-NARRATION-1", run_id: "R1", sequence: 2, stage: "review", phase: "review", kind: "canopus_summary" as const, title_en: "Review", text_en: "The reviewer asked for a revision.", evidence_ids: ["a", "SYN-CMP-1"], graph_node_ids: ["a"], model: "gpt-oss:120b", outcome_state: null };
    expect(narrationEvent(told)).toMatchObject({ stage: 5, kind: "canopus_summary", graphNodeIds: ["a"], model: "gpt-oss:120b" });
    expect(narrationEvent({ ...told, stage: "writeback", phase: "verification", kind: "system_event", outcome_state: "HUMAN_REVIEW" })).toMatchObject({ stage: 7, outcomeState: "HUMAN_REVIEW" });
    const empty = applyDetail(base, detailA());
    expect(empty.backend?.narration?.events).toEqual([]);
    const once = applyNarration(empty, told);
    expect(once.backend?.narration?.events).toHaveLength(1);
    expect(applyNarration(once, told)).toBe(once);
    const earlier = applyNarration(once, { ...told, id: "SYN-OPS-NARRATION-0", sequence: 1, stage: "extract", kind: "system_event" });
    expect(earlier.backend?.narration?.events.map((event) => event.sequence)).toEqual([1, 2]);
    // Evidence that moved during the run is not worded as a model failure.
    const moved = applyDetail(base, detailA({ workflow_state: "HUMAN_REVIEW", run: { ...seed.run!, result: { ...seed.run!.result!, degraded: [{ role: "snapshot", error: "evidence changed during investigation" }] } } }));
    expect(moved.backend?.investigationLog?.degradedKinds).toEqual(["snapshot_changed"]);
    expect(moved.backend?.investigationLog?.degraded[0]).toMatch(/superseded snapshot/);
    expect(sent.backend?.verification).toBeUndefined();
    expect(sent.outcome).toBeUndefined();
    expect(controls(sent).humanOutcome).toBe(true);
  });

  it("labels findings the reviewer did not accept and never promotes them to the diagnosis", () => {
    const refused = applyDetail(
      base,
      detailA({
        workflow_state: "HUMAN_REVIEW",
        diagnosis: {
          ...detailA().diagnosis!,
          available: false,
          reason: "review_not_accepted",
          summary: null,
          primary_cause: null,
          hypotheses: [],
          unaccepted_investigation: {
            primary_cause: "POSSIBLE_MISDELIVERY",
            summary: "The parcel was handed to the wrong person.",
            confidence: "low",
            hypotheses: [{ cause: "POSSIBLE_MISDELIVERY", status: "uncertain" }],
            missing_evidence: ["recipient statement"],
          },
        },
      }),
    );
    expect(refused.backend!.investigation).toMatchObject({
      accepted: false,
      primaryCause: "POSSIBLE_MISDELIVERY",
    });
    // The case itself is still described by what the monitor observed.
    expect(refused.issue).toBe("Session end unreconciled +1");
    expect(refused.diagnosis).toMatch(/did not accept/);
    expect(refused.diagnosis).not.toMatch(/wrong person/);
    expect(refused.summary).not.toMatch(/wrong person/);
  });

  it("keeps real citations inside the graph bound even when collection stages list everything", () => {
    const all = detailA().evidence.nodes.map((node) => node.id);
    const crowded = applyDetail(
      base,
      detailA({
        pipeline: {
          ...detailA().pipeline!,
          events: [
            // As the real backend records them: extract and retrieve list every record read.
            { sequence: 1, stage: "extract", status: "COMPLETED", output: { evidence_ids: all } },
            { sequence: 2, stage: "retrieve", status: "COMPLETED", output: { evidence_ids: all, nodes: all.length } },
            { sequence: 3, stage: "classify", status: "COMPLETED", output: { evidence_ids: [`${SHIP_A}-SCAN-77`] } },
          ],
        },
        rule_signals: {
          kind: "rule_signals",
          is_diagnosis: false,
          as_of: "2026-09-03T14:00:00+00:00",
          signals: [{ code: "MISSED_MILESTONE", evidence_ids: [`${SHIP_A}-SCAN-78`] }],
        },
      }),
    );
    const ids = new Set(crowded.nodes.map((n) => n.id));
    expect(ids.size).toBe(GRAPH_LIMIT);
    for (const id of [`${SHIP_A}-SCAN-77`, `${SHIP_A}-SCAN-78`, `${SHIP_A}-CUST-02-01`])
      expect(ids.has(id), id).toBe(true);
  });

  it("marks a queued re-investigation and never shows the superseded run as current", () => {
    const requeued = applyDetail(
      base,
      detailA({
        workflow_state: "REOPENED",
        run: null,
        previous_run: { entity_id: "SYN-RUN-1", superseded: true },
        pipeline: { events: [], status: "QUEUED" },
        recommendation: null,
        review: null,
        diagnosis: { ...detailA().diagnosis!, available: false, reason: "reinvestigation_pending", summary: null, primary_cause: null, hypotheses: [] },
      }),
    );
    expect(requeued.status).toBe("queued");
    expect(requeued.run).toBeUndefined();
    expect(requeued.backend?.supersededRunId).toBe("SYN-RUN-1");
    expect(requeued.backend?.stageDetail).toEqual({});
    expect(requeued.diagnosis).toMatch(/earlier run is superseded/);
    expect(requeued.recommendation.available).toBe(false);
    expect(controls(requeued).investigate).toBe(true);
  });

  it("shows an absent diagnosis as absent, with the backend's reason", () => {
    const pending = applyDetail(
      base,
      detailA({
        diagnosis: { ...detailA().diagnosis!, available: false, reason: "review_not_accepted", summary: "Loss in transit." },
      }),
    );
    expect(pending.diagnosis).toMatch(/did not accept/);
    expect(pending.diagnosis).not.toMatch(/Loss in transit/);
    expect(pending.backend?.diagnosisReason).toBe("review_not_accepted");
  });

  it("keeps loaded evidence across a poll of the same version and drops the approval on a newer one", () => {
    const same = caseFromQueue(queueRows[0], c, exploreItems[0]);
    expect(same.backend?.detailLoaded).toBe(true);
    expect(same.nodes).toBe(c.nodes);
    expect(controls(same).approve).toBe(true);
    const newer = caseFromQueue({ ...queueRows[0], state_version: 8 }, c, exploreItems[0]);
    expect(newer.backend?.detailLoaded).toBe(false);
    // Approval eligibility is only known from the reloaded detail.
    expect(controls(newer).approve).toBe(false);
  });
});

describe("V3 route evidence and pipeline fencing", () => {
  it("requires evidence ids for GPS selection and chronology from observations", () => {
    const base = caseFromQueue({
      case_id: detailV3Route().case_id,
      shipment_id: detailV3Route().shipment_id,
      issue_summary: "",
      priority: "low",
      workflow_state: "OPEN",
      state_version: 1,
    });
    const c = applyDetail(base, detailV3Route());
    expect(c.evidence.some((e) => e.id.startsWith("gps@"))).toBe(false);
    expect(c.evidence.filter((e) => e.kind === "gps").length).toBeGreaterThan(0);
    expect(c.backend?.routeEvidence?.firstObservedAt).toBe(
      "2026-09-14T11:04:13+00:00",
    );
    expect(c.route.vehicleSegments.length).toBeGreaterThan(1);
  });

  it("ignores stale pipeline events but accepts a new run", () => {
    const base = caseFromQueue({
      case_id: "SYN-X",
      shipment_id: "SYN-S",
      issue_summary: "",
      priority: "low",
      workflow_state: "INVESTIGATING",
      state_version: 2,
    });
    const withRun = applyPipeline(base, {
      workflow_state: "INVESTIGATING",
      state_version: 2,
      run_id: "SYN-RUN-2",
      status: "RUNNING",
      events: [],
    });
    expect(
      shouldApplyPipeline(withRun, {
        workflow_state: "INVESTIGATING",
        state_version: 2,
        run_id: "SYN-RUN-1",
        status: "RUNNING",
        events: [],
      }),
    ).toBe(false);
    expect(
      shouldApplyPipeline(withRun, {
        workflow_state: "INVESTIGATING",
        state_version: 3,
        run_id: "SYN-RUN-3",
        status: "RUNNING",
        events: [],
        previous_run_id: "SYN-RUN-2",
      }),
    ).toBe(true);
  });
});

describe("recorded pipeline and audit events", () => {
  it("maps backend stages onto the rail and follows a live frame", () => {
    const view = pipelineView(pipelineEvents.slice(0, 3));
    expect(view.stage).toBe(2);
    expect(view.stageDetail[1]).toMatch(/41 nodes, 77 relationships/);
    // An invalid reply being asked again is a live state with its elapsed time, then it ends.
    const repair = { sequence: 9, stage: "classify", status: "RETRYING", elapsed_seconds: 41.2, output: { kind: "invalid_output_repair", role: "investigator", attempt: 1, message: "model reply invalid, retrying" } };
    const live = pipelineView([repair]);
    expect(live.repairing).toBe("investigator");
    expect(live.stageDetail[2]).toMatch(/Model reply invalid, retrying \(investigator, attempt 1\)/);
    expect(live.stageElapsed[2]).toBe(41.2);
    expect(
      pipelineView([{ sequence: 12, stage: "classify", status: "RUNNING", output: { kind: "forced_final_turn", message: "turn budget exhausted; the investigator is asked once to conclude from the evidence already retrieved" } }]).stageDetail[2],
    ).toMatch(/asked once to conclude/);
    expect(pipelineView([repair, { sequence: 10, stage: "classify", status: "COMPLETED", elapsed_seconds: 55, output: {} }]).repairing).toBeNull();
    const base = caseFromQueue(queueRows[2]);
    const running = applyPipeline(base, {
      workflow_state: "INVESTIGATING",
      state_version: 2,
      run_id: "SYN-RUN-2",
      status: "RUNNING",
      events: pipelineEvents.slice(0, 2),
    });
    expect(running.status).toBe("investigating");
    expect(running.run?.stage).toBe(1);
    expect(controls(running).investigate).toBe(false);
    const queued = applyPipeline(running, {
      workflow_state: "OPEN",
      state_version: 3,
      run_id: null,
      status: "QUEUED",
      events: [],
    });
    // Queued again: the earlier run's stages are not the current pipeline.
    expect(queued.run).toBeUndefined();
    expect(queued.backend?.stageDetail).toEqual({});
  });

  it("presents audit records as backend records with both clocks", () => {
    const stage = auditEvent(auditRows[1]);
    expect(stage.simulated).toBe(false);
    expect(stage.kind).toBe("policy");
    expect(stage.stage).toBe(5);
    expect(stage.timestamp).toBe("2026-10-09T10:00:06+00:00");
    expect(stage.evidenceTimestamp).toBe("2026-09-03T13:00:00+00:00");
    expect(stage.actor).toMatch(/gpt-oss:120b/);
    expect(auditEvent(auditRows[3]).kind).toBe("verification");
    expect(auditEvent(auditRows[3]).actorRole).toBe("verifier");
    expect(stage.actorRole).toBe("reviewer");
    expect(auditEvent(auditRows[0]).actorRole).toBe("system");
    // The authority policy's record is the policy's, never an operator's decision.
    const authority = auditEvent({
      id: "SYN-AUD-9",
      timestamp: "2026-10-09T10:00:07+00:00",
      shipment_id: SHIP_A,
      case_id: CASE_A,
      event_type: "AUTHORITY_DECISION",
      actor: "SUHAIL-AUTHORITY-POLICY",
      result: '{"rule_id":"AUTH-09-no-review-accept","risk_class":"APPROVAL_REQUIRED"}',
    });
    expect(authority.kind).toBe("policy");
    expect(authority.actorRole).toBe("policy");
    expect(authority.title).toBe("Authority decision");
    expect(decisionFromAudit({ id: "x", timestamp: "", shipment_id: SHIP_A, case_id: CASE_A, event_type: "AUTHORITY_DECISION", actor: "SUHAIL-AUTHORITY-POLICY", decision: "approve" }, "")).toBeNull();
    const decision = decisionFromAudit(auditRows[2], "Request device synchronisation");
    expect(decision).toMatchObject({ verdict: "approved", actor: "SYN-OPERATOR-LOCAL", reason: "" });
    expect(decisionFromAudit(auditRows[0], "")).toBeNull();
  });
});
