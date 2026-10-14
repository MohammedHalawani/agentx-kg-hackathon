# V3.1 legacy fixture repair — October 14, 2026

Branch: `codex/v3-1-corrective`, worktree `C:\Projects\suhail-v3-1-corrective`.
Repair parent: `bfbfa896d8206a0fd0b16b542e77510c291a8349`.
Protected V3 integration: `765cb4033e6f0238d7cf758e20a89b54cfe6a0bf`.

**V3.1 READY TO MERGE: YES**, for this corrective branch after final independent review. The complete offline gate passed: **861 passed, 0 failed, 0 errors, 25 skipped**. The skipped live Neo4j tests were not executed and are not passes. This is a test-fixture repair; V3.2 implementation has not started. No merge or push is part of this handoff. Routine unattended billable use remains blocked by the risks below.

## Root cause and correction

The prior review found two failures in `chat/tests/test_operations_agents.py`. Its investigator/reviewer doubles did not forward the graph's shared session or reviewer context. The default reviewer returned ACCEPT while leaving `alternatives_tested` empty. V3.1 correctly rejected that invalid response, so the positive tests never reached their automatic-action paths. The prior focused gate had omitted these older workflow tests.

The repaired double follows the current protocol, forwarding the shared session, review/feedback, source context and repair callbacks. The investigator still retrieves evidence through real tools. It additionally checks up to three retrieved observation records' `occurred_at` against `recorded_at`, cites those actual records, and records delayed synchronization as an alternative. Prompt receipts weaken that explanation for those observations; they do not disprove buffering of unseen records. The alternative therefore retains uncertainty. No second alternative is invented if no valid pair exists or synchronization is already primary.

The reviewer receives only its packet and independently recomputes the source-time check. ACCEPT and `alternatives_tested="yes"` depend on agreement between those fields, source IDs and the declared alternative. Missing times, a missing alternative, or a source change that makes the earlier assessment incorrect returns HUMAN_REVIEW. This is a deterministic test double, not a model-quality evaluation or production diagnostic rule. The fixture's no-evidence path also uses the current INSUFFICIENT_EVIDENCE schema with an explicit next evidence step.

Production reviewer validation, authority policy, concurrency, model/provider settings, evidence cutoffs and frozen API contract are unchanged. No preferred decision for 000064/000194 was added.

## Safety and protocol assertions

- Positive automatic requests reach AWAITING_OUTCOME with current deterministic authority; no outcome or RESOLVED case is claimed before independent verification.
- The no-adapter workflow records NOT_ACKNOWLEDGED and no verified outcome, even when later source evidence exists. A request is not a resolution.
- The positive graph passes the same session to both roles; final investigation counters, run log and latency call counts agree and are nonzero.
- The reviewer receives citation validity and bounded uncited-source context.
- Changing a source event time while keeping the investigator's old assessment causes HUMAN_REVIEW; missing source time or hypothesis cannot acquire default acceptance.
- An honest no-alternative review requests human judgment. An injected ACCEPT with `alternatives_tested="no"` is rejected by the unchanged production validator and becomes UNAVAILABLE under bounded retries. Both paths create no execution, no outcome and no resolved case.
- Existing rejection of unknown contradiction IDs, invalid citations and inconsistent ACCEPT-with-objections remains covered by the full suite.

## Before/after evidence and gate

Before: the October 14 review reported 856 passing tests, 2 workflow failures and 25 skipped tests (883 test executions after resolving test search-path errors). Both named workflow tests independently failed; an in-memory control using the older validator passed. Historical evidence remains in `C:\Projects\suhail-v3-2-review-2026-10-14`.

After: both named tests independently passed with this repair. The affected module passed all 19 tests. Corrected discovery loaded 886 tests in one run: **861 passed, 0 failed, 0 errors, 25 skipped** (1,368.578 seconds). This adds three focused regression tests and restores the two previously failing cases. Separate focused repeats are not added to the full-suite count. Frontend: **57 unit tests and 9 Chrome browser tests passed**, with zero failures/skips; typechecking and the browser server's production build passed. Exact results and all 25 skip reasons are recorded in `fixture-repair-verification.json`.

Discovery now uses `unittest.defaultTestLoader.discover("tests")` from `chat`, with both `chat` and `chat/tests` on `sys.path`, and no `-t .`. This resolves the three older flat test-helper imports in a single complete run. Opt-in Neo4j write/race tests are explicitly disabled; skipped tests are not counted as passes. The existing suite builds temporary synthetic fixtures for validation; it does not rebuild the frozen V3 bundle.

Reproduce with the worktree's existing locked environment, using placeholder credentials, `NEO4J_URI=bolt://127.0.0.1:1`, `LLM_API_BASE=http://127.0.0.1:1/v1`, `SUHAIL_NEO4J_TESTS=0`, `SUHAIL_V3_RACE_TESTS=0`, `LITELLM_LOCAL_MODEL_COST_MAP=True` and `LITELLM_TELEMETRY=False`:

```text
cd C:\Projects\suhail-v3-1-corrective\chat
$env:PYTHONPATH = "$PWD;$PWD\tests"
$env:PYTHONIOENCODING = "utf-8"
$env:NEO4J_URI = "bolt://127.0.0.1:1"
$env:NEO4J_USERNAME = "offline"
$env:NEO4J_PASSWORD = "offline"
$env:LLM_API_KEY = "offline-placeholder"
$env:LLM_API_BASE = "http://127.0.0.1:1/v1"
$env:SUHAIL_NEO4J_TESTS = "0"
$env:SUHAIL_V3_RACE_TESTS = "0"
$env:LITELLM_LOCAL_MODEL_COST_MAP = "True"
$env:LITELLM_TELEMETRY = "False"
.venv/Scripts/python.exe -m unittest -v tests.test_operations_agents.AgentPipelineTests.test_live_case_runs_agent_stages_and_low_risk_action_awaits_outcome_without_a_human
.venv/Scripts/python.exe -m unittest -v tests.test_operations_agents.OutcomeEngineTests.test_live_world_resolves_only_from_later_verified_evidence_with_no_human
.venv/Scripts/python.exe -m unittest discover -s tests
```

The two independent logs and complete verbose log/JSON are retained in ignored `artifacts/v3.1-fixture-repair/`. Frontend checks repeat all unit tests, application/test typechecking and nine relevant scripted-backend Chrome tests covering approval without resolution, current briefs, two active cases, chronology, route evidence and map segmentation. Browser output screenshots are preserved under the same artifact directory; tracked screenshots are restored rather than included in the repair.

## V3.1 corrections and protection

The full offline gate includes the real loopback SDK 503/429/timeout tests, explicit retry accounting, bounded source-backed reviewer packets, fail-closed verdicts, DEMO/SYN key conversion/collision/reference tests and canonical final counter checks. The five production correction files remain byte-for-byte equal to the repair parent; their new test coverage remains in place.

Protected integration and `fhd` retain their original HEADs and clean checkouts. The finished video hashes and frozen bundle manifest match their recorded protection values. No database writes, billable inference, protected application/port 8022 changes, push, deployment or merge occurred. This repair opens no new database connection; real database writes/races remain unexecuted in this gate.

## Remaining risks and final-review handoff

Production still lacks an explicit output-token ceiling and aggregate token/cost reservations. A logical call cap does not guarantee a spending ceiling. The admission wait and execution can each consume the configured call deadline. Routine unattended billable use and a strict shared-deadline guarantee remain blocked; this fixture repair does not implement those controls.

Scripted acceptance is not proof of live investigator/reviewer accuracy. This fixture checks one evidence-backed receipt-time alternative and does not claim coverage of all playbook families. The 136-case catalogue and roughly 12 priority scenarios, independent model evaluations, and rescan/device-sync/missing-custody action-response-verification work remain deferred to V3.2 after V3.1 approval.

Changed files are limited to `chat/tests/test_operations_agents.py`, this handoff and `docs/v3.1/fixture-repair-verification.json`. Final reviewers should inspect the source-pair calculation, packet-only reviewer recomputation, shared-budget forwarding and negative no-execution/no-resolution assertions, then reproduce the gate. Do not weaken the validator or authority rules. No Composer production/UI changes are required for this repair.

Rollback, if needed after final review: revert only the fixture-repair commit on a review branch; do not reset or alter protected integration or datasets. No data rollback or migration is needed. The final repair commit SHA is supplied in the completion message and can be verified with `git rev-parse HEAD` in this worktree.
