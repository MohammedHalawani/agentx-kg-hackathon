import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowRight,
  CheckCheck,
  CircleCheckBig,
  Hourglass,
  Inbox,
  ScanSearch,
  UserRound,
  ChevronLeft,
  ChevronRight,
  Clock3,
  PanelRightClose,
  SkipForward,
  Pause,
  Play,
  RefreshCw,
  Search,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { toast } from "sonner";
import type { ColumnDef } from "@tanstack/react-table";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Collapsible, CollapsibleTrigger } from "@/components/ui/collapsible";
import { OperationsFilters } from "@/components/operations-filters";
import {
  MonitoringStatus,
  useMonitorOverview,
} from "@/components/monitor-overview";
import { KpiCards } from "@/components/kpi-cards";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  defaultQueueFilters,
  caseQueuePage,
  CASE_QUEUE_PAGE_SIZE,
  STAGE_GROUPS,
  investigationAssignments,
  operationsCollection,
} from "@/domain/desktop-operations";
import { DataTable } from "@/components/data-table";
import { CaseLink, PageTitle, PriorityLabel } from "@/components/shared";
import { timeLabel } from "@/lib/dates";
import { useOperations } from "@/state/operations";
import { usePreferences } from "@/state/preferences";
import { type OperationalCase } from "@/domain/types";
import {
  displayId,
  matchesCause,
  matchesOperational,
  searchText,
} from "@/domain/case-view";
import { useCanopusScreen } from "@/state/canopus";
import {
  byRecordedPriority,
  lastUpdateOf,
  nextActionOf,
} from "@/domain/priority";
import { viewLabel, viewRule, viewRows } from "@/domain/operations-assistant";
import {
  clearOpsView,
  undoOpsView,
  useCanUndoOpsView,
  useOpsView,
} from "@/state/ops-view";
import { Sparkles, Undo2, X } from "lucide-react";
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
    backend: fromBackend,
    connection,
  } = useOperations();
  // Connected build: always the backend, so lab-only branches are removed at build time.
  const backend = !LAB_BUILD || fromBackend;
  const { t } = usePreferences();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState(defaultQueueFilters);
  const { status, priority, city, cause, operational, sort } = filters;
  const [resolvedOpen, setResolvedOpen] = useState(false);
  const [queueTab, setQueueTab] = useState<"waiting" | "resolved">("waiting");
  const [queuePages, setQueuePages] = useState({ waiting: 0, resolved: 0 });
  const queueList = useRef<HTMLDivElement>(null);
  const focusedQueueCase = useRef<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const overview = useMonitorOverview(backend);
  // A KPI card applies the matching stage filter over all loaded cases; "Clear applied
  // filters" undoes it. Its count is the backend's; the table lists the loaded cases.
  const kpiFilter =
    filters.collection === "all" &&
    filters.stage === "all" &&
    filters.status === "all"
      ? "open"
      : filters.stage === "awaiting_investigation"
        ? "awaiting"
        : filters.stage === "action_pending"
          ? "pending"
          : filters.stage === "human_review"
            ? "person"
            : null;
  function applyKpi(card: "open" | "awaiting" | "pending" | "person") {
    setQuery("");
    setFilters({
      ...defaultQueueFilters,
      collection: "all",
      stage: {
        open: "all",
        awaiting: "awaiting_investigation",
        pending: "action_pending",
        person: "human_review",
      }[card],
    });
    resetPage();
  }
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: 10 });
  useCanopusScreen({
    screen: "operations",
    filters: { search: query, status, priority, city, cause },
  });
  const active = cases.filter((c) => caseQueueGroup(c) === "active");
  const resolved = cases.filter((c) => verifiedResolution(c));
  const closed = cases.filter((c) => caseQueueGroup(c) !== "active");
  const pendingResolution = closed.length - resolved.length;
  const activeClaims = investigationAssignments(connection?.worker, cases);
  const collectionOf = (c: OperationalCase) =>
    operationsCollection(c, activeClaims);
  const waiting = cases.filter((c) => collectionOf(c) === "waiting");
  const queueEntries = queueTab === "waiting" ? waiting : closed;
  const waitingPageCount = Math.ceil(waiting.length / CASE_QUEUE_PAGE_SIZE);
  const closedPageCount = Math.ceil(closed.length / CASE_QUEUE_PAGE_SIZE);
  const queuePage = caseQueuePage(queueEntries, queuePages[queueTab]);
  useLayoutEffect(() => {
    // Keep keyboard focus inside the queue if a polled removal unmounts its focused row.
    if (!focusedQueueCase.current || document.activeElement !== document.body)
      return;
    const links = [
      ...(queueList.current?.querySelectorAll<HTMLAnchorElement>(
        "a[data-case-id]",
      ) ?? []),
    ];
    const target =
      links.find((link) => link.dataset.caseId === focusedQueueCase.current) ??
      links[0] ??
      queueList.current;
    target?.focus();
  }, [queuePage.items]);
  useEffect(() => {
    // Persist the clamp so later arrivals cannot revive an out-of-range old page.
    setQueuePages((previous) => {
      const waiting = Math.min(
        previous.waiting,
        Math.max(0, waitingPageCount - 1),
      );
      const resolved = Math.min(
        previous.resolved,
        Math.max(0, closedPageCount - 1),
      );
      return waiting === previous.waiting && resolved === previous.resolved
        ? previous
        : { waiting, resolved };
    });
  }, [waitingPageCount, closedPageCount]);
  function moveQueueTab(event: KeyboardEvent<HTMLButtonElement>) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next =
      event.key === "Home"
        ? "waiting"
        : event.key === "End"
          ? "resolved"
          : queueTab === "waiting"
            ? "resolved"
            : "waiting";
    setQueueTab(next);
    document
      .getElementById(next === "waiting" ? "waiting-tab" : "resolved-tab")
      ?.focus();
  }
  const human = active.filter((c) =>
    ["human_review", "needs_evidence", "escalated"].includes(c.status),
  );
  const resetPage = () => setPagination((p) => ({ ...p, pageIndex: 0 }));
  const assistant = useOpsView();
  const canUndoAssistant = useCanUndoOpsView();
  // A view Canopus applied replaces the collection and filters until it is cleared or undone;
  // it is shown above the table, and it only reads the loaded cases.
  const filtered = assistant
    ? viewRows(assistant.view, cases)
    : cases
        .filter(
          (c) =>
            query.trim() ||
            filters.collection === "all" ||
            collectionOf(c) === filters.collection,
        )
        .filter(
          (c) =>
            (status === "all" ||
              c.status === status ||
              (status === "attention" &&
                ["human_review", "needs_evidence", "escalated"].includes(
                  c.status,
                ))) &&
            (priority === "all" || c.priority === priority) &&
            (filters.stage === "all" ||
              (caseQueueGroup(c) === "active" &&
                !!STAGE_GROUPS[filters.stage]?.includes(
                  c.backend?.workflowState ?? "",
                ))) &&
            (city === "all" ||
              c.shipment.destination === city ||
              c.shipment.origin === city) &&
            matchesCause(c, cause) &&
            matchesOperational(c, operational) &&
            searchText(c).includes(query.toLowerCase()),
        )
        .sort((a, b) =>
          sort === "priority"
            ? byRecordedPriority(a, b)
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
  const sortByPriority = () => {
    setFilters((value) => ({
      ...value,
      sort: value.sort === "priority" ? "newest" : "priority",
    }));
    resetPage();
  };
  const columns: ColumnDef<OperationalCase>[] = [
    {
      id: "priority",
      header: () => (
        <button
          type="button"
          className="sort-header"
          aria-label={t("Sort by priority", "الترتيب حسب الأولوية")}
          aria-pressed={sort === "priority" || !!assistant}
          onClick={sortByPriority}
          disabled={!!assistant}
        >
          {t("Priority", "الأولوية")}
          <span aria-hidden="true">
            {sort === "priority" || assistant ? "↓" : "↕"}
          </span>
        </button>
      ),
      size: 80,
      cell: ({ row }) => <PriorityLabel priority={row.original.priority} />,
    },
    {
      id: "shipment",
      header: t("Shipment", "الشحنة"),
      size: 130,
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
      header: t("Problem", "المشكلة"),
      size: 200,
      cell: ({ row }) => (
        <span className="exception-name">{row.original.issue}</span>
      ),
    },
    {
      id: "next",
      header: t("Next action", "الإجراء التالي"),
      size: 160,
      cell: ({ row }) => {
        const next = nextActionOf(row.original);
        return (
          <span
            className={`next-action-cell ${next.pending ? "muted" : ""} ${next.actor === "operator" ? "by-operator" : ""}`}
          >
            {t(next.label[0], next.label[1])}
          </span>
        );
      },
    },
    {
      id: "time",
      header: t("Last update · AST", "آخر تحديث · السعودية"),
      size: 100,
      cell: ({ row }) => (
        <span className="received-time">
          {timeLabel(lastUpdateOf(row.original))}
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
    setFilters(defaultQueueFilters);
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
        {!backend && (
          <span className="inline-count">
            {active.length} {t("open", "مفتوحة")}
            <i>·</i>
            {human.length} {t("need attention", "تتطلب انتباهاً")}
          </span>
        )}
      </PageTitle>
      {backend && (
        <>
          <KpiCards
            testId="operations-kpis"
            label={t("Case counts", "أعداد الحالات")}
            cards={[
              {
                key: "open",
                icon: <Inbox size={15} />,
                value: overview?.cases_open ?? null,
                label: t("Open cases", "حالات مفتوحة"),
                title: t(
                  "Cases not closed, as the backend's case ledger counts them now.",
                  "الحالات غير المغلقة كما يعدها سجل الحالات في الخادم الآن.",
                ),
                active: kpiFilter === "open",
                onSelect: () => applyKpi("open"),
              },
              {
                key: "awaiting",
                icon: <ScanSearch size={15} />,
                value: overview?.awaiting_investigation ?? null,
                label: t("Awaiting investigation", "بانتظار التحقيق"),
                title: t(
                  "Detected exceptions not yet investigated.",
                  "استثناءات مكتشفة لم يُحقَّق فيها بعد.",
                ),
                active: kpiFilter === "awaiting",
                onSelect: () => applyKpi("awaiting"),
              },
              {
                key: "pending",
                icon: <Hourglass size={15} />,
                value: overview?.action_pending ?? null,
                label: t("Action pending", "إجراء معلّق"),
                title: t(
                  "Investigated; a recommendation, approval, request or outcome is pending.",
                  "اكتمل التحقيق؛ توصية أو موافقة أو طلب أو نتيجة معلّقة.",
                ),
                active: kpiFilter === "pending",
                onSelect: () => applyKpi("pending"),
              },
              {
                key: "person",
                icon: <UserRound size={15} />,
                value: overview?.human_review ?? null,
                label: t("With a person", "لدى شخص"),
                title: t(
                  "Human review, escalated or rejected.",
                  "مراجعة بشرية أو مصعّدة أو مرفوضة.",
                ),
                active: kpiFilter === "person",
                onSelect: () => applyKpi("person"),
              },
              {
                key: "verified",
                icon: <CircleCheckBig size={15} />,
                value: overview?.verified_resolved ?? null,
                label: t("Verified resolved", "حُلّت بتحقق"),
                title: t(
                  "Closed by the verifier or a person's verified finding.",
                  "أُغلقت بالمدقق أو بنتيجة بشرية متحقق منها.",
                ),
                onSelect: () => {
                  setResolvedOpen(true);
                  setQueueTab("resolved");
                },
              },
            ]}
          />
          <MonitoringStatus overview={overview} />
        </>
      )}
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
            <OperationsFilters
              value={filters}
              onChange={(next) => {
                setFilters(next);
                resetPage();
              }}
              cities={cities}
            />
          </div>
          <div className="queue-controls">
            {backend && connection?.clock && (
              <span
                className={`clock-state ${connection.clock.running ? "running" : ""}`}
                data-testid="clock-state"
              >
                <Clock3 size={11} />
                {connection.clock.running
                  ? t(
                      `Clock ×${connection.clock.speed}`,
                      `الساعة ×${connection.clock.speed}`,
                    )
                  : t("Clock paused", "الساعة متوقفة")}
              </span>
            )}
            {backend && connection?.clock && service.setClock && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="outline"
                    size="icon-sm"
                    className="clock-control"
                    data-testid="clock-control"
                    aria-pressed={connection.clock.running}
                    aria-label={
                      connection.clock.running
                        ? t(
                            "Pause the simulated clock",
                            "إيقاف الساعة المحاكاة",
                          )
                        : t(
                            "Start the simulated clock",
                            "تشغيل الساعة المحاكاة",
                          )
                    }
                    disabled={skipping || connection.controls === "unavailable"}
                    onClick={() =>
                      void service.setClock!(!connection.clock!.running).catch(
                        (e: Error) => toast.error(e.message),
                      )
                    }
                  >
                    {connection.clock.running ? (
                      <Pause size={13} />
                    ) : (
                      <Play size={13} />
                    )}
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  {connection.clock.running
                    ? t(
                        "Pause the simulated clock. New exceptions and request answers stop arriving until it runs again. Investigations are not affected.",
                        "إيقاف الساعة المحاكاة. يتوقف وصول الاستثناءات الجديدة وإجابات الطلبات حتى تعمل مجدداً. لا يتأثر التحقيق.",
                      )
                    : t(
                        "Start the simulated clock. New exceptions arrive and requests are answered only while it runs. This does not start an investigation.",
                        "تشغيل الساعة المحاكاة. تصل الاستثناءات الجديدة وتُجاب الطلبات فقط أثناء تشغيلها. لا يبدأ ذلك تحقيقاً.",
                      )}
                </TooltipContent>
              </Tooltip>
            )}
            {backend && connection?.clock && service.skipClock && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="outline"
                    size="icon-sm"
                    className="clock-control"
                    data-testid="clock-skip"
                    aria-label={t(
                      "Skip the simulated clock to the next event",
                      "تخطي الساعة المحاكاة إلى الحدث التالي",
                    )}
                    disabled={skipping || connection.controls === "unavailable"}
                    onClick={skipToNext}
                  >
                    <SkipForward
                      size={13}
                      className={skipping ? "slow-spin" : ""}
                    />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  {t(
                    "Run the simulated clock fast until an awaited result arrives or a new case opens, then return to the current speed. It does not start an AI investigation.",
                    "تشغيل الساعة المحاكاة بسرعة حتى تصل نتيجة منتظرة أو تُفتح حالة جديدة، ثم العودة إلى السرعة الحالية. لا يبدأ تحقيقاً بالذكاء الاصطناعي.",
                  )}
                </TooltipContent>
              </Tooltip>
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
              {assistant
                ? t(
                    "Canopus view · loaded open cases",
                    "عرض كانوبس · الحالات المفتوحة المحملة",
                  )
                : query.trim() || filters.collection === "all"
                  ? t(
                      "Search / history · all loaded cases",
                      "البحث / السجل · كل الحالات المحملة",
                    )
                  : filters.collection === "unassigned"
                    ? t(
                        "Open cases with no reported assignment",
                        "حالات مفتوحة دون تكليف مسجل",
                      )
                    : t("Filtered case collection", "مجموعة حالات مصفاة")}
            </span>
            <Badge variant="secondary">{filtered.length}</Badge>
          </div>
          <p className="automatic-state-note" id="automatic-state-note">
            {t(
              "Automatic claims are rechecked by the backend. Review and outcome verification remain mandatory.",
              "يتحقق الخادم من التكليفات التلقائية. تظل المراجعة والتحقق من النتائج إلزاميين.",
            )}
          </p>
          {connection?.queue?.truncated && (
            <p className="automatic-state-note">
              {t(
                "Only the loaded subset is shown; additional backend cases are outside this view.",
                "تُعرض المجموعة المحملة فقط؛ توجد حالات إضافية خارج هذا العرض.",
              )}
            </p>
          )}
          {assistant && (
            <div
              className="assistant-view-chip"
              role="status"
              data-testid="assistant-view"
            >
              <Sparkles size={13} aria-hidden="true" />
              <div>
                <b>
                  {t("Canopus applied", "طبّق كانوبس")}:{" "}
                  {t(...viewLabel(assistant.view))}
                </b>
                <small>
                  {t(...viewRule(assistant.view))}{" "}
                  {t(
                    "Visible view only · nothing changed on the server.",
                    "عرض مرئي فقط · لم يتغير شيء في الخادم.",
                  )}
                </small>
              </div>
              {canUndoAssistant && (
                <Button variant="ghost" size="sm" onClick={undoOpsView}>
                  <Undo2 size={12} />
                  {t("Undo", "تراجع")}
                </Button>
              )}
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={t("Clear Canopus view", "إزالة عرض كانوبس")}
                onClick={clearOpsView}
              >
                <X size={13} />
              </Button>
            </div>
          )}
          <DataTable
            compact
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
                  : !query.trim() && filters.collection === "unassigned"
                    ? t("No unassigned cases", "لا حالات غير مكلّفة")
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
          <Link className="queue-audit-link" to="/audit">
            {t("View audit", "سجل التدقيق")}
            <ArrowRight size={12} />
          </Link>
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
                <span>{t("Waiting / Closed", "المنتظرة / المغلقة")}</span>
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
                aria-label="Waiting and closed cases"
              >
                <div className="section-heading compact">
                  <h2>
                    <CheckCheck size={15} />
                    {t("Case queue", "قائمة الحالات")}
                  </h2>
                  <Link
                    className="view-all-decisions"
                    to="/decisions"
                    data-testid="view-all-decisions"
                  >
                    {t("View all decisions", "عرض كل القرارات")}
                    <ArrowRight size={12} />
                  </Link>
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
                    tabIndex={queueTab === "waiting" ? 0 : -1}
                    onKeyDown={moveQueueTab}
                    onClick={() => setQueueTab("waiting")}
                  >
                    {t("Waiting", "المنتظرة")} <span>{waiting.length}</span>
                  </button>
                  <button
                    role="tab"
                    id="resolved-tab"
                    aria-selected={queueTab === "resolved"}
                    aria-controls="case-queue-panel"
                    tabIndex={queueTab === "resolved" ? 0 : -1}
                    onKeyDown={moveQueueTab}
                    onClick={() => setQueueTab("resolved")}
                  >
                    {t("Closed", "المغلقة")} <span>{closed.length}</span>
                  </button>
                </div>
                <p className="resolved-intro">
                  {t(
                    queueTab === "resolved"
                      ? "Closed cases · verification shown per case"
                      : "Operational work, evidence and decisions pending",
                    queueTab === "resolved"
                      ? "حالات مغلقة · حالة التحقق موضحة لكل حالة"
                      : "بانتظار العمل التشغيلي والأدلة والقرارات",
                  )}
                </p>
                {connection?.queue?.truncated && (
                  <p
                    className="case-queue-subset"
                    data-testid="case-queue-subset"
                  >
                    {t(
                      "Loaded queue only · more cases exist on the backend. Counts below describe loaded records.",
                      "القائمة المحملة فقط · توجد حالات إضافية في الخادم. الأعداد أدناه للسجلات المحملة.",
                    )}
                  </p>
                )}
                {queueTab === "resolved" && (
                  <p
                    className="closed-counts"
                    role="status"
                    data-testid="resolution-pending-count"
                  >
                    <span>
                      {resolved.length} {t("verified", "متحققة")}
                    </span>
                    <span>
                      {pendingResolution} {t("unconfirmed", "غير مؤكدة")}
                    </span>
                  </p>
                )}
                <div
                  className="case-queue-list"
                  ref={queueList}
                  tabIndex={-1}
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
                          : "No closed cases in the loaded queue.",
                        queueTab === "waiting"
                          ? "لا حالات منتظرة في القائمة المحملة."
                          : "لا حالات مغلقة في القائمة المحملة.",
                      )}
                    </p>
                  )}
                  {queuePage.items.map((c) => (
                    <Link
                      key={c.id}
                      data-case-id={c.id}
                      onFocus={() => {
                        focusedQueueCase.current = c.id;
                      }}
                      onBlur={() => {
                        focusedQueueCase.current = null;
                      }}
                      className="resolved-entry"
                      to={`/cases/${c.id}`}
                    >
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
                          {timeLabel(c.outcome?.timestamp ?? c.openedAt)} AST
                        </small>
                      </div>
                      <ArrowRight size={13} />
                    </Link>
                  ))}
                </div>
                <nav
                  className="case-queue-pagination"
                  aria-label={t("Case queue pagination", "ترقيم قائمة الحالات")}
                >
                  <span>
                    {t(
                      `Showing ${queuePage.total ? queuePage.start + 1 : 0}–${queuePage.end} of ${queuePage.total}${connection?.queue?.truncated ? " loaded" : ""}`,
                      `عرض ${queuePage.total ? queuePage.start + 1 : 0}–${queuePage.end} من ${queuePage.total}${connection?.queue?.truncated ? " محملة" : ""}`,
                    )}
                  </span>
                  <div>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={t(
                        "Previous case queue page",
                        "الصفحة السابقة للحالات",
                      )}
                      disabled={!queuePage.pageIndex}
                      onClick={() =>
                        setQueuePages((previous) => ({
                          ...previous,
                          [queueTab]: queuePage.pageIndex - 1,
                        }))
                      }
                    >
                      <ChevronLeft size={13} />
                    </Button>
                    <span
                      className="case-queue-page-index"
                      dir="ltr"
                      aria-live="polite"
                    >
                      {queuePage.pageCount ? queuePage.pageIndex + 1 : 0} /{" "}
                      {queuePage.pageCount}
                    </span>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={t(
                        "Next case queue page",
                        "الصفحة التالية للحالات",
                      )}
                      disabled={
                        !queuePage.pageCount ||
                        queuePage.pageIndex >= queuePage.pageCount - 1
                      }
                      onClick={() =>
                        setQueuePages((previous) => ({
                          ...previous,
                          [queueTab]: queuePage.pageIndex + 1,
                        }))
                      }
                    >
                      <ChevronRight size={13} />
                    </Button>
                  </div>
                </nav>
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
                <Link className="rail-history" to="/audit?kind=resolution">
                  {t("Resolution history", "سجل الحلول")}
                  <ArrowRight size={13} />
                </Link>
              </motion.aside>
            )}
          </AnimatePresence>
        </Collapsible>
      </div>
      {(query ||
        Object.keys(filters).some(
          (key) =>
            filters[key as keyof typeof filters] !==
            defaultQueueFilters[key as keyof typeof filters],
        )) && (
        <Button
          variant="ghost"
          size="sm"
          onClick={clear}
          className="clear-filters-link"
        >
          {t("Clear applied filters", "مسح عوامل التصفية المطبقة")}
        </Button>
      )}
    </>
  );
}
