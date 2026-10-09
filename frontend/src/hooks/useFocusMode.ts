import { useState } from 'react'

export type FocusMode = 'balanced' | 'map' | 'graph'
/** 'auto' follows the active investigation stage; the others are the operator's manual choice. */
export type FocusChoice = FocusMode | 'auto'
const FOCUS_KEY = 'suhail.caseFocus'

/** The operator's focus for this browser session; defaults to Auto (follow the live stage). */
export function useFocusMode(): [FocusChoice, (mode: FocusChoice) => void] {
  const [mode, setMode] = useState<FocusChoice>(() => {
    try { const v = sessionStorage.getItem(FOCUS_KEY); return v === 'balanced' || v === 'map' || v === 'graph' || v === 'auto' ? v : 'auto' } catch { return 'auto' }
  })
  return [mode, (next: FocusChoice) => { setMode(next); try { sessionStorage.setItem(FOCUS_KEY, next) } catch { /* storage unavailable */ } }]
}
