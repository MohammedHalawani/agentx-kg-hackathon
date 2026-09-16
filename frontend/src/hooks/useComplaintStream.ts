import { useCallback, useRef, useState } from 'react'
import type { FinalResult, Stage } from '../types/agent'

// Drives one complaint through POST /complaint and collects the stage trace as it streams.
// Deliberately separate from useChatStream: that one accumulates free text token by token,
// this one accumulates whole stages, and the AFL loop means a stage can legitimately arrive
// twice (same `stage`, higher `loop`) - so stages are appended, never keyed and replaced.
export function useComplaintStream() {
  const [stages, setStages] = useState<Stage[]>([])
  const [final, setFinal] = useState<FinalResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [complaint, setComplaint] = useState('')
  const ctrlRef = useRef<AbortController | null>(null)

  const stop = useCallback(() => {
    ctrlRef.current?.abort()
    ctrlRef.current = null
    setBusy(false)
  }, [])

  const run = useCallback(async (text: string) => {
    ctrlRef.current?.abort()
    const ctrl = new AbortController()
    ctrlRef.current = ctrl
    setStages([])
    setFinal(null)
    setError(null)
    setComplaint(text)
    setBusy(true)

    try {
      const res = await fetch('/complaint', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
        signal: ctrl.signal,
      })
      if (!res.ok || !res.body) {
        await res.body?.cancel()
        setError(`Request failed (${res.status})`)
        setBusy(false)
        return
      }
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const frames = buffer.split('\n\n')
        buffer = frames.pop() ?? '' // keep the trailing partial frame for the next read
        for (const frame of frames) {
          let event = 'message'
          const data: string[] = []
          for (const line of frame.split('\n')) {
            if (line.startsWith('event:')) event = line.slice(6).trim()
            else if (line.startsWith('data:')) data.push(line.slice(5).trim())
          }
          if (!data.length) continue
          let payload: unknown
          try {
            payload = JSON.parse(data.join('\n'))
          } catch {
            continue // skip a malformed frame rather than killing the read loop
          }
          if (event === 'stage') setStages((prev) => [...prev, payload as Stage])
          else if (event === 'final') setFinal(payload as FinalResult)
          else if (event === 'error') setError((payload as { message?: string }).message ?? 'stream error')
        }
      }
    } catch (e) {
      if ((e as Error).name !== 'AbortError') setError('The pipeline stream was interrupted.')
    } finally {
      setBusy(false)
      ctrlRef.current = null
    }
  }, [])

  return { stages, final, busy, error, complaint, run, stop }
}
