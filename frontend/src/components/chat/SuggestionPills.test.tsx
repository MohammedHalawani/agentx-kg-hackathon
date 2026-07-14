import { describe, expect, it } from 'vitest'
import { preview } from '../../lib/questionPreview'

// Guards the starter-pill label truncation: descriptive but compact, never mid-word garbage.
describe('preview', () => {
  it('returns short questions (<= 40 chars) unchanged', () => {
    expect(preview('Map all recorded pollution incidents')).toBe('Map all recorded pollution incidents')
  })

  it('truncates a long question at a word boundary with an ellipsis', () => {
    const out = preview('How did the investor-purchase share in Makkah change across 2023-2025?')
    expect(out.endsWith('…')).toBe(true)
    expect(out.length).toBeLessThanOrEqual(41) // 40 cap + the ellipsis
    expect(out).not.toContain(' …') // trailing space/punctuation stripped before the ellipsis
    expect(out.startsWith('How did the investor')).toBe(true)
  })
})
