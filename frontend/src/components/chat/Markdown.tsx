import type { ComponentPropsWithoutRef, ReactNode } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

// A slot injected into the source as inline code so it renders INSIDE the prose (in the sentence
// flow, not as a block underneath). Swapped for the `trailing` element at render time.
const TRAILING_SLOT = '⟦kg-inline⟧'

// Put the slot where it fits: right after the first sentence that talks about the map, so the
// button sits next to the claim it backs up ("The map shows 37 sites. [Map] These are..."). Falls
// back to the end of the first sentence, then the end of the text.
function injectSlot(md: string): string {
  const at = /[^.!?\n]*\bmap(?:ped|s)?\b[^.!?\n]*[.!?]/i.exec(md) ?? /[^.!?\n]{10,}[.!?]/.exec(md)
  if (at) {
    const cut = at.index + at[0].length
    return `${md.slice(0, cut)} \`${TRAILING_SLOT}\`${md.slice(cut)}`
  }
  return `${md} \`${TRAILING_SLOT}\``
}

// Render assistant answers as markdown, styled from the design tokens (no prose plugin). Covers the
// structure the agent actually emits — paragraphs, lists, bold, inline code, links, the odd table.
const COMPONENTS: Components = {
  p: (props) => <p className="mb-2 last:mb-0" {...props} />,
  ul: (props) => <ul className="mb-2 list-disc space-y-1 pl-5 last:mb-0" {...props} />,
  ol: (props) => <ol className="mb-2 list-decimal space-y-1 pl-5 last:mb-0" {...props} />,
  li: (props) => <li className="marker:text-muted" {...props} />,
  strong: (props) => <strong className="font-semibold text-ink" {...props} />,
  a: (props) => (
    <a
      className="text-accent underline underline-offset-2 hover:opacity-80"
      target="_blank"
      rel="noopener noreferrer"
      {...props}
    />
  ),
  pre: (props) => (
    <pre className="mb-2 overflow-x-auto rounded-lg border border-hairline bg-surface p-3 font-mono text-xs last:mb-0" {...props} />
  ),
  table: (props) => (
    <div className="mb-2 overflow-x-auto last:mb-0">
      <table className="w-full border-collapse text-xs" {...props} />
    </div>
  ),
  th: (props) => <th className="border border-hairline bg-surface px-2 py-1 text-left font-semibold" {...props} />,
  td: (props) => <td className="border border-hairline px-2 py-1" {...props} />,
  h1: (props) => <h1 className="mb-2 mt-1 font-display text-lg font-semibold tracking-tight text-ink" {...props} />,
  h2: (props) => <h2 className="mb-1.5 mt-2 font-display text-base font-semibold text-ink" {...props} />,
  h3: (props) => <h3 className="mb-1 mt-1.5 text-sm font-semibold text-ink" {...props} />,
}

// `trailing` (when set) is an inline element woven into the answer's prose (after the sentence that
// mentions the map) — used for the "Show on map" affordance so it reads as part of the text.
export function Markdown({ children, trailing }: { children: string; trailing?: ReactNode }) {
  const source = trailing ? injectSlot(children) : children
  const components: Components = {
    ...COMPONENTS,
    code: ({ className, children: content, ...props }: ComponentPropsWithoutRef<'code'>) => {
      if (trailing && String(content) === TRAILING_SLOT) return <>{trailing}</>
      return className?.includes('language-') ? (
        <code className={className} {...props}>
          {content}
        </code>
      ) : (
        <code className="rounded bg-surface px-1 py-0.5 font-mono text-[0.85em] text-ink" {...props}>
          {content}
        </code>
      )
    },
  }
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
      {source}
    </ReactMarkdown>
  )
}
