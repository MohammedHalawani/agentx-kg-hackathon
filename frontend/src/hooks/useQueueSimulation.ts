import { useEffect, useState } from 'react'
import { useFetch } from './useFetch'
import { operationsPost } from '@/lib/operationsClient'

export type SimulationSpeed = 1 | 10 | 60 | 600 | 3600
export type ReplayMode = 'timeline' | 'compressed'
export interface SimulationEvent { id: string; type: string; shipmentId: string; timestamp?: string }
export interface OperationsStatus { synthetic: boolean; as_of: string; worker: { state: string; concurrency: number; processed_count: number; active_case_id: string | null; active_shipment_id?: string | null; last_case_id?: string | null; last_shipment_id?: string | null; last_workflow_state?: string | null; last_processed_at?: string | null }; simulator: { state: string; speed: SimulationSpeed; replay_mode?: ReplayMode; event_count: number; cursor?: { time: string; id: string }; end_at?: string }; notifications: { mode: string; external_calls: number }; session?: { case_source: 'dataset' | 'monitor'; session_id: string | null; started_at: string | null; monitor_pending: number; monitor_checked: number; monitor_opened: number } }
export type SimulationStatus = OperationsStatus
export type WorkerStatus = OperationsStatus

export function useOperationsControl<T extends OperationsStatus>(kind: 'worker' | 'simulation') {
  const { data, loading, error, refetch } = useFetch<T>(`/${kind}/status`, true)
  const [pending, setPending] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  useEffect(() => { const timer = setInterval(refetch, 5000); return () => clearInterval(timer) }, [refetch])
  const command = async (action: 'start' | 'pause' | 'tick' | 'reset', body: Record<string, unknown> = {}) => {
    if (pending) return
    setPending(true); setActionError(null)
    try { await operationsPost(`/${kind}/${action}`, body); refetch() }
    catch (e) { setActionError(e instanceof Error ? e.message : 'Request failed') }
    finally { setPending(false) }
  }
  const valid = !data || (data.worker && data.simulator && typeof data.worker.state === 'string' && typeof data.simulator.state === 'string')
  return { data: valid ? data : null, loading, error: actionError ?? error ?? (valid ? null : 'Unexpected operations status'), pending, command, refetch: () => { setActionError(null); refetch() } }
}
