# Stage 3 blind evaluation harness (`chat/stage3_eval`)

Implements the frozen Stage 3 design (`docs/plans/2026-10-10_stage3_evaluation_design.md`: b1d331f, amendment 1
001bcbf, amendment 2 ac6f857 and its addendum 7af0d5c) and the independent review of it, so the real-model pilot and
the evaluation can start once Stage 2 lands. It makes no model call and opens no database: the backend track plugs in
the real investigator, tools and databases as described in [WIRING.md](WIRING.md).

All data is synthetic. Nothing here describes real SPL operations. The committed fixture under `fixtures/` is a
hand-specified stand-in labelled FIXTURE, not a world-1 export.

## Steps and the truth boundary

| Step | Process | Reads truth? | Writes |
|---|---|---|---|
| `select` | before any run | yes (truth.jsonl, monitor_replay_rows.jsonl) | `selection.json` (run side), `selection_scorer.json`, `extras.json`, `pairs.json`, `strata.json` (scorer side), each with `.sha256`, written once |
| `run` | the evaluation | **no**: refuses to start with `SUHAIL_EVAL_TRUTH_ROOT`, `SUHAIL_SIM_STATE_ROOT` or any variable naming TRUTH set (before the wiring is built); imports nothing truth-side (tested); invalid if a truth-side module is loaded when it ends | `ledger.jsonl`, `cases.jsonl`, `settled.jsonl`, `results/`, `captured/`, `run_manifest.json` |
| `score` | after the run | yes | `scores.jsonl`, `canary.json` |
| `report` | after scoring | no | `report.json`, `report.md` |

`selection.json` carries, per case, only its order, key, world, shipment and expected opening: no stratum, main-test
flag, extras list, cause, mechanism, label or canary (checked on write, and refused by the run on load); the run
checks it against its pre-registered sha256 and the sealed configuration hash before anything runs. The stratum and
main-test flag of each case and the allocation are in `selection_scorer.json`; the extras lists are in `extras.json`,
which the run opens only when `--extras` names it and only after the last main-test case. Shipments listed in
`docs/evals/2026-10-10_world1_pilot/excluded_shipments.json` are never drawn from a world with that dataset id
(`exclusions.py`).

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

## Design item to module

| Design item | Where |
|---|---|
| Budget: 4,000 calls, C_cap (+ R_cap) per agent case, 2 for B_notools, N_main = floor(4000 / (C_cap + R_cap + 2)) | `design.py`, `budget.py` |
| One campaign ledger for every real model call (`docs/evals/model_call_ledger.json`, cap 4,000): `select` seals budget = cap - spent, so N_main = floor(remaining / (C_cap + R_cap + 2)); `run` refuses to start past the cap, reserves its budget and writes what it used. `select --reserve N` keeps N calls out: budget = cap - spent - N, N sealed in the configuration, and `run` refuses if spent + budget would exceed cap - N | `operations/call_ledger.py`, `__main__.py`, `runner.run(campaign=...)` |
| Allocation (160 / 60 / 30+10 / 20+5 at C_cap 12) and the shrink order | `design.py`, `selection.allocate` |
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
| Exploratory extras (cross-shipment ablation, stability), fixed order, budget permitting, never pooled | `runner._run_extras`, `report._extras` |
| Run validity (provider failures > 5%, crash, sealed-hash mismatch, dirty tree, canary hit) | `report._validity` |

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
