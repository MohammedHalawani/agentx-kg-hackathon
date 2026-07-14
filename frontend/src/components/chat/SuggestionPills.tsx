import { motion } from 'motion/react'
import type { SampleGroup } from '../../types/contract'
import { preview } from '../../lib/questionPreview'

// One quick-start per dataset, taken from the backend's ontology-derived samples (same source as the
// Examples menu, so nothing is hardcoded). Show the real question - trimmed to a compact preview so a
// chip stays one short line - with the full question on hover and sent on click.

export function SuggestionPills({
  groups,
  onPick,
}: {
  groups: SampleGroup[]
  onPick: (question: string) => void
}) {
  const starters = groups
    .filter((g) => g.questions.length > 0)
    .map((g) => g.questions[0])
  if (!starters.length) return null

  return (
    <motion.div
      className="flex flex-wrap justify-center gap-2"
      initial="hidden"
      animate="visible"
      variants={{ visible: { transition: { staggerChildren: 0.05, delayChildren: 0.15 } } }}
    >
      {starters.map((q) => (
        <motion.button
          key={q}
          onClick={() => onPick(q)}
          title={q}
          variants={{ hidden: { opacity: 0, y: 6 }, visible: { opacity: 1, y: 0 } }}
          whileHover={{ scale: 1.03 }}
          whileTap={{ scale: 0.97 }}
          className="inline-flex items-center gap-1.5 rounded-full border border-hairline bg-panel py-1.5 pl-2.5 pr-3.5 text-sm text-ink transition-colors hover:border-accent hover:bg-accent-soft"
        >
          <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
          {preview(q)}
        </motion.button>
      ))}
    </motion.div>
  )
}
