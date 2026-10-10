import type {
  CanopusBlock,
  CanopusReference,
  CanopusReply,
  CanopusRequest,
  CanopusService,
  CanopusSnapshotReader,
  CanopusStreamEvent,
} from "@/domain/canopus";
import { stages, type Scenario } from "@/domain/types";
import { timeLabel } from "@/lib/dates";
import { queryAudit } from "@/services/page-queries";
import { emptyAuditFilters } from "@/domain/page-actions";

const arabicDiagnosis: Record<Scenario, string> = {
  barcode:
    "قرأ الماسح رمزاً ثانوياً قديماً. يطابق وزن الطرد ومسح الحاوية المختومة هذه الشحنة، ويظل تأكيد الرمز الجديد مطلوباً.",
  weight:
    "سجل ميزان الوجهة 3.7 كغ مقابل 2.4 كغ عند المصدر. الختم سليم، ويلزم وزن معاير بإشراف موظف.",
  address:
    "يشير العنوان الوطني إلى الدمام بينما يوجه الملصق الطرد إلى الأحساء. موقع المركبة لا يثبت صحة تغيير العنوان.",
  custody:
    "مسح تسليم الطرد عند المغادرة مفقود. موقع المركبة قرب الأحساء لا يؤكد انتقال حيازة الطرد من مرفق المصدر.",
  contractor:
    "تتعارض حيازة الطرد المؤكدة في الأحساء مع إسناد المسار المباشر. يتطلب تعديل سجل المتعهد تفويض المشغل.",
  delivery:
    "يتضمن سجل محاولة التسليم وقتاً وموقع مركبة دون توقيع مستلم أو دليل خاص بالطرد. لا يمكن تأكيد التسليم.",
  failed:
    "قُبلت تعليمات النقل لكن لم يظهر مسح مستقل للطرد يثبت نجاح المعالجة. تحتاج الحالة متابعة إشراف الإرسال.",
  normal: "تتسق ملاحظات حيازة الطرد مع المسار المتوقع وإثبات التسليم المستقل.",
};
const arabicAction: Record<Scenario, string> = {
  barcode:
    "مطابقة رمز الطرد باستخدام مسح الحاوية الموثق ثم طلب مسح مغادرة جديد.",
  weight: "إبقاء الطرد بالمرفق وطلب إعادة وزن معايرة وصورة للختم بإشراف موظف.",
  address: "طلب تأكيد عنوان المستلم قبل السماح بتعديل وجهة التسليم.",
  custody:
    "طلب ملاحظة تسليم خاصة بالطرد من مشرف مرفق المصدر قبل تعديل سجل الحيازة.",
  contractor:
    "تسوية سجل المتعهد بالاستناد إلى مسح الأحساء وطلب نقل بإشراف إلى بوابة الوجهة.",
  delivery: "طلب إثبات تسليم موقع أو مسح مستقل يؤكد عودة الطرد إلى المستودع.",
  failed:
    "تصعيد المعالجة غير المثبتة وأدلة الحيازة إلى إشراف الإرسال للمتابعة.",
  normal: "الاحتفاظ بسلسلة الحيازة وإثبات التسليم الموثقين في سجل التدقيق.",
};
function localizedFacility(text: string) {
  return text.replace(
    /Al Ahsa|Al Hofuf|Riyadh|Dammam|Khobar|Jeddah|Buraydah|warehouse|sorting hub|gateway|delivery depot/gi,
    (word) =>
      ({
        "al ahsa": "الأحساء",
        "al hofuf": "الهفوف",
        riyadh: "الرياض",
        dammam: "الدمام",
        khobar: "الخبر",
        jeddah: "جدة",
        buraydah: "بريدة",
        warehouse: "المستودع",
        "sorting hub": "مركز الفرز",
        gateway: "البوابة",
        "delivery depot": "مستودع التسليم",
      })[word.toLowerCase()] ?? word,
  );
}
function pause(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted)
      return reject(new DOMException("Aborted", "AbortError"));
    const abort = () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", abort);
      resolve();
    }, ms);
    signal.addEventListener("abort", abort, { once: true });
  });
}

/** Entirely local: fixture selection and timed text fragments, with no network calls. */
export class MockCanopusService implements CanopusService {
  private failedRequests = new Set<string>();
  constructor(private readSnapshot: CanopusSnapshotReader) {}
  async *stream(
    request: CanopusRequest,
    { signal }: { signal: AbortSignal },
  ): AsyncIterable<CanopusStreamEvent> {
    const ar = request.language === "ar";
    yield {
      type: "activity",
      text: ar
        ? "قراءة سياق المحاكاة المختار…"
        : "Reading the selected synthetic context…",
    };
    await pause(180, signal);
    if (request.simulateFailure && !this.failedRequests.has(request.id)) {
      this.failedRequests.add(request.id);
      throw new Error(
        ar
          ? "تعذّر عرض إجابة المحاكاة. أعد المحاولة؛ لم تتغير أي حالة."
          : "The simulated response could not finish. Retry to continue; no case state changed.",
      );
    }
    const reply = this.respond(request);
    const chunks = reply.summary.match(/\S+(?:\s+|$)/g) ?? [reply.summary];
    for (let i = 0; i < chunks.length; i += 6) {
      if (signal.aborted) return;
      yield { type: "delta", text: chunks.slice(i, i + 6).join("") };
      await pause(55, signal);
    }
    yield { type: "complete", reply };
  }
  private respond(request: CanopusRequest): CanopusReply {
    const { cases, decisions, automatic } = this.readSnapshot();
    const ar = request.language === "ar",
      text = request.message.toLowerCase();
    const requestedId =
      text.match(/shp-\d+/)?.[0].toUpperCase() ?? request.context.caseId;
    const c = requestedId
      ? cases.find((item) => item.id === requestedId)
      : undefined;
    const reply: CanopusReply = {
      id: request.id,
      summary: "",
      blocks: [],
      source: "synthetic",
      context: request.context,
    };
    if (requestedId && !c) {
      reply.summary = ar
        ? `الشحنة ${requestedId} غير موجودة في بيانات المحاكاة. اختر شحنة متاحة للمتابعة.`
        : `${requestedId} is not in this synthetic workspace. Select an available shipment to continue.`;
      return reply;
    }
    if (!c) {
      const pending = cases.filter((item) => item.status === "human_review"),
        open = cases.filter((item) => item.status !== "resolved"),
        verified = cases.filter(
          (item) => item.outcome?.successful && item.status === "resolved",
        );
      reply.summary = ar
        ? "أنا كانوبس، مساعد العمليات في سهيل. هذه قراءة لبيانات مساحة المحاكاة الحالية."
        : "I’m Canopus, Suhail’s operations assistant. Here is the current synthetic workspace context.";
      if (request.context.screen === "audit") {
        const audit = queryAudit(
          this.readSnapshot(),
          { ...emptyAuditFilters, ...request.context.filters },
          0,
          10,
        );
        reply.blocks.push({
          kind: "observation",
          text: ar
            ? `يعرض سياق التدقيق الحالي ${audit.total} أحداث تخص ${audit.uniqueShipments} شحنات فريدة. تظل التصفية والفترة الزمنية المحددتان جزءاً من سياق الإجابة.`
            : `The current Audit filters match ${audit.total} events across ${audit.uniqueShipments} unique shipments. The selected date range and filters are included in this context.`,
          references: [
            {
              id: "filtered-audit",
              kind: "view",
              label: ar
                ? "عرض نتائج التدقيق الحالية"
                : "View current audit results",
              href: `/audit?${new URLSearchParams(request.context.filters)}`,
            },
          ],
        });
      }
      reply.blocks.push({
        kind: "observation",
        text: ar
          ? `${open.length} حالة مفتوحة، و${pending.length} بانتظار التفويض، و${verified.length} نتيجة تحققت بشكل مستقل.`
          : `${open.length} open cases; ${pending.length} awaiting authorization; ${verified.length} independently verified outcomes.`,
        references: open.slice(0, 3).map((item) => ({
          id: item.id,
          kind: "shipment",
          label: item.id,
          href: `/cases/${item.id}`,
        })),
      });
      reply.blocks.push({
        kind: "recommendation",
        text: ar
          ? "ابدأ بالحالات التي تتطلب مراجعة بشرية، وافحص أدلة الطرد قبل تفويض الإجراء المقترح."
          : "Review cases awaiting human authority. Inspect parcel-level evidence before authorizing the named proposed action.",
        references: pending.map((item) => ({
          id: `review-${item.id}`,
          kind: "decision",
          label: item.id,
          href: `/cases/${item.id}?section=assessment`,
        })),
      });
      reply.blocks.push({
        kind: "observation",
        text: ar
          ? `${automatic ? "التحقيق التلقائي مفعّل" : "بدء تحقيقات تلقائية جديدة متوقف مؤقتاً"}. تظل مراقبة الاستثناءات وفحوص المراجعة والتحقق الإلزامية نشطة في المحاكاة.`
          : `${automatic ? "Automatic investigation is running" : "New automatic investigations are paused"}. Exception monitoring and mandatory review and verification checks remain active in the simulation.`,
        references: [
          {
            id: "operations",
            kind: "view",
            label: ar ? "قائمة العمليات" : "Operations queue",
            href: "/operations",
          },
        ],
      });
      reply.blocks.push({
        kind: "outcome",
        verified: true,
        text: ar
          ? "تضم قائمة المحلولة نتائج تحققت بأدلة مستقلة فقط. يوضح سجل التدقيق مسار كل حالة."
          : "Resolved contains independently verified outcomes only. The audit timeline records each case’s evidence, authority, execution, and outcome.",
        references: [
          {
            id: "audit",
            kind: "timeline",
            label: ar ? "فتح سجل التدقيق" : "Open audit history",
            href: "/audit?timeRange=all",
          },
        ],
      });
      return reply;
    }
    const evidenceId = request.context.selectedEvidenceId;
    const selectedNode = c.nodes.find((n) => n.id === evidenceId);
    const selectedEvidence = c.evidence.find(
      (e) => e.id === evidenceId || e.id === selectedNode?.evidenceId,
    );
    const custody = c.evidence
      .filter((e) => e.confidence === "confirmed" && e.kind !== "gps")
      .at(-1)!;
    const evidence =
      /node|highlight|selected|عقدة|محدد/.test(text) && selectedEvidence
        ? selectedEvidence
        : custody;
    reply.context = { ...request.context, caseId: c.id };
    const stage = Math.max(
      0,
      Math.min(7, request.context.stage ?? c.run?.stage ?? 0),
    );
    const caseRef: CanopusReference = {
      id: c.id,
      kind: "shipment",
      label: c.id,
      href: `/cases/${c.id}`,
    };
    const observationRef: CanopusReference = {
      id: `evidence-${evidence.id}`,
      kind: "evidence",
      label: ar ? `دليل · ${evidence.time}` : evidence.label,
      href: `/cases/${c.id}?evidence=${evidence.id}`,
    };
    reply.summary = ar
      ? `هذا ملخص حالة ${c.id} من بيانات المحاكاة. تفصل الإجابة بين الملاحظات والتفسير والإجراء المقترح والنتيجة المتحققة.`
      : `Here is ${c.id} in the synthetic workflow. Observations, hypotheses, recommendations, decisions, and verified outcomes are kept separate.`;
    const blocks: CanopusBlock[] = [
      {
        kind: "observation",
        text: ar
          ? `${localizedFacility(evidence.facility)} · ${evidence.time} بتوقيت السعودية. ${evidence.confidence === "vehicle_only" ? "يؤكد هذا موقع المركبة فقط ولا يثبت حيازة الطرد." : evidence.confidence === "missing" ? "هذه ملاحظة مخططة أو مفقودة؛ لا تشكل دليلاً مؤكداً." : "تؤكد ملاحظة مستقلة خاصة بالطرد الحيازة في هذا المرفق."}`
          : `${evidence === custody ? `Last confirmed parcel custody: ${evidence.facility}. ` : ""}${evidence.label}: ${evidence.detail} (${evidence.time} AST).`,
        references: [caseRef, observationRef],
      },
    ];
    if (/stage|pipeline|مرحلة|سير العمل/.test(text))
      blocks.push({
        kind: "observation",
        text: ar
          ? `${stages[stage].arabic}. هذه هي المرحلة المحددة؛ حالة سير العمل الحالية: ${c.status === "resolved" ? "محلولة" : c.status === "human_review" ? "بانتظار تفويض المشغل" : "محاكاة قيد المتابعة"}.`
          : `${stages[stage].label}: ${stages[stage].detail} Current workflow: ${c.status.replaceAll("_", " ")}.`,
        references: [
          {
            id: `stage-${stage}`,
            kind: "stage",
            label: ar ? stages[stage].arabic : stages[stage].label,
            href: `/cases/${c.id}?stage=${stage}`,
          },
        ],
      });
    blocks.push({
      kind: "hypothesis",
      text: ar ? arabicDiagnosis[c.scenario] : c.diagnosis,
      references: [
        {
          id: "diagnose",
          kind: "stage",
          label: ar ? "مرحلة التشخيص" : "Diagnose stage",
          href: `/cases/${c.id}?stage=2`,
        },
      ],
    });
    blocks.push({
      kind: "recommendation",
      text: ar
        ? `${arabicAction[c.scenario]} ${c.recommendation.authority === "operator" ? "يتطلب هذا تفويضاً صريحاً من المشغل وفق السياسة C-04." : c.recommendation.authority === "evidence" ? "يلزم دليل إضافي قبل أي إجراء." : "الإجراء محدود المخاطر ومتاح للتحقيق التلقائي المحاكى."}`
        : `${c.recommendation.title}. ${c.recommendation.detail} ${c.recommendation.authority === "operator" ? "Explicit operator authority is required under policy C-04." : c.recommendation.authority === "evidence" ? "Additional independent evidence is required." : "Eligible for the low-risk automatic simulation."}`,
      references: [
        {
          id: "recommendation",
          kind: "decision",
          label: ar ? "فحص الإجراء المقترح" : "Review proposed action",
          href: `/cases/${c.id}?section=assessment`,
        },
      ],
    });
    const decision = decisions.find((d) => d.caseId === c.id);
    blocks.push({
      kind: "decision",
      text: decision
        ? `${ar ? { approved: "مفوّض", rejected: "مرفوض", escalated: "تم التصعيد" }[decision.verdict] : decision.verdict} · ${decision.actor} · ${timeLabel(decision.timestamp)} AST. ${decision.reason}`
        : ar
          ? "لم يسجل مشغل قراراً لهذه الحالة. لا تُفوّض الدردشة أي إجراء ولا تغيّر حالة الشحنة."
          : "No operator decision has been recorded. Chat cannot authorize, execute, or resolve a case; use the explicit case controls.",
      references: [
        {
          id: "decisions",
          kind: "decision",
          label: ar ? "القرارات وسجل الصلاحية" : "Decisions & authority",
          href: `/decisions?case=${c.id}`,
        },
      ],
    });
    blocks.push({
      kind: "outcome",
      verified: c.status === "resolved" && c.outcome?.successful === true,
      text: ar
        ? c.outcome?.successful
          ? "أكد دليل مستقل نتيجة المعالجة. انتقلت الحالة إلى المحلولة بعد التحقق."
          : c.outcome?.successful === false
            ? "فشل التحقق من النتيجة. تظل الحالة غير محلولة وتحتاج متابعة بشرية."
            : "لم تتحقق نتيجة المعالجة بعد. التوصية والتفويض والتنفيذ وحدها لا تؤكد نجاح النتيجة."
        : (c.outcome?.detail ??
          "No independently verified outcome yet. A recommendation, authorization, or execution receipt alone does not establish success."),
      references: [
        {
          id: "timeline",
          kind: "timeline",
          label: ar ? "فتح الخط الزمني" : "Open shipment timeline",
          href: `/audit?case=${c.id}&mode=by_shipment&timeRange=all`,
        },
        ...(c.outcome?.evidenceIds ?? [])
          .filter((id) => c.evidence.some((e) => e.id === id))
          .map((id): CanopusReference => ({
            id: `proof-${id}`,
            kind: "outcome",
            label: ar ? "دليل النتيجة" : "Outcome evidence",
            href: `/cases/${c.id}?evidence=${id}&stage=7`,
          })),
      ],
    });
    reply.blocks = blocks;
    // The floating conversation leads with the relevant fixture answer; details stay expandable.
    if (
      /node|highlight|selected|عقدة|محدد|custody|where|location|evidence|حيازة|أين|موقع|أدلة/.test(
        text,
      )
    ) {
      reply.summary = blocks[0].text;
    } else if (
      request.participant === "reviewer" ||
      /approval|authority|review|تفويض|موافق|مراجعة/.test(text)
    ) {
      reply.summary = blocks.find(
        (block) => block.kind === "recommendation",
      )!.text;
    } else if (/stage|pipeline|مرحلة|سير العمل/.test(text)) {
      reply.summary = blocks.find(
        (block) =>
          block.kind === "observation" &&
          block.references.some((ref) => ref.kind === "stage"),
      )!.text;
    } else if (/outcome|verif|execution|نتيجة|تحقق|تنفيذ/.test(text)) {
      reply.summary = blocks.find((block) => block.kind === "outcome")!.text;
    } else {
      reply.summary = ar ? arabicDiagnosis[c.scenario] : c.diagnosis;
    }
    if (
      /\b(approve|authorize|resolve|reject|execute)\b|فوّض|وافق|حل الحالة/.test(
        text,
      )
    )
      reply.summary = ar
        ? "الدردشة للشرح والقراءة فقط. استخدم عناصر الحالة لتسجيل قرار صريح مع سببه."
        : "Canopus is read-only in this lab. Use the case controls to record an explicit decision and its reason.";
    return reply;
  }
}
