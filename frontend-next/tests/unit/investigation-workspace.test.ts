import { describe, expect, it } from "vitest";
import { applyDetail, applyPipeline, caseFromQueue } from "@/api/adapters";
import {
  actionLabel,
  evidenceFocus,
  retrievalEvents,
  verifiedResolution,
  waitingLabel,
} from "@/domain/investigation-workspace";
import { detailA, detailV3Route, queueRows } from "../fixtures/backend";
import { actionCase, actionTraces } from "../fixtures/v32-actions";
import type { ApiPipelineEvent } from "@/api/contracts";

describe("V3.2 authoritative action projection", () => {
  it("reports failed detail enrichment instead of inventing continued progress", () => {
    const c = actionCase(0);
    c.backend = {
      ...c.backend!,
      actionStatus: null,
      detailLoaded: false,
      detailError: "unavailable",
    };
    expect(waitingLabel(c)[0]).toBe("Operational status unavailable");
  });
  it.each(
    actionTraces.map((trace, index) => ({
      name: trace.workflow,
      index,
      resolved: trace.action_status.resolution === "VERIFIED_RESOLVED",
    })),
  )("preserves the actual verifier result for $name", ({ index, resolved }) => {
    const c = actionCase(index);
    expect(verifiedResolution(c)).toBe(resolved);
    if (resolved) expect(c.outcome?.successful).toBe(true);
    else expect(verifiedResolution(c)).toBe(false);
  });
  it("keeps accepted work, a verified action with remaining uncertainty and genuine human decisions distinct", () => {
    const c = actionCase(
      actionTraces.findIndex((trace) => trace.workflow.includes("custody")),
    );
    expect(verifiedResolution(c)).toBe(false);
    expect(waitingLabel(c)[0]).toMatch(/exception remains/);
    const action = c.backend!.actionStatus!.actions[0];
    expect(
      actionLabel({
        ...action,
        state: "ACCEPTED",
        operational_label: "AWAITING_RESCAN",
      })[0],
    ).toBe("Awaiting independent rescan");
    c.backend!.actionStatus = {
      ...c.backend!.actionStatus!,
      human_decision_required: true,
      resolution: "HUMAN_DECISION_REQUIRED",
    };
    expect(waitingLabel(c)[0]).toBe("Human decision required");
  });
  it("labels rejected, failed, expired and refused tasks without calling them all delivery failures", () => {
    const action = actionCase(0).backend!.actionStatus!.actions[0];
    expect(
      actionLabel({
        ...action,
        state: "REJECTED",
        operational_label: "REJECTED",
      })[0],
    ).toMatch(/Task rejected/);
    expect(
      actionLabel({
        ...action,
        state: "FAILED",
        dispatch: "SENT",
        operational_label: "FAILED",
      })[0],
    ).toMatch(/Operational task failed/);
    expect(
      actionLabel({
        ...action,
        state: "EXPIRED",
        operational_label: "EXPIRED",
      })[0],
    ).toMatch(/Request expired/);
    expect(
      actionLabel({
        ...action,
        state: "REFUSED",
        operational_label: "REFUSED",
      })[0],
    ).toMatch(/Authorization refused/);
    expect(
      verifiedResolution({
        ...actionCase(0),
        status: "resolved",
        outcome: {
          id: "invalid",
          timestamp: "",
          successful: true,
          evidenceIds: [],
          detail: "",
        },
      }),
    ).toBe(false);
  });
});

describe("real retrieval to graph/map linkage", () => {
  it("does not show an earlier run's accepted findings, action or outcome as current", () => {
    const c = applyDetail(caseFromQueue(queueRows[0]), detailA());
    const current = applyPipeline(c, {
      workflow_state: "INVESTIGATING",
      state_version: c.backend!.stateVersion + 1,
      run_id: "SYN-NEW-INVESTIGATION",
      status: "RUNNING",
      events: [],
    });
    expect(current.backend?.diagnosisAvailable).toBe(false);
    expect(current.backend?.investigation).toBeUndefined();
    expect(current.backend?.review).toBeUndefined();
    expect(current.backend?.actionStatus).toBeNull();
    expect(current.backend?.narration?.events).toEqual([]);
    expect(current.outcome).toBeUndefined();
    expect(current.recommendation.available).toBe(false);
  });
  it("uses only recorded tool operations and keeps retrieved records separate from citations", () => {
    const detail = detailA();
    const id =
      detail.evidence.nodes.find((node) => node.kind === "Device")?.id ??
      detail.evidence.nodes[0].id;
    const call: ApiPipelineEvent = {
      sequence: 100,
      stage: "classify",
      status: "RUNNING",
      output: {
        kind: "tool_call",
        tool: "scans",
        evidence_ids: [id],
        computed_ids: ["SYN-COMPUTED-ONLY"],
      },
    };
    detail.diagnosis = undefined;
    detail.recommendation = null;
    detail.outcome = null;
    detail.rule_signals = undefined;
    detail.pipeline = { events: [call], status: "RUNNING" };
    const c = applyDetail(caseFromQueue(queueRows[0]), detail);
    expect(
      retrievalEvents([
        call,
        call,
        { ...call, sequence: 101, output: { kind: "forced_final_turn" } },
      ]),
    ).toEqual([call]);
    expect(c.nodes.find((node) => node.id === id)?.cited).not.toBe(true);
    expect(c.backend?.pipelineEvents?.[0].output?.tool).toBe("scans");
  });
  it("selects exact source nodes and real neighbours, with grounded map points only", () => {
    const c = applyDetail(caseFromQueue(queueRows[0]), detailV3Route());
    const located = c.evidence.find((point) =>
      c.nodes.some((node) => node.id === point.id),
    )!;
    expect(located).toBeDefined();
    const focus = evidenceFocus(c, [located.id]);
    expect(focus.graphIds).toContain(located.id);
    expect(focus.mapIds).toContain(located.id);
    expect(focus.missingIds).toEqual([]);
    expect(evidenceFocus(c, ["SYN-OTHER-SHIPMENT-RECORD"]).graphIds).toEqual(
      [],
    );
    expect(evidenceFocus(c, ["SYN-OTHER-SHIPMENT-RECORD"]).mapIds).toEqual([]);
    expect(evidenceFocus({ ...c, evidence: [] }, [located.id]).mapIds).toEqual(
      [],
    );
  });
  it("does not replace newer streamed retrieval history with an older detail of the same run", () => {
    const detail = detailA();
    const c = applyDetail(caseFromQueue(queueRows[0]), detail);
    const call: ApiPipelineEvent = {
      sequence: 900,
      stage: "classify",
      status: "RUNNING",
      output: { kind: "tool_call", tool: "custody_chain", evidence_ids: [] },
    };
    const streamed = applyPipeline(c, {
      workflow_state: detail.workflow_state,
      state_version: detail.state_version,
      run_id: c.run?.id ?? null,
      status: "RUNNING",
      events: [call],
    });
    expect(
      applyDetail(streamed, detail).backend?.pipelineEvents?.at(-1)?.sequence,
    ).toBe(900);
  });
});
