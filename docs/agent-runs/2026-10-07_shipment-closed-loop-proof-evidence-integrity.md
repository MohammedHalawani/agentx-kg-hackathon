# Recorded evidence integrity correction

Timestamp: 2026-10-07T22:43:38+03:00. Scope: narrow baseline correction discovered during Batch 2 AFL proof, before serious evaluation. No database writes or commits.

The first read-only SHP-0017 proof exposed final classifier summaries claiming four and then three failed attempts, despite two recorded DELIVERY_ATTEMPT events. The old trace remains preserved and annotated as a model evidence-fidelity limitation.

classifier.py now includes authoritative deterministic recorded facts in its prompt: delivery-attempt count, total events, policy retry limit/SLA, recorded timeline span and source descriptions. The system prompt explicitly prohibits invented counts/elapsed days/limits and distinguishes recorded delivery attempts from proof every attempt failed.

reviewer.py now hard-rejects clear count contradictions before asking the reviewer model, with exact feedback naming claimed and recorded counts. It detects observed English word forms, numeric/Arabic-digit forms and parenthesized counts. It skips uncertain/approximate/range language, attributed customer claims, policy allowance and proposed future attempts; recommendation counts are outside this classifier-rationale guard. A failed subset smaller than the recorded total is permitted because the supplied event list does not prove every attempt failed. Missing event evidence is not treated as a verified zero count.

The same review corrects the existing retry-action implementation by casefolding English action/token text and recognizing re-deliver spellings. Policy limits and retry rules are unchanged. Existing substring-based action detection is not a complete negation parser.

Validation: ten focused evidence-integrity tests cover prompt provenance, observed 4/3 versus 2 contradictions, English and Arabic-digit forms, truthful/uncertain/policy/future counts, missing events, exact prompt feedback, real compiled LangGraph contradiction -> feedback -> corrected count -> acceptance, reviewer-model bypass, retry capitalization/hyphenation and redirect distinction. The six prior AFL state-machine tests also pass. `git diff --check` passes.

Read-only live 20B verification on SHP-0017 completed in 49.32 seconds: both classifier summaries now used two attempts; the first proposed retry was actually hard-rejected for exhausted budget, feedback caused reconsideration and the second review accepted. The sanitized trace is 2026-10-07_shipment-closed-loop-proof-evidence-integrity-live-readonly.json. No writeback ran and observed success remains null.

Limits remain explicit: this guard is not a general natural-language fact checker. It does not guarantee all unmarked final assessments are grounded. The new first live summary said two attempts exceeded a limit of two, whereas equality exhausts the limit; it also described SLA timing imprecisely. Broader numeric comparisons, failure outcome claims and temporal fidelity belong in serious evaluation and subsequent evidence checks. Review acceptance must not be presented as real operational success.
