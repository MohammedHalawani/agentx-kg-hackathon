import { useEffect, useRef, useState } from 'react'
import * as RD from '@radix-ui/react-dialog'
import { AnimatePresence, motion } from 'motion/react'
import { X } from 'lucide-react'
import type { Artifact } from '../../types/contract'
import { shouldZoomViz } from '../../lib/vizWheel'
import { ArtifactRenderer } from './ArtifactRenderer'

// The artifact, filling its container (the side panel in the split-pane layout). An Expand control
// opens the same content in a near-fullscreen overlay for detail work.
export function ArtifactCard({ artifact }: { artifact: Artifact }) {
  const [expanded, setExpanded] = useState(false)
  const cardRef = useRef<HTMLDivElement>(null)

  // The inline graph/map canvases grab the wheel to zoom, which would trap page scrolling. Swallow a
  // PLAIN wheel in the capture phase so the chat scrolls normally; let a Ctrl/⌘-wheel or trackpad
  // pinch through so the viz still zooms in place. stopPropagation (not preventDefault) keeps native
  // scrolling intact; drag/hover/click always work.
  useEffect(() => {
    const el = cardRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      if (!shouldZoomViz(e)) e.stopPropagation()
    }
    el.addEventListener('wheel', onWheel, { capture: true, passive: true })
    return () => el.removeEventListener('wheel', onWheel, { capture: true })
  }, [])

  return (
    <>
      <div ref={cardRef} className="relative h-full">
        <ArtifactRenderer artifact={artifact} onExpand={() => setExpanded(true)} />
        <span className="pointer-events-none absolute bottom-2 left-2 z-[500] rounded bg-panel/70 px-1.5 py-0.5 text-[10px] text-muted backdrop-blur">
          ⌘/Ctrl-scroll or pinch to zoom
        </span>
      </div>

      <RD.Root open={expanded} onOpenChange={setExpanded}>
        <AnimatePresence>
          {expanded && (
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
                    <RD.Title className="font-display text-sm font-bold text-ink">Visualization</RD.Title>
                    <RD.Close
                      aria-label="Close"
                      className="rounded-md p-1 text-muted transition-colors hover:bg-panel hover:text-ink"
                    >
                      <X size={18} />
                    </RD.Close>
                  </div>
                  <div className="min-h-0 flex-1">
                    <ArtifactRenderer artifact={artifact} />
                  </div>
                </motion.div>
              </RD.Content>
            </RD.Portal>
          )}
        </AnimatePresence>
      </RD.Root>
    </>
  )
}
