import { useEffect, useState } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import { AppShell } from './components/layout/AppShell'
import type { ViewKey } from './components/layout/types'
import { IntakeView } from './components/views/IntakeView'
import { OperationsDecisionsView } from './components/views/OperationsDecisionsView'
import { ExploreView } from './components/views/ExploreView'
import { AuditView } from './components/views/AuditView'
import type { ExploreShipment } from './types/explore'

export default function App() {
  const [scope, setScope] = useState<string>('')
  const [scopeLoading, setScopeLoading] = useState(true)
  const [view, setView] = useState<ViewKey>('intake')
  const [selectedShipment, setSelectedShipment] = useState<Pick<ExploreShipment, 'shipment_id' | 'case_id'> | null>(null)
  const reduce = useReducedMotion()

  useEffect(() => {
    fetch('/meta')
      .then((r) => r.json())
      .then((d: { scope?: string }) => setScope(d.scope ?? ''))
      .catch(() => undefined)
      .finally(() => setScopeLoading(false))
  }, [])

  return (
    <div className="h-full">
      <AppShell view={view} onViewChange={setView} scope={scope} scopeLoading={scopeLoading}>
        <motion.div
          key={view}
          className="h-full"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: reduce ? 0 : 0.15, ease: 'easeOut' }}
        >
          {view === 'intake' && <IntakeView selectedShipment={selectedShipment} onClearShipment={() => setSelectedShipment(null)} />}
          {view === 'decisions' && <OperationsDecisionsView />}
          {view === 'explore' && (
            <ExploreView
              onOpenCase={(shipment) => {
                setSelectedShipment(shipment)
                setView('intake')
              }}
            />
          )}
          {view === 'audit' && <AuditView onOpenCase={(shipmentId, caseId) => { setSelectedShipment({ shipment_id: shipmentId, case_id: caseId }); setView('intake') }} />}
        </motion.div>
      </AppShell>
    </div>
  )
}
