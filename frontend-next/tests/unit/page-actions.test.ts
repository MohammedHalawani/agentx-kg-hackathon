import { describe, it, expect } from "vitest";
import { initialSnapshot } from "@/data/fixtures";
import { filterShipments, queryAudit } from "@/services/page-queries";
import { parsePageIntent } from "@/services/mock-intents";
import { emptyAuditFilters, emptyShipmentFilters } from "@/domain/page-actions";
const snapshot = initialSnapshot();
describe("read-only contextual page actions", () => {
  it("filters exact route destinations rather than treating passing through a city as arrival", () => {
    const shipments = filterShipments(snapshot.cases, {
      ...emptyShipmentFilters,
      origin: "Riyadh",
      destination: "Khobar",
    });
    expect(shipments.length).toBeGreaterThan(0);
    expect(
      shipments.every(
        (c) =>
          c.shipment.origin === "Riyadh" && c.shipment.destination === "Khobar",
      ),
    ).toBe(true);
    expect(shipments.some((c) => c.id === "SHP-10482")).toBe(false);
  });
  it("returns chronological, non-overlapping audit pages and truthful unique counts", () => {
    const filters = { ...emptyAuditFilters, timeRange: "all" as const };
    const first = queryAudit(snapshot, filters, 0, 10),
      second = queryAudit(snapshot, filters, 1, 10),
      all = queryAudit(snapshot, filters, 0, 1000);
    expect(first.items).toHaveLength(10);
    expect(second.items).toHaveLength(10);
    expect(
      new Set([...first.items, ...second.items].map((e) => e.id)).size,
    ).toBe(20);
    expect(Date.parse(first.items.at(-1)!.timestamp)).toBeLessThanOrEqual(
      Date.parse(second.items[0].timestamp),
    );
    expect(all.total).toBe(all.items.length);
    expect(all.uniqueShipments).toBe(
      new Set(all.items.map((e) => e.caseId)).size,
    );
  });
  it("honors month, custom date, route, and shipment filters across the full dataset", () => {
    const monthly = queryAudit(
      snapshot,
      { ...emptyAuditFilters, timeRange: "month", destination: "Riyadh" },
      0,
      1000,
    );
    expect(monthly.total).toBeGreaterThan(0);
    expect(
      monthly.items.every(
        (e) =>
          Date.parse(e.timestamp) >= Date.parse("2026-10-01T00:00:00+03:00"),
      ),
    ).toBe(true);
    expect(
      monthly.matchingShipments.every(
        (c) => c.shipment.destination === "Riyadh",
      ),
    ).toBe(true);
    const custom = queryAudit(
      snapshot,
      {
        ...emptyAuditFilters,
        timeRange: "custom",
        from: "2026-10-02",
        to: "2026-10-02",
      },
      0,
      1000,
    );
    expect(custom.items.every((e) => e.caseId === "SHP-10442")).toBe(true);
    expect(custom.total).toBeGreaterThan(0);
  });
  it("applies only supported typed requests and rejects unknown shipments or decisions", () => {
    const context = {
      page: "explore" as const,
      filters: emptyShipmentFilters,
      view: "map",
      selectedCaseId: "SHP-10482",
    };
    expect(
      parsePageIntent(
        "Show shipments from Riyadh to Khobar",
        context,
        snapshot.cases,
      ).actions,
    ).toContainEqual({
      type: "filter_shipments",
      filters: { origin: "Riyadh", destination: "Khobar" },
    });
    expect(
      parsePageIntent(
        "اعرض الشحنات من الرياض إلى الخبر",
        context,
        snapshot.cases,
        "ar",
      ).actions,
    ).toContainEqual({
      type: "filter_shipments",
      filters: { origin: "Riyadh", destination: "Khobar" },
    });
    expect(
      parsePageIntent("Show resolved shipments", context, snapshot.cases)
        .supported,
    ).toBe(true);
    expect(
      parsePageIntent("approve SHP-10482", context, snapshot.cases).actions,
    ).toHaveLength(0);
    expect(
      parsePageIntent("Show SHP-99999", context, snapshot.cases).supported,
    ).toBe(false);
  });
  it("supports the monthly failed-outcome audit example and retains filter context for follow-ups", () => {
    const context = {
      page: "audit" as const,
      filters: { ...emptyAuditFilters, destination: "Riyadh" },
      view: "events",
    };
    const intent = parsePageIntent(
      "Show this month’s failed outcomes",
      context,
      snapshot.cases,
    );
    expect(intent.actions).toContainEqual({
      type: "filter_audit_events",
      filters: { timeRange: "month", kind: "verification", search: "failed" },
    });
    expect(
      parsePageIntent(
        "اعرض النتائج التي فشل التحقق منها هذا الشهر",
        context,
        snapshot.cases,
        "ar",
      ).actions,
    ).toContainEqual({
      type: "filter_audit_events",
      filters: { timeRange: "month", kind: "verification", search: "failed" },
    });
    const next = queryAudit(
      snapshot,
      {
        ...emptyAuditFilters,
        timeRange: "month",
        kind: "verification",
        search: "failed",
      },
      0,
      100,
    );
    expect(next.items.length).toBeGreaterThan(0);
    expect(next.items.every((e) => e.kind === "verification")).toBe(true);
    const followup = parsePageIntent(
      "Show their audit histories",
      context,
      snapshot.cases,
    );
    expect(followup.actions).toContainEqual({
      type: "change_view",
      view: "events",
    });
    expect(context.filters.destination).toBe("Riyadh");
  });
});
