"""Wires the Stage 3 harness (chat/stage3_eval) to the real investigator and the world databases, as
stage3_eval/WIRING.md asks. Loaded by the harness, from chat/:

  python -m stage3_eval run   --selection .../selection.json --out RUN --wiring scripts.stage3_wiring:build [--dry-run]
  python -m stage3_eval score --selection .../selection.json --run RUN --world E1=TRUTH ... --wiring scripts.stage3_wiring:build_scorer

build(config, dry_run, resume, selection) -> arms, case source, capture, extras, provenance (the run process: no truth).
build_scorer(config, run_dir)             -> ingestion log and evidence resolver (the scorer process, after the run).

What the run side does, and does not do:
- Opens OperationsStore on each world's database (config.worlds[W]["database"], created by world.export apply; this
  module never creates, replaces or drops a database) with agents = operations.investigator and no execution adapter.
- Replays each world's feed hour by hour (tick, monitor_step until nothing is pending, outcome_step) only as far as
  the next selected case needs, so the clock only moves forward and a case is investigated at the tick it opens.
- Investigates a selected case with store.process_one(case_id, manual=True), then store.execute_step, and reads the
  result back from the ledger with stage3_eval.records.from_ops_run. Cases the monitor opens that are not selected
  are never investigated. The store's own per-case counter is the only count of the agent's calls.
- The extras re-investigate as of the main run's snapshot through operations.graph.investigate with the disabled
  tool set, with no commit: nothing is recorded or executed for them.
- Captures the five canary surfaces: tool results as the model received them, the case API responses, execution
  receipts and outcomes, a property dump of the run database, and the run's log output.
- A dry run drives the replay (ticks and the monitor) and reads the cases; it investigates nothing and calls no model.

The live session. A run needs the replay at its start. A session that has already advanced (an earlier attempt, a
pilot, a dry run) is continued only with --resume; otherwise the wiring refuses, unless SUHAIL_STAGE3_RESET_SESSION=1
is set, in which case it runs the store's development reset (operations ledger and live-ingested records of this
dataset only; imported records are never touched), exactly as scripts/world_pilot.py does. Score a run BEFORE the
session is reset again: the ingestion times in the database are that run's, and the scorer refuses another session.

No truth: this module never imports the world's truth-label or mechanism modules or the harness's scorer side, opens
no file outside the run's own outputs, and refuses to build the run side while a truth path variable is set.
"""
from datetime import timedelta
import json
import logging
import os
from pathlib import Path
import sys
import time

from stage3_eval.arms import AgentArm, CaseRef, NoToolsArm, RuleCodeArm, SymptomArm
from stage3_eval.budget import RunStopped
from stage3_eval.exclusions import excluded_in, load_exclusions
from stage3_eval.records import ArmResult, from_ops_run

ROOT = Path(__file__).resolve().parents[2]
RESET_ENV = "SUHAIL_STAGE3_RESET_SESSION"
OPEN_HORIZON_HOURS = 2      # A selected case is waited for until this long after the monitor replica's expected opening.
TICK_SECONDS = 3600         # The replica that produced the expected openings ticks hourly (world.validate.monitor_replay).
MONITOR_LIMIT = 25
GRAPH_BATCH = 500
LEDGER_KINDS = ("OpsCase", "OpsRun", "OpsExecution", "OpsOutcome", "OpsAudit")
LEDGER_FILTERS = ("entity_id", "case_id", "session_id", "event_type", "shipment_id")
log = logging.getLogger("stage3_wiring")


def _pilot():
    """scripts/world_pilot.py (repository root): the store opener, the development reset and the provider-call record."""
    path = str(ROOT / "scripts")
    if path not in sys.path:
        sys.path.insert(0, path)
    import world_pilot
    return world_pilot


def _iso(value):
    from operations.schema import public_value
    return public_value(value)


# ---------------------------------------------------------------------- one world: its store and its ledger
class WorldSession:
    """One evaluation world on its database: the store, the reader and read-only access to the operations ledger."""

    def __init__(self, world, driver, database, store, reader, manifest_hash):
        self.world, self.driver, self.database = world, driver, database
        self.store, self.reader, self.manifest_hash = store, reader, manifest_hash
        self.dataset_id = store.dataset_id
        self.notes = []

    def clock(self):
        return self.store.status()["as_of"]

    def rows(self, kind, **where):
        """Properties of this dataset's ledger records of one kind, oldest first."""
        if kind not in LEDGER_KINDS or set(where) - set(LEDGER_FILTERS):
            raise ValueError("unregistered ledger read")
        clause = "".join(f" AND n.{key} = ${key}" for key in sorted(where))
        with self.driver.session(database=self.database, default_access_mode="READ") as session:
            found = session.run(f"MATCH (n:OpsEntity:{kind}) WHERE n.dataset_id = $dataset{clause} "
                                "RETURN properties(n) AS props ORDER BY n.recorded_at, n.entity_id", dataset=self.dataset_id, **where)
            return [_iso(dict(r["props"])) for r in found]

    def opening_facts(self, shipment_id, at):
        """(rule codes, evidence ids) of the exceptions the monitor's rules raise for the shipment on the evidence
        visible at `at`: the same assessment monitor_step makes when it opens the case."""
        from dataset_v2.derive import assess_shipment
        from operations.reasoning import evidence_world
        from operations.store import DETECTION_ALLOWANCE_SECONDS
        context = self.reader.evidence(shipment_id, at)
        assessment = assess_shipment(evidence_world(context, self.store.config), shipment_id, context["as_of"],
                                     detection_allowance_seconds=DETECTION_ALLOWANCE_SECONDS)
        exceptions = assessment.get("exceptions") or []
        return (tuple(sorted({e["code"] for e in exceptions})),
                tuple(sorted({i for e in exceptions for i in e.get("evidence_ids") or [] if isinstance(i, str)})))

    def api_responses(self, case):
        """What the UI gets for the case: its detail (GET /cases/{id}) and its queue row."""
        out = [{"endpoint": "case_detail", "response": self.reader.case_detail(case.case_id)}]
        try:
            page = self.reader.queue(limit=25, search=case.shipment_id)
        except Exception as error:   # The failure is captured, not hidden.
            page = {"error": type(error).__name__}
        out.append({"endpoint": "queue", "response": page})
        return out

    def graph_dump(self):
        """Every node and relationship property of the database, in batches (as world.export's isolation scan reads it)."""
        with self.driver.session(database=self.database, default_access_mode="READ") as session:
            for kind, query in (("nodes", "MATCH (n) RETURN labels(n) AS l, properties(n) AS p"),
                                ("relationships", "MATCH ()-[r]->() RETURN type(r) AS l, properties(r) AS p")):
                batch = []
                for record in session.run(query):
                    batch.append({"labels" if kind == "nodes" else "type": record["l"], "properties": _iso(dict(record["p"]))})
                    if len(batch) >= GRAPH_BATCH:
                        yield {"world": self.world, "database": self.database, kind: batch}
                        batch = []
                if batch:
                    yield {"world": self.world, "database": self.database, kind: batch}


def open_world(driver, world, spec, agents):
    database = (spec or {}).get("database")
    if not database:
        raise SystemExit(f"the sealed configuration names no database for {world} (select with --database {world}=<name>)")
    store, reader, manifest_hash = _pilot().open_store(driver, database, agents)
    return WorldSession(world, driver, database, store, reader, manifest_hash)


def backend_cap(store):
    """The per-case model-call cap the backend will enforce for this store's next investigation: the investigator's
    own reading of the store's setting (None there means the environment's default, which is not the sealed one)."""
    from operations import investigator
    return investigator.CallBudget(store.model_call_cap).cap


def require_sealed_cap(ws, c_cap):
    """The backend's per-case cap must BE the sealed C_cap, not merely fit under the reservation: a lower cap would
    degrade cases the design allows to finish, a higher one would break the reservation. Stops the run otherwise."""
    cap = backend_cap(ws.store)
    if ws.store.model_call_cap != c_cap or cap != c_cap:
        raise RunStopped(f"{ws.database}: the backend's per-case model-call cap is {cap} (store setting {ws.store.model_call_cap!r}); "
                         f"the sealed C_cap is {c_cap}")
    return cap


def prepare_session(ws, *, resume, c_cap, allow_reset=None):
    """Put one world's store in the state a run needs: caps set, worker paused, replay at its start (or, with resume,
    where the earlier attempt left it). Returns what was done, for the run's provenance."""
    from operations import investigator
    if not isinstance(c_cap, int) or c_cap < 3 or investigator.CallBudget(c_cap).cap != c_cap:
        raise SystemExit(f"C_cap {c_cap} is outside what one investigation needs (at least 3 calls: a tool call, a conclusion, a review)")
    ws.store.model_call_cap = int(c_cap)     # The one per-case counter, capped in code at C_cap.
    ws.store.disabled_tools = ()             # The main run withholds nothing, whatever SUHAIL_DISABLED_TOOLS says.
    status = ws.store.status()
    done = {"database": ws.database, "dataset_id": ws.dataset_id, "manifest_hash": ws.manifest_hash, "execution_adapter": status["execution"]["adapter"],
            "per_case_model_call_cap": int(c_cap), "session_reset": False}
    if status["worker"]["state"] == "running":
        ws.store.control("worker", "pause")  # The harness, not the first-in-first-out worker, chooses what is investigated.
        done["worker_paused_by_wiring"] = True
    session = status["session"]
    fresh = bool(session.get("session_id")) and not status["simulator"]["event_count"] and not session.get("monitor_checked") \
        and not ws.rows("OpsCase", session_id=session["session_id"])
    if not fresh and not resume:
        nothing_to_lose = not session.get("session_id") and not ws.rows("OpsRun")
        allowed = os.environ.get(RESET_ENV) == "1" if allow_reset is None else allow_reset
        if not (nothing_to_lose or allowed):
            raise SystemExit(f"{ws.database}: the live session has already advanced (clock {status['as_of']}). Continue it with --resume, or, "
                             f"if its earlier run is scored and no longer needed, set {RESET_ENV}=1 to reset the operations ledger and the "
                             "live-ingested records of this dataset (imported records are never touched).")
        _pilot().reset_ledger(ws.store)
        done["session_reset"] = True
        status = ws.store.status()
    done.update(session_id=status["session"]["session_id"], clock_at_start=status["as_of"], resumed=bool(resume and not fresh))
    return done


# ---------------------------------------------------------------------- the case source (WIRING.md section 3)
class WorldCaseSource:
    """Advances each world's replay until the selected case opens. The clock only moves forward, so the harness asks
    for cases in the selection's order (world by world, by expected opening time)."""

    def __init__(self, sessions, expected=None, *, horizon_hours=OPEN_HORIZON_HOURS, exclusions=None):
        self.sessions = sessions
        self.exclusions = load_exclusions()[0] if exclusions is None else exclusions   # {dataset id: shipment ids}
        self.expected = dict(expected or {})      # {(world, shipment_id): expected_opened_at}
        self.horizon = timedelta(hours=horizon_hours)
        self.cases = {world: {} for world in sessions}            # shipment id -> the FIRST case the monitor opened for it
        self.counts = {world: {"hours": 0, "ingested": 0, "rejected": 0, "monitor_checked": 0, "cases_opened": 0} for world in sessions}
        for world, ws in sessions.items():
            session_id = ws.store.status()["session"].get("session_id")
            for case in ws.rows("OpsCase", session_id=session_id) if session_id else []:   # A resumed session's cases.
                self._note(world, case)

    def _note(self, world, case):
        ws = self.sessions[world]
        self.counts[world]["cases_opened"] += 1
        sid = case["shipment_id"]
        if sid in self.cases[world] and str(self.cases[world][sid]["opened_at"]) <= str(case["opened_at"]):
            return
        opened = [a for a in ws.rows("OpsAudit", case_id=case["entity_id"], event_type="CASE_OPENED")]
        text = (opened[0].get("result") or "") if opened else ""
        symptoms = sorted(s.strip() for s in text.split(":", 1)[1].split(",") if s.strip()) if ":" in text else sorted(case.get("symptom_codes") or [])
        codes, evidence = ws.opening_facts(sid, case["opened_at"])
        self.cases[world][sid] = {"case_id": case["entity_id"], "opened_at": case["opened_at"], "symptoms": tuple(symptoms),
                                  "rule_codes": codes, "opening_evidence_ids": evidence}

    def advance(self, world):
        """One hour of the world's feed: ingest, let the monitor check every queued shipment, verify due outcomes.
        Returns False when the clock did not move (the replay has ended)."""
        ws, counts = self.sessions[world], self.counts[world]
        before = ws.clock()
        tick = ws.store.tick(seconds=TICK_SECONDS, manual=True, speed=1)
        counts["hours"] += 1
        counts["ingested"] += tick.get("events_replayed", 0)
        counts["rejected"] += tick.get("rejected", 0)
        while ws.store.status()["session"]["monitor_pending"]:
            step = ws.store.monitor_step(limit=MONITOR_LIMIT)
            counts["monitor_checked"] += step["checked"]
            for case_id in step["opened"]:
                for case in ws.rows("OpsCase", entity_id=case_id):
                    self._note(world, case)
        ws.store.outcome_step(limit=50)      # Earlier cases' verifications keep running.
        return tick["as_of"] != before

    def case_ref(self, world, shipment_id):
        from dataset_v2.contracts import instant
        ws = self.sessions[world]
        if excluded_in(self.exclusions, ws.dataset_id, [shipment_id]):
            # Its truth labels were exposed: it is never an evaluation case, whatever the selection says.
            raise RunStopped(f"{world} {shipment_id} is on the exclusion list of dataset {ws.dataset_id}")
        expected = self.expected.get((world, shipment_id))
        # Without an expected opening the case is waited for over the horizon from where the clock stands.
        deadline = instant(expected or ws.clock()) + self.horizon
        while shipment_id not in self.cases[world] and instant(ws.clock()) < deadline:
            if not self.advance(world):
                break
        case = self.cases[world].get(shipment_id)
        if case is None:
            log.info("%s %s: no case opened by %s (expected %s)", world, shipment_id, ws.clock(), expected)
            return None
        return CaseRef(key=f"{world}:{shipment_id}", world=world, shipment_id=shipment_id, case_id=case["case_id"], as_of=ws.clock(),
                       symptoms=case["symptoms"], rule_codes=case["rule_codes"], opening_evidence_ids=case["opening_evidence_ids"])


# ---------------------------------------------------------------------- what the model was shown (tools surface)
class ToolTap:
    """The investigator and reviewer of the run, unchanged, with every tool result recorded as the model received it.
    Standing in for `agents` on the store, it changes no prompt, tool or answer: it wraps InvestigationTools.call."""

    def __init__(self, agents):
        self.agents = agents
        self.calls, self.belts = [], []

    def _tap(self, tools):
        if any(belt is tools for belt in self.belts):
            return
        self.belts.append(tools)
        original = tools.call

        def call(tool, args):
            started = time.perf_counter()
            output = original(tool, args)
            self.calls.append({"shipment_id": getattr(tools, "sid", None), "as_of": getattr(tools, "as_of", None), "tool": tool, "args": args,
                               "seconds": round(time.perf_counter() - started, 4), "output": output})
            return output
        tools.call = call

    def investigate(self, tools, *, turn=None, on_step=None, feedback=None, session=None, review=None):
        self._tap(tools)
        extra = {k: v for k, v in (("turn", turn),) if v is not None}
        return self.agents.investigate(tools, on_step=on_step, feedback=feedback, session=session, review=review, **extra)

    def review(self, conclusion, records, checks, symptoms, *, ask=None, context=None, session=None):
        extra = {k: v for k, v in (("ask", ask),) if v is not None}
        return self.agents.review(conclusion, records, checks, symptoms, context=context, session=session, **extra)

    def drain(self):
        """(tool calls, evidence index) since the last drain. The index holds every id a tool listed as citable with the
        time it was recorded (a tool-computed result: the snapshot it was computed at). It is written by the tools'
        code, never by the model, and lets the scorer resolve cited ids that are not graph records of the database."""
        calls, belts, self.calls, self.belts = self.calls, self.belts, [], []
        index = {}
        for tools in belts:
            as_of = getattr(tools, "as_of", None)
            for key, meta in (getattr(tools, "index", None) or {}).items():
                computed = (getattr(tools, "computed", None) or {}).get(key) or {}
                index[key] = {"kind": meta.get("kind"), "scope": meta.get("scope"), "shown_as_of": as_of,
                              "recorded_at": meta.get("recorded_at") or computed.get("computed_as_of")}
        return calls, index


def _degraded(case, mode, **extra):
    return ArmResult(case_key=case.key, arm="agent", shipment_id=case.shipment_id, case_id=case.case_id, as_of=case.as_of, degraded=True,
                     failure_mode=mode, **extra)


def run_case(ws, case, *, tap=None, tokens=None, c_cap=None):
    """The agent arm on one opened case (WIRING.md section 2): the real pipeline on this case only, read back from the
    ledger. The calls are the run record's own counter; a run that left no record is settled at its worst case.
    With c_cap, the backend's cap is checked against the sealed one before anything is called (RunStopped if not)."""
    if c_cap is not None:
        require_sealed_cap(ws, c_cap)
    tokens_before = tokens() if tokens else None
    seconds_from = len(tap.calls) if tap else 0
    outcome = ws.store.process_one(case.case_id, manual=True)      # tools, investigator, reviewer, authority
    if not outcome.get("processed"):
        # Not retried: an aborted run's calls are in no stored record, and a second run could pass the reservation.
        return _degraded(case, f"not_processed:{outcome.get('reason') or 'case_not_claimable'}")
    execution_error = None
    try:
        ws.store.execute_step(limit=25)                            # authorised automatic actions (no adapter: not acknowledged)
    except Exception as error:
        execution_error = type(error).__name__
        log.warning("%s: execute_step failed (%s)", case.key, execution_error)
    rows = ws.rows("OpsCase", entity_id=case.case_id)
    result = from_ops_run(case.key, case.shipment_id, case=rows[0] if rows else {"entity_id": case.case_id},
                          runs=ws.rows("OpsRun", case_id=case.case_id), executions=ws.rows("OpsExecution", case_id=case.case_id),
                          outcomes=ws.rows("OpsOutcome", case_id=case.case_id))
    if tokens:
        result.tokens = tokens() - tokens_before
    if tap:
        result.tool_seconds = [c["seconds"] for c in tap.calls[seconds_from:]]
    if execution_error:
        result.texts.append(f"execute_step failed: {execution_error}")
    return result


def investigate_as_of(ws, case, *, disabled=(), tap=None, tokens=None, arm="extra", c_cap=None):
    """An exploratory extra (WIRING.md section 5): the same investigation as of the main run's snapshot with some
    tools withheld. Read-only: no commit, so no run, recommendation, execution or audit is written for the case."""
    from operations.graph import investigate
    if c_cap is not None:
        require_sealed_cap(ws, c_cap)
    tokens_before = tokens() if tokens else None
    seconds_from = len(tap.calls) if tap else 0
    reader, store = ws.reader, ws.store
    analysis, _ = investigate(case.shipment_id, case.as_of, store.config, reader.evidence,
                              lambda sid, codes: reader.precedents(sid, codes, as_of=case.as_of),
                              commit=None, on_event=None, agents=store.agents, live_session=True, symptoms=list(case.symptoms),
                              heartbeats=getattr(reader, "heartbeats", None), port=getattr(reader, "fetch", None),
                              disabled_tools=tuple(disabled), call_cap=store.model_call_cap)
    result = from_ops_run(case.key, case.shipment_id, case={"entity_id": case.case_id},
                          runs=[{"recorded_at": case.as_of, "result_json": analysis}])
    result.arm = arm
    if tokens:
        result.tokens = tokens() - tokens_before
    if tap:
        result.tool_seconds = [c["seconds"] for c in tap.calls[seconds_from:]]
    return result


# ---------------------------------------------------------------------- capture for the canary scan (section 6)
class LogCapture(logging.Handler):
    """The run's log output: every record that reaches the root logger while the run is going."""

    def __init__(self):
        super().__init__(level=logging.INFO)
        self.lines = []
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))

    def emit(self, record):
        try:
            self.lines.append(self.format(record))
        except Exception:
            self.lines.append(f"{record.levelname} {record.name} (unformattable record)")


class WorldCapture:
    def __init__(self, sessions, tap=None, logs=None):
        self.sessions, self.tap, self.logs = sessions, tap, logs
        self.extra_tools, self.extra_index = [], []

    def stash_extra(self, case, arm):
        """Keep an extra's tool results and index (extras run after the per-case capture) for capture_run."""
        calls, index = self.tap.drain() if self.tap else ([], {})
        self.extra_tools.append({"case": case.key, "arm": arm, "calls": calls})
        self.extra_index.append({"world": case.world, "case": case.key, "arm": arm, "index": index})

    def capture_case(self, case, results):
        ws = self.sessions[case.world]
        calls, index = self.tap.drain() if self.tap else ([], {})
        receipts = [{"kind": kind, "record": row} for kind in ("OpsExecution", "OpsOutcome") for row in ws.rows(kind, case_id=case.case_id)]
        return {"tools": [{"case": case.key, "calls": calls}],
                "tool_index": [{"world": case.world, "case": case.key, "index": index}],
                "api": ws.api_responses(case),
                # A case with no execution still yields a line, so the surface is never silently absent.
                "receipts": receipts or [{"kind": "none", "case_id": case.case_id, "note": "no execution or outcome recorded for this case"}]}

    def capture_run(self):
        lines = list(self.logs.lines) if self.logs else []
        out = {"graph": (item for ws in self.sessions.values() for item in ws.graph_dump()),
               "logs": [{"captured": "root logger, level INFO and above", "records": len(lines)}, *lines]}
        if self.extra_tools:
            out["tools"], out["tool_index"] = list(self.extra_tools), list(self.extra_index)
        return out


def refuse_excluded(sessions, selection, exclusions=None):
    """Refuse (before anything runs) a selection that names a shipment on the exclusion list of the dataset its
    world's database holds. Returns the lists that were applied, for the provenance."""
    by_dataset, sources = load_exclusions() if exclusions is None else exclusions
    for world, ws in sessions.items():
        named = [row["shipment_id"] for row in (selection or {}).get("cases", []) if row["world"] == world]
        listed = excluded_in(by_dataset, ws.dataset_id, named)
        if listed:
            raise SystemExit(f"the selection names {len(listed)} shipment(s) of {world} that are on the exclusion list of dataset "
                             f"{ws.dataset_id} (truth labels exposed): {', '.join(listed[:5])}. Select again; the selection step leaves them out.")
    return sources


# ---------------------------------------------------------------------- build (the run process)
def build(config, *, dry_run=False, resume=False, selection=None, agents=None, notools_turn=None, driver=None, allow_reset=None,
          provider_calls=None):
    """The run side. `agents`, `notools_turn`, `driver`, `allow_reset` and `provider_calls` are for tests (a scripted
    model, a given driver, a stand-in for the provider's call count); the command line passes none of them, so the real
    investigator and model are used and the provider count is LiteLLM's callbacks."""
    pilot = _pilot()
    pilot.refuse_truth_access()
    from operations import investigator
    from operations.tools import CROSS_SHIPMENT_TOOLS
    real_model = agents is None and not dry_run
    code_state = pilot.git_state()
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    logs = LogCapture()
    logging.getLogger().addHandler(logs)
    log.setLevel(logging.INFO)
    owns_driver = driver is None
    if driver is None:
        import config as settings
        from neo4j import GraphDatabase
        logging.getLogger("neo4j").setLevel(logging.ERROR)
        driver = GraphDatabase.driver(settings.NEO4J_URI, auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD))
    tap = ToolTap(agents or investigator)
    sessions, prepared = {}, {}
    for world, spec in config.worlds.items():
        sessions[world] = open_world(driver, world, spec, tap)
        prepared[world] = prepare_session(sessions[world], resume=resume, c_cap=config.c_cap, allow_reset=allow_reset)
        # Equality with the sealed cap, read back from the store the investigations will use (and again before each case).
        prepared[world]["backend_model_call_cap"] = require_sealed_cap(sessions[world], config.c_cap)
        log.info("%s: %s session %s clock %s", world, prepared[world]["database"], prepared[world]["session_id"], prepared[world]["clock_at_start"])
    exclusion_sources = refuse_excluded(sessions, selection)
    if real_model:
        pilot.record_model_calls()           # LiteLLM callbacks: every provider call, completed or failed, and its tokens
    tokens = (lambda: pilot.MODEL_CALLS["total_tokens"]) if real_model else None
    expected = {(row["world"], row["shipment_id"]): row.get("expected_opened_at") for row in (selection or {}).get("cases", [])}
    source = WorldCaseSource(sessions, expected)
    capture = WorldCapture(sessions, tap, logs)

    def extra(name, disabled):
        def run_extra(case):
            try:
                return investigate_as_of(sessions[case.world], case, disabled=disabled, tap=tap, tokens=tokens, arm=name, c_cap=config.c_cap)
            finally:
                capture.stash_extra(case, name)
        return AgentArm(run_extra, config.c_cap, config.r_cap, name=name)

    def provenance():
        import config as settings
        from dataset_v2.contracts import digest
        now = pilot.git_state()
        calls = json.loads(json.dumps(pilot.MODEL_CALLS)) if real_model else {"succeeded": {}, "failed": {}, "prompt_tokens": 0,
                                                                              "completion_tokens": 0, "total_tokens": 0}
        return {"wiring": "chat/scripts/stage3_wiring.py", "commit": code_state[0], "dirty_tree": code_state[1],
                "tree_changed_during_run": now != code_state, "started_at": started_at,
                "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "model": "scripted (test)" if agents is not None else "none (dry run)" if dry_run else settings.LLM_MODEL,
                "model_api_base": settings.LLM_API_BASE if real_model else None,
                "investigator_prompt_sha256": digest(investigator.SYSTEM), "reviewer_prompt_sha256": digest(investigator.REVIEWER_SYSTEM),
                "cause_catalogue_sha256": digest(investigator.cause_catalogue()),
                "model_calls": calls, "open_horizon_hours": OPEN_HORIZON_HOURS, "tick_seconds": TICK_SECONDS,
                "cross_shipment_tools_withheld_in_the_ablation": list(CROSS_SHIPMENT_TOOLS),
                "worlds": {w: {**prepared[w], "clock_at_end": sessions[w].clock(), "replay": source.counts[w]} for w in sessions},
                "exclusion_lists": exclusion_sources,
                "truth_environment_set": pilot.truth_environment(), "world_truth_imported": pilot.truth_module_loaded()}

    def close():
        logging.getLogger().removeHandler(logs)
        if owns_driver:
            driver.close()

    return {"arms": {"agent": AgentArm(lambda case: run_case(sessions[case.world], case, tap=tap, tokens=tokens, c_cap=config.c_cap),
                                       config.c_cap, config.r_cap),
                     "notools": NoToolsArm(turn=notools_turn),    # None: operations.investigator.model_turn, the agent's model
                     "rulecode": RuleCodeArm(), "symptom": SymptomArm()},
            "case_source": source, "capture": capture,
            "extras_arms": {"cross_shipment_ablation": extra("cross_shipment_ablation", CROSS_SHIPMENT_TOOLS),
                            "stability_rerun": extra("stability_rerun", ())},
            # Every provider call of this process, completed or failed: the harness compares it with its ledger after each case.
            "provider_calls": pilot.provider_calls if real_model else provider_calls,
            "provenance": provenance, "close": close, "sessions": sessions}


# ---------------------------------------------------------------------- the scorer seams (section 7)
class WorldIngestionLog:
    """ingested(world, t): the evidence ids the run held at t, by world.validate.monitor_replay's rule: an imported
    record from its own recorded_at, a fed record from the tick that ingested it (and never before it was recorded)."""

    def __init__(self, read_times):
        self.read_times = read_times     # world -> [(entity id, recorded_at, ingested_at or None)]
        self._rows, self._sets = {}, {}

    def ingested(self, world, t):
        from dataset_v2.contracts import instant
        if world not in self._rows:
            self._rows[world] = [(key, instant(str(recorded)), instant(str(arrived)) if arrived else None)
                                 for key, recorded, arrived in self.read_times(world) if recorded]
        if (world, t) not in self._sets:
            when = instant(t)
            self._sets[(world, t)] = frozenset(key for key, recorded, arrived in self._rows[world]
                                               if recorded <= when and (arrived is None or arrived <= when))
        return self._sets[(world, t)]


class WorldResolver:
    """recorded_at(world, ids): when each cited id was recorded. A record of the database answers from the database.
    An id that is not a database record (a tool-computed result, a precedent or another record shown by a tool) answers
    from the run's captured tool index, which the tools' code wrote; an id in neither does not resolve."""

    def __init__(self, read_recorded, tool_index=None):
        self.read_recorded, self.tool_index = read_recorded, tool_index or {}

    def recorded_at(self, world, ids):
        ids = sorted({i for i in ids if isinstance(i, str)})
        found = {key: str(at) for key, at in self.read_recorded(world, ids).items() if at}
        for key in ids:
            shown = (self.tool_index.get(world) or {}).get(key)
            if key not in found and shown and (shown.get("recorded_at") or shown.get("shown_as_of")):
                found[key] = str(shown.get("recorded_at") or shown["shown_as_of"])
        return found


def read_tool_index(run_dir):
    """{world: {id: {kind, scope, recorded_at, shown_as_of}}} from <run>/captured/tool_index/."""
    out = {}
    root = Path(run_dir) / "captured" / "tool_index"
    for path in sorted(root.glob("*.jsonl")) if root.exists() else []:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entry = json.loads(line)
                for key, meta in (entry.get("index") or {}).items():
                    known = out.setdefault(entry["world"], {}).get(key)
                    # The earliest time an id was recorded or shown wins: a later showing proves nothing about an earlier t.
                    if known is None or str(meta.get("recorded_at") or meta.get("shown_as_of")) < str(known.get("recorded_at") or known.get("shown_as_of")):
                        out[entry["world"]][key] = meta
    return out


def build_scorer(config, *, run_dir=None, driver=None):
    """The scorer side (its own process, after the run): reads the run's databases, read-only. Refuses when a database's
    live session is not the one the run manifest names, because the ingestion times would not be that run's."""
    owns_driver = driver is None
    if driver is None:
        import config as settings
        from neo4j import GraphDatabase
        logging.getLogger("neo4j").setLevel(logging.ERROR)
        driver = GraphDatabase.driver(settings.NEO4J_URI, auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD))
    databases = {world: (spec or {}).get("database") for world, spec in config.worlds.items()}
    manifest_path = Path(run_dir) / "run_manifest.json" if run_dir else None
    ran = (json.loads(manifest_path.read_text(encoding="utf-8")).get("provenance") or {}).get("worlds") if manifest_path and manifest_path.exists() else None

    def read(world, query, **params):
        with driver.session(database=databases[world], default_access_mode="READ") as session:
            return [dict(r) for r in session.run(query, **params)]

    for world in databases:
        if ran and world in ran:
            row = read(world, "MATCH (c:OpsEntity:OpsControl) RETURN c.session_id AS session")
            marker = read(world, "MATCH (m:_V2Import) RETURN m.manifest_hash AS hash")
            if not row or row[0]["session"] != ran[world].get("session_id"):
                raise SystemExit(f"{databases[world]}: the live session was reset after the run; its ingestion times are not this run's")
            if not marker or marker[0]["hash"] != ran[world].get("manifest_hash"):
                raise SystemExit(f"{databases[world]} holds a different import than the one the run names")

    def read_times(world):
        return [(r["id"], _iso(r["recorded"]), r["arrived"]) for r in read(
            world, "MATCH (n:V2Entity) RETURN n.entity_id AS id, n.recorded_at AS recorded, n.ingested_at AS arrived")]

    def read_recorded(world, ids):
        out = {}
        for offset in range(0, len(ids), 5000):
            for r in read(world, "MATCH (n:V2Entity) WHERE n.entity_id IN $ids RETURN n.entity_id AS id, n.recorded_at AS at",
                          ids=ids[offset:offset + 5000]):
                out[r["id"]] = _iso(r["at"])
        return out

    return {"ingestion": WorldIngestionLog(read_times),
            "resolver": WorldResolver(read_recorded, read_tool_index(run_dir) if run_dir else {}),
            "close": (driver.close if owns_driver else None)}
