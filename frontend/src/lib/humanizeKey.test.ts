import { describe, expect, it } from 'vitest'
import { humanizeKey } from './humanizeKey'

// Regression guard: the node-detail panel used to show raw DB property names verbatim
// ("municipality_id: 302") - a premium app humanizes the label, not just the value.
describe('humanizeKey', () => {
  it('strips a trailing _id or _key suffix', () => {
    expect(humanizeKey('municipality_id')).toBe('Municipality')
    expect(humanizeKey('incident_key')).toBe('Incident')
  })

  it('title-cases multi-word snake_case properties', () => {
    expect(humanizeKey('first_seen')).toBe('First Seen')
  })

  it('leaves a single lowercase word capitalized', () => {
    expect(humanizeKey('name')).toBe('Name')
  })
})
