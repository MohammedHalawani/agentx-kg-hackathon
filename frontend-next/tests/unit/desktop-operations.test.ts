import { describe, expect, it } from "vitest";
import { caseFromQueue, workerConnectionOf } from "@/api/adapters";
import {
  operationsCollection,
  investigationAssignments,
  assignmentIsRunning,
  workerCapacity,
  tablePages,
} from "@/domain/desktop-operations";
import { queueRows, workerStatus, workerStatusDual } from "../fixtures/backend";

describe("Desktop case placement and actual worker assignments", () => {
  it.each([
    ["OPEN", "unassigned"],
    ["REOPENED", "unassigned"],
    ["INVESTIGATING", "assigned"],
    ["AWAITING_APPROVAL", "waiting"],
    ["AWAITING_OUTCOME", "waiting"],
    ["NEEDS_EVIDENCE", "waiting"],
    ["REJECTED", "waiting"],
    ["ESCALATED", "waiting"],
    ["RESOLVED", "closed"],
  ])("places %s using the backend lifecycle", (state, expected) => {
    const c = caseFromQueue(queueRows[0]);
    c.backend!.workflowState = state;
    // Deliberately inconsistent coarse label must never override source workflow.
    c.status = "queued";
    expect(operationsCollection(c)).toBe(expected);
  });
  it("excludes an OPEN row claimed between polls, and allows it after release", () => {
    const c = caseFromQueue(queueRows[0]);
    c.backend!.workflowState = "OPEN";
    const assignments = workerConnectionOf(workerStatusDual).activeCases;
    expect(operationsCollection(c, assignments)).toBe("assigned");
    expect(operationsCollection(c, [])).toBe("unassigned");
    c.backend!.workflowState = "RESOLVED";
    expect(operationsCollection(c, assignments)).toBe("closed");
  });
  it("honors an explicit empty V3 roster over a stale legacy id", () => {
    const source = structuredClone(workerStatusDual);
    source.worker.active_cases = [];
    source.worker.active_count = 0;
    source.worker.active_case_id = queueRows[0].case_id;
    const worker = workerConnectionOf(source);
    expect(investigationAssignments(worker, [])).toEqual([]);
    expect(workerCapacity(worker)).toBe(2);
  });
  it("does not invent identities or RUNNING stages for legacy assignments", () => {
    const source = structuredClone(workerStatus);
    source.worker.active_case_id = queueRows[0].case_id;
    const [claim] = investigationAssignments(workerConnectionOf(source), []);
    expect(claim.workerId).toBeNull();
    expect(claim.runStatus).toBe("UNKNOWN");
    expect(assignmentIsRunning(claim, true)).toBe(false);
    expect(workerCapacity(undefined)).toBeNull();
  });
  it("animates only online RUNNING investigations, independently of pool auto pause", () => {
    const claim = workerConnectionOf(workerStatusDual).activeCases[0];
    expect(assignmentIsRunning(claim, true)).toBe(true);
    expect(assignmentIsRunning(claim, false)).toBe(false);
    for (const runStatus of [
      "QUEUED",
      "PAUSED",
      "FAILED",
      "COMPLETED",
      "UNKNOWN",
    ])
      expect(assignmentIsRunning({ ...claim, runStatus }, true)).toBe(false);
    expect(
      assignmentIsRunning(
        { ...claim, workflowState: "AWAITING_OUTCOME" },
        true,
      ),
    ).toBe(false);
  });
  it("bounds pool capacity even when source counts disagree", () => {
    const worker = workerConnectionOf(workerStatusDual);
    expect(workerCapacity(worker)).toBe(0);
    expect(workerCapacity({ ...worker, concurrency: 8 })).toBe(6);
    expect(workerCapacity({ ...worker, activeCount: 20 })).toBe(0);
  });
});

describe("Loaded-row pagination", () => {
  it("shows actual first/current/last pages and ellipses without nonexistent page numbers", () => {
    expect(tablePages(0, 1)).toEqual([0]);
    expect(tablePages(0, 0)).toEqual([]);
    expect(tablePages(4, 10)).toEqual([0, "ellipsis", 3, 4, 5, "ellipsis", 9]);
    expect(tablePages(8, 10)).toEqual([0, "ellipsis", 7, 8, 9]);
  });
});
