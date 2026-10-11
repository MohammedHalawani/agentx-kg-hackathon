import { useEffect, useState } from "react";
import {
  Link,
  Navigate,
  useLocation,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { useGroupRef } from "react-resizable-panels";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Clock3,
  Columns2,
  Maximize2,
  MapPin,
  MessageSquare,
  Network,
  Package,
  ScanSearch,
  ShieldCheck,
  X,
  AlertTriangle,
  FileSearch,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbSeparator,
  BreadcrumbPage,
} from "@/components/ui/breadcrumb";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { ScrollArea } from "@/components/ui/scroll-area";
import { RouteMap } from "@/components/route-map";
import { KnowledgeGraph } from "@/components/knowledge-graph";
import { DecisionDialog } from "@/components/decision-dialog";
import { StatusBadge, PriorityLabel, EmptyState } from "@/components/shared";
import { dateTimeLabel, secondsLabel, timeLabel } from "@/lib/dates";
import { InvestigatorFindings } from "@/components/investigator-findings";
import { InvestigationRecord } from "@/components/investigation-record";
import { NextStep } from "@/components/next-step";
import { CaseAssessment } from "@/components/case-assessment";
import { NarrationStrip } from "@/components/narration";
import { explainStage, type StageState } from "@/domain/stage-explain";
import { HumanOutcomeDialog } from "@/components/human-outcome-dialog";
import {
  stages,
  type AuthorityDecision,
  type OperationalCase,
} from "@/domain/types";
import { authorityLabel, controls, displayId } from "@/domain/case-view";
import { useOperations } from "@/state/operations";
import { usePreferences } from "@/state/preferences";
import { useMediaQuery } from "@/hooks/use-media-query";
import { useCanopus, useCanopusScreen } from "@/state/canopus";
const LAB_BUILD = import.meta.env.VITE_SUHAIL_DATA === "lab";

/** Backend cases: the first evidence the recorded stage cited that this screen can show. */
function stageTarget(c: OperationalCase, index: number) {
  const ids = c.backend?.stageEvidence[index] ?? [];
  return (
    ids.find((id) => c.evidence.some((e) => e.id === id)) ??
    ids.find((id) => c.nodes.some((n) => n.id === id)) ??
    null
  );
}
export function InvestigationPage() {
  const { caseId } = useParams();
  const { key: navigationKey } = useLocation();
  const [params] = useSearchParams();
  const {
    cases,
    unlisted,
    events,
    decisions,
    service,
    connection,
    backend: fromBackend,
  } = useOperations();
  // Connected build: always the backend, so lab-only branches are removed at build time.
  const backend = !LAB_BUILD || fromBackend;
  const { t, preferences } = usePreferences();
  const canopus = useCanopus();
  const c =
    cases.find((c) => c.id === caseId) ??
    unlisted?.find((c) => c.id === caseId);
  // Lab fixtures open on a known marker; backend evidence has no predetermined focus.
  const [selected, setSelected] = useState<string | null>(
    backend ? null : "warehouse",
  );
  const [relationship, setRelationship] = useState<string | null>(null);
  const [previewStage, setPreviewStage] = useState<number | null>(null);
  // The narration message whose cited records are lit in the graph.
  const [narrated, setNarrated] = useState<{
    id: string | null;
    ids: string[];
  }>({
    id: null,
    ids: [],
  });
  const [split, setSplit] = useState(50);
  const [verdict, setVerdict] = useState<AuthorityDecision["verdict"] | null>(
    null,
  );
  const [details, setDetails] = useState(false);
  const [humanOutcome, setHumanOutcome] = useState(false);
  const groupRef = useGroupRef();
  const smallCanvas = useMediaQuery("(max-width:767px)");
  const requestedEvidence = params.get("evidence");
  const evidenceIsValid = !!c?.evidence.some((e) => e.id === requestedEvidence);
  const requestedStage = params.has("stage")
    ? Number(params.get("stage"))
    : null;
  const stageIsValid =
    requestedStage !== null &&
    Number.isInteger(requestedStage) &&
    requestedStage >= 0 &&
    requestedStage <= 7;
  // Backend: hold the case open so its evidence loads and its recorded stages stream in.
  // A link may carry a shipment id; cases are addressed by case id, so it is redirected.
  const alias = backend
    ? cases.find((item) => item.id !== caseId && item.shipment.id === caseId)
    : undefined;
  const watchId = alias ? null : caseId;
  useEffect(
    () => (watchId ? service.watchCase?.(watchId) : undefined),
    [watchId, service],
  );
  const labStageEvidence = [
    "origin",
    "package",
    c?.scenario === "custody" ? "handover" : "warehouse",
    "shipment",
    "recommendation",
    "recommendation",
    "gps",
    c?.evidence.some((e) => e.id === "recovery") ? "recovery" : "destination",
  ][requestedStage ?? 0];
  const stageEvidence = c?.backend
    ? stageTarget(c, requestedStage ?? 0)
    : labStageEvidence;
  const requestedSection = params.get("section");
  useCanopusScreen({
    screen: "investigation",
    caseId: c?.id,
    selectedEvidenceId: selected,
    stage: previewStage ?? c?.run?.stage ?? 0,
  });
  useEffect(() => {
    setSelected(backend ? null : "warehouse");
    setRelationship(null);
    setPreviewStage(null);
    setSplit(50);
    groupRef.current?.setLayout({ map: 50, graph: 50 });
  }, [caseId, groupRef, backend]);
  // Canopus (in its panel) asks this page to show records or open the approval dialog. Both
  // use the paths the page already has; nothing is decided from there.
  useEffect(() => {
    const show = (event: Event) => {
      const detail = (event as CustomEvent<{ caseId: string; ids: string[] }>)
        .detail;
      if (detail?.caseId !== caseId) return;
      setSelected(null);
      setRelationship(null);
      setNarrated({ id: null, ids: detail.ids });
    };
    const authorize = (event: Event) => {
      const detail = (event as CustomEvent<{ caseId: string }>).detail;
      if (detail?.caseId === caseId) setVerdict("approved");
    };
    window.addEventListener("suhail:graph-highlight", show);
    window.addEventListener("suhail:authorize", authorize);
    return () => {
      window.removeEventListener("suhail:graph-highlight", show);
      window.removeEventListener("suhail:authorize", authorize);
    };
  }, [caseId]);
  const detailsOpenFor = details ? caseId : null;
  useEffect(() => {
    // The case activity list reads the audit ledger; load it when the assessment opens.
    if (detailsOpenFor) void service.loadAudit?.();
  }, [detailsOpenFor, service]);
  useEffect(() => {
    if (stageIsValid) {
      setPreviewStage(requestedStage);
      setSelected(stageEvidence);
    }
    if (evidenceIsValid) {
      setSelected(requestedEvidence);
      setRelationship(null);
    }
    if (requestedSection === "assessment") setDetails(true);
  }, [
    caseId,
    requestedEvidence,
    evidenceIsValid,
    requestedStage,
    stageIsValid,
    stageEvidence,
    requestedSection,
    navigationKey,
  ]);
  if (alias) return <Navigate to={`/cases/${alias.id}`} replace />;
  const missing =
    c?.backend && !c.backend.detailLoaded && c.backend.detailError;
  if (c?.backend && !c.backend.detailLoaded && !missing && !c.shipment.id)
    return (
      <EmptyState
        title={t(
          "Loading the case from the backend…",
          "جارٍ تحميل الحالة من الخادم…",
        )}
        description={t(
          "Evidence, recorded stages and decisions are read from the Suhail backend.",
          "تُقرأ الأدلة والمراحل المسجلة والقرارات من خادم سهيل.",
        )}
      />
    );
  if (!c || (missing && !c.shipment.id))
    return (
      <>
        <EmptyState
          title={
            backend
              ? t("Case not available", "الحالة غير متاحة")
              : t("Shipment not found", "لم يتم العثور على الشحنة")
          }
          description={
            backend
              ? (c?.backend?.detailError ??
                t(
                  "The backend has no case with this identifier.",
                  "لا توجد لدى الخادم حالة بهذا المعرف.",
                ))
              : t(
                  "This shipment is not part of the local simulation.",
                  "هذه الشحنة غير موجودة في المحاكاة المحلية.",
                )
          }
        />
        <Button asChild>
          <Link to="/operations">
            {t("Back to operations", "العودة إلى العمليات")}
          </Link>
        </Button>
      </>
    );
  const stage = previewStage ?? c.run?.stage ?? 0;
  const evidence = c.evidence.find((e) => e.id === selected);
  const entity = c.nodes.find(
    (n) => n.id === selected || n.evidenceId === selected,
  );
  const edge = c.relationships.find((e) => e.id === relationship);
  // Lab: one simulated run at a time. Backend: the server decides and refuses if it must.
  const active =
    !backend &&
    cases.some((c) =>
      ["investigating", "executing", "verifying"].includes(c.status),
    );
  const can = controls(c);
  // The backend investigates one case at a time.
  const busyElsewhere =
    !!connection?.worker?.activeCaseId &&
    connection.worker.activeCaseId !== c.id;
  const authority = authorityLabel(c);
  const lastCustody = c.evidence
    .filter((e) => e.confidence === "confirmed" && e.kind !== "gps")
    .at(-1);
  const caseEvents = events.filter((e) => e.caseId === c.id);
  const select = (id: string) => {
    setSelected(id);
    setRelationship(null);
  };
  const act = (fn: () => void | Promise<void>) => {
    try {
      void Promise.resolve(fn()).catch((e: Error) => toast.error(e.message));
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  function focus(value: number) {
    setSplit(value);
    groupRef.current?.setLayout({ map: value, graph: 100 - value });
  }
  function inspectStage(index: number) {
    setPreviewStage(index);
    if (c?.backend) {
      // Highlight what the recorded stage actually cited, or nothing.
      const target = stageTarget(c, index);
      if (target) select(target);
      else {
        setSelected(null);
        setRelationship(null);
      }
      return;
    }
    if (index === 0) select("origin");
    if (index === 1) select("package");
    if (index === 2)
      select(c?.scenario === "custody" ? "handover" : "warehouse");
    if (index === 3) select("shipment");
    if (index === 4 || index === 5) select("recommendation");
    if (index === 6) select("gps");
    if (index === 7)
      select(
        c?.evidence.some((e) => e.id === "recovery")
          ? "recovery"
          : "destination",
      );
  }
  /** Where a pipeline step stands, from the backend's recorded run and outcome. */
  const stageState = (i: number): StageState => {
    if (!c.run) return "queued";
    const recorded = c.backend?.stageStatus?.[i];
    // A step the backend recorded as failed or degraded did not produce its result.
    if (i <= c.run.stage && (recorded === "DEGRADED" || recorded === "FAILED"))
      return "failed";
    if (c.status === "resolved" || i < c.run.stage) return "completed";
    if (i !== c.run.stage) return "queued";
    // The authorized request could not be delivered: a genuine failure of the step.
    if (i === 6 && !!c.backend && !!c.execution && !c.execution.successful)
      return "failed";
    // Routed to a person, awaiting approval, escalated, or checked and not confirmed: the
    // workflow did what it should. These wait on someone; they are not failures.
    if (
      c.status === "escalated" ||
      ["human_review", "needs_evidence"].includes(c.status) ||
      (i === 7 &&
        !!c.backend?.verification &&
        c.backend.verification.result !== "confirmed")
    )
      return "waiting";
    return "running";
  };
  /** What a waiting or failed step is waiting on, in the case's own recorded terms. */
  const stageNote = (i: number, state: StageState): [string, string] | null => {
    if (!c.backend) return null;
    if (state === "failed")
      return i === 6 && c.execution && !c.execution.successful
        ? ["Request not delivered", "لم يُسلّم الطلب"]
        : ["No result recorded", "لا نتيجة مسجلة"];
    if (state !== "waiting") return null;
    const verification = c.backend.verification;
    if (i === 7 && verification)
      return verification.result === "unanswered"
        ? ["Executed · no answer, not verified", "نُفذ · بلا إجابة، غير متحقق"]
        : verification.result === "exception_remains"
          ? ["Executed · exception remains", "نُفذ · الاستثناء باقٍ"]
          : verification.result === "finding"
            ? ["Person's finding · not resolved", "نتيجة بشرية · غير محلولة"]
            : [
                "Executed · not verified as resolved",
                "نُفذ · لم يُتحقق من الحل",
              ];
    if (c.status === "escalated")
      return ["Escalated to a person", "صُعّدت إلى شخص"];
    if (c.backend.allowed.approve)
      return ["Awaiting your approval", "بانتظار موافقتك"];
    if (c.status === "needs_evidence") return ["Needs evidence", "تحتاج أدلة"];
    return ["Routed to a person", "أُحيلت إلى شخص"];
  };
  /**
   * One short line per pipeline step for a backend case, saying what the step did. Every line
   * is read from the case's records (stage events, finding, review, authority, execution,
   * outcome); a step that has not run shows nothing.
   */
  const stageShort = (
    i: number,
    state: StageState,
  ): [string, string] | null => {
    const b = c.backend;
    if (!b || state === "queued") return null;
    const note = stageNote(i, state);
    if (note && i >= 6) return note;
    const recorded = b.stageDetail[i] ?? "";
    const words = (code: string | null | undefined) =>
      (code ?? "").replaceAll("_", " ").toLowerCase();
    const clip = (text: string, max = 46) =>
      text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text;
    if (state === "failed") return ["No result recorded", "لا نتيجة مسجلة"];
    const running = state === "running";
    switch (i) {
      case 0:
        return running
          ? ["Collecting evidence", "جمع الأدلة"]
          : ["Evidence collected", "جُمعت الأدلة"];
      case 1: {
        const count = /(\d+) nodes/.exec(recorded)?.[1];
        return running
          ? ["Examining connections", "فحص الروابط"]
          : count
            ? [
                `${count} linked records examined`,
                `فُحص ${count} سجلاً مرتبطاً`,
              ]
            : ["Connections examined", "فُحصت الروابط"];
      }
      case 2: {
        if (running) {
          const tool = /^Investigator queried ([^:]+)/.exec(recorded)?.[1];
          return tool
            ? [`Checking ${tool}`, `فحص ${tool}`]
            : ["Investigating", "جارٍ التحقيق"];
        }
        const finding = b.investigation;
        if (b.investigationLog?.degraded.length && !b.diagnosisAvailable)
          return ["No conclusion reached", "لم يُتوصل إلى استنتاج"];
        if (finding?.primaryCause)
          return finding.accepted
            ? [
                `Suspected cause: ${words(finding.primaryCause)}`,
                `السبب المرجح: ${words(finding.primaryCause)}`,
              ]
            : [
                `Suspected: ${words(finding.primaryCause)} (challenged)`,
                `مرجح: ${words(finding.primaryCause)} (اعتُرض عليه)`,
              ];
        return ["Cause assessed", "قُيّم السبب"];
      }
      case 3: {
        const count = /(\d+) verified precedents/.exec(recorded)?.[1];
        return running
          ? ["Checking similar cases", "مراجعة حالات مشابهة"]
          : count
            ? [`${count} similar cases checked`, `رُوجعت ${count} حالات مشابهة`]
            : ["Similar cases checked", "رُوجعت حالات مشابهة"];
      }
      case 4:
        return running
          ? ["Choosing an action", "اختيار إجراء"]
          : c.recommendation.available
            ? [
                clip(`Proposed: ${c.recommendation.title}`),
                clip(`مقترح: ${c.recommendation.title}`),
              ]
            : ["No action proposed", "لم يُقترح إجراء"];
      case 5: {
        if (running) return ["Independent review", "مراجعة مستقلة"];
        const verdict = (b.review?.verdict ?? "").toLowerCase();
        return verdict === "accept"
          ? ["Reviewer accepted", "قبِل المراجع"]
          : verdict
            ? ["Reviewer challenged it", "اعترض المراجع"]
            : ["Review recorded", "سُجلت المراجعة"];
      }
      case 6:
        return running
          ? ["Deciding who acts", "تحديد من يتصرف"]
          : c.execution
            ? ["Action dispatched", "أُرسل الإجراء"]
            : ["Decided by policy", "قررته السياسة"];
      default:
        return running || c.status === "verifying"
          ? ["Awaiting evidence", "بانتظار الأدلة"]
          : c.status === "resolved"
            ? ["Verified: resolved", "تم التحقق: حُلّت"]
            : null;
    }
  };
  return (
    <>
      <Breadcrumb className="mb-4">
        <BreadcrumbList className="text-xs">
          <BreadcrumbItem>
            <BreadcrumbLink asChild>
              <Link to="/operations" className="flex items-center gap-1">
                <ArrowLeft size={12} />
                {t("Operations", "العمليات")}
              </Link>
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage dir="ltr">{displayId(c)}</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>
      <div className="case-title">
        <div>
          <div className="case-heading">
            <h1>{displayId(c)}</h1>
            <StatusBadge status={c.status} c={c} />
            <PriorityLabel priority={c.priority} />
          </div>
          <p>
            {c.backend && (
              <>
                <span dir="ltr" title={t("Case identifier", "معرف الحالة")}>
                  {t("Case", "الحالة")} {c.id.replace(/^SYN-OPS-CASE-/, "")}
                </span>
                <i>·</i>
              </>
            )}
            {c.issue}
            <i>·</i>
            {c.shipment.origin}
            <ArrowRight size={12} />
            {c.shipment.destination}
          </p>
        </div>
        <div className="case-top-actions">
          <Button variant="outline" size="sm" onClick={() => setDetails(true)}>
            <Package size={14} />
            {t("Case details", "تفاصيل الحالة")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              canopus.open({
                screen: "investigation",
                caseId: c.id,
                selectedEvidenceId: selected,
                stage,
              })
            }
          >
            <MessageSquare size={14} />
            {t("Ask Suhail", "اسأل سهيل")}
          </Button>
          {can.investigate && (
            <Button
              size="sm"
              disabled={active || busyElsewhere}
              title={
                busyElsewhere
                  ? t(
                      "The backend is investigating another case; it runs one at a time.",
                      "يحقق الخادم في حالة أخرى؛ يعمل على حالة واحدة في كل مرة.",
                    )
                  : undefined
              }
              onClick={() =>
                act(() => {
                  setPreviewStage(null);
                  return service.investigate(c.id);
                })
              }
            >
              <ScanSearch size={14} />
              {t("Investigate now", "التحقيق الآن")}
            </Button>
          )}
        </div>
      </div>
      <section className="pipeline surface" aria-label="Investigation pipeline">
        <div className="pipeline-meta">
          <b>{t("Investigation pipeline", "مسار التحقيق")}</b>
          <span>
            {c.status === "resolved"
              ? t("Verified · completed", "تحقق · مكتمل")
              : c.backend && !c.backend.detailLoaded
                ? (c.backend.detailError ??
                  t(
                    "Loading evidence from the backend…",
                    "جارٍ تحميل الأدلة من الخادم…",
                  ))
                : c.backend?.verification &&
                    c.backend.verification.result !== "confirmed"
                  ? c.backend.verification.result === "failed"
                    ? t(
                        "Request delivered and answered · not confirmed · with a person",
                        "سُلّم الطلب وأُجيب · لم يتأكد · لدى شخص",
                      )
                    : c.backend.verification.result === "unanswered"
                      ? t(
                          "Request delivered · no answer by the deadline · with a person",
                          "سُلّم الطلب · لا إجابة حتى الموعد النهائي · لدى شخص",
                        )
                      : c.backend.verification.result === "exception_remains"
                        ? t(
                            "Action verified · the exception remains · with a person",
                            "تم التحقق من الإجراء · الاستثناء باقٍ · لدى شخص",
                          )
                        : t(
                            "A person's finding is on record · case still open",
                            "نتيجة فحص بشري مسجلة · الحالة ما زالت مفتوحة",
                          )
                  : c.backend?.investigationLog?.degradedKinds.includes(
                        "turn_budget_exhausted",
                      )
                    ? t(
                        "The investigator reached no conclusion within its turn budget · no diagnosis · with a person",
                        "لم يصل المحقق إلى استنتاج ضمن عدد أدواره · لا تشخيص · لدى شخص",
                      )
                    : c.backend?.investigationLog?.degradedKinds.includes(
                          "snapshot_changed",
                        )
                      ? t(
                          "Evidence changed during the investigation · a person must review the latest evidence",
                          "تغيرت الأدلة أثناء التحقيق · على شخص مراجعة أحدث الأدلة",
                        )
                      : c.backend?.investigationLog?.degradedKinds.includes(
                            "model_unavailable",
                          ) && !c.backend.diagnosisAvailable
                        ? t(
                            "The model was unavailable · no investigation result · with a person",
                            "النموذج غير متاح · لا نتيجة تحقيق · لدى شخص",
                          )
                        : c.backend?.investigationLog?.degraded.length &&
                            !c.backend.diagnosisAvailable
                          ? t(
                              "The model's reply could not be used · no diagnosis · with a person",
                              "تعذر استخدام رد النموذج · لا تشخيص · لدى شخص",
                            )
                          : c.execution && !c.execution.successful
                            ? t(
                                "The request could not be delivered · nothing carried out · with a person",
                                "تعذر تسليم الطلب · لم يُنفذ شيء · لدى شخص",
                              )
                            : c.backend?.workflowState === "HUMAN_REVIEW"
                              ? c.backend.authority?.ruleId
                                ? t(
                                    `Routed to a person by policy rule ${c.backend.authority.ruleId} · the agent's finding is not verified`,
                                    `أُحيلت إلى شخص بقاعدة السياسة ${c.backend.authority.ruleId} · استنتاج الوكيل غير متحقق منه`,
                                  )
                                : t(
                                    "Waiting for a person to investigate",
                                    "بانتظار تحقيق بشري",
                                  )
                              : c.status === "human_review"
                                ? t(
                                    "Waiting for operator authority",
                                    "بانتظار صلاحية المشغل",
                                  )
                                : c.status === "needs_evidence"
                                  ? t(
                                      "Blocked · independent evidence needed",
                                      "متوقف · يحتاج أدلة مستقلة",
                                    )
                                  : c.status === "escalated"
                                    ? t(
                                        "Escalated · manual follow-up",
                                        "تم التصعيد · متابعة بشرية",
                                      )
                                    : c.backend?.supersededRunId &&
                                        c.status === "queued"
                                      ? t(
                                          "Queued for re-investigation · the earlier run is superseded",
                                          "في انتظار إعادة التحقيق · التحقيق السابق لم يعد سارياً",
                                        )
                                      : c.run
                                        ? backend
                                          ? c.status === "investigating"
                                            ? `${
                                                c.backend?.repairing
                                                  ? t(
                                                      "Model reply invalid, retrying · no diagnosis is substituted",
                                                      "رد النموذج غير صالح، إعادة المحاولة · لا يُستبدل تشخيص",
                                                    )
                                                  : t(
                                                      "Investigation in progress",
                                                      "التحقيق جارٍ",
                                                    )
                                              }${
                                                c.backend?.stageElapsed?.[
                                                  c.run.stage
                                                ] !== undefined
                                                  ? ` · ${secondsLabel(c.backend.stageElapsed[c.run.stage])}`
                                                  : ""
                                              }`
                                            : c.status === "verifying"
                                              ? c.backend?.expectedResponseAt
                                                ? t(
                                                    `Request delivered · an answer is scheduled for ${dateTimeLabel(c.backend.expectedResponseAt)}`,
                                                    `سُلّم الطلب · إجابة مجدولة عند ${dateTimeLabel(c.backend.expectedResponseAt)}`,
                                                  )
                                                : c.backend
                                                      ?.verificationDeadline
                                                  ? t(
                                                      `Request delivered · answer expected by ${dateTimeLabel(c.backend.verificationDeadline)}`,
                                                      `سُلّم الطلب · الإجابة متوقعة قبل ${dateTimeLabel(c.backend.verificationDeadline)}`,
                                                    )
                                                  : t(
                                                      "Executed · awaiting independent verification",
                                                      "نُفذ · بانتظار التحقق المستقل",
                                                    )
                                              : c.backend?.timing
                                                    ?.totalSeconds != null
                                                ? t(
                                                    `Recorded run · investigated in ${secondsLabel(c.backend.timing.totalSeconds)}`,
                                                    `تحقيق مسجل · استغرق ${secondsLabel(c.backend.timing.totalSeconds)}`,
                                                  )
                                                : t(
                                                    "Recorded run",
                                                    "تحقيق مسجل",
                                                  )
                                          : t(
                                              "Simulated run in progress",
                                              "تحقيق محاكى جارٍ",
                                            )
                                        : t("Queued", "في الانتظار")}
          </span>
          {previewStage !== null && previewStage !== (c.run?.stage ?? 0) && (
            <Button
              className="follow-button"
              variant="ghost"
              size="sm"
              onClick={() => {
                // Back to the step the case is on now, brought into view.
                setPreviewStage(null);
                setNarrated({ id: null, ids: [] });
                requestAnimationFrame(() =>
                  document
                    .querySelector(".pipeline-step.selected")
                    ?.scrollIntoView({
                      block: "nearest",
                      inline: "center",
                      behavior: "smooth",
                    }),
                );
              }}
            >
              {t("Follow current stage", "تتبع المرحلة الحالية")}
            </Button>
          )}
        </div>
        <div
          className={`pipeline-stages ${c.backend ? "connected" : ""}`}
          style={
            {
              // How far the case has come, for the connecting line (from the recorded step).
              "--progress": c.run
                ? c.status === "resolved"
                  ? 1
                  : Math.min(1, (c.run.stage + 0.5) / stages.length)
                : 0,
            } as React.CSSProperties
          }
        >
          {stages.map((s, i) => {
            const state = stageState(i);
            // What this step did or is doing, from the case's records where they exist.
            const explanation = explainStage(c, i, state);
            // One short line of what the step did, from the case's records.
            const fact =
              state === "queued" ? undefined : c.backend?.stageFacts?.[i];
            const short: [string, string] | null = fact
              ? [fact.en, fact.ar ?? fact.en]
              : stageShort(i, state);
            return (
              <Button
                variant="ghost"
                key={s.label}
                className={`pipeline-step state-${state} ${stage === i ? "selected" : ""} ${explanation || short ? "explained" : ""}`}
                aria-pressed={stage === i}
                aria-label={`${i === 6 && c.backend ? "Disposition" : s.label} · ${state}`}
                title={explanation?.text || s.detail || undefined}
                onClick={() => inspectStage(i)}
              >
                <span className="stage-number">
                  {state === "completed" ? (
                    <Check size={11} />
                  ) : state === "waiting" ? (
                    <Clock3 size={10} />
                  ) : state === "failed" ? (
                    <X size={11} />
                  ) : (
                    i + 1
                  )}
                </span>
                <span>
                  {/* For a case, this step is its disposition (who acts next), not a vehicle route. */}
                  {i === 6 && c.backend
                    ? t("Disposition", "التصرف في الحالة")
                    : t(s.label, s.arabic)}
                  {short ? (
                    <em
                      className="stage-explain stage-short"
                      data-source="record"
                      data-testid={`stage-explain-${i}`}
                    >
                      {t(...short)}
                    </em>
                  ) : (
                    <small>
                      {t(
                        {
                          queued: "Queued",
                          completed: "Done",
                          waiting: "Waiting",
                          running: "Running",
                          failed: "Failed",
                        }[state],
                        {
                          queued: "انتظار",
                          completed: "مكتمل",
                          waiting: "متوقف",
                          running: "جارٍ",
                          failed: "فشل",
                        }[state],
                      )}
                    </small>
                  )}
                  {state === "completed" &&
                    c.backend?.timing?.stageSeconds[i] !== undefined &&
                    c.backend.timing.stageSeconds[i] >= 1 && (
                      <small className="stage-time">
                        {secondsLabel(c.backend.timing.stageSeconds[i])}
                      </small>
                    )}
                </span>
              </Button>
            );
          })}
        </div>
        {/* The full record of a step, when the operator picks one (lab: always shown). */}
        {(!c.backend || previewStage !== null) && (
          <div className="pipeline-stage-summary">
            <span className="purple-stage-dot" />
            <b>
              {stage === 6 && c.backend
                ? t("Disposition", "التصرف في الحالة")
                : t(stages[stage].label, stages[stage].arabic)}
            </b>
            <span>
              {c.backend
                ? (explainStage(c, stage, stageState(stage))?.text ??
                  (stage === 6 && c.execution
                    ? c.execution.detail
                    : undefined) ??
                  c.backend.stageDetail[stage] ??
                  (stage === 7
                    ? (c.outcome?.detail ??
                      t(
                        "No independently verified outcome is recorded.",
                        "لا توجد نتيجة متحقق منها بشكل مستقل.",
                      ))
                    : stage === 6 && c.execution
                      ? c.execution.detail
                      : c.status === "investigating" &&
                          stage === (c.run?.stage ?? 0)
                        ? t("Starting…", "جارٍ البدء…")
                        : t(
                            "No event is recorded for this stage in the current run.",
                            "لا يوجد حدث مسجل لهذه المرحلة في التحقيق الحالي.",
                          )))
                : stage === 2
                  ? c.diagnosis
                  : stage === 4
                    ? c.recommendation.title
                    : stages[stage].detail}
            </span>
          </div>
        )}
        {/* The pipeline's final output. */}
        <NextStep c={c} />
        {c.backend && (
          <NarrationStrip
            key={c.id}
            c={c}
            stage={stage}
            onStage={(index) => setPreviewStage(index)}
            onHighlight={(ids, id) => {
              // The narration's cited records take the graph: a manual selection gives way.
              if (ids.length) {
                setSelected(null);
                setRelationship(null);
              }
              setNarrated({ id, ids });
            }}
            highlighted={narrated.id}
          />
        )}
      </section>
      <div className="workspace-toolbar">
        <div>
          <h2>{t("Evidence workspace", "مساحة الأدلة")}</h2>
          <span>
            {t(
              "Map and graph share selected evidence",
              "الخريطة والرسم يشتركان في الدليل المحدد",
            )}
            {c.backend?.graphTotals &&
              c.backend.graphTotals.shown < c.backend.graphTotals.nodes &&
              ` · ${t(
                `graph draws from ${c.backend.graphTotals.shown} of ${c.backend.graphTotals.nodes} recorded nodes, cited evidence first`,
                `يستند الرسم إلى ${c.backend.graphTotals.shown} من ${c.backend.graphTotals.nodes} عقدة مسجلة، والأدلة المستشهد بها أولاً`,
              )}`}
          </span>
        </div>
        <div className="view-modes" role="group" aria-label="Workspace view">
          <Button
            variant={Math.abs(split - 50) < 1 ? "outline" : "ghost"}
            aria-label="Balanced view"
            aria-pressed={Math.abs(split - 50) < 1}
            onClick={() => focus(50)}
          >
            <Columns2 size={13} />
            {t("Balanced", "متوازن")}
          </Button>
          <Button
            variant="ghost"
            aria-label="Map focus"
            aria-pressed={split > 51}
            onClick={() => focus(65)}
          >
            <Maximize2 size={13} />
            {t("Map focus", "تركيز الخريطة")}
          </Button>
          <Button
            variant="ghost"
            aria-label="Graph focus"
            aria-pressed={split < 49}
            onClick={() => focus(35)}
          >
            <Network size={13} />
            {t("Graph focus", "تركيز الرسم")}
          </Button>
        </div>
      </div>
      <div className="case-workspace">
        <aside
          className={`case-context ${c.backend?.brief ? "with-assessment" : ""}`}
        >
          {c.backend?.brief ? (
            <div className="context-section">
              <small>{t("CASE ASSESSMENT", "تقييم الحالة")}</small>
              <CaseAssessment c={c} onEvidence={select} />
            </div>
          ) : (
            <div className="context-section">
              {c.backend?.authority?.ruleId.startsWith("AUTH-27") &&
                !c.backend.diagnosisAvailable && (
                  <small data-testid="context-doubt">
                    {t(
                      "REVIEWER DID NOT ACCEPT THE FINDING · EVIDENCE-GATHERING ACTION ONLY",
                      "لم يقبل المراجع الاستنتاج · إجراء جمع أدلة فقط",
                    )}
                  </small>
                )}
              <small data-testid="context-source">
                {!c.backend
                  ? t("WHAT HAPPENED", "ما الذي حدث")
                  : c.backend.diagnosisAvailable
                    ? t(
                        "AGENT'S FINDING · REVIEWER ACCEPTED · NOT VERIFIED",
                        "استنتاج الوكيل · قبله المراجع · غير متحقق منه",
                      )
                    : t("WHAT THE MONITOR OBSERVED", "ما رصدته المراقبة")}
              </small>
              <h3>{c.issue}</h3>
              <p>
                {c.summary ||
                  (c.backend && !c.backend.diagnosisAvailable
                    ? t(
                        "No accepted agent diagnosis is recorded for this case.",
                        "لا يوجد تشخيص مقبول من الوكيل لهذه الحالة.",
                      )
                    : "")}
              </p>
            </div>
          )}
          {/* The assessment already says what was found and what was done. */}
          {!c.backend?.brief && (
            <>
              <div className="context-section">
                <small>{t("LAST CONFIRMED CUSTODY", "آخر حيازة مؤكدة")}</small>
                <b>
                  {lastCustody?.facility ??
                    t(
                      "No confirmed custody observation",
                      "لا توجد حيازة مؤكدة",
                    )}
                </b>
                {lastCustody && (
                  <span className="context-custody">
                    <ShieldCheck size={11} />
                    {lastCustody.time} AST
                  </span>
                )}
              </div>
              <div className="context-section">
                <small>{t("RECOMMENDATION", "التوصية")}</small>
                <b>{c.recommendation.title}</b>
                <Badge variant="secondary" className="context-authority">
                  {t(authority[0], authority[1])}
                </Badge>
              </div>
            </>
          )}
          <div className="context-actions">
            {c.status === "human_review" ? (
              <>
                {can.approve && (
                  <Button size="sm" onClick={() => setVerdict("approved")}>
                    {t("Review & authorize", "مراجعة وتفويض")}
                    <ArrowRight size={12} />
                  </Button>
                )}
                {c.backend && !can.approve && c.backend.detailLoaded && (
                  <p className="context-assigned">
                    {c.backend.approvalReason ??
                      t(
                        "The backend does not offer an approval for this case.",
                        "لا يتيح الخادم الموافقة على هذه الحالة.",
                      )}
                  </p>
                )}
                {can.reject && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setVerdict("rejected")}
                  >
                    {backend
                      ? t("Reject the action", "رفض الإجراء")
                      : t("Reject / request evidence", "رفض / طلب أدلة")}
                  </Button>
                )}
                {can.escalate && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setVerdict("escalated")}
                  >
                    {t("Escalate case", "تصعيد الحالة")}
                  </Button>
                )}
              </>
            ) : c.status === "verifying" ? (
              can.verify && (
                <Button
                  size="sm"
                  onClick={() => act(() => service.verify(c.id))}
                >
                  <ShieldCheck size={13} />
                  {backend
                    ? t(
                        "Ask the verifier to check now",
                        "اطلب من المتحقق الفحص الآن",
                      )
                    : t("Verify outcome", "التحقق من النتيجة")}
                </Button>
              )
            ) : c.status === "resolved" ? (
              <StatusBadge status={c.status} c={c} />
            ) : c.status === "needs_evidence" ? (
              can.escalate && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setVerdict("escalated")}
                >
                  {t("Escalate for evidence", "التصعيد لطلب الأدلة")}
                </Button>
              )
            ) : c.status === "escalated" ? (
              <p className="context-assigned">
                {backend
                  ? t("Escalated for human follow-up", "صُعّدت لمتابعة بشرية")
                  : t(
                      "Assigned to dispatch supervision",
                      "مُسند إلى إشراف الإرسال",
                    )}
              </p>
            ) : null}
            {can.humanOutcome && c.backend?.detailLoaded && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => setHumanOutcome(true)}
              >
                {t("Record a person's finding", "تسجيل نتيجة فحص بشري")}
              </Button>
            )}
            <Button size="sm" variant="ghost" onClick={() => setDetails(true)}>
              <FileSearch size={13} />
              {t("Full assessment", "التقييم الكامل")}
            </Button>
          </div>
          <span className="context-lab">
            <span className="live-dot" />
            {backend
              ? t("Backend evidence", "أدلة الخادم")
              : t("Synthetic evidence", "أدلة محاكاة")}
          </span>
        </aside>
        <ResizablePanelGroup
          className="evidence-split"
          style={{ height: "var(--evidence-height)" }}
          dir="ltr"
          orientation={smallCanvas ? "vertical" : "horizontal"}
          groupRef={groupRef}
          defaultLayout={{ map: 50, graph: 50 }}
          onLayoutChange={(layout) => setSplit(layout.map ?? 50)}
        >
          <ResizablePanel id="map" defaultSize="50%" minSize="30%">
            <RouteMap
              c={c}
              selected={selected}
              onSelect={select}
              stage={stage}
            />
          </ResizablePanel>
          <ResizableHandle
            className="split-handle"
            withHandle
            aria-label="Resize map and graph"
          />
          <ResizablePanel id="graph" defaultSize="50%" minSize="30%">
            <KnowledgeGraph
              c={c}
              selected={selected}
              onSelect={select}
              onRelation={(id) => {
                setRelationship(id);
                setSelected(null);
              }}
              stage={stage}
              highlight={narrated.ids}
            />
          </ResizablePanel>
        </ResizablePanelGroup>
      </div>
      <div
        className={`evidence-inspector surface ${edge || evidence || entity ? "" : "idle"}`}
        data-testid="evidence-inspector"
      >
        <span
          className={`inspector-icon ${evidence?.confidence === "vehicle_only" ? "vehicle-only" : ""}`}
        >
          {edge ? (
            <Network size={17} />
          ) : evidence?.confidence === "confirmed" ? (
            <ShieldCheck size={17} />
          ) : (
            <MapPin size={17} />
          )}
        </span>
        <div>
          <div className="inspector-title">
            <b>
              {edge?.label ??
                evidence?.label ??
                entity?.label ??
                t(
                  "Click a map marker or a graph record to inspect it",
                  "انقر علامة على الخريطة أو سجلاً في الرسم لفحصه",
                )}
            </b>
            {evidence && (
              <Badge
                variant="secondary"
                className={`confidence-tag confidence-${evidence.confidence}`}
              >
                {evidence.confidence === "confirmed"
                  ? t("CONFIRMED CUSTODY", "حيازة مؤكدة")
                  : evidence.confidence === "vehicle_only"
                    ? t("VEHICLE TELEMETRY ONLY", "موقع المركبة فقط")
                    : c.backend && evidence.kind === "delivery"
                      ? t(
                          "RECORDED ATTEMPT · NOT PROOF",
                          "محاولة مسجلة · ليست إثباتاً",
                        )
                      : t("EXPECTED · UNCONFIRMED", "متوقع · غير مؤكد")}
              </Badge>
            )}
          </div>
          <p>
            {evidence?.afterInvestigation &&
              `${t(
                "Recorded after the investigation's evidence snapshot; the investigator did not see it.",
                "سُجل بعد لقطة أدلة التحقيق؛ لم يطّلع عليه المحقق.",
              )} `}
            {edge?.detail ??
              evidence?.detail ??
              entity?.detail ??
              t(
                "Select a map marker, graph node, or relationship.",
                "اختر علامة أو عقدة أو علاقة.",
              )}
          </p>
        </div>
        {evidence && (
          <span className="inspector-time">
            <Clock3 size={12} />
            {evidence.time} AST
          </span>
        )}
        <Button
          size="icon-sm"
          variant="ghost"
          aria-label="Clear evidence selection"
          onClick={() => {
            setSelected(null);
            setRelationship(null);
          }}
        >
          <X size={13} />
        </Button>
      </div>
      <div className="case-workspace-footer">
        <span>
          <ShieldCheck size={12} />
          {t(
            "Vehicle GPS proves vehicle movement, not parcel custody.",
            "موقع المركبة يثبت حركة المركبة فقط وليس حيازة الطرد.",
          )}
        </span>
        <Link to={`/audit?case=${c.id}&mode=by_shipment`}>
          {t("View complete audit trail", "عرض سجل التدقيق الكامل")}
          <ArrowRight size={12} />
        </Link>
      </div>
      <Sheet open={details} onOpenChange={setDetails}>
        <SheetContent
          className="case-details-sheet"
          side={preferences.language === "ar" ? "left" : "right"}
        >
          <SheetHeader>
            <SheetTitle>
              {displayId(c)} · {t("Case assessment", "تقييم الحالة")}
            </SheetTitle>
            <SheetDescription>
              {backend
                ? t(
                    `Case ${c.id}. Evidence, review and outcomes as recorded by the backend.`,
                    `الحالة ${c.id}. الأدلة والمراجعة والنتائج كما سجلها الخادم.`,
                  )
                : t(
                    "Synthetic evidence, recommendation, and recorded outcomes.",
                    "أدلة المحاكاة والتوصية والنتائج المسجلة.",
                  )}
            </SheetDescription>
          </SheetHeader>
          <ScrollArea className="flex-1">
            <div className="sheet-body">
              <dl className="case-detail-fields">
                <div>
                  <dt>{t("Package", "الطرد")}</dt>
                  <dd>{c.shipment.packageId || "—"}</dd>
                </div>
                <div>
                  <dt>{t("Service / weight", "الخدمة / الوزن")}</dt>
                  <dd>
                    {c.shipment.service || "—"} ·{" "}
                    {c.shipment.weight === null
                      ? "—"
                      : `${c.shipment.weight} kg`}
                  </dd>
                </div>
                <div>
                  <dt>{t("Opened", "فُتحت")}</dt>
                  <dd>{c.openedAt ? `${timeLabel(c.openedAt)} AST` : "—"}</dd>
                </div>
              </dl>
              <DetailSection title={t("Current assessment", "التقييم الحالي")}>
                {c.diagnosis}
              </DetailSection>
              <DetailSection title={t("Expected journey", "الرحلة المتوقعة")}>
                {c.shipment.origin} → {c.shipment.destination}
                {!backend && <> → {t("Delivery depot", "مستودع التسليم")}</>}
              </DetailSection>
              <InvestigationRecord c={c} />
              <InvestigatorFindings
                c={c}
                onEvidence={(id) => {
                  select(id);
                  setDetails(false);
                }}
              />
              {c.backend?.ruleSignals &&
                c.backend.ruleSignals.signals.length > 0 && (
                  <section
                    className="detail-section"
                    data-testid="rule-signals"
                  >
                    <h3>
                      {t(
                        "Rule checks · not a diagnosis",
                        "فحوص القواعد · ليست تشخيصاً",
                      )}
                    </h3>
                    <div>
                      <p className="finding-meta">
                        {t(
                          `Deterministic checks over the evidence visible at ${dateTimeLabel(c.backend.ruleSignals.asOf)}. They open cases and back fact checks; they do not say what happened.`,
                          `فحوص حتمية على الأدلة الظاهرة عند ${dateTimeLabel(c.backend.ruleSignals.asOf)}. تفتح الحالات وتدعم التحقق من الوقائع، ولا تحدد ما حدث.`,
                        )}
                      </p>
                      {c.backend.ruleSignals.signals.map((signal) => (
                        <div className="finding" key={signal.code}>
                          <b>
                            {signal.code.replaceAll("_", " ").toLowerCase()}
                          </b>
                          {signal.summary && <p>{signal.summary}</p>}
                        </div>
                      ))}
                    </div>
                  </section>
                )}
              {c.backend?.review && (
                <DetailSection
                  title={
                    c.backend.review.byModel
                      ? t("Independent review", "المراجعة المستقلة")
                      : t(
                          "Deterministic evidence guard · no model review",
                          "حارس أدلة حتمي · دون مراجعة نموذج",
                        )
                  }
                >
                  {t("Verdict", "الحكم")}: {c.backend.review.verdict ?? "—"}
                  {c.backend.review.summary && (
                    <p className="mt-2">{c.backend.review.summary}</p>
                  )}
                </DetailSection>
              )}
              <div className="detail-section">
                <h3>{t("Actual evidence", "الأدلة الفعلية")}</h3>
                {c.evidence
                  // The planned-route end marker is drawn by this screen, not recorded evidence.
                  .filter((e) => !(c.backend && e.id.startsWith("planned:")))
                  .map((e) => (
                    <Button
                      key={e.id}
                      variant="ghost"
                      className="detail-evidence"
                      onClick={() => {
                        select(e.id);
                        setDetails(false);
                      }}
                    >
                      <span>
                        {e.label}
                        <small>
                          {e.facility} · {e.time} AST
                          {e.afterInvestigation &&
                            ` · ${t(
                              "recorded after the investigation",
                              "سُجل بعد التحقيق",
                            )}`}
                        </small>
                      </span>
                      {e.confidence === "confirmed" ? (
                        <ShieldCheck size={14} />
                      ) : (
                        <AlertTriangle size={14} />
                      )}
                    </Button>
                  ))}
              </div>
              <DetailSection title={c.recommendation.title}>
                {c.recommendation.detail}
                <p className="detail-expected">
                  {c.recommendation.expectedOutcome}
                </p>
              </DetailSection>
              <DetailSection
                title={t("Execution & verification", "التنفيذ والتحقق")}
              >
                {c.execution?.detail ??
                  t("No action has been executed.", "لم يُنفذ أي إجراء.")}
                {c.backend?.earlierOutcome && (
                  <p
                    className="finding-meta mt-3"
                    data-testid="earlier-outcome"
                  >
                    {t(
                      `An earlier action on this case was checked by the verifier and ${c.backend.earlierOutcome.success ? "confirmed" : "not confirmed"}: ${c.backend.earlierOutcome.reason} It belongs to an earlier cycle and is not the outcome of the current action.`,
                      `إجراء سابق في هذه الحالة فحصه المتحقق و${c.backend.earlierOutcome.success ? "تأكد" : "لم يتأكد"}: ${c.backend.earlierOutcome.reason} يخص دورة سابقة وليس نتيجة الإجراء الحالي.`,
                    )}
                  </p>
                )}
                {c.backend?.verification ? (
                  <div className="finding" data-testid="verification-result">
                    <Badge
                      variant="secondary"
                      className={`finding-status finding-${c.backend.verification.result === "confirmed" ? "supported" : ["failed", "unanswered"].includes(c.backend.verification.result) ? "refuted" : "uncertain"}`}
                    >
                      {t(
                        {
                          confirmed: "Answered · verified · exception cleared",
                          failed: "Answered · not confirmed",
                          unanswered: "Delivered · no answer by the deadline",
                          exception_remains: "Verified · exception remains",
                          finding: "Finding on record · not resolved",
                        }[c.backend.verification.result],
                        {
                          confirmed: "تم التحقق · زال الاستثناء",
                          failed: "أُجيب · لم يتأكد",
                          unanswered: "سُلّم · لا إجابة حتى الموعد النهائي",
                          exception_remains: "تم التحقق · الاستثناء باقٍ",
                          finding: "نتيجة مسجلة · لم تُحل",
                        }[c.backend.verification.result],
                      )}
                    </Badge>
                    <b>
                      {c.backend.verification.byPerson
                        ? t("A person's finding", "نتيجة فحص بشري")
                        : t("Independent verifier", "المتحقق المستقل")}
                    </b>
                    {c.backend.verification.reason && (
                      <p>{c.backend.verification.reason}</p>
                    )}
                    {c.backend.verification.remainingSymptoms.length > 0 && (
                      <p>
                        {t("Still observed", "ما زال مرصوداً")}:{" "}
                        {c.backend.verification.remainingSymptoms
                          .map((code) =>
                            code.replaceAll("_", " ").toLowerCase(),
                          )
                          .join(", ")}
                      </p>
                    )}
                  </div>
                ) : c.backend?.verificationDeadline &&
                  c.status === "verifying" ? (
                  <p className="mt-3">
                    {t(
                      `Waiting for evidence of the outcome.${c.backend.expectedResponseAt ? ` An answer is scheduled for ${dateTimeLabel(c.backend.expectedResponseAt)}.` : ""} The verifier waits until ${dateTimeLabel(c.backend.verificationDeadline)} (dataset clock); with no confirming evidence by then it records a failed outcome and the case goes to a person.`,
                      `بانتظار دليل على النتيجة. ينتظر المتحقق حتى ${dateTimeLabel(c.backend.verificationDeadline)} (ساعة البيانات)، ثم تُحال الحالة إلى شخص.`,
                    )}
                  </p>
                ) : (
                  c.outcome && <p className="mt-3">{c.outcome.detail}</p>
                )}
              </DetailSection>
              {decisions
                .filter((d) => d.caseId === c.id)
                .map((d, i) => (
                  <DetailSection key={i} title={`${d.verdict} · ${d.actor}`}>
                    {d.reason ||
                      t(
                        "The backend does not store a reason for decisions yet.",
                        "لا يخزن الخادم سبب القرارات بعد.",
                      )}
                    <p className="mt-2 text-xs">{timeLabel(d.timestamp)} AST</p>
                  </DetailSection>
                ))}
              <DetailSection title={t("Activity", "النشاط")}>
                {caseEvents.slice(0, 8).map((e) => (
                  <div key={e.id} className="detail-activity">
                    <b>{e.title}</b>
                    <small>{timeLabel(e.timestamp)} AST</small>
                    <p>{e.detail}</p>
                  </div>
                ))}
              </DetailSection>
            </div>
          </ScrollArea>
        </SheetContent>
      </Sheet>
      <HumanOutcomeDialog
        c={humanOutcome ? c : null}
        onClose={() => setHumanOutcome(false)}
      />
      <DecisionDialog
        c={verdict ? c : null}
        verdict={verdict ?? "approved"}
        onClose={() => setVerdict(null)}
      />
    </>
  );
}
function DetailSection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="detail-section">
      <h3>{title}</h3>
      <div>{children}</div>
    </section>
  );
}
