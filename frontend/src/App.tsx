import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { BrainCircuit } from 'lucide-react'
import { AppNav, type ViewKey } from './components/chat/AppNav'
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
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-hairline bg-panel px-6 py-3">
        <BrainCircuit className="shrink-0 text-accent" size={20} />
        <h1 className="font-display text-lg font-bold tracking-tight text-ink">Shipment Complaint Resolution</h1>
        {scope && <span className="text-xs text-muted">{scope}</span>}
      </header>

      <div className="flex min-h-0 flex-1">
        <AppNav active={view} onSelect={setView} />
        <main className="min-h-0 flex-1 overflow-hidden">
          <motion.div
            key={view}
            className="h-full"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
          >
            {view === 'intake' && <IntakeView />}
            {view === 'decisions' && <DecisionsView />}
            {view === 'explore' && <ExploreView />}
          </motion.div>
        </main>
      </div>
    </div>
  )
}
