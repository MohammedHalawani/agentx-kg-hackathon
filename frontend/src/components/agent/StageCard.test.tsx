import { describe, expect, it, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { LanguageProvider } from '@/components/i18n/LanguageProvider'
import { StageCard } from './StageCard'
import type { Stage } from '../../types/agent'

const classifyStage: Stage = {
  stage: 'classify',
  label: 'Classify root cause',
  lane: 'Classification',
  arabic: 'تصنيف',
  is_agent: true,
  loop: 0,
  detail: {
    category: 'address_conflict',
    confidence: 0.92,
    priority: 'high',
    rationale: 'Address mismatch detected',
  },
}

describe('StageCard i18n (I04)', () => {
  beforeEach(() => {
    localStorage.setItem('agentx-language', 'ar')
  })

  afterEach(() => {
    localStorage.removeItem('agentx-language')
  })

  it('renders translated field labels and root cause in Arabic', () => {
    render(
      <LanguageProvider>
        <ul>
          <StageCard stage={classifyStage} index={0} />
        </ul>
      </LanguageProvider>,
    )

    expect(screen.getByText('الفئة')).toBeTruthy()
    expect(screen.getByText('الثقة')).toBeTruthy()
    expect(screen.getByText('الأولوية')).toBeTruthy()
    expect(screen.getByText('تعارض في العنوان')).toBeTruthy()
    expect(screen.queryByText('Category')).toBeNull()
    expect(screen.queryByText('Verdict')).toBeNull()
  })
})
