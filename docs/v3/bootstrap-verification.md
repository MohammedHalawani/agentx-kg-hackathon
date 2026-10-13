# Bootstrap verification — 13 October 2026

This records the approved initial bootstrap only. No development workstream, provider call, database access/migration or V3 runtime investigation was launched. Source worktrees and frozen contracts are ready for the user's Claude/Composer/separate Sol High distribution.

## Source provenance

- Integration parent: protected `fhd` at `4cd43045a1db284e83cd5702d63acf7950492492`.
- Recording UI: exact committed `frontend-next` subtree from `5aab052daead6141bf54fda068f7bd4bdcba3cb2` in `C:\Projects\demo\.ui-integration`.
- Imported paths: 426 files. No tracked application edits beyond that exact source import; backend/chat/scripts unchanged from parent.
- Approved contract `suhail-v3-1`: interface reference plus synthetic wire examples, ownership/milestones and Composer Phase C included in this commit.
- Protected checkout states and SHA-256 hashes of both final videos captured before bootstrap in the external readiness artifact directory; final equality verification is recorded in the readiness report.

## Completed checks

| Check | Result |
|---|---|
| Imported source versus recording UI commit | PASS; exact subtree match |
| Dependency installation | PASS; `npm.cmd ci --ignore-scripts`, 622 packages; lockfile unchanged |
| Type checking | PASS; `npm.cmd run typecheck` |
| Existing adapter/service tests | PASS; two files, 37 tests |
| Fresh production build | PASS; `npm.cmd run build` |
| Existing mocked connected UI smoke | PASS; one existing Operations queue test; isolated fresh port 5191, `reuseExistingServer=false` |
| Existing credential scanner | PASS; 1,022 text files, values suppressed |
| Frozen JSON parse/version/status | PASS; `suhail-v3-1`, `approved_frozen` |

The first browser run used 5291 while the existing backend stub only intercepts 5191, so that attempt failed with an empty queue. The bootstrap-only configuration outside Git was corrected to the expected unused port; rerun passed. No source/test/application file was modified to obtain the pass. No backend was started.

The fresh build's main assets are byte-identical to the recording assets:

- `index-Ct2BapBv.js`: SHA-256 `62438B902214684336C3E3900DF7DEBDD5C7D97BD5D73BE127539F787884E170`.
- `index-CD_EZO1c.css`: SHA-256 `92B47C0A56F04B0B91B43E3A2604B5B0A9D4C3DC4FEDFE03177830738FE2D1A4`.

Entry HTML matches after line-ending normalization; raw file hashes differ (fresh Windows checkout line endings versus recording). No claim of whole-directory byte identity is made. Existing dependency deprecation and bundle-size warnings were preserved; no dependency changes were made.

## Ready versus pending

Ready: common source/bootstrap ancestry, recording UI, frozen contract, role prompts, scoped Composer A/B/C, and evidence-first QA/report ownership.

Pending implementation: concurrency, scenarios/GPS and frontend changes. Downstream worktrees inherit the committed source/contract, not ignored dependency directories or environment files. Each owner installs dependencies/configuration in its own worktree. No database is provisioned and no provider entitlement/balance is tested during this bootstrap.

The final bootstrap SHA, all four branches/worktree paths and protected-state comparison are in `C:\Projects\suhail-v3-plan-2026-10-13\12-bootstrap-readiness.md`. The user distributes the handoffs; this chat does not launch subagents or development threads.
