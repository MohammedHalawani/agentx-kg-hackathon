# Closed-loop proof — independent decision semantics review

Recorded: 2026-10-07 22:38 +03:00 (19:38 UTC).
Scope: read-only backend/database review plus narrow frontend correctness fixes. No database mutation, backend edit or later-phase product expansion by this reviewer.

## Success statistics and denominators

`chat/llm/pipeline/cases.py` computes category/action performance only where `Outcome.success IS NOT NULL` (lines 54 and 68). Success=true contributes a win; success=false contributes an observed unsuccessful outcome; null contributes neither. `_COVERAGE` instead counts FailureReasons carrying a RESOLVES_WITH edge, so its `resolved` field represents recorded recommendations/resolutions, not successful shipment outcomes.

Read-only GET /cases at 22:34 +03:00 reported coverage resolved166/unresolved74/total240 and writebacks agent1/seeded165/pending1/total166. Category denominators sum165, wins149, confirming the existing pending recommendation is excluded from the observed historical success rate (149/165, approximately90.3%). These are synthetic recorded outcomes; no SPL operational performance claim is justified.

`rules.precedent_strength` and `rules.action_success_rate` both omit null outcomes. A direct pure-function probe over true/false/null cases for one action produced tried2/succeeded1/rate0.5 and “1/2 comparable cases succeeded.” An all-pending action produced no rate entry. Pending recommendations do not inflate or depress these calculations.

## Retrieval eligibility finding

At the start of this review, `retrieve._GRAPH` and `_VECTOR` matched any Resolution→Outcome chain without excluding null outcomes. `embed_backfill_shipments._PENDING` relied on case_summary presence rather than observed outcome eligibility. Write-back creates a case_summary and pending Outcome, so a newly accepted recommendation could enter graph retrieval immediately and vector retrieval after a backfill. A pending-only retrieval could satisfy the pipeline's “precedent exists” gate and be cited as precedent even though success-rate calculations correctly omitted it.

This is feedback contamination risk, not a fabricated positive success counter. Coordinator was notified and owns the narrow retrieval/backfill eligibility correction and backend regression tests. This review does not claim those fixes until separately validated.

## Frontend fixes

Decisions previously named recorded-resolution coverage “Precedent available”/“Covered by historical precedent”, counted agent records as precedents and colored resolution coverage as outcome success. It now says Recorded resolutions / outcome may be pending, agent recommendations recorded, and uses neutral coverage styling. An empty observed-outcome denominator displays an unavailable value rather than a0% failure rate.

StageCard's retrieved-outcome ternary treated success=null as “did not work”. The contract now explicitly permits null, and English/Arabic both render pending verification with a neutral clock icon. True/false retain their observed outcome meanings. The write-back stage now says recommendation recorded / operational outcome pending, with a neutral record identifier, instead of asserting immediate precedent availability.

Reviewer acceptance remains model/policy review acceptance. It is not human approval, authorized execution or verified operational success. The legacy wire disposition `execute` is retained; operator-facing text explains the recommendation-recording meaning. Human approval/outcome capture remains later gated work.

## Validation

PASS: npm test -- StageCard DecisionsView — 2 files,13 tests; includes English/Arabic null-outcome text and neutral recorded-resolution coverage. Existing historical-rate test confirms observed escalation categories remain included in the overall denominator. No observed failure is relabeled pending.

The first added null-outcome tests failed only on an assumed Lucide CSS classname, while their semantic labels already passed. Removed the implementation-specific icon classname assertion; retained pending text, absence of failed text and absence of success styling.

PASS at22:38 +03:00: npm run build — TypeScript and Vite succeeded. Existing graph bundle-size warning remains. npm run lint — exit0 with13 baseline warnings. git diff --check — exit0, Windows line-ending normalization notice only.

Coordinator owns the full Batch2 closed-loop proof and retrieval eligibility gate. This review's source changes contain no backend edits or database writes.
