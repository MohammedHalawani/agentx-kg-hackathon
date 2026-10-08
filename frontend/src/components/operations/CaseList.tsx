import type { OperationsCase } from '@/contracts/operations'
import { CaseCard } from './CaseCard'
import { EmptyState } from './EmptyState'

export function CaseList({
  cases,
  onSelect,
  selectedId,
  emptyTitle,
  emptyDescription,
}: {
  cases: OperationsCase[]
  onSelect: (caseRow: OperationsCase) => void
  selectedId?: string | null
  emptyTitle: string
  emptyDescription: string
}) {
  if (!cases.length) {
    return <EmptyState title={emptyTitle} description={emptyDescription} />
  }
  return (
    <ul className="space-y-2" role="list">
      {cases.map((c) => (
        <li key={c.caseId}>
          <CaseCard caseRow={c} onSelect={() => onSelect(c)} selected={selectedId === c.caseId} />
        </li>
      ))}
    </ul>
  )
}
