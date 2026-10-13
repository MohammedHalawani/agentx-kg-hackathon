import { describe, it, expect } from "vitest";
import { MockOperationsService, STORAGE_KEY } from "@/services/mock-operations";
const now = () => "2026-10-09T12:00:00+03:00";
const find = (service: MockOperationsService, id: string) =>
  service.getSnapshot().cases.find((c) => c.id === id)!;
describe("frontend simulation lifecycle", () => {
  it("starts the oldest eligible case and keeps one active run", () => {
    const service = new MockOperationsService(undefined, now);
    service.setAutomatic(true);
    service.tick();
    expect(find(service, "SHP-10471").status).toBe("investigating");
    expect(() => service.investigate("SHP-10491")).toThrow(
      "current investigation",
    );
    expect(
      service.getSnapshot().cases.filter((c) => c.status === "investigating"),
    ).toHaveLength(1);
    const id = find(service, "SHP-10471").run!.id;
    expect(
      service
        .getSnapshot()
        .events.find((e) => e.title === "Investigation started")?.runId,
    ).toBe(id);
  });
  it("pauses new intake while finishing the current simulated run", () => {
    const service = new MockOperationsService(undefined, now);
    service.setAutomatic(true);
    service.tick();
    service.setAutomatic(false);
    for (let i = 0; i < 7; i++) service.tick();
    expect(find(service, "SHP-10471").status).toBe("resolved");
    service.tick();
    expect(find(service, "SHP-10491").status).toBe("queued");
  });
  it("approves only the named action; execution and verification happen separately", () => {
    const service = new MockOperationsService(undefined, now);
    expect(() => service.decide("SHP-10482", "approved", "")).toThrow("reason");
    service.decide(
      "SHP-10482",
      "approved",
      "Independent Al Ahsa parcel scan supports custody reconciliation.",
    );
    expect(find(service, "SHP-10482").status).toBe("executing");
    expect(find(service, "SHP-10482").outcome).toBeUndefined();
    service.tick();
    expect(find(service, "SHP-10482").status).toBe("verifying");
    service.tick();
    const c = find(service, "SHP-10482");
    expect(c.status).toBe("resolved");
    expect(c.outcome?.successful).toBe(true);
    expect(c.outcome?.evidenceIds).toContain("recovery");
    expect(
      service
        .getSnapshot()
        .events.find((e) => e.title === "Outcome independently verified")
        ?.evidenceIds,
    ).toContain("recovery");
    expect(service.getSnapshot().decisions[0].reason).toContain("Al Ahsa");
  });
  it("keeps failed recovery unresolved and never creates a successful resolution", () => {
    const service = new MockOperationsService(undefined, now);
    const id = service.addCase("failed");
    service.investigate(id);
    for (let i = 0; i < 5; i++) service.tick();
    expect(find(service, id).status).toBe("human_review");
    service.decide(
      id,
      "approved",
      "Authorize the proposed recovery, with independent outcome verification.",
    );
    service.tick();
    service.tick();
    expect(find(service, id).status).toBe("escalated");
    expect(find(service, id).outcome?.successful).toBe(false);
    expect(
      service
        .getSnapshot()
        .events.filter((e) => e.caseId === id && e.kind === "resolution"),
    ).toHaveLength(0);
  });
  it("stops for missing evidence or human authority instead of simulating an unauthorized action", () => {
    const service = new MockOperationsService(undefined, now);
    service.investigate("SHP-10489");
    for (let i = 0; i < 8; i++) service.tick();
    expect(find(service, "SHP-10489").status).toBe("needs_evidence");
    expect(find(service, "SHP-10489").execution).toBeUndefined();
    service.investigate("SHP-10491");
    for (let i = 0; i < 8; i++) service.tick();
    expect(find(service, "SHP-10491").status).toBe("human_review");
    expect(find(service, "SHP-10491").execution).toBeUndefined();
  });
  it("records rejection and escalation without resolving a case", () => {
    const service = new MockOperationsService(undefined, now);
    service.decide(
      "SHP-10479",
      "rejected",
      "A second independently calibrated weight scan is required.",
    );
    expect(find(service, "SHP-10479").status).toBe("needs_evidence");
    service.decide(
      "SHP-10479",
      "escalated",
      "Dispatch supervision must gather the missing evidence.",
    );
    expect(find(service, "SHP-10479").status).toBe("escalated");
    expect(service.getSnapshot().decisions).toHaveLength(2);
  });
  it("restores browser changes and returns a safe fixture after corrupt storage", () => {
    const store = new Map<string, string>();
    const storage = {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => {
        store.set(key, value);
      },
    };
    const service = new MockOperationsService(storage, now);
    service.decide("SHP-10482", "rejected", "Need independent proof.");
    expect(
      find(new MockOperationsService(storage, now), "SHP-10482").status,
    ).toBe("needs_evidence");
    store.set(STORAGE_KEY, "broken JSON");
    expect(
      find(new MockOperationsService(storage, now), "SHP-10482").status,
    ).toBe("human_review");
  });
  it("chat answers stay grounded in the selected fixture and cannot mutate it", () => {
    const service = new MockOperationsService(undefined, now);
    const before = JSON.stringify(service.getSnapshot());
    expect(
      service.answer("SHP-10482", "@investigator where is custody confirmed?"),
    ).toContain("Al Ahsa warehouse");
    expect(service.answer("SHP-10482", "where is it?")).toContain(
      "does not prove",
    );
    service.answer("SHP-10482", "approve this case");
    expect(JSON.stringify(service.getSnapshot())).toBe(before);
  });
});
