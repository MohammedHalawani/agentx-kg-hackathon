import { useCallback, useEffect, useRef, useState } from 'react'

// Minimal GET hook for the read-only feature views. No caching/retry — these endpoints are cheap
// and the views mount on demand. Aborts the in-flight request on unmount or refetch so a slow
// response can't set state late. `refetch()` re-runs the same GET (e.g. a "load a different
// random sample" button on an endpoint that returns something new each call).
export function useFetch<T>(url: string): { data: T | null; loading: boolean; refetch: () => void } {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [tick, setTick] = useState(0)
  const ctrlRef = useRef<AbortController | null>(null)

  useEffect(() => {
    const ctrl = new AbortController()
    ctrlRef.current = ctrl
    setLoading(true)
    fetch(url, { signal: ctrl.signal })
      .then((r) => r.json())
      .then((d: T) => {
        setData(d)
        setLoading(false)
      })
      .catch(() => {
        if (!ctrl.signal.aborted) setLoading(false)
      })
    return () => ctrl.abort()
  }, [url, tick])

  const refetch = useCallback(() => {
    ctrlRef.current?.abort()
    setTick((t) => t + 1)
  }, [])

  return { data, loading, refetch }
}
