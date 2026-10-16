# Suhail V3.4.1: context-limit reliability fix

Date: 2026-10-16. Branch `v3/v341-context-limit` in `C:\Projects\suhail-v341-context`, from `d5ed571` (tree `81a4fb4`). It is a local commit only: nothing was pushed or merged, and no paid model call was made. `fhd` (`4cd4304`), `main` (`2b9f7c8`), `v3/integration` (`d5ed571`), the integration worktree and the live 5190/8023 app were not touched. All worktrees share `C:\Projects\demo\.git`.

**READY FOR INDEPENDENT REVIEW: YES.** The paid live comparison is the one gate still open; it needs Fahad's separate GO (budget in section 8).

## 1. Commits and files

| Commit | What |
|---|---|
| `a77f788` | the fix, the replay tests and the five fixtures |
| the commit after it | this report and two API doc tables |

Files changed by `a77f788`:

| File | Change |
|---|---|
| `chat/operations/inference_safety.py` | `ContextLimitExceeded(SafetyRefused)` (size, bound); `input_limit()`; the ledger raises it for an oversized request |
| `chat/llm/pipeline/_llm.py` | `invoke` raises `ContextLimitExceeded`; one `suhail.context` warning line with role, case, run, bytes and bound, never the prompt |
| `chat/operations/context_budget.py` (new) | Request measurement identical to the dispatcher's; the deterministic digest; `ContextLedger` (which results were compacted, the conclude-only turn, exhaustion, refusals); reviewer packet fitting |
| `chat/operations/investigator.py` | Pre-dispatch size check on every turn; compaction; conclude-only turns; `context_exhausted` with `partial_investigation`; a refused request is never re-sent; the reviewer's own pre-check (and its repair's) |
| `chat/operations/agents.py` | `_ask` stops on `ContextLimitExceeded` instead of retrying it |
| `chat/operations/graph.py` | Review reason `INVESTIGATOR_CONTEXT_EXHAUSTED`; authority reason "Input limit reached ..." when every degraded role is `context_exhausted`; `context_management` in the round and run logs |
| `chat/operations/authority.py` | Rule `AUTH-28-context-exhausted` |
| `chat/operations/worker.py` | Arabic summary for the new review reason |
| `chat/operations/store.py` | Audit wording for `context_exhausted` |
| `chat/tests/test_v341_context_limit.py`, `chat/tests/fixtures/v341/*.json.gz` (136 KB) | Five-trace replay and unit tests |

Unchanged: the 64 KB bound (`SUHAIL_MAX_INPUT_BYTES`), call caps, aggregate and per-lane budgets, authority rules other than the new label, reviewer verdict semantics, verifier, approval and closure. There are no frontend changes.

## 2. Root cause and measurements

All 199 tool calls of the 24 recorded V3.4 runs were rebuilt on a new disposable database (`shipments-v2-world-v341-replay-20261016`, the frozen bundle stepped to 2026-09-17 03:30, agents off, no keys). Every call returned the recorded evidence ids and computed-result ids.

Contents of the five refused requests (characters; refused at 61.7k to 68.9k):

| Part | Size | Share |
|---|---|---|
| Fixed part of every request: system prompt 7.8k, cause catalogue 7.7k, tool list 4.5k, actions 2.0k | about 22.9k | 35% |
| Tool results (9 to 11 each; median result 3.5k, largest 6.5k) | 34k to 42k | 55 to 65% |
| Model's call replies, round-0 conclusion and revision request | 1.9k to 4.7k | 3 to 7% |

Other measurements:

- The bound counts each quote inside a tool result twice (JSON escaping), adding about 8.6%. That is why 000194 was refused at 61.7k characters.
- Growth per tool turn: median 3.8k with one tool, 7.2k with two, 11.7k with three. The first prompt has a median of 25.3k.
- The reviewer prompt is 25k to 45k. It was never refused, but nothing checked it.
- Four of the five failures happened in the revision round, which re-sends the whole conversation. The fifth (000049) failed in round 0 after 9 calls, two of them identical `scans` calls.

The defect has two parts. The overflow surfaced as `SafetyRefused` and was caught as a provider failure, so the identical request was retried and the case was labelled `model_unavailable` / AUTH-02 "Model role unavailable". And nothing kept the conversation under the bound.

**Context reduction.** On the real results, the digest is a median 55% of the original (53% in bound bytes). Every id is kept, with no losses across 51 results. In the five replays, compaction freed 5.3k to 18.0k characters, which brought each request back under the bound.

## 3. What the fix does (spec items 1 to 8)

1. `ContextLimitExceeded` is raised by the dispatcher and the ledger and logged once with sizes and ids only.
2. Every investigator turn, reviewer request and reviewer repair is measured before it uses a model call or reaches the dispatcher. While a request fits, nothing changes (section 5).
3. The conclude-only turn comes after compaction, when the conversation still does not fit. It is the same validator, reviewer and authority path, and INSUFFICIENT_EVIDENCE is still an accepted answer. No confident diagnosis is forced.
4. Compaction is deterministic and oldest first. Each shortened result keeps:
   - every evidence id with its kind, scope and times (`id@occurred_at+Ns`, lossless);
   - every computed result with its values;
   - the tool and its arguments;
   - every other id the text named;
   - a `COMPACTED` label and the hint to call the tool again.
5. The full records stay in `investigation_log.evidence_index`, and the reviewer reads cited records in full.
6. If even a conclude-only request cannot fit, it is not sent. The round ends `context_exhausted` with `partial_investigation`:
   - every retrieved evidence id and computed id;
   - the last hypotheses, labelled "sent back by the independent reviewer; not a diagnosis";
   - the reviewer's points;
   - "a person reviews the evidence gathered so far".
7. Classification: `context_exhausted` is its own failure kind, review reason (`INVESTIGATOR_CONTEXT_EXHAUSTED`) and authority rule (AUTH-28, HUMAN_REVIEW). The other kinds are unchanged: `model_unavailable` (provider), a reviewer REVISE / INSUFFICIENT_EVIDENCE / HUMAN_REVIEW, a valid INSUFFICIENT_EVIDENCE conclusion, `turn_budget_exhausted`, `model_call_cap` and `invalid_model_output`.
8. Reviewer and revision:
   - The revision round shares the investigator's conversation and its checks.
   - The reviewer packet may shrink only in parts that were already optional and bounded: uncited record contents, lowest priority first, and long computed-input id lists replaced by their count. The packet records what was removed. Records flagged by an earlier review, cited records, citation validity, deterministic checks, the conclusion and earlier reviews never shrink.
   - If the packet still does not fit, the review is UNAVAILABLE as `context_exhausted` and nothing is sent.

Results holding evidence that a review or a conclusion marked as contradicting are never shortened. Results the current hypotheses cite, and the latest turn's results, are shortened only to let a conclusion through.

## 4. Five-trace offline replay

The harness runs:
- the real tools over the recorded database rows, with every result checked against a SHA-256 of the original text;
- a scripted model that repeats the recorded tool choices, round by round;
- a scripted reviewer that repeats the recorded verdicts and asks for a person after that;
- the real investigator, reviewer, guard, graph and authority code.

Where the recording ends, the original request was refused, so the scripted model follows one of three policies:
- `conclude`: concludes with the round's recorded conclusion, or an honest INSUFFICIENT_EVIDENCE when none was recorded;
- `more_tools`: keeps asking for tools until told to conclude;
- `stubborn`: never concludes.

| Trace | Recorded | `conclude` | `more_tools` | `stubborn` | Largest request (bound 65,536 bytes) |
|---|---|---|---|---|---|
| 000134 (two lanes) | model_unavailable, AUTH-02 | DELAYED_SYNC, reviewed | same | context_exhausted, AUTH-28, 97 ids handed over | 64,379 |
| 000012 (four lanes) | model_unavailable, AUTH-02 | WEIGHT_MISMATCH, reviewed | same | model_call_cap | 65,398 |
| 000049 (four lanes) | model_unavailable, AUTH-02 | INSUFFICIENT_EVIDENCE, reviewed | same | model_call_cap | 63,639 |
| 000194 (four lanes) | model_unavailable, AUTH-02 | CUSTODY_GAP, reviewed | same | context_exhausted, AUTH-28, 87 ids | 64,221 |
| 000207 (four lanes) | model_unavailable, AUTH-02 | DELAYED_SYNC, reviewed | same | context_exhausted, AUTH-28, 100 ids | 64,848 |

Results:
- No oversized request was handed to the model or the reviewer in any case, so none was dispatched or repeated.
- No case was classified as provider-unavailable.
- Every retrieved id is in the evidence index and in the handoff.
- No result holding flagged contradicting evidence was shortened after it was flagged.
- Nothing was resolved or verified; every case is HUMAN_REVIEW or under review.
- Because the scripted reviewer asks for a person after the recorded verdicts, every concluded case ends HUMAN_REVIEW (AUTH-03) here. Live verdicts will differ.
- The stubborn model on 000012 and 000049 runs into the existing call cap before the input limit. That is a person too, under the pre-existing AUTH-02 wording.

**The 19 recorded runs that fit are unchanged.** Replayed the same way, none was compacted, none got a conclude-only turn, and all made the same tool calls.

**Margin, flagged for review.** The largest replayed request was 65,398 bytes, 138 under the bound. That is by design: compaction starts only when a request would otherwise be refused, and the pre-check uses the dispatcher's own measure, so a request that passes cannot be refused for size. If the two measures ever disagreed, the defensive path would catch the refusal, shorten the conversation and conclude, never re-send the request. The reviewer may prefer a deliberate margin, for example 2 KB. That would be a one-constant change, and compaction would start slightly earlier.

## 5. Tests

| Gate | Result |
|---|---|
| New V3.4.1 tests (`tests.test_v341_context_limit`) | 20/20 |
| Focused suites (investigator, forced conclusion, repair, reviewer doubt and evidence, agents, graph, timeouts, transport, latency equivalence, provider gate, two- and four-lane) | 197/197, then 217/217 together with the new module |
| Full offline regression (`artifacts\v341\offline.ps1 discover`, test rates, throwaway ledger) | **1,007 run, 0 failed, 35 skipped** (the same 35 opt-in skips as V3.4's 987; +20 new) |
| Real Neo4j: two-client, three/four-client races, lease expiry/fencing, V3.2 action protocol with its four-client race | **21/21**, 2,925 s, on the new disposable `shipments-v2-world-v341-race-20261016` |

An earlier version also limited how many tools a turn could run when room was short. The latency-equivalence test caught that it changed investigations that never reach the limit, so it was removed before the gates.

## 6. Databases and processes

- Created (disposable, kept as evidence): `shipments-v2-world-v341-replay-20261016` (the world at 03:30, 14 open cases, no runs) and `shipments-v2-world-v341-race-20261016` (race fixture).
- Protected databases: counted with READ sessions before and after. Twelve of thirteen are identical. The live demo database `-v32-demo-20261016` grew from 559 to 586 operations records (+27 nodes and +27 relationships). All new records sit at the live app's paused clock (2026-09-17 17:30) and were written by the 8023 app itself:
  - operator `DEMO-OPERATOR-LOCAL` verification requests and action responses;
  - `DEMO-RULE-WORKER` runs, processed count 10 to 11;
  - the monitor's case openings and symptom updates.

  My tooling only reads that database (a READ session for counts).
- Still running and mine: the agents-off replay backend on 8030 (no key, Auto paused; PID in `artifacts\v341\backend_8030.pid`). I can't stop processes in this mode. To stop it: `Stop-Process -Id (Get-Content C:\Projects\suhail-v341-context\artifacts\v341\backend_8030.pid)`.

## 7. Remaining failure modes

- A model that will not conclude still ends without a diagnosis: `context_exhausted` (AUTH-28) or the existing turn budget or call cap. In every case the evidence is handed to a person.
- The fixed 23k part of every request is untouched (instructions and catalogue). Very long investigations can still need compaction early.
- A shortened result hides record fields from the investigator, though not from the reviewer or the evidence index. The model may re-call a tool to read it, which costs a call.
- Reviewer trimming of uncited record contents has never been needed (the largest replay review was 48.9k). If it happens, the reviewer sees the ids of the removed records but not their contents, and the packet says so.
- Frontend (out of scope): `context_exhausted` shows the generic degraded line ("Investigator: Context exhausted. A person has this case."). The case status line falls into "The model's reply could not be used", which is accurate but not specific. A follow-up should add its own wording.
- Pre-existing and unchanged: `turn_budget_exhausted` and `model_call_cap` still carry the AUTH-02 "Model role unavailable" text.
- Not fixed: identical repeated tool calls (2 of 199) still add a second copy of the result.
- Not yet measured live: how GPT-OSS behaves with compacted results and the conclude-only message.

## 8. Investigation consistency

Offline, the five investigations that lost their diagnosis now reach a valid conclusion with a cooperative model, or an honest, labelled handoff with no lost evidence. The 19 that fit behave exactly as before.

That removes the largest avoidable source of difference between the V3.4 runs: 4 of the 7 differing outcomes in the V3.4 review involved the input bound on one side (000012, 000049, 000134, 000207). The model's own run-to-run variance in verdicts and causes is not affected by this change. Whether live consistency improved can only be measured with the paid comparison.

**Proposed paid live comparison (needs your GO):**
- **Setup:**
  - A fresh disposable database, `shipments-v2-world-v341-live-20261016`: import, then step the clock to 2026-09-17 03:30. That should reproduce the same 14 open cases.
  - Backend from `a77f788` on port 8031.
  - Settings identical to B's four-lane run: 4 workers, 4 lanes, 3 tools a reply, overview prefetch, repair, forced turn, 12 calls a case, 60 s a call, 4,096 output tokens. Auto stops after 12 investigations.
  - Keys read from the demo `.env` into the process only.
- **Ledger:** a new file, `artifacts\v341\inference-budget-live.json`.
- **Hard caps:** 144 calls, 3,000,000 tokens, $0.40 in total; 36 calls, 750,000 tokens, $0.10 per lane. Rates are $0.15 in and $0.60 out per million.
- **Expected:** about 85 to 95 calls and $0.22 to $0.25. B's identical run used 85 calls and $0.217.
- **Compared with B's two recorded runs:** input-bound refusals (expected 0), `context_exhausted` count, outcomes per case, compactions, and that nothing is resolved without verification.
