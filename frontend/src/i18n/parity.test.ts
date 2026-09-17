import { describe, expect, it } from 'vitest'
import { ar } from './ar'
import { en } from './en'

function leafPaths(obj: Record<string, unknown>, prefix = ''): string[] {
  const paths: string[] = []
  for (const [key, value] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${key}` : key
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      paths.push(...leafPaths(value as Record<string, unknown>, path))
    } else {
      paths.push(path)
    }
  }
  return paths
}

describe('dictionary parity (EN ↔ AR)', () => {
  it('has the same leaf keys in both locales', () => {
    const enPaths = leafPaths(en as unknown as Record<string, unknown>).sort()
    const arPaths = leafPaths(ar as unknown as Record<string, unknown>).sort()
    expect(arPaths).toEqual(enPaths)
  })
})
