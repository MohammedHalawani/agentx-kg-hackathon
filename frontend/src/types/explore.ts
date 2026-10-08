import type { RoutePoint } from './agent'
import type { SubGraph } from './contract'

export type ShipmentFilter = 'needs_attention' | 'all' | 'stalled' | 'critical' | 'delivered'
export const SHIPMENT_FILTERS: ShipmentFilter[] = ['needs_attention', 'critical', 'stalled', 'delivered', 'all']

export interface ExploreShipment {
  shipment_id: string
  tracking_id?: string
  status: string
  priority: string | null
  root_causes: string[]
  needs_attention: boolean
  stalled: boolean
  critical: boolean
  delivered: boolean
  last_event: { event_type: string; timestamp: string | null } | null
  origin: RoutePoint | null
  destinations: RoutePoint[]
  city?: string | null
  courier?: string | null
}

export interface ExploreData {
  shipments: ExploreShipment[]
  counts: Record<ShipmentFilter, number>
  filter: ShipmentFilter
  limit: number
  total: number
  returned: number
  truncated: boolean
  graph: SubGraph
}

// These are presentation semantics for backend-derived classifications, never new diagnoses.
export function shipmentVisualState(shipment: ExploreShipment): 'critical' | 'stalled' | 'delivered' | 'normal' {
  if (shipment.critical) return 'critical'
  if (shipment.delivered) return 'delivered'
  if (shipment.stalled || shipment.needs_attention) return 'stalled'
  return 'normal'
}
