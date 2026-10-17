import type { OperationalCase } from "@/domain/types";
import { caseQueueGroup } from "@/domain/investigation-workspace";
import {
  byRecordedPriority,
  EVIDENCE_STATES,
  OVERDUE_SYMPTOMS,
  PERSON_STATES,
} from "@/domain/priority";
import { displayId } from "@/domain/case-view";

/**
 * The Operations assistant: an operator's request about the queue, turned by fixed rules into
 * a visible, reversible view of the Operations table (filter, priority sort, highlight). It
 * reads only the cases the page has loaded from the backend, makes no model call and changes
 * nothing on the server: no record, no claim and no investigation schedule.
 */
export type ProblemKind =
  "barcode" | "weight" | "custody" | "delivery" | "address" | "delay";
export type OpsView =
  | { kind: "urgent"; limit: number }
  | { kind: "overdue" }
  | { kind: "problem"; problem: ProblemKind }
  | { kind: "custody_wait" }
  | { kind: "human" }
  | { kind: "priority"; priority: "high" | "medium" | "low" | "unknown" };

const PROBLEM_SYMPTOMS: Record<ProblemKind, string[]> = {
  barcode: ["BARCODE_READ_DIFFERS"],
  weight: ["WEIGHT_READ_DIFFERS"],
  custody: [
    "CUSTODY_TRANSFER_UNCONFIRMED",
    "CUSTODY_REPORTS_CONFLICT",
    "MANIFEST_CUSTODY_CONFLICT",
    "SESSION_END_UNRECONCILED",
  ],
  delivery: [
    "DELIVERY_PROOF_INCOMPLETE",
    "DELIVERY_ATTEMPT_FAILED",
    "RECIPIENT_REPORTED_NOT_RECEIVED",
  ],
  address: [],
  delay: ["MILESTONE_OVERDUE", "MILESTONE_LATE", "OVERDUE_AT_FACILITY"],
};
const PROBLEM_CAUSES: Record<ProblemKind, string[]> = {
  barcode: ["BARCODE_MISMATCH"],
  weight: ["WEIGHT_MISMATCH"],
  custody: [
    "CUSTODY_GAP",
    "UNRECONCILED_CUSTODY",
    "CONFLICTING_CUSTODY",
    "MANIFEST_CONFLICT",
  ],
  delivery: [
    "PROOF_INSUFFICIENT",
    "DELIVERY_DISPUTE",
    "POSSIBLE_MISDELIVERY",
    "RECIPIENT_UNAVAILABLE",
    "WRONG_GATE",
  ],
  address: ["ADDRESS_CONFLICT", "WRONG_GATE"],
  delay: [
    "MISSED_MILESTONE",
    "JOURNEY_DELAY",
    "HUB_DELAY",
    "ROUTE_DELAY",
    "TRAFFIC_DELAY",
    "SLA_RISK",
  ],
};
const PROBLEM_WORDS: [ProblemKind, RegExp][] = [
  ["barcode", /barcode|scan mismatch|باركود|الباركود/i],
  ["weight", /weigh|وزن|الوزن/i],
  ["address", /address|gate|عنوان|العنوان|بوابة/i],
  ["delivery", /deliver|proof|dispute|not received|تسليم|التسليم|إثبات|نزاع/i],
  ["custody", /custody|handover|حيازة|الحيازة|تسليم الطرد/i],
  ["delay", /delay|late|تأخ/i],
];
const PROBLEM_LABEL: Record<ProblemKind, [string, string]> = {
  barcode: ["barcode problems", "مشكلات الباركود"],
  weight: ["weight problems", "مشكلات الوزن"],
  custody: ["custody problems", "مشكلات الحيازة"],
  delivery: ["delivery and proof problems", "مشكلات التسليم وإثباته"],
  address: ["address problems", "مشكلات العنوان"],
  delay: ["delays", "حالات التأخير"],
};
const PRIORITY_WORDS: Record<
  "high" | "medium" | "low" | "unknown",
  [string, string]
> = {
  high: ["High", "المرتفعة"],
  medium: ["Medium", "المتوسطة"],
  low: ["Low", "المنخفضة"],
  unknown: ["Not set", "غير المحددة"],
};
const NUMBER_WORDS: Record<string, number> = {
  one: 1,
  two: 2,
  three: 3,
  four: 4,
  five: 5,
  six: 6,
  seven: 7,
  eight: 8,
  nine: 9,
  ten: 10,
  واحدة: 1,
  اثنتين: 2,
  ثلاث: 3,
  أربع: 4,
  خمس: 5,
  ست: 6,
  سبع: 7,
  ثماني: 8,
  تسع: 9,
  عشر: 10,
};

export type OpsIntent =
  { type: "view"; view: OpsView } | { type: "clear" } | { type: "unsupported" };

export function parseOpsRequest(text: string): OpsIntent {
  const q = text.trim().toLowerCase();
  if (!q) return { type: "unsupported" };
  if (
    /^(clear|reset|undo|show all|remove (the )?filter)|امسح|ألغ|تراجع|اعرض الكل/i.test(
      q,
    )
  )
    return { type: "clear" };
  if (
    /custody verif|waiting for custody|custody check|reconcil|تحقق الحيازة|التحقق من الحيازة|تسوية الحيازة/i.test(
      q,
    )
  )
    return { type: "view", view: { kind: "custody_wait" } };
  if (
    /human|person|manual|immediate|attention|يدوي|بشري|شخص|انتباه|فوري/i.test(q)
  )
    return { type: "view", view: { kind: "human" } };
  if (/overdue|past due|missed deadline|متأخرة|تجاوز|فات موعد/i.test(q))
    return { type: "view", view: { kind: "overdue" } };
  const level =
    /\b(high|medium|low)\b[- ]?priority|priority[: ]+(high|medium|low)|أولوية (مرتفعة|متوسطة|منخفضة)|الأولوية (المرتفعة|المتوسطة|المنخفضة)/i.exec(
      q,
    );
  if (level) {
    const word = (
      level[1] ??
      level[2] ??
      level[3] ??
      level[4] ??
      ""
    ).toLowerCase();
    const priority = /high|مرتفع/.test(word)
      ? "high"
      : /medium|متوسط/.test(word)
        ? "medium"
        : "low";
    return { type: "view", view: { kind: "priority", priority } };
  }
  if (/urgent|critical|priorit|important|أولوية|عاجل|إلحاح|حرج/i.test(q)) {
    const digits = /\b(\d{1,2})\b/.exec(q)?.[1];
    const word = Object.keys(NUMBER_WORDS).find((w) => q.includes(w));
    const limit = Math.min(
      25,
      Math.max(1, Number(digits ?? (word ? NUMBER_WORDS[word] : 5))),
    );
    return { type: "view", view: { kind: "urgent", limit } };
  }
  for (const [problem, words] of PROBLEM_WORDS)
    if (words.test(q))
      return { type: "view", view: { kind: "problem", problem } };
  return { type: "unsupported" };
}

const symptoms = (c: OperationalCase) => c.backend?.symptomCodes ?? [];
const causes = (c: OperationalCase) => c.backend?.causeCodes ?? [];

/** Whether one loaded case belongs to a view. Closed cases never do. */
export function inView(view: OpsView, c: OperationalCase): boolean {
  if (caseQueueGroup(c) !== "active") return false;
  const state = c.backend?.workflowState ?? "";
  switch (view.kind) {
    case "urgent":
      return true;
    case "priority":
      return c.priority === view.priority;
    case "overdue":
      return symptoms(c).some((s) => OVERDUE_SYMPTOMS.has(s));
    case "problem":
      return (
        symptoms(c).some((s) => PROBLEM_SYMPTOMS[view.problem].includes(s)) ||
        causes(c).some((s) => PROBLEM_CAUSES[view.problem].includes(s)) ||
        (!c.backend && c.scenario === view.problem)
      );
    case "custody_wait": {
      if (!EVIDENCE_STATES.has(state)) return false;
      const action = c.backend?.actionStatus?.actions[0];
      if (action)
        return (
          action.action_type === "INITIATE_CUSTODY_RECONCILIATION" ||
          action.operational_label === "AWAITING_CUSTODY_RECONCILIATION"
        );
      return (
        c.backend?.brief?.actions?.[0]?.action_type ===
        "INITIATE_CUSTODY_RECONCILIATION"
      );
    }
    case "human":
      return (
        PERSON_STATES.has(state) ||
        c.backend?.actionStatus?.human_decision_required === true
      );
  }
}

/** The view's rows: matching active cases, highest recorded priority first, oldest first within a priority. */
export function viewRows(view: OpsView, cases: readonly OperationalCase[]) {
  const rows = cases.filter((c) => inView(view, c)).sort(byRecordedPriority);
  return view.kind === "urgent" ? rows.slice(0, view.limit) : rows;
}

/** The chip text naming the applied view. */
export function viewLabel(view: OpsView): [string, string] {
  switch (view.kind) {
    case "urgent":
      return [
        `${view.limit} most urgent open cases`,
        `أكثر ${view.limit} حالات مفتوحة إلحاحاً`,
      ];
    case "priority":
      return [
        `Open ${PRIORITY_WORDS[view.priority][0]}-priority cases`,
        `الحالات المفتوحة ذات الأولوية ${PRIORITY_WORDS[view.priority][1]}`,
      ];
    case "overdue":
      return [
        "Cases with an overdue journey step",
        "حالات بها خطوة رحلة متأخرة",
      ];
    case "problem":
      return [
        `Open ${PROBLEM_LABEL[view.problem][0]}`,
        `${PROBLEM_LABEL[view.problem][1]} المفتوحة`,
      ];
    case "custody_wait":
      return ["Waiting for custody verification", "بانتظار التحقق من الحيازة"];
    case "human":
      return ["Need a person now", "تحتاج قرار شخص الآن"];
  }
}

/** The rule applied, stated so the operator can check it. */
export function viewRule(view: OpsView): [string, string] {
  switch (view.kind) {
    case "urgent":
      return [
        "Sorted by the priority the detector recorded (High, Medium, Low), oldest first within a priority.",
        "مرتبة حسب الأولوية التي سجلها نظام الرصد (مرتفع، متوسط، منخفض)، والأقدم أولاً ضمن الأولوية نفسها.",
      ];
    case "priority":
      return [
        "The priority the detector recorded for the case.",
        "الأولوية التي سجلها نظام الرصد للحالة.",
      ];
    case "overdue":
      return [
        "The monitor recorded an overdue milestone or an overdue stay at a facility.",
        "سجّل نظام المراقبة خطوة متأخرة أو بقاءً متأخراً في منشأة.",
      ];
    case "problem":
      return [
        "The monitor's symptom or the investigation's cause on record matches this problem.",
        "عرَض المراقبة أو السبب المسجل في التحقيق يطابق هذه المشكلة.",
      ];
    case "custody_wait":
      return [
        "A custody reconciliation request is out and its evidence has not been verified yet.",
        "أُرسل طلب تسوية حيازة ولم يُتحقق من أدلته بعد.",
      ];
    case "human":
      return [
        "The case is in human review, awaiting approval or escalated, or its action status requires a person's decision.",
        "الحالة قيد المراجعة البشرية أو بانتظار الموافقة أو مصعّدة، أو تتطلب حالة إجرائها قرار شخص.",
      ];
  }
}

export interface OpsAnswer {
  view: OpsView | null;
  text: [string, string];
  caseIds: string[];
}

/** The reply to one request, from the loaded cases only. */
export function answerOps(
  request: string,
  cases: readonly OperationalCase[],
): OpsAnswer {
  const intent = parseOpsRequest(request);
  if (intent.type === "clear")
    return {
      view: null,
      text: [
        "Filters cleared. The full queue is shown again.",
        "أُزيلت التصفية وعادت القائمة كاملة.",
      ],
      caseIds: [],
    };
  if (intent.type === "unsupported")
    return {
      view: null,
      caseIds: [],
      text: [
        "I can filter the queue for: the most urgent cases, overdue cases, a problem (barcode, weight, custody, delivery, address, delays), cases waiting for custody verification, or cases that need a person.",
        "يمكنني تصفية القائمة حسب: الحالات الأكثر إلحاحاً، أو المتأخرة، أو نوع المشكلة (باركود، وزن، حيازة، تسليم، عنوان، تأخير)، أو الحالات بانتظار التحقق من الحيازة، أو التي تحتاج قرار شخص.",
      ],
    };
  const rows = viewRows(intent.view, cases);
  const [label, labelAr] = viewLabel(intent.view);
  const list = rows
    .slice(0, 5)
    .map((c) => `${displayId(c)} (${PRIORITY_WORDS[c.priority][0]})`)
    .join(", ");
  const more = rows.length > 5 ? ` +${rows.length - 5}` : "";
  return {
    view: intent.view,
    caseIds: rows.map((c) => c.id),
    text: rows.length
      ? [
          `${label}: ${rows.length} in the loaded queue. ${list}${more}.`,
          `${labelAr}: ${rows.length} في القائمة المحملة. ${list}${more}.`,
        ]
      : [
          `${label}: none in the loaded queue.`,
          `${labelAr}: لا توجد في القائمة المحملة.`,
        ],
  };
}
