import type { CaseStatus, OperationalCase, Priority } from "@/domain/types";
import { statusLabels } from "@/domain/types";
import { caseQueueGroup } from "@/domain/investigation-workspace";

/**
 * Priority as the backend records it (High / Medium / Low / Unknown), ordered for sorting.
 * Nothing here recalculates or replaces a case's priority, and the investigation scheduler
 * never reads this order.
 */
export const PRIORITY_RANK: Record<Priority, number> = {
  high: 0,
  medium: 1,
  low: 2,
  unknown: 3,
};
/** Highest recorded priority first, oldest first within a priority. */
export function byRecordedPriority(a: OperationalCase, b: OperationalCase) {
  return (
    PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority] ||
    Date.parse(a.openedAt) - Date.parse(b.openedAt)
  );
}

/** The operational statuses for which the backend records priority "high" (store.py). */
export const SERIOUS_STATUSES = new Set([
  "CRITICAL",
  "UNRECONCILED_CUSTODY",
  "DELIVERY_DISPUTE",
]);
/** Symptoms that can mean a lost, disputed or misdirected parcel. */
export const LOSS_SYMPTOMS = new Set([
  "RECIPIENT_REPORTED_NOT_RECEIVED",
  "CUSTODY_REPORTS_CONFLICT",
  "MANIFEST_CUSTODY_CONFLICT",
  "SESSION_END_UNRECONCILED",
]);
export const OVERDUE_SYMPTOMS = new Set([
  "MILESTONE_OVERDUE",
  "OVERDUE_AT_FACILITY",
]);
/** Workflow states in which the case waits for a person. */
export const PERSON_STATES = new Set([
  "HUMAN_REVIEW",
  "AWAITING_APPROVAL",
  "ESCALATED",
]);
/** Workflow states in which a request is out and Suhail waits for its evidence. */
export const EVIDENCE_STATES = new Set([
  "ACTION_INITIATED",
  "AWAITING_OUTCOME",
]);

const LAB_STATUS_AR: Record<CaseStatus, string> = {
  queued: "في الانتظار",
  investigating: "قيد التحقيق",
  human_review: "بانتظار الموافقة",
  needs_evidence: "يتطلب أدلة",
  executing: "قيد التنفيذ",
  verifying: "التحقق من النتيجة",
  escalated: "تم التصعيد",
  resolved: "تم الحل",
};
const STEP_LABELS: Record<string, [string, string]> = {
  NONE: ["No action needed", "لا إجراء مطلوب"],
  START_INVESTIGATION: ["Investigate", "التحقيق"],
  WAIT_INVESTIGATION: ["Suhail is investigating", "سهيل يحقق"],
  WAIT_VERIFICATION: ["Wait for requested evidence", "انتظار الأدلة المطلوبة"],
  APPROVE_OR_REJECT: [
    "Approve or reject the action",
    "الموافقة على الإجراء أو رفضه",
  ],
  APPROVE_EVIDENCE_REQUEST_OR_INVESTIGATE: [
    "Approve evidence request or check",
    "الموافقة على طلب الأدلة أو الفحص",
  ],
  INVESTIGATE_AND_RECORD_FINDING: [
    "Person checks and records finding",
    "يفحص شخص ويسجل النتيجة",
  ],
  REVIEW_VERIFIED_RESULT_AND_RECORD_FINDING: [
    "Person reviews the verified result",
    "يراجع شخص النتيجة المتحقق منها",
  ],
  REVIEW_UNACCEPTED_INVESTIGATION: [
    "Person reviews the unaccepted finding",
    "يراجع شخص النتيجة غير المقبولة",
  ],
  REVIEW_WHAT_STILL_STANDS: [
    "Person reviews what still stands",
    "يراجع شخص ما لا يزال قائماً",
  ],
  PROVIDE_EVIDENCE_OR_REANALYSE: [
    "Add evidence or re-analyse",
    "إضافة أدلة أو إعادة التحليل",
  ],
};
const STATE_LABELS: Record<string, [string, string]> = {
  OPEN: ["Awaiting investigation", "بانتظار التحقيق"],
  REOPENED: ["Awaiting investigation", "بانتظار التحقيق"],
  INVESTIGATING: ["Suhail is investigating", "سهيل يحقق"],
  RECOMMENDATION_READY: ["Suhail is investigating", "سهيل يحقق"],
  AWAITING_APPROVAL: [
    "Approve or reject the action",
    "الموافقة على الإجراء أو رفضه",
  ],
  HUMAN_REVIEW: ["Person review needed", "مطلوب مراجعة شخص"],
  NEEDS_EVIDENCE: ["Add evidence or re-analyse", "إضافة أدلة أو إعادة التحليل"],
  REJECTED: ["Add evidence or re-analyse", "إضافة أدلة أو إعادة التحليل"],
  ACTION_INITIATED: ["Wait for requested evidence", "انتظار الأدلة المطلوبة"],
  AWAITING_OUTCOME: ["Wait for requested evidence", "انتظار الأدلة المطلوبة"],
  ESCALATED: ["Escalated to a person", "صُعّدت إلى شخص"],
  RESOLVED: ["Verified resolved", "تم التحقق من الحل"],
};

/**
 * The next action in a few words: the backend's own next step once the case detail is
 * loaded, otherwise the recorded workflow state. `actor` says who acts when recorded.
 */
export function nextActionOf(c: OperationalCase): {
  label: [string, string];
  actor: "operator" | "system" | "none" | null;
  pending: boolean;
} {
  // Lab fixtures have no backend lifecycle: their simulated status is the next action.
  if (!c.backend)
    return {
      label: [statusLabels[c.status], LAB_STATUS_AR[c.status]],
      actor: null,
      pending: c.status === "queued",
    };
  const step = c.backend?.nextStep;
  const state = c.backend?.workflowState;
  if (step && STEP_LABELS[step.code])
    return {
      label: STEP_LABELS[step.code],
      actor: (["operator", "system", "none"].includes(step.actor)
        ? step.actor
        : null) as "operator" | "system" | "none" | null,
      pending: false,
    };
  if (state && STATE_LABELS[state])
    return {
      label:
        state === "RESOLVED" && caseQueueGroup(c) !== "resolved"
          ? ["Checking verification", "جارٍ التحقق"]
          : STATE_LABELS[state],
      actor: null,
      pending: state === "OPEN" || state === "REOPENED",
    };
  return {
    label: ["Not recorded", "غير مسجل"],
    actor: null,
    pending: false,
  };
}

/** The most recent recorded time on the case, for "Last update". */
export function lastUpdateOf(c: OperationalCase): string {
  const times = [
    c.openedAt,
    c.backend?.asOf,
    c.outcome?.timestamp,
    c.backend?.actionStatus?.actions[0]?.events.at(-1)?.occurred_at,
  ].filter(
    (value): value is string => !!value && !Number.isNaN(Date.parse(value)),
  );
  return times.sort((a, b) => Date.parse(b) - Date.parse(a))[0] ?? c.openedAt;
}
