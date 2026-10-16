import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowRight,
  CheckCheck,
  ChevronRight,
  Clock3,
  PanelRightClose,
  FastForward,
  Pause,
  Play,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Sparkles,
  ShieldCheck,
  X,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { toast } from "sonner";
import type { ColumnDef } from "@tanstack/react-table";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Collapsible, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { ScrollArea } from "@/components/ui/scroll-area";
import { SelectControl } from "@/components/select-control";
import { DataTable } from "@/components/data-table";
import {
  CaseLink,
  PageTitle,
  PriorityLabel,
  StatusBadge,
} from "@/components/shared";
import { timeLabel } from "@/lib/dates";
import { useOperations } from "@/state/operations";
import { usePreferences } from "@/state/preferences";
import { stages, type OperationalCase } from "@/domain/types";
import {
  displayId,
  matchesCause,
  matchesOperational,
  operationalOf,
  searchText,
} from "@/domain/case-view";
import { useCanopusScreen } from "@/state/canopus";
import { humanize } from "@/api/adapters";
import {
  caseQueueGroup,
  verifiedResolution,
  waitingLabel,
} from "@/domain/investigation-workspace";
const LAB_BUILD = import.meta.env.VITE_SUHAIL_DATA === "lab";

export function OperationsPage() {
  const {
    cases,
    automatic,
    service,
    catalog,
    backend: fromBackend,
    connection,
  } = useOperations();
  // Connected build: always the backend, so lab-only branches are removed at build time.
  const backend = !LAB_BUILD || fromBackend;
  const { t } = usePreferences();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [priority, setPriority] = useState("all");
  const [city, setCity] = useState("all");
  const [cause, setCause] = useState("all");
  const [operational, setOperational] = useState("all");
  const [sort, setSort] = useState("newest");
  const [resolvedOpen, setResolvedOpen] = useState(false);
  const [queueTab, setQueueTab] = useState<"waiting" | "resolved">("waiting");
  const [refreshing, setRefreshing] = useState(false);
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: 10 });
  useCanopusScreen({
    screen: "operations",
    filters: { search: query, status, priority, city, cause },
  });
  const active = cases.filter((c) => caseQueueGroup(c) === "active");
  const resolved = cases.filter((c) => verifiedResolution(c));
  const closed = cases.filter((c) => caseQueueGroup(c) !== "active");
  const pendingResolution = closed.length - resolved.length;
  const activeClaims = connection?.worker?.activeCases ?? [];
  const waiting = active.filter(
    (c) =>
      !activeClaims.some((claim) => claim.caseId === c.id) &&
      !["queued", "investigating"].includes(c.status),
  );
  const queueEntries = queueTab === "waiting" ? waiting : closed;
  // Backend: active V3 claims, else legacy single id. Lab: the one simulated run.
  const running = backend
    ? activeClaims.length
      ? cases.find((c) => c.id === activeClaims[0].caseId)
      : connection?.worker?.activeCaseId
        ? cases.find((c) => c.id === connection?.worker?.activeCaseId)
        : undefined
    : cases.find((c) =>
        ["investigating", "executing", "verifying"].includes(c.status),
      );
  const activeCards = backend
    ? activeClaims.slice(0, 2).map((claim) => ({
        claim,
        c: cases.find((item) => item.id === claim.caseId),
      }))
    : running
      ? [{ claim: null, c: running }]
      : [];
  const human = active.filter((c) =>
    ["human_review", "needs_evidence", "escalated"].includes(c.status),
  );
  const resetPage = () => setPagination((p) => ({ ...p, pageIndex: 0 }));
  const filtered = active
    .filter(
      (c) =>
        (status === "all" ||
          c.status === status ||
          (status === "attention" &&
            ["human_review", "needs_evidence", "escalated"].includes(
              c.status,
            ))) &&
        (priority === "all" || c.priority === priority) &&
        (city === "all" ||
          c.shipment.destination === city ||
          c.shipment.origin === city) &&
        matchesCause(c, cause) &&
        matchesOperational(c, operational) &&
        searchText(c).includes(query.toLowerCase()),
    )
    .sort((a, b) =>
      sort === "priority"
        ? { high: 0, medium: 1, low: 2, unknown: 3 }[a.priority] -
          { high: 0, medium: 1, low: 2, unknown: 3 }[b.priority]
        : sort === "newest"
          ? Date.parse(b.openedAt) - Date.parse(a.openedAt)
          : Date.parse(a.openedAt) - Date.parse(b.openedAt),
    );
  const safePagination = {
    ...pagination,
    pageIndex: Math.min(
      pagination.pageIndex,
      Math.max(0, Math.ceil(filtered.length / pagination.pageSize) - 1),
    ),
  };
  const columns: ColumnDef<OperationalCase>[] = [
    {
      id: "shipment",
      header: t("Shipment", "الشحنة"),
      size: 140,
      cell: ({ row }) => (
        <>
          <CaseLink id={row.original.id} label={displayId(row.original)} />
          <span className="cell-secondary">
            {row.original.shipment.origin}
            <span className="route-arrow">→</span>
            {row.original.shipment.destination}
          </span>
        </>
      ),
    },
    {
      accessorKey: "issue",
      header: t("Exception", "الاستثناء"),
      size: 190,
      cell: ({ row }) => (
        <span className="exception-name">{row.original.issue}</span>
      ),
    },
    {
      accessorKey: "priority",
      header: t("Priority", "الأولوية"),
      size: 75,
      cell: ({ row }) => <PriorityLabel priority={row.original.priority} />,
    },
    {
      accessorKey: "status",
      header: t("Workflow", "سير العمل"),
      size: 145,
      cell: ({ row }) => (
        <StatusBadge status={row.original.status} c={row.original} />
      ),
    },
    {
      id: "operational",
      header: t("Operational status", "الحالة التشغيلية"),
      size: 130,
      cell: ({ row }) => (
        <span className="tracking-label">
          {t(operationalOf(row.original)[1], operationalOf(row.original)[2])}
        </span>
      ),
    },
    {
      id: "city",
      header: t("City", "المدينة"),
      size: 90,
      cell: ({ row }) => (
        <span className="muted">{row.original.shipment.destination}</span>
      ),
    },
    {
      id: "time",
      header: t("Received · AST", "الوصول · السعودية"),
      size: 100,
      cell: ({ row }) => (
        <span className="received-time">
          {timeLabel(row.original.openedAt)}
        </span>
      ),
    },
    {
      id: "open",
      header: "",
      size: 35,
      cell: ({ row }) => (
        <Button asChild variant="ghost" size="icon-sm">
          <Link
            aria-label={`Open investigation for ${displayId(row.original)}`}
            to={`/cases/${row.original.id}`}
          >
            <ArrowRight size={14} />
          </Link>
        </Button>
      ),
    },
  ];
  const cities = [
    ...new Set(
      cases.flatMap((c) => [c.shipment.origin, c.shipment.destination]),
    ),
  ];
  const clear = () => {
    setQuery("");
    setPriority("all");
    setStatus("all");
    setCity("all");
    setCause("all");
    setOperational("all");
    setSort("newest");
    resetPage();
  };
  function refresh() {
    setRefreshing(true);
    if (service.refresh) {
      // Backend: read the queue again now, and say what actually happened.
      void service.refresh().then(() => {
        setRefreshing(false);
        const state = service.getSnapshot().connection;
        if (state?.state === "online")
          toast.info(
            t("Queue read from the backend.", "تمت قراءة القائمة من الخادم."),
          );
        else
          toast.error(
            state?.error ??
              t("The backend is not reachable.", "تعذر الوصول إلى الخادم."),
          );
      });
      return;
    }
    window.setTimeout(() => {
      setRefreshing(false);
      toast.info(t("Local queue is up to date.", "القائمة المحلية محدّثة."));
    }, 450);
  }
  const [skipping, setSkipping] = useState(false);
  function skipToNext() {
    if (skipping || !service.skipClock) return;
    setSkipping(true);
    void service
      .skipClock()
      .then((result) => {
        // One plain line of what the backend reports happened.
        const hours = Math.round((result.simulatedMinutes / 60) * 10) / 10;
        const names = result.caseIds
          .map((id) => cases.find((item) => item.id === id)?.shipment.id ?? "")
          .filter(Boolean)
          .join(", ");
        const what =
          result.reason === "outcome_decided"
            ? t(
                `the verifier decided a waiting case${names ? ` for ${names}` : ""}`,
                `حسم المتحقق حالة منتظرة${names ? ` لـ ${names}` : ""}`,
              )
            : result.reason === "case_opened"
              ? t(
                  `a new case opened${names ? `, ${names}` : ""}`,
                  `فُتحت حالة جديدة${names ? `، ${names}` : ""}`,
                )
              : result.reason === "end_of_timeline"
                ? t(
                    "the end of the timeline was reached",
                    "بلغت نهاية الخط الزمني",
                  )
                : t("nothing arrived yet", "لم يصل شيء بعد");
        toast.info(
          t(
            `Skipped ${hours} hours: ${what}.`,
            `تم تخطي ${hours} ساعة: ${what}.`,
          ),
        );
      })
      .catch((error: Error) =>
        toast.error(
          /409/.test(error.message)
            ? t(
                "An investigation is running; skip again when it has finished.",
                "هناك تحقيق جارٍ؛ أعد التخطي بعد انتهائه.",
              )
            : error.message,
        ),
      )
      .finally(() => setSkipping(false));
  }
  function setAutomatic(enabled: boolean) {
    // The switch reflects the backend worker; it changes only when the backend confirms.
    void Promise.resolve()
      .then(() => service.setAutomatic(enabled))
      .catch((error: Error) => toast.error(error.message));
  }
  return (
    <>
      <PageTitle
        title={t("Operations", "العمليات")}
        description={t(
          "Shipment exceptions requiring action.",
          "استثناءات الشحنات التي تتطلب إجراءً.",
        )}
      >
        <span className="inline-count">
          {active.length} {t("open", "مفتوحة")}
          <i>·</i>
          {human.length} {t("need attention", "تتطلب انتباهاً")}
        </span>
      </PageTitle>
      <div
        className={`operations-workbench ${resolvedOpen ? "resolved-expanded" : ""}`}
      >
        <section className="operations-ledger surface">
          <div className="table-toolbar operations-toolbar">
            <div className="search-field">
              <Search size={14} />
              <Input
                aria-label="Search exception queue"
                placeholder={t(
                  "Search shipment or case…",
                  "البحث عن شحنة أو حالة…",
                )}
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  resetPage();
                }}
              />
            </div>
            <SelectControl
              label="Filter by status"
              value={status}
              onChange={(v) => {
                setStatus(v);
                resetPage();
              }}
              options={[
                { value: "all", label: t("All workflows", "كل الحالات") },
                { value: "queued", label: t("Queued", "في الانتظار") },
                {
                  value: "investigating",
                  label: t("Investigating", "قيد التحقيق"),
                },
                {
                  value: "attention",
                  label: t("Human attention", "تدخل بشري"),
                },
                {
                  value: "human_review",
                  label: t("Awaiting approval", "بانتظار الموافقة"),
                },
                {
                  value: "needs_evidence",
                  label: t("Needs evidence", "يتطلب أدلة"),
                },
                { value: "verifying", label: t("Verifying", "التحقق") },
                { value: "escalated", label: t("Escalated", "تم التصعيد") },
              ]}
            />
            <SelectControl
              label="Filter by priority"
              value={priority}
              onChange={(v) => {
                setPriority(v);
                resetPage();
              }}
              options={[
                { value: "all", label: t("All priorities", "كل الأولويات") },
                { value: "high", label: t("High", "مرتفع") },
                { value: "medium", label: t("Medium", "متوسط") },
                { value: "low", label: t("Low", "منخفض") },
              ]}
            />
            <SelectControl
              label="Filter by city"
              value={city}
              onChange={(v) => {
                setCity(v);
                resetPage();
              }}
              options={[
                { value: "all", label: t("All cities", "كل المدن") },
                ...cities.map((city) => ({ value: city, label: city })),
              ]}
            />
            <Popover>
              <PopoverTrigger asChild>
                <Button
                  aria-label="More queue filters"
                  variant={
                    cause !== "all" || operational !== "all"
                      ? "secondary"
                      : "outline"
                  }
                  size="icon-sm"
                >
                  <SlidersHorizontal size={14} />
                </Button>
              </PopoverTrigger>
              <PopoverContent align="end" className="filter-popover">
                <label>{t("Exception cause", "سبب الاستثناء")}</label>
                <SelectControl
                  label="Filter by cause"
                  value={cause}
                  onChange={(v) => {
                    setCause(v);
                    resetPage();
                  }}
                  options={[
                    { value: "all", label: t("All causes", "كل الأسباب") },
                    ...catalog.causes,
                  ]}
                />
                <label>{t("Operational status", "الحالة التشغيلية")}</label>
                <SelectControl
                  label="Operational status filter"
                  value={operational}
                  onChange={(v) => {
                    setOperational(v);
                    resetPage();
                  }}
                  options={[
                    { value: "all", label: t("All statuses", "كل الحالات") },
                    ...catalog.operational.map((item) => ({
                      value: item.value,
                      label: t(item.label, item.arabic),
                    })),
                  ]}
                />
                <Button
                  variant="outline"
                  size="sm"
                  onClick={clear}
                  className="w-full"
                >
                  {t("Clear all filters", "مسح كل عوامل التصفية")}
                </Button>
              </PopoverContent>
            </Popover>
            <SelectControl
              label="Sort cases"
              value={sort}
              onChange={(v) => {
                setSort(v);
                resetPage();
              }}
              options={[
                { value: "newest", label: t("Newest first", "الأحدث أولاً") },
                { value: "oldest", label: t("Oldest first", "الأقدم أولاً") },
                {
                  value: "priority",
                  label: t("Priority first", "الأولوية أولاً"),
                },
              ]}
            />
            {backend && connection?.clock && service.setClock && (
              <Button
                variant="outline"
                size="sm"
                className="clock-control"
                data-testid="clock-control"
                aria-pressed={connection.clock.running}
                disabled={skipping || connection.controls === "unavailable"}
                title={t(
                  "The simulated clock. New exceptions arrive and requests are answered only while it runs.",
                  "الساعة المحاكاة. تصل الاستثناءات الجديدة وتُجاب الطلبات فقط أثناء تشغيلها.",
                )}
                onClick={() =>
                  void service.setClock!(!connection.clock!.running).catch(
                    (e: Error) => toast.error(e.message),
                  )
                }
              >
                {connection.clock.running ? (
                  <Pause size={12} />
                ) : (
                  <Play size={12} />
                )}
                {connection.clock.running
                  ? t(
                      `Clock running ×${connection.clock.speed} · Pause`,
                      `الساعة تعمل ×${connection.clock.speed} · إيقاف`,
                    )
                  : t("Clock paused · Start", "الساعة متوقفة · تشغيل")}
              </Button>
            )}
            {backend && connection?.clock && service.skipClock && (
              <Button
                variant="outline"
                size="sm"
                className="clock-control"
                data-testid="clock-skip"
                disabled={skipping || connection.controls === "unavailable"}
                title={t(
                  "Runs the clock fast until an awaited result arrives or a new case opens, then returns to the current speed. Every other shipment ages by the skipped time.",
                  "يشغّل الساعة بسرعة حتى تصل نتيجة منتظرة أو تُفتح حالة جديدة، ثم يعود إلى السرعة الحالية. تتقدم كل الشحنات الأخرى بالزمن المتخطى.",
                )}
                onClick={skipToNext}
              >
                <FastForward size={12} />
                {skipping
                  ? t("Skipping…", "جارٍ التخطي…")
                  : t("Skip to next event", "تخطَّ إلى الحدث التالي")}
              </Button>
            )}
            <label className="inline-automation">
              <span>{t("Auto", "تلقائي")}</span>
              <Switch
                aria-label="Automatic investigation"
                aria-describedby="automatic-state-note"
                checked={automatic}
                onCheckedChange={setAutomatic}
                disabled={backend && connection?.controls === "unavailable"}
              />
              <span className="auto-switch-state">
                {t(
                  automatic ? "Running" : "Paused",
                  automatic ? "نشط" : "متوقف مؤقتاً",
                )}
              </span>
            </label>
            <Button
              aria-label="Refresh queue"
              title={
                backend
                  ? t(
                      "Read the queue from the backend",
                      "قراءة القائمة من الخادم",
                    )
                  : t("Refresh local queue", "تحديث القائمة المحلية")
              }
              variant="ghost"
              size="icon-sm"
              onClick={refresh}
              disabled={refreshing}
            >
              <RefreshCw size={14} className={refreshing ? "slow-spin" : ""} />
            </Button>
          </div>
          <div className="ledger-caption">
            <span>
              <span
                className={automatic || running ? "live-dot" : "paused-dot"}
              />
              {activeCards.length > 1
                ? t(
                    `${activeCards.length} active investigations`,
                    `${activeCards.length} تحقيقات نشطة`,
                  )
                : running
                  ? `${displayId(running)} · ${t(stages[running.run?.stage ?? 0].label, stages[running.run?.stage ?? 0].arabic)}`
                  : automatic
                    ? t(
                        "Picking the oldest eligible case",
                        "اختيار أقدم حالة مؤهلة",
                      )
                    : t(
                        "New automatic investigations paused",
                        "بدء تحقيقات تلقائية جديدة متوقف مؤقتاً",
                      )}
              <Badge variant="outline" className="fifo-badge">
                FIFO
              </Badge>
            </span>
            <span>
              {t("Unresolved cases", "الحالات غير المحلولة")}
              <Badge variant="secondary">{filtered.length}</Badge>
            </span>
          </div>
          <div className="automatic-state-note" id="automatic-state-note">
            <ShieldCheck size={12} />
            {t(
              "Monitoring active · mandatory review and outcome verification remain enforced.",
              "المراقبة نشطة · تبقى المراجعة والتحقق الإلزاميان مفروضين.",
            )}
            {activeCards.length > 0 && !automatic && (
              <span>
                {t(
                  "Active investigations continue in parallel.",
                  "تستمر التحقيقات النشطة بالتوازي.",
                )}
              </span>
            )}
          </div>
          {activeCards.length > 0 && (
            <div
              className="active-investigations"
              data-testid="active-investigations"
            >
              {activeCards.map(({ claim, c: row }) =>
                row ? (
                  <Link
                    key={row.id}
                    className="active-investigation-card"
                    to={`/cases/${row.id}`}
                  >
                    <small>
                      {claim?.runStatus === "QUEUED"
                        ? t("QUEUED FOR WORKER", "في انتظار العامل")
                        : t("INVESTIGATING", "قيد التحقيق")}
                    </small>
                    <b>{displayId(row)}</b>
                    <span className="cell-secondary">
                      {claim?.activeStage
                        ? humanize(claim.activeStage)
                        : t(
                            stages[row.run?.stage ?? 0].label,
                            stages[row.run?.stage ?? 0].arabic,
                          )}
                    </span>
                  </Link>
                ) : null,
              )}
            </div>
          )}
          <DataTable
            columns={columns}
            data={filtered}
            rowId={(c) => c.id}
            onRowClick={(c) => navigate(`/cases/${c.id}`)}
            pagination={safePagination}
            onPaginationChange={setPagination}
            emptyTitle={
              backend && connection?.state === "connecting"
                ? t(
                    "Reading the queue from the backend…",
                    "جارٍ قراءة القائمة من الخادم…",
                  )
                : backend && connection?.state === "offline"
                  ? t(
                      "The Suhail backend is not reachable",
                      "تعذر الوصول إلى خادم سهيل",
                    )
                  : t("No matching exceptions", "لا توجد استثناءات مطابقة")
            }
            emptyDescription={
              backend && connection?.state === "offline"
                ? (connection.error ??
                  t(
                    "No cases are shown until it answers.",
                    "لا تُعرض حالات حتى يستجيب.",
                  ))
                : backend && connection?.state === "connecting"
                  ? t(
                      "No cases are shown until it answers.",
                      "لا تُعرض حالات حتى يستجيب.",
                    )
                  : t(
                      "Try another search or clear the filters.",
                      "جرّب بحثاً آخر أو امسح عوامل التصفية.",
                    )
            }
            animate
          />
          <div className="ledger-bottom">
            <ShieldCheckIcon />
            <span>
              {t(
                "Only independently verified outcomes receive a verified resolution check.",
                "لا تُمنح علامة الحل المتحقق إلا للنتائج المتحققة بشكل مستقل.",
              )}
            </span>
            <Link to="/audit">
              {t("View audit", "سجل التدقيق")}
              <ArrowRight size={12} />
            </Link>
          </div>
        </section>
        <Collapsible
          open={resolvedOpen}
          onOpenChange={setResolvedOpen}
          className="resolved-rail"
        >
          {!resolvedOpen && (
            <CollapsibleTrigger asChild>
              <Button
                variant="outline"
                className="resolved-rail-trigger"
                aria-label="Expand resolved panel"
              >
                <CheckCheck size={15} />
                <span>{t("Waiting / Resolved", "المنتظرة / المحلولة")}</span>
                <Badge variant="secondary">
                  {waiting.length} / {closed.length}
                </Badge>
                <ChevronRight size={13} />
              </Button>
            </CollapsibleTrigger>
          )}
          <AnimatePresence>
            {resolvedOpen && (
              <motion.aside
                initial={{ opacity: 0, x: 8 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 8 }}
                className="resolved-panel surface"
                aria-label="Waiting and resolved cases"
              >
                <div className="section-heading compact">
                  <h2>
                    <CheckCheck size={15} />
                    {t("Case queue", "قائمة الحالات")}
                  </h2>
                  <CollapsibleTrigger asChild>
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      aria-label="Collapse resolved panel"
                    >
                      <PanelRightClose size={14} />
                    </Button>
                  </CollapsibleTrigger>
                </div>
                <div
                  className="queue-tabs"
                  role="tablist"
                  aria-label={t("Case queue scope", "نطاق قائمة الحالات")}
                >
                  <button
                    role="tab"
                    id="waiting-tab"
                    aria-selected={queueTab === "waiting"}
                    aria-controls="case-queue-panel"
                    onClick={() => setQueueTab("waiting")}
                  >
                    {t("Waiting", "المنتظرة")} <span>{waiting.length}</span>
                  </button>
                  <button
                    role="tab"
                    id="resolved-tab"
                    aria-selected={queueTab === "resolved"}
                    aria-controls="case-queue-panel"
                    onClick={() => setQueueTab("resolved")}
                  >
                    {t("Resolved", "المحلولة")} <span>{closed.length}</span>
                  </button>
                </div>
                <p className="resolved-intro">
                  {t(
                    queueTab === "resolved"
                      ? "Backend-reported resolutions · verification shown per case"
                      : "Operational work, evidence and decisions pending",
                    queueTab === "resolved"
                      ? "حلول أبلغ عنها الخادم · حالة التحقق موضحة لكل حالة"
                      : "بانتظار العمل التشغيلي والأدلة والقرارات",
                  )}
                </p>
                {queueTab === "resolved" && pendingResolution > 0 && (
                  <p
                    className="resolved-intro"
                    role="status"
                    data-testid="resolution-pending-count"
                  >
                    {t(
                      `${pendingResolution} reported resolved · verification pending or unavailable`,
                      `${pendingResolution} أُبلغ عن حلها · التحقق قيد الانتظار أو غير متاح`,
                    )}
                  </p>
                )}
                <ScrollArea
                  className="resolved-scroll"
                  id="case-queue-panel"
                  role="tabpanel"
                  aria-labelledby={
                    queueTab === "waiting" ? "waiting-tab" : "resolved-tab"
                  }
                >
                  {!queueEntries.length && (
                    <p className="resolved-intro">
                      {t(
                        queueTab === "waiting"
                          ? "No waiting cases in the loaded queue."
                          : "No verified resolutions in the loaded queue.",
                        queueTab === "waiting"
                          ? "لا حالات منتظرة في القائمة المحملة."
                          : "لا حلول متحققة في القائمة المحملة.",
                      )}
                    </p>
                  )}
                  <AnimatePresence initial={false}>
                    {queueEntries.map((c) => (
                      <motion.div
                        key={c.id}
                        layout
                        initial={{ opacity: 0, x: -8 }}
                        animate={{ opacity: 1, x: 0 }}
                      >
                        <Link className="resolved-entry" to={`/cases/${c.id}`}>
                          <span
                            className={
                              verifiedResolution(c)
                                ? "verified-check"
                                : "waiting-check"
                            }
                          >
                            {verifiedResolution(c) ? (
                              <CheckCheck size={14} />
                            ) : (
                              <Clock3 size={14} />
                            )}
                          </span>
                          <div>
                            <b dir="ltr">{displayId(c)}</b>
                            <p>{c.issue}</p>
                            {!verifiedResolution(c) && (
                              <p className="waiting-label">
                                {t(...waitingLabel(c))}
                              </p>
                            )}
                            <small>
                              <Clock3 size={10} />
                              {timeLabel(
                                c.outcome?.timestamp ?? c.openedAt,
                              )}{" "}
                              AST
                            </small>
                          </div>
                          <ArrowRight size={13} />
                        </Link>
                      </motion.div>
                    ))}
                  </AnimatePresence>
                </ScrollArea>
                {running && (
                  <Link className="rail-running" to={`/cases/${running.id}`}>
                    <Sparkles size={14} />
                    <div>
                      <small>
                        {t("CURRENTLY INVESTIGATING", "قيد التحقيق الآن")}
                      </small>
                      <b>{displayId(running)}</b>
                      <p>
                        {t(
                          stages[running.run?.stage ?? 0].label,
                          stages[running.run?.stage ?? 0].arabic,
                        )}
                      </p>
                    </div>
                  </Link>
                )}
                <dl className="rail-summary">
                  <div>
                    <dt>{t("Open cases", "حالات مفتوحة")}</dt>
                    <dd>{active.length}</dd>
                  </div>
                  <div>
                    <dt>{t("Human attention", "تدخل بشري")}</dt>
                    <dd>{human.length}</dd>
                  </div>
                  <div>
                    <dt>{t("Verified outcomes", "نتائج متحققة")}</dt>
                    <dd>{resolved.length}</dd>
                  </div>
                </dl>
                <Button
                  asChild
                  variant="ghost"
                  size="sm"
                  className="rail-history"
                >
                  <Link to="/audit?kind=resolution">
                    {t("Resolution history", "سجل الحلول")}
                    <ArrowRight size={13} />
                  </Link>
                </Button>
              </motion.aside>
            )}
          </AnimatePresence>
        </Collapsible>
      </div>
      {(query ||
        status !== "all" ||
        priority !== "all" ||
        city !== "all" ||
        cause !== "all" ||
        operational !== "all") && (
        <Button
          variant="ghost"
          size="sm"
          onClick={clear}
          className="clear-filters-link"
        >
          <X size={12} />
          {t("Clear applied filters", "مسح عوامل التصفية المطبقة")}
        </Button>
      )}
    </>
  );
}
function ShieldCheckIcon() {
  return <CheckCheck size={12} />;
}
