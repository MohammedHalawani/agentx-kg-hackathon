import { ShieldCheck } from 'lucide-react'
import { Tooltip } from '../ui/Tooltip'

// A small trust signal on each grounded answer. Tone rides on the accent token (opacity), so it
// re-skins with the theme. The tooltip explains what "grounded" and the number mean.
export function TrustChip({ confidence }: { confidence: number }) {
  return (
    <Tooltip
      label={`Grounded: this answer uses only values the database returned, not the model's own guess. ${confidence.toFixed(
        2,
      )} is the agent's self-reported confidence (0 to 1).`}
    >
      <span className="inline-flex cursor-help items-center gap-1 rounded-full bg-accent-soft px-2 py-0.5 text-[11px] font-medium text-accent">
        <ShieldCheck size={12} />
        grounded · {confidence.toFixed(2)}
      </span>
    </Tooltip>
  )
}
