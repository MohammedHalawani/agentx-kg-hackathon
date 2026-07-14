import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Message } from './Message'
import type { ChatMessage } from '../../hooks/useChatStream'

// Regression guard: answers render as markdown (live during streaming), not raw text that snaps to
// formatted at the end. A `**bold**` answer must produce a <strong>, not literal asterisks.
describe('Message markdown rendering', () => {
  it('renders markdown while the message is still streaming', () => {
    const msg = { role: 'assistant', content: '**Makkah**', streaming: true } as ChatMessage
    const { container } = render(<Message message={msg} onInspect={() => {}} />)
    expect(container.querySelector('strong')?.textContent).toBe('Makkah')
    expect(container.textContent).not.toContain('**')
  })
})

describe('Message map affordance', () => {
  it('offers a Show on map chip inside the answer when incidents were mapped', () => {
    const msg = {
      role: 'assistant',
      content: 'Mapped the recurring sites.',
      artifact: { tool: 'show_on_map', incidents: [{ lat: 21.5, lon: 39.2 }, { lat: 24.7, lon: 46.7 }] },
    } as ChatMessage
    render(<Message message={msg} onInspect={() => {}} />)
    const chip = screen.getByRole('button', { name: /show on map/i })
    expect(chip.textContent).toContain('2') // carries the incident count
  })

  it('places the map button right after the sentence that mentions the map, not at the end', () => {
    const msg = {
      role: 'assistant',
      content: 'The map shows 5 recurring sites. These sites need more attention over time.',
      artifact: { tool: 'show_on_map', incidents: [{ lat: 21.5, lon: 39.2 }] },
    } as ChatMessage
    const { container } = render(<Message message={msg} onInspect={() => {}} />)
    const html = container.innerHTML
    const buttonAt = html.indexOf('aria-label="Show on map"')
    expect(buttonAt).toBeGreaterThan(html.indexOf('recurring sites.')) // after the map sentence
    expect(buttonAt).toBeLessThan(html.indexOf('These sites need')) // before the rest of the prose
  })

  it('shows no map chip when the answer has nothing to map', () => {
    const msg = {
      role: 'assistant',
      content: 'There are 37 recurring incidents.',
      artifact: { tool: 'run_cypher', incidents: [] },
    } as unknown as ChatMessage
    render(<Message message={msg} onInspect={() => {}} />)
    expect(screen.queryByRole('button', { name: /show on map/i })).toBeNull()
  })
})
