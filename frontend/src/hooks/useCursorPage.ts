import { useState } from 'react'

// Store only visited opaque cursors; every page still comes from the server.
export function useCursorPage() {
  const [cursor, setCursorState] = useState<string | null>(null)
  const [history, setHistory] = useState<(string | null)[]>([])
  const [offset, setOffset] = useState(0)
  const reset = () => { setCursorState(null); setHistory([]); setOffset(0) }
  const next = (value: string | null | undefined, limit: number) => {
    if (!value) return
    setHistory(h => [...h, cursor]); setCursorState(value); setOffset(n => n + limit)
  }
  const previous = (limit: number) => {
    if (!history.length) return
    setCursorState(history[history.length - 1]); setHistory(h => h.slice(0, -1)); setOffset(n => Math.max(0, n - limit))
  }
  return { cursor, offset, hasPrevious: history.length > 0, reset, next, previous }
}
