import type { ReactNode } from 'react'
import { AlertTriangle, CheckCircle2, ClipboardList, GitBranch, Target } from 'lucide-react'
import { useFetch } from '../../hooks/useFetch'
import { RankedBars, type RankedItem } from '../dashboard/RankedBars'
import { StackedBar, type Segment } from '../dashboard/StackedBar'
import { StatTile } from '../dashboard/StatTile'
import { TableView } from '../artifacts/TableView'
import { Skeleton } from '../ui/Skeleton'

interface Tile {
  id: string
  title: string
  question: string
  live: boolean
  rows?: Record<string, unknown>[]
  params?: string[]
}

// Person and BudgetLine are deliberately kept off the Dashboard - Q32 (named individuals'
// attendance) and Q24 (budget totals) still exist for Filter/Chat, just not curated here.
const HIDDEN_ON_DASHBOARD = new Set(['Q24', 'Q32'])

const num = (v: unknown): number => (typeof v === 'number' ? v : Number(v) || 0)
const str = (v: unknown): string => (v == null ? '' : String(v))

function ShortcutTile({ tile, onOpenFilter }: { tile: Tile; onOpenFilter: (id: string) => void }) {
  return (
    <section className="flex h-40 flex-col justify-between rounded-2xl border border-dashed border-hairline bg-panel/60 p-4">
      <div>
        <h3 className="text-sm font-semibold text-ink">{tile.title}</h3>
        <p className="mt-1 text-xs text-muted">{tile.question}</p>
      </div>
      <button
        onClick={() => onOpenFilter(tile.id)}
        className="self-start rounded-full bg-accent-soft px-3 py-1 text-xs font-medium text-accent transition-colors hover:bg-accent hover:text-white"
      >
        Go pick one →
      </button>
    </section>
  )
}

function LiveTile({ tile }: { tile: Tile }) {
  return (
    <section className="flex h-72 flex-col rounded-2xl border border-hairline bg-panel p-4">
      <h3 className="text-sm font-semibold text-ink">{tile.title}</h3>
      <p className="mb-2 text-xs text-muted">{tile.question}</p>
      <div className="min-h-0 flex-1 overflow-hidden rounded-lg border border-hairline">
        <TableView rows={tile.rows ?? []} title={tile.title} />
      </div>
    </section>
  )
}

function ChartCard({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <section className="rounded-2xl border border-hairline bg-panel p-4">
      <h3 className="text-sm font-semibold text-ink">{title}</h3>
      <p className="mb-4 mt-0.5 text-xs text-muted">{subtitle}</p>
      {children}
    </section>
  )
}

function ListCard({ title, subtitle, rows, children }: { title: string; subtitle: string; rows: unknown[]; children: ReactNode }) {
  return (
    <section className="rounded-2xl border border-hairline bg-panel p-4">
      <h3 className="text-sm font-semibold text-ink">{title}</h3>
      <p className="mb-2 mt-0.5 text-xs text-muted">{subtitle}</p>
      <div className="max-h-72 overflow-y-auto">
        {rows.length ? children : <p className="py-6 text-center text-sm text-muted">No matching rows.</p>}
      </div>
    </section>
  )
}

// Fixed status -> color mapping: color follows the entity, never the sort order the query
// happens to return it in (see dataviz skill's non-negotiables).
const STATUS_COLOR: Record<string, string> = {
  Open: 'bg-chart-blue',
  Closed: 'bg-chart-aqua',
  Evolved: 'bg-chart-orange',
}

// Status colors (good/warning), never color alone - each carries an icon + label.
const OWNERSHIP_STYLE: Record<string, { colorClass: string; icon: ReactNode }> = {
  'Named individual': { colorClass: 'bg-chart-good', icon: <CheckCircle2 size={12} className="text-chart-good" /> },
  'No named individual': { colorClass: 'bg-chart-warning', icon: <AlertTriangle size={12} className="text-chart-warning" /> },
}

// Every query from the catalog is still available here (see backend main.py:/dashboard), but
// the five queries with a natural aggregate shape (Q01/Q02/Q07/Q11/Q39) get a purpose-built
// stat/chart/list treatment instead of a raw table. Anything else - a future query this view
// doesn't yet curate - still falls back to the old plain-table tile, so nothing silently
// disappears from the Dashboard just because it isn't hand-designed yet.
export function DashboardView({ onOpenFilter }: { onOpenFilter: (id: string) => void }) {
  const { data, loading } = useFetch<{ tiles: Tile[] }>('/dashboard')

  if (loading) {
    return (
      <div className="h-full overflow-y-auto px-6 py-8">
        <div className="mx-auto grid w-full max-w-6xl gap-3 md:grid-cols-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-72" />
          ))}
        </div>
      </div>
    )
  }

  const tiles = (data?.tiles ?? []).filter((t) => !HIDDEN_ON_DASHBOARD.has(t.id))
  const byId = new Map(tiles.map((t) => [t.id, t]))
  const q01 = byId.get('Q01')?.rows ?? []
  const q02 = byId.get('Q02')?.rows ?? []
  const q07 = byId.get('Q07')?.rows ?? []
  const q11 = byId.get('Q11')?.rows ?? []
  const q39 = byId.get('Q39')?.rows ?? []

  const CURATED_IDS = new Set(['Q01', 'Q02', 'Q07', 'Q11', 'Q39'])
  const extraLive = tiles.filter((t) => t.live && !CURATED_IDS.has(t.id))
  const shortcuts = tiles.filter((t) => !t.live)

  const totalMandates = q01.reduce((sum, r) => sum + num(r.mandates), 0)
  const overdueCount = q02.length
  const noOwnerPct = num(q07.find((r) => str(r.ownership) === 'No named individual')?.pct)
  const createdCount = q11.length

  const statusSegments: Segment[] = q01.map((r) => ({
    key: str(r.status),
    label: str(r.status) || 'Unknown',
    value: num(r.mandates),
    colorClass: STATUS_COLOR[str(r.status)] ?? 'bg-muted/40',
  }))

  const ownershipSegments: Segment[] = q07.map((r) => {
    const style = OWNERSHIP_STYLE[str(r.ownership)] ?? { colorClass: 'bg-muted/40', icon: undefined }
    return {
      key: str(r.ownership),
      label: `${str(r.ownership)} (${num(r.pct)}%)`,
      value: num(r.mandates),
      colorClass: style.colorClass,
      icon: style.icon,
    }
  })

  const closureRateItems: RankedItem[] = [...q39]
    .sort((a, b) => num(b.closure_rate_pct) - num(a.closure_rate_pct))
    .map((r) => ({
      key: str(r.entity),
      label: str(r.entity) || 'Unknown',
      value: num(r.closure_rate_pct),
      detail: `${num(r.closed)}/${num(r.total)} closed`,
    }))

  return (
    <div className="h-full overflow-y-auto px-6 py-8">
      <div className="mx-auto w-full max-w-6xl">
        <h2 className="font-display text-2xl font-bold tracking-tight text-ink">Dashboard</h2>
        <p className="mt-1 text-sm text-muted">A live read across the mandate &amp; governance graph.</p>

        <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatTile label="Total mandates" value={totalMandates} icon={<ClipboardList size={18} />} />
          <StatTile
            label="Overdue mandates"
            value={overdueCount}
            icon={<AlertTriangle size={18} />}
            tone={overdueCount > 0 ? 'critical' : 'good'}
          />
          <StatTile
            label="No named owner"
            value={`${noOwnerPct}%`}
            icon={<Target size={18} />}
            tone={noOwnerPct > 0 ? 'warning' : 'good'}
          />
          <StatTile label="Tracks &amp; sub-tracks created" value={createdCount} icon={<GitBranch size={18} />} />
        </div>

        <div className="mt-6 grid gap-3 lg:grid-cols-3">
          <ChartCard title="Mandate status" subtitle="Every mandate, by current status.">
            {statusSegments.length ? <StackedBar segments={statusSegments} unit=" mandates" /> : <p className="text-sm text-muted">No data.</p>}
          </ChartCard>

          <ChartCard title="Ownership accountability" subtitle="Named individual vs. no named owner.">
            {ownershipSegments.length ? <StackedBar segments={ownershipSegments} unit=" mandates" /> : <p className="text-sm text-muted">No data.</p>}
          </ChartCard>

          <ChartCard title="Institutional closure rate" subtitle="Ministries &amp; agencies, ranked by closure rate.">
            {closureRateItems.length ? <RankedBars items={closureRateItems} unit="%" /> : <p className="text-sm text-muted">No data.</p>}
          </ChartCard>
        </div>

        <div className="mt-6 grid gap-3 md:grid-cols-2">
          <ListCard title="Overdue watchlist" subtitle="Open mandates past their due date, with the owner." rows={q02}>
            {q02.map((r, i) => (
              <div key={i} className="flex items-center justify-between gap-3 border-b border-hairline/60 py-2 last:border-0">
                <div className="min-w-0">
                  <p className="truncate text-sm text-ink" dir="auto" title={str(r.directive)}>
                    {str(r.mandate)} — {str(r.directive)}
                  </p>
                  <p className="truncate text-xs text-muted" dir="auto">
                    {str(r.owner)} · {str(r.owner_type)}
                  </p>
                </div>
                <span className="shrink-0 rounded-full bg-danger/10 px-2 py-0.5 text-xs font-medium text-danger">
                  {num(r.days_overdue)}d overdue
                </span>
              </div>
            ))}
          </ListCard>

          <ListCard title="Decisions becoming delivery" subtitle="Tracks &amp; sub-tracks created by a mandate." rows={q11}>
            {q11.map((r, i) => (
              <div key={i} className="flex items-start gap-3 border-b border-hairline/60 py-2 last:border-0">
                <span className="mt-0.5 shrink-0 rounded-full bg-accent-soft px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-accent">
                  {str(r.created)}
                </span>
                <div className="min-w-0">
                  <p className="truncate text-sm text-ink" dir="auto" title={str(r.delivery_unit)}>
                    {str(r.delivery_unit)}
                  </p>
                  <p className="truncate text-xs text-muted" dir="auto">
                    from {str(r.from_mandate)} · {str(r.committee)}
                  </p>
                </div>
              </div>
            ))}
          </ListCard>
        </div>

        {extraLive.length > 0 && (
          <div className="mt-6 grid gap-3 md:grid-cols-2">
            {extraLive.map((t) => (
              <LiveTile key={t.id} tile={t} />
            ))}
          </div>
        )}

        {shortcuts.length > 0 && (
          <>
            <h3 className="mb-3 mt-8 text-[11px] font-semibold uppercase tracking-wider text-muted">
              Pick a track, mandate, or person to see
            </h3>
            <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
              {shortcuts.map((t) => (
                <ShortcutTile key={t.id} tile={t} onOpenFilter={onOpenFilter} />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
