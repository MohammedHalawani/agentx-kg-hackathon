import { motion } from 'motion/react'
import { Compass, LayoutDashboard, MessageSquare, SlidersHorizontal } from 'lucide-react'
import { cn } from '../../lib/cn'

export type ViewKey = 'chat' | 'dashboard' | 'filter' | 'explore'

const NAV: { key: ViewKey; label: string; icon: typeof MessageSquare }[] = [
  { key: 'chat', label: 'Chat', icon: MessageSquare },
  { key: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { key: 'filter', label: 'Filter', icon: SlidersHorizontal },
  { key: 'explore', label: 'Explore', icon: Compass },
]

// Slim icon rail that switches the main surface between the chat and the standalone graph views.
export function AppNav({ active, onSelect }: { active: ViewKey; onSelect: (v: ViewKey) => void }) {
  return (
    <nav className="flex w-16 shrink-0 flex-col items-center gap-1 border-r border-hairline bg-panel py-3">
      {NAV.map(({ key, label, icon: Icon }) => (
        <motion.button
          key={key}
          onClick={() => onSelect(key)}
          aria-label={label}
          aria-current={active === key}
          whileHover={{ scale: 1.06 }}
          whileTap={{ scale: 0.94 }}
          transition={{ type: 'spring', stiffness: 400, damping: 22 }}
          className={cn(
            'relative flex w-14 flex-col items-center gap-1 rounded-xl py-2 text-[10px] font-medium transition-colors',
            active === key ? 'text-accent' : 'text-muted hover:bg-surface hover:text-ink',
          )}
        >
          {active === key && (
            <motion.span
              layoutId="nav-active"
              className="absolute inset-0 rounded-xl bg-accent-soft"
              transition={{ type: 'spring', stiffness: 400, damping: 32 }}
            />
          )}
          <Icon size={18} className="relative z-10" />
          <span className="relative z-10">{label}</span>
        </motion.button>
      ))}
    </nav>
  )
}
