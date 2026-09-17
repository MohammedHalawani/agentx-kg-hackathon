import { Map as MapIcon, Network } from 'lucide-react'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { Graph } from '../artifacts/Graph'
import { ShipmentMap } from './ShipmentMap'
import type { CaseFile as CaseFileData } from '../../types/agent'

function Panel({
  title,
  hint,
  icon,
  children,
}: {
  title: string
  hint: string
  icon: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-hairline bg-panel">
      <header className="flex shrink-0 items-center gap-2 border-b border-hairline px-3 py-2">
        <span className="text-accent">{icon}</span>
        <h3 className="text-xs font-semibold text-ink">{title}</h3>
        <span className="truncate text-[11px] text-muted-foreground">{hint}</span>
      </header>
      <div className="min-h-0 flex-1">{children}</div>
    </section>
  )
}

// The evidence pane: the shipment's own graph above, the same journey as a map below. Shown
// for every run, not only escalations - on an escalation it is what a human inherits instead
// of a bare sentence, and on an execution it is how someone checks the decision against the
// shipment it was made about.
export function CaseFile({ data }: { data: CaseFileData }) {
  const { t } = useLanguage()
  const graph = data.graph
  const route = data.route
  const shipment = graph?.nodes.find((n) => n.labels.includes('Shipment'))
  const pinCount = (route?.points.length ?? 0) + (route?.origin ? 1 : 0)
  // Two delivery pins means the recorded address and the actual one disagree - the
  // address-conflict case, visible as distance rather than as a category name.
  const conflicting = (route?.points.length ?? 0) > 1

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      {graph && graph.nodes.length > 0 && (
        <Panel
          title={
            shipment
              ? t('intake.caseFile.titleWithShipment', { caption: shipment.caption })
              : t('intake.caseFile.title')
          }
          hint={t('intake.caseFile.nodesLinks', {
            nodes: graph.nodes.length,
            links: graph.relationships.length,
          })}
          icon={<Network size={14} />}
        >
          <Graph graph={graph} />
        </Panel>
      )}

      {route && pinCount > 0 && (
        <Panel
          title={t('intake.caseFile.journey')}
          hint={
            conflicting
              ? t('intake.caseFile.conflictingAddresses')
              : t('intake.caseFile.locationCount', { count: pinCount })
          }
          icon={<MapIcon size={14} />}
        >
          <ShipmentMap origin={route.origin} points={route.points} />
        </Panel>
      )}
    </div>
  )
}
