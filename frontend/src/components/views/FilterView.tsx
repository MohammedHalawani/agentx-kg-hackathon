import { useEffect, useRef, useState } from 'react'
import { useFetch } from '../../hooks/useFetch'
import { cn } from '../../lib/cn'
import { TableView } from '../artifacts/TableView'
import { Skeleton } from '../ui/Skeleton'

interface ParamMeta {
  name: string
  kind: 'registry' | 'enum' | 'text'
  label?: string // registry node label, when kind === 'registry'
  options?: string[] // fixed choices, when kind === 'enum'
}

interface QueryMeta {
  id: string
  title: string
  question_en: string
  question_ar: string
  params: ParamMeta[]
}

interface RegistryOption {
  id: string
  displayName_ar?: string
  displayName_en?: string
  [k: string]: unknown
}

const controlClass =
  'rounded-md border border-hairline bg-surface px-2 py-1.5 text-sm text-ink focus:outline-none focus:ring-1 focus:ring-accent'

function optionLabel(o: RegistryOption): string {
  return o.displayName_en || o.displayName_ar || o.id
}

function EnumControl({ param, value, onChange }: { param: ParamMeta; value: string; onChange: (v: string) => void }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} className={controlClass}>
      <option value="">Any {param.name}</option>
      {(param.options ?? []).map((o) => (
        <option key={o} value={o}>{o}</option>
      ))}
    </select>
  )
}

function RegistryControl({ param, value, onChange }: { param: ParamMeta; value: string; onChange: (v: string) => void }) {
  const { data } = useFetch<{ options: RegistryOption[] }>(`/registry/${param.label}`)
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} className={controlClass}>
      <option value="">Any {param.label}</option>
      {(data?.options ?? []).map((o) => (
        <option key={o.id} value={o.id}>{optionLabel(o)}</option>
      ))}
    </select>
  )
}

function TextControl({ param, value, onChange }: { param: ParamMeta; value: string; onChange: (v: string) => void }) {
  return (
    <input
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={param.name}
      className={controlClass}
    />
  )
}

function ParamControl(props: { param: ParamMeta; value: string; onChange: (v: string) => void }) {
  if (props.param.kind === 'enum') return <EnumControl {...props} />
  if (props.param.kind === 'registry') return <RegistryControl {...props} />
  return <TextControl {...props} />
}

function QueryCard({ query, focused }: { query: QueryMeta; focused: boolean }) {
  const [values, setValues] = useState<Record<string, string>>({})
  const [rows, setRows] = useState<Record<string, unknown>[] | null>(null)
  const [loading, setLoading] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (focused) ref.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [focused])

  const run = () => {
    setLoading(true)
    const qs = query.params
      .map((p) => (values[p.name] ? `${encodeURIComponent(p.name)}=${encodeURIComponent(values[p.name])}` : null))
      .filter((v): v is string => Boolean(v))
      .join('&')
    fetch(`/filter/${query.id}${qs ? `?${qs}` : ''}`)
      .then((r) => r.json())
      .then((d: { rows?: Record<string, unknown>[] }) => setRows(d.rows ?? []))
      .catch(() => setRows([]))
      .finally(() => setLoading(false))
  }

  return (
    <section
      ref={ref}
      className={cn(
        'rounded-2xl border bg-panel p-4 transition-colors',
        focused ? 'border-accent' : 'border-hairline',
      )}
    >
      <h3 className="text-sm font-semibold text-ink">{query.title}</h3>
      <p className="mt-0.5 text-xs text-muted">{query.question_en}</p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {query.params.map((p) => (
          <ParamControl
            key={p.name}
            param={p}
            value={values[p.name] ?? ''}
            onChange={(v) => setValues((prev) => ({ ...prev, [p.name]: v }))}
          />
        ))}
        <button
          onClick={run}
          className="rounded-full bg-accent px-3 py-1.5 text-xs font-medium text-white transition-colors hover:opacity-90"
        >
          Run
        </button>
      </div>

      {rows !== null && (
        <div className="mt-3 h-64 overflow-hidden rounded-lg border border-hairline">
          {loading ? <Skeleton className="h-full w-full" /> : <TableView rows={rows} title={query.title} />}
        </div>
      )}
    </section>
  )
}

// Every query in the catalog, as a card: a plain "Run" button when it needs no input, a
// dropdown/enum/text control per param otherwise. `focusId` (set from the Dashboard's
// "Go pick one →" shortcut tiles) scrolls that one card into view and highlights it.
export function FilterView({ focusId }: { focusId?: string | null }) {
  const { data, loading } = useFetch<{ queries: QueryMeta[] }>('/filter/catalog')

  if (loading) {
    return (
      <div className="h-full overflow-y-auto px-6 py-8">
        <div className="mx-auto w-full max-w-4xl space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-40" />
          ))}
        </div>
      </div>
    )
  }

  const queries = data?.queries ?? []

  return (
    <div className="h-full overflow-y-auto px-6 py-8">
      <div className="mx-auto w-full max-w-4xl">
        <h2 className="font-display text-2xl font-bold tracking-tight text-ink">Filter</h2>
        <p className="mt-1 text-sm text-muted">Browse the graph directly — pick a value, run the query.</p>
        <div className="mt-6 space-y-3">
          {queries.map((q) => (
            <QueryCard key={q.id} query={q} focused={q.id === focusId} />
          ))}
        </div>
      </div>
    </div>
  )
}
