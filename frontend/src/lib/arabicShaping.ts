/**
 * Pre-shaping Arabic for NVL's canvas caption renderer.
 *
 * WHY THIS EXISTS. @neo4j-nvl/base draws a node caption one character at a time - it spreads
 * the caption into an array (`Array.from(text)`) so each character can carry its own
 * bold/italic/underline style, then `fillText`s each one and advances x by its measured
 * width. Canvas only shapes and bidi-orders text *within a single fillText call*, so a
 * per-character loop defeats both: every Arabic letter is drawn in its isolated form (no
 * joining) and placed left-to-right, which is why `دانة العمري` came out as disconnected
 * letters in reverse. No `direction`/`unicode-bidi` setting can fix that - there is no run
 * for the shaper to work on.
 *
 * So we hand NVL text that is already in visual order with the joined glyphs chosen for it:
 *   1. shape - map each Arabic letter to its Unicode Presentation Forms-B variant
 *      (isolated/final/initial/medial) from its neighbours' joining behaviour, and fold the
 *      four mandatory lam-alef ligatures into single code points.
 *   2. reorder - reverse each right-to-left run, and reverse the order of the runs themselves
 *      when the text's base direction is RTL, so Latin/digit runs land on the correct side.
 * Drawing that left-to-right, character by character, reproduces correct Arabic.
 *
 * This is a rendering-path workaround, so it belongs ONLY where NVL captions are built.
 * Everything else in the app draws captions as DOM text, where the browser shapes Arabic
 * correctly on its own - passing shaped text there would be wrong (it would defeat text
 * selection, search and copy, since the code points are presentation forms, not letters).
 */

// Joining behaviour of the characters we shape.
//   D = dual-joining (joins on both sides), R = right-joining (joins only to its right),
//   T = transparent (harakat: invisible to joining), U = non-joining, C = join-causing.
type Joining = 'D' | 'R' | 'T' | 'U' | 'C'

// base code point -> [isolated, final] for R, or [isolated, final, initial, medial] for D.
const FORMS: Record<number, [number, number] | [number, number, number, number]> = {
  0x0621: [0xfe80, 0xfe80], // ء  hamza (non-joining; final form never applies)
  0x0622: [0xfe81, 0xfe82], // آ
  0x0623: [0xfe83, 0xfe84], // أ
  0x0624: [0xfe85, 0xfe86], // ؤ
  0x0625: [0xfe87, 0xfe88], // إ
  0x0626: [0xfe89, 0xfe8a, 0xfe8b, 0xfe8c], // ئ
  0x0627: [0xfe8d, 0xfe8e], // ا
  0x0628: [0xfe8f, 0xfe90, 0xfe91, 0xfe92], // ب
  0x0629: [0xfe93, 0xfe94], // ة
  0x062a: [0xfe95, 0xfe96, 0xfe97, 0xfe98], // ت
  0x062b: [0xfe99, 0xfe9a, 0xfe9b, 0xfe9c], // ث
  0x062c: [0xfe9d, 0xfe9e, 0xfe9f, 0xfea0], // ج
  0x062d: [0xfea1, 0xfea2, 0xfea3, 0xfea4], // ح
  0x062e: [0xfea5, 0xfea6, 0xfea7, 0xfea8], // خ
  0x062f: [0xfea9, 0xfeaa], // د
  0x0630: [0xfeab, 0xfeac], // ذ
  0x0631: [0xfead, 0xfeae], // ر
  0x0632: [0xfeaf, 0xfeb0], // ز
  0x0633: [0xfeb1, 0xfeb2, 0xfeb3, 0xfeb4], // س
  0x0634: [0xfeb5, 0xfeb6, 0xfeb7, 0xfeb8], // ش
  0x0635: [0xfeb9, 0xfeba, 0xfebb, 0xfebc], // ص
  0x0636: [0xfebd, 0xfebe, 0xfebf, 0xfec0], // ض
  0x0637: [0xfec1, 0xfec2, 0xfec3, 0xfec4], // ط
  0x0638: [0xfec5, 0xfec6, 0xfec7, 0xfec8], // ظ
  0x0639: [0xfec9, 0xfeca, 0xfecb, 0xfecc], // ع
  0x063a: [0xfecd, 0xfece, 0xfecf, 0xfed0], // غ
  0x0641: [0xfed1, 0xfed2, 0xfed3, 0xfed4], // ف
  0x0642: [0xfed5, 0xfed6, 0xfed7, 0xfed8], // ق
  0x0643: [0xfed9, 0xfeda, 0xfedb, 0xfedc], // ك
  0x0644: [0xfedd, 0xfede, 0xfedf, 0xfee0], // ل
  0x0645: [0xfee1, 0xfee2, 0xfee3, 0xfee4], // م
  0x0646: [0xfee5, 0xfee6, 0xfee7, 0xfee8], // ن
  0x0647: [0xfee9, 0xfeea, 0xfeeb, 0xfeec], // ه
  0x0648: [0xfeed, 0xfeee], // و
  0x0649: [0xfeef, 0xfef0], // ى
  0x064a: [0xfef1, 0xfef2, 0xfef3, 0xfef4], // ي
  0x0671: [0xfb50, 0xfb51], // ٱ
  0x067e: [0xfb56, 0xfb57, 0xfb58, 0xfb59], // پ
  0x0686: [0xfb7a, 0xfb7b, 0xfb7c, 0xfb7d], // چ
  0x0698: [0xfb8a, 0xfb8b], // ژ
  0x06a9: [0xfb8e, 0xfb8f, 0xfb90, 0xfb91], // ک
  0x06af: [0xfb92, 0xfb93, 0xfb94, 0xfb95], // گ
  0x06cc: [0xfbfc, 0xfbfd, 0xfbfe, 0xfbff], // ی
}

const JOINING: Record<number, Joining> = {
  0x0621: 'U',
  0x0622: 'R',
  0x0623: 'R',
  0x0624: 'R',
  0x0625: 'R',
  0x0627: 'R',
  0x0629: 'R',
  0x062f: 'R',
  0x0630: 'R',
  0x0631: 'R',
  0x0632: 'R',
  0x0648: 'R',
  0x0649: 'R',
  0x0671: 'R',
  0x0698: 'R',
  0x0640: 'C', // ـ tatweel: joins both sides but has no forms of its own
}

// Mandatory lam-alef ligatures: [isolated, final], keyed by the alef that follows the lam.
const LAM_ALEF: Record<number, [number, number]> = {
  0x0622: [0xfef5, 0xfef6], // لآ
  0x0623: [0xfef7, 0xfef8], // لأ
  0x0625: [0xfef9, 0xfefa], // لإ
  0x0627: [0xfefb, 0xfefc], // لا
}
const LAM = 0x0644

/** Harakat and other combining marks that joining looks straight through. */
function isTransparent(cp: number): boolean {
  return (
    (cp >= 0x064b && cp <= 0x065f) || // fathatan..low marks
    cp === 0x0610 ||
    (cp >= 0x0611 && cp <= 0x061a) ||
    cp === 0x0670 || // superscript alef
    (cp >= 0x06d6 && cp <= 0x06dc) ||
    (cp >= 0x06df && cp <= 0x06e4) ||
    (cp >= 0x06e7 && cp <= 0x06e8) ||
    (cp >= 0x06ea && cp <= 0x06ed) ||
    (cp >= 0x0300 && cp <= 0x036f) // generic combining marks
  )
}

function joiningOf(cp: number): Joining {
  if (isTransparent(cp)) return 'T'
  const explicit = JOINING[cp]
  if (explicit) return explicit
  if (FORMS[cp]) return FORMS[cp].length === 4 ? 'D' : 'R'
  return 'U'
}

/** Does this code point belong to a right-to-left script? (Arabic + Hebrew blocks.) */
export function isRtlChar(cp: number): boolean {
  return (
    (cp >= 0x0590 && cp <= 0x05ff) || // Hebrew
    (cp >= 0x0600 && cp <= 0x06ff) || // Arabic
    (cp >= 0x0750 && cp <= 0x077f) || // Arabic Supplement
    (cp >= 0x08a0 && cp <= 0x08ff) || // Arabic Extended-A
    (cp >= 0xfb50 && cp <= 0xfdff) || // Arabic Presentation Forms-A
    (cp >= 0xfe70 && cp <= 0xfeff) // Arabic Presentation Forms-B
  )
}

/** Does the string contain any right-to-left character at all? */
export function hasRtl(text: string): boolean {
  for (const ch of text) {
    if (isRtlChar(ch.codePointAt(0)!)) return true
  }
  return false
}

/** A strongly left-to-right character: Latin/Greek/Cyrillic letters and ASCII digits. */
function isStrongLtr(cp: number): boolean {
  return (
    (cp >= 0x0030 && cp <= 0x0039) || // 0-9 (kept LTR inside RTL text, as bidi does)
    (cp >= 0x0041 && cp <= 0x005a) ||
    (cp >= 0x0061 && cp <= 0x007a) ||
    (cp >= 0x00c0 && cp <= 0x024f) ||
    (cp >= 0x0370 && cp <= 0x04ff)
  )
}

// Paired characters that read the other way round inside an RTL run.
const MIRRORED: Record<string, string> = {
  '(': ')',
  ')': '(',
  '[': ']',
  ']': '[',
  '{': '}',
  '}': '{',
  '<': '>',
  '>': '<',
}

/**
 * Replace every Arabic letter with the presentation form its neighbours call for, in logical
 * order. Non-Arabic characters and anything outside FORMS pass through untouched.
 */
function shapeRun(chars: string[]): string[] {
  const cps = chars.map((c) => c.codePointAt(0)!)
  // the nearest non-transparent neighbour on each side, so harakat never break a join
  const prevVisible = (i: number): number => {
    for (let j = i - 1; j >= 0; j--) if (joiningOf(cps[j]) !== 'T') return cps[j]
    return -1
  }
  const nextVisible = (i: number): number => {
    for (let j = i + 1; j < cps.length; j++) if (joiningOf(cps[j]) !== 'T') return cps[j]
    return -1
  }

  const out: string[] = []
  for (let i = 0; i < cps.length; i++) {
    const cp = cps[i]
    const forms = FORMS[cp]
    if (!forms) {
      out.push(chars[i])
      continue
    }

    const before = prevVisible(i)
    const after = nextVisible(i)
    // a letter joins leftwards when the letter before it can join to its left...
    const beforeJoins = before !== -1 && (joiningOf(before) === 'D' || joiningOf(before) === 'C')
    // ...and rightwards when the next letter can be joined from the right at all
    const afterJoins =
      after !== -1 && (joiningOf(after) === 'D' || joiningOf(after) === 'R' || joiningOf(after) === 'C')

    // lam + alef is a single glyph, not two: consume both and emit the ligature
    if (cp === LAM && after !== -1 && LAM_ALEF[after]) {
      const [iso, fin] = LAM_ALEF[after]
      out.push(String.fromCodePoint(beforeJoins ? fin : iso))
      // skip the alef (and keep any harakat between them, already emitted by their own pass)
      for (let j = i + 1; j < cps.length; j++) {
        if (joiningOf(cps[j]) === 'T') out.push(chars[j])
        else {
          i = j
          break
        }
      }
      continue
    }

    if (forms.length === 4) {
      const [iso, fin, init, med] = forms
      const form = beforeJoins ? (afterJoins ? med : fin) : afterJoins ? init : iso
      out.push(String.fromCodePoint(form))
    } else {
      const [iso, fin] = forms
      out.push(String.fromCodePoint(beforeJoins ? fin : iso))
    }
  }
  return out
}

type Run = { dir: 'rtl' | 'ltr' | 'neutral'; chars: string[] }

/** Split into runs of RTL / strong-LTR / neutral characters, in logical order. */
function splitRuns(text: string): Run[] {
  const runs: Run[] = []
  for (const ch of text) {
    const cp = ch.codePointAt(0)!
    const dir: Run['dir'] = isRtlChar(cp) ? 'rtl' : isStrongLtr(cp) ? 'ltr' : 'neutral'
    const last = runs[runs.length - 1]
    if (last && last.dir === dir) last.chars.push(ch)
    else runs.push({ dir, chars: [ch] })
  }
  // A neutral run between two runs of the same direction belongs to them (the space in
  // "دانة العمري" must travel with the Arabic, not sit between two reordered halves).
  const merged: Run[] = []
  for (let i = 0; i < runs.length; i++) {
    const run = runs[i]
    const prev = merged[merged.length - 1]
    const next = runs[i + 1]
    if (run.dir === 'neutral' && prev && next && prev.dir === next.dir && prev.dir !== 'neutral') {
      prev.chars.push(...run.chars)
      continue
    }
    if (prev && prev.dir === run.dir) {
      prev.chars.push(...run.chars)
      continue
    }
    merged.push({ dir: run.dir, chars: [...run.chars] })
  }
  return merged
}

/**
 * Turn logical-order text into the visual-order, pre-shaped string NVL's per-character canvas
 * renderer needs. Text with no RTL character is returned unchanged, so Latin captions - the
 * overwhelming majority - take an identity fast path and are byte-for-byte what they were.
 *
 * Known limit: the result is visual order, so NVL's own width-based ellipsis truncation trims
 * what is visually on the right, which for RTL text is the start of the string rather than its
 * end. Captions here are short (names, ids, cities), so this has no effect in practice.
 */
export function shapeForCanvas(text: string): string {
  if (!text || !hasRtl(text)) return text

  const runs = splitRuns(text)
  const firstStrong = runs.find((r) => r.dir !== 'neutral')
  const baseRtl = firstStrong?.dir === 'rtl'

  const rendered = runs.map((run) => {
    if (run.dir !== 'rtl') return run.chars.join('')
    const shaped = shapeRun(run.chars)
    // reverse into visual order, mirroring paired punctuation as bidi does
    return shaped
      .map((c) => MIRRORED[c] ?? c)
      .reverse()
      .join('')
  })

  return (baseRtl ? rendered.reverse() : rendered).join('')
}
