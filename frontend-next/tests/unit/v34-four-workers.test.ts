import { describe, expect, it } from "vitest";
import { workerConnectionOf } from "@/api/adapters";
import { investigationAssignments, workerCapacity } from "@/domain/desktop-operations";
import { workerStatusDual, workerStatusQuad } from "../fixtures/backend";

describe("V3.4 four workers and provider lanes", () => {
  it("maps four active claims, the lanes and the model calls exactly as reported", () => {
    const worker = workerConnectionOf(workerStatusQuad);
    expect(worker.concurrency).toBe(4);
    expect(investigationAssignments(worker, []).map((claim) => claim.workerId)).toEqual([
      "investigation-1",
      "investigation-2",
      "investigation-3",
      "investigation-4",
    ]);
    expect(workerCapacity(worker)).toBe(0);
    expect(worker.lanes).toEqual([
      { lane: "A", state: "busy", reason: null },
      { lane: "B", state: "busy", reason: null },
      { lane: "C", state: "cooling", reason: "RateLimitError" },
      { lane: "D", state: "ready", reason: null },
    ]);
    expect(worker.calls?.inFlight.map((call) => [call.workerId, call.lane])).toEqual([
      ["investigation-1", "A"],
      ["investigation-2", "B"],
    ]);
    expect(worker.calls?.waiting.map((call) => call.workerId)).toEqual(["investigation-3"]);
    expect(worker.autoStop).toBeNull();
  });

  it("invents nothing when the backend reports no provider section", () => {
    const worker = workerConnectionOf(workerStatusDual);
    expect(worker.lanes).toBeUndefined();
    expect(worker.calls).toBeUndefined();
    expect(worker.autoStop).toBeNull();
  });

  it("carries the server's reason for stopping Auto", () => {
    const worker = workerConnectionOf({
      ...workerStatusQuad,
      auto_stop: { reason: "inference_budget_exhausted", paused: true },
    });
    expect(worker.autoStop).toEqual({ reason: "inference_budget_exhausted", paused: true });
  });
});
