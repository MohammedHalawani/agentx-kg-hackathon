import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowRight,
  ArrowUpRight,
  Map,
  Network,
  Search,
  SlidersHorizontal,
  X,
  PanelRightClose,
  PanelRightOpen,
  Package,
  GitBranch,
  MapPin,
  ShieldCheck,
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
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible";
import {
  ResizablePanelGroup,
  ResizablePanel,
  ResizableHandle,
} from "@/components/ui/resizable";
import { ScrollArea } from "@/components/ui/scroll-area";
import { SelectControl } from "@/components/select-control";
import {
  PageTitle,
  StatusBadge,
  PriorityLabel,
  EmptyState,
} from "@/components/shared";
import { NetworkMap } from "@/components/network-map";
import { KnowledgeGraph } from "@/components/knowledge-graph";
import { PageAssistant } from "@/components/page-assistant";
import { useOperations } from "@/state/operations";
import { usePreferences } from "@/state/preferences";
import { useMediaQuery } from "@/hooks/use-media-query";
import { filterShipments } from "@/services/page-queries";
import {
  emptyShipmentFilters,
  type PageAction,
  type ShipmentFilters,
} from "@/domain/page-actions";
import { displayId } from "@/domain/case-view";
import { useCanopusScreen } from "@/state/canopus";
const LAB_BUILD = import.meta.env.VITE_SUHAIL_DATA === "lab";

type ExploreView = "map" | "graph" | "schema";
export function ExplorePage() {
  const { cases, catalog, service, backend: fromBackend } = useOperations();
  // Connected build: always the backend, so lab-only branches are removed at build time.
  const backend = !LAB_BUILD || fromBackend;
  const { t, preferences } = usePreferences();
  const [params, setParams] = useSearchParams();
  const filters = {
    ...emptyShipmentFilters,
    ...Object.fromEntries(
      Object.keys(emptyShipmentFilters).map((key) => [
        key,
        params.get(key) ?? emptyShipmentFilters[key as keyof ShipmentFilters],
      ]),
    ),
  };
  const view = (
    ["map", "graph", "schema"].includes(params.get("view") ?? "")
      ? params.get("view")
      : "map"
  ) as ExploreView;
  const [selectedId, setSelectedId] = useState(
    params.get("shipment") ?? (backend ? "" : "SHP-10482"),
  );
  const [selectedEvidence, setSelectedEvidence] = useState<string | null>(null);
  const [entityFilter, setEntityFilter] = useState("all");
  const [resultsOpen, setResultsOpen] = useState(true);
  const [focus, setFocus] = useState<{ city: string; revision: number } | null>(
    null,
  );
  const small = useMediaQuery("(max-width:979px)");
  const previous = useRef<{
    params: string;
    selectedId: string;
    evidence: string | null;
    focus: typeof focus;
  } | null>(null);
  const resultsRef = useRef<HTMLDivElement>(null);
  const filterKey = JSON.stringify(filters);
  const matching = useMemo(
    () => filterShipments(cases, JSON.parse(filterKey)),
    [cases, filterKey],
  );
  const c = matching.find((c) => c.id === selectedId) ?? matching[0];
  // Backend: the selected shipment's evidence and graph are loaded when it is selected.
  const watchedId = c?.backend ? c.id : null;
  useEffect(
    () => (watchedId ? service.watchCase?.(watchedId) : undefined),
    [watchedId, service],
  );
  useCanopusScreen({
    screen: "explore",
    caseId: c?.id,
    selectedEvidenceId: selectedEvidence,
    filters: { ...filters, view },
  });
  useEffect(() => {
    const viewport = resultsRef.current?.querySelector(
      "[data-slot=scroll-area-viewport]",
    );
    const row = resultsRef.current?.querySelector(
      `[data-testid="shipment-result-${c?.id}"]`,
    );
    if (viewport && row) {
      const delta =
        row.getBoundingClientRect().top - viewport.getBoundingClientRect().top;
      if (
        delta < 0 ||
        delta + row.getBoundingClientRect().height > viewport.clientHeight
      )
        viewport.scrollBy({
          top: delta - 10,
          behavior: preferences.motion === "reduce" ? "instant" : "smooth",
        });
    }
  }, [c?.id, resultsOpen, preferences.motion]);
  function update(
    patch: Partial<ShipmentFilters>,
    newView = view,
    shipment = selectedId,
  ) {
    const next = { ...filters, ...patch };
    const query = new URLSearchParams();
    Object.entries(next).forEach(([key, value]) => {
      if (value !== emptyShipmentFilters[key as keyof ShipmentFilters])
        query.set(key, value);
    });
    if (newView !== "map") query.set("view", newView);
    if (shipment) query.set("shipment", shipment);
    setParams(query, { replace: true });
    setFocus(null);
  }
  function select(id: string) {
    setSelectedId(id);
    setSelectedEvidence(null);
    update({}, view, id);
  }
  function apply(actions: PageAction[]) {
    previous.current = {
      params: params.toString(),
      selectedId,
      evidence: selectedEvidence,
      focus,
    };
    let nextFilters = { ...filters },
      nextView = view,
      id = c?.id ?? selectedId,
      evidence = selectedEvidence;
    let nextFocus: typeof focus = null;
    for (const action of actions) {
      if (action.type === "filter_shipments")
        nextFilters = { ...nextFilters, ...action.filters };
      if (action.type === "select_shipment") {
        id = action.caseId;
        nextFilters.search = action.caseId;
      }
      if (
        action.type === "change_view" &&
        ["map", "graph", "schema"].includes(action.view)
      )
        nextView = action.view as ExploreView;
      if (action.type === "focus_map") {
        nextFocus = { city: action.city, revision: Date.now() };
        nextView = "map";
      }
      if (action.type === "highlight_graph_evidence") {
        evidence = action.evidenceId;
        nextView = "graph";
      }
    }
    const result = filterShipments(cases, nextFilters);
    id = result.find((c) => c.id === id)?.id ?? result[0]?.id ?? id;
    update(nextFilters, nextView, id);
    setSelectedId(id);
    setSelectedEvidence(evidence);
    setFocus(nextFocus);
    setResultsOpen(true);
    toast.info(
      t(
        `Explore updated · ${result.length} matching shipments`,
        `تم التحديث · ${result.length} شحنات مطابقة`,
      ),
    );
    return t(
      `${result.length} matching synthetic shipment${result.length === 1 ? "" : "s"}. ${nextFilters.origin !== "all" ? `Origin: ${nextFilters.origin}. ` : ""}${nextFilters.destination !== "all" ? `Destination: ${nextFilters.destination}. ` : ""}The visible ${nextView} and results use these filters.${result.length === 0 ? " No matching records; try clearing a filter." : ""}`,
      `${result.length} شحنات محاكاة مطابقة. ${nextFilters.origin !== "all" ? `المصدر: ${nextFilters.origin}. ` : ""}${nextFilters.destination !== "all" ? `الوجهة: ${nextFilters.destination}. ` : ""}تم تحديث العرض والنتائج وفق التصفية.${result.length === 0 ? " لا توجد سجلات مطابقة؛ جرّب إزالة أحد المرشحات." : ""}`,
    );
  }
  const activeFilters = Object.entries(filters).filter(
    ([, value]) => value !== "all" && value !== "",
  );
  const cities = catalog.cities.map((city) => ({
    value: city,
    label: city,
  }));
  const entity = c?.nodes.find(
    (n) => n.id === selectedEvidence || n.evidenceId === selectedEvidence,
  );
  const evidence = c?.evidence.find((e) => e.id === selectedEvidence);
  const relationship = c?.relationships.find((e) => e.id === selectedEvidence);
  const canvas =
    view === "map" ? (
      <NetworkMap
        cases={matching}
        selected={c}
        onSelect={select}
        focus={focus}
      />
    ) : view === "graph" ? (
      c ? (
        <KnowledgeGraph
          c={c}
          selected={selectedEvidence}
          onSelect={setSelectedEvidence}
          onRelation={setSelectedEvidence}
          stage={-1}
          filter={entityFilter}
        />
      ) : (
        <EmptyState
          title={t("No matching shipments", "لا توجد شحنات مطابقة")}
          description={t(
            "Clear a filter to explore the network.",
            "امسح تصفية لاستكشاف الشبكة.",
          )}
        />
      )
    ) : backend ? (
      <BackendSchemaView />
    ) : (
      <SchemaView />
    );
  return (
    <>
      <PageTitle
        title={t("Explore", "استكشاف")}
        description={t(
          "See the network. Follow a shipment. Connect the evidence.",
          "شاهد الشبكة. تتبع الشحنة. اربط الأدلة.",
        )}
      >
        <span className="date-pill">
          <span className="live-dot" />
          {t("Synthetic logistics network", "شبكة لوجستية محاكاة")}
        </span>
      </PageTitle>
      <div className="explore-controls">
        <Tabs value={view} onValueChange={(v) => update({}, v as ExploreView)}>
          <TabsList>
            <TabsTrigger value="map">
              <Map size={14} />
              {t("Map", "الخريطة")}
            </TabsTrigger>
            <TabsTrigger value="graph">
              <Network size={14} />
              {t("Graph", "الرسم")}
            </TabsTrigger>
            <TabsTrigger value="schema">
              <GitBranch size={14} />
              {t("Schema", "البنية")}
            </TabsTrigger>
          </TabsList>
        </Tabs>
        <div className="explore-count">
          <b data-testid="explore-count">{matching.length}</b>{" "}
          {backend ? t("cases", "حالات") : t("shipments", "شحنات")}
          <span>·</span>
          {t("selected filters", "التصفية المحددة")}
        </div>
      </div>
      <div className="table-toolbar explore-filter-bar surface">
        <div className="search-field">
          <Search size={14} />
          <Input
            aria-label="Search Explore shipments"
            placeholder={t(
              "Search shipment or exception…",
              "البحث عن شحنة أو استثناء…",
            )}
            value={filters.search}
            onChange={(e) => update({ search: e.target.value })}
          />
        </div>
        <SelectControl
          label="Explore origin"
          value={filters.origin}
          onChange={(origin) => update({ origin })}
          options={[
            { value: "all", label: t("All origins", "كل المصادر") },
            ...cities,
          ]}
        />
        <SelectControl
          label="Explore destination"
          value={filters.destination}
          onChange={(destination) => update({ destination })}
          options={[
            { value: "all", label: t("All destinations", "كل الوجهات") },
            ...cities,
          ]}
        />
        <SelectControl
          label="Explore status"
          value={filters.status}
          onChange={(status) => update({ status })}
          options={[
            { value: "all", label: t("All statuses", "كل الحالات") },
            {
              value: "attention",
              label: t("Needs attention", "تحتاج انتباهاً"),
            },
            {
              value: "human_review",
              label: t("Awaiting approval", "بانتظار الموافقة"),
            },
            { value: "resolved", label: t("Resolved", "تم الحل") },
          ]}
        />
        <Popover>
          <PopoverTrigger asChild>
            <Button variant="outline" size="sm">
              <SlidersHorizontal size={13} />
              {t("More filters", "تصفية إضافية")}
            </Button>
          </PopoverTrigger>
          <PopoverContent className="filter-popover">
            <h3>{t("Refine the network", "تصفية الشبكة")}</h3>
            <label>
              {t("Exception", "الاستثناء")}
              <SelectControl
                label="Explore exception"
                value={filters.cause}
                onChange={(cause) => update({ cause })}
                options={[
                  {
                    value: "all",
                    label: t("All exceptions", "كل الاستثناءات"),
                  },
                  ...catalog.causes,
                ]}
              />
            </label>
            <label>
              {t("Priority", "الأولوية")}
              <SelectControl
                label="Explore priority"
                value={filters.priority}
                onChange={(priority) => update({ priority })}
                options={[
                  { value: "all", label: t("All priorities", "كل الأولويات") },
                  ...["high", "medium", "low"].map((value) => ({
                    value,
                    label: value[0].toUpperCase() + value.slice(1),
                  })),
                ]}
              />
            </label>
          </PopoverContent>
        </Popover>
        {activeFilters.length > 0 && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => update(emptyShipmentFilters)}
          >
            <X size={13} />
            {t("Clear", "مسح")}
          </Button>
        )}
        {view === "graph" && (
          <SelectControl
            label="Graph entity filter"
            value={entityFilter}
            onChange={setEntityFilter}
            options={[
              { value: "all", label: t("All entities", "كل العقد") },
              ...["observation", "facility", "vehicle", "package"].map(
                (value) => ({
                  value,
                  label: value[0].toUpperCase() + value.slice(1),
                }),
              ),
            ]}
          />
        )}
      </div>
      {activeFilters.length > 0 && (
        <div className="active-filter-chips">
          {activeFilters.map(([key, value]) => (
            <Badge variant="secondary" key={key}>
              {key}: {value}
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={`Clear ${key} filter`}
                onClick={() =>
                  update({
                    [key]: emptyShipmentFilters[key as keyof ShipmentFilters],
                  })
                }
              >
                <X size={10} />
              </Button>
            </Badge>
          ))}
        </div>
      )}
      <div
        className={`explore-workspace ${resultsOpen ? "" : "results-collapsed"}`}
      >
        <ResizablePanelGroup
          orientation={small ? "vertical" : "horizontal"}
          className="network-split"
          key={`${resultsOpen}-${small}`}
          defaultLayout={{
            canvas: resultsOpen ? 72 : 96,
            results: resultsOpen ? 28 : 4,
          }}
          dir="ltr"
        >
          <ResizablePanel
            id="canvas"
            minSize={small ? "40%" : "50%"}
            defaultSize={resultsOpen ? "72%" : "96%"}
          >
            <div className="explore-canvas">{canvas}</div>
          </ResizablePanel>
          {resultsOpen && (
            <ResizableHandle
              className="split-handle"
              withHandle
              aria-label="Resize map and shipment results"
            />
          )}
          <ResizablePanel
            id="results"
            defaultSize={resultsOpen ? "28%" : "42px"}
            minSize={resultsOpen ? "24%" : "42px"}
            maxSize={resultsOpen ? "45%" : "42px"}
          >
            <Collapsible
              open={resultsOpen}
              className="explore-results"
              dir={preferences.language === "ar" ? "rtl" : "ltr"}
            >
              <div className="results-header">
                {resultsOpen ? (
                  <>
                    <h2>
                      <Package size={14} />
                      {backend ? t("Cases", "الحالات") : t("Shipments", "الشحنات")}
                      <span className="subtle-count">{matching.length}</span>
                    </h2>
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      aria-label="Collapse shipment results"
                      onClick={() => setResultsOpen(false)}
                    >
                      <PanelRightClose size={15} />
                    </Button>
                  </>
                ) : (
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Expand shipment results"
                    onClick={() => setResultsOpen(true)}
                  >
                    <PanelRightOpen size={16} />
                  </Button>
                )}
              </div>
              <CollapsibleContent className="results-content">
                <ScrollArea
                  ref={resultsRef}
                  className="shipment-results-scroll"
                >
                  <div className="shipment-results-list">
                    {matching.length === 0 && (
                      <EmptyState
                        title={t(
                          "No matching shipments",
                          "لا توجد شحنات مطابقة",
                        )}
                        description={t(
                          "Try a broader filter.",
                          "جرّب تصفية أوسع.",
                        )}
                      />
                    )}{" "}
                    {matching.map((item) => (
                      <Button
                        key={item.id}
                        variant="ghost"
                        className={`shipment-result ${item.id === c?.id ? "selected" : ""}`}
                        onClick={() => select(item.id)}
                        aria-pressed={item.id === c?.id}
                        data-testid={`shipment-result-${item.id}`}
                      >
                        <div className="result-heading">
                          <b dir="ltr">{displayId(item)}</b>
                          <PriorityLabel priority={item.priority} />
                        </div>
                        <p>{item.issue}</p>
                        <span className="result-route">
                          {item.shipment.origin}
                          <ArrowRight size={10} />
                          {item.shipment.destination}
                        </span>
                        <StatusBadge status={item.status} c={item} />
                      </Button>
                    ))}
                  </div>
                </ScrollArea>
                {c && (
                  <div className="selected-result-footer">
                    <small>{t("SELECTED SHIPMENT", "الشحنة المحددة")}</small>
                    <b dir="ltr">{displayId(c)}</b>
                    <div>
                      <Button asChild variant="outline" size="sm">
                        <Link to={`/cases/${c.id}`}>
                          {t("Investigate", "التحقيق")}
                          <ArrowUpRight size={12} />
                        </Link>
                      </Button>
                      <Button asChild variant="ghost" size="sm">
                        <Link
                          to={`/audit?case=${c.id}&mode=by_shipment&timeRange=all`}
                        >
                          {t("Audit trail", "سجل التدقيق")}
                          <ArrowRight size={12} />
                        </Link>
                      </Button>
                    </div>
                  </div>
                )}
              </CollapsibleContent>
            </Collapsible>
          </ResizablePanel>
        </ResizablePanelGroup>
      </div>
      <div className="explore-context-bar" data-testid="explore-context">
        <MapPin size={15} />
        <div>
          <b>
            {evidence?.label ??
              entity?.label ??
              relationship?.label ??
              (c ? displayId(c) : undefined) ??
              t("Network overview", "نظرة عامة على الشبكة")}
          </b>
          <p>
            {evidence?.detail ??
              entity?.detail ??
              relationship?.detail ??
              (c
                ? `${c.shipment.origin} → ${c.shipment.destination} · ${c.summary}`
                : t(
                    "No matching data. Adjust the filters to continue.",
                    "لا توجد بيانات مطابقة. عدّل التصفية للمتابعة.",
                  ))}
          </p>
        </div>
        <span>
          <ShieldCheck size={12} />
          {backend
            ? t("Backend evidence · synthetic dataset", "أدلة الخادم · بيانات اصطناعية")
            : t("Simulated evidence", "أدلة محاكاة")}
        </span>
      </div>
      <PageAssistant
        context={{ page: "explore", filters, view, selectedCaseId: c?.id }}
        onApply={apply}
        onUndo={() => {
          if (previous.current) {
            setParams(previous.current.params, { replace: true });
            setSelectedId(previous.current.selectedId);
            setSelectedEvidence(previous.current.evidence);
            setFocus(previous.current.focus);
            toast.info(t("Previous view restored", "استعادة العرض السابق"));
          }
        }}
      />
    </>
  );
}

const schema = [
  {
    name: "Shipment",
    icon: Package,
    detail:
      "A synthetic operational case, route, exception, and workflow status.",
    links: "CONTAINS → Package · HAS_RECOMMENDATION → Recommendation",
  },
  {
    name: "Package",
    icon: Package,
    detail:
      "The physical parcel identity. Its custody is supported by parcel scans, never by vehicle GPS alone.",
    links: "OBSERVED_IN → Observation · CARRIED_BY → Vehicle",
  },
  {
    name: "Observation",
    icon: ShieldCheck,
    detail:
      "A time-stamped scan, handover, or delivery observation with explicit confidence.",
    links: "AT → Facility · SUPPORTS → Outcome",
  },
  {
    name: "Vehicle",
    icon: MapPin,
    detail:
      "Transport telemetry and linked driver or contractor. Movement proves only vehicle location.",
    links: "OPERATED_BY → Driver · CONTRACTED_TO → Contractor",
  },
  {
    name: "Facility",
    icon: Map,
    detail:
      "A sorting hub, regional warehouse, or delivery depot in the Saudi logistics network.",
    links: "EXPECTED_AT / OBSERVED_AT ← Package",
  },
  {
    name: "Outcome",
    icon: ShieldCheck,
    detail: "The separately verified result of a simulated recovery action.",
    links: "VERIFIES → Recommendation · SUPPORTED_BY → Observation",
  },
];
/** The live label topology of the backend graph (GET /schema): labels and relationship types only. */
function BackendSchemaView() {
  const { t } = usePreferences();
  const { service } = useOperations();
  const [schema, setSchema] = useState<Awaited<
    ReturnType<NonNullable<typeof service.schema>>
  > | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    service
      .schema?.()
      .then((result) => {
        if (!cancelled) setSchema(result);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [service]);
  const nodes = [...(schema?.nodes ?? [])].sort((a, b) =>
    a.label.localeCompare(b.label),
  );
  const entity = nodes.find((n) => n.id === selected) ?? nodes[0];
  const label = (id: string) => nodes.find((n) => n.id === id)?.label ?? "?";
  const links = (schema?.relationships ?? []).filter(
    (r) => entity && (r.from === entity.id || r.to === entity.id),
  );
  return (
    <section className="schema-view visualization">
      <div className="viz-header">
        <div className="flex gap-2 items-center">
          <GitBranch size={14} />
          <h2>{t("Graph schema", "بنية الرسم")}</h2>
          <span className="subtle-count">{nodes.length}</span>
        </div>
        <Badge variant="secondary">{t("Neo4j labels", "تسميات Neo4j")}</Badge>
      </div>
      <div className="schema-canvas" style={{ overflowY: "auto" }}>
        <p>
          {error ??
            (schema
              ? t(
                  "Select a label to see the relationship types connected to it.",
                  "اختر تسمية لعرض أنواع العلاقات المرتبطة بها.",
                )
              : t("Reading the schema from the backend…", "جارٍ قراءة البنية من الخادم…"))}
        </p>
        <div className="schema-entities">
          {nodes.map((n) => (
            <Button
              variant="outline"
              key={n.id}
              className={`schema-entity ${entity?.id === n.id ? "selected" : ""}`}
              onClick={() => setSelected(n.id)}
            >
              <GitBranch size={25} />
              <b>{n.label}</b>
              <span>
                {t("View connections", "عرض العلاقات")}
                <ArrowRight size={10} />
              </span>
            </Button>
          ))}
        </div>
        {entity && (
          <div className="schema-inspector">
            <b>{entity.label}</b>
            <p>
              {links.length} {t("relationship types", "أنواع علاقات")}
            </p>
            <code>
              {links
                .map((r) =>
                  r.from === entity.id
                    ? `${r.type} → ${label(r.to)}`
                    : `${r.type} ← ${label(r.from)}`,
                )
                .join(" · ") || "—"}
            </code>
          </div>
        )}
      </div>
      <div className="viz-legend">
        <span>
          <i className="dot purple" />
          {t(
            "Live label topology from the backend graph · no shipment properties",
            "بنية التسميات الحية من رسم الخادم · دون خصائص الشحنات",
          )}
        </span>
      </div>
    </section>
  );
}
function SchemaView() {
  const { t } = usePreferences();
  const [selected, setSelected] = useState("Package");
  const entity = schema.find((s) => s.name === selected)!;
  return (
    <section className="schema-view visualization">
      <div className="viz-header">
        <div className="flex gap-2 items-center">
          <GitBranch size={14} />
          <h2>{t("Evidence model", "نموذج الأدلة")}</h2>
        </div>
        <Badge variant="secondary">{t("UI schema", "بنية الواجهة")}</Badge>
      </div>
      <div className="schema-canvas">
        <p>
          {t(
            "Select an entity to inspect its role and connections.",
            "اختر عقدة لفحص دورها وعلاقاتها.",
          )}
        </p>
        <div className="schema-entities">
          {schema.map((s) => (
            <Button
              variant="outline"
              key={s.name}
              className={`schema-entity ${selected === s.name ? "selected" : ""}`}
              onClick={() => setSelected(s.name)}
            >
              <s.icon size={25} />
              <b>{s.name}</b>
              <span>
                {t("View connections", "عرض العلاقات")}
                <ArrowRight size={10} />
              </span>
            </Button>
          ))}
        </div>
        <div className="schema-inspector">
          <b>{entity.name}</b>
          <p>{entity.detail}</p>
          <code>{entity.links}</code>
        </div>
      </div>
      <div className="viz-legend">
        <span>
          <i className="dot purple" />
          {t(
            "Typed local fixtures · no database connection",
            "بيانات محاكاة محددة الأنواع · لا اتصال بقاعدة بيانات",
          )}
        </span>
      </div>
    </section>
  );
}
