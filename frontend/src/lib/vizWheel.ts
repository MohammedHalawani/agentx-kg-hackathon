// An inline graph/map lives inside the scrolling chat. A plain wheel should scroll the page, not get
// trapped zooming the viz; a modifier (Ctrl/⌘) or a trackpad pinch (which the browser reports as a
// ctrl-wheel) should zoom. This returns true when the wheel is meant to zoom and should reach the viz.
export const shouldZoomViz = (e: Pick<WheelEvent, 'ctrlKey' | 'metaKey'>): boolean =>
  e.ctrlKey || e.metaKey
