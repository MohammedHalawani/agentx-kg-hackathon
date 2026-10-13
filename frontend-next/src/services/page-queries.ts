import type {
  CaseQueue,
  InvestigationStageEvent,
  OperationalCase,
} from "@/domain/types";
import type { AuditFilters, ShipmentFilters } from "@/domain/page-actions";
import { matchesCause, searchText } from "@/domain/case-view";

export const LAB_TODAY = "2026-10-09";
export { cityLocations } from "@/domain/geo";
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
        matchesCause(c, filters.cause) &&
        searchText(c).includes(filters.search.toLowerCase()),
    )
    .sort((a, b) => Date.parse(b.openedAt) - Date.parse(a.openedAt));
}
/** Today in Saudi time, as YYYY-MM-DD. */
export function riyadhToday(now = new Date()) {
  return new Date(now.getTime() + 3 * 3600000).toISOString().slice(0, 10);
}
/** The week (from Sunday) and month containing `today`, as YYYY-MM-DD. */
export function rangeStarts(today: string) {
  const date = new Date(`${today}T00:00:00Z`);
  const week = new Date(date.getTime() - date.getUTCDay() * 86400000);
  return {
    week: week.toISOString().slice(0, 10),
    month: `${today.slice(0, 7)}-01`,
  };
}
/**
 * The lab's fixtures are anchored to LAB_TODAY with its original fixed week and month. Backend
 * records use the real calendar: pass `today` (Saudi time).
 */
export function timeBounds(filters: AuditFilters, today?: string) {
  const starts = today
    ? rangeStarts(today)
    : { week: "2026-10-05", month: "2026-10-01" };
  const anchor = today ?? LAB_TODAY;
  const start =
    filters.timeRange === "week"
      ? starts.week
      : filters.timeRange === "month"
        ? starts.month
        : filters.timeRange === "custom"
          ? filters.from
          : anchor;
  const end = filters.timeRange === "custom" ? filters.to : anchor;
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
  today?: string,
): AuditPageResult {
  const matchingShipments = filterShipments(snapshot.cases, {
    ...filters,
    search: filters.shipmentId === "all" ? "" : filters.shipmentId,
  });
  const ids = new Set(matchingShipments.map((c) => c.id));
  const bounds = timeBounds(filters, today);
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
