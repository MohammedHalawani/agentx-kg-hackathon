import { useState, type ReactNode } from 'react'
import * as RD from '@radix-ui/react-dialog'
import { AnimatePresence, motion } from 'motion/react'
import { Map as MapIcon, Maximize2, Network, X } from 'lucide-react'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { Graph } from '../artifacts/Graph'
import { ShipmentMap } from './ShipmentMap'
import type { CaseFile as CaseFileData } from '../../types/agent'

interface PanelProps {
  title: string
  hint: string
  icon: ReactNode
  children: ReactNode
}

/**
 * One evidence panel, with a full-screen view of the same content behind its expand button.
 *
 * `children` is rendered in whichever of the two is showing - never both at once. The graph
 * and the map size themselves from their container, so a second live copy behind a modal
 * would mean two layouts running against two different boxes; mounting one at a time lets
 * the expanded view lay out for the space it actually has (and keeps one NVL instance).
 */
function Panel({ title, hint, icon, children }: PanelProps) {
  const { t } = useLanguage()
  const [full, setFull] = useState(false)

  const header = (
    <>
      <span className="text-accent">{icon}</span>
      <h3 className="text-xs font-semibold text-ink">{title}</h3>
      <span className="truncate text-[11px] text-muted-foreground">{hint}</span>
    </>
  )

  return (
    <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-hairline bg-panel">
      <header className="flex shrink-0 items-center gap-2 border-b border-hairline px-3 py-2">
        {header}
        <button
          onClick={() => setFull(true)}
          aria-label={t('intake.caseFile.expand')}
          title={t('intake.caseFile.expand')}
          className="ml-auto shrink-0 rounded-md p-1 text-muted-foreground transition-colors hover:bg-surface hover:text-ink"
        >
          <Maximize2 size={13} />
        </button>
      </header>
      <div className="min-h-0 flex-1">{!full && children}</div>

      {/* Same scale-and-fade as the chat's MapModal, so expanding any pane feels the same. */}
      <RD.Root open={full} onOpenChange={setFull}>
        <AnimatePresence>
          {full && (
            <RD.Portal forceMount>
              <RD.Overlay asChild forceMount>
                <motion.div
                  className="fixed inset-0 z-[1100] bg-ink/30 backdrop-blur-sm"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.15 }}
                />
              </RD.Overlay>
              <RD.Content asChild forceMount aria-describedby={undefined}>
                <motion.div
                  className="fixed inset-4 z-[1110] flex flex-col rounded-2xl border border-hairline bg-surface p-4 shadow-2xl focus:outline-none md:inset-8"
                  initial={{ opacity: 0, scale: 0.97 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.98 }}
                  transition={{ duration: 0.2, ease: 'easeOut' }}
                >
                  <div className="mb-2 flex items-center gap-2">
                    <RD.Title asChild>
                      <div className="flex min-w-0 items-center gap-2">{header}</div>
                    </RD.Title>
                    <RD.Close
                      aria-label={t('intake.caseFile.collapse')}
                      title={t('intake.caseFile.collapse')}
                      className="ml-auto shrink-0 rounded-md p-1 text-muted-foreground transition-colors hover:bg-panel hover:text-ink"
                    >
                      <X size={18} />
                    </RD.Close>
                  </div>
                  <div className="min-h-0 flex-1 overflow-hidden rounded-xl border border-hairline">
                    {children}
                  </div>
                </motion.div>
              </RD.Content>
            </RD.Portal>
          )}
        </AnimatePresence>
      </RD.Root>
    </section>
  )
}

// The evidence pane: the shipment's own graph above, the same journey as a map below. Shown
// for every run, not only escalations - on an escalation it is what a human inherits instead
// of a bare sentence, and on an execution it is how someone checks the decision against the
// shipment it was made about. Either panel expands to full screen: the case-file pane is a
// third of the width, which is enough to see the shape of the graph but not to read it.
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
