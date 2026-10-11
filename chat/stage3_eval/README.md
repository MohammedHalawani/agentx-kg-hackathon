# Stage 3 blind evaluation harness (`chat/stage3_eval`)

Implements the frozen Stage 3 design (`docs/plans/2026-10-10_stage3_evaluation_design.md`: b1d331f, amendment 1
001bcbf, amendment 2 ac6f857 and its addendum 7af0d5c, amendment 3 15514ac and its addendum 6f0ed49) and the
independent review of it, so the real-model pilot and
the evaluation can start once Stage 2 lands. It makes no model call and opens no database: the backend track plugs in
the real investigator, tools and databases as described in [WIRING.md](WIRING.md).

All data is synthetic. Nothing here describes real SPL operations. The committed fixture under `fixtures/` is a
hand-specified stand-in labelled FIXTURE, not a world-1 export.

## Steps and the truth boundary

| Step | Process | Reads truth? | Writes |
|---|---|---|---|
| `select` | before any run | yes (truth.jsonl, monitor_replay_rows.jsonl) | `selection.json` (run side), `selection_scorer.json`, `extras.json`, `pairs.json`, `strata.json` (scorer side), each with `.sha256`, written once |
| `run` | the evaluation | **no**: refuses to start with `SUHAIL_EVAL_TRUTH_ROOT`, `SUHAIL_SIM_STATE_ROOT` or any variable naming TRUTH set (before the wiring is built); imports nothing truth-side (tested); invalid if a truth-side module is loaded when it ends | `ledger.jsonl`, `cases.jsonl`, `settled.jsonl`, `results/`, `captured/`, `run_manifest.json` |
| `checkpoint` | on a paused run | **no**: refused like `run` while a truth variable is set; reads the run directory, `selection.json` and, read-only, the run's database | `checkpoint.json` (exit code 0 on pass, 3 on fail) |
| `score` | after the run | yes | `scores.jsonl`, `canary.json` |
| `report` | after scoring | no | `report.json`, `report.md` |
| `rerun-failed` | after a finished run | **no**: as `run` | a new run directory with the same files as `run`, its manifest marked `completion` |

`selection.json` carries, per case, only its order, key, world, shipment and expected opening: no stratum, main-test
flag, extras list, cause, mechanism, label or canary (checked on write, and refused by the run on load); the run
checks it against its pre-registered sha256 and the sealed configuration hash before anything runs. The stratum and
main-test flag of each case, the allocation and the sizing are in `selection_scorer.json`; the extras lists are in `extras.json`,
which the run opens only when `--extras` names it and only after the last main-test case. Shipments listed in
`docs/evals/2026-10-10_world1_pilot/excluded_shipments.json` are never drawn from a world with that dataset id
(`exclusions.py`).

## Sizing and the ledger guard (budget lifted, 2026-10-11)

Model calls are an engineering resource: the 4,000 cap, the 3,600 stop line and the 400 reserve are no longer limits.
`design.CALL_BUDGET` and `design.STAGE3_STOP_AT` remain as historical constants and gate nothing.

- **Sizing.** `select` takes the design's statistical targets (`design.ALLOCATION_AT_PLANNING`: E1 identifiable
  ambiguous 160, E2 identifiable ambiguous 60, determined 30 + 10, unidentifiable 20 + 5 = 285), each cell capped by
  the cases the world holds in it. Target, available and selected are recorded per cell in the summary and in
  `selection_scorer.json` (`sizing`); a short cell is never an error. The seeded draw is unchanged. Nothing is sized
  from the ledger.
- **Per-case caps.** `select --c-cap` is required (the agent arm's one counter per case; 16 per amendment 3);
  B_notools takes at most 3 calls (`design.NOTOOLS_MAX_CALLS`; 2 in every selection sealed before its correction,
  see "The no-tools arm" below).
- **Extras.** After the main test, as before, but no longer conditional on calls left over: the cross-shipment
  ablation on every eligible E1 identifiable ambiguous case, and the stability rerun on 40 of that cell's cases drawn
  by seed (`design.STABILITY_MAX`).
- **The sealed budget** is the worst case of the selection (`design.worst_case_calls`): n_cases * (C_cap + R_cap + 3)
  plus (ablation cases + stability cases) * (C_cap + R_cap). At 285 cases, C_cap 16, that is 5,415 plus the extras
  (19 per case; 23 per case at C_cap 20).
  `run` reserves it in the campaign ledger, settles what it used, and its own ledger refuses to pass it.
- **The guard.** The cap in `docs/evals/model_call_ledger.json` (20,000, with a note) is a runaway guard, not an
  allowance, and need not equal any design number. `run` refuses to start only if the calls spent plus its worst
  case would cross it. `select --reserve N` and `select --stop-at N` are options, off by default and sealed when given.
- Accurate accounting, per-case reservations, reconciliation with the provider's count and crash recovery are unchanged.

## The no-tools arm (B_notools): a prepared correction, NOT YET USED IN ANY RUN

In the first evaluation run (run1, selection `68abd34f94ff`, sealed with a 2-call arm) 160 of 244 no-tools replies
were invalid: "primary_cause must be one of the cause codes" 99, "hypotheses must be a non-empty list" 47, "the
primary cause must be a supported hypothesis" 14. The arm was defective, so that column of run1 measures the arm's
defects as much as the model without tools. `arms.NoToolsArm` is corrected as follows (2026-10-11). **No run has
used the corrected arm: every no-tools number recorded so far comes from the arm as it was.** The agent arm, the
agent's prompt and the agent's packet function (`operations.investigator.case_packet`) are unchanged.

| | Arm of run1 | Corrected arm |
|---|---|---|
| Opening user message | the agent's packet with an empty tool list, under a prompt that says to work by calling tools | the same packet, then `arms.NOTOOLS_NOTE` in the same message: no tools are available on this case; conclude now, or conclude INSUFFICIENT_EVIDENCE and name what is missing and the next step. It names no cause |
| Retry | the opening messages plus one rejection line; the rejected reply was not in the conversation | the conversation continued: the rejected reply as the assistant's message, then the agent's own rejection line |
| Attempts | 2 calls in all, a tool-call reply using one | 2 attempts at a conclusion, which is what the agent's conclusion gets (`operations.investigator.ATTEMPTS_PER_TURN`: one call and its corrective retry); a reply that is not a conclusion (a tool call, no JSON object) is corrected once without using one, as the agent's are. At most 3 calls (`design.NOTOOLS_MAX_CALLS`); a provider failure gets one retry, as before |
| What is recorded | the outcome only (`texts` was `[""]` for a degraded reply) | `ArmResult.attempts`: every attempt's reply text (first 4,000 characters) and validation error. It is part of the result line, so it is in `results/` and `captured/arm_outputs/`, under the per-case marker screen and the scorer's scan. A rejected reply is recorded, never scored |

Consequences. The worst case per case is C_cap + R_cap + 3 (23 at C_cap 20), and `select` seals that. A selection
sealed before the correction still verifies (`design.sealed_notools_max_calls` recognises its hash), but `run`
refuses to run the corrected arm on it, because its budget holds 2 calls per case for this arm: select again. The
post hoc completion below sizes its own budget and may use the corrected arm; its manifest then says so. The validator
difference (no citation possible) is unchanged. These changes need a line in the next dated design amendment before
the corrected arm is used for a reported number (`tests/test_arms.py`).

## The checkpoint (`run --max-cases 40`, `checkpoint`, `run --resume`)

```
python -m stage3_eval run --selection DIR/selection.json --extras DIR/extras.json --out RUN --wiring scripts.stage3_wiring:build --max-cases 40
python -m stage3_eval checkpoint --selection DIR/selection.json --run RUN --wiring scripts.stage3_wiring:build_checkpoint [--out FILE]
python -m stage3_eval run --selection DIR/selection.json --extras DIR/extras.json --out RUN --wiring scripts.stage3_wiring:build --resume
```

`checkpoint` reads no truth and no score. It writes `RUN/checkpoint.json` with every condition and `"pass"`, and
exits 0 on pass, 3 on fail. Conditions (defaults; the first five are options: `--max-degraded`, `--max-cap-hit`,
`--max-provider-failures`, `--min-citations-valid`, `--min-opened`):

| Condition | Rule |
|---|---|
| agent-arm degraded rate | <= 0.15 |
| agent-arm cap-hit rate | <= 0.10 |
| provider failure rate (all parts of the run) | <= 0.05 |
| concluded agent cases whose citations are all valid (the run record's own check; with the resolver for a record without one) | >= 0.90 |
| settled cases that opened | >= 0.90 |
| agent cases with any retrieved or cited record recorded after the case's snapshot (resolver over the database, read-only) | 0 |
| marker screen over the captured surfaces so far (canary and mechanism-id shapes) | clean, every surface present |
| ledger reconciled with the provider's count after every settled case; no cap violation; campaign entry equal | yes |
| truth-side modules loaded in the run process (manifest) | none |
| run status | `paused` (or `completed`), of this selection |

A measure that could not be taken fails its condition. Resume only on a pass (`checkpoint.py`, `tests/test_checkpoint.py`).

## Taking the run in parts (`run --max-cases N`)

`run --max-cases N` stops before starting case N + 1 of the pre-registered order (the order of `selection.json`;
cases already settled in the run directory count), never inside a case. N counts the selection's cases: the run
cannot count the cases of the E1 gate cell, because it never learns a case's stratum. The stop reads that number and
nothing any case answered. The manifest's status is then `paused` (not invalid, not completed) and its `progress`
block gives N and the total. A paused run has no open reservation in `ledger.jsonl`, has run no extra and has not
opened `extras.json`, has captured the run-level surfaces as of the pause (`captured/<surface>/paused_after_NNNN.jsonl`),
and its campaign-ledger entry is settled at the calls committed so far, so the unspent part of its budget is free
until it is resumed. `run --resume` (with a larger N, or none) reserves the whole sealed budget again (refused if it
no longer fits), reruns, recaptures and reconciles no settled case (`settled.jsonl`), and ends with the results an
unpaused run gives (`tests/test_pause.py`). The manifest keeps every earlier part in `earlier_segments`; validity is
judged over all of them (provider failures summed, a part that ended as anything but paused makes the run invalid).

`score` and `report` work on a paused run. The report is then titled INTERIM, states "the first N of T cases in the
pre-registered order", shows the pass bars' counts with the verdict `interim (no verdict)` (the fixed test is on the
whole sample, once) and gives an interim validity verdict. Scoring reads truth, so do it in its own process and never
hand its output to a later part of the run.

## Completing a run after a provider failure (`rerun-failed`): post hoc, and labelled so

A run whose provider ran out of quota leaves cases whose agent or no-tools result is degraded with failure_mode
`model_unavailable`: the model was never asked, or never answered. In run1 that is the last 52 cases of the
pre-registered order, all in E2, in both model arms. `rerun-failed` re-runs exactly those and nothing else:

```
python -m stage3_eval rerun-failed --selection DIR/selection.json --run RUN --world E2 --dry-run
python -m stage3_eval rerun-failed --selection DIR/selection.json --run RUN --out NEW --wiring scripts.stage3_wiring:build_completion --world E2 [--arm agent,notools]
python -m stage3_eval score  --selection DIR/selection.json --run NEW --world E2=TRUTH_DIR --wiring scripts.stage3_wiring:build_scorer
python -m stage3_eval report --selection DIR/selection.json --run RUN --completion NEW
```

- **What is selected.** The cases of `RUN` whose main result in one of the named arms has failure_mode
  `model_unavailable`, of the world named, in the selection's order (`completion.plan`). A result that holds an
  answer (right, wrong, invalid, capped) is never re-run. `--dry-run` prints the list and its worst case and builds
  no wiring, opens no database and writes nothing.
- **Where it goes.** A new run directory. `RUN` is only read (its results, `cases.jsonl` and manifest); a completion
  into `RUN` or below it is refused (`tests/test_completion.py` compares the directory before and after).
- **The ledger.** As for `run`: the worst case of the listed cases and arms only (cases * (C_cap + R_cap + 3) for both
  arms) is the completion's own budget, reserved in the campaign ledger before the first case; each case is
  reconciled with the provider's count; the entry is settled at what was used. `--max-cases` and `--resume` work.
- **The manifest** carries `completion`: `post_hoc: true`, the label, the source run, the re-run case keys, the arms,
  each case's original snapshot time, and which no-tools arm ran. A completion that re-runs `notools` uses the
  corrected arm (above) while the rest of the source run's no-tools column comes from the arm as it was: the manifest
  and the report say so, and `--arm agent` leaves the no-tools column to the source run.
- **The replay clock.** Each case is investigated as of its original snapshot time (`RUN/cases.jsonl` `as_of`); a
  case that would be investigated at another time stops the run. `scripts.stage3_wiring:build_completion` does it
  without replaying anything: the agent arm is `operations.graph.investigate` as of that time with no commit (the
  path the extras use), on the database as the source run left it, which it only reads. That is the same graph,
  tools, investigator, reviewer, revision rounds, authority decision, cap and visible evidence as the main run's
  `store.process_one`; what is missing is everything that records: no claim, no run, recommendation, review or audit
  record, no workflow state, no execution step (executions, outcomes and final state are empty for these cases), and
  no snapshot-changed check. It refuses a database whose live session is not the source run's (after a reset the
  ingested records are gone). For that case `scripts.stage3_wiring:build_completion_replay` resets the session of that
  world only and replays the feed to each listed case in order through the main run's own path; the cases the source
  run investigated before them are then absent from the operations ledger, and the source run must be scored first.
- **Scoring and the report.** `score --run NEW` scores the completion like any run. `report --run RUN --completion NEW`
  writes the union report into `NEW`, never into `RUN`: for each re-run case and arm the completion's row replaces the
  source run's, every other row is the source run's own (`report.union_scores`). Every cell of the completed world,
  and any pass bar on it, is labelled "completed post hoc after a provider quota failure" with the number of cases
  re-run; the other world's cells are computed from the source run's rows only and are exactly as scored from it
  (tested). The sections pooled over every case include the re-run results, and the report says so.

It is a deviation from the pre-registered single pass, selected on the provider's failure and on no answer. It needs
a dated line in the design before a number that rests on it is reported.

## Design item to module

| Design item | Where |
|---|---|
| Budget (lifted 2026-10-11; see "Sizing and the ledger guard"): C_cap (+ R_cap) per agent case, sealed at selection (16 per amendment 3, R_cap 0), plus 3 for B_notools (2 before its correction); the sealed budget is the worst case of the selection, extras included | `design.worst_case_calls`, `selection.select`, `budget.py` |
| One campaign ledger for every real model call (`docs/evals/model_call_ledger.json`); its cap (20,000) is a runaway guard. `run` refuses to start only if spent + its worst case would cross it, reserves its worst case and writes what it used. `select --reserve N` and `select --stop-at N` are off by default; when given they are sealed and `run` also refuses past cap - N, or past N | `operations/call_ledger.py`, `__main__.py`, `runner.refuse_into_reserve`, `runner.refuse_past_stop_line`, `runner.run(campaign=...)` |
| Allocation: the design's targets (160 / 60 / 30+10 / 20+5 = 285), each cell capped by what the world holds; target, available and selected recorded per cell. The shrink order (`selection.allocate`) is historical and unused | `design.ALLOCATION_AT_PLANNING`, `selection.select` |
| The recorded checkpoint of a paused run (no truth) | `checkpoint.py`, `scripts/stage3_wiring.build_checkpoint` |
| Strata: identifiable ambiguous, determined (census of >= 5, else the generator map), unidentifiable | `strata.py` |
| Reproduces the Stage 0 S5 split (19 determined, 22 ambiguous) | `tests/test_strata_selection.py` |
| Truth knowable at t from the run's ingestion log (world.truth discrimination specs) | `truth_io.truth_at` |
| Seeds from the freeze commit (E1 k=1, E2 k=2) and seeded draws | `design.eval_seed`, `design.selection_seed` |
| Arms on the same cases: agent, B_notools, B_rulecode (frozen order), B_symptom (frozen table) | `arms.py` |
| One result per case, first case per shipment at its first investigation; degraded counts wrong | `records.from_ops_run`, `scoring.py` |
| Categories, honest uncertainty kept apart from confident wrong | `design.CATEGORIES`, `scoring.categorise` |
| Citation validity and evidence-grounded accuracy | `scoring._citation_audit` |
| Canary and truth-vocabulary scan with a planted positive control | `canary.py` |
| Per-case screen during the run (canary-shaped and mechanism-id-shaped tokens stop the run) | `canary.marker_hits`, `runner.run` |
| The backend's per-case cap equals the sealed C_cap; the ledger is reconciled with the provider's count after every case | `scripts/stage3_wiring.require_sealed_cap`, `budget.BudgetLedger.reconcile` |
| Correct answers split into observation level and mechanism level, per arm and stratum | `report.correct_level`, `report._levels` |
| Pass bars (E1 identifiable ambiguous: agent vs B_rulecode, agent vs B_notools, exact McNemar, alpha 0.05, more wins) | `design.PASS_BARS`, `report.py` |
| Wilson intervals, exact McNemar, paired difference interval, minimum detectable gain | `stats.py` |
| Abstention metrics, agreement with B_rulecode, symptom-name dependence, reviewer vs correctness, matched pairs, usage, latency, outcome rates | `report._details` |
| Exploratory extras (cross-shipment ablation on every eligible main-test case, stability on 40 seeded ones), fixed order, inside the sealed worst case, never pooled | `selection.select`, `runner._run_extras`, `report._extras` |
| Run validity (provider failures > 5%, crash, sealed-hash mismatch, dirty tree, canary hit) | `report._validity` |
| Post hoc completion of provider-failed cases (not in the design; labelled wherever it is used) | `completion.py`, `runner.run(only_keys=...)`, `report.union_scores`, `scripts/stage3_wiring.build_completion` |

## Answer categories

Exactly one per arm per case, in this precedence:

1. `unsafe_or_fabricated`: cites a record it did not retrieve, that does not resolve, or that was recorded after t;
   recommends a prohibited action; blame or GPS-as-delivery text; truth vocabulary in its output.
2. `degraded`: no valid conclusion (cap hit, provider failure, invalid output). Counted wrong.
3. `correct_supported`: knowable at t, acceptable primary cause, at least one valid citation that discriminates a
   mechanism accepting that cause (not the opening alert's own evidence).
4. `correct_unsupported`: knowable, acceptable primary, no such citation.
5. `honest_uncertainty`: not knowable at t, and the answer abstains (INSUFFICIENT_EVIDENCE or UNKNOWN).
6. `insufficient_when_knowable`: knowable at t, and the answer abstains. Wrong.
7. `confident_wrong`: a specific cause that is not acceptable at t.

Plain accuracy = 3 + 4 + 5. Evidence-grounded accuracy = 3 + 5.

## Running it here

From `chat/` (needs only the standard library and pytest):

```
python -m pytest stage3_eval -q
python -m stage3_eval dry-run --fixture --out /tmp/stage3-dry
```

The dry run selects over the two fixture worlds, runs every arm in dry-run mode (the ledger records the plan; zero
calls are reserved or settled, and the agent and model functions are never called), and writes the report skeleton.
On the fixture the cells are far below the design's sizes; the selection reports each shortfall.
