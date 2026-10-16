/** GET /operations/monitor/overview (chat/operations/store.py monitor_overview). Counts only: no truth, no model. */
export interface ApiMonitorOverview {
  synthetic: true;
  as_of: string;
  shipments_booked: number;
  shipments_monitored: number;
  no_active_exception: number;
  active_exception: number;
  cases_total: number;
  cases_open: number;
  awaiting_investigation: number;
  investigating: number;
  action_pending: number;
  human_review: number;
  alerts_cleared_by_later_evidence: number;
  alerts_partly_cleared: number;
  verified_resolved: number;
}

export interface MonitorOverviewItem {
  key: string;
  value: number;
  en: string;
  ar: string;
  title_en: string;
  title_ar: string;
}

/** The compact Operations overview line, in a fixed order. A zero is a real count and is shown. */
export function monitorOverviewItems(
  o: ApiMonitorOverview,
): MonitorOverviewItem[] {
  const items: MonitorOverviewItem[] = [
    {
      key: "monitored",
      value: o.shipments_monitored,
      en: "monitored",
      ar: "تحت المراقبة",
      title_en: `Shipments the monitor has checked this session (${o.shipments_booked} booked so far).`,
      title_ar: `الشحنات التي فحصها المراقب في هذه الجلسة (${o.shipments_booked} محجوزة حتى الآن).`,
    },
    {
      key: "healthy",
      value: o.no_active_exception,
      en: "no active exception",
      ar: "دون استثناء قائم",
      title_en:
        "Latest check found no rule match and the shipment has no open case.",
      title_ar: "لم يجد آخر فحص أي مطابقة لقاعدة وليس للشحنة حالة مفتوحة.",
    },
    {
      key: "new",
      value: o.awaiting_investigation,
      en: "awaiting investigation",
      ar: "بانتظار التحقيق",
      title_en: "Detected exceptions not yet investigated.",
      title_ar: "استثناءات مكتشفة لم يُحقَّق فيها بعد.",
    },
    {
      key: "investigating",
      value: o.investigating,
      en: "investigating",
      ar: "قيد التحقيق",
      title_en: "Cases a worker is investigating now.",
      title_ar: "حالات يحقق فيها عامل الآن.",
    },
    {
      key: "pending",
      value: o.action_pending,
      en: "action pending",
      ar: "إجراء معلّق",
      title_en:
        "Investigated; a recommendation, approval, request or outcome is pending.",
      title_ar: "اكتمل التحقيق؛ توصية أو موافقة أو طلب أو نتيجة معلّقة.",
    },
    {
      key: "human",
      value: o.human_review,
      en: "with a person",
      ar: "لدى شخص",
      title_en: "Human review, escalated or rejected.",
      title_ar: "مراجعة بشرية أو مصعّدة أو مرفوضة.",
    },
    {
      key: "verified",
      value: o.verified_resolved,
      en: "verified resolved",
      ar: "حُلّت بتحقق",
      title_en: "Closed by the verifier or a person's verified finding.",
      title_ar: "أُغلقت بالمدقق أو بنتيجة بشرية متحقق منها.",
    },
  ];
  if (o.alerts_cleared_by_later_evidence > 0)
    items.push({
      key: "cleared",
      value: o.alerts_cleared_by_later_evidence,
      en: "alerts cleared by later evidence",
      ar: "تنبيهات زالت بأدلة لاحقة",
      title_en:
        "Open cases whose monitored symptoms are no longer found. Not resolved and not verified.",
      title_ar:
        "حالات مفتوحة لم تعد أعراضها المرصودة موجودة. ليست محلولة ولا متحققاً منها.",
    });
  return items;
}
