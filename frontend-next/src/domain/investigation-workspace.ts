import type { ApiActionLifecycle, ApiPipelineEvent } from "@/api/contracts";
import type { OperationalCase } from "@/domain/types";

export function verifiedResolution(c: OperationalCase) {
  if (c.backend?.actionStatus)
    return c.backend.actionStatus.resolution === "VERIFIED_RESOLVED";
  return c.status === "resolved" && c.outcome?.successful === true;
}

export function actionLabel(action: ApiActionLifecycle): [string, string] {
  const labels: Record<string, [string, string]> = {
    REFUSED: [
      "Authorization refused · nothing dispatched",
      "رُفض التفويض · لم يُرسل الطلب",
    ],
    AUTHORIZED: ["Authorized · dispatch pending", "مفوّض · بانتظار الإرسال"],
    AWAITING_ACKNOWLEDGEMENT: [
      "Request sent · awaiting acknowledgement",
      "أُرسل الطلب · بانتظار تأكيد الاستلام",
    ],
    ACKNOWLEDGED: [
      "Acknowledged · acceptance pending",
      "تم الاستلام · بانتظار قبول المهمة",
    ],
    AWAITING_RESCAN: [
      "Awaiting independent rescan",
      "بانتظار إعادة مسح مستقلة",
    ],
    AWAITING_SYNCHRONIZATION: [
      "Awaiting device synchronization",
      "بانتظار مزامنة الجهاز",
    ],
    AWAITING_CUSTODY_RECONCILIATION: [
      "Awaiting directed custody check",
      "بانتظار فحص الحيازة الموجّه",
    ],
    ACCEPTED: [
      "Task accepted · evidence pending",
      "قُبلت المهمة · بانتظار الأدلة",
    ],
    EXECUTING: ["Operational work in progress", "العمل التشغيلي جارٍ"],
    EVIDENCE_RECEIVED: [
      "Evidence received · verification pending",
      "وصلت الأدلة · بانتظار التحقق",
    ],
    REJECTED: [
      "Task rejected · exception unresolved",
      "رُفضت المهمة · الاستثناء غير محلول",
    ],
    FAILED: [
      action.dispatch === "UNAVAILABLE"
        ? "Dispatch unavailable · request not delivered"
        : "Operational task failed · exception unresolved",
      "تعذّر الإجراء · الاستثناء غير محلول",
    ],
    EXPIRED: [
      "Request expired · no verified resolution",
      "انتهت مهلة الطلب · لا حل متحققاً منه",
    ],
    VERIFIED: [
      action.resolved
        ? "Action verified · case resolution recorded"
        : "Action verified · exception remains",
      action.resolved
        ? "تم التحقق من الإجراء · سُجل حل الحالة"
        : "تم التحقق من الإجراء · الاستثناء باقٍ",
    ],
    UNRESOLVED: [
      "Evidence did not verify the requested effect",
      "لم تثبت الأدلة الأثر المطلوب",
    ],
  };
  return (
    labels[action.operational_label] ??
    labels[action.state] ?? [
      "Operational status unavailable",
      "الحالة التشغيلية غير متاحة",
    ]
  );
}

export function waitingLabel(c: OperationalCase): [string, string] {
  if (c.backend?.detailError && !c.backend.detailLoaded)
    return ["Operational status unavailable", "الحالة التشغيلية غير متاحة"];
  const status = c.backend?.actionStatus;
  if (status?.human_decision_required)
    return ["Human decision required", "قرار بشري مطلوب"];
  if (
    c.backend?.workflowState === "AWAITING_APPROVAL" &&
    c.backend.allowed.approve
  )
    return ["Awaiting approval", "بانتظار الموافقة"];
  const action = status?.actions.at(-1);
  if (action) return actionLabel(action);
  if (status?.resolution === "UNRESOLVED")
    return ["Unresolved · evidence needed", "غير محلولة · أدلة مطلوبة"];
  return c.backend?.detailLoaded
    ? ["Waiting for the next evidence step", "بانتظار خطوة الأدلة التالية"]
    : ["Reading operational status…", "جارٍ قراءة الحالة التشغيلية…"];
}

export function retrievalEvents(events: ApiPipelineEvent[] = []) {
  return events
    .filter(
      (event) =>
        event.output?.kind === "tool_call" &&
        typeof event.output.tool === "string",
    )
    .filter(
      (event, index, all) =>
        all.findIndex((other) => other.sequence === event.sequence) === index,
    )
    .sort((a, b) => a.sequence - b.sequence);
}

/** Exact current-case IDs and real relationships only; absence never supplies geography. */
export function evidenceFocus(c: OperationalCase, ids: string[]) {
  const nodeIds = new Set(c.nodes.map((node) => node.id));
  const locatedIds = new Set(
    c.evidence
      .filter((item) => item.selectable !== false)
      .map((item) => item.id),
  );
  const seeds = new Set(
    ids.filter((id) => nodeIds.has(id) || locatedIds.has(id)),
  );
  for (const edge of c.relationships) {
    if (ids.includes(edge.id)) {
      seeds.add(edge.source);
      seeds.add(edge.target);
    }
  }
  const graphIds = new Set(seeds);
  for (const edge of c.relationships) {
    if (seeds.has(edge.source)) graphIds.add(edge.target);
    if (seeds.has(edge.target)) graphIds.add(edge.source);
  }
  const mapIds = c.evidence
    .filter(
      (item) =>
        item.selectable !== false &&
        (graphIds.has(item.id) ||
          (!!item.routeRunId && seeds.has(item.routeRunId)) ||
          (!!item.tripId && seeds.has(item.tripId)) ||
          (!!item.vehicleId && seeds.has(item.vehicleId))),
    )
    .map((item) => item.id);
  return {
    graphIds: [...graphIds].filter((id) => nodeIds.has(id)),
    mapIds,
    missingIds: ids.filter(
      (id) => !seeds.has(id) && !c.relationships.some((edge) => edge.id === id),
    ),
  };
}
