import { Fragment, type ReactNode } from 'react'

// A minimal Cypher tokenizer + highlighter - hand-rolled rather than pulling in Shiki/Prism (a
// full language grammar + theme bundle) for one code block. Colors ride our own design tokens so
// it matches the app instead of a generic highlight.js theme.
const KEYWORDS = new Set([
  'CYPHER', 'MATCH', 'OPTIONAL', 'WHERE', 'RETURN', 'WITH', 'ORDER', 'BY', 'LIMIT', 'SKIP',
  'CREATE', 'MERGE', 'DELETE', 'DETACH', 'SET', 'REMOVE', 'UNWIND', 'CALL', 'YIELD', 'AS',
  'AND', 'OR', 'XOR', 'NOT', 'IN', 'IS', 'NULL', 'DISTINCT', 'CASE', 'WHEN', 'THEN', 'ELSE',
  'END', 'ASC', 'DESC', 'ON', 'FOREACH', 'UNION', 'ALL', 'EXISTS', 'COUNT',
])

// Named groups, tried in order: line comment, quoted string, $parameter, number, word, punctuation, whitespace
const TOKEN_RE =
  /(\/\/[^\n]*)|('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")|(\$\w+)|(\b\d+\.?\d*\b)|([A-Za-z_][A-Za-z0-9_]*)|([^\sA-Za-z0-9_'"$]+)|(\s+)/g

export function CypherCode({ code }: { code: string }) {
  const nodes: ReactNode[] = []
  let key = 0
  let match: RegExpExecArray | null
  TOKEN_RE.lastIndex = 0
  while ((match = TOKEN_RE.exec(code))) {
    const [, comment, str, param, num, word, punct, ws] = match
    if (comment) {
      nodes.push(<span key={key++} className="italic text-muted">{comment}</span>)
    } else if (str) {
      nodes.push(<span key={key++} style={{ color: 'var(--node-incident)' }}>{str}</span>)
    } else if (param || num) {
      nodes.push(<span key={key++} style={{ color: 'var(--node-category)' }}>{param ?? num}</span>)
    } else if (word) {
      nodes.push(
        KEYWORDS.has(word.toUpperCase()) ? (
          <span key={key++} className="font-semibold text-accent">{word}</span>
        ) : (
          <Fragment key={key++}>{word}</Fragment>
        ),
      )
    } else if (punct) {
      nodes.push(<span key={key++} className="text-muted">{punct}</span>)
    } else if (ws) {
      nodes.push(<Fragment key={key++}>{ws}</Fragment>)
    }
  }
  return <>{nodes}</>
}
