import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type { ColumnDef, PaginationState } from "@tanstack/react-table";
import type { DateRange } from "react-day-picker";
import { format } from "date-fns";
import {
  ArrowRight,
  ArrowUpDown,
  CalendarDays,
  Search,
  SlidersHorizontal,
  ShieldCheck,
  ScrollText,
  Package,
  X,
  RefreshCw,
  ChevronRight,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Calendar } from "@/components/ui/calendar";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { ScrollArea } from "@/components/ui/scroll-area";
import { SelectControl } from "@/components/select-control";
import { DataTable } from "@/components/data-table";
import {
  PageTitle,
  CaseLink,
  StatusBadge,
  EmptyState,
} from "@/components/shared";
import { PageAssistant } from "@/components/page-assistant";
import { useOperations } from "@/state/operations";
import { usePreferences } from "@/state/preferences";
import {
  queryAudit,
  LAB_TODAY,
  rangeStarts,
  riyadhToday,
} from "@/services/page-queries";
import { displayId } from "@/domain/case-view";
import {
  emptyAuditFilters,
  supportedStatuses,
  type AuditFilters,
  type PageAction,
  type TimeRange,
} from "@/domain/page-actions";
import {
  stages,
  statusLabels,
  type InvestigationStageEvent,
} from "@/domain/types";
import { dateLabel, timeLabel, dateTimeLabel } from "@/lib/dates";
import { useCanopusScreen } from "@/state/canopus";
const LAB_BUILD = import.meta.env.VITE_SUHAIL_DATA === "lab";

const kinds = [
  "intake",
  "investigation",
  "evidence",
  "recommendation",
  "policy",
  "decision",
  "execution",
  "verification",
  "resolution",
] as const;
const labels = {
  intake: "Intake",
  investigation: "Investigation",
  evidence: "Evidence",
  recommendation: "Recommendation",
  policy: "Review",
  decision: "Operator decision",
  execution: "Execution",
  verification: "Verification",
  resolution: "Resolution",
};
const arabic = {
  intake: "الوارد",
  investigation: "التحقيق",
  evidence: "الأدلة",
  recommendation: "التوصية",
  policy: "المراجعة",
  decision: "قرار المشغل",
  execution: "التنفيذ",
  verification: "التحقق",
  resolution: "الحل",
};
type AuditMode = "events" | "by_shipment";
/** Backend ledger: open on everything recorded, newest first (stored runs are rarely from today). */
const backendAuditFilters: AuditFilters = {
  ...emptyAuditFilters,
  timeRange: "all",
  sort: "newest",
};
const shortDate = (day: string) =>
  new Date(`${day}T12:00:00Z`).toLocaleDateString("en-GB", {
    timeZone: "UTC",
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
export function AuditPage() {
  const snapshot = useOperations();
  const {
    cases,
    events,
    backend: fromBackend,
    service,
    connection,
    catalog,
  } = snapshot;
  // Connected build: always the backend, so lab-only branches are removed at build time.
  const backend = !LAB_BUILD || fromBackend;
  const base = backend ? backendAuditFilters : emptyAuditFilters;
  // Lab fixtures are anchored to a fixed day; backend records use the real calendar.
  const today = backend ? riyadhToday() : LAB_TODAY;
  useEffect(() => {
    void service.loadAudit?.();
  }, [service]);
  // Backend "policy" records come from the review stage and from the authority policy alike.
  const kindLabel = (kind: InvestigationStageEvent["kind"]) =>
    backend && kind === "policy"
      ? t("Review / policy", "المراجعة / السياسة")
      : t(labels[kind], arabic[kind]);
  const label = (id: string) => {
    const found = cases.find((c) => c.id === id);
    return found ? displayId(found) : id;
  };
  const { t, preferences } = usePreferences();
  const [params, setParams] = useSearchParams();
  const filters = {
    ...base,
    ...Object.fromEntries(
      Object.keys(base).map((key) => [
        key,
        params.get(key === "shipmentId" ? "case" : key) ??
          (key === "timeRange" && params.has("case")
            ? "all"
            : base[key as keyof AuditFilters]),
      ]),
    ),
  } as AuditFilters;
  const mode: AuditMode =
    params.get("mode") === "by_shipment" ? "by_shipment" : "events";
  const [pagination, setPagination] = useState<PaginationState>({
    pageIndex: 0,
    pageSize: 10,
  });
  const [selected, setSelected] = useState<InvestigationStageEvent | null>(
    null,
  );
  const [timelineId, setTimelineId] = useState(
    params.get("case") ?? (backend ? "" : "SHP-10482"),
  );
  const [dateOpen, setDateOpen] = useState(false);
  const [range, setRange] = useState<DateRange | undefined>({
    from: new Date(`${today}T12:00:00`),
    to: new Date(`${today}T12:00:00`),
  });
  const previous = useRef<{ params: string; timelineId: string } | null>(null);
  const filterKey = JSON.stringify(filters);
  const result = useMemo(
    () =>
      queryAudit(
        snapshot,
        JSON.parse(filterKey),
        0,
        Number.MAX_SAFE_INTEGER,
        backend ? today : undefined,
      ),
    [snapshot, filterKey, backend, today],
  );
  const safePagination = {
    ...pagination,
    pageIndex: Math.min(
      pagination.pageIndex,
      Math.max(0, Math.ceil(result.total / pagination.pageSize) - 1),
    ),
  };
  const pageEvents = result.items.slice(
    safePagination.pageIndex * safePagination.pageSize,
    (safePagination.pageIndex + 1) * safePagination.pageSize,
  );
  const shipmentIds = new Set(result.items.map((e) => e.caseId));
  const matchingCases = result.matchingShipments.filter((c) =>
    shipmentIds.has(c.id),
  );
  const timelineCase =
    matchingCases.find((c) => c.id === timelineId) ?? matchingCases[0];
  const timelineEvents = result.items
    .filter((e) => e.caseId === timelineCase?.id)
    .sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp));
  useCanopusScreen({
    screen: "audit",
    caseId:
      mode === "by_shipment"
        ? timelineCase?.id
        : filters.shipmentId !== "all"
          ? filters.shipmentId
          : undefined,
    filters: { ...filters, mode },
  });
  function update(patch: Partial<AuditFilters>, nextMode = mode) {
    const next = { ...filters, ...patch },
      query = new URLSearchParams();
    Object.entries(next).forEach(([key, value]) => {
      if (value !== base[key as keyof AuditFilters])
        query.set(key === "shipmentId" ? "case" : key, value);
    });
    // Preserve an explicit Today range when a shipment is selected.
    if (next.shipmentId !== "all") query.set("timeRange", next.timeRange);
    if (nextMode === "by_shipment") query.set("mode", nextMode);
    setParams(query, { replace: true });
    setPagination((p) => ({ ...p, pageIndex: 0 }));
  }
  function apply(actions: PageAction[]) {
    previous.current = { params: params.toString(), timelineId };
    let next = { ...filters },
      nextMode = mode,
      id = timelineId;
    for (const action of actions) {
      if (action.type === "filter_audit_events")
        next = { ...next, ...action.filters };
      if (action.type === "select_shipment") {
        next.shipmentId = action.caseId;
        id = action.caseId;
      }
      if (action.type === "change_view")
        nextMode = action.view === "events" ? "events" : "by_shipment";
    }
    if (
      actions.some(
        (a) =>
          a.type === "filter_audit_events" &&
          a.filters.shipmentId &&
          !a.filters.timeRange,
      )
    ) {
      next.timeRange = "all";
      id = next.shipmentId;
    }
    const output = queryAudit(
      snapshot,
      next,
      0,
      Number.MAX_SAFE_INTEGER,
      backend ? today : undefined,
    );
    update(next, nextMode);
    setTimelineId(id);
    toast.info(
      t(
        `Audit updated · ${output.total} matching events`,
        `تم تحديث التدقيق · ${output.total} أحداث مطابقة`,
      ),
    );
    return t(
      `${output.total} matching ${LAB_BUILD ? "simulated " : ""}events across ${output.uniqueShipments} unique shipments and ${output.uniqueCases} cases. ${next.destination !== "all" ? `Destination: ${next.destination}. ` : ""}Time range: ${next.timeRange}. ${nextMode === "by_shipment" ? "Shipment histories are shown." : "The event table is updated."}${output.total === 0 ? " No records match; try a broader time range or clear a filter." : ""}`,
      `${output.total} أحداث محاكاة مطابقة تخص ${output.uniqueShipments} شحنات فريدة و${output.uniqueCases} حالات. ${next.destination !== "all" ? `الوجهة: ${next.destination}. ` : ""}${nextMode === "by_shipment" ? "تظهر سجلات الشحنات المطابقة." : "تم تحديث جدول الأحداث."}${output.total === 0 ? " لا توجد سجلات مطابقة؛ وسّع الفترة الزمنية أو أزل أحد المرشحات." : ""}`,
    );
  }
  const columns: ColumnDef<InvestigationStageEvent>[] = [
    {
      id: "time",
      size: 135,
      header: () => (
        <Button
          variant="ghost"
          size="sm"
          className="table-sort"
          onClick={() =>
            update({ sort: filters.sort === "oldest" ? "newest" : "oldest" })
          }
          aria-label="Toggle audit time order"
        >
          {t("Time · AST", "الوقت · السعودية")}
          <ArrowUpDown size={11} />
        </Button>
      ),
      cell: ({ row }) => {
        const timestamp =
          filters.timeBasis === "evidence"
            ? (row.original.evidenceTimestamp ?? row.original.timestamp)
            : row.original.timestamp;
        return (
          <span className="audit-time">
            {timeLabel(timestamp)}
            <small className="cell-secondary">{dateLabel(timestamp)}</small>
          </span>
        );
      },
    },
    {
      id: "shipment",
      header: t("Shipment", "الشحنة"),
      size: 130,
      cell: ({ row }) => (
        <CaseLink id={row.original.caseId} label={label(row.original.caseId)} />
      ),
    },
    {
      id: "type",
      header: t("Type", "النوع"),
      size: 134,
      cell: ({ row }) => (
        <Badge
          variant="secondary"
          className={`event-type event-type-${row.original.kind}`}
        >
          {kindLabel(row.original.kind)}
        </Badge>
      ),
    },
    {
      id: "event",
      header: t("Event", "الحدث"),
      size: 440,
      cell: ({ row }) => (
        <div>
          <Button
            variant="link"
            className="audit-event-button"
            onClick={() => setSelected(row.original)}
          >
            {row.original.title}
          </Button>
          <span
            className="cell-secondary audit-detail"
            title={row.original.detail}
          >
            {row.original.detail}
          </span>
        </div>
      ),
    },
    {
      id: "actor",
      header: t("Actor", "الفاعل"),
      size: 140,
      cell: ({ row }) => (
        <span className="actor-label">
          {row.original.actor}
          <small className="cell-secondary">
            {row.original.actorRole ?? (backend ? "system" : "simulation")}
          </small>
        </span>
      ),
    },
    {
      id: "source",
      header: t("Source", "المصدر"),
      size: 95,
      cell: ({ row }) => (
        <span className="micro-tag">
          {LAB_BUILD && row.original.simulated
            ? t("SIMULATED", "محاكاة")
            : t("BACKEND", "الخادم")}
        </span>
      ),
    },
  ];
  const cities = catalog.cities.map((city) => ({
    value: city,
    label: city,
  }));
  const active = Object.entries(filters).filter(
    ([key, value]) =>
      !["timeRange", "timeBasis", "sort", "from", "to"].includes(key) &&
      value !== "all" &&
      value !== "",
  );
  return (
    <>
      <PageTitle
        title={t("Audit", "سجل التدقيق")}
        description={t(
          "A clear record of evidence, decisions, and verified outcomes.",
          "سجل واضح للأدلة والقرارات والنتائج المتحققة.",
        )}
      >
        <span className="date-pill">
          <ShieldCheck size={13} />
          {backend
            ? t(
                "Backend audit ledger · synthetic data",
                "سجل تدقيق الخادم · بيانات اصطناعية",
              )
            : t("Traceable · simulated", "قابل للتتبع · محاكاة")}
        </span>
      </PageTitle>
      <div className="audit-view-row">
        <Tabs value={mode} onValueChange={(v) => update({}, v as AuditMode)}>
          <TabsList>
            <TabsTrigger value="events">
              <ScrollText size={14} />
              {t("All events", "كل الأحداث")}
            </TabsTrigger>
            <TabsTrigger value="by_shipment">
              <Package size={14} />
              {t("By shipment", "حسب الشحنة")}
            </TabsTrigger>
          </TabsList>
        </Tabs>
        <div className="audit-summary">
          <span>
            <b data-testid="audit-event-count">{result.total}</b>{" "}
            {t("events", "أحداث")}
          </span>
          <span>
            <b>{result.uniqueShipments}</b>{" "}
            {t("unique shipments", "شحنات فريدة")}
          </span>
          <span>
            <b>{result.uniqueCases}</b> {t("cases", "حالات")}
          </span>
        </div>
      </div>
      <section className="surface audit-surface">
        <div className="table-toolbar audit-filter-bar">
          <div className="search-field">
            <Search size={14} />
            <Input
              aria-label="Search audit events"
              placeholder={t(
                "Search events, shipments, actors…",
                "البحث في الأحداث والشحنات والمشغلين…",
              )}
              value={filters.search}
              onChange={(e) => update({ search: e.target.value })}
            />
          </div>
          <SelectControl
            label="Audit event type"
            value={filters.kind}
            onChange={(kind) => update({ kind })}
            options={[
              { value: "all", label: t("All event types", "كل أنواع الأحداث") },
              ...kinds.map((k) => ({
                value: k,
                label: t(labels[k], arabic[k]),
              })),
            ]}
          />
          <SelectControl
            label="Audit shipment"
            value={filters.shipmentId}
            onChange={(shipmentId) => {
              update({ shipmentId });
              setTimelineId(shipmentId);
            }}
            options={[
              { value: "all", label: t("All shipments", "كل الشحنات") },
              ...cases.map((c) => ({ value: c.id, label: displayId(c) })),
            ]}
          />
          <SelectControl
            label="Audit date range"
            value={filters.timeRange}
            onChange={(v) => {
              if (v === "custom") setDateOpen(true);
              else update({ timeRange: v as TimeRange });
            }}
            options={[
              { value: "today", label: t("Today", "اليوم") },
              { value: "week", label: t("This week", "هذا الأسبوع") },
              { value: "month", label: t("This month", "هذا الشهر") },
              { value: "all", label: t("All time", "كل الأوقات") },
              { value: "custom", label: t("Custom range", "فترة مخصصة") },
            ]}
          />
          <Popover open={dateOpen} onOpenChange={setDateOpen}>
            <PopoverTrigger asChild>
              <Button
                variant="outline"
                size="icon-sm"
                aria-label="Choose custom audit dates"
              >
                <CalendarDays size={14} />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="date-range-popover" align="end">
              <h3>{t("Custom date range", "فترة زمنية مخصصة")}</h3>
              <Calendar
                mode="range"
                selected={range}
                onSelect={setRange}
                defaultMonth={new Date(`${today.slice(0, 7)}-01T12:00:00`)}
                numberOfMonths={1}
              />
              <p>
                {range?.from
                  ? format(range.from, "dd MMM yyyy")
                  : t("Start date", "تاريخ البداية")}{" "}
                →{" "}
                {range?.to
                  ? format(range.to, "dd MMM yyyy")
                  : t("End date", "تاريخ النهاية")}
              </p>
              <Button
                className="w-full"
                size="sm"
                disabled={!range?.from || !range?.to}
                onClick={() => {
                  if (range?.from && range?.to) {
                    update({
                      timeRange: "custom",
                      from: format(range.from, "yyyy-MM-dd"),
                      to: format(range.to, "yyyy-MM-dd"),
                    });
                    setDateOpen(false);
                  }
                }}
              >
                {t("Apply dates", "تطبيق الفترة")}
              </Button>
            </PopoverContent>
          </Popover>
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outline" size="sm">
                <SlidersHorizontal size={13} />
                {t("More filters", "تصفية إضافية")}
              </Button>
            </PopoverTrigger>
            <PopoverContent
              className="filter-popover audit-more-filters"
              align="end"
            >
              <h3>{t("Refine audit history", "تصفية سجل التدقيق")}</h3>
              <label>
                {t("Origin", "المصدر")}
                <SelectControl
                  label="Audit origin"
                  value={filters.origin}
                  onChange={(origin) => update({ origin })}
                  options={[
                    { value: "all", label: t("All origins", "كل المصادر") },
                    ...cities,
                  ]}
                />
              </label>
              <label>
                {t("Destination", "الوجهة")}
                <SelectControl
                  label="Audit destination"
                  value={filters.destination}
                  onChange={(destination) => update({ destination })}
                  options={[
                    {
                      value: "all",
                      label: t("All destinations", "كل الوجهات"),
                    },
                    ...cities,
                  ]}
                />
              </label>
              <label>
                {t("Workflow status", "حالة سير العمل")}
                <SelectControl
                  label="Audit workflow"
                  value={filters.workflow}
                  onChange={(workflow) => update({ workflow })}
                  options={[
                    { value: "all", label: t("All workflows", "كل الحالات") },
                    ...supportedStatuses.map((value) => ({
                      value,
                      label: statusLabels[value],
                    })),
                  ]}
                />
              </label>
              <label>
                {t("Actor role", "دور الفاعل")}
                <SelectControl
                  label="Audit actor"
                  value={filters.actor}
                  onChange={(actor) => update({ actor })}
                  options={[
                    { value: "all", label: t("All actors", "كل المشغلين") },
                    { value: "investigator", label: "Investigator" },
                    { value: "reviewer", label: "Reviewer" },
                    { value: "operator", label: t("Operator", "المشغل") },
                    { value: "verifier", label: "Verifier" },
                    ...(backend
                      ? [
                          {
                            value: "policy",
                            label: t("Authority policy", "سياسة الصلاحيات"),
                          },
                          { value: "system", label: t("System", "النظام") },
                        ]
                      : []),
                  ]}
                />
              </label>
              <label>
                {t("Time basis", "أساس الوقت")}
                <SelectControl
                  label="Audit time basis"
                  value={filters.timeBasis}
                  onChange={(v) =>
                    update({ timeBasis: v as AuditFilters["timeBasis"] })
                  }
                  options={[
                    {
                      value: "recorded",
                      label: t("Recorded time", "وقت التسجيل"),
                    },
                    {
                      value: "evidence",
                      label: t("Evidence time", "وقت الدليل"),
                    },
                  ]}
                />
              </label>
            </PopoverContent>
          </Popover>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Refresh audit"
            onClick={() => {
              if (service.loadAudit) {
                // Backend: read new ledger records now and report the real count.
                void service.loadAudit().then(() => {
                  const state = service.getSnapshot();
                  toast.info(
                    t(
                      `Audit ledger read · ${state.events.length} events loaded`,
                      `تمت قراءة سجل التدقيق · ${state.events.length} أحداث محمّلة`,
                    ),
                  );
                });
                return;
              }
              toast.info(
                t(
                  `Up to date · ${events.length} local events`,
                  `محدث · ${events.length} أحداث محلية`,
                ),
              );
            }}
          >
            <RefreshCw size={14} />
          </Button>
          {active.length > 0 && (
            <Button variant="ghost" size="sm" onClick={() => update(base)}>
              {t("Clear", "مسح")}
            </Button>
          )}
        </div>
        <div className="audit-results-meta">
          <span>
            <span className="live-dot" />
            {t(
              filters.sort === "oldest"
                ? "Chronological · oldest first"
                : "Newest first",
              "سجل مرتب زمنياً",
            )}
            <i>·</i>
            {t(
              filters.timeBasis === "recorded"
                ? "Recorded time"
                : "Evidence time; recorded time when unavailable",
              "وقت السعودية",
            )}
          </span>
          <span>
            {backend && connection?.audit?.loading
              ? `${t("Reading the ledger…", "جارٍ قراءة السجل…")} · `
              : backend && connection?.audit?.truncated
                ? `${t(
                    `Showing the first ${connection.audit.loaded} of ${connection.audit.total} recorded events`,
                    `عرض أول ${connection.audit.loaded} من ${connection.audit.total} حدثاً مسجلاً`,
                  )} · `
                : ""}
            {filters.timeRange === "custom"
              ? `${filters.from} → ${filters.to}`
              : backend
                ? {
                    today: shortDate(today),
                    week: `${shortDate(rangeStarts(today).week)} → ${shortDate(today)}`,
                    month: `${shortDate(rangeStarts(today).month)} → ${shortDate(today)}`,
                    all: t("All recorded dates", "كل الأوقات"),
                    custom: "",
                  }[filters.timeRange]
                : t(
                    {
                      today: "09 Oct 2026",
                      week: "05–09 Oct 2026",
                      month: "01–09 Oct 2026",
                      all: "All recorded dates",
                      custom: "",
                    }[filters.timeRange],
                    {
                      today: "09 أكتوبر 2026",
                      week: "05–09 أكتوبر 2026",
                      month: "01–09 أكتوبر 2026",
                      all: "كل الأوقات",
                      custom: "",
                    }[filters.timeRange],
                  )}
          </span>
        </div>
        {active.length > 0 && (
          <div className="active-filter-chips audit-filter-chips">
            {active.map(([key, value]) => (
              <Badge variant="secondary" key={key}>
                {key === "shipmentId" ? "shipment" : key}: {value}
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Clear audit ${key} filter`}
                  onClick={() =>
                    update({
                      [key]: base[key as keyof AuditFilters],
                    })
                  }
                >
                  <X size={10} />
                </Button>
              </Badge>
            ))}
          </div>
        )}
        {mode === "events" ? (
          <DataTable
            columns={columns}
            data={pageEvents}
            rowId={(e) => e.id}
            onRowClick={setSelected}
            pagination={safePagination}
            onPaginationChange={setPagination}
            total={result.total}
            manualPagination
            emptyTitle={t("No matching events", "لا توجد أحداث مطابقة")}
            emptyDescription={t(
              "Try a broader date range, or clear a filter.",
              "جرّب فترة أوسع أو امسح تصفية.",
            )}
          />
        ) : (
          <div className="audit-shipment-workspace">
            <aside className="audit-shipment-list">
              <div className="timeline-list-title">
                {matchingCases.length} {t("shipment histories", "سجلات شحنات")}
              </div>
              <ScrollArea className="audit-shipments-scroll">
                {matchingCases.map((c) => (
                  <Button
                    key={c.id}
                    variant="ghost"
                    className={`audit-shipment-item ${c.id === timelineCase?.id ? "selected" : ""}`}
                    onClick={() => setTimelineId(c.id)}
                    data-testid={`audit-shipment-${c.id}`}
                  >
                    <b dir="ltr">
                      {displayId(c)}
                      <ChevronRight size={12} />
                    </b>
                    <p>
                      {c.shipment.origin} → {c.shipment.destination}
                    </p>
                    <div>
                      <StatusBadge status={c.status} c={c} />
                      <small>
                        {result.items.filter((e) => e.caseId === c.id).length}{" "}
                        {t("events", "أحداث")}
                      </small>
                    </div>
                  </Button>
                ))}
              </ScrollArea>
            </aside>
            <section className="shipment-timeline">
              {timelineCase ? (
                <>
                  <div className="timeline-header">
                    <div>
                      <h2 dir="ltr">{displayId(timelineCase)}</h2>
                      <p>
                        {timelineCase.issue} · {timelineCase.shipment.origin} →{" "}
                        {timelineCase.shipment.destination}
                      </p>
                    </div>
                    <Button asChild variant="outline" size="sm">
                      <Link to={`/cases/${timelineCase.id}`}>
                        {t("Open case", "فتح الحالة")}
                        <ArrowRight size={12} />
                      </Link>
                    </Button>
                  </div>
                  <ScrollArea className="timeline-scroll">
                    <div className="timeline-events">
                      {timelineEvents.map((e, i) => (
                        <div className="timeline-event" key={e.id}>
                          {(i === 0 ||
                            dateLabel(e.timestamp) !==
                              dateLabel(timelineEvents[i - 1].timestamp)) && (
                            <h3 className="timeline-day">
                              {dateLabel(e.timestamp)}
                            </h3>
                          )}
                          <div className="timeline-entry">
                            <span className={`timeline-dot kind-${e.kind}`} />
                            <span className="timeline-time">
                              {timeLabel(e.timestamp)}
                              <small>AST</small>
                            </span>
                            <div>
                              <Badge
                                variant="secondary"
                                className={`event-type event-type-${e.kind}`}
                              >
                                {kindLabel(e.kind)}
                              </Badge>
                              <Button
                                variant="link"
                                className="timeline-event-title"
                                onClick={() => setSelected(e)}
                              >
                                {e.title}
                              </Button>
                              <p>{e.detail}</p>
                              <small>
                                {e.actor} ·{" "}
                                {LAB_BUILD && e.simulated
                                  ? t("simulated", "محاكاة")
                                  : t(
                                      "recorded by the backend",
                                      "سجّله الخادم",
                                    )}
                              </small>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </ScrollArea>
                </>
              ) : (
                <EmptyState
                  title={t("No matching histories", "لا توجد سجلات مطابقة")}
                  description={t(
                    "Adjust the date range or filters to find a shipment.",
                    "عدل الفترة أو التصفية للعثور على شحنة.",
                  )}
                />
              )}
            </section>
          </div>
        )}
      </section>
      <div className="audit-footnote">
        <ShieldCheck size={12} />
        {backend
          ? t(
              "Counts reflect the loaded, filtered ledger records for cases in the queue. Recorded time is when the backend wrote the event; evidence time is the dataset clock. Times use Asia/Riyadh.",
              "الأعداد من سجلات التدقيق المحمّلة والمُصفاة للحالات في القائمة. وقت التسجيل هو وقت كتابة الخادم للحدث، ووقت الدليل هو ساعة البيانات. الأوقات بتوقيت الرياض.",
            )
          : t(
              "Counts reflect the filtered records. Each synthetic shipment has one case. Times use Asia/Riyadh.",
              "الأعداد من السجلات المُصفاة. لكل شحنة محاكاة حالة واحدة. الأوقات بتوقيت الرياض.",
            )}
      </div>
      <Sheet
        open={!!selected}
        onOpenChange={(v) => {
          if (!v) setSelected(null);
        }}
      >
        <SheetContent
          className="audit-detail-sheet"
          side={preferences.language === "ar" ? "left" : "right"}
        >
          <SheetHeader>
            <SheetTitle>{selected?.title}</SheetTitle>
            <SheetDescription>
              {selected ? label(selected.caseId) : ""} ·{" "}
              {LAB_BUILD && selected?.simulated !== false
                ? t("Simulated audit event", "حدث تدقيق محاكى")
                : t("Backend audit event", "حدث تدقيق من الخادم")}
            </SheetDescription>
          </SheetHeader>
          {selected && (
            <ScrollArea className="flex-1">
              <div className="sheet-body">
                <Badge
                  variant="secondary"
                  className={`event-type event-type-${selected.kind}`}
                >
                  {kindLabel(selected.kind)}
                </Badge>
                <p className="audit-event-detail mt-5">{selected.detail}</p>
                <dl className="audit-event-metadata">
                  <dt>{t("Recorded time", "وقت التسجيل")}</dt>
                  <dd>{dateTimeLabel(selected.timestamp)}</dd>
                  <dt>{t("Evidence time", "وقت الدليل")}</dt>
                  <dd>
                    {selected.evidenceTimestamp
                      ? dateTimeLabel(selected.evidenceTimestamp)
                      : t("Not supplied by this event", "غير متوفر لهذا الحدث")}
                  </dd>
                  <dt>{t("Actor / role", "الفاعل / الدور")}</dt>
                  <dd>
                    {selected.actor} ·{" "}
                    {selected.actorRole ?? (backend ? "system" : "simulation")}
                  </dd>
                  <dt>{t("Shipment / case", "الشحنة / الحالة")}</dt>
                  <dd>
                    <CaseLink
                      id={selected.caseId}
                      label={label(selected.caseId)}
                    />
                  </dd>
                  <dt>{t("Event ID", "معرف الحدث")}</dt>
                  <dd>
                    <code>{selected.id}</code>
                  </dd>
                  <dt>{t("Run ID", "معرف التحقيق")}</dt>
                  <dd>
                    <code>{selected.runId ?? "—"}</code>
                  </dd>
                  <dt>{t("Stage", "المرحلة")}</dt>
                  <dd>
                    {selected.stage === undefined
                      ? "—"
                      : stages[selected.stage]?.label}
                  </dd>
                  <dt>{t("Evidence references", "مراجع الأدلة")}</dt>
                  <dd>{selected.evidenceIds?.join(", ") ?? "—"}</dd>
                  <dt>{t("Source", "المصدر")}</dt>
                  <dd>
                    {LAB_BUILD && selected.simulated
                      ? t(
                          "Local synthetic fixture / mock service",
                          "محاكاة محلية",
                        )
                      : t(
                          `Suhail backend audit ledger · ${selected.eventType ?? "event"} · synthetic dataset`,
                          `سجل تدقيق خادم سهيل · ${selected.eventType ?? "حدث"} · بيانات اصطناعية`,
                        )}
                  </dd>
                </dl>
                <Button asChild variant="outline" className="w-full">
                  <Link
                    to={`/cases/${selected.caseId}`}
                    onClick={() => setSelected(null)}
                  >
                    {t("Open investigation workspace", "فتح مساحة التحقيق")}
                    <ArrowRight size={13} />
                  </Link>
                </Button>
              </div>
            </ScrollArea>
          )}
        </SheetContent>
      </Sheet>
      <PageAssistant
        context={{
          page: "audit",
          filters,
          view: mode,
          selectedCaseId: timelineCase?.id,
        }}
        onApply={apply}
        onUndo={() => {
          if (previous.current) {
            setParams(previous.current.params, { replace: true });
            setTimelineId(previous.current.timelineId);
            setPagination((p) => ({ ...p, pageIndex: 0 }));
            toast.info(
              t("Previous filters restored", "استعادة التصفية السابقة"),
            );
          }
        }}
      />
    </>
  );
}
