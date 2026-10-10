# Wiring the Stage 3 harness to the real investigator and database

For the backend track (branch `fhd`). The harness lives entirely in `chat/stage3_eval/` and edits no existing file.
Everything below is done on Fahad's machine; the harness itself opens no database and calls no model.

All data is synthetic. Nothing here describes real SPL operations.

## 1. What to add (one new file the backend track owns)

Create one module of your own, for example `chat/scripts/stage3_wiring.py`, with two functions. The CLI loads them
with `--wiring scripts.stage3_wiring:build` and `--wiring scripts.stage3_wiring:build_scorer` (run from `chat/`).

```python
from stage3_eval.arms import AgentArm, CaseRef, NoToolsArm, RuleCodeArm, SymptomArm
from stage3_eval.records import from_ops_run

def build(config, *, dry_run=False):
    # config.worlds["E1"]["database"] etc. name the databases that `world.export apply` already created.
    # Open the driver and the OperationsStore for each world here (never create, replace or reset a database).
    stores = {w: make_world_store(spec) for w, spec in config.worlds.items()}       # your helper
    return {
        "arms": {
            "agent": AgentArm(lambda case: run_case(stores[case.world], case), config.c_cap, config.r_cap),
            "notools": NoToolsArm(),            # default turn = operations.investigator.model_turn (same model and settings)
            "rulecode": RuleCodeArm(),
            "symptom": SymptomArm(),
        },
        "case_source": WorldCaseSource(stores),                                        # section 3
        "capture": WorldCapture(stores),                                               # section 6
        "extras_arms": {
            "cross_shipment_ablation": AgentArm(lambda c: investigate_as_of(stores[c.world], c, disabled=CROSS_SHIPMENT_TOOLS),
                                                config.c_cap, config.r_cap, name="cross_shipment_ablation"),
            "stability_rerun": AgentArm(lambda c: investigate_as_of(stores[c.world], c, disabled=()),
                                        config.c_cap, config.r_cap, name="stability_rerun"),
        },
        "provenance": provenance(),        # scripts/s5_scenarios.py provenance(): commit, dirty flag, model, prompt hashes,
                                           # and model_calls {"succeeded": {...}, "failed": {...}} from the LiteLLM callbacks
    }

def build_scorer(config):
    return {"ingestion": WorldIngestionLog(...), "resolver": WorldResolver(...)}       # section 7
```

The `config` passed in is the one sealed into `selection.json`; the run refuses any other (sealed hash check).

## 2. The agent arm: `run_case(store, case) -> ArmResult`

Drive the real pipeline on the one selected case, then read the result back from the ledger:

```python
def run_case(store, case):
    store.process_one(case.case_id, manual=True)      # tools, investigator, reviewer, authority, on this case only
    store.execute_step(limit=25)                      # Stage 4: authorised automatic actions
    case_row = read_one(store, "OpsCase", entity_id=case.case_id)
    runs = read_all(store, "OpsRun", case_id=case.case_id)
    return from_ops_run(case.key, case.shipment_id, case=case_row, runs=runs,
                        executions=read_all(store, "OpsExecution", case_id=case.case_id),
                        outcomes=read_all(store, "OpsOutcome", case_id=case.case_id))
```

- Keep the worker paused: the harness, not the FIFO worker, chooses which cases are investigated. Cases the monitor
  opens that are not in the selection are never investigated (they would spend calls outside the plan).
- The FIRST OpsRun of the case is scored (`from_ops_run` sorts by `recorded_at`); re-investigations are kept but are
  not the headline.
- **The call count.** Stage 2's per-case counter (investigator turns, reviewer rounds, revisions and retries, one
  counter, capped at C_cap in code) must be on the run record. `records.FIELDS["calls_used"]` tries
  `model_calls_used`, `calls_used`, `model_calls` on the analysis and on the OpsRun row; if Stage 2 names it otherwise,
  add the name there (that tuple is the only place to change). The ledger never counts the agent's calls a second
  way. A record without the field is settled at its full worst case and flagged. A count above C_cap + R_cap stops
  the run as a cap violation.
- If Stage 2 keeps a separate reviewer cap, put it in `EvalConfig.r_cap` before selecting: the sizing becomes
  `floor(4000 / (C_cap + R_cap + 2))` (addendum, item 1) and each agent case reserves C_cap + R_cap.
- Also map, if Stage 2 adds them: `tokens`, `cap_hit`, `wall_seconds`, `tool_seconds` (per tool query, seconds) in
  `records.FIELDS`. They feed the usage and latency sections; nothing is scored on them.

## 3. `CaseSource.case_ref(world, shipment_id) -> CaseRef | None`

Selection order is world by world, by the monitor's expected opening time (`expected_opened_at` in selection.json),
because the replay clock only moves forward. For each selected case:

1. Advance that world's replay (`store.tick(seconds=3600, manual=True)` and `monitor_step` until nothing is pending,
   as `scripts/s5_scenarios.py step_loop` does with `investigate=False`; also `outcome_step` so earlier cases'
   verifications keep running) until the monitor has opened a case for the shipment, or until a horizon past
   `expected_opened_at` (return None then; the harness records "case_not_opened_in_run").
2. Return `CaseRef(key, world, shipment_id, case_id=<OpsCase entity_id>, as_of=<store clock now>,
   symptoms=<opening symptoms from the CASE_OPENED audit>, rule_codes=<the case's rule codes at opening>,
   opening_evidence_ids=<the evidence ids the opening exception cites>)`.

`symptoms` and `rule_codes` feed B_symptom and B_rulecode; `opening_evidence_ids` are the alert's own evidence, which
does not count toward evidence-grounded accuracy. The no-tools arm is given the agent's own snapshot (`as_of` from the
agent's run record), so both model arms answer at the same t.

## 4. The no-tools arm

`NoToolsArm()` with no argument uses `operations.investigator.model_turn`, i.e. the agent's model and settings, its
`SYSTEM` prompt, cause catalogue (with INSUFFICIENT_EVIDENCE and UNKNOWN), action catalogue and output schema, given
the same opening packet with an empty tool list. At most 2 calls (one retry on invalid output, the agent's own retry
message); invalid after that counts as degraded, as for the agent.

One deliberate difference, which needs a line in the next dated design amendment: `investigate()`'s validator
requires a supported primary cause to cite retrieved evidence, so with no tools it would reject every specific
answer. The no-tools validator (`arms._notools_problem`) keeps every other rule and instead forbids any citation.
If Stage 2 adds a native no-tools mode to `investigate()` with the same two-call bound and the same rule, it can
replace `NoToolsArm.run` behind the same `Arm` interface.

## 5. The extras (exploratory)

They run only if calls remain after the main test, in the fixed order ablation then stability, and each extra case
is handed a `CaseRef` whose `as_of` is the MAIN agent run's snapshot (the clock has moved on by then). So they must
investigate **as of** `case.as_of` with the time-correct predicate, e.g. through `operations.graph.investigate(
shipment_id, as_of, ...)` with the Stage 2 `disabled=` tool set (the cross-shipment tools for the ablation, none for
stability), and **must not execute or record actions** on the case: they are read-only re-investigations. Return an
ArmResult (e.g. `records.from_investigation(...)` with `calls_used`).

## 6. Capture for the canary scan

`capture_case(case, results)` and `capture_run()` return `{surface: [text or JSON-able, ...]}`; the harness writes them
under `<run>/captured/<surface>/`. The design's five surfaces are all required, otherwise the scan reports
"incomplete" and the run is only "valid pending a complete canary scan":

| Surface | What to return |
|---|---|
| `tools` | every tool result the agent received for the case (the text the model saw), from Stage 2's per-round log or an `on_step` hook |
| `api` | the case API responses the UI would get for the case (case detail and list rows) |
| `receipts` | the case's execution receipts (OpsExecution `adapter_result_json`) and outcome records |
| `graph` | once per run: every node and relationship property of the run database (as `world.export check` scans) |
| `logs` | once per run: the run's log output |

## 7. The scorer seams (scorer process only, after the run)

- `IngestionLog.ingested(world, t) -> set[str]`: the evidence ids recorded at or before t in that world's database
  after the run, with the same rule as `world.validate.monitor_replay` (an imported record from its own
  `recorded_at`, a fed record from its ingestion). This is the `ingested` that `world.truth.labels_at` expects.
- `EvidenceResolver.recorded_at(world, ids) -> {id: recorded_at}`: e.g.
  `MATCH (n:V2Entity) WHERE n.entity_id IN $ids RETURN n.entity_id AS id, n.recorded_at AS at`.
  An id missing from the answer does not resolve and makes the answer "unsafe or fabricated".

## 8. The sequence

From `chat/`, on a clean tree (the run refuses a tree that is dirty or changes during the run, through provenance):

```
# 0. Freeze: investigator, tools, reviewer and C_cap fixed (C_cap = p95 of calls of correct development runs).
#    E1 and E2 seeds: python -c "from stage3_eval.design import eval_seed; print(eval_seed('<full commit>', 1), eval_seed('<full commit>', 2))"
# 1. Export and import E1 and E2 (backend track only; world.export export ... --truth-root ... ; world.export apply ...).
# 2. Pre-register (truth readable here only):
python -m stage3_eval select --world E1=<truth dir of E1>/development --world E2=<truth dir of E2>/development \
    --database E1=shipments-v2-world-<e1 name> --database E2=shipments-v2-world-<e2 name> --freeze-commit <full commit> --c-cap <C_cap> [--r-cap <R_cap>] --out ../docs/evals/<date>_stage3/preregistration
#    then commit selection.json, pairs.json, strata.json and their .sha256 files BEFORE any run.
# 3. Zero-call rehearsal on the real databases (no model call, no case investigated):
SUHAIL_EVAL_TRUTH_ROOT= python -m stage3_eval run --selection .../selection.json --out <run dir>-dry --wiring scripts.stage3_wiring:build --dry-run
# 4. The run (truth unreachable):
SUHAIL_EVAL_TRUTH_ROOT= python -m stage3_eval run --selection .../selection.json --out <run dir> --wiring scripts.stage3_wiring:build
# 5. Score and report (truth readable again):
python -m stage3_eval score --selection .../selection.json --run <run dir> --world E1=<truth dir> --world E2=<truth dir> \
    --wiring scripts.stage3_wiring:build_scorer
python -m stage3_eval report --selection .../selection.json --run <run dir>
```

`--resume` continues a crashed run in the same directory: settled cases are not rerun, a reservation that was open
at the crash is counted at its worst case and its case is scored as degraded. Every attempt, valid or not, keeps its
own directory and is disclosed (amendment 1, H).

## 9. What must not happen

- **No truth readable from any arm.** The run process never gets a truth path: `SUHAIL_EVAL_TRUTH_ROOT` unset (the
  run refuses to start otherwise), no truth or physical-state directory passed to the store, the tools, the reviewer,
  the API or the capture. Only `select` and `score` read truth, each in its own process. The Stage 4 operational
  simulator may read physical state only (never truth labels), as world/README.md section 5 requires.
- No `select` after any agent run on that world, and no edit to selection.json (the run checks its sha256).
- No second count of the agent's calls; no per-case call counter outside Stage 2's.
- No database created, replaced or reset by the harness wiring; `world.export apply` remains the only importer.
- No investigation of non-selected cases during the evaluation run; no FIFO worker running alongside it.
- No look at per-case traces before the full report is written; no change to prompts, tools or reviewer after the
  first evaluation run without new seeds (design header).
- No use of the extras or of E2 as a pass or fail; E1 identifiable ambiguous is the only gate.

## 10. Lines for the next dated design amendment

The harness had to decide these; none changes a bar, size or order already in the design. They should be recorded
in a dated amendment before E1 and E2 exist:

1. This harness commit is the committed stratum script and B_symptom table (amendment 1, C and F).
2. B_rulecode: `POSSIBLE_MISDELIVERY` (emitted by the derive rules, absent from amendment 1, C's list) and any other
   unlisted code follow the list, alphabetically.
3. B_symptom: DELIVERY_ATTEMPT_FAILED maps to RECIPIENT_UNAVAILABLE and MILESTONE_LATE to JOURNEY_DELAY; the primary
   is the first opening symptom in the B_rulecode order carried over to symptom names.
4. Strata: unidentifiable shipments are left out of the census; the pre-run stratum uses the generator's knowability
   estimate at the replica opening; scoring uses the run's ingestion log at the agent's snapshot, all arms at the same
   t, and the report counts cases whose knowability moved.
5. Within a cell, cases are drawn by a seeded round robin over the explaining mechanism types.
6. The no-tools validator difference in section 4.
7. Exact power: at 160 cases the minimum detectable gain is 13.5 points (discordance 0.35) to 15.3 points (0.45),
   slightly above amendment 2's "about 13 to 14"; at 60 cases 21.8 to 25.0.
8. Run order: world by world, by expected opening time.
