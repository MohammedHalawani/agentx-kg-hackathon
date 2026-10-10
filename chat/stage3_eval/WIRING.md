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
        "provenance": provenance,          # a dict, or a callable evaluated when the run ends: commit, dirty flag, model,
                                           # prompt hashes and model_calls {"succeeded": {...}, "failed": {...}} from the
                                           # LiteLLM callbacks. The model is scripts/s5_scenarios.py at the REPOSITORY ROOT
                                           # (not chat/scripts), whose provenance(phase, started_at) takes two arguments.
    }

def build_scorer(config):
    return {"ingestion": WorldIngestionLog(...), "resolver": WorldResolver(...)}       # section 7
```

The `config` passed in is the one sealed into `selection.json`; the run refuses any other (sealed hash check).

## 2. The agent arm: `run_case(store, case) -> ArmResult`

Drive the real pipeline on the one selected case, then read the result back from the ledger:

```python
def run_case(ws, case):
    ws.store.process_one(case.case_id, manual=True)   # tools, investigator, reviewer, authority, on this case only
    ws.store.execute_step(limit=25)                   # Stage 4: authorised automatic actions
    case_row = ws.rows("OpsCase", entity_id=case.case_id)[0]
    runs = ws.rows("OpsRun", case_id=case.case_id)
    return from_ops_run(case.key, case.shipment_id, case=case_row, runs=runs,
                        executions=ws.rows("OpsExecution", case_id=case.case_id),
                        outcomes=ws.rows("OpsOutcome", case_id=case.case_id))
```

`ws.rows(kind, **where)` is the wiring's own read-only ledger reader (`WorldSession.rows` in
`chat/scripts/stage3_wiring.py`: the properties of this dataset's `OpsEntity` records of one kind, oldest first). The
backend has no `read_one` or `read_all` helper, as an earlier version of this page assumed. Do not use
`scripts/s5_scenarios.py` `case_rows` for this: that function joins the ledger with truth rows and belongs to a scorer.

- Keep the worker paused: the harness, not the FIFO worker, chooses which cases are investigated. Cases the monitor
  opens that are not in the selection are never investigated (they would spend calls outside the plan).
- The FIRST OpsRun of the case is scored (`from_ops_run` sorts by `recorded_at`); re-investigations are kept but are
  not the headline.
- **The call count.** Stage 2's per-case counter (investigator turns, reviewer rounds, revisions and retries, one
  counter, capped at C_cap in code) must be on the run record. `records.FIELDS["calls_used"]` reads
  `investigation_log.model_calls_used`, then the investigator's own budget at
  `investigation.model_calls.model_calls_used`, then `model_calls_used` and `calls_used` on the analysis and on the
  OpsRun row, and takes a whole number only, never the counter object (that tuple is the only place to change). The
  ledger never counts the agent's calls a second way. A record without a readable count is settled at its full worst
  case and flagged. A count above C_cap + R_cap stops the run as a cap violation.
- If Stage 2 keeps a separate reviewer cap, put it in `EvalConfig.r_cap` before selecting: the sizing becomes
  `floor(4000 / (C_cap + R_cap + 2))` (addendum, item 1) and each agent case reserves C_cap + R_cap.
- Also map, if Stage 2 adds them: `tokens`, `cap_hit`, `wall_seconds`, `tool_seconds` (per tool query, seconds) in
  `records.FIELDS`. They feed the usage and latency sections; nothing is scored on them.

## 3. `CaseSource.case_ref(world, shipment_id) -> CaseRef | None`

Selection order is world by world, by the monitor's expected opening time (`expected_opened_at` in selection.json),
because the replay clock only moves forward. For each selected case:

1. Advance that world's replay (`store.tick(seconds=3600, manual=True)` and `monitor_step` until nothing is pending,
   as `step_loop` in `scripts/s5_scenarios.py` (repository root) does with `investigate=False`; also `outcome_step` so earlier cases'
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
shipment_id, as_of, ...)` with its `disabled_tools=` keyword (the cross-shipment tools for the ablation, an empty
tuple for stability), and **must not execute or record actions** on the case: they are read-only re-investigations. Return an
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

Neither seam existed in the backend when this page was written: there is no `IngestionLog.ingested` and no
`EvidenceResolver.recorded_at` outside the wiring. The building blocks were the `recorded_at` query in
`scripts/s5_scenarios.py` `case_rows` (the `MATCH (n:V2Entity) WHERE n.entity_id IN $ids` read) and the `ingested`
closure inside `world.validate.monitor_replay`. As wired they are `WorldIngestionLog` and `WorldResolver` in
`chat/scripts/stage3_wiring.py` (section 11).

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
#    then commit selection.json, selection_scorer.json, extras.json, pairs.json, strata.json and their .sha256 files BEFORE any run.
#    The run reads selection.json only (key, world, shipment and expected opening per case). The other files are
#    derived from truth; extras.json is opened by the run only when --extras names it, after the last main-test case.
# 3. Zero-call rehearsal on the real databases (no model call, no case investigated):
SUHAIL_EVAL_TRUTH_ROOT= python -m stage3_eval run --selection .../selection.json --extras .../extras.json --out <run dir>-dry --wiring scripts.stage3_wiring:build --dry-run
# 4. The run (truth unreachable: no variable naming TRUTH and no SUHAIL_SIM_STATE_ROOT may be set):
SUHAIL_EVAL_TRUTH_ROOT= python -m stage3_eval run --selection .../selection.json --extras .../extras.json --out <run dir> --wiring scripts.stage3_wiring:build
# 5. Score and report (truth readable again):
python -m stage3_eval score --selection .../selection.json --run <run dir> --world E1=<truth dir> --world E2=<truth dir> \
    --wiring scripts.stage3_wiring:build_scorer
python -m stage3_eval report --selection .../selection.json --run <run dir>
```

`--resume` continues a crashed run in the same directory: settled cases are not rerun, a reservation that was open
at the crash is counted at its worst case and its case is scored as degraded. Every attempt, valid or not, keeps its
own directory and is disclosed (amendment 1, H).

`--max-cases N` takes step 4 in parts: the run stops before starting case N + 1 of the selection's order (settled
cases of the directory count; N is the only thing the stop reads), with status `paused`, no extras, and the campaign
ledger holding the calls committed so far. Continue with `--resume --max-cases M` (M > N) or `--resume` alone, in the
same directory and on the same live session (the wiring's `--resume` rule; do not reset the session or start another
run in between: the pause frees the unspent budget and the resume must be able to reserve it again). Step 5 works on
a paused run and labels its report an interim look over the first N of the total cases (README, "Taking the run in
parts"). The wiring needs no change: a resumed run asks `case_ref` for the settled cases again (the clock does not
move for them) and calls `capture_case` only for cases it settles itself; `capture_run` is also called at a pause.

## 9. What must not happen

- **No truth readable from any arm.** The run process never gets a truth path: `SUHAIL_EVAL_TRUTH_ROOT`,
  `SUHAIL_SIM_STATE_ROOT` and every variable whose name contains TRUTH unset (the command refuses before the wiring is
  built, and the run is invalid if a truth-side module is loaded in its process when it ends), no truth or physical-state directory passed to the store, the tools, the reviewer,
  the API or the capture. Only `select` and `score` read truth, each in its own process. The Stage 4 operational
  simulator may read physical state only (never truth labels), as world/README.md section 5 requires.
- No `select` after any agent run on that world, and no edit to selection.json (the run checks its sha256).
- No stratum, main-test flag, extras list or allocation in selection.json (the run refuses such a file), and no
  selection_scorer.json, pairs.json or strata.json handed to the run.
- No shipment of `docs/evals/2026-10-10_world1_pilot/excluded_shipments.json` as a case of a world with that dataset id.
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

## 11. As wired (`chat/scripts/stage3_wiring.py`, backend track)

What the wiring added to or settled about the sections above:

- **Wiring arguments.** The CLI passes a wiring function the keyword arguments it declares: `build(config, dry_run, resume,
  selection)` and `build_scorer(config, run_dir)`. The case source needs the selection's `expected_opened_at` (the
  horizon below); the scorer needs the run directory (session check, tool index). `provenance` is a callable, evaluated
  when the run ends. A wiring may return `close`, which the CLI calls.
- **Field names (section 2).** `records.FIELDS` reads `investigation_log.model_calls_used` (the one counter),
  `investigation_log.snapshot_as_of` and `investigation_log.cap_reached`. The run record holds no tokens and no times:
  tokens are the LiteLLM usage delta around the case, tool seconds are measured around each tool call.
- **Per-case cap.** Stage 2 has one counter for investigator and reviewer, so the store's cap is set to `C_cap` and
  `R_cap` stays 0.
- **Horizon (section 3).** A selected case is waited for until 2 hours after its expected opening
  (`OPEN_HORIZON_HOURS`); later cases are then investigated at a clock up to that much past their own opening.
  A run that returns `snapshot_changed` is not retried (a second run could pass the reservation): degraded, settled at
  the worst case.
- **Rule codes and opening evidence.** The case record stores symptoms only, so the rule codes and the evidence ids of
  the opening exceptions are recomputed with the monitor's own assessment on the evidence visible at the opening.
- **The live session.** A run starts from a fresh session. One that has advanced (a dry run, an earlier attempt) is
  continued only with `--resume`; otherwise the wiring refuses unless `SUHAIL_STAGE3_RESET_SESSION=1`, which runs the
  store's development reset of the operations ledger and live-ingested records (not a database reset; imported records
  stay). So after step 3 (the rehearsal) step 4 needs that variable. **Score before any reset:** the scorer refuses a
  database whose session is not the run's.
- **Capture (section 6).** Tool results are recorded as the model received them by wrapping `InvestigationTools.call`
  (nothing the model sees changes; tested). A sixth directory, `captured/tool_index/`, holds every id a tool listed
  as citable with its recorded time (a computed result: its snapshot). The graph dump is every node and relationship
  of the run database in batches of 500.
- **Resolver (section 7).** A cited id resolves from the database's `V2Entity` records first; an id that is not one
  (a tool-computed `DEMO-CMP-` result, a precedent, a device) resolves from `captured/tool_index/`, written by the
  tools' code. An id in neither does not resolve.
- **Campaign ledger.** `select` seals `budget = min(4000 - spent, 3600 - spent)` from `docs/evals/model_call_ledger.json`
  (3,600 is `design.STAGE3_STOP_AT`, where Stage 3 stops; addendum to amendment 3); `run` refuses to start past the cap
  or past that line, reserves the budget and writes what it used (README, design item table). `select --reserve N`
  seals `budget = min(4000 - spent - N, 3600 - spent)` and the reserve itself; `run` then also refuses if spent + budget
  would exceed 4000 - N.
- **Gate fixes (2026-10-11).**
  - *Cap equality.* `prepare_session` sets the store's `model_call_cap` to the sealed `C_cap`; `require_sealed_cap` reads
    it back through `investigator.CallBudget` at build and again before every case and extra, and stops the run
    (`budget.RunStopped`, never an arm error) if it is not exactly `C_cap`.
  - *Reconciliation.* `build` returns `provider_calls` (the LiteLLM callback count). After each case and each extra the
    runner writes a `reconcile` entry to `ledger.jsonl` with the ledger's calls and the provider's calls for this
    process, and stops the run if the provider counted more than the ledger holds.
  - *Selection files.* The run reads `selection.json` only; strata, main-test flags and the allocation are in
    `selection_scorer.json`, the extras lists in `extras.json` (`--extras`, opened after the main test). `score` and
    `report` join them with `selection.scorer_view`.
  - *Truth guard.* The pilot's guard (any set variable naming TRUTH, plus `SUHAIL_SIM_STATE_ROOT`) is applied by the
    command before the wiring is built; the manifest's `isolation` block records the variables set and the truth-side
    modules loaded at the end.
  - *Per-case screen.* Each case's captured surfaces and arm outputs are screened for canary-shaped and
    mechanism-id-shaped tokens as the run goes (`canary.marker_hits`); a hit stops the run after the evidence is written.
    The scorer's scan with the real vocabulary remains the verdict.
  - *Exclusions.* `refuse_excluded` refuses a selection naming a shipment on the exclusion list of the dataset the
    database holds, and the case source stops the run rather than hand one to an arm (`stage3_eval/exclusions.py`).
