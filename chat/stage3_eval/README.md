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
| `select` | before any run | yes (truth.jsonl, monitor_replay_rows.jsonl) | `selection.json`, `pairs.json`, `strata.json`, each with `.sha256`, written once |
| `run` | the evaluation | **no**: refuses to start with `SUHAIL_EVAL_TRUTH_ROOT` set; imports nothing truth-side (tested) | `ledger.jsonl`, `cases.jsonl`, `results/`, `captured/`, `run_manifest.json` |
| `score` | after the run | yes | `scores.jsonl`, `canary.json` |
| `report` | after scoring | no | `report.json`, `report.md` |

`selection.json` carries no cause, mechanism, label or canary (checked on write); the run checks it against its
pre-registered sha256 and the sealed configuration hash before anything runs.

## Design item to module

| Design item | Where |
|---|---|
| Budget: 4,000 calls, C_cap (+ R_cap) per agent case, 2 for B_notools, N_main = floor(4000 / (C_cap + R_cap + 2)) | `design.py`, `budget.py` |
| One campaign ledger for every real model call (`docs/evals/model_call_ledger.json`, cap 4,000): `select` seals budget = cap - spent, so N_main = floor(remaining / (C_cap + R_cap + 2)); `run` refuses to start past the cap, reserves its budget and writes what it used | `operations/call_ledger.py`, `__main__.py`, `runner.run(campaign=...)` |
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
