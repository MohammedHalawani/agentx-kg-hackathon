import { useOperationsPage } from './useOperationsPage'
import { pageQuery } from '@/adapters/operationsApi'
import type { ExploreData, ExploreShipment, ShipmentFilter } from '@/types/explore'
import type { RoutePoint } from '@/types/agent'
import type { CaseWorkflowState, OperationalShipmentStatus } from '@/contracts/operations'

interface ApiExploreShipment {
  shipment_id: string; status: string; operational_status?: OperationalShipmentStatus; city?: string; cause_codes?: string[]
  priority?: string; case_id?: string; workflow_state?: CaseWorkflowState; origin?: RoutePoint | null; destination?: RoutePoint | null
  risk_watch?: { latest_estimate_at?: string; promise_at?: string; certainty?: string } | null
}
export function useExploreData(filter: ShipmentFilter, limit: number, cursor: string | null = null, filters: Record<string, string> = {}) {
  const { data: response, loading, error, refetch } = useOperationsPage<ApiExploreShipment>(`/explore?${pageQuery({ filter, limit, cursor, ...filters })}`)
  const shipments: ExploreShipment[] = (response?.items ?? []).map(s => ({ ...s, workflow_state: s.workflow_state ?? null, priority: s.priority ?? null, operational_status: s.operational_status, root_causes: s.cause_codes ?? [], needs_attention: Boolean(s.case_id && s.workflow_state !== 'RESOLVED'), stalled: s.operational_status === 'HUB_DELAY', critical: s.operational_status === 'CRITICAL', delivered: s.status === 'DELIVERED', origin: s.origin ?? null, destinations: s.destination ? [s.destination] : [], last_event: null }))
  const data: ExploreData | null = response ? { shipments, counts: {}, filter, limit, total: response.filtered_total, returned: shipments.length, truncated: Boolean(response.next_cursor), graph: { nodes: shipments.map(s => ({ id: s.shipment_id, labels: ['Shipment'], caption: s.shipment_id, properties: { status: s.status, operational_status: s.operational_status ?? '' } })), relationships: [] }, next_cursor: response.next_cursor, previous_cursor: response.previous_cursor, metadata: response.metadata } : null
  return { data, loading, error, refetch }
}
