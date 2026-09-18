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

// The stylesheet keys its Arabic text handling off <html lang> (see index.css:
// :root[lang='ar'] sets unicode-bidi: plaintext), and deliberately does NOT mirror the
// frame. Both halves of that contract are asserted here, because breaking either one is
// invisible in a component test and obvious only on screen.
describe('document language attributes', () => {
  afterEach(() => {
    localStorage.removeItem('agentx-language')
    document.documentElement.lang = ''
    document.documentElement.dir = ''
  })

  it('marks the document Arabic so text blocks take their own direction', () => {
    localStorage.setItem('agentx-language', 'ar')
    render(
      <LanguageProvider>
        <span />
      </LanguageProvider>,
    )
    expect(document.documentElement.lang).toBe('ar')
  })

  it('keeps the frame left-to-right in Arabic', () => {
    localStorage.setItem('agentx-language', 'ar')
    render(
      <LanguageProvider>
        <span />
      </LanguageProvider>,
    )
    expect(document.documentElement.dir).toBe('ltr')
  })

  it('marks the document English when English is selected', () => {
    localStorage.setItem('agentx-language', 'en')
    render(
      <LanguageProvider>
        <span />
      </LanguageProvider>,
    )
    expect(document.documentElement.lang).toBe('en')
  })
})

