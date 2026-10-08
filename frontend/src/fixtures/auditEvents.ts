import type { AuditEvent } from '@/contracts/operations'

/** Demo-only audit rows until Dataset V2 exposes `/audit`. */
export const FIXTURE_AUDIT_EVENTS: AuditEvent[] = [
  {
    id: 'fx-1',
    timestamp: '2026-10-08T08:12:04Z',
    shipmentId: 'SHP-0142',
    caseId: 'FAIL-0142',
    eventType: 'exception_opened',
    actor: 'system',
    fixture: true,
  },
  {
    id: 'fx-2',
    timestamp: '2026-10-08T08:12:18Z',
    shipmentId: 'SHP-0142',
    eventType: 'investigation_started',
    actor: 'suhail.intake',
    model: 'gpt-oss-20b',
    fixture: true,
  },
  {
    id: 'fx-3',
    timestamp: '2026-10-08T08:13:02Z',
    shipmentId: 'SHP-0142',
    eventType: 'recommendation_ready',
    actor: 'suhail.recommend',
    decision: 'Reattempt delivery with corrected gate code',
    fixture: true,
  },
]
