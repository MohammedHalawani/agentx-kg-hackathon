import type {
  AssistantContext,
  IntentResult,
  PageAction,
  ShipmentFilters,
  AuditFilters,
} from "@/domain/page-actions";
import type { OperationalCase } from "@/domain/types";
import { cityLocations } from "@/services/page-queries";

export function parsePageIntent(
  request: string,
  context: AssistantContext,
  cases: OperationalCase[],
  language: "en" | "ar" = "en",
): IntentResult {
  const text = request.toLowerCase().trim();
  const ar = language === "ar";
  if (
    /\b(approve|authorize|resolve|reject|execute)\b|موافقة|تفويض|حل الحالة/.test(
      text,
    )
  )
    return {
      actions: [],
      supported: false,
      explanation: ar
        ? "يغيّر هذا المساعد العرض والتصفية فقط. تتطلب القرارات التشغيلية استخدام عناصر الحالة وتسجيل تفويض صريح."
        : "This helper changes views and filters only. Operational decisions require the explicit case controls.",
    };
  if (/undo|تراجع/.test(text))
    return {
      actions: [],
      supported: false,
      explanation: ar
        ? "استخدم تراجع عن التصفية أدناه لاستعادة حالة الصفحة السابقة."
        : "Use Undo filters below to restore the previous page state.",
    };
  const actions: PageAction[] = [];
  const filters: Partial<ShipmentFilters> = {};
  const audit: Partial<AuditFilters> = {};
  const cityNames = Object.keys(cityLocations);
  const arabicNames: Record<string, string> = {
    Riyadh: "الرياض",
    Dammam: "الدمام",
    Khobar: "الخبر",
    Jeddah: "جدة",
    "Al Hofuf": "الهفوف",
    Buraydah: "بريدة",
  };
  for (const city of cityNames) {
    const name = city.toLowerCase();
    if (
      text.includes(`from ${name}`) ||
      text.includes(`من ${arabicNames[city]}`)
    )
      filters.origin = city;
    if (
      text.includes(`to ${name}`) ||
      text.includes(`destination ${name}`) ||
      text.includes(`heading to ${name}`) ||
      text.includes(`arrived in ${name}`) ||
      text.includes(`إلى ${arabicNames[city]}`) ||
      text.includes(`الى ${arabicNames[city]}`) ||
      text.includes(`وجهة ${arabicNames[city]}`)
    )
      filters.destination = city;
  }
  if (/needs? attention|exceptions|تحتاج.*انتباه/.test(text))
    filters.status = "attention";
  if (
    /delivery dispute|delivery confirmation dispute|اعتراضات التسليم|نزاع التسليم/.test(
      text,
    )
  )
    filters.cause = "delivery";
  if (/custody gap|missing custody|فجوة الحيازة|حيازة مفقودة/.test(text))
    filters.cause = "custody";
  if (/barcode|الباركود/.test(text)) filters.cause = "barcode";
  if (/weight|الوزن/.test(text)) filters.cause = "weight";
  if (/high priority|critical|أولوية عالية/.test(text))
    filters.priority = "high";
  if (/\bresolved\b|الحالات المحلولة/.test(text)) filters.status = "resolved";
  if (/this month|month|الشهر/.test(text)) audit.timeRange = "month";
  else if (/this week|week|الأسبوع/.test(text)) audit.timeRange = "week";
  else if (/today|اليوم/.test(text)) audit.timeRange = "today";
  if (/newest/.test(text)) audit.sort = "newest";
  if (/oldest|chronological/.test(text)) audit.sort = "oldest";
  if (/failed outcomes?|النتائج.*فشل|نتائج.*فاشلة/.test(text)) {
    audit.kind = "verification";
    audit.search = "failed";
  }
  if (/reviewer/.test(text)) audit.actor = "reviewer";
  if (/operator/.test(text)) audit.actor = "operator";
  const id = text.match(/shp-\d+/)?.[0].toUpperCase();
  if (id && !cases.some((c) => c.id === id))
    return {
      actions: [],
      supported: false,
      explanation: ar
        ? `الشحنة ${id} غير موجودة في بيانات المحاكاة. اختر شحنة متاحة.`
        : `${id} is not in the synthetic dataset. No shipment or evidence was invented.`,
    };
  const wantsAudit = /audit|events|records|histor|سجل|أحداث|الأحداث|تدقيق/.test(
    text,
  );
  if (context.page === "audit") {
    if (id) audit.shipmentId = id;
    if (Object.keys(filters).length || Object.keys(audit).length || id)
      actions.push({
        type: "filter_audit_events",
        filters: { ...filters, ...audit },
      });
    if (wantsAudit)
      actions.push({
        type: "change_view",
        view: /by shipment|timeline|حسب الشحنة|الخط الزمني/.test(text)
          ? "by_shipment"
          : "events",
      });
    else if (/shipments|heading to|الشحنات/.test(text))
      actions.push({ type: "change_view", view: "shipments" });
  } else {
    if (Object.keys(filters).length)
      actions.push({ type: "filter_shipments", filters });
    if (id) actions.push({ type: "select_shipment", caseId: id });
    if (/zoom|focus.*near|focus.*city|ركّز|ركز|تكبير/.test(text)) {
      const city = cityNames.find(
        (city) =>
          text.includes(city.toLowerCase()) || text.includes(arabicNames[city]),
      );
      if (city) actions.push({ type: "focus_map", city });
    }
    if (/highlight.*custody|أبرز.*حيازة/.test(text) && context.selectedCaseId) {
      const c = cases.find((c) => c.id === context.selectedCaseId);
      const evidence = c?.evidence
        .filter((e) => e.confidence === "confirmed")
        .at(-1);
      if (evidence)
        actions.push({
          type: "highlight_graph_evidence",
          evidenceId: evidence.id,
        });
    }
    if (/graph view|show.*graph|اعرض.*الرسم/.test(text))
      actions.push({ type: "change_view", view: "graph" });
    if (/map view|show.*map|اعرض.*الخريطة/.test(text))
      actions.push({ type: "change_view", view: "map" });
    if (/schema|المخطط/.test(text))
      actions.push({ type: "change_view", view: "schema" });
  }
  if (actions.length === 0)
    return {
      actions: [],
      supported: false,
      explanation: ar
        ? "جرّب: اعرض الشحنات من الرياض إلى الخبر، أو اعرض كل الأحداث للشحنة SHP-10482، أو اعرض النتائج التي فشل التحقق منها هذا الشهر. يستخدم المساعد قواعد محلية بسيطة وبيانات محاكاة."
        : "Supported examples: “Show shipments from Riyadh to Khobar”, “Show all events for SHP-10482”, “Show audits heading to Riyadh this month”, or “Show this month’s failed outcomes”. This is a deterministic UI helper, not a connected AI model.",
    };
  return {
    actions,
    supported: true,
    explanation: ar
      ? "تم تطبيق العرض والتصفية على بيانات المحاكاة المحلية."
      : "Applied validated, read-only page actions to the local synthetic dataset.",
  };
}
