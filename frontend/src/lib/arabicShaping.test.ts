import { describe, expect, it } from 'vitest'
import { hasRtl, shapeForCanvas } from './arabicShaping'

// Presentation forms are easier to assert by code point than by eye.
const cps = (s: string) => [...s].map((c) => c.codePointAt(0)!.toString(16).padStart(4, '0'))

describe('hasRtl', () => {
  it('detects Arabic', () => expect(hasRtl('دانة العمري')).toBe(true))
  it('is false for Latin, digits and punctuation', () =>
    expect(hasRtl('SHP-1042 (Riyadh)')).toBe(false))
})

describe('shapeForCanvas', () => {
  it('leaves text with no RTL character exactly as it was', () => {
    for (const s of ['Shipment SHP-1042', 'address_conflict', '', '92%', 'Ali Al-Otaibi']) {
      expect(shapeForCanvas(s)).toBe(s)
    }
  })

  it('shapes and reverses the node caption from the bug report', () => {
    // دانة العمري -> visual order, joined forms:
    //   ي(iso) ر(final) م(medial) ع(medial) ل(initial) ا(iso) _ ة(final) ن(initial) ا(iso) د(iso)
    expect(cps(shapeForCanvas('دانة العمري'))).toEqual([
      'fef1', 'feae', 'fee4', 'fecc', 'fedf', 'fe8d', '0020', 'fe94', 'fee7', 'fe8d', 'fea9',
    ])
  })

  it('picks the four joining forms from context', () => {
    // بب -> initial + final; ببب -> initial + medial + final; ب alone -> isolated
    expect(cps(shapeForCanvas('ب'))).toEqual(['fe8f'])
    expect(cps(shapeForCanvas('بب'))).toEqual(['fe90', 'fe91'])
    expect(cps(shapeForCanvas('ببب'))).toEqual(['fe90', 'fe92', 'fe91'])
  })

  it('does not join after a right-joining letter', () => {
    // د never joins to what follows it, so the alef in "دا" stays isolated
    expect(cps(shapeForCanvas('دا'))).toEqual(['fe8d', 'fea9'])
  })

  it('folds lam-alef into its single ligature glyph', () => {
    // لا on its own is one code point (isolated ligature), not two letters
    expect(cps(shapeForCanvas('لا'))).toEqual(['fefb'])
    // preceded by a joining letter it takes the final ligature, after a medial beh
    expect(cps(shapeForCanvas('بلا'))).toEqual(['fefc', 'fe91'])
  })

  it('looks through harakat when choosing a form', () => {
    // fatha between two letters must not break the join: ب stays initial
    const out = shapeForCanvas('بَب')
    expect(cps(out)).toEqual(['fe90', '064e', 'fe91'])
  })

  it('keeps an embedded Latin/digit run readable and on the correct side', () => {
    // base direction is RTL, so the id run sits to the LEFT of the Arabic
    const out = shapeForCanvas('الشحنة SHP-1042')
    expect(out.startsWith('SHP-1042')).toBe(true)
    expect(hasRtl(out)).toBe(true)
  })

  it('keeps base-LTR text in order and only reverses the Arabic inside it', () => {
    const out = shapeForCanvas('Customer دانة')
    expect(out.startsWith('Customer ')).toBe(true)
    expect(cps(out.slice('Customer '.length))).toEqual(['fe94', 'fee7', 'fe8d', 'fea9'])
  })

  it('mirrors paired punctuation inside an RTL run', () => {
    expect(shapeForCanvas('(دانة)').endsWith('(')).toBe(true)
  })

  it('is idempotent enough to be safe if applied twice', () => {
    // already-shaped text contains no unshaped letters left to change, only re-reversal -
    // so a double application must not corrupt the glyphs, just the order
    const once = shapeForCanvas('دانة العمري')
    const twice = shapeForCanvas(once)
    expect([...twice].sort().join('')).toBe([...once].sort().join(''))
  })
})
