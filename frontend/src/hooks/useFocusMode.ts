import { useState } from 'react'

export type FocusMode = 'balanced' | 'map' | 'graph'
const FOCUS_KEY = 'suhail.caseFocus'

/** The operator's explicit focus for this browser session; null means "not chosen yet". */
export function useFocusMode(): [FocusMode | null, (mode: FocusMode) => void] {
  const [mode, setMode] = useState<FocusMode | null>(() => {
    try { const v = sessionStorage.getItem(FOCUS_KEY); return v === 'balanced' || v === 'map' || v === 'graph' ? v : null } catch { return null }
  })
  return [mode, (next: FocusMode) => { setMode(next); try { sessionStorage.setItem(FOCUS_KEY, next) } catch { /* storage unavailable */ } }]
}
