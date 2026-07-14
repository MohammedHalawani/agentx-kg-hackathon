import { useFetch } from '../../hooks/useFetch'
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

function LiveTile({ tile }: { tile: Tile }) {
  return (
    <section className="flex h-72 flex-col rounded-2xl border border-hairline bg-panel p-4">
      <h3 className="text-sm font-semibold text-ink">{tile.title}</h3>
      <p className="mb-2 text-xs text-muted">{tile.question}</p>
      <div className="min-h-0 flex-1 overflow-hidden rounded-lg border border-hairline">
        <TableView rows={tile.rows ?? []} />
      </div>
    </section>
  )
}

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

// Every query from the catalog shows up here: the param-free ones load real numbers on
// mount, the ones that need a track/mandate/etc. picked first show a shortcut into the
// Filter tab instead of a live tile — see backend main.py:/dashboard.
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

  const tiles = data?.tiles ?? []
  const live = tiles.filter((t) => t.live)
  const shortcuts = tiles.filter((t) => !t.live)

  return (
    <div className="h-full overflow-y-auto px-6 py-8">
      <div className="mx-auto w-full max-w-6xl">
        <h2 className="font-display text-2xl font-bold tracking-tight text-ink">Dashboard</h2>
        <p className="mt-1 text-sm text-muted">A live read across the mandate &amp; governance graph.</p>

        <div className="mt-6 grid gap-3 md:grid-cols-2">
          {live.map((t) => (
            <LiveTile key={t.id} tile={t} />
          ))}
        </div>

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
