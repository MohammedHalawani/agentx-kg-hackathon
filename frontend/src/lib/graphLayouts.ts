// Shared between GraphView (the canvas) and ArtifactRenderer (the control bar that can drive it) -
// kept out of a component file so exporting it doesn't break Fast Refresh.
export const LAYOUTS = [
  { key: 'forceDirected', label: 'Force', hint: 'Physics layout: connected nodes pull together into clusters.' },
  { key: 'hierarchical', label: 'Tree', hint: 'Hierarchical layout: arranges the nodes top-down by connection.' },
] as const
export type LayoutKey = (typeof LAYOUTS)[number]['key']
