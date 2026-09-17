import type { ReactNode } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Inbox,
  Repeat,
  TrendingUp,
  UserCheck,
} from "lucide-react";
import { useFetch } from "../../hooks/useFetch";
import { RankedBars, type RankedItem } from "../dashboard/RankedBars";
import { StackedBar, type Segment } from "../dashboard/StackedBar";
import { StatTile } from "../dashboard/StatTile";
import { Skeleton } from "../ui/Skeleton";
import type { CasesOverview } from "../../types/agent";

function Card({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-hairline bg-panel p-4">
      <h3 className="text-sm font-semibold text-ink">{title}</h3>
      <p className="mb-4 mt-0.5 text-xs text-muted">{subtitle}</p>
      {children}
    </section>
  );
}

// Category names in the graph are snake_case, and the escalation:* prefix marks a case that
// was escalated rather than resolved directly. Rendered readably without losing that.
const label = (raw: string): string => {
  const escalated = raw.startsWith("escalation:");
  const base = escalated ? raw.slice("escalation:".length) : raw;
  const words = base.replace(/_/g, " ");
  return escalated ? `${words} (escalated)` : words;
};

export function DecisionsView() {
  const { data, loading } = useFetch<CasesOverview>("/cases");

  if (loading || !data) {
    return (
      <div className="grid gap-4 overflow-y-auto p-6 md:grid-cols-2 xl:grid-cols-5">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="h-40 rounded-2xl" />
        ))}
      </div>
    );
  }

  const {
    coverage,
    by_category,
    by_action,
    writebacks,
    queue,
    escalations,
    escalations_by_team,
  } = data;
  const resolvedPct = coverage.total
    ? Math.round((coverage.resolved / coverage.total) * 100)
    : 0;

  // Overall precedent quality: how often the historical action actually worked.
  const totalCases = by_category.reduce((a, c) => a + c.cases, 0);
  const totalWon = by_category.reduce((a, c) => a + c.succeeded, 0);
  const overallRate = totalCases
    ? Math.round((totalWon / totalCases) * 100)
    : 0;

  const coverageSegments: Segment[] = [
    {
      key: "resolved",
      label: "Resolved",
      value: coverage.resolved,
      colorClass: "bg-chart-good",
      icon: <CheckCircle2 size={12} className="text-chart-good" />,
    },
    {
      key: "unresolved",
      label: "Open",
      value: coverage.unresolved,
      colorClass: "bg-chart-warning",
      icon: <AlertTriangle size={12} className="text-chart-warning" />,
    },
  ];

  const categoryBars: RankedItem[] = by_category
    .filter((c) => !c.category.startsWith("escalation:"))
    .slice(0, 7)
    .map((c) => ({
      key: c.category,
      label: label(c.category),
      value: Math.round(c.success_rate),
      detail: `${c.succeeded} of ${c.cases} worked`,
    }));

  const actionBars: RankedItem[] = by_action.slice(0, 7).map((a) => ({
    key: a.action,
    label: a.action,
    value: Math.round(a.success_rate),
    detail: `used ${a.used}×`,
  }));

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <StatTile
          label="Open cases"
          value={coverage.unresolved}
          detail="Unresolved failures awaiting a decision"
          icon={<Inbox size={16} />}
          tone={coverage.unresolved > 0 ? "warning" : "good"}
        />
        <StatTile
          label="Precedent available"
          value={coverage.resolved}
          detail={`${resolvedPct}% of all failures carry a resolution`}
          icon={<CheckCircle2 size={16} />}
          tone="good"
        />
        <StatTile
          label="Historical success rate"
          value={`${overallRate}%`}
          detail={`${totalWon} of ${totalCases} resolutions worked`}
          icon={<TrendingUp size={16} />}
          tone="default"
        />
        <StatTile
          label="Waiting on a human"
          value={escalations.filter((e) => e.status === "open").length}
          detail={
            escalations.length === 0
              ? "Nothing escalated yet"
              : `across ${escalations_by_team.length} team${escalations_by_team.length === 1 ? "" : "s"}`
          }
          icon={<UserCheck size={16} />}
          tone={
            escalations.some((e) => e.status === "open") ? "warning" : "default"
          }
        />
        <StatTile
          label="Written by the agent"
          value={writebacks.by_agent}
          detail={
            writebacks.by_agent === 0
              ? "No agent resolutions yet — run a complaint"
              : `of ${writebacks.total} total resolutions in the graph`
          }
          icon={<Repeat size={16} />}
          tone={writebacks.by_agent > 0 ? "good" : "default"}
        />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card
          title="Case coverage"
          subtitle="Every failure in the graph, split by whether it has a resolution the agent can learn from"
        >
          <StackedBar segments={coverageSegments} />
        </Card>

        <Card
          title="Closed-loop learning"
          subtitle="Resolutions the pipeline wrote back, against the seeded history"
        >
          <StackedBar
            segments={[
              {
                key: "agent",
                label: "Written by the agent",
                value: writebacks.by_agent,
                colorClass: "bg-chart-blue",
              },
              {
                key: "seeded",
                label: "Seeded history",
                value: writebacks.seeded,
                colorClass: "bg-chart-aqua",
              },
            ]}
          />
          <p className="mt-3 text-xs text-muted">
            Each accepted recommendation becomes a new precedent, retrievable by
            the next case's vector search.
          </p>
        </Card>

        <Card
          title="Success rate by root cause"
          subtitle="What the recommender draws on — how often the historical fix actually worked, per category"
        >
          <RankedBars items={categoryBars} />
        </Card>

        <Card
          title="Success rate by action"
          subtitle="The action vocabulary, ranked by how well it has held up"
        >
          <RankedBars items={actionBars} />
        </Card>
      </div>

      <div className="mt-4 space-y-4">
        {escalations.length > 0 && (
          <Card
            title={`Escalated to a human (${escalations.filter((e) => e.status === "open").length} open)`}
            subtitle="Cases the agent handed over, with the root cause it reached and the actions already tried"
          >
            <div className="max-h-96 space-y-2 overflow-y-auto">
              {escalations.map((e) => (
                <div
                  key={e.escalation_id}
                  className="rounded-xl border border-hairline p-3"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className="rounded-md bg-accent-soft px-2 py-0.5 text-[11px] font-medium text-accent"
                      dir="rtl"
                    >
                      {e.team}
                    </span>
                    {e.priority && (
                      <span className="rounded-md bg-surface px-2 py-0.5 text-[11px] text-muted">
                        {e.priority}
                      </span>
                    )}
                    {e.shipment_id && (
                      <span className="text-[11px] text-muted">
                        {e.shipment_id}
                      </span>
                    )}
                    <span className="ml-auto font-mono text-[10px] text-muted">
                      {e.escalation_id}
                    </span>
                  </div>
                  <p className="mt-1.5 text-sm text-ink" dir="auto">
                    {e.complaint}
                  </p>
                  <p className="mt-1 text-xs text-muted">{e.reason}</p>
                  {e.attempted_actions.length > 0 && (
                    <p className="mt-1.5 text-xs text-muted">
                      Already tried:{" "}
                      <span className="text-ink" dir="rtl">
                        {e.attempted_actions.join(" · ")}
                      </span>
                    </p>
                  )}
                </div>
              ))}
            </div>
          </Card>
        )}

        <Card
          title={`Open case queue (${queue.length})`}
          subtitle="Unresolved failures — each one is a complaint the agent can be run against"
        >
          <div className="max-h-96 overflow-y-auto">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-panel">
                <tr className="text-muted">
                  <th className="py-1.5 pr-3 font-medium">Failure</th>
                  <th className="py-1.5 pr-3 font-medium">Shipment</th>
                  <th className="py-1.5 pr-3 font-medium">Root cause</th>
                  <th className="py-1.5 pr-3 font-medium">City</th>
                  <th className="py-1.5 font-medium">Courier</th>
                </tr>
              </thead>
              <tbody>
                {queue.map((c) => (
                  <tr key={c.failure_id} className="border-t border-hairline">
                    <td className="py-1.5 pr-3 font-mono text-[11px] text-muted">
                      {c.failure_id}
                    </td>
                    <td className="py-1.5 pr-3 text-ink">
                      {c.shipment_id ?? "—"}
                    </td>
                    <td className="py-1.5 pr-3 text-ink">
                      {label(c.category)}
                    </td>
                    <td className="py-1.5 pr-3 text-ink" dir="auto">
                      {c.city ?? "—"}
                    </td>
                    <td className="py-1.5 text-ink" dir="auto">
                      {c.courier ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </div>
  );
}
