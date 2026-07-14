import * as RD from '@radix-ui/react-dialog'
import { AnimatePresence, motion } from 'motion/react'
import { X } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '../../lib/cn'

interface DialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: ReactNode
  children: ReactNode
}

// Radix Dialog gives focus-trap + Esc-to-close + scroll-lock for free (the a11y baseline).
// `forceMount` + AnimatePresence lets the overlay/content animate OUT (Radix normally unmounts
// immediately on close, which skips exit transitions) - the modal scales up and fades in/out
// instead of snapping onto the screen.
export function Dialog({ open, onOpenChange, title, children }: DialogProps) {
  return (
    <RD.Root open={open} onOpenChange={onOpenChange}>
      <AnimatePresence>
        {open && (
          <RD.Portal forceMount>
            {/* z above Leaflet's panes/controls (which go up to z-index 1000) so the map can't cover the modal */}
            <RD.Overlay asChild forceMount>
              <motion.div
                className="fixed inset-0 z-[1100] bg-ink/25 backdrop-blur-[2px]"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
              />
            </RD.Overlay>
            <RD.Content asChild forceMount>
              <motion.div
                className={cn(
                  'fixed left-1/2 top-1/2 z-[1110] w-[min(46rem,92vw)] max-h-[85vh] -translate-x-1/2 -translate-y-1/2',
                  'overflow-y-auto rounded-2xl border border-hairline bg-panel p-6 shadow-2xl focus:outline-none',
                )}
                initial={{ opacity: 0, scale: 0.96, y: 6 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.97, y: 4 }}
                transition={{ duration: 0.18, ease: 'easeOut' }}
              >
                <div className="mb-4 flex items-center justify-between gap-4">
                  <RD.Title className="font-display text-lg font-bold text-ink">{title}</RD.Title>
                  <RD.Close
                    aria-label="Close"
                    className="rounded-md p-1 text-muted transition-colors hover:bg-surface hover:text-ink"
                  >
                    <X size={18} />
                  </RD.Close>
                </div>
                {children}
              </motion.div>
            </RD.Content>
          </RD.Portal>
        )}
      </AnimatePresence>
    </RD.Root>
  )
}
