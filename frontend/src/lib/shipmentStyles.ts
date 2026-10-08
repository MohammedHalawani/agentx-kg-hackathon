import { AlertTriangle, CheckCircle2, Clock3, Package } from 'lucide-react'

export const SHIPMENT_STATE_STYLE = {
  critical: { Icon: AlertTriangle, className: 'text-danger', token: '--color-danger', glyph: '!' },
  stalled: { Icon: Clock3, className: 'text-chart-warning', token: '--color-chart-warning', glyph: 'Ⅱ' },
  delivered: { Icon: CheckCircle2, className: 'text-chart-good', token: '--color-chart-good', glyph: '✓' },
  normal: { Icon: Package, className: 'text-chart-blue', token: '--color-chart-blue', glyph: '□' },
}
