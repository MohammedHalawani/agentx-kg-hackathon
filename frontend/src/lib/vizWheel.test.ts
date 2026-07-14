import { describe, expect, it } from 'vitest'
import { shouldZoomViz } from './vizWheel'

// Regression guard: the inline graph/map must stay zoomable (a plain wheel scrolls the chat; a
// Ctrl/⌘-wheel or trackpad pinch zooms the viz). This broke once when a blanket wheel-swallow
// disabled zooming entirely.
describe('shouldZoomViz', () => {
  it('does NOT zoom on a plain wheel (so the page scrolls)', () => {
    expect(shouldZoomViz({ ctrlKey: false, metaKey: false })).toBe(false)
  })

  it('zooms on Ctrl-wheel / trackpad pinch', () => {
    expect(shouldZoomViz({ ctrlKey: true, metaKey: false })).toBe(true)
  })

  it('zooms on ⌘-wheel', () => {
    expect(shouldZoomViz({ ctrlKey: false, metaKey: true })).toBe(true)
  })
})
