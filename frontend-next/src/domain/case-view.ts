import type { OperationalCase } from "@/domain/types";

/**
 * How a case is presented, for both data sources. For backend cases every answer comes from
 * what the backend served (`c.backend`); the lab branch keeps the original fixture behaviour.
 */
export const displayId = (c: OperationalCase) =>
  c.backend ? c.shipment.id || c.id : c.id;

/** Backend workflow states, verbatim, with their labels. */
export const workflowLabels: Record<string, [string, string]> = {
  OPEN: ["Queued", "في الانتظار"],
  REOPENED: ["Reopened · queued", "أعيد فتحها · في الانتظار"],
  INVESTIGATING: ["Investigating", "قيد التحقيق"],
  NEEDS_EVIDENCE: ["Needs evidence", "يتطلب أدلة"],
  REJECTED: ["Action rejected", "رُفض الإجراء"],
  RECOMMENDATION_READY: ["Recommendation ready", "التوصية جاهزة"],
  AWAITING_APPROVAL: ["Awaiting approval", "بانتظار الموافقة"],
  HUMAN_REVIEW: ["Human investigation", "تحقيق بشري"],
  ACTION_INITIATED: ["Executing", "قيد التنفيذ"],
  AWAITING_OUTCOME: ["Verifying outcome", "التحقق من النتيجة"],
  ESCALATED: ["Escalated", "تم التصعيد"],
  RESOLVED: ["Resolved", "تم الحل"],
};

export function matchesCause(c: OperationalCase, cause: string) {
  if (cause === "all") return true;
  return c.backend ? c.backend.causeCodes.includes(cause) : c.scenario === cause;
}

const LAB_OPERATIONAL = {
  held: ["Parcel held", "الطرد محتجز"],
  disputed: ["Delivery disputed", "التسليم محل نزاع"],
  exception: ["Exception open", "استثناء مفتوح"],
} as const;
const BACKEND_OPERATIONAL: Record<string, string> = {
  ON_TIME: "في الموعد",
  NEEDS_ATTENTION: "تحتاج انتباهاً",
  SLA_RISK: "خطر على الالتزام",
  CRITICAL: "حرجة",
  UNRECONCILED_CUSTODY: "حيازة غير مسوّاة",
  DELIVERY_DISPUTE: "تسليم محل نزاع",
  ADDRESS_CONFLICT: "تعارض في العنوان",
  RECIPIENT_UNAVAILABLE: "المستلم غير متاح",
  HUB_DELAY: "تأخر في المركز",
  RESOLVED: "تم الحل",
};
const sentence = (code: string) =>
  code.charAt(0) + code.slice(1).replaceAll("_", " ").toLowerCase();
/** The operational status shown in the queue: [value, English, Arabic]. */
export function operationalOf(c: OperationalCase): [string, string, string] {
  if (c.backend) {
    const value = c.backend.operationalStatus ?? "NEEDS_ATTENTION";
    return [
      value,
      sentence(value),
      BACKEND_OPERATIONAL[value] ?? sentence(value),
    ];
  }
  const value =
    c.scenario === "delivery"
      ? "disputed"
      : c.scenario === "address" || c.scenario === "weight"
        ? "held"
        : "exception";
  return [value, ...LAB_OPERATIONAL[value]];
}
export function matchesOperational(c: OperationalCase, value: string) {
  if (value === "all") return true;
  if (c.backend) return operationalOf(c)[0] === value;
  return (
    (value === "held" && ["weight", "address"].includes(c.scenario)) ||
    (value === "disputed" && c.scenario === "delivery") ||
    (value === "exception" && c.scenario !== "normal")
  );
}

/** Awaiting an operator's authorization of a reviewed recommendation. */
export function awaitingApproval(c: OperationalCase) {
  return c.backend
    ? ["AWAITING_APPROVAL", "RECOMMENDATION_READY"].includes(
        c.backend.workflowState,
      )
    : c.status === "human_review";
}

/** Which operator controls to show. Backend cases show only what the backend lifecycle accepts. */
export function controls(c: OperationalCase) {
  if (c.backend) return c.backend.allowed;
  return {
    investigate: c.status === "queued",
    approve: c.status === "human_review",
    reject: c.status === "human_review",
    escalate: c.status === "human_review" || c.status === "needs_evidence",
    verify: c.status === "verifying",
  };
}

/** The authority a recommendation needs: [English, Arabic]. */
export function authorityLabel(c: OperationalCase): [string, string] {
  if (c.backend) {
    if (!c.recommendation.available)
      return ["No reviewed recommendation", "لا توجد توصية مُراجعة"];
    const risk = c.backend.riskClass;
    if (c.backend.approvalRule?.startsWith("AUTH-22"))
      return ["Rules-only proposal · not executable", "اقتراح قواعد فقط · غير قابل للتنفيذ"];
    if (risk === "AUTO")
      return ["Automatic · policy-authorized", "تلقائي · مصرح به"];
    if (risk === "APPROVAL_REQUIRED")
      return ["Operator approval required", "يتطلب موافقة المشغل"];
    if (risk === "PROHIBITED")
      return ["Prohibited · never automated", "محظور · لا يُؤتمت"];
    return ["Human investigation", "تحقيق بشري"];
  }
  return c.recommendation.authority === "operator"
    ? ["Operator authority", "صلاحية المشغل"]
    : c.recommendation.authority === "evidence"
      ? ["Needs evidence", "يتطلب أدلة"]
      : ["Low-risk action", "إجراء منخفض المخاطر"];
}

/** Text searched by the queue, Explore and global search. */
export const searchText = (c: OperationalCase) =>
  `${c.id} ${c.shipment.id} ${c.issue} ${c.shipment.origin} ${c.shipment.destination}`.toLowerCase();
