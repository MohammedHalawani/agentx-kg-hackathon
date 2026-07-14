import { useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

const GAP = 6 // px between the trigger and the tooltip
const MARGIN = 8 // px kept clear of the viewport edge

// A hover/focus tooltip that reliably shows its text (the native `title` attribute is delayed and,
// in some webviews, never renders). Rendered via a portal into <body> with fixed positioning
// computed from the trigger's real bounding rect - unlike a plain absolutely-positioned span, this
// can't be clipped by an ancestor's `overflow` (the chat thread's scroll container, an artifact
// panel, etc.) or hidden by an unrelated stacking context. Flips below only if there's no room above.
export function Tooltip({ label, children }: { label: string; children: ReactNode }) {
  const triggerRef = useRef<HTMLSpanElement>(null)
  const [pos, setPos] = useState<{ top: number; left: number; above: boolean } | null>(null)

  const show = () => {
    const rect = triggerRef.current?.getBoundingClientRect()
    if (!rect) return
    const above = rect.top > 60 // enough room for the bubble + gap above the trigger
    setPos({
      left: Math.min(Math.max(rect.left + rect.width / 2, MARGIN + 120), window.innerWidth - MARGIN - 120),
      top: above ? rect.top - GAP : rect.bottom + GAP,
      above,
    })
  }
  const hide = () => setPos(null)

  return (
    <span ref={triggerRef} className="relative inline-flex" onMouseEnter={show} onMouseLeave={hide} onFocus={show} onBlur={hide}>
      {children}
      {pos &&
        createPortal(
          <span
            role="tooltip"
            style={{ left: pos.left, top: pos.top, transform: `translate(-50%, ${pos.above ? '-100%' : '0'})` }}
            className="pointer-events-none fixed z-[1200] w-max max-w-[15rem] rounded-md bg-ink px-2 py-1 text-[11px] font-normal leading-snug text-surface shadow-lg"
          >
            {label}
          </span>,
          document.body,
        )}
    </span>
  )
}
