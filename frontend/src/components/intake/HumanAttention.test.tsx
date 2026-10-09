import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { LanguageProvider } from '@/components/i18n/LanguageProvider'
import { HumanAttentionRail } from './HumanAttentionRail'
import { NowProcessingPanel } from './NowProcessingPanel'

const urls: string[] = []
vi.mock('@/hooks/useFetch', () => ({
  useFetch: (url: string) => {
    urls.push(url)
    return { data: { items: [{ case_id: 'SYN-CASE-1', shipment_id: 'SYN-SHP-001241', issue_summary: 'Delivery dispute', priority: 'high', workflow_state: 'HUMAN_REVIEW', opened_at: '2026-10-07T08:00:00Z' }], filtered_total: 40, next_cursor: 'c2', previous_cursor: null, metadata: { as_of: '2026-10-08T08:00:00Z' } }, loading: false, error: null, refetch: vi.fn() }
  },
}))
const pipeline = vi.hoisted(() => ({ live: null as unknown }))
vi.mock('@/hooks/useCasePipeline', () => ({ useCasePipeline: () => ({ live: pipeline.live, unavailable: false }) }))

describe('HumanAttentionRail', () => {
  it('pages one human state at a time from the server and carries no decision controls', () => {
    const onOpen = vi.fn()
    render(<LanguageProvider><HumanAttentionRail counts={{ HUMAN_REVIEW: 40, AWAITING_APPROVAL: 3 }} refreshKey={0} onOpen={onOpen} collapsed={false} onCollapsedChange={() => {}} /></LanguageProvider>)
    expect(urls.at(-1)).toContain('workflow_state=HUMAN_REVIEW')
    expect(urls.at(-1)).toContain('limit=25')
    expect(screen.getByText('43')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Approve|Reject/ })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(urls.at(-1)).toContain('cursor=c2')
    fireEvent.click(screen.getByText('SYN-SHP-001241'))
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ caseId: 'SYN-CASE-1' }))
  })
})

describe('NowProcessingPanel', () => {
  const status = (worker: Record<string, unknown>) => ({ synthetic: true, as_of: '', simulator: { state: 'paused', speed: 1 as const, event_count: 0 }, notifications: { mode: 'dry_run', external_calls: 0 }, worker: { state: 'running', concurrency: 1, processed_count: 1, active_case_id: null, ...worker } })
  it('shows only recorded stage events of the active claim', () => {
    pipeline.live = { status: 'RUNNING', workflow_state: 'INVESTIGATING', state_version: 2, events: [
      { sequence: 1, stage: 'extract', status: 'COMPLETED', iteration: 0, recorded_at: '', evidence_as_of: '', output: {} },
      { sequence: 2, stage: 'retrieve', status: 'RUNNING', iteration: 0, recorded_at: '', evidence_as_of: '', output: {} }] }
    render(<LanguageProvider><NowProcessingPanel status={status({ active_case_id: 'SYN-CASE-9', active_shipment_id: 'SYN-SHP-000941' })} running onOpen={() => {}} /></LanguageProvider>)
    expect(screen.getByText('Now processing')).toBeTruthy()
    expect(screen.getByText('SYN-SHP-000941')).toBeTruthy()
    expect(screen.getByText('Graph').closest('li')!.className).toContain('border-primary')
    expect(screen.getByText('Diagnose').closest('li')!.className).toContain('text-muted-foreground')
  })
  it('after a run, says it was routed to a person and that the queue continues — never "solved"', () => {
    pipeline.live = { status: 'REVIEWED', workflow_state: 'HUMAN_REVIEW', state_version: 4, events: [] }
    render(<LanguageProvider><NowProcessingPanel status={status({ last_case_id: 'SYN-CASE-9', last_shipment_id: 'SYN-SHP-000941', last_workflow_state: 'HUMAN_REVIEW' })} running onOpen={() => {}} /></LanguageProvider>)
    expect(screen.getByText(/Investigation completed automatically → Human review/)).toBeTruthy()
    expect(screen.getByText(/auto-triage continues/)).toBeTruthy()
    expect(screen.queryByText(/solved|Resolved/i)).toBeNull()
  })
})
