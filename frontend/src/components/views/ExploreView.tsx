import { useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { BrainCircuit, Workflow } from 'lucide-react'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { cn } from '../../lib/cn'
import { BrainView } from './BrainView'
import { SchemaView } from './SchemaView'

type Lens = 'graph' | 'schema'

export function ExploreView() {
  const [lens, setLens] = useState<Lens>('graph')
  const { t } = useLanguage()

  const lenses: { key: Lens; label: string; icon: typeof BrainCircuit; hint: string }[] = [
    { key: 'graph', label: t('explore.graph'), icon: BrainCircuit, hint: t('explore.graphHint') },
    { key: 'schema', label: t('explore.schema'), icon: Workflow, hint: t('explore.schemaHint') },
  ]

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 justify-center border-b border-border bg-card px-4 py-2.5">
        <div className="inline-flex gap-0.5 rounded-lg border border-border bg-background p-0.5 text-sm">
          {lenses.map(({ key, label, icon: Icon, hint }) => (
            <button
              key={key}
              onClick={() => setLens(key)}
              title={hint}
              className={cn(
                'relative inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 font-medium transition-colors',
                lens === key ? 'text-primary-foreground' : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {lens === key && (
                <motion.span
                  layoutId="explore-lens"
                  className="absolute inset-0 rounded-md bg-primary"
                  transition={{ type: 'spring', stiffness: 400, damping: 32 }}
                />
              )}
              <Icon size={15} className="relative z-10" />
              <span className="relative z-10">{label}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={lens}
            className="h-full"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15, ease: 'easeOut' }}
          >
            {lens === 'graph' && <BrainView />}
            {lens === 'schema' && <SchemaView />}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  )
}
