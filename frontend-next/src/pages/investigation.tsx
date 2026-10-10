import { useEffect, useState } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";
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
import { timeLabel } from "@/lib/dates";
import { stages, type AuthorityDecision } from "@/domain/types";
import { useOperations } from "@/state/operations";
import { usePreferences } from "@/state/preferences";
import { useMediaQuery } from "@/hooks/use-media-query";
import { useCanopus, useCanopusScreen } from "@/state/canopus";

export function InvestigationPage() {
  const { caseId } = useParams();
  const { key: navigationKey } = useLocation();
  const [params] = useSearchParams();
  const { cases, events, decisions, service } = useOperations();
  const { t, preferences } = usePreferences();
  const canopus = useCanopus();
  const c = cases.find((c) => c.id === caseId);
  const [selected, setSelected] = useState<string | null>("warehouse");
  const [relationship, setRelationship] = useState<string | null>(null);
  const [previewStage, setPreviewStage] = useState<number | null>(null);
  const [split, setSplit] = useState(50);
  const [verdict, setVerdict] = useState<AuthorityDecision["verdict"] | null>(
    null,
  );
  const [details, setDetails] = useState(false);
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
  const stageEvidence = [
    "origin",
    "package",
    c?.scenario === "custody" ? "handover" : "warehouse",
    "shipment",
    "recommendation",
    "recommendation",
    "gps",
    c?.evidence.some((e) => e.id === "recovery") ? "recovery" : "destination",
  ][requestedStage ?? 0];
  const requestedSection = params.get("section");
  useCanopusScreen({
    screen: "investigation",
    caseId: c?.id,
    selectedEvidenceId: selected,
    stage: previewStage ?? c?.run?.stage ?? 0,
  });
  useEffect(() => {
    setSelected("warehouse");
    setRelationship(null);
    setPreviewStage(null);
    setSplit(50);
    groupRef.current?.setLayout({ map: 50, graph: 50 });
  }, [caseId, groupRef]);
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
  if (!c)
    return (
      <>
        <EmptyState
          title={t("Shipment not found", "لم يتم العثور على الشحنة")}
          description={t(
            "This shipment is not part of the local simulation.",
            "هذه الشحنة غير موجودة في المحاكاة المحلية.",
          )}
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
  const active = cases.some((c) =>
    ["investigating", "executing", "verifying"].includes(c.status),
  );
  const lastCustody = c.evidence
    .filter((e) => e.confidence === "confirmed" && e.kind !== "gps")
    .at(-1);
  const caseEvents = events.filter((e) => e.caseId === c.id);
  const select = (id: string) => {
    setSelected(id);
    setRelationship(null);
  };
  const act = (fn: () => void) => {
    try {
      fn();
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
            <BreadcrumbPage dir="ltr">{c.id}</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>
      <div className="case-title">
        <div>
          <div className="case-heading">
            <h1>{c.id}</h1>
            <StatusBadge status={c.status} />
            <PriorityLabel priority={c.priority} />
          </div>
          <p>
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
          {c.status === "queued" && (
            <Button
              size="sm"
              disabled={active}
              onClick={() =>
                act(() => {
                  service.investigate(c.id);
                  setPreviewStage(null);
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
              : c.status === "human_review"
                ? t("Waiting for operator authority", "بانتظار صلاحية المشغل")
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
                    : c.run
                      ? t("Simulated run in progress", "تحقيق محاكى جارٍ")
                      : t("Queued", "في الانتظار")}
          </span>
          {previewStage !== null && (
            <Button
              className="follow-button"
              variant="ghost"
              size="sm"
              onClick={() => setPreviewStage(null)}
            >
              {t("Follow current stage", "تتبع المرحلة الحالية")}
            </Button>
          )}
        </div>
        <div className="pipeline-stages">
          {stages.map((s, i) => {
            const state = !c.run
              ? "queued"
              : c.status === "resolved" || i < c.run.stage
                ? "completed"
                : i === c.run.stage
                  ? c.status === "escalated"
                    ? "failed"
                    : ["human_review", "needs_evidence"].includes(c.status)
                      ? "waiting"
                      : "running"
                  : "queued";
            return (
              <Button
                variant="ghost"
                key={s.label}
                className={`pipeline-step state-${state} ${stage === i ? "selected" : ""}`}
                aria-pressed={stage === i}
                aria-label={`${s.label} · ${state}`}
                title={s.detail}
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
                  {t(s.label, s.arabic)}
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
                </span>
              </Button>
            );
          })}
        </div>
        <div className="pipeline-stage-summary">
          <span className="purple-stage-dot" />
          <b>{t(stages[stage].label, stages[stage].arabic)}</b>
          <span>
            {stage === 2
              ? c.diagnosis
              : stage === 4
                ? c.recommendation.title
                : stages[stage].detail}
          </span>
        </div>
      </section>
      <div className="workspace-toolbar">
        <div>
          <h2>{t("Evidence workspace", "مساحة الأدلة")}</h2>
          <span>
            {t(
              "Map and graph share selected evidence",
              "الخريطة والرسم يشتركان في الدليل المحدد",
            )}
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
        <aside className="case-context">
          <div className="context-section">
            <small>{t("WHAT HAPPENED", "ما الذي حدث")}</small>
            <h3>{c.issue}</h3>
            <p>{c.summary}</p>
          </div>
          <div className="context-section">
            <small>{t("LAST CONFIRMED CUSTODY", "آخر حيازة مؤكدة")}</small>
            <b>{lastCustody?.facility}</b>
            <span className="context-custody">
              <ShieldCheck size={11} />
              {lastCustody?.time} AST
            </span>
          </div>
          <div className="context-section">
            <small>{t("RECOMMENDATION", "التوصية")}</small>
            <b>{c.recommendation.title}</b>
            <Badge variant="secondary" className="context-authority">
              {c.recommendation.authority === "operator"
                ? t("Operator authority", "صلاحية المشغل")
                : c.recommendation.authority === "evidence"
                  ? t("Needs evidence", "يتطلب أدلة")
                  : t("Low-risk action", "إجراء منخفض المخاطر")}
            </Badge>
          </div>
          <div className="context-actions">
            {c.status === "human_review" ? (
              <>
                <Button size="sm" onClick={() => setVerdict("approved")}>
                  {t("Review & authorize", "مراجعة وتفويض")}
                  <ArrowRight size={12} />
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setVerdict("rejected")}
                >
                  {t("Reject / request evidence", "رفض / طلب أدلة")}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setVerdict("escalated")}
                >
                  {t("Escalate case", "تصعيد الحالة")}
                </Button>
              </>
            ) : c.status === "verifying" ? (
              <Button size="sm" onClick={() => act(() => service.verify(c.id))}>
                <ShieldCheck size={13} />
                {t("Verify outcome", "التحقق من النتيجة")}
              </Button>
            ) : c.status === "resolved" ? (
              <StatusBadge status={c.status} />
            ) : c.status === "needs_evidence" ? (
              <Button
                size="sm"
                variant="outline"
                onClick={() => setVerdict("escalated")}
              >
                {t("Escalate for evidence", "التصعيد لطلب الأدلة")}
              </Button>
            ) : c.status === "escalated" ? (
              <p className="context-assigned">
                {t(
                  "Assigned to dispatch supervision",
                  "مُسند إلى إشراف الإرسال",
                )}
              </p>
            ) : null}
            <Button size="sm" variant="ghost" onClick={() => setDetails(true)}>
              <FileSearch size={13} />
              {t("Full assessment", "التقييم الكامل")}
            </Button>
          </div>
          <span className="context-lab">
            <span className="live-dot" />
            {t("Synthetic evidence", "أدلة محاكاة")}
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
            />
          </ResizablePanel>
        </ResizablePanelGroup>
      </div>
      <div
        className="evidence-inspector surface"
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
                t("Select evidence to inspect", "اختر دليلاً لفحصه")}
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
                    : t("EXPECTED · UNCONFIRMED", "متوقع · غير مؤكد")}
              </Badge>
            )}
          </div>
          <p>
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
              {c.id} · {t("Case assessment", "تقييم الحالة")}
            </SheetTitle>
            <SheetDescription>
              {t(
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
                  <dd>{c.shipment.packageId}</dd>
                </div>
                <div>
                  <dt>{t("Service / weight", "الخدمة / الوزن")}</dt>
                  <dd>
                    {c.shipment.service} · {c.shipment.weight} kg
                  </dd>
                </div>
                <div>
                  <dt>{t("Opened", "فُتحت")}</dt>
                  <dd>{timeLabel(c.openedAt)} AST</dd>
                </div>
              </dl>
              <DetailSection title={t("Current assessment", "التقييم الحالي")}>
                {c.diagnosis}
              </DetailSection>
              <DetailSection title={t("Expected journey", "الرحلة المتوقعة")}>
                {c.shipment.origin} → {c.shipment.destination} →{" "}
                {t("Delivery depot", "مستودع التسليم")}
              </DetailSection>
              <div className="detail-section">
                <h3>{t("Actual evidence", "الأدلة الفعلية")}</h3>
                {c.evidence.map((e) => (
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
                {c.outcome && <p className="mt-3">{c.outcome.detail}</p>}
              </DetailSection>
              {decisions
                .filter((d) => d.caseId === c.id)
                .map((d, i) => (
                  <DetailSection key={i} title={`${d.verdict} · ${d.actor}`}>
                    {d.reason}
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
