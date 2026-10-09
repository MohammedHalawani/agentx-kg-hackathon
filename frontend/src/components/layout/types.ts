export type ViewKey = 'intake' | 'decisions' | 'explore' | 'audit' | 'simulation'

export const VIEW_TITLES: Record<ViewKey, string> = {
  intake: 'Intake',
  decisions: 'Decisions',
  explore: 'Explore',
  audit: 'Audit',
  simulation: 'Simulation (development)',
}
