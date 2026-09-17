import { describe, expect, it, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { LanguageProvider, useLanguage } from './LanguageProvider'

function Probe() {
  const { rootCauseLabel, entityLabel, propertyLabel } = useLanguage()
  return (
    <div>
      <span data-testid="root-cause">{rootCauseLabel('failed_attempt_barcode_mismatch')}</span>
      <span data-testid="escalated-root-cause">{rootCauseLabel('escalation:weight_mismatch')}</span>
      <span data-testid="entity">{entityLabel('Shipment')}</span>
      <span data-testid="property">{propertyLabel('municipality_id')}</span>
    </div>
  )
}

describe('LanguageProvider display maps', () => {
  beforeEach(() => {
    localStorage.setItem('agentx-language', 'en')
  })

  afterEach(() => {
    localStorage.removeItem('agentx-language')
  })

  it('maps root causes in English', () => {
    render(
      <LanguageProvider>
        <Probe />
      </LanguageProvider>,
    )
    expect(screen.getByTestId('root-cause').textContent).toBe('failed attempt barcode mismatch')
    expect(screen.getByTestId('entity').textContent).toBe('Shipment')
    expect(screen.getByTestId('property').textContent).toBe('Municipality')
  })

  it('maps root causes, entities, and properties in Arabic', () => {
    localStorage.setItem('agentx-language', 'ar')
    render(
      <LanguageProvider>
        <Probe />
      </LanguageProvider>,
    )
    expect(screen.getByTestId('root-cause').textContent).toBe('عدم تطابق الباركود')
    expect(screen.getByTestId('escalated-root-cause').textContent).toContain('(مصعّدة)')
    expect(screen.getByTestId('entity').textContent).toBe('الشحنة')
    expect(screen.getByTestId('property').textContent).toBe('البلدية')
  })
})
