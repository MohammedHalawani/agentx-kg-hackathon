# Baseline stabilization — gate

Timestamp: 2026-10-08T16:30:20.998277+00:00. Branch: fhd.

**Baseline stabilization gate: PASS for an experimental local baseline.**

- Python: 81 tests passed, including real AFL fixtures, identity/writeback, pending precedent, normalization, operator output and evaluator/aggregate contracts.
- Frontend: 107 tests across 28 files passed on final source.
- Lint: zero errors, 13 existing warnings. TypeScript/Vite build passed; large bundle warning remains.
- Read-only API: all five Explore filters, bounded graph, live schema, Intake 73 and Decisions 167 records / two pending / 165 observed passed. Legacy route and favicon checks are attached below.
- Browser: English LTR and Arabic RTL, map tiles/25 shipment markers, positive graph canvases, live schema, no desktop/mobile overflow and mobile drawer closure verified. Screenshots in evidence.
- Prior controlled writeback: exact +2 nodes/+2 edges for a pending recommendation; sequential/concurrent replay produced no additional objects. No new writeback proof was needed or performed in this read-only closure.
- Evaluation before/after/current census equality: all non-timestamp fields identical; 300 shipments, 3638 nodes, 4210 edges, 165 observed histories, two pending recommendations and ONLINE vector index.
- Final whitespace/secret checks must pass before commit; their actual result is appended below.

This gate does not certify autonomous execution, production accuracy or verified new model quality after the prompt/boundary fixes. Logical commits are permitted only after the attached final checks pass.

## Final pre-commit verification — 2026-10-08T16:31:27.134999+00:00

PASS: git diff --check (line-ending notices only); secret scan of 425 text files found no configured credentials or token/private-key patterns and printed no secret values. Live valid POST /chat returned 410, /registry/Customer 410 and followed favicon redirect 200. An initial malformed legacy-chat smoke payload correctly returned 422 at request validation; the corrected valid payload verifies retirement. English Decisions explicitly separates 165 observed histories and two pending records. English/Arabic screenshots were visually inspected.

This supersedes the pending-check sentence above. Baseline gate is complete; selective logical commits may proceed. No evaluation run or database mutation was needed for these checks.

Final independent-review copy correction: 12 focused tests passed and TypeScript/Vite rebuild passed after the two locale-string edits. No functional code changed after the full 81/107 test runs. Local artifact links pass. Known bundle/lint warnings remain unchanged.
