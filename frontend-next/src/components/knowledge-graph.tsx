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
  forceCenter,
  forceCollide,
  forceX,
  forceY,
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
} from "lucide-react";
import "@xyflow/react/dist/style.css";
import type { GraphNode, OperationalCase } from "@/domain/types";
import { Button } from "@/components/ui/button";
import { usePreferences } from "@/state/preferences";

const nodeIcons = {
  shipment: Package,
  package: Box,
  facility: Building2,
  vehicle: Truck,
  driver: UserRound,
  contractor: Building2,
  observation: ScanLine,
  recommendation: Sparkles,
  outcome: CheckCheck,
};
type EvidenceNode = Node<
  {
    entity: GraphNode;
    focused: boolean;
    dimmed: boolean;
    selectedEvidence: boolean;
  },
  "evidence"
>;
function EntityNode({ data }: NodeProps<EvidenceNode>) {
  const Icon = nodeIcons[data.entity.kind];
  return (
    <div
      className={`entity-node entity-${data.entity.kind} ${data.selectedEvidence ? "evidence-selected" : ""} ${data.focused ? "evidence-focus" : ""} ${data.dimmed ? "dimmed" : ""}`}
    >
      <Handle type="target" position={Position.Left} />
      <div className="node-circle">
        <Icon size={19} />
      </div>
      <span className="node-label">{data.entity.label}</span>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
const nodeTypes = { evidence: EntityNode };
type SimNode = SimulationNodeDatum & { id: string };
function positions(
  c: Pick<OperationalCase, "nodes" | "relationships">,
  layout: "force" | "tree",
) {
  if (layout === "tree")
    return c.nodes.map((node, index) => ({
      id: node.id,
      x:
        node.kind === "shipment"
          ? 0
          : node.kind === "package"
            ? 220
            : node.kind === "observation"
              ? 440
              : node.kind === "facility"
                ? 660
                : node.kind === "outcome"
                  ? 880
                  : 220,
      y:
        node.kind === "observation"
          ? (c.nodes
              .filter((n) => n.kind === "observation")
              .findIndex((n) => n.id === node.id) -
              2) *
            115
          : node.id === "shipment" || node.id === "package"
            ? 0
            : node.kind === "shipment"
              ? 0
              : node.kind === "package"
                ? c.nodes
                    .filter((n) => n.kind === "package")
                    .findIndex((n) => n.id === node.id) * 90
            : ((index % 5) - 2) * 125,
    }));
  const nodes: SimNode[] = c.nodes.map((n, i) => ({
    id: n.id,
    x: Math.cos(i * 2.399) * 220,
    y: Math.sin(i * 2.399) * 200,
  }));
  const links = c.relationships.map((e) => ({
    source: e.source,
    target: e.target,
  }));
  const simulation = forceSimulation(nodes)
    .force(
      "link",
      forceLink(links)
        .id((n) => (n as SimNode).id)
        .distance(125)
        .strength(0.8),
    )
    .force("charge", forceManyBody().strength(-300))
    .force("center", forceCenter(350, 240))
    .force("collision", forceCollide(65))
    .force("horizontal", forceX(350).strength(0.065))
    .force("vertical", forceY(240).strength(0.12))
    .stop();
  simulation.tick(240);
  return nodes.map((n) => ({ id: n.id, x: n.x ?? 0, y: n.y ?? 0 }));
}
function GraphInner({
  c,
  selected,
  onSelect,
  onRelation,
  stage,
  filter = "all",
}: {
  c: OperationalCase;
  selected: string | null;
  onSelect: (id: string) => void;
  onRelation: (id: string) => void;
  stage: number;
  filter?: string;
}) {
  const canvasRef = useRef<HTMLDivElement>(null);
  const { t, preferences } = usePreferences();
  const [layout, setLayout] = useState<"force" | "tree">("force");
  const [pathOnly, setPathOnly] = useState(false);
  const flow = useReactFlow();
  const [nodes, setNodes, onNodesChange] = useNodesState<EvidenceNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  // Keyed on the graph itself: a status update that leaves the graph unchanged keeps the layout.
  const { nodes: graphNodes, relationships: graphEdges } = c;
  const layoutPositions = useMemo(
    () => positions({ nodes: graphNodes, relationships: graphEdges }, layout),
    [graphNodes, graphEdges, layout],
  );
  useEffect(() => {
    const selectedNode = c.nodes.find(
      (n) => n.id === selected || n.evidenceId === selected,
    );
    const related = new Set(
      selectedNode
        ? [
            selectedNode.id,
            ...c.relationships
              .filter(
                (e) =>
                  e.source === selectedNode.id || e.target === selectedNode.id,
              )
              .flatMap((e) => [e.source, e.target]),
          ]
        : [],
    );
    const stageKinds =
      stage === 1
        ? ["facility"]
        : stage === 2
          ? ["observation", "vehicle", "package"]
          : stage === 4 || stage === 5
            ? ["recommendation"]
            : stage === 7
              ? ["outcome"]
              : [];
    setNodes(
      c.nodes
        .filter(
          (n) => filter === "all" || n.kind === filter || n.kind === "shipment",
        )
        .map((n) => {
          const p = layoutPositions.find((p) => p.id === n.id)!;
          return {
            id: n.id,
            type: "evidence",
            position: { x: p.x, y: p.y },
            data: {
              entity: n,
              selectedEvidence: n.id === selected || n.evidenceId === selected,
              focused: stageKinds.includes(n.kind) || related.has(n.id),
              dimmed: pathOnly && !!selected && !related.has(n.id),
            },
            ariaLabel: `${n.label} · ${n.kind}`,
            selected: n.id === selected || n.evidenceId === selected,
          };
        }),
    );
    setEdges(
      c.relationships
        .filter(
          (e) =>
            filter === "all" ||
            (c.nodes.some(
              (n) =>
                n.id === e.source &&
                (n.kind === filter || n.kind === "shipment"),
            ) &&
              c.nodes.some(
                (n) =>
                  n.id === e.target &&
                  (n.kind === filter || n.kind === "shipment"),
              )),
        )
        .map((e) => ({
          id: e.id,
          source: e.source,
          target: e.target,
          label:
            layout === "tree"
              ? e.label
              : e.label.replaceAll("_", " ").toLowerCase(),
          type: "default",
          style: {
            stroke:
              related.has(e.source) && related.has(e.target)
                ? "#8b6ccb"
                : "#c9ccd6",
            strokeWidth:
              related.has(e.source) && related.has(e.target) ? 2.5 : 1.3,
            opacity:
              pathOnly &&
              !!selected &&
              (!related.has(e.source) || !related.has(e.target))
                ? 0.12
                : 0.8,
          },
          labelStyle: {
            fontSize: 9,
            fill: preferences.theme === "dark" ? "#b5bbcd" : "#85899b",
          },
          labelBgStyle: {
            fill: preferences.theme === "dark" ? "#1c202c" : "#fff",
            fillOpacity: 0.9,
          },
          ariaLabel: `${e.label}: ${e.detail}`,
        })),
    );
  }, [
    c,
    selected,
    layoutPositions,
    layout,
    stage,
    pathOnly,
    preferences.theme,
    filter,
    setNodes,
    setEdges,
  ]);
  useEffect(() => {
    const timer = setTimeout(
      () =>
        flow.fitView({
          padding: 0.08,
          duration: preferences.motion === "reduce" ? 0 : 180,
        }),
      80,
    );
    return () => clearTimeout(timer);
  }, [layout, graphNodes, filter, flow, preferences.motion]);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let timer: ReturnType<typeof setTimeout>;
    const observer = new ResizeObserver(() => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        void flow.fitView({
          padding: 0.08,
          duration: preferences.motion === "reduce" ? 0 : 180,
        });
      }, 80);
    });
    observer.observe(canvas);
    return () => {
      observer.disconnect();
      clearTimeout(timer);
    };
  }, [flow, preferences.motion]);
  return (
    <section
      className="visualization graph-panel"
      aria-label={t("Knowledge graph", "الرسم البياني المعرفي")}
    >
      <div className="viz-header">
        <div className="flex items-center gap-2">
          <Network size={15} />
          <h2>{t("Knowledge graph", "الرسم البياني المعرفي")}</h2>
          <span className="subtle-count">{nodes.length}</span>
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
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={(_, node) =>
            onSelect(node.data.entity.evidenceId ?? node.id)
          }
          onEdgeClick={(_, edge) => onRelation(edge.id)}
          fitView
          fitViewOptions={{ padding: 0.08 }}
          minZoom={0.2}
          maxZoom={2.5}
          nodesConnectable={false}
          deleteKeyCode={null}
          colorMode={preferences.theme}
          proOptions={{ hideAttribution: false }}
        >
          <Background
            color={preferences.theme === "dark" ? "#353b4c" : "#e1e3eb"}
            gap={20}
            size={1}
          />
          <Controls showInteractive={false} position="top-left" />
        </ReactFlow>
        <div className="graph-tools">
          <Button
            size="sm"
            variant={pathOnly ? "secondary" : "outline"}
            disabled={!selected}
            onClick={() => setPathOnly((v) => !v)}
          >
            <Focus size={13} />
            {t("Evidence path", "مسار الأدلة")}
          </Button>
          <span className="graph-2d">2D</span>
        </div>
      </div>
      <div className="viz-legend">
        <span>
          <i className="dot purple" />
          {t("Shipment", "الشحنة")}
        </span>
        <span>
          <i className="dot blue" />
          {t("Custody", "الحيازة")}
        </span>
        <span>
          <i className="dot amber" />
          {t("Transport", "النقل")}
        </span>
        <span>
          <i className="dot green" />
          {t("Facility", "المرفق")}
        </span>
        <span className="legend-hint">
          {t("Drag to explore", "اسحب للاستكشاف")}
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
