import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowRight,
  CheckCheck,
  ChevronRight,
  Clock3,
  PanelRightClose,
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

export function OperationsPage() {
  const { cases, automatic, service, catalog, backend, connection } =
    useOperations();
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
  const [refreshing, setRefreshing] = useState(false);
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: 10 });
  useCanopusScreen({
    screen: "operations",
    filters: { search: query, status, priority, city, cause },
  });
  const active = cases.filter((c) => c.status !== "resolved");
  const resolved = cases.filter(
    (c) => c.status === "resolved" && c.outcome?.successful,
  );
  // Backend: the case the investigation worker holds now. Lab: the one simulated run.
  const running = backend
    ? cases.find((c) => c.id === connection?.worker?.activeCaseId)
    : cases.find((c) =>
        ["investigating", "executing", "verifying"].includes(c.status),
      );
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
                  ? t("Read the queue from the backend", "قراءة القائمة من الخادم")
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
              {running
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
            {running && !automatic && (
              <span>
                {t("Current case continues.", "تستمر الحالة الحالية.")}
              </span>
            )}
          </div>
          <DataTable
            columns={columns}
            data={filtered}
            rowId={(c) => c.id}
            onRowClick={(c) => navigate(`/cases/${c.id}`)}
            pagination={safePagination}
            onPaginationChange={setPagination}
            emptyTitle={
              backend && connection?.state === "connecting"
                ? t("Reading the queue from the backend…", "جارٍ قراءة القائمة من الخادم…")
                : backend && connection?.state === "offline"
                  ? t("The Suhail backend is not reachable", "تعذر الوصول إلى خادم سهيل")
                  : t("No matching exceptions", "لا توجد استثناءات مطابقة")
            }
            emptyDescription={
              backend && connection?.state === "offline"
                ? (connection.error ??
                  t("No cases are shown until it answers.", "لا تُعرض حالات حتى يستجيب."))
                : backend && connection?.state === "connecting"
                  ? t("No cases are shown until it answers.", "لا تُعرض حالات حتى يستجيب.")
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
                "Only independently verified outcomes move to Resolved.",
                "لا تنتقل إلى المحلولة إلا النتائج المتحققة بشكل مستقل.",
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
                <span>{t("Resolved", "المحلولة")}</span>
                <Badge variant="secondary">{resolved.length}</Badge>
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
                aria-label="Verified resolutions"
              >
                <div className="section-heading compact">
                  <h2>
                    <CheckCheck size={15} />
                    {t("Resolved", "المحلولة")}
                    <Badge variant="secondary">{resolved.length}</Badge>
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
                <p className="resolved-intro">
                  {t(
                    "Independently verified outcomes",
                    "نتائج تحققت بشكل مستقل",
                  )}
                </p>
                <ScrollArea className="resolved-scroll">
                  <AnimatePresence initial={false}>
                    {resolved.map((c) => (
                      <motion.div
                        key={c.id}
                        layout
                        initial={{ opacity: 0, x: -8 }}
                        animate={{ opacity: 1, x: 0 }}
                      >
                        <Link className="resolved-entry" to={`/cases/${c.id}`}>
                          <span className="verified-check">
                            <CheckCheck size={14} />
                          </span>
                          <div>
                            <b dir="ltr">{displayId(c)}</b>
                            <p>{c.issue}</p>
                            <small>
                              <Clock3 size={10} />
                              {timeLabel(c.outcome!.timestamp)} AST
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
