import type {
  CaseQueue,
  InvestigationStageEvent,
  OperationalCase,
} from "@/domain/types";
import type { AuditFilters, ShipmentFilters } from "@/domain/page-actions";

export const LAB_TODAY = "2026-10-09";
export const cityLocations: Record<string, [number, number]> = {
  Riyadh: [24.7136, 46.6753],
  Dammam: [26.4207, 50.0888],
  Khobar: [26.2794, 50.2083],
  Jeddah: [21.5433, 39.1728],
  "Al Hofuf": [25.3646, 49.5876],
  Buraydah: [26.3592, 43.9818],
};
export function filterShipments(
  cases: OperationalCase[],
  filters: ShipmentFilters,
) {
  return cases
    .filter(
      (c) =>
        (filters.origin === "all" || c.shipment.origin === filters.origin) &&
        (filters.destination === "all" ||
          c.shipment.destination === filters.destination) &&
        (filters.city === "all" ||
          c.shipment.origin === filters.city ||
          c.shipment.destination === filters.city) &&
        (filters.status === "all" ||
          (filters.status === "attention" && c.status !== "resolved") ||
          c.status === filters.status) &&
        (filters.priority === "all" || c.priority === filters.priority) &&
        (filters.cause === "all" || c.scenario === filters.cause) &&
        `${c.id} ${c.issue} ${c.shipment.origin} ${c.shipment.destination}`
          .toLowerCase()
          .includes(filters.search.toLowerCase()),
    )
    .sort((a, b) => Date.parse(b.openedAt) - Date.parse(a.openedAt));
}
export function timeBounds(filters: AuditFilters) {
  const start =
    filters.timeRange === "week"
      ? "2026-10-05"
      : filters.timeRange === "month"
        ? "2026-10-01"
        : filters.timeRange === "custom"
          ? filters.from
          : LAB_TODAY;
  const end = filters.timeRange === "custom" ? filters.to : LAB_TODAY;
  return {
    start:
      filters.timeRange === "all"
        ? Number.NEGATIVE_INFINITY
        : Date.parse(`${start}T00:00:00+03:00`),
    end:
      filters.timeRange === "all"
        ? Number.POSITIVE_INFINITY
        : Date.parse(`${end}T23:59:59.999+03:00`),
  };
}
export interface AuditPageResult {
  items: InvestigationStageEvent[];
  total: number;
  uniqueShipments: number;
  uniqueCases: number;
  matchingShipments: OperationalCase[];
}
/** Frontend-only query boundary. Pagination can later be replaced by a cursor adapter. */
export function queryAudit(
  snapshot: CaseQueue,
  filters: AuditFilters,
  pageIndex: number,
  pageSize: number,
): AuditPageResult {
  const matchingShipments = filterShipments(snapshot.cases, {
    ...filters,
    search: filters.shipmentId === "all" ? "" : filters.shipmentId,
  });
  const ids = new Set(matchingShipments.map((c) => c.id));
  const bounds = timeBounds(filters);
  const all = snapshot.events
    .filter((e) => {
      const timestamp = Date.parse(
        filters.timeBasis === "evidence"
          ? (e.evidenceTimestamp ?? e.timestamp)
          : e.timestamp,
      );
      const c = snapshot.cases.find((c) => c.id === e.caseId);
      return (
        ids.has(e.caseId) &&
        (filters.kind === "all" || e.kind === filters.kind) &&
        (filters.workflow === "all" || c?.status === filters.workflow) &&
        (filters.actor === "all" ||
          e.actorRole === filters.actor ||
          (filters.actor === "operator" && e.kind === "decision")) &&
        timestamp >= bounds.start &&
        timestamp <= bounds.end &&
        `${e.caseId} ${e.title} ${e.detail} ${e.actor}`
          .toLowerCase()
          .includes(filters.search.toLowerCase())
      );
    })
    .sort((a, b) => {
      const aTime =
        filters.timeBasis === "evidence"
          ? (a.evidenceTimestamp ?? a.timestamp)
          : a.timestamp;
      const bTime =
        filters.timeBasis === "evidence"
          ? (b.evidenceTimestamp ?? b.timestamp)
          : b.timestamp;
      return (
        (Date.parse(aTime) - Date.parse(bTime)) *
        (filters.sort === "oldest" ? 1 : -1)
      );
    });
  const unique = new Set(all.map((e) => e.caseId));
  return {
    items: all.slice(pageIndex * pageSize, (pageIndex + 1) * pageSize),
    total: all.length,
    uniqueShipments: unique.size,
    uniqueCases: unique.size,
    matchingShipments,
  };
}
