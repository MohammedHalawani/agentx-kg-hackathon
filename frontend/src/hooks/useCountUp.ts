import { useEffect, useState } from 'react'
import { useReducedMotion } from 'motion/react'

// Ease a number from 0 up to `target` on mount (ease-out cubic). Used for the Dashboard KPIs so it
// feels alive on load. Honours the OS "reduce motion" setting by showing the value flat.
export function useCountUp(target: number, durationMs = 900): number {
  const reduce = useReducedMotion()
  const [value, setValue] = useState(reduce ? target : 0)

  useEffect(() => {
    if (reduce) {
      setValue(target)
      return
    }
    let raf = 0
    let startTs = 0
    const tick = (ts: number) => {
      if (!startTs) startTs = ts
      const p = Math.min(1, (ts - startTs) / durationMs)
      setValue(target * (1 - Math.pow(1 - p, 3)))
      if (p < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [target, durationMs, reduce])

  return value
}
