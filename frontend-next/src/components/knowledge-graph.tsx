import { useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  Handle,
  Position,
  useNodesState,
  useEdgesState,
  useReactFlow,
  type NodeProps,
  type Node,
  type Edge,
} from "@xyflow/react";
import {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCollide,
  forceRadial,
  type SimulationNodeDatum,
} from "d3-force";
import {
  Box,
  Package,
  Truck,
  UserRound,
  Building2,
  ScanLine,
  Sparkles,
  CheckCheck,
  Network,
  Focus,
  ArrowLeftRight,
  Smartphone,
  Route as RouteIcon,
  Flag,
  FileCheck2,
  MessageSquare,
  MapPin,
  Landmark,
  Maximize2,
  Minimize2,
} from "lucide-react";
import "@xyflow/react/dist/style.css";
import type {
  GraphNode,
  GraphRelationship,
  OperationalCase,
} from "@/domain/types";
import { Button } from "@/components/ui/button";
import { usePreferences } from "@/state/preferences";

/**
 * How a record is drawn. Derived only from the record's own type as the backend serves it
 * (its Neo4j label); lab fixtures without that type fall back to their broader kind.
 */
type Category =
  | "shipment"
  | "package"
  | "facility"
  | "vehicle"
  | "transport"
  | "person"
  | "organisation"
  | "device"
  | "custody"
  | "scan"
  | "status"
  | "attempt"
  | "proof"
  | "message"
  | "position"
  | "recommendation"
  | "outcome";

const SOURCE_CATEGORY: Record<string, Category> = {
  Shipment: "shipment",
  Package: "package",
  Vehicle: "vehicle",
  Trip: "transport",
  Container: "transport",
  RouteRun: "transport",
  Driver: "person",
  Provider: "organisation",
  Organization: "organisation",
  Device: "device",
  CustodyEvent: "custody",
  DepotReconciliation: "custody",
  ScanEvent: "scan",
  StatusEvent: "status",
  DeliveryAttempt: "attempt",
  ContactAttempt: "attempt",
  DeliveryProof: "proof",
  HandoffEvidence: "proof",
  PhotoEvidence: "proof",
  SignatureEvidence: "proof",
  AuthenticationEvidence: "proof",
  RecipientReport: "message",
  CommunicationEvent: "message",
  GPSObservation: "position",
  LocationPin: "position",
  TrafficObservation: "position",
  OpsRecommendation: "recommendation",
  OpsCase: "recommendation",
  OpsRun: "recommendation",
  OpsReview: "recommendation",
  OpsExecution: "recommendation",
  OpsOutcome: "outcome",
};
const KIND_CATEGORY: Record<GraphNode["kind"], Category> = {
  shipment: "shipment",
  package: "package",
  facility: "facility",
  vehicle: "vehicle",
  driver: "person",
  contractor: "organisation",
  observation: "custody",
  recommendation: "recommendation",
  outcome: "outcome",
};
const categoryOf = (node: GraphNode): Category =>
  (node.sourceKind && SOURCE_CATEGORY[node.sourceKind]) ||
  KIND_CATEGORY[node.kind];
const categoryIcons: Record<Category, typeof Box> = {
  shipment: Package,
  package: Box,
  facility: Building2,
  vehicle: Truck,
  transport: RouteIcon,
  person: UserRound,
  organisation: Landmark,
  device: Smartphone,
  custody: ArrowLeftRight,
  scan: ScanLine,
  status: Flag,
  attempt: MapPin,
  proof: FileCheck2,
  message: MessageSquare,
  position: MapPin,
  recommendation: Sparkles,
  outcome: CheckCheck,
};
/** Records of what happened to the parcel, as opposed to the things they refer to. */
const EVENTS = new Set<Category>([
  "custody",
  "scan",
  "status",
  "attempt",
  "proof",
  "message",
  "position",
]);
/** How many nodes the focused view opens with, and how many one expansion adds. */
const FOCUS_LIMIT = 30;
const EXPAND_STEP = 10;

type EvidenceNode = Node<
  {
    entity: GraphNode;
    category: Category;
    time: string;
    focused: boolean;
    dimmed: boolean;
    selectedEvidence: boolean;
    onPath: boolean;
    more: number;
    expand: (id: string) => void;
  },
  "evidence"
>;
function EntityNode({ data }: NodeProps<EvidenceNode>) {
  const Icon = categoryIcons[data.category];
  return (
    <div
      className={`entity-node entity-${data.entity.kind} category-${data.category} ${data.selectedEvidence ? "evidence-selected" : ""} ${data.focused ? "evidence-focus" : ""} ${data.onPath ? "evidence-path" : ""} ${data.dimmed ? "dimmed" : ""}`}
    >
      <Handle type="target" position={Position.Top} />
      <div className="node-circle">
        <Icon size={data.category === "shipment" ? 24 : 18} />
        {data.more > 0 && (
          <button
            type="button"
            className="node-more nodrag"
            title={`Show ${Math.min(data.more, EXPAND_STEP)} more connected records`}
            aria-label={`Show more records connected to ${data.entity.label}`}
            onClick={(event) => {
              event.stopPropagation();
              data.expand(data.entity.id);
            }}
          >
            +{data.more}
          </button>
        )}
      </div>
      <span className="node-label">
        {data.entity.label}
        {data.time && <small>{data.time}</small>}
      </span>
      <Handle type="source" position={Position.Top} />
    </div>
  );
}
const nodeTypes = { evidence: EntityNode };
type SimNode = SimulationNodeDatum & { id: string; depth: number };

const stamp = (value: string | undefined) =>
  value && !Number.isNaN(Date.parse(value))
    ? new Date(value).toLocaleString("en-GB", {
        timeZone: "Asia/Riyadh",
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "";

/** Hops from the shipment through the drawn relationships (unreached records go outermost). */
function depths(nodes: GraphNode[], edges: GraphRelationship[]) {
  const next = new Map<string, string[]>();
  for (const edge of edges) {
    next.set(edge.source, [...(next.get(edge.source) ?? []), edge.target]);
    next.set(edge.target, [...(next.get(edge.target) ?? []), edge.source]);
  }
  const depth = new Map<string, number>();
  const roots = nodes.filter((node) => node.kind === "shipment");
  const queue = (roots.length ? roots : nodes.slice(0, 1)).map(
    (node) => node.id,
  );
  for (const id of queue) depth.set(id, 0);
  while (queue.length) {
    const id = queue.shift()!;
    for (const other of next.get(id) ?? [])
      if (!depth.has(other)) {
        depth.set(other, depth.get(id)! + 1);
        queue.push(other);
      }
  }
  // A record with no drawn relationship to the shipment sits on the first ring, unlinked.
  for (const node of nodes) if (!depth.has(node.id)) depth.set(node.id, 1);
  return depth;
}

/** Shipment-centred positions: rings by distance from the shipment (force) or columns (tree). */
function positions(
  nodes: GraphNode[],
  edges: GraphRelationship[],
  layout: "force" | "tree",
) {
  const depth = depths(nodes, edges);
  if (layout === "tree") {
    const columns = new Map<number, GraphNode[]>();
    for (const node of nodes) {
      const level = depth.get(node.id) ?? 0;
      columns.set(level, [...(columns.get(level) ?? []), node]);
    }
    return nodes.map((node) => {
      const level = depth.get(node.id) ?? 0;
      const column = [...(columns.get(level) ?? [])].sort(
        (a, b) =>
          (a.occurredAt ?? "").localeCompare(b.occurredAt ?? "") ||
          a.label.localeCompare(b.label),
      );
      const index = column.findIndex((item) => item.id === node.id);
      return {
        id: node.id,
        x: level * 215,
        y: (index - (column.length - 1) / 2) * 92,
      };
    });
  }
  const ring = 138;
  const sim: SimNode[] = nodes.map((node, index) => {
    const level = depth.get(node.id) ?? 0;
    return {
      id: node.id,
      depth: level,
      x: Math.cos(index * 2.399) * level * ring,
      y: Math.sin(index * 2.399) * level * ring,
      ...(level === 0 ? { fx: 0, fy: 0 } : {}),
    };
  });
  const ids = new Set(nodes.map((node) => node.id));
  const links = edges
    .filter((edge) => ids.has(edge.source) && ids.has(edge.target))
    .map((edge) => ({ source: edge.source, target: edge.target }));
  forceSimulation(sim)
    .force(
      "link",
      forceLink(links)
        .id((node) => (node as SimNode).id)
        .distance(120)
        .strength(0.3),
    )
    .force("charge", forceManyBody().strength(-420))
    .force("collision", forceCollide(62))
    .force(
      "rings",
      forceRadial((node) => (node as SimNode).depth * ring, 0, 0).strength(0.9),
    )
    .stop()
    .tick(320);
  return sim.map((node) => ({ id: node.id, x: node.x ?? 0, y: node.y ?? 0 }));
}

function GraphInner({
  c,
  selected,
  onSelect,
  onRelation,
  stage,
  filter = "all",
  highlight,
}: {
  c: OperationalCase;
  /** Records a narration message cites: drawn, ringed and lit while it is shown. */
  highlight?: string[];
  selected: string | null;
  onSelect: (id: string) => void;
  onRelation: (id: string) => void;
  stage: number;
  filter?: string;
}) {
  const canvasRef = useRef<HTMLDivElement>(null);
  const backend = !!c.backend;
  const { t, preferences } = usePreferences();
  const [layout, setLayout] = useState<"force" | "tree">("force");
  const [pathOnly, setPathOnly] = useState(false);
  const [showAll, setShowAll] = useState(false);
  // Records the operator asked to see around a node: node id -> how many of its neighbours.
  const [expanded, setExpanded] = useState<Record<string, number>>({});
  const flow = useReactFlow();
  const [nodes, setNodes, onNodesChange] = useNodesState<EvidenceNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  // Keyed on the graph itself: a status update that leaves the graph unchanged keeps the layout.
  const { nodes: pool, relationships: poolEdges, id: caseId } = c;
  useEffect(() => {
    setExpanded({});
    setShowAll(false);
    setPathOnly(false);
  }, [caseId]);

  const neighbours = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const edge of poolEdges) {
      map.set(edge.source, [...(map.get(edge.source) ?? []), edge.target]);
      map.set(edge.target, [...(map.get(edge.target) ?? []), edge.source]);
    }
    return map;
  }, [poolEdges]);
  const selectedNode = useMemo(
    () => pool.find((n) => n.id === selected || n.evidenceId === selected),
    [pool, selected],
  );
  /** The evidence path: the shipment, its packages, the decision, and every cited record. */
  const path = useMemo(
    () =>
      new Set(
        pool
          .filter(
            (n) =>
              n.cited ||
              ["shipment", "package", "recommendation", "outcome"].includes(
                n.kind,
              ),
          )
          .map((n) => n.id),
      ),
    [pool],
  );
  const hasCitations = useMemo(() => pool.some((n) => n.cited), [pool]);

  /** The nodes drawn now: a focused, shipment-centred set, plus whatever was expanded. */
  const visible = useMemo(() => {
    const byId = new Map(pool.map((n) => [n.id, n]));
    const recent = (a: GraphNode, b: GraphNode) =>
      (b.occurredAt ?? "").localeCompare(a.occurredAt ?? "");
    // A small graph (the lab's, or a filtered one) is drawn whole.
    if (showAll || pool.length <= FOCUS_LIMIT)
      return new Set(pool.map((n) => n.id));
    const keep = new Set<string>();
    for (const n of pool)
      if (
        ["shipment", "package", "recommendation", "outcome"].includes(n.kind) ||
        n.cited
      )
        keep.add(n.id);
    // No citations yet (not investigated, or nothing accepted): the latest located records.
    if (!hasCitations)
      for (const n of pool
        .filter((n) => n.evidenceId && EVENTS.has(categoryOf(n)))
        .sort(recent)
        .slice(0, 8))
        keep.add(n.id);
    // What those records refer to: where, by which device, on which vehicle, who held it.
    // One thing per record first (a device or facility before anything else), then more.
    const order: Category[] = [
      "device",
      "facility",
      "vehicle",
      "transport",
      "person",
      "organisation",
    ];
    const events = [...keep]
      .map((id) => byId.get(id))
      .filter(
        (node): node is GraphNode => !!node && EVENTS.has(categoryOf(node)),
      );
    for (const round of [0, 1])
      for (const node of events) {
        if (keep.size >= FOCUS_LIMIT) break;
        const around = (neighbours.get(node.id) ?? [])
          .map((other) => byId.get(other))
          .filter(
            (item): item is GraphNode =>
              !!item &&
              !EVENTS.has(categoryOf(item)) &&
              item.kind !== "package",
          )
          .sort(
            (a, b) =>
              order.indexOf(categoryOf(a)) - order.indexOf(categoryOf(b)),
          );
        const next = around.filter((item) => !keep.has(item.id))[0];
        if (next && (round === 1 || !around.some((item) => keep.has(item.id))))
          keep.add(next.id);
      }
    // Whatever the operator selected (on the map too) or expanded is always drawn, and so are
    // the records a narration message points at (bounded, so a wide query stays readable).
    if (selectedNode) keep.add(selectedNode.id);
    for (const id of highlight ?? []) if (byId.has(id)) keep.add(id);
    for (const [id, count] of Object.entries(expanded)) {
      const around = (neighbours.get(id) ?? [])
        .map((other) => byId.get(other))
        .filter((item): item is GraphNode => !!item)
        .sort(
          (a, b) =>
            Number(EVENTS.has(categoryOf(a))) -
              Number(EVENTS.has(categoryOf(b))) || recent(a, b),
        );
      for (const item of around.slice(0, count)) keep.add(item.id);
    }
    return keep;
  }, [
    pool,
    neighbours,
    expanded,
    showAll,
    selectedNode,
    hasCitations,
    highlight,
  ]);

  const drawn = useMemo(
    () =>
      pool.filter(
        (n) =>
          visible.has(n.id) &&
          (filter === "all" || n.kind === filter || n.kind === "shipment"),
      ),
    [pool, visible, filter],
  );
  const drawnEdges = useMemo(() => {
    const ids = new Set(drawn.map((n) => n.id));
    // One line per pair of records: parallel relationships share it.
    const seen = new Map<string, GraphRelationship & { also: string[] }>();
    for (const edge of poolEdges) {
      if (!ids.has(edge.source) || !ids.has(edge.target)) continue;
      const key = [edge.source, edge.target].sort().join("|");
      const first = seen.get(key);
      if (first) first.also.push(edge.label);
      else seen.set(key, { ...edge, also: [] });
    }
    return [...seen.values()];
  }, [drawn, poolEdges]);
  const layoutPositions = useMemo(
    () => new Map(positions(drawn, drawnEdges, layout).map((p) => [p.id, p])),
    [drawn, drawnEdges, layout],
  );

  useEffect(() => {
    const related = new Set(
      selectedNode
        ? [selectedNode.id, ...(neighbours.get(selectedNode.id) ?? [])]
        : [],
    );
    const stageKinds = backend
      ? []
      : stage === 1
        ? ["facility"]
        : stage === 2
          ? ["observation", "vehicle", "package"]
          : stage === 4 || stage === 5
            ? ["recommendation"]
            : stage === 7
              ? ["outcome"]
              : [];
    // The highlighted set: around the selection if there is one, else what the narration
    // message on screen cites, else the cited evidence path.
    const narrated = new Set(highlight ?? []);
    const lit = selectedNode
      ? new Set([...related, ...narrated])
      : narrated.size
        ? new Set([
            ...narrated,
            ...pool
              .filter((n) => n.kind === "shipment" || n.kind === "package")
              .map((n) => n.id),
          ])
        : hasCitations
          ? path
          : new Set<string>();
    const expand = (id: string) =>
      setExpanded((all) => ({ ...all, [id]: (all[id] ?? 0) + EXPAND_STEP }));
    setNodes(
      drawn.map((n) => {
        const p = layoutPositions.get(n.id) ?? { x: 0, y: 0 };
        const category = categoryOf(n);
        const hidden = (neighbours.get(n.id) ?? []).filter(
          (other) => !visible.has(other),
        ).length;
        return {
          id: n.id,
          type: "evidence",
          position: { x: p.x, y: p.y },
          data: {
            entity: n,
            category,
            time: EVENTS.has(category) ? stamp(n.occurredAt) : "",
            selectedEvidence: n.id === selected || n.evidenceId === selected,
            focused: stageKinds.includes(n.kind) || related.has(n.id),
            onPath: narrated.size
              ? narrated.has(n.id)
              : hasCitations && !!n.cited,
            dimmed:
              (pathOnly || narrated.size > 0) && lit.size > 0 && !lit.has(n.id),
            more: hidden,
            expand,
          },
          ariaLabel: `${n.label} · ${n.kind}`,
          selected: n.id === selected || n.evidenceId === selected,
          zIndex: category === "shipment" ? 3 : n.cited ? 2 : 1,
        };
      }),
    );
    const dark = preferences.theme === "dark";
    setEdges(
      drawnEdges.map((e) => {
        const strong = lit.has(e.source) && lit.has(e.target);
        const touching =
          !!selectedNode &&
          (e.source === selectedNode.id || e.target === selectedNode.id);
        return {
          id: e.id,
          source: e.source,
          target: e.target,
          // Relationship names are shown where they are being read: on the selection.
          label:
            touching || (layout === "tree" && drawn.length <= 14)
              ? [e.label, ...e.also]
                  .slice(0, 2)
                  .join(" · ")
                  .replaceAll("_", " ")
                  .toLowerCase()
              : undefined,
          type: "straight",
          style: {
            stroke: strong ? "#8b6ccb" : dark ? "#4a5166" : "#c5c9d6",
            strokeWidth: strong ? 2.4 : 1.2,
            opacity:
              (pathOnly || narrated.size > 0) && lit.size > 0 && !strong
                ? 0.1
                : strong
                  ? 0.95
                  : 0.7,
          },
          labelStyle: {
            fontSize: 10,
            fill: dark ? "#c3c8d8" : "#6d7286",
          },
          labelBgStyle: {
            fill: dark ? "#1c202c" : "#fff",
            fillOpacity: 0.92,
          },
          labelBgPadding: [4, 2] as [number, number],
          labelBgBorderRadius: 3,
          ariaLabel: `${[e.label, ...e.also].join(", ")}: ${e.detail}`,
          zIndex: strong ? 1 : 0,
        };
      }),
    );
  }, [
    drawn,
    drawnEdges,
    selected,
    selectedNode,
    neighbours,
    visible,
    path,
    hasCitations,
    highlight,
    pool,
    layoutPositions,
    layout,
    stage,
    backend,
    pathOnly,
    preferences.theme,
    setNodes,
    setEdges,
  ]);
  const fit = () =>
    flow.fitView({
      padding: 0.12,
      maxZoom: 1.15,
      duration: preferences.motion === "reduce" ? 0 : 220,
    });
  const drawnKey = drawn.map((n) => n.id).join("|");
  useEffect(() => {
    const timer = setTimeout(() => void fit(), 90);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layout, drawnKey, flow, preferences.motion]);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let timer: ReturnType<typeof setTimeout>;
    const observer = new ResizeObserver(() => {
      clearTimeout(timer);
      timer = setTimeout(() => void fit(), 90);
    });
    observer.observe(canvas);
    return () => {
      observer.disconnect();
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flow, preferences.motion]);
  const focusable = pool.length > FOCUS_LIMIT;
  const present = new Set(drawn.map(categoryOf));
  const legend: [string, string, string, Category[]][] = [
    [
      "shipment",
      "Shipment & packages",
      "الشحنة والطرود",
      ["shipment", "package"],
    ],
    ["custody", "Custody", "الحيازة", ["custody"]],
    ["scan", "Scans", "المسح", ["scan"]],
    [
      "status",
      "Status, attempts, proof",
      "الحالة والمحاولات والإثبات",
      ["status", "attempt", "proof", "message", "position"],
    ],
    ["device", "Devices", "الأجهزة", ["device"]],
    ["facility", "Facilities", "المرافق", ["facility"]],
    [
      "vehicle",
      "Vehicles & trips",
      "المركبات والرحلات",
      ["vehicle", "transport"],
    ],
    [
      "person",
      "People & organisations",
      "الأشخاص والجهات",
      ["person", "organisation"],
    ],
    [
      "outcome",
      "Decision & outcome",
      "القرار والنتيجة",
      ["recommendation", "outcome"],
    ],
  ];
  return (
    <section
      className="visualization graph-panel"
      aria-label={t("Knowledge graph", "الرسم البياني المعرفي")}
    >
      <div className="viz-header">
        <div className="flex items-center gap-2">
          <Network size={15} />
          <h2>{t("Knowledge graph", "الرسم البياني المعرفي")}</h2>
          <span className="subtle-count" data-testid="graph-count">
            {focusable && !showAll
              ? t(
                  `${nodes.length} of ${pool.length}`,
                  `${nodes.length} من ${pool.length}`,
                )
              : nodes.length}
          </span>
        </div>
        <div className="graph-layout" role="group" aria-label="Graph layout">
          <Button
            variant="ghost"
            size="sm"
            aria-pressed={layout === "force"}
            onClick={() => setLayout("force")}
          >
            {t("Force", "قوى")}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            aria-pressed={layout === "tree"}
            onClick={() => setLayout("tree")}
          >
            {t("Tree", "شجرة")}
          </Button>
        </div>
      </div>
      <div
        ref={canvasRef}
        className="graph-canvas"
        dir="ltr"
        data-testid="knowledge-graph"
      >
        {!pool.length && (
          <p
            className="workspace-empty-visual"
            role="status"
            data-testid="graph-empty-state"
          >
            {t(
              "No source graph records are available for this case.",
              "لا سجلات رسم مصدر متاحة لهذه الحالة.",
            )}
          </p>
        )}
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={(_, node) =>
            onSelect(node.data.entity.evidenceId ?? node.id)
          }
          onNodeDoubleClick={(_, node) => node.data.expand(node.id)}
          onEdgeClick={(_, edge) => onRelation(edge.id)}
          fitView
          fitViewOptions={{ padding: 0.12, maxZoom: 1.15 }}
          minZoom={0.15}
          maxZoom={2.5}
          nodesConnectable={false}
          zoomOnDoubleClick={false}
          deleteKeyCode={null}
          colorMode={preferences.theme}
          proOptions={{ hideAttribution: false }}
        >
          <Background
            color={preferences.theme === "dark" ? "#2c3242" : "#e6e8ef"}
            gap={22}
            size={1}
          />
          <Controls showInteractive={false} position="top-left" />
        </ReactFlow>
        <div className="graph-tools">
          {focusable && (
            <Button
              size="sm"
              variant={showAll ? "secondary" : "outline"}
              onClick={() => setShowAll((value) => !value)}
              title={t(
                "Switch between the focused view and every record drawn for this case",
                "التبديل بين العرض المركّز وكل السجلات المرسومة لهذه الحالة",
              )}
            >
              {showAll ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
              {showAll
                ? t("Focused view", "عرض مركّز")
                : t(
                    `All ${pool.length} records`,
                    `كل السجلات (${pool.length})`,
                  )}
            </Button>
          )}
          <Button
            size="sm"
            variant={pathOnly ? "secondary" : "outline"}
            disabled={!selected && !hasCitations}
            onClick={() => setPathOnly((v) => !v)}
          >
            <Focus size={13} />
            {t("Evidence path", "مسار الأدلة")}
          </Button>
        </div>
      </div>
      <div className="viz-legend graph-legend">
        {legend
          .filter(([, , , categories]) =>
            categories.some((item) => present.has(item)),
          )
          .map(([key, en, ar]) => (
            <span key={key}>
              <i className={`dot category-dot-${key}`} />
              {t(en, ar)}
            </span>
          ))}
        {hasCitations && (
          <span>
            <i className="dot ring" />
            {t("Cited by the finding", "استشهد به الاستنتاج")}
          </span>
        )}
        <span className="legend-hint">
          {t(
            "Click a record to inspect · +N or double-click to expand",
            "انقر سجلاً لفحصه · ‎+N أو نقر مزدوج للتوسيع",
          )}
        </span>
      </div>
    </section>
  );
}
export function KnowledgeGraph(props: Parameters<typeof GraphInner>[0]) {
  return (
    <ReactFlowProvider>
      <GraphInner {...props} />
    </ReactFlowProvider>
  );
}
