import { useEffect, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import type { ColumnDef, PaginationState } from "@tanstack/react-table";
import {
  Search,
  ShieldCheck,
  ArrowRight,
  Clock3,
  FileSearch,
} from "lucide-react";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { ScrollArea } from "@/components/ui/scroll-area";
import { DataTable } from "@/components/data-table";
import { DecisionDialog } from "@/components/decision-dialog";
import {
  PageTitle,
  CaseLink,
  StatusBadge,
  PriorityLabel,
} from "@/components/shared";
import { dateTimeLabel } from "@/lib/dates";
import { useOperations } from "@/state/operations";
import { usePreferences } from "@/state/preferences";
import type { AuthorityDecision, OperationalCase } from "@/domain/types";
import {
  authorityLabel,
  awaitingApproval,
  controls,
  displayId,
} from "@/domain/case-view";
import { useCanopus, useCanopusScreen } from "@/state/canopus";
const LAB_BUILD = import.meta.env.VITE_SUHAIL_DATA === "lab";
export function DecisionsPage() {
  const { cases, decisions, service, backend: fromBackend } = useOperations();
  // Connected build: always the backend, so lab-only branches are removed at build time.
  const backend = !LAB_BUILD || fromBackend;
  const { t, preferences } = usePreferences();
  const [params] = useSearchParams();
  const { key: navigationKey } = useLocation();
  const linkedCase = params.get("case");
  const [tab, setTab] = useState("review");
  const [query, setQuery] = useState(() => params.get("case") ?? "");
  const [pagination, setPagination] = useState<PaginationState>({
    pageIndex: 0,
    pageSize: 10,
  });
  const [detailsId, setDetailsId] = useState<string | null>(() =>
    params.get("case"),
  );
  useEffect(() => {
    if (linkedCase) {
      setQuery(linkedCase);
      setDetailsId(linkedCase);
      setPagination((p) => (p.pageIndex ? { ...p, pageIndex: 0 } : p));
    }
  }, [linkedCase, navigationKey]);
  const [selection, setSelection] = useState<{
    c: OperationalCase;
    verdict: AuthorityDecision["verdict"];
  } | null>(null);
  const pending = cases.filter((c) =>
    ["human_review", "needs_evidence", "escalated"].includes(c.status),
  );
  const rows = pending
    .filter(
      (c) =>
        (tab === "review" ||
          (tab === "approval"
            ? awaitingApproval(c)
            : c.status ===
              {
                evidence: "needs_evidence",
                escalated: "escalated",
              }[tab])) &&
        `${c.id} ${c.shipment.id} ${c.issue} ${c.recommendation.title}`
          .toLowerCase()
          .includes(query.toLowerCase()),
    )
    .sort((a, b) => Date.parse(a.openedAt) - Date.parse(b.openedAt));
  const history = decisions.filter((d) =>
    `${d.caseId} ${d.action} ${d.actor} ${d.reason}`
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  const details = cases.find((c) => c.id === detailsId);
  // Backend: the proposed action and the allowed controls come from each case's detail.
  const pendingIds = rows
    .slice(
      pagination.pageIndex * pagination.pageSize,
      (pagination.pageIndex + 1) * pagination.pageSize,
    )
    .map((c) => c.id)
    .join(",");
  useEffect(() => {
    if (pendingIds) void service.loadCases?.(pendingIds.split(","));
  }, [pendingIds, service]);
  useEffect(() => {
    void service.loadAudit?.();
  }, [service]);
  useEffect(
    () => (detailsId ? service.watchCase?.(detailsId) : undefined),
    [detailsId, service],
  );
  const caseLabel = (id: string) => {
    const found = cases.find((c) => c.id === id);
    return found ? displayId(found) : undefined;
  };
  const canopus = useCanopus();
  useCanopusScreen({
    screen: "decisions",
    caseId: details?.id ?? selection?.c.id,
    filters: { tab, search: query },
  });
  function decide(c: OperationalCase, verdict: AuthorityDecision["verdict"]) {
    setDetailsId(null);
    setSelection({ c, verdict });
  }
  const columns: ColumnDef<OperationalCase>[] = [
    {
      id: "shipment",
      header: t("Shipment", "الشحنة"),
      size: 140,
      cell: ({ row }) => (
        <CaseLink id={row.original.id} label={displayId(row.original)} />
      ),
    },
    {
      id: "exception",
      header: t("Exception / route", "الاستثناء / المسار"),
      size: 230,
      cell: ({ row }) => (
        <div>
          <b className="font-medium">{row.original.issue}</b>
          <span className="cell-secondary">
            {row.original.shipment.origin} → {row.original.shipment.destination}
          </span>
        </div>
      ),
    },
    {
      id: "action",
      header: t("Proposed action", "الإجراء المقترح"),
      size: 340,
      cell: ({ row }) => (
        <div className="decision-proposed">
          <b>{row.original.recommendation.title}</b>
          <span className="cell-secondary">
            {row.original.backend
              ? row.original.backend.detailLoaded
                ? t(
                    authorityLabel(row.original)[0],
                    authorityLabel(row.original)[1],
                  )
                : t("Loading from the backend…", "جارٍ التحميل من الخادم…")
              : row.original.recommendation.authority === "operator"
                ? t("Requires operator authorization", "يتطلب تفويض المشغل")
                : t("Independent evidence required", "يتطلب أدلة مستقلة")}
          </span>
        </div>
      ),
    },
    {
      id: "priority",
      header: t("Priority", "الأولوية"),
      size: 90,
      cell: ({ row }) => <PriorityLabel priority={row.original.priority} />,
    },
    {
      id: "status",
      header: t("Workflow", "سير العمل"),
      size: 140,
      cell: ({ row }) => (
        <StatusBadge status={row.original.status} c={row.original} />
      ),
    },
    {
      id: "review",
      header: "",
      size: 105,
      cell: ({ row }) => (
        <Button
          variant="outline"
          size="sm"
          onClick={() => setDetailsId(row.original.id)}
          aria-label={`Review ${displayId(row.original)}`}
        >
          <FileSearch size={13} />
          {t("Review", "مراجعة")}
        </Button>
      ),
    },
  ];
  const historyColumns: ColumnDef<AuthorityDecision>[] = [
    {
      id: "shipment",
      header: t("Shipment", "الشحنة"),
      size: 140,
      cell: ({ row }) => (
        <CaseLink
          id={row.original.caseId}
          label={caseLabel(row.original.caseId)}
        />
      ),
    },
    {
      accessorKey: "action",
      header: t("Authorized action", "الإجراء"),
      size: 260,
    },
    {
      id: "verdict",
      header: t("Decision", "القرار"),
      size: 105,
      cell: ({ row }) => (
        <Badge
          variant="secondary"
          className={`decision-verdict verdict-${row.original.verdict}`}
        >
          {row.original.verdict}
        </Badge>
      ),
    },
    {
      id: "reason",
      header: t("Reason", "السبب"),
      size: 340,
      cell: ({ row }) =>
        row.original.reason ||
        (backend ? (
          <span className="cell-secondary">
            {t(
              "Not stored by the backend yet",
              "لا يخزنه الخادم بعد",
            )}
          </span>
        ) : (
          ""
        )),
    },
    {
      id: "actor",
      header: t("Operator / time", "المشغل / الوقت"),
      size: 180,
      cell: ({ row }) => (
        <div>
          {row.original.actor}
          <span className="cell-secondary">
            {dateTimeLabel(row.original.timestamp)}
          </span>
        </div>
      ),
    },
  ];
  const count = tab === "history" ? history.length : rows.length;
  const safePagination = {
    ...pagination,
    pageIndex: Math.min(
      pagination.pageIndex,
      Math.max(0, Math.ceil(count / pagination.pageSize) - 1),
    ),
  };
  return (
    <>
      <PageTitle
        title={t("Decisions", "القرارات")}
        description={t(
          "Review the evidence. Authorize the action. Verify the outcome.",
          "راجع الأدلة. فوّض الإجراء. تحقق من النتيجة.",
        )}
      >
        <span className="date-pill">
          <ShieldCheck size={13} />
          {backend
            ? t(
                "Operator authority · enforced by the backend",
                "صلاحية المشغل · يفرضها الخادم",
              )
            : t(
                "Operator authority · simulated policy C-04",
                "صلاحية المشغل · سياسة محاكاة C-04",
              )}
        </span>
      </PageTitle>
      <div className="decision-counts">
        <span>
          <Clock3 size={12} />
          <b>{pending.filter(awaitingApproval).length}</b>
          {t("awaiting approval", "بانتظار الموافقة")}
        </span>
        <span>
          <b>{pending.filter((c) => c.status === "needs_evidence").length}</b>
          {t("need evidence", "تحتاج أدلة")}
        </span>
        <span>
          <b>{pending.filter((c) => c.status === "escalated").length}</b>
          {t("escalated", "تم التصعيد")}
        </span>
        <span>
          <b>{decisions.length}</b>
          {t("decisions recorded", "قرارات مسجلة")}
        </span>
      </div>
      <section className="surface decision-table-surface">
        <div className="decision-table-toolbar">
          <Tabs
            value={tab}
            onValueChange={(v) => {
              setTab(v);
              setPagination((p) => ({ ...p, pageIndex: 0 }));
            }}
          >
            <TabsList>
              <TabsTrigger value="review">
                {t("Human review", "مراجعة بشرية")}
                <span className="subtle-count">{pending.length}</span>
              </TabsTrigger>
              <TabsTrigger value="approval">
                {t("Awaiting approval", "بانتظار الموافقة")}
              </TabsTrigger>
              <TabsTrigger value="evidence">
                {t("Needs evidence", "يتطلب أدلة")}
              </TabsTrigger>
              <TabsTrigger value="escalated">
                {t("Escalated", "تم التصعيد")}
              </TabsTrigger>
              <TabsTrigger value="history">
                {t("Decision history", "سجل القرارات")}
              </TabsTrigger>
            </TabsList>
          </Tabs>
          <div className="search-field">
            <Search size={14} />
            <Input
              aria-label="Search decisions"
              placeholder={t("Search decisions…", "البحث في القرارات…")}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setPagination((p) => ({ ...p, pageIndex: 0 }));
              }}
            />
          </div>
        </div>
        {tab === "history" ? (
          <DataTable
            columns={historyColumns}
            data={history}
            rowId={(d) => `${d.caseId}-${d.timestamp}`}
            pagination={safePagination}
            onPaginationChange={setPagination}
            emptyTitle={t(
              "No decisions recorded yet",
              "لا توجد قرارات مسجلة بعد",
            )}
            emptyDescription={t(
              "Recorded approvals, rejections, and escalations appear here.",
              "تظهر هنا الموافقات والرفض والتصعيد المسجلة.",
            )}
          />
        ) : (
          <DataTable
            columns={columns}
            data={rows}
            rowId={(c) => c.id}
            onRowClick={(c) => setDetailsId(c.id)}
            pagination={safePagination}
            onPaginationChange={setPagination}
            emptyTitle={t("Nothing waiting here", "لا توجد حالات تنتظر هنا")}
            emptyDescription={t(
              "Cases requiring this type of attention will appear here.",
              "ستظهر هنا الحالات التي تحتاج إلى هذا النوع من التدخل.",
            )}
          />
        )}
      </section>
      <p className="decision-footnote">
        <ShieldCheck size={12} />
        {backend
          ? t(
              "Approval authorizes the named action; the backend re-checks authority before dispatch. A case resolves only after independent outcome verification.",
              "تفوض الموافقة الإجراء المحدد، ويعيد الخادم فحص الصلاحية قبل التنفيذ. لا تُحل الحالة إلا بعد تحقق مستقل من النتيجة.",
            )
          : t(
              "Approval authorizes the named mock action. A case resolves only after independent outcome verification.",
              "تفوض الموافقة إجراء المحاكاة المحدد. لا تُحل الحالة إلا بعد تحقق مستقل من النتيجة.",
            )}
      </p>
      <Sheet
        open={!!details}
        onOpenChange={(v) => {
          if (!v) setDetailsId(null);
        }}
      >
        <SheetContent
          className="decision-detail-sheet"
          side={preferences.language === "ar" ? "left" : "right"}
        >
          <SheetHeader>
            <SheetTitle>
              {details ? displayId(details) : ""} ·{" "}
              {t("Decision review", "مراجعة القرار")}
            </SheetTitle>
            <SheetDescription>{details?.issue}</SheetDescription>
          </SheetHeader>
          {details && (
            <>
              <ScrollArea className="flex-1">
                <div className="sheet-body">
                  <div className="flex items-center gap-3 mb-6">
                    <StatusBadge status={details.status} c={details} />
                    <PriorityLabel priority={details.priority} />
                  </div>
                  <section className="detail-section">
                    <h3>{t("What happened", "ما الذي حدث")}</h3>
                    <div>{details.summary}</div>
                  </section>
                  <section className="detail-section">
                    <h3>{t("Evidence assessment", "تقييم الأدلة")}</h3>
                    <div>{details.diagnosis}</div>
                  </section>
                  <section className="detail-section">
                    <h3>{t("Proposed action", "الإجراء المقترح")}</h3>
                    <b className="text-sm font-medium">
                      {details.recommendation.title}
                    </b>
                    <p className="mt-3 text-xs text-muted-foreground leading-relaxed">
                      {details.recommendation.detail}
                    </p>
                    <p className="detail-expected text-xs">
                      {details.recommendation.expectedOutcome}
                    </p>
                  </section>
                  <div className="decision-evidence-summary">
                    <ShieldCheck size={15} />
                    {
                      details.evidence.filter(
                        (e) => e.confidence === "confirmed" && e.kind !== "gps",
                      ).length
                    }{" "}
                    {t("confirmed parcel observations", "ملاحظات طرود مؤكدة")}
                    <p>
                      {t(
                        "Vehicle GPS is telemetry, not parcel custody proof.",
                        "موقع المركبة قياس لحركتها وليس دليلاً على حيازة الطرد.",
                      )}
                    </p>
                  </div>
                  <Button asChild variant="outline" className="w-full">
                    <Link to={`/cases/${details.id}`}>
                      {t(
                        "Inspect map & knowledge graph",
                        "فحص الخريطة والرسم المعرفي",
                      )}
                      <ArrowRight size={13} />
                    </Link>
                  </Button>
                  <Button
                    variant="ghost"
                    className="w-full mt-2"
                    onClick={() => {
                      setDetailsId(null);
                      canopus.open({ screen: "decisions", caseId: details.id });
                    }}
                  >
                    {" "}
                    {t(
                      "Ask Suhail about this decision",
                      "اسأل سهيل عن هذا القرار",
                    )}{" "}
                  </Button>
                </div>
              </ScrollArea>
              <div className="decision-sheet-actions">
                {details.status === "human_review" ? (
                  <>
                    {controls(details).approve && (
                      <Button onClick={() => decide(details, "approved")}>
                        {t("Review & authorize", "مراجعة وتفويض")}
                      </Button>
                    )}
                    {details.backend && !controls(details).approve && (
                      <p className="text-xs text-muted-foreground">
                        {details.backend.detailLoaded
                          ? (details.backend.approvalReason ??
                            t(
                              "The backend does not offer an approval for this case.",
                              "لا يتيح الخادم الموافقة على هذه الحالة.",
                            ))
                          : t("Loading from the backend…", "جارٍ التحميل من الخادم…")}
                      </p>
                    )}
                    {controls(details).reject && (
                      <Button
                        variant="outline"
                        onClick={() => decide(details, "rejected")}
                      >
                        {backend
                          ? t("Reject the action", "رفض الإجراء")
                          : t("Reject / request evidence", "رفض / طلب أدلة")}
                      </Button>
                    )}
                    {controls(details).escalate && (
                      <Button
                        variant="ghost"
                        onClick={() => decide(details, "escalated")}
                      >
                        {t("Escalate case", "تصعيد الحالة")}
                      </Button>
                    )}
                  </>
                ) : details.status === "needs_evidence" &&
                  controls(details).escalate ? (
                  <Button
                    variant="outline"
                    onClick={() => decide(details, "escalated")}
                  >
                    {t("Escalate for evidence", "التصعيد لطلب الأدلة")}
                  </Button>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    {backend
                      ? t(
                          "No operator decision is open for this case.",
                          "لا يوجد قرار مشغل مفتوح لهذه الحالة.",
                        )
                      : t(
                          "Assigned to dispatch supervision.",
                          "مُسند إلى إشراف الإرسال.",
                        )}
                  </p>
                )}
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
      <DecisionDialog
        c={selection?.c ?? null}
        verdict={selection?.verdict ?? "approved"}
        onClose={() => setSelection(null)}
      />
    </>
  );
}
