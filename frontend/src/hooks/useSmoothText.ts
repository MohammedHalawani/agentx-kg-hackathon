import { useEffect, useRef, useState } from 'react'
import { useReducedMotion } from 'motion/react'

// Reveal `target` steadily instead of in network-sized bursts. SSE delivers tokens in clumps; each
// animation frame here closes a fraction of the remaining gap (min a couple of chars), so the text
// reads as a smooth stream and the reveal lands just after the final token. Snaps when the target
// stops being a prefix of what's shown (a reused component now holding a different message), and
// respects the OS "reduce motion" setting by showing the full text immediately.
export function useSmoothText(target: string): { text: string; revealing: boolean } {
  const reduce = useReducedMotion()
  const [shown, setShown] = useState(target)
  const shownRef = useRef(target)

  useEffect(() => {
    if (reduce || !target.startsWith(shownRef.current)) {
      shownRef.current = target
      setShown(target)
      return
    }
    let raf = 0
    const tick = () => {
      const cur = shownRef.current
      if (cur.length >= target.length) return
      const step = Math.max(2, Math.round((target.length - cur.length) * 0.2))
      shownRef.current = target.slice(0, cur.length + step)
      setShown(shownRef.current)
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [target, reduce])

  return { text: reduce ? target : shown, revealing: !reduce && shown.length < target.length }
}
