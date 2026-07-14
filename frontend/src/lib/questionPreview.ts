// Trim a sample question to a compact one-line pill label: full if short, else cut at a word
// boundary (past 20 chars) with an ellipsis, trailing punctuation stripped.
export const preview = (q: string, max = 40): string => {
  if (q.length <= max) return q
  const cut = q.slice(0, max)
  const sp = cut.lastIndexOf(' ')
  return `${(sp > 20 ? cut.slice(0, sp) : cut).replace(/[\s,;:—-]+$/, '')}…`
}
