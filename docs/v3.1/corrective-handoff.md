# Suhail V3.1 corrective integration handoff — October 14, 2026

READY TO MERGE: **YES, for this scoped corrective patch after final human review.** All targeted offline gates pass. This does not approve deployment, routine unattended billable use, or assert improved live diagnostic accuracy. No merge, push or deployment was performed.

Branch: `codex/v3-1-corrective`. Worktree: `C:\Projects\suhail-v3-1-corrective`.
Exact parent: `765cb4033e6f0238d7cf758e20a89b54cfe6a0bf`.
The final corrective commit SHA is supplied in the completion report and can be verified with `git rev-parse HEAD` in this worktree. Frozen contract remains `suhail-v3-1`.

## Corrections and evidence

| Issue / root cause | Precise correction | Regression evidence |
| --- | --- | --- |
| Hidden HTTP retries: `ChatLiteLLM.max_retries` controls the wrapper but was absent from LiteLLM's provider parameters. The inner OpenAI SDK defaulted to two retries. | `_llm._build_model` retains wrapper `max_retries=0` and forwards `model_kwargs={"max_retries": 0}` to the transport. Application retries remain explicit and counted. No provider-gate implementation changed. | Real locked LiteLLM/OpenAI transport against an ephemeral loopback server: 503, 429 and HTTP timeout each produce exactly one POST. An explicit two-attempt reviewer failure produces exactly two POSTs and two reviewer budget entries. Existing cap-1 abandonment, cancellation and capacity tests pass. |
| Independent reviewer received uncited IDs/kinds without their actual contents; contradiction IDs and inconsistent ACCEPT responses were unchecked. | Add `retrieved_uncited_records`, bounded to 40 complete records and 20,000 JSON characters, plus coverage/omission counts. Selection prioritizes previous flagged IDs, operational record kinds and shipment scope; it never uses a diagnosis or hidden truth. Include available source provenance, exact timestamps and source fields. Exclude unresolved, unretrieved and future records from contents. Contradiction IDs must resolve to contents actually shown; invalid outputs retry under the existing shared budget or fail UNAVAILABLE. ACCEPT cannot carry unresolved objections or invalid citations, and a non-abstaining ACCEPT must report a tested alternative. | Saved visible 000064 excerpts expose both matching and differing barcode observations. Saved 000194 excerpts expose CUST-001's merchant→warehouse endpoints and CUST-003's vehicle→sorter endpoints, timestamps and acknowledgments. Tests check bounds, omitted records, provenance, future/unretrieved records, invalid references, independent rejection, inconsistent ACCEPT, retry accounting and unchanged deterministic safeguards. No preferred verdict is scripted for either shipment. |
| Public values changed DEMO→SYN while ID-keyed dictionaries retained DEMO keys, breaking `index[id]` frontend lookup. | Convert identifier-shaped dictionary keys recursively in both directions. Reject normalization collisions with ValueError; never overwrite one source with another. Preserve schema keys and opaque token/cursor/idempotency fields. The frontend production adapter remains unchanged. | Real in-memory store case details and saved-shaped evidence maps resolve their public references; roundtrip, no mutation, cross-shipment lookup and collision tests pass. Frontend adapter resolves two actual cross-shipment sources in a saved run excerpt. |
| Conclusion counters were captured before the final independent review. | Final `graph.analysis` copies the completed run log's five canonical budget fields into the final investigation result. Persisted/API results use this projection; historical per-round conclusion snapshots keep their original meaning. | Saved 000064's final counters agree at 8 (6 investigator + 2 reviewer); 000194 agrees at 7 (5 + 2). Scripted one/two-round runs, persisted case details, retries, shared caps and latency turn counts agree. |

Saved fixtures contain only visible source-record excerpts, source file SHA256s and accounting fields. They contain no private truth, expected diagnosis, model reasoning or credentials. The original saved artifacts and frozen dataset were not edited. These regressions establish packet/reference/accounting correctness, not semantic reliability of a future live reviewer.

## Verification

- Final combined Python run: **154 passed, 0 failed, 0 skipped** in 209.635 seconds.
- Strengthened transport error-type assertions were then rerun: **4 passed** in 3.783 seconds, confirming ServiceUnavailableError, RateLimitError and Timeout with the required request counts.
- Frontend adapter regressions: **21 passed**; TypeScript application/test typecheck passed.
- `git diff --check` passed. Dependency lockfiles remain unchanged.
- Locked transport versions: langchain-litellm 0.7.0, LiteLLM 1.92.0, OpenAI SDK 2.45.0.
- Test process configuration used placeholder credentials, loopback-only model URLs and an unreachable offline Neo4j address. Store/ledger tests use in-memory doubles; their reset/claim log messages are not actions against Neo4j.

Reproduction in `chat` (after `uv sync --frozen`): set `NEO4J_URI=bolt://127.0.0.1:1`, `NEO4J_USERNAME=offline`, `NEO4J_PASSWORD=offline`, `LLM_API_KEY=offline-placeholder`, `LLM_API_BASE=http://127.0.0.1:1/v1`, `LITELLM_LOCAL_MODEL_COST_MAP=True`, `LITELLM_TELEMETRY=False` in the test process only, then:

```text
.venv/Scripts/python.exe -m unittest tests.test_provider_transport tests.test_identifier_boundary tests.test_reviewer_evidence tests.test_stage2_investigation tests.test_llm_safety tests.test_v3_provider_gate tests.test_investigator tests.test_v3_integration tests.test_latency_equivalence tests.test_model_call_timeout tests.test_preui_review_fixes tests.test_skip_to_next_event
```

In `frontend-next`, run `npm run test -- tests/unit/api-adapters.test.ts` and `npm run typecheck`.

## Remaining safety and integration limits

**Blocking before routine unattended billable API use:** experiment-only `live_budget.py` is not a shipped guard. Production still has no explicit output-token limit or aggregate token/cost reservation; a logical call cap is not a spending ceiling. The added source packet is bounded, but can increase input exposure. This batch does not import the experiment wrapper or claim its $0.50 limit as a production guarantee.

**Existing deadline risk (P2):** no shared-deadline fix was introduced. Admission and provider execution can each spend the full configured deadline; nominal 60 seconds can approach 120 seconds. This blocks reliance on a strict 60-second wait-plus-execution guarantee. Abandoned provider calls still retain their slot until the underlying call exits. Addressing the total deadline is a separately scoped follow-up, not a reason to free an abandoned permit early.

No live inference was run, so no evidence supports a new live-accuracy/acceptance claim. Bounded live comparison would require separate authorization. No unresolved offline correctness gate remains for the four approved corrections. Existing authority, model choice, worker/provider limits, frozen interface and dataset remain unchanged. Other audit findings, including prompt/validator low-confidence alignment, are outside this batch.

## Protection checks

- `v3/integration` remains clean at `765cb4033e6f0238d7cf758e20a89b54cfe6a0bf`.
- `fhd` remains clean at `4cd43045a1db284e83cd5702d63acf7950492492`.
- Protected Stage 4 and recording-UI commits remain `187ae087a0083dd36192d3653a669b4de706f692` and `5aab052daead6141bf54fda068f7bd4bdcba3cb2`; their existing untracked recording/screenshot artifacts were not changed.
- Both finished video SHA256s match the October 13 protection snapshot.
- Frozen bundle manifest SHA256 remains `538d9fffe7c23cb9637be959e7c5ac0f83c76b3fab5c67b8e377e071d687e2b6`, matching the recorded import-readiness manifest.
- No Neo4j data was read or written by this implementation/testing batch. No service was started, stopped or configured on port 8022. No paid inference, API migration, dataset rebuild, additional concurrency infrastructure, frontend redesign, push, deployment or integration merge occurred.

## Files changed

Production (five files):

- `chat/llm/pipeline/_llm.py`
- `chat/operations/checks.py`
- `chat/operations/investigator.py`
- `chat/operations/identifiers.py`
- `chat/operations/graph.py`

Regression tests (nine files):

- `chat/tests/test_provider_transport.py` (new)
- `chat/tests/test_reviewer_evidence.py` (new)
- `chat/tests/test_identifier_boundary.py` (new)
- `chat/tests/test_llm_safety.py`
- `chat/tests/test_investigator.py`
- `chat/tests/test_stage2_investigation.py`
- `chat/tests/test_latency_equivalence.py`
- `chat/tests/test_v3_integration.py`
- `frontend-next/tests/unit/api-adapters.test.ts`

Visible-source fixtures and handoff (four files):

- `chat/tests/fixtures/v31_saved_evidence.json` (new)
- `frontend-next/tests/fixtures/v31-wire-evidence.json` (new)
- `docs/v3.1/corrective-handoff.md` (new)
- `docs/v3.1/verification.json` (new)

## Final review handoff

Review this single corrective commit against its exact parent; focus on inner retry forwarding, fail-closed reviewer validation, key-collision behavior and completed-run counter projection. Reproduce the offline command above and the frontend checks. Preserve historical records and retain routine billable-use/deadline gates. Merge into `v3/integration` only after explicit human review; no merge or live test is part of this handoff.
