import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import { CypherCode } from './CypherCode'

describe('CypherCode', () => {
  it('preserves the exact text content regardless of highlighting', () => {
    const code = "CYPHER 25\nMATCH (i:Incident) WHERE i.category = 'graffiti' RETURN i LIMIT 25"
    const { container } = render(<CypherCode code={code} />)
    expect(container.textContent).toBe(code)
  })

  it('highlights keywords distinctly from identifiers', () => {
    const { container } = render(<CypherCode code="MATCH (n) RETURN n" />)
    const keywordSpans = [...container.querySelectorAll('span.text-accent')].map((s) => s.textContent)
    expect(keywordSpans).toEqual(['MATCH', 'RETURN'])
  })

  it('colors string literals and $parameters differently from plain identifiers', () => {
    const { container } = render(<CypherCode code="MATCH (n {name: $name}) RETURN 'ok'" />)
    const colored = [...container.querySelectorAll('span[style]')].map((s) => s.textContent)
    expect(colored).toContain('$name')
    expect(colored).toContain("'ok'")
  })

  it('renders a line comment in muted italic', () => {
    const { container } = render(<CypherCode code={'// a note\nRETURN 1'} />)
    const comment = container.querySelector('span.italic')
    expect(comment?.textContent).toBe('// a note')
  })
})
