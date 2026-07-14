import * as RD from '@radix-ui/react-dialog'
import { AnimatePresence, motion } from 'motion/react'
import { X } from 'lucide-react'
import type { Incident } from '../../types/contract'
import { MapView } from './MapView'

interface MapModalProps {
  incidents: Incident[]
  open: boolean
  onOpenChange: (open: boolean) => void
}

// The answer's mapped points (incidents, track-status visits, or any other located result) on a
// near-fullscreen map, opened from the "Show on map" chip inside the answer - one click to the
// spatial view without hunting for the plate's Map tab. Scales up and fades in/out (forceMount +
// AnimatePresence) rather than snapping onto the screen.
export function MapModal({ incidents, open, onOpenChange }: MapModalProps) {
  return (
    <RD.Root open={open} onOpenChange={onOpenChange}>
      <AnimatePresence>
        {open && (
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
                <div className="mb-2 flex items-center justify-between">
                  <RD.Title className="font-mono text-[11px] font-semibold uppercase tracking-[0.14em] text-ink tabular-nums">
                    Map · {incidents.length} {incidents.length === 1 ? 'location' : 'locations'}
                  </RD.Title>
                  <RD.Close
                    aria-label="Close"
                    className="rounded-md p-1 text-muted transition-colors hover:bg-panel hover:text-ink"
                  >
                    <X size={18} />
                  </RD.Close>
                </div>
                <div className="min-h-0 flex-1 overflow-hidden rounded-xl border border-hairline">
                  <MapView incidents={incidents} />
                </div>
              </motion.div>
            </RD.Content>
          </RD.Portal>
        )}
      </AnimatePresence>
    </RD.Root>
  )
}
