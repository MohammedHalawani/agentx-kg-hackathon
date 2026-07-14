import { describe, expect, it } from 'vitest'
import { fireEvent, render } from '@testing-library/react'
import { AreaChart } from './AreaChart'

const DATA = [
  { label: 'Jan', value: 10 },
  { label: 'Feb', value: 40 },
  { label: 'Mar', value: 25 },
]

// Regression guard: hovering a point is the only way to read its exact value (the axis only labels
// first/mid/last); before this, hovering did nothing at all.
describe('AreaChart hover', () => {
  it('shows no value tag until a point is hovered', () => {
    const { container } = render(<AreaChart data={DATA} />)
    expect(container.querySelector('rect[rx="4"]')).toBeNull()
  })

  it('shows the exact label and value when a point is hovered', () => {
    const { container } = render(<AreaChart data={DATA} />)
    const hitTargets = container.querySelectorAll('circle[r="10"]')
    expect(hitTargets).toHaveLength(3)
    fireEvent.mouseEnter(hitTargets[1])
    const tag = [...container.querySelectorAll('text')].find((t) => t.textContent?.includes('Feb: 40'))
    expect(tag).toBeTruthy()
  })

  it('hides the tag again on mouse leave', () => {
    const { container } = render(<AreaChart data={DATA} />)
    const hitTargets = container.querySelectorAll('circle[r="10"]')
    fireEvent.mouseEnter(hitTargets[0])
    fireEvent.mouseLeave(hitTargets[0])
    expect(container.querySelector('rect[rx="4"]')).toBeNull()
  })
})
