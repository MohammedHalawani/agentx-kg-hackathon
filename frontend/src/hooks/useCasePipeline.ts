import { useEffect, useRef, useState } from 'react'
import type { PipelineEvent } from '@/contracts/caseDetail'

export function useCasePipeline(caseId: string | undefined, refetch: () => void, stateVersion?: number) {
  const [live, setLive] = useState<{ events: PipelineEvent[]; status:string; workflow_state:string; state_version:number } | null>(null)
  const [unavailable, setUnavailable] = useState(false)
  const version = useRef<number | undefined>(undefined)
  const refreshedVersion = useRef<number | undefined>(undefined)
  useEffect(() => {
    if (live && stateVersion != null && live.state_version > stateVersion && refreshedVersion.current !== live.state_version) {
      refreshedVersion.current = live.state_version
      refetch()
    }
  }, [live, stateVersion, refetch])
  useEffect(() => {
    setLive(null); version.current = undefined; refreshedVersion.current = undefined; setUnavailable(false)
    if (!caseId || typeof EventSource === 'undefined') return
    const stream = new EventSource(`/cases/${encodeURIComponent(caseId)}/events`)
    stream.addEventListener('pipeline', event => {
      try {
        const value = JSON.parse((event as MessageEvent).data)
        if (!Array.isArray(value.events) || typeof value.state_version !== 'number') throw new Error()
        setLive(value); setUnavailable(false)
        if (version.current != null && version.current !== value.state_version) { refreshedVersion.current = value.state_version; refetch() }
        version.current = value.state_version
      } catch { setUnavailable(true) }
    })
    stream.addEventListener('unavailable', () => setUnavailable(true))
    stream.onerror = () => setUnavailable(true)
    return () => stream.close()
  }, [caseId, refetch])
  return { live, unavailable }
}
