import { useCountUp } from '../../hooks/useCountUp'

// Counts up to `value` on mount. `decimals > 0` keeps a fixed precision (e.g. a ratio); otherwise
// it renders a rounded, thousands-separated integer. tabular-nums keeps the width from jittering.
export function AnimatedNumber({ value, decimals = 0 }: { value: number; decimals?: number }) {
  const v = useCountUp(value)
  const shown = decimals > 0 ? v.toFixed(decimals) : Math.round(v).toLocaleString()
  return <span className="tabular-nums">{shown}</span>
}
