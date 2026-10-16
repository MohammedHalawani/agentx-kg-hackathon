import { describe, expect, it } from "vitest";
import {
  monitorOverviewItems,
  type ApiMonitorOverview,
} from "../../src/lib/monitor-overview";

const overview: ApiMonitorOverview = {
  synthetic: true,
  as_of: "2026-09-16T06:00:00+00:00",
  shipments_booked: 80,
  shipments_monitored: 74,
  no_active_exception: 66,
  active_exception: 7,
  cases_total: 9,
  cases_open: 9,
  awaiting_investigation: 5,
  investigating: 1,
  action_pending: 2,
  human_review: 1,
  alerts_cleared_by_later_evidence: 0,
  alerts_partly_cleared: 0,
  verified_resolved: 0,
};

describe("monitor overview", () => {
  it("shows the backend counts in a fixed order, zeros included", () => {
    const items = monitorOverviewItems(overview);
    expect(items.map((i) => [i.key, i.value])).toEqual([
      ["monitored", 74],
      ["healthy", 66],
      ["new", 5],
      ["investigating", 1],
      ["pending", 2],
      ["human", 1],
      ["verified", 0],
    ]);
    expect(items[0].title_en).toContain("80 booked");
  });
  it("adds cleared alerts only when there are some, and never calls them resolved", () => {
    const items = monitorOverviewItems({
      ...overview,
      alerts_cleared_by_later_evidence: 3,
    });
    const cleared = items.find((i) => i.key === "cleared")!;
    expect(cleared.value).toBe(3);
    expect(cleared.title_en).toContain("Not resolved and not verified");
  });
});
