import { useCallback, useEffect, useState } from 'react'

// Entity descriptions come from the backend (/meta, sourced from the ontology) - NOT hardcoded here -
// so the UI carries no domain knowledge and adapts to whatever labels the ontology defines. Cached at
// module scope so the many GraphView instances (inline cards + Explore) share a single fetch.
let cache: Record<string, string> | null = null
let inflight: Promise<Record<string, string>> | null = null

export function loadLabels(): Promise<Record<string, string>> {
  if (cache) return Promise.resolve(cache)
  inflight ??= fetch('/meta')
    .then((r) => {
      if (!r.ok) throw new Error(`/meta ${r.status}`)
      return r.json()
    })
    .then((d: { labels?: Record<string, string> }) => (cache = d.labels ?? {}))
    .catch(() => {
      // a transient failure must NOT poison the cache - reset so a later mount retries rather than
      // leaving every tooltip blank for the rest of the session.
      inflight = null
      return {}
    })
  return inflight
}

// A stable lookup fn: label -> description. Undefined until /meta resolves, and for unknown labels -
// callers render no tooltip, so nothing breaks when the ontology grows.
export function useEntityInfo(): (label: string) => string | undefined {
  const [labels, setLabels] = useState<Record<string, string>>(cache ?? {})
  useEffect(() => {
    let live = true
    void loadLabels().then((m) => {
      if (live) setLabels(m)
    })
    return () => {
      live = false
    }
  }, [])
  return useCallback((label: string) => labels[label], [labels])
}
