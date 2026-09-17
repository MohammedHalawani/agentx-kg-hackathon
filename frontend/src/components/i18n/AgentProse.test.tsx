import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { __resetTranslationCache } from '@/lib/translate'
import { LanguageProvider } from './LanguageProvider'
import { AgentProse } from './AgentProse'

const ENGLISH =
  'Both the customer complaint and the recorded_failure entry explicitly state that delivery ' +
  'failed due to a weight mismatch on SHP-1042, matching 3 precedents at 87% success.'
const ARABIC = 'يذكر كل من شكوى العميل والسجل أن التسليم فشل بسبب عدم تطابق الوزن في SHP-1042 بنسبة 87%.'

function mockTranslate() {
  const fetchMock = vi.fn(async () => ({
    ok: true,
    json: async () => ({ texts: [ARABIC] }),
  }))
  vi.stubGlobal('fetch', fetchMock as unknown as typeof fetch)
  return fetchMock
}

describe('AgentProse (display-only translation)', () => {
  beforeEach(() => __resetTranslationCache())
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.removeItem('agentx-language')
  })

  it('renders the agent output verbatim in English and never calls the backend', () => {
    localStorage.setItem('agentx-language', 'en')
    const fetchMock = mockTranslate()
    render(
      <LanguageProvider>
        <AgentProse text={ENGLISH} />
      </LanguageProvider>,
    )
    expect(screen.getByText(ENGLISH)).toBeTruthy()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('shows the Arabic translation when the interface is Arabic', async () => {
    localStorage.setItem('agentx-language', 'ar')
    mockTranslate()
    render(
      <LanguageProvider>
        <AgentProse text={ENGLISH} />
      </LanguageProvider>,
    )
    // the agent's own words show first - never a blank or a spinner
    expect(screen.getByText(ENGLISH)).toBeTruthy()
    await waitFor(() => expect(screen.getByText(ARABIC)).toBeTruthy())
  })

  it('sends the source text unchanged, asking only for a translation', async () => {
    localStorage.setItem('agentx-language', 'ar')
    const fetchMock = mockTranslate()
    render(
      <LanguageProvider>
        <AgentProse text={ENGLISH} />
      </LanguageProvider>,
    )
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    const [, init] = (fetchMock as unknown as { mock: { calls: [string, RequestInit][] } }).mock.calls[0]
    expect(JSON.parse(String(init.body))).toEqual({ texts: [ENGLISH], target: 'ar' })
  })

  it('translates one string once, however many times it is rendered', async () => {
    localStorage.setItem('agentx-language', 'ar')
    const fetchMock = mockTranslate()
    const { unmount } = render(
      <LanguageProvider>
        <AgentProse text={ENGLISH} />
      </LanguageProvider>,
    )
    await waitFor(() => expect(screen.getByText(ARABIC)).toBeTruthy())
    unmount()

    render(
      <LanguageProvider>
        <AgentProse text={ENGLISH} />
      </LanguageProvider>,
    )
    // straight from cache: Arabic on the first paint, no second request
    expect(screen.getByText(ARABIC)).toBeTruthy()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('keeps showing the agent output if translation fails', async () => {
    localStorage.setItem('agentx-language', 'ar')
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 503, json: async () => ({}) })) as unknown as typeof fetch)
    render(
      <LanguageProvider>
        <AgentProse text={ENGLISH} />
      </LanguageProvider>,
    )
    await waitFor(() => expect(screen.getByText(ENGLISH)).toBeTruthy())
  })

  it('coalesces several rationales rendered together into one request', async () => {
    localStorage.setItem('agentx-language', 'ar')
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(String(init.body)) as { texts: string[] }
      return { ok: true, json: async () => ({ texts: body.texts.map((t) => `ar:${t}`) }) }
    })
    vi.stubGlobal('fetch', fetchMock as unknown as typeof fetch)

    render(
      <LanguageProvider>
        <AgentProse text="classification rationale" />
        <AgentProse text="recommendation rationale" />
      </LanguageProvider>,
    )
    await waitFor(() => expect(screen.getByText('ar:classification rationale')).toBeTruthy())
    expect(screen.getByText('ar:recommendation rationale')).toBeTruthy()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
