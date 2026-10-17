import type {
  BackendConnection,
  InvestigationStatus,
  OperationalCase,
} from "@/domain/types";
import { caseQueueGroup } from "@/domain/investigation-workspace";

export type OperationsCollection =
  "unassigned" | "assigned" | "waiting" | "closed";

export type QueueFilters = {
  collection: string;
  status: string;
  priority: string;
  city: string;
  cause: string;
  operational: string;
  sort: string;
  /** A case-ledger stage group, as the backend's monitor overview counts it. */
  stage: string;
};
/** The workflow states of each overview group (chat/operations/store.py OVERVIEW_GROUPS). */
export const STAGE_GROUPS: Record<string, readonly string[]> = {
  awaiting_investigation: ["OPEN", "REOPENED"],
  action_pending: [
    "RECOMMENDATION_READY",
    "AWAITING_APPROVAL",
    "ACTION_INITIATED",
    "AWAITING_OUTCOME",
    "NEEDS_EVIDENCE",
  ],
  human_review: ["HUMAN_REVIEW", "ESCALATED", "REJECTED"],
};
export const defaultQueueFilters: QueueFilters = {
  collection: "unassigned",
  status: "all",
  priority: "all",
  city: "all",
  cause: "all",
  operational: "all",
  sort: "newest",
  stage: "all",
};

export function investigationAssignments(
  worker: BackendConnection["worker"],
  cases: readonly OperationalCase[],
): InvestigationStatus[] {
  if (!worker) return [];
  if (worker.activeCases.length || !worker.activeCaseId)
    return worker.activeCases;
  const c = cases.find((item) => item.id === worker.activeCaseId);
  return [
    {
      caseId: worker.activeCaseId,
      shipmentId: c?.shipment.id ?? "",
      workerId: null,
      runId: c?.run?.id ?? null,
      runStatus: c?.backend?.pipelineStatus ?? "UNKNOWN",
      activeStage: null,
      workflowState: c?.backend?.workflowState ?? "UNKNOWN",
      startedAt: null,
      updatedAt: null,
      leaseExpiresAt: null,
      asOf: null,
      stateVersion: c?.backend?.stateVersion ?? 0,
    },
  ];
}

/** Display placement only. Claim eligibility and authorization remain backend decisions. */
export function operationsCollection(
  c: OperationalCase,
  assignments: readonly InvestigationStatus[] = [],
): OperationsCollection {
  if (caseQueueGroup(c) !== "active") return "closed";
  if (assignments.some((claim) => claim.caseId === c.id)) return "assigned";
  if (c.backend) {
    if (["OPEN", "REOPENED"].includes(c.backend.workflowState))
      return "unassigned";
    if (c.backend.workflowState === "INVESTIGATING") return "assigned";
    return "waiting";
  }
  if (c.status === "queued") return "unassigned";
  if (c.status === "investigating") return "assigned";
  return "waiting";
}

export function assignmentIsRunning(
  claim: InvestigationStatus,
  online: boolean,
) {
  return (
    online &&
    claim.workflowState === "INVESTIGATING" &&
    claim.runStatus === "RUNNING"
  );
}

/** Free capacity is a pool count, not a fabricated roster of idle worker identities. */
export function workerCapacity(worker: BackendConnection["worker"]) {
  if (!worker) return null;
  return Math.max(
    0,
    worker.concurrency -
      Math.max(worker.activeCount, worker.activeCases.length),
  );
}

/** Numbered pages refer only to the loaded row array, never unvisited backend cursors. */
export function tablePages(
  current: number,
  count: number,
): (number | "ellipsis")[] {
  const pages = new Set(
    [0, count - 1, current - 1, current, current + 1].filter(
      (n) => n >= 0 && n < count,
    ),
  );
  const result: (number | "ellipsis")[] = [];
  [...pages]
    .sort((a, b) => a - b)
    .forEach((n) => {
      const previous = result.at(-1);
      if (typeof previous === "number" && n - previous > 1)
        result.push("ellipsis");
      result.push(n);
    });
  return result;
}

export const CASE_QUEUE_PAGE_SIZE = 4;

/** Pages only the loaded queue. It never requests records or infers server totals. */
export function caseQueuePage<T>(items: readonly T[], requestedPage: number) {
  const total = items.length;
  const pageCount = Math.ceil(total / CASE_QUEUE_PAGE_SIZE);
  const pageIndex = Math.max(
    0,
    Math.min(Math.floor(requestedPage), pageCount - 1),
  );
  const start = pageIndex * CASE_QUEUE_PAGE_SIZE;
  const end = Math.min(start + CASE_QUEUE_PAGE_SIZE, total);
  return {
    items: items.slice(start, end),
    total,
    pageIndex,
    pageCount,
    start,
    end,
  };
}
