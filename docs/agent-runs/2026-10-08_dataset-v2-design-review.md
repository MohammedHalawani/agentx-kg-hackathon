# Dataset V2 design — review

Timestamp: 2026-10-08T16:30:20.998277+00:00. DESIGN ONLY.

Checked the full required-entity list, city coverage and flows against the user request. Scenario causes derive from observations with contrast controls, evidence removal and unknown/conflict outcomes. Vehicle GPS alone is not parcel position; missing reconciliation is UNRECONCILED_CUSTODY and never automatic loss or personal blame. Recommendations and reviews do not resolve cases; only authorized outcome evidence can do so.

Generation is offline/deterministic with chronology/capacity/custody/provenance validators and gold separated from model-visible context. Migration proposes a verified isolated shadow database/DBMS, backup/dry run/idempotent import/rollback; V1 is preserved and unknown data is not fabricated. V2 evaluation excludes complete holdout groups, measures unsupported claims/action validity/lifecycle and retains all attempts; human gold is required for human correctness metrics.

Notification mode defaults to dry_run with zero provider calls in tests/evaluation and durable dedup beyond provider retention. No external email is sent. Assumption sizing, database edition/target, operator/outcome authority, budget and adjudication remain future manual decisions before dependent implementation.

## Fresh read-only independent review — 2026-10-08T16:35:18.443328+00:00

The UI owner reviewed the post-evaluation operator_output/graph/writeback integration, EN/AR lifecycle copy and all seven design documents. One blocking copy claim said rejection wrote nothing to the graph even though escalation can persist an EscalatedCase. Root fixed both languages to say no recommendation was recorded and human review is required. Twelve focused Intake/language/parity tests passed after that correction.

The reviewer reported no other blocking issues and conditional PASS; the correction satisfies that condition. Review relied on coordinator tests/API/browser results and did not independently recheck external citations. Experimental/model/dataset/translation and V1 timeline limitations remain explicit.
