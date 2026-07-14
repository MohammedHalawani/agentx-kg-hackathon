import type { ReactNode } from 'react'
import type { Artifact, TraceStep } from '../../types/contract'
import { CypherCode } from './CypherCode'
import { Dialog } from '../ui/Dialog'

function parseTrace(trace?: string | null): TraceStep[] {
  if (!trace) return []
  try {
    const parsed: unknown = JSON.parse(trace)
    return Array.isArray(parsed) ? (parsed as TraceStep[]) : []
  } catch {
    return []
  }
}

const Tag = ({ children, title }: { children: ReactNode; title?: string }) => (
  <span title={title} className={`rounded-full border border-hairline px-2 py-0.5${title ? ' cursor-help' : ''}`}>
    {children}
  </span>
)

const Section = ({ title, children }: { title: string; children: ReactNode }) => (
  <div>
    <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">{title}</h3>
    {children}
  </div>
)

interface InspectModalProps {
  artifact: Artifact | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

// The whole point of the redesign: the dev internals (how the answer was produced) live
// one click away, never cluttering the thread.
export function InspectModal({ artifact, open, onOpenChange }: InspectModalProps) {
  if (!artifact) return null
  const steps = parseTrace(artifact.trace)
  const t = artifact.timing ?? {}

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="How this was answered">
      <div className="space-y-5 text-sm">
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
          {artifact.tool && <Tag title="The agent tool that produced this answer.">tool · {artifact.tool}</Tag>}
          {typeof artifact.confidence === 'number' && (
            <Tag title="The agent's self-reported confidence in this answer, from 0 to 1.">
              confidence · {artifact.confidence.toFixed(2)}
            </Tag>
          )}
          {typeof t.total_ms === 'number' && <Tag title="Total wall-clock time to produce this answer.">{t.total_ms} ms total</Tag>}
          {typeof t.agent_llm_ms === 'number' && <Tag title="Time spent in language-model calls.">{t.agent_llm_ms} ms in model calls</Tag>}
          {typeof t.db_ms === 'number' && <Tag title="Time spent running queries in the Neo4j database.">{t.db_ms} ms in Neo4j</Tag>}
          {typeof t.llm_tokens === 'number' && t.llm_tokens > 0 && (
            <Tag title="Approximate language-model tokens used for this answer.">≈{t.llm_tokens.toLocaleString()} tokens</Tag>
          )}
        </div>

        {artifact.reason && (
          <Section title="Confidence reason">
            <p className="text-ink">{artifact.reason}</p>
          </Section>
        )}

        {steps.length > 0 && (
          <Section title="Tool calls">
            <p className="mb-1.5 text-xs text-muted">The steps the agent took to answer, in order.</p>
            <ol className="space-y-1.5">
              {steps.map((s, i) => (
                <li key={i} className="rounded-lg border border-hairline bg-surface px-3 py-2">
                  <span className="font-medium text-ink">{s.tool}</span>
                  <pre className="mt-1 overflow-x-auto font-mono text-xs text-muted">
                    {JSON.stringify(s.args, null, 2)}
                  </pre>
                </li>
              ))}
            </ol>
          </Section>
        )}

        {artifact.cypher && (
          <Section title="Generated Cypher">
            <p className="mb-1.5 text-xs text-muted">
              Cypher is Neo4j's query language - the database query the agent wrote and ran to get this answer.
            </p>
            {typeof artifact.repairs === 'number' && artifact.repairs > 0 && (
              <p className="mb-1 text-xs text-muted">
                self-corrected after {artifact.repairs} failed attempt(s)
              </p>
            )}
            <pre className="overflow-x-auto whitespace-pre-wrap rounded-lg border border-hairline bg-surface px-3 py-2 font-mono text-xs leading-relaxed text-ink">
              <CypherCode code={artifact.cypher} />
            </pre>
          </Section>
        )}
      </div>
    </Dialog>
  )
}
