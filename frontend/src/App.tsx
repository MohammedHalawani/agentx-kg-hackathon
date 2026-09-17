import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { AppShell } from './components/layout/AppShell'
import type { ViewKey } from './components/layout/types'
import { IntakeView } from './components/views/IntakeView'
import { DecisionsView } from './components/views/DecisionsView'
import { ExploreView } from './components/views/ExploreView'

export default function App() {
  const [scope, setScope] = useState<string>('')
  const [view, setView] = useState<ViewKey>('intake')

  useEffect(() => {
    fetch('/meta')
      .then((r) => r.json())
      .then((d: { scope?: string }) => setScope(d.scope ?? ''))
      .catch(() => undefined)
  }, [])

  return (
    <div className="h-full">
      <AppShell view={view} onViewChange={setView} scope={scope}>
        <motion.div
          key={view}
          className="h-full"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.15, ease: 'easeOut' }}
        >
          {view === 'intake' && <IntakeView />}
          {view === 'decisions' && <DecisionsView />}
          {view === 'explore' && <ExploreView />}
        </motion.div>
      </AppShell>
    </div>
  )
}
