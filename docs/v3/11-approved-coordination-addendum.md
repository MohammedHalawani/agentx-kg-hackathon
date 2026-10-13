# Approved ownership and milestone addendum — Composer Phase C

Approved 13 October 2026. Architecture and wire contract remain `suhail-v3-1`. This adds an independent QA gate to the approved 72-hour prototype without a new development branch/chat.

| Owner / branch | Responsibility | Additional Phase C boundary |
|---|---|---|
| Fable coordinator / existing Claude project | Coordinate milestones, blockers and ownership; delegate concurrency to one Opus high-effort chat | Track neutral packet readiness, four-hour QA budget and defect owners; do not authorize unsafe merges or paid calls |
| Opus / `v3/concurrency` | Claims/leases/fencing, workers, provider limit, failure isolation, concurrency tests | Fix only assigned worker/lifecycle defects; no dataset/UI edits |
| Separate Sol High task / `v3/scenarios` | Scenario generation, GPS/source retrieval, temporal/provenance and automated structural validation over full generated dataset | Supply neutral actual-source packets; withhold test catalogue until independent review snapshot is complete; fix all data defects |
| Composer / `v3/route-ui` | Phase A discovery; Phase B map/graph/timeline and multi-case display; same thread/worktree | Phase C: review every 6–10 curated development shipment and two V2 video references where evidence exists; no dataset changes |
| Sol integrator / `v3/integration` | Bootstrap, controlled merges, focused verification and final signoff | Require completed case-audit matrix, resolve REVIEW rows and block curated-case FAILs; preserve V2 |

## Existing milestones, with the QA addition

- Bootstrap checkpoint before any downstream code edits: exact common SHA, frozen contracts, recording UI provenance, protection checks and readiness.
- Hours 0–4: owners receive that SHA and verify their assigned worktree; Composer A can start immediately.
- Hour 24: Opus claims/fencing, Sol first deterministic source fixtures, Composer A report.
- Hour 36: two-worker/mock provider and DB races; first validated scenarios/GPS evidence; Composer B integration fixtures.
- Hour 48: feature freeze, first controlled integration; Sol seals curated case list and neutral evidence packets. No new scenarios/features after this point.
- Hours 48–60: Composer C, HARD FOUR HOURS total, after Phase B is ready. Neutral first-pass notes are finalized before catalogue release/comparison. Sol performs full-dataset structural validation in parallel and owns corrections.
- Hours 60–68: focused defect fixes/retests, case QA dispositions and final integration signoff. No paid calls are authorized by this addendum.
- Hours 68–72: buffer/presentation; V2 final videos remain fallback. No-go if core concurrency/source/temporal gates or curated-case QA remain unsafe.

## QA packet and reporting ownership

Sol supplies actual source records/relationships, shipment/case IDs, hashes, relevant before/after receipt cutoffs and deterministic tool-access snapshots. No expected diagnosis/desired outcome/scenario labels in the neutral first-pass packet. The separate authored test catalogue is released only after all first-pass notes are timestamped/hashed. Historical hidden evaluation answers and private truth remain inaccessible to runtime tools, investigator, reviewer, Canopus and API throughout.

Composer writes `docs/v3/case-qa/evidence-first.md`, `case-audit-matrix.csv` and `case-audit-report.md` on its existing branch. It routes data defects to Sol, UI defects to itself and lifecycle defects to integrator/Opus. First-pass notes are immutable; later expectation comparison and repair/retest notes are appended separately. Structural validation across the entire generated dataset is not delegated to Composer.

Original video reference IDs are `SYN-SHP-000304` and `SYN-SHP-000443`. Review only available read-only evidence; no replay/reset/live inference/video modification. Unavailable reference evidence is documented as not checked, never passed. Curated V3 cases must all have a PASS/REVIEW/FAIL row with actual source citations before signoff. Catalogue matching alone is insufficient.

## Dispatch boundary

This bootstrap chat stops after the readiness report. The user distributes Fable/Opus, Composer A (with B/C follow-ups), and separate Sol High handoffs. No Codex subagents or replacement developer threads are launched here. No push, paid model run, database migration, API migration or broad evaluation campaign is authorized.
