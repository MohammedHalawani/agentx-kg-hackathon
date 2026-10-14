"""Mutable development ledger in the verified local shadow; never writes V2Entity."""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import logging
import math
import os
import queue
import threading

from dataset_v2.contracts import Config, canonical, digest, instant, UTC_FIELDS
from dataset_v2.load import target_guard
from operations.schema import SCHEMA, FIELDS, COMMON, WALL_FIELDS, public_value
from operations.lifecycle import OperationsConflict, decision_state, require_version, require_actor
from operations import claims, provider_gate
from operations.diagnosis import case_diagnosis, investigation_status
from operations.simulator import SPEEDS, EVENT_KINDS
from operations.worker import analyze
from operations import materiality

log = logging.getLogger("suhail.operations")
CONTROL_ID = "DEMO-OPS-CONTROL"
# The development reset deletes the whole operations ledger. It is off unless the server process is started
# with this variable set to 1, and each request must also carry the current session's confirmation.
DEV_RESET_ENV = "SUHAIL_DEV_RESET"
RESET_AUDIT_LIMIT = 50


def development_reset_enabled():
    return os.environ.get(DEV_RESET_ENV, "").strip() == "1"


# The approval context recorded with every recommendation and every authorized execution. Approval and
# dispatch recompute it on the current case and compare (context_changes).
CONTEXT_KEYS = ("symptoms", "evidence_count", "latest_evidence_recorded_at", "run_id", "review_id", "review_verdict",
                "model_verdict", "state_version")
# What the recommendation was decided on: the symptoms, the investigation run and its final review. Any difference in
# one of these means its basis changed.
DECISION_KEYS = ("symptoms", "run_id", "review_id", "review_verdict", "model_verdict")
# How much evidence is visible. A difference here is a change only when a new record is material (operations.materiality).
EVIDENCE_KEYS = ("evidence_count", "latest_evidence_recorded_at")


def context_changes(recorded, current, *, material=None):
    """Which parts of the approval context changed (all of them when nothing was recorded).

    A different symptom set, investigation run, review or reviewer verdict is always a change.
    material: the material changes among the records that became visible since the context was recorded, as
    operations.materiality decides them (the module the monitor and the worker use): a record that supersedes or
    re-versions cited evidence, a late upload from before the investigation's snapshot, a monitor finding added or
    cleared. With a list, the evidence keys count as changed only when it is not empty, and a case version that moved
    by exactly the number of records ingested since is not a change (each ingested record advances the version); any
    other move of the version is. With None (not assessed: a context recorded without what the assessment needs), any
    difference in the evidence or the version is a change, as it always was."""
    if not recorded:
        return ["approval_context_missing"]
    changed = {key for key in DECISION_KEYS if recorded.get(key) != current.get(key)}
    if material is None or material:
        changed |= {key for key in EVIDENCE_KEYS if recorded.get(key) != current.get(key)}
    if recorded.get("state_version") != current.get("state_version"):
        accounted = None
        if material is not None and all(isinstance(c.get(k), int) for c in (recorded, current) for k in ("state_version", "evidence_events")):
            accounted = current["evidence_events"] - recorded["evidence_events"]
        if accounted is None or current["state_version"] - recorded["state_version"] != accounted:
            changed.add("state_version")
    return [key for key in CONTEXT_KEYS if key in changed]


# Progress events of a running investigation (operations.graph emits one per stage start, stage end and tool call) are
# written in batches, not one transaction each: at about 0.3 s a write that was 5 to 8 s of every case, spent on the
# investigation's own thread. An event now waits at most STAGE_FLUSH_SECONDS (default 0.75 s, never more than
# STAGE_FLUSH_MAX_SECONDS = 1 s; SUHAIL_STAGE_FLUSH_SECONDS, 0 writes every event at once as before) before it is in
# the run record, the audit trail, GET /cases/{id} and the SSE stream. See StageBuffer.
STAGE_FLUSH_ENV = "SUHAIL_STAGE_FLUSH_SECONDS"
STAGE_FLUSH_SECONDS = 0.75
STAGE_FLUSH_MAX_SECONDS = 1.0


def stage_flush_seconds(value=None):
    """How long a progress event may wait to be written: the store's setting, else SUHAIL_STAGE_FLUSH_SECONDS, else
    0.75 s; never negative and never above 1 s."""
    if value is None:
        try:
            value = float(os.environ.get(STAGE_FLUSH_ENV, "").strip() or STAGE_FLUSH_SECONDS)
        except ValueError:
            value = STAGE_FLUSH_SECONDS
    value = float(value)
    return max(0.0, min(value if math.isfinite(value) else STAGE_FLUSH_SECONDS, STAGE_FLUSH_MAX_SECONDS))


class StageBuffer:
    """The progress events of one running investigation that are not written yet.

    add(event, events) is called by the investigation for every event, in order. The first event of a run and a FAILED
    event are written at once, on the investigation's own thread (so a run that cannot be recorded, or was superseded,
    stops where it did before). Any other event starts a timer if none is running; when it fires, after `interval`
    seconds, everything waiting is written in ONE transaction, in order, on the timer's thread, while the investigation
    goes on. So no event waits longer than `interval` (plus the write itself), and events that arrive together (a
    stage's end and the next stage's start; a burst of quick stages) share a write.

    flush() writes whatever is waiting, on the caller's thread: before the run's result is committed. close() does
    the same and ends the buffer: after the run, and on every failure path. Nothing is dropped: a write that fails
    leaves its events waiting, a failed timer write is retried by the next add() on the investigation's thread (where
    its error is raised, as it was when every event was written there), and close() writes the rest or raises.
    Writes are serialised and each takes the oldest waiting events first, so the order is the order of add()."""

    def __init__(self, write, interval, *, timer=threading.Timer):
        self.write, self.interval, self.make_timer = write, interval, timer
        self.lock, self.writing = threading.Lock(), threading.Lock()
        self.pending, self.events, self.written = [], [], 0
        self.timer, self.closed, self.retry = None, False, False

    def add(self, event, events):
        with self.lock:
            self.pending.append(event)
            self.events = events
            now = (self.closed or self.interval <= 0 or self.retry or event.get("status") == "FAILED"
                   or (not self.written and len(self.pending) == 1))
            if not now and self.timer is None:
                self.timer = self.make_timer(self.interval, self._timed)
                self.timer.daemon = True
                self.timer.start()
        if now:
            self.flush()

    def _timed(self):
        try:
            self.flush(timed=True)
        except Exception as error:   # Not lost: the events are still waiting, and the next add() or close() writes them.
            logging.getLogger("operations.store").warning("A batch of progress events was not written (%s); it will be retried",
                                                          type(error).__name__)
            with self.lock:
                self.retry = True

    def flush(self, *, timed=False):
        """Write every waiting event, oldest first, in one transaction. Returns how many were written."""
        with self.writing:
            with self.lock:
                timer, self.timer = self.timer, None
                if timed and self.closed:
                    return 0
                batch, events = list(self.pending), self.events
            if timer is not None and not timed:
                timer.cancel()
            if not batch:
                return 0
            self.write(batch, events)             # raises: the batch stays waiting
            with self.lock:
                del self.pending[:len(batch)]
                self.written += len(batch)
                self.retry = False
                if self.pending and self.timer is None and not self.closed and self.interval > 0:
                    # Events that arrived during the write wait their own interval at most.
                    self.timer = self.make_timer(self.interval, self._timed)
                    self.timer.daemon = True
                    self.timer.start()
            return len(batch)

    def close(self, *, quiet=False):
        """Write what is waiting and end the buffer. quiet: on a failure path, where a second error must not hide the first."""
        with self.lock:
            self.closed = True
        try:
            return self.flush()
        except Exception:
            if not quiet:
                raise
            return 0


def reset_token(control):
    """Names the current session (its digest part, unchanged by the public identifier mapping)."""
    session = control.get("session_id") or ""
    return "RESET-LEDGER-" + (session[-24:] if session else "NO-SESSION")
# The fixed databases (foundation replay, live provider feed and its test twins) are listed in operations.datasets;
# a mechanism-world database is accepted there by its name pattern, for a mechanism-world dataset only.
from operations.datasets import (OPERATIONS_DATABASES, dataset_kind, is_feed_dataset, operations_database_allowed,
                                 pairing_error)
INGEST_BATCH = 500


MONITOR_QUEUE_LIMIT = 500
AUTO_OUTCOME_WINDOW_HOURS = 72
# Normal provider upload lag is seconds to minutes. The monitor waits this long past a deadline
# before calling an expected observation missing, so in-flight uploads do not open cases.
DETECTION_ALLOWANCE_SECONDS = 900
# A case whose shipment keeps receiving evidence mid-investigation is re-investigated at most this
# many times before it goes to a person instead of acting on a superseded snapshot.
MAX_SNAPSHOT_REFRESHES = 2
# A case that was already investigated is requeued when the monitor adds a standing or human-floor symptom to it
# (the first diagnosis could not have known it). Bounded: after this many such re-investigations the case stays
# where it is, and the approval and dispatch rechecks keep refusing a recommendation whose symptoms changed.
MAX_SYMPTOM_REINVESTIGATIONS = 2
# A finished investigation is superseded only by a material change (operations.materiality): a changed symptom set, or
# a newly ingested record that replaces or contradicts what the conclusion rests on. Routine new records for the
# shipment do not requeue it. Material evidence arriving after a run requeues the case at most this many times.
MAX_EVIDENCE_REINVESTIGATIONS = 2
# After a run finishes (or is released for a material mid-run change), the worker starts no automatic investigation of
# the same case for this long on the simulation clock, so a burst of related records is investigated once. An operator's
# explicit request (re-analysis, a manual step, a named case) is not delayed, and neither is anything while the
# simulation is paused (the clock, and so the interval, would not move). 0 disables the interval.
REINVESTIGATION_QUIET_ENV = "SUHAIL_REINVESTIGATION_QUIET_SECONDS"
REINVESTIGATION_QUIET_SECONDS = 7200


def reinvestigation_quiet_seconds(value=None):
    """The quiet interval in simulated seconds: the store's setting, else the environment, else two hours."""
    if value is None:
        value = os.environ.get(REINVESTIGATION_QUIET_ENV, "").strip() or REINVESTIGATION_QUIET_SECONDS
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return REINVESTIGATION_QUIET_SECONDS
# States in which an investigation has been recorded and no action is authorized, being dispatched or awaiting its
# outcome. ACTION_INITIATED is left to the dispatch recheck (which refuses and requeues on a changed context).
# AWAITING_OUTCOME is left to the outcome verifier: an executed action is always verified and its outcome recorded, and
# the verifier sends the case to a person when a standing or human-floor symptom is recorded or still visible, so a
# symptom seen after execution can never drop that verification or lead to a second automatic action. OPEN, REOPENED
# and INVESTIGATING are already queued or running (a running investigation notices the change and refreshes its snapshot).
REINVESTIGABLE_STATES = frozenset(("RECOMMENDATION_READY", "AWAITING_APPROVAL", "HUMAN_REVIEW", "NEEDS_EVIDENCE", "ESCALATED"))


# A curated demo session (off unless set): comma-separated shipment ids, public (SYN-) or internal (DEMO-) form. The
# monitor then opens cases only for these shipments. Every other shipment is still ingested and stays visible to the
# investigator's tools as evidence; it just never becomes a case, so the queue holds the curated cases only and the
# automatic-investigation worker spends no model calls on the rest.
DEMO_SHIPMENTS_ENV = "SUHAIL_DEMO_SHIPMENTS"


def demo_shipments(value=None):
    """The curated shipment ids in storage form, or None when the option is not set (every shipment is monitored)."""
    from operations.identifiers import storage_value
    text = os.environ.get(DEMO_SHIPMENTS_ENV, "") if value is None else value
    ids = frozenset(storage_value(part.strip()) for part in str(text).split(",") if part.strip())
    return ids or None


def monitor_enqueue(queue, shipment_ids):
    """Bounded, ordered, de-duplicated shipments awaiting an expected-vs-actual check."""
    out = list(queue)
    for sid in shipment_ids:
        if sid and sid not in out:
            out.append(sid)
    return out[-MONITOR_QUEUE_LIMIT:]


# Detection hands the investigator observable symptoms, never a diagnosis: several causes share
# one symptom (an overdue milestone may be a hub delay, an offline scanner or a lost parcel).
SYMPTOMS = {
    "MISSED_MILESTONE": "MILESTONE_OVERDUE", "JOURNEY_DELAY": "MILESTONE_LATE", "TRAFFIC_DELAY": "MILESTONE_LATE",
    "BARCODE_MISMATCH": "BARCODE_READ_DIFFERS", "WEIGHT_MISMATCH": "WEIGHT_READ_DIFFERS",
    "CUSTODY_GAP": "CUSTODY_TRANSFER_UNCONFIRMED", "CONFLICTING_CUSTODY": "CUSTODY_REPORTS_CONFLICT",
    "UNRECONCILED_CUSTODY": "SESSION_END_UNRECONCILED", "ADDRESS_CONFLICT": "DELIVERY_ATTEMPT_FAILED",
    "WRONG_GATE": "DELIVERY_ATTEMPT_FAILED", "RECIPIENT_UNAVAILABLE": "DELIVERY_ATTEMPT_FAILED",
    "DELIVERY_DISPUTE": "RECIPIENT_REPORTED_NOT_RECEIVED", "PROOF_INSUFFICIENT": "DELIVERY_PROOF_INCOMPLETE",
    "INSUFFICIENT_EVIDENCE": "EVIDENCE_MISSING", "MANIFEST_CONFLICT": "MANIFEST_CUSTODY_CONFLICT",
}
SYMPTOM_STATUS = (("RECIPIENT_REPORTED_NOT_RECEIVED", "DELIVERY_DISPUTE"), ("CUSTODY_REPORTS_CONFLICT", "CRITICAL"),
                  ("MANIFEST_CUSTODY_CONFLICT", "CRITICAL"),
                  ("SESSION_END_UNRECONCILED", "UNRECONCILED_CUSTODY"), ("MILESTONE_OVERDUE", "SLA_RISK"))


# Standing symptoms (conditions still true at the clock) and the one clearance check shared by the outcome verifier
# and a person's recorded finding live in operations.closure.
from operations.closure import STANDING_SYMPTOMS, delivered as delivery_corroborated, finding_evidence, remaining_symptoms


def monitor_finding(assessment):
    """Deterministic monitor rule: open a case only when visible evidence shows an abnormal symptom."""
    symptoms = sorted({SYMPTOMS.get(item["code"], "EVIDENCE_MISSING") for item in assessment.get("exceptions", [])})
    return {"open": bool(symptoms), "symptoms": symptoms}


def symptom_status(symptoms):
    return next((status for symptom, status in SYMPTOM_STATUS if symptom in symptoms), "NEEDS_ATTENTION")


# What the case record says about itself before, or without, an accepted agent diagnosis: neutral monitor text, no
# cause codes and the status of the observed symptoms. Rule triage never fills these fields (it is kept apart as
# rule_signal_codes), and neither does an investigation the independent reviewer did not accept.
MONITOR_SUMMARY_PENDING = "Monitor detected an expected-vs-actual divergence in visible evidence; automatic investigation pending."
MONITOR_SUMMARY = "Monitor detected an expected-vs-actual divergence in visible evidence; no accepted agent diagnosis."


def narration_view(record):
    """A stored narration record as served (the contract of docs/api/narration.md)."""
    return {"id":record["entity_id"],"case_id":record["case_id"],"shipment_id":record["shipment_id"],"run_id":record["run_id"],
            "sequence":record["sequence"],"stage":record["stage"],"phase":record["phase"],"kind":record["kind"],
            "iteration":record.get("iteration") or 0,"title_en":record.get("title_en"),"title_ar":record.get("title_ar"),
            "text_en":record.get("text_en"),"text_ar":record.get("text_ar"),"evidence_ids":list(record.get("evidence_ids") or []),
            "graph_node_ids":list(record.get("graph_node_ids") or []),"source":json.loads(record.get("source_json") or "{}"),
            "occurred_at":record.get("source_wall_at"),"scenario_time":record.get("scenario_time"),
            "created_at":record.get("wall_recorded_at"),"model":record.get("model"),"grounded":record.get("grounded"),
            "fallback":bool(record.get("fallback")),"outcome_state":record.get("outcome_state")}


def without_diagnosis(case, *, pending):
    """Reset the case's summary fields to the monitor's view (also when a case goes back for re-investigation)."""
    case.update(issue_summary=MONITOR_SUMMARY_PENDING if pending else MONITOR_SUMMARY, cause_codes=[], rule_signal_codes=[],
                diagnosis_available=False, operational_status=symptom_status(case.get("symptom_codes") or []))
    return case


def served_run_result(result):
    """A stored run's result as served. Review text is derived from each review's reason (records written before reason
    codes existed may carry a fixed sentence). An agent hypothesis carries the model's own text only: runs recorded
    before that was fixed stored a rule-definition sentence as its Arabic summary, which is removed here."""
    from operations.worker import with_review_reason
    if result.get("review"):
        result["review"] = with_review_reason(result["review"])
    for item in result.get("trace") or []:
        item["review"] = with_review_reason(item.get("review"))
    agent = result.get("mode") == "gpt_oss_agents"
    for diagnosis in (result.get("result") or {}).get("diagnoses") or []:
        if agent or diagnosis.get("certainty") == "model_hypothesis":
            diagnosis["summary_ar"] = None
    for event in result.get("pipeline_events") or []:
        output = event.get("output") or {}
        if event.get("stage") == "review" and output.get("verdict"):
            event["output"] = output = with_review_reason(output)
        for diagnosis in output.get("diagnoses") or []:
            if diagnosis.get("certainty") == "model_hypothesis":
                diagnosis["summary_ar"] = None
    return result


def identity(kind, *parts):
    return "DEMO-OPS-" + kind.upper() + "-" + digest(parts)[:24]


def temporal_properties(props):
    fields = UTC_FIELDS | {"initial_as_of", "cursor_time", "claim_at", "observed_at", "source_occurred_at",
                           "outcome_checked_as_of", "investigated_as_of", "evidence_checked_as_of", "quiet_until", "deadline_at", "expected_response_at", "closed_at", "session_started_at", "last_processed_at", "executed_at",
                           "claim_as_of", *WALL_FIELDS}
    return {key: instant(value) if key in fields and isinstance(value, str) else value for key, value in props.items()}


class OperationsStore:
    def __init__(self, driver, database, dataset_id, config=None, reader=None, *, uri="bolt://localhost:7687", protected=(), agents=None):
        target_guard(uri, database, protected)
        if not operations_database_allowed(database) or not str(dataset_id).startswith("DEMO-"):
            raise OperationsConflict("Operations requires the fixed audited local shadow")
        if pairing_error(database, dataset_id):
            raise OperationsConflict(pairing_error(database, dataset_id))
        self.driver, self.database, self.dataset_id = driver, database, dataset_id
        # Live-network and mechanism-world datasets receive observations only through the provider gateway, never by
        # replaying imports.
        self.live = is_feed_dataset(dataset_id)
        if self.live:
            from operations.ingestion import Gateway
            self.gateway = Gateway(driver, database, dataset_id)
        self.config = config or Config(dataset_id=dataset_id)
        self.reader = reader
        self.agents = agents  # operations.investigator (GPT-OSS tool loop + reviewer) or None for rules only
        self.adapter = None   # Execution adapter; in development the synthetic operational simulator
        # Evaluation switches: tools withheld from the investigator (an ablation), and the per-case model-call cap
        # (None: SUHAIL_MODEL_CALL_CAP, default 12). Both are recorded with every run.
        self.disabled_tools = tuple(t for t in os.environ.get("SUHAIL_DISABLED_TOOLS", "").replace(" ", "").split(",") if t)
        self.model_call_cap = None
        # Simulated seconds after a run before the same case may be investigated again automatically
        # (None: SUHAIL_REINVESTIGATION_QUIET_SECONDS, default 7200).
        self.reinvestigation_quiet_seconds = None
        # Seconds a progress event may wait before it is written (None: SUHAIL_STAGE_FLUSH_SECONDS, default 0.75, at
        # most 1; 0 writes each event at once), and the timer that ends the wait (tests give their own).
        self.stage_flush_seconds = None
        self.stage_timer = threading.Timer
        self.demo_shipments = demo_shipments()   # None, or the only shipments the monitor may open cases for
        # Investigation claims (operations.claims): how many cases may be investigated at once (1 or 2;
        # SUHAIL_INVESTIGATION_WORKERS), a claim's wall-clock lease and how often its owner renews it (None:
        # SUHAIL_CLAIM_LEASE_SECONDS and SUHAIL_CLAIM_HEARTBEAT_SECONDS, default 180 s and 15 s), the wall clock (tests
        # give their own) and whether each claim renews itself on a thread (tests renew by hand).
        self.capacity = claims.investigation_workers()
        self.lease_seconds = None
        self.heartbeat_seconds = None
        self.wall = claims.wall_now
        self.claim_heartbeats = True
        # The claims this process holds, by case: used only to signal their workers (a pause, a stop). Ownership is
        # always read from the ledger.
        self._claims = {}
        self._claims_lock = threading.Lock()
        self._subscribers={}
        self._subscribers_lock=threading.RLock()
        # Canopus narration (operations.narration.Narrator), attached by the server when SUHAIL_NARRATION is set. The
        # store only tells it which case changed; it reads and writes through narration_sources / narration_append.
        self.narrator=None
        self._narration_dirty=set()
        self._narration_lock=threading.Lock()

    def _execute(self, callback, *, write=False):
        with self.driver.session(database=self.database, default_access_mode="WRITE" if write else "READ") as session:
            def guarded(tx):
                self._guard(tx)
                return callback(tx)
            result=session.execute_write(guarded) if write else session.execute_read(guarded)
        if write and self.narrator is not None and self._narration_dirty:
            # After the commit: the cases whose audit trail just grew are narrated on the narrator's own thread.
            # Several workers write at once; the set is handed over under a lock so none of them changes it mid-read.
            with self._narration_lock:
                dirty,self._narration_dirty=self._narration_dirty,set()
            for case_id in dirty:self.narrator.request(case_id)
        return result

    def _guard(self, tx):
        rows = list(tx.run("MATCH (m:_V2Import) RETURN properties(m) AS props"))
        if len(rows) != 1 or rows[0]["props"].get("state") != "COMPLETE":
            raise OperationsConflict("Operations requires a COMPLETE immutable import")
        marker = rows[0]["props"]
        manifest = json.loads(marker["manifest_json"])
        if (digest(manifest) != marker["manifest_hash"] or manifest.get("synthetic") is not True
                or manifest.get("dataset_id") != self.dataset_id or manifest.get("config") != asdict(self.config)):
            raise OperationsConflict("Operations manifest/config differs")

    def _get(self, tx, kind, identifier):
        if kind not in FIELDS:
            raise OperationsConflict("Unregistered ledger kind")
        row = tx.run(f"MATCH (n:OpsEntity:{kind} {{entity_id:$id,dataset_id:$dataset,split:'development'}}) RETURN properties(n) AS props",
                     id=identifier, dataset=self.dataset_id).single()
        return public_value(row["props"]) if row else None

    def _put(self, tx, kind, props, *, update=False):
        if kind not in FIELDS or set(props) - COMMON - FIELDS[kind]:
            raise OperationsConflict("Unregistered ledger fields")
        owner = props.get("shipment_id")
        envelope = {"dataset_id": self.dataset_id, "synthetic": True, "split": "development",
                    "holdout_group": owner, "provenance": "SYNTHETIC_DEMO_ASSUMPTION", **props}
        if kind != "OpsControl":
            row = tx.run("MATCH (s:V2Entity:Shipment {entity_id:$id,dataset_id:$dataset,split:'development',synthetic:true}) RETURN s.entity_id AS id",
                         id=owner, dataset=self.dataset_id).single()
            if row is None:
                raise OperationsConflict("Ledger owner is not a development shipment")
        existing = self._get(tx, kind, props["entity_id"])
        if existing and not update:
            if canonical(existing) != canonical({key: value for key, value in envelope.items() if value is not None}):
                raise OperationsConflict("Immutable ledger receipt identity collision")
            return existing
        mutation="SET n += $props" if update else "ON CREATE SET n=$props"
        tx.run(f"MERGE (n:OpsEntity:{kind} {{entity_id:$id}}) {mutation}",
               id=props["entity_id"], props=temporal_properties(envelope)).consume()
        return {key: value for key, value in envelope.items() if value is not None}

    def _link(self, tx, kind, start, end, owner, when):
        from operations.schema import RELATIONSHIPS
        if kind not in RELATIONSHIPS:
            raise OperationsConflict("Unregistered ledger relationship")
        props = {"edge_id": identity("edge", start, kind, end), "dataset_id": self.dataset_id,
                 "synthetic": True, "split": "development", "shipment_id": owner, "holdout_group": owner,
                 "recorded_at": when}
        summary = tx.run(f"MATCH (a:OpsEntity {{entity_id:$start}}),(b {{entity_id:$end}}) "
                        f"MERGE (a)-[r:{kind} {{edge_id:$id}}]->(b) ON CREATE SET r=$props",
                        start=start, end=end, id=props["edge_id"], props=temporal_properties(props)).consume()

    def _control(self, tx, *, lock=False):
        if lock:
            tx.run("MATCH (c:OpsEntity:OpsControl {entity_id:$id}) SET c.state_version=c.state_version+1 RETURN c.state_version",
                   id=CONTROL_ID).consume()  # Serializes claims, replay cursor and operator transitions.
        control = self._get(tx, "OpsControl", CONTROL_ID)
        if not control:
            raise OperationsConflict("Operations ledger is not initialized")
        return control

    def _case(self, tx, case_id):
        case = self._get(tx, "OpsCase", case_id)
        if not case:
            raise OperationsConflict("Operational case not found")
        return case

    def _audit(self, tx, case, event_type, when, *, result="", actor="DEMO-RULE-WORKER", decision=None, old=None, key=None):
        audit_id = identity("audit", case["entity_id"], event_type, case["state_version"], key)
        self._put(tx, "OpsAudit", {"entity_id": audit_id, "shipment_id": case["shipment_id"], "case_id": case["entity_id"],
            "event_type": event_type, "occurred_at": when, "recorded_at": when, "wall_recorded_at":datetime.now(timezone.utc).isoformat(), "actor_id": actor, "decision": decision,
            "result": result[:1000], "from_state": old, "to_state": case["workflow_state"]})
        self._link(tx, "OPS_HAS_AUDIT", case["entity_id"], audit_id, case["shipment_id"], when)
        if self.narrator is not None:
            with self._narration_lock:self._narration_dirty.add(case["entity_id"])

    def _invalidate_outcomes(self,tx,case):
        rows=tx.run("MATCH(n:OpsEntity:OpsOutcome {case_id:$case_id,dataset_id:$dataset}) RETURN properties(n) AS props ORDER BY n.recorded_at DESC,n.entity_id DESC LIMIT 20",
                    case_id=case["entity_id"],dataset=self.dataset_id)
        for row in rows:
            outcome=public_value(row["props"])
            if outcome.get("verification_status") in ("VERIFIED","HUMAN_VERIFIED") and not outcome.get("invalidated"):
                # A reopened case's outcome no longer stands, whoever verified it: it is never a precedent again.
                outcome.update(invalidated=True,trusted_precedent=False)
                self._put(tx,"OpsOutcome",outcome,update=True)

    def recover_executions(self):
        """After a restart, executions claimed but never acknowledged go back to AUTHORIZED. Dispatch is
        idempotent per execution (the simulator's messages have deterministic ids; a real adapter must honour
        the execution's idempotency_key), so a re-dispatch cannot double-act."""
        def recover(tx):
            c=self._control(tx,lock=True);recovered=[]
            for row in tx.run("MATCH(e:OpsEntity:OpsExecution {dataset_id:$dataset,status:'EXECUTING'}) RETURN properties(e) AS e",dataset=self.dataset_id):
                e=public_value(row["e"]);e["status"]="AUTHORIZED";self._put(tx,"OpsExecution",e,update=True)
                self._audit(tx,self._case(tx,e["case_id"]),"EXECUTION_RECOVERED",c["as_of"],actor="SUHAIL-EXECUTION-ADAPTER",key=e["entity_id"],
                            result="Claimed before a restart without a receipt; re-dispatched idempotently.")
                recovered.append(e["entity_id"])
            return recovered
        return self._execute(recover,write=True)

    def initialize(self):
        self._execute(lambda tx: None)
        with self.driver.session(database=self.database) as session:
            for name, (kind, label, prop) in SCHEMA.items():
                query = (f"CREATE CONSTRAINT {name} IF NOT EXISTS FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
                         if kind == "CONSTRAINT" else f"CREATE INDEX {name} IF NOT EXISTS FOR (n:{label}) ON (n.{prop})")
                session.run(query).consume()
        def initialize_tx(tx):
            initial = self.config.start_at
            props={"entity_id": CONTROL_ID,"dataset_id":self.dataset_id,"synthetic":True,"split":"development",
                "provenance":"SYNTHETIC_DEMO_ASSUMPTION", "recorded_at": initial, "as_of": initial,
                "initial_as_of": initial, "end_at": self.config.as_of, "speed": 1, "simulator_state": "paused",
                "worker_state": "paused", "replay_mode":"timeline", "state_version": 0, "cursor_time": initial, "cursor_id": "",
                "processed_count": 0, "event_count": 0}
            # Unique control MERGE + self-dependent SET acquires the lock before reading;
            # concurrent initialization never resets an existing clock/worker/cursor.
            tx.run("MERGE (n:OpsEntity:OpsControl {entity_id:$id}) ON CREATE SET n=$props "
                   "SET n.state_version=n.state_version RETURN n.state_version",
                   id=CONTROL_ID,props=temporal_properties(props)).consume()
            # Only the monitor opens cases. Dataset Case/Exception nodes were derived offline from each
            # shipment's whole evidence window (including later evidence) and are never loaded as live work.
        self._execute(initialize_tx, write=True)
        self.recover_executions()
        # Only claims whose lease has run out: a claim still within its lease may belong to a worker that is alive.
        self.recover_claims()
        return self.status()

    def clock(self):
        return self._execute(lambda tx: self._control(tx)["as_of"])

    def _reader(self):
        if self.reader is None:
            from operations.read_model import OperationsReader
            self.reader=OperationsReader(self.driver,self.database,self.dataset_id,self.config,clock=self.clock,store=self)
        return self.reader

    def status(self):
        def read(tx):
            control = self._control(tx)
            return control, [self._investigation_status(tx, case) for case in self._live_claims(tx, self._wall())]
        control, active = self._execute(read)
        # active_cases is the authority: the claims that are live now (their lease has not expired), oldest first.
        # concurrency is how many there may be, active_count how many there are. The single ids of the earlier format
        # are filled only while exactly one case is being investigated.
        # (Wall times are stored and served in one UTC form, so their text orders as they do.)
        active.sort(key=lambda item: (item["started_at"] or "", item["case_id"]))
        single = active[0] if len(active) == 1 else {}
        return {"synthetic": True, "demo": True, "as_of": control["as_of"],
            "worker": {"state": control["worker_state"], "concurrency": self.capacity, "active_count": len(active),
                       "processed_count": control["processed_count"],
                       "active_case_id": single.get("case_id"), "active_shipment_id": single.get("shipment_id"),
                       "active_cases": active,
                       # Most recent completed claim, so the live panel can show its recorded stages after the run.
                       "last_case_id": control.get("last_case_id"), "last_shipment_id": control.get("last_shipment_id"),
                       "last_workflow_state": control.get("last_workflow_state"), "last_processed_at": control.get("last_processed_at")},
            "session": {"case_source": "monitor", "session_id": control.get("session_id"),
                        "started_at": control.get("session_started_at"), "monitor_pending": len(control.get("monitor_queue") or []),
                        "monitor_checked": control.get("monitor_checked", 0), "monitor_opened": control.get("monitor_opened", 0),
                        # SUHAIL_DEMO_SHIPMENTS: whether the monitor is limited to a curated list, and how many it lists.
                        "demo_shipments": {"enabled": self.demo_shipments is not None, "count": len(self.demo_shipments or ())}},
            "simulator": {"state": control["simulator_state"], "speed": control["speed"], "replay_mode":control.get("replay_mode","timeline"), "event_count": control["event_count"],
                          "cursor": {"time": control["cursor_time"], "id": control["cursor_id"]}, "end_at": control["end_at"]},
            "development_reset": {"enabled": development_reset_enabled(),
                                  "confirmation": reset_token(control) if development_reset_enabled() else None,
                                  "last": (json.loads(control.get("reset_audit_json") or "[]") or [None])[-1]},
            # What carries out an authorized action. With no adapter nothing is sent: an authorized action is recorded
            # as not acknowledged, nothing can be verified and the case goes to a person (never resolved).
            "execution": {"adapter": "none" if self.adapter is None else getattr(self.adapter, "name", "synthetic_operational_simulator"),
                          "dataset_kind": dataset_kind(self.dataset_id)},
            "notifications": {"mode": "dry_run", "external_calls": 0}}

    def control(self, component, action, speed=None, actor_id="DEMO-OPERATOR-LOCAL", replay_mode=None):
        require_actor(actor_id)
        if component not in {"worker", "simulator"} or action not in {"start", "pause", "step"}:
            raise OperationsConflict("Invalid operations control")
        if speed is not None and (type(speed) is not int or speed not in SPEEDS):
            raise OperationsConflict("Simulation speed must be 1, 10, 60, 300, 600 or 3600")
        if replay_mode is not None and (component!="simulator" or replay_mode not in {"timeline","compressed"}):
            raise OperationsConflict("Replay mode must be timeline or compressed")
        revoked = []
        def control_tx(tx):
            del revoked[:]      # the driver may run this again after a transient failure
            c = self._control(tx, lock=True)
            c[component + "_state"] = "running" if action == "start" else "paused"
            if speed is not None: c["speed"] = speed
            if replay_mode is not None:c["replay_mode"]=replay_mode
            if action == "pause" and component == "worker":
                # A deliberate, global stop: every running investigation loses its case here, whoever holds it. What
                # those workers still compute is refused when they try to write it (operations.claims).
                now = self._wall()
                self._recover_expired(tx, c, now)
                for case in self._investigating(tx):
                    self._end_claim(tx, case, c["as_of"], now, reason=claims.END_PAUSED, event="CLAIM_RELEASED", actor=actor_id,
                                    recovery=False, result="Automatic investigation was paused; the investigation in progress was "
                                                           "stopped and the case is queued again.")
                    revoked.append(case["entity_id"])
            self._put(tx, "OpsControl", c, update=True)
        self._execute(control_tx, write=True)
        self._signal(revoked)
        if action == "step":
            if component == "worker": self.process_one(manual=True)
            else: self.tick(step=True)
        return self.status()

    SKIP_STEP_MINUTES = 30      # The clock moves in steps of thirty simulated minutes while skipping (it can stop up to that late).
    SKIP_MAX_HOURS = 168

    def _case_states(self):
        def read(tx):
            return {row["id"]: row["state"] for row in tx.run(
                "MATCH(w:OpsEntity:OpsCase {dataset_id:$dataset,split:'development'}) RETURN w.entity_id AS id,w.workflow_state AS state",
                dataset=self.dataset_id)}
        return self._execute(read)

    def skip_to_next_event(self, actor_id="DEMO-OPERATOR-LOCAL", max_hours=72):
        """Run the simulated clock forward, as fast as the machine allows, until something an operator is waiting for
        happens: a case that was awaiting evidence gets its verified outcome (the evidence arrived, or its deadline
        passed), or the monitor opens a new case. The clock is then left PAUSED, at the speed it had, whatever its state
        was before: every advance of the world is an explicit Start or Skip, and nothing ages while the operator reads.

        It is the same clock, the same feed and the same monitor, execution and verification steps as at any speed:
        nothing is scheduled or looked up ahead, and nothing about a future event is returned, only what happened by
        the time it stopped. Everything else in the world ages by the same time. Refused while an investigation runs."""
        require_actor(actor_id)
        if type(max_hours) is not int or not 1 <= max_hours <= self.SKIP_MAX_HOURS:
            raise OperationsConflict(f"A skip is limited to between 1 and {self.SKIP_MAX_HOURS} simulated hours")
        self.recover_claims()      # a claim whose lease ran out is not a running investigation
        status = self.status()
        if status["worker"].get("active_count"):      # every live claim, not only the first
            raise OperationsConflict("An investigation is running; wait for it to finish before skipping time")
        speed = status["simulator"]["speed"]
        started = instant(status["as_of"])
        end = instant(status["simulator"]["end_at"]) if status["simulator"].get("end_at") else None
        limit = started + timedelta(hours=max_hours)
        before = self._case_states()
        waiting = {case for case, state in before.items() if state == "AWAITING_OUTCOME"}
        self.control("simulator", "pause", actor_id=actor_id)      # The ingestion worker must not advance the clock at the same time.
        reason, changed, now = "limit_reached", [], started
        try:
            while now < limit:
                if end is not None and now >= end:
                    reason = "end_of_timeline"
                    break
                step = min(self.SKIP_STEP_MINUTES * 60, (limit - now).total_seconds())
                now = instant(self.tick(seconds=step / 60, manual=True, speed=60)["as_of"])
                while self.status()["session"]["monitor_pending"]:
                    if not self.monitor_step(limit=10)["checked"]:
                        break
                self.execute_step(limit=10)
                self.outcome_step(limit=10)
                after = self._case_states()
                decided = sorted(case for case in waiting if after.get(case) != "AWAITING_OUTCOME")
                opened = sorted(case for case in after if case not in before)
                if decided or opened:
                    reason, changed = ("outcome_decided" if decided else "case_opened"), decided + opened
                    break
        finally:
            self.control("simulator", "pause", speed=speed, actor_id=actor_id)      # On every exit path, a failed step included.
        final = self.status()
        states = self._case_states()
        return {"reason": reason, "from": started.isoformat(), "to": final["as_of"],
                "simulated_minutes": round((instant(final["as_of"]) - started).total_seconds() / 60),
                "cases": [{"case_id": case, "workflow_state": states.get(case)} for case in changed],
                "still_awaiting_evidence": sum(1 for state in states.values() if state == "AWAITING_OUTCOME"), "status": final}

    def tick(self, seconds=1, *, step=False, manual=False, speed=None, replay_mode=None):
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 86400:
            raise OperationsConflict("Invalid bounded simulation advance")
        if speed is not None and (type(speed) is not int or speed not in SPEEDS):
            raise OperationsConflict("Invalid simulation speed")
        if replay_mode is not None and replay_mode not in ("timeline","compressed"):
            raise OperationsConflict("Invalid replay mode")
        if not manual and (speed is not None or replay_mode is not None):
            raise OperationsConflict("Replay settings require a manual operator step")
        if self.live:
            return self._tick_live(seconds, step=step, manual=manual, speed=speed, replay_mode=replay_mode)
        def replay_tx(tx):
            c = self._control(tx, lock=True)
            if speed is not None:c["speed"]=speed
            if replay_mode is not None:c["replay_mode"]=replay_mode
            if c["simulator_state"] != "running" and not step and not manual:
                return {"events_replayed": 0, "as_of": c["as_of"], "case_ids": []}
            compressed=step or (c.get("replay_mode")=="compressed" and (c["simulator_state"]=="running" or manual))
            target = min(instant(c["as_of"]) + timedelta(seconds=seconds*c["speed"]), instant(c["end_at"]))
            # Step traverses the next recorded event even across a quiet time interval.
            rows = list(tx.run("MATCH (e:V2Entity {dataset_id:$dataset,split:'development'}) "
                "WHERE any(k IN labels(e) WHERE k IN $kinds) "
                "WITH e,CASE WHEN e.recorded_at>e.occurred_at THEN e.recorded_at ELSE e.occurred_at END AS time "
                "WHERE (time > $cursor OR (time=$cursor AND e.entity_id>$id)) "
                "AND ($step OR time <= $target) RETURN properties(e) AS props,labels(e) AS labels,time "
                "ORDER BY time,e.entity_id LIMIT 100", dataset=self.dataset_id, kinds=sorted(EVENT_KINDS),
                cursor=instant(c["cursor_time"]), id=c["cursor_id"], target=target, step=compressed))
            case_ids=[];touched=[]
            previous=instant(c["as_of"])
            for row in rows:
                p=public_value(row["props"]); when=public_value(row["time"])
                sid=p.get("shipment_id") or p.get("holdout_group")
                receipt_id=identity("event",p["entity_id"])
                existing=self._get(tx,"OpsEventReceipt",receipt_id)
                if not existing:
                    self._put(tx,"OpsEventReceipt",{"entity_id":receipt_id,"shipment_id":sid,"source_event_id":p["entity_id"],
                        "event_kind":next(k for k in row["labels"] if k in EVENT_KINDS),"source_occurred_at":p.get("occurred_at",when),
                        "occurred_at":when,"recorded_at":when})
                    if sid:touched.append(sid)
                    self._update_cases_for_event(tx,row,p,sid,when)
                    c["event_count"]+=1
                c.update(cursor_time=when,cursor_id=p["entity_id"])
            # A full batch retains its last committed timestamp; no unreplayed future becomes visible.
            if rows:c["as_of"]=max(c["as_of"],c["cursor_time"])
            if len(rows)<100 and not compressed:c["as_of"]=target.isoformat()
            # A missed milestone produces no event: also check shipments whose deadline just passed.
            due=self._due_shipments(tx,previous,instant(c["as_of"]))
            c["monitor_queue"]=monitor_enqueue(c.get("monitor_queue") or [],[*touched,*due])
            self._put(tx,"OpsControl",c,update=True)
            return {"events_replayed":len(rows),"as_of":c["as_of"],"case_ids":case_ids}
        result=self._execute(replay_tx,write=True)
        result["status"]=self.status()
        return result

    def _due_shipments(self, tx, previous, now):
        """Deadlines produce no event: milestones and end-of-shift reconciliation become due on the clock."""
        params = dict(dataset=self.dataset_id, previous=previous, now=now, allowance=DETECTION_ALLOWANCE_SECONDS)
        milestones = [r["sid"] for r in tx.run("MATCH (m:V2Entity:ExpectedMilestone {dataset_id:$dataset,split:'development'}) "
            "WITH m,m.latest_at+duration({seconds:coalesce(m.grace_seconds,0)+$allowance}) AS due "
            "WHERE due > $previous AND due <= $now RETURN DISTINCT m.shipment_id AS sid LIMIT 300", **params)]
        shifts = [r["sid"] for r in tx.run("MATCH (s:V2Entity:DeliverySession {dataset_id:$dataset,split:'development'}) "
            "WITH s,s.end_at+duration({seconds:coalesce(s.grace_seconds,0)+$allowance+60}) AS due "
            "WHERE due > $previous AND due <= $now RETURN DISTINCT s.shipment_id AS sid LIMIT 300", **params)]
        return [*milestones, *shifts]

    def _tick_live(self, seconds, *, step, manual, speed, replay_mode):
        """Advance the simulation clock and let the gateway ingest every message delivered by then."""
        def plan(tx):
            c = self._control(tx, lock=True)
            if speed is not None: c["speed"] = speed
            if replay_mode is not None: c["replay_mode"] = replay_mode
            self._put(tx, "OpsControl", c, update=True)
            if c["simulator_state"] != "running" and not step and not manual:
                return None, c
            end = instant(c["end_at"])
            target = min(instant(c["as_of"]) + timedelta(seconds=seconds*c["speed"]), end)
            if step or c.get("replay_mode") == "compressed":
                # Compressed replay skips quiet time: advance at least to the next delivered message.
                row = tx.run("MATCH (f:ProviderFeedItem {status:'PENDING'}) WHERE f.deliver_at > $now "
                             "RETURN min(f.deliver_at) AS next", now=instant(c["as_of"])).single()
                upcoming = public_value(row["next"]) if row and row["next"] else None
                if upcoming and instant(upcoming) > target:
                    target = min(instant(upcoming), end)
            return target.isoformat(), c
        target, control = self._execute(plan, write=True)
        if target is None:
            return {"events_replayed": 0, "as_of": control["as_of"], "case_ids": [], "status": self.status()}
        ingested, counts = [], {"duplicate": 0, "conflicting_duplicate": 0, "rejected": 0}
        while True:
            # Every message delivered by the previous clock was already ingested: one that turns up now with an
            # earlier delivery time was enqueued late and is stamped at this tick, never back-dated before it.
            batch = self.gateway.ingest_due(target, limit=INGEST_BATCH, not_before=control["as_of"])
            ingested.extend(batch["items"])
            for key in counts: counts[key] += batch[key]
            if batch["messages"] < INGEST_BATCH: break
        def record(tx):
            c = self._control(tx, lock=True)
            previous = instant(c["as_of"])
            for sid, kind, entity_id in ingested:
                if sid: self._live_case_event(tx, sid, kind, entity_id, target)
            c["event_count"] += len(ingested)
            c.update(cursor_time=target, cursor_id="", as_of=max(c["as_of"], target, key=instant))
            due = self._due_shipments(tx, previous, instant(c["as_of"]))
            touched = [sid for sid, _, _ in ingested if sid]
            c["monitor_queue"] = monitor_enqueue(c.get("monitor_queue") or [], [*touched, *due])
            self._put(tx, "OpsControl", c, update=True)
            return c["as_of"]
        as_of = self._execute(record, write=True)
        return {"events_replayed": len(ingested), "as_of": as_of, "case_ids": [], **counts, "status": self.status()}

    def _live_case_event(self, tx, sid, kind, entity_id, when):
        """New ingested evidence advances the shipment's open cases; a non-receipt report reopens a resolved one."""
        for item in tx.run("MATCH(c:OpsCase {shipment_id:$sid,dataset_id:$dataset,split:'development'}) RETURN properties(c) AS props",
                           sid=sid, dataset=self.dataset_id):
            case = public_value(item["props"])
            if instant(when) <= instant(case["as_of"]):
                continue
            case.update(as_of=when, state_version=case["state_version"]+1, evidence_events=(case.get("evidence_events") or 0)+1)
            if kind == "RecipientReport" and case["workflow_state"] == "RESOLVED":
                case.update(workflow_state="REOPENED", state_version=case["state_version"]+1, is_terminal=False, closed_at=None, verified_outcome_id=None)
                without_diagnosis(case, pending=True)
                self._invalidate_outcomes(tx, case)
                self._audit(tx, case, "CASE_REOPENED", when, result="A new attributed recipient report reopens investigation.", actor="SUHAIL-INGESTION")
            self._put(tx, "OpsCase", case, update=True)
            self._audit(tx, case, "EVIDENCE_INGESTED", when, result=kind, key=entity_id, actor="SUHAIL-INGESTION")

    def monitor_step(self, limit=5):
        """Check queued shipments against visible evidence only (events <= scenario clock)."""
        def take(tx):
            c=self._control(tx,lock=True)
            queue=list(c.get("monitor_queue") or [])
            if not queue:return None,c["as_of"]
            if self.demo_shipments is not None:
                # A curated session: shipments outside the list leave the queue unchecked and never become cases.
                listed=[sid for sid in queue if sid in self.demo_shipments]
                c["monitor_queue"]=listed[limit:];self._put(tx,"OpsControl",c,update=True)
                return listed[:limit],c["as_of"]
            c["monitor_queue"]=queue[limit:];self._put(tx,"OpsControl",c,update=True)
            return queue[:limit],c["as_of"]
        batch,clock=self._execute(take,write=True)
        if not batch:return {"checked":0,"opened":[]}
        from dataset_v2.derive import assess_shipment
        from operations.reasoning import evidence_world, journey_forecast
        findings=[]
        for sid in batch:
            try:context=self._reader().evidence(sid,clock)
            except LookupError:continue  # Shipment not yet visible at this snapshot.
            world=evidence_world(context,self.config)
            assessment=assess_shipment(world,sid,context["as_of"],detection_allowance_seconds=DETECTION_ALLOWANCE_SECONDS)
            finding=monitor_finding(assessment)
            # Milestone risk is a travel-window estimate from route bounds, not a validated prediction:
            # it is recorded as a watch flag and never opens a case on its own.
            forecast=journey_forecast(world,assessment) if not finding["open"] else {"available":False}
            findings.append((sid,finding,context["as_of"],forecast,context))
        def record(tx):
            c=self._control(tx,lock=True);opened=[]
            for sid,finding,as_of,forecast,context in findings:
                c["monitor_checked"]=c.get("monitor_checked",0)+1
                self._risk_flag(tx,sid,forecast,as_of)
                cases=[public_value(r["props"]) for r in tx.run("MATCH(c:OpsCase {shipment_id:$sid,dataset_id:$dataset,split:'development'}) RETURN properties(c) AS props",
                        sid=sid,dataset=self.dataset_id)]
                # Records ingested since a finished investigation: only a material one requeues its case.
                for case in cases:self._reinvestigate_for_evidence(tx,case,context,as_of)
                if not finding["open"]:continue
                active=[x for x in cases if not x.get("is_terminal") and x["workflow_state"]!="RESOLVED"]
                if active:
                    # The open case follows this shipment; newly observed symptoms are added to it, not a new case.
                    case=active[0];new=sorted(set(finding["symptoms"])-set(case.get("symptom_codes") or []))
                    if new:
                        case.update(symptom_codes=sorted(set(case.get("symptom_codes") or [])|set(new)),state_version=case["state_version"]+1)
                        if not case.get("diagnosis_available"):case["operational_status"]=symptom_status(case["symptom_codes"])
                        self._put(tx,"OpsCase",case,update=True)
                        self._audit(tx,case,"SYMPTOMS_UPDATED",as_of,actor="SUHAIL-MONITOR",result="New symptoms: "+", ".join(new))
                        self._reinvestigate_for_symptoms(tx,case,new,as_of)
                    continue
                seen=set().union(*[set(x.get("symptom_codes") or []) for x in cases]) if cases else set()
                if cases and set(finding["symptoms"])<=seen:
                    continue  # Same symptoms as an already resolved case: nothing new to open.
                opened.append(self._open_monitored_case(tx,sid,finding["symptoms"],as_of,c.get("session_id"),len(cases)))
                c["monitor_opened"]=c.get("monitor_opened",0)+1
            self._put(tx,"OpsControl",c,update=True)
            return opened
        opened=self._execute(record,write=True)
        return {"checked":len(findings),"opened":opened}

    def _reinvestigate_for_symptoms(self,tx,case,new,when):
        """A standing or human-floor symptom was added to a case that was already investigated: its diagnosis was made
        without it, so the case is queued for re-investigation. Bounded by MAX_SYMPTOM_REINVESTIGATIONS (no loops). A
        case whose action is authorized, dispatched or awaiting its outcome is never requeued here: the dispatch recheck
        and the outcome verifier handle it, and the executed action keeps its verification."""
        from operations.authority import HUMAN_FLOOR_SYMPTOMS
        significant=sorted(set(new)&(STANDING_SYMPTOMS|HUMAN_FLOOR_SYMPTOMS))
        if not significant or not case.get("last_run_id") or case["workflow_state"] not in REINVESTIGABLE_STATES:
            return False
        done=case.get("symptom_reinvestigations") or 0
        if done>=MAX_SYMPTOM_REINVESTIGATIONS:
            self._audit(tx,case,"REINVESTIGATION_LIMIT",when,actor="SUHAIL-MONITOR",key="symptoms:"+",".join(significant),
                        result=f"New symptoms ({', '.join(significant)}) after {done} symptom-driven re-investigations; the case stays "
                               f"{case['workflow_state']} for a person, and approval and dispatch keep rechecking its context.")
            return False
        old=case["workflow_state"]
        case.update(workflow_state="OPEN",recommendation_id=None,state_version=case["state_version"]+1,
                    symptom_reinvestigations=done+1,outcome_checked_as_of=None)
        without_diagnosis(case,pending=True)
        self._put(tx,"OpsCase",case,update=True)
        self._audit(tx,case,"REINVESTIGATION_QUEUED",when,actor="SUHAIL-MONITOR",old=old,key="symptoms:"+",".join(significant),
                    result=f"New symptoms ({', '.join(significant)}) were observed after the investigation; the earlier investigation "
                           "remains recorded and the case is investigated again with the evidence visible now.")
        return True

    def _reinvestigate_for_evidence(self,tx,case,context,when):
        """Records became visible after a finished investigation. Routine ones leave the case where it is; a material
        one (operations.materiality: it supersedes or re-versions a record the conclusion cites, is a late upload from
        before the investigation's snapshot, or adds or clears a monitor finding) queues the case for re-investigation.
        Bounded by MAX_EVIDENCE_REINVESTIGATIONS. As with symptoms, a case whose action is authorized, dispatched or
        awaiting its outcome is never requeued here: the dispatch recheck and the outcome verifier handle it."""
        checked=case.get("evidence_checked_as_of")
        if (not case.get("last_run_id") or case.get("is_terminal") or case["workflow_state"] not in REINVESTIGABLE_STATES
                or not checked or not case.get("investigated_as_of") or instant(case["as_of"])<=instant(checked)
                or instant(when)<=instant(checked)):
            return False
        run=self._get(tx,"OpsRun",case["last_run_id"]) or {}
        material=materiality.material_evidence(self._reader().evidence(case["shipment_id"],checked),context,
                                               snapshot_at=case["investigated_as_of"],config=self.config,allowance=DETECTION_ALLOWANCE_SECONDS,
                                               cited=materiality.cited_evidence_ids(json.loads(run.get("result_json") or "{}")))
        case["evidence_checked_as_of"]=when  # Each record is checked once; the case version is not touched by the check.
        done=case.get("evidence_reinvestigations") or 0
        if not material or done>=MAX_EVIDENCE_REINVESTIGATIONS:
            self._put(tx,"OpsCase",case,update=True)
            if material:
                self._audit(tx,case,"REINVESTIGATION_LIMIT",when,actor="SUHAIL-MONITOR",key="evidence:"+when,
                            result=f"Material new evidence ({materiality.describe(material)}) after {done} evidence-driven re-investigations; "
                                   f"the case stays {case['workflow_state']} for a person, and approval and dispatch keep rechecking its context.")
            return False
        old=case["workflow_state"]
        case.update(workflow_state="OPEN",recommendation_id=None,state_version=case["state_version"]+1,
                    evidence_reinvestigations=done+1,outcome_checked_as_of=None)
        without_diagnosis(case,pending=True)
        self._put(tx,"OpsCase",case,update=True)
        self._audit(tx,case,"REINVESTIGATION_QUEUED",when,actor="SUHAIL-MONITOR",old=old,key="evidence:"+when,
                    result=f"Material new evidence after the investigation ({materiality.describe(material)}); the earlier investigation "
                           "remains recorded and the case is investigated again with the evidence visible now.")
        return True

    def _risk_flag(self,tx,sid,forecast,when):
        identifier=identity("risk",sid)
        existing=self._get(tx,"OpsRiskFlag",identifier)
        at_risk=bool(forecast.get("available") and forecast.get("sla_risk"))
        if not at_risk and not existing:return
        flag={"entity_id":identifier,"shipment_id":sid,"recorded_at":(existing or {}).get("recorded_at",when),"occurred_at":when,
              "active":at_risk,"certainty":"travel_window_estimate","promise_at":forecast.get("promise_at"),
              "latest_estimate_at":forecast.get("latest_estimate_at"),"earliest_estimate_at":forecast.get("earliest_estimate_at"),
              "evidence_ids":forecast.get("evidence_ids",[]),"checked_at":when}
        if existing and existing.get("active")==at_risk and existing.get("latest_estimate_at")==flag["latest_estimate_at"]:return
        self._put(tx,"OpsRiskFlag",flag,update=bool(existing))

    def _open_monitored_case(self,tx,sid,symptoms,when,session_id,sequence=0):
        identifier=identity("case","monitor",session_id,sid,*([sequence] if sequence else []))
        status=symptom_status(symptoms)
        row=tx.run("MATCH(s:V2Entity:Shipment {entity_id:$sid,dataset_id:$dataset,split:'development'}) RETURN s.destination_city AS city",
                   sid=sid,dataset=self.dataset_id).single()
        case=self._put(tx,"OpsCase",{"entity_id":identifier,"shipment_id":sid,"source_case_id":None,"opened_by":"MONITOR",
            "session_id":session_id,"workflow_state":"OPEN","operational_status":status,
            "priority":"high" if status in {"CRITICAL","UNRECONCILED_CUSTODY","DELIVERY_DISPUTE"} else "medium",
            "symptom_codes":symptoms,"cause_codes":[],"city":row["city"] if row else "","opened_at":when,"recorded_at":when,"as_of":when,"state_version":0,
            "issue_summary":MONITOR_SUMMARY_PENDING,"diagnosis_available":False,"rule_signal_codes":[]})
        self._link(tx,"OPS_ABOUT",identifier,sid,sid,when)
        self._audit(tx,case,"CASE_OPENED",when,result="Monitor symptoms: "+", ".join(symptoms),actor="SUHAIL-MONITOR")
        return identifier

    def reset_confirmation(self):
        """The confirmation a development reset must carry. It names the current session, so a replayed or
        stale request (made before another reset) is refused."""
        return reset_token(self._execute(lambda tx:self._control(tx)))

    def _reset_audit(self,actor_id,result,reason,**details):
        """Reset attempts are recorded on the control record, which the reset never deletes."""
        entry={"result":result,"actor_id":actor_id,"wall_recorded_at":datetime.now(timezone.utc).isoformat(),"reason":reason,**details}
        log.warning("Development ledger reset %s by %s: %s",result,actor_id,reason)
        def record(tx):
            c=self._control(tx,lock=True)
            entry["clock"]=c["as_of"];entry.setdefault("session_id",c.get("session_id"))
            c["reset_audit_json"]=canonical([*json.loads(c.get("reset_audit_json") or "[]"),entry][-RESET_AUDIT_LIMIT:])
            self._put(tx,"OpsControl",c,update=True)
        self._execute(record,write=True)
        return entry

    def reset_session(self, actor_id="DEMO-OPERATOR-LOCAL", confirmation=None):
        """Development only: clear the derived operational ledger (never V2 evidence) and rewind the clock.

        This deletes every case, run, decision, execution, outcome and audit record of the session. It runs only
        when the server was started with SUHAIL_DEV_RESET=1 and the request carries the current confirmation
        (reset_confirmation()); otherwise it is refused. Every attempt, refused or performed, is audited."""
        require_actor(actor_id)
        if not development_reset_enabled():
            self._reset_audit(actor_id,"REFUSED","development reset disabled")
            raise OperationsConflict(f"Development reset is disabled. It deletes the operations ledger and runs only on a server "
                                     f"started with {DEV_RESET_ENV}=1.")
        expected=self.reset_confirmation()
        if not isinstance(confirmation,str) or confirmation!=expected:
            self._reset_audit(actor_id,"REFUSED","missing or stale confirmation")
            raise OperationsConflict("Development reset needs the confirmation for the current session "
                                     "(status: development_reset.confirmation); nothing was deleted.")
        outcome={}
        def reset_tx(tx):
            # The control lock is held from here to the commit: no worker can claim a case between the check below and
            # the deletions, and the live ingestion ledger is reset only after that check, under the same lock.
            c=self._control(tx,lock=True);now=self._wall()
            # Every live claim is checked, case by case; one whose lease ran out is requeued first and does not count.
            self._recover_expired(tx,c,now)
            active=[case["entity_id"] for case in self._live_claims(tx,now)]
            if active:
                entry={"result":"REFUSED","actor_id":actor_id,"wall_recorded_at":datetime.now(timezone.utc).isoformat(),
                       "reason":"investigation worker active","clock":c["as_of"],"session_id":c.get("session_id"),
                       "active_case_id":active[0],"active_case_ids":active}
                c["reset_audit_json"]=canonical([*json.loads(c.get("reset_audit_json") or "[]"),entry][-RESET_AUDIT_LIMIT:])
                self._put(tx,"OpsControl",c,update=True)
                return "worker_active"  # Committed: the refusal is audited and nothing was deleted.
            if self.live:
                try:self.gateway.reset()
                except Exception as error:
                    outcome["gateway_error"]=type(error).__name__
                    raise
                start=self.gateway.first_delivery()
            else:
                row=tx.run("MATCH (e:V2Entity {dataset_id:$dataset,split:'development'}) WHERE e.occurred_at IS NOT NULL "
                           "RETURN min(e.occurred_at) AS start",dataset=self.dataset_id).single()
                start=public_value(row["start"]) if row and row["start"] else None
            start=start or c["initial_as_of"]
            start=start.isoformat() if hasattr(start,"isoformat") else str(start)
            start=(instant(start)-timedelta(seconds=1)).isoformat()
            deleted=tx.run("MATCH (n:OpsEntity {dataset_id:$dataset,split:'development'}) WHERE NOT n:OpsControl DETACH DELETE n "
                           "RETURN count(n) AS deleted",dataset=self.dataset_id).single()
            session=identity("session",c["state_version"],start)
            outcome.update(deleted_records=deleted["deleted"] if deleted else None,session_before=c.get("session_id"),session_after=session,
                           clock=c["as_of"])
            c.update(as_of=start,initial_as_of=start,cursor_time=start,cursor_id="",simulator_state="paused",worker_state="paused",
                     worker_claim=None,claim_at=None,claim_shipment_id=None,processed_count=0,event_count=0,
                     last_case_id=None,last_shipment_id=None,last_workflow_state=None,last_processed_at=None,
                     case_source="monitor",session_id=session,session_started_at=start,monitor_queue=[],monitor_checked=0,monitor_opened=0)
            # Audited in the same transaction as the deletion, on the record the deletion keeps.
            entry={"result":"PERFORMED","actor_id":actor_id,"wall_recorded_at":datetime.now(timezone.utc).isoformat(),
                   "reason":"confirmed development reset","session_id":outcome["session_before"],**outcome}
            c["reset_audit_json"]=canonical([*json.loads(c.get("reset_audit_json") or "[]"),entry][-RESET_AUDIT_LIMIT:])
            self._put(tx,"OpsControl",c,update=True)
        try:
            refused=self._execute(reset_tx,write=True)
        except Exception as error:
            if "gateway_error" not in outcome:raise
            # The ingestion reset failed under the lock: the operations ledger was not deleted. Audited, then refused.
            self._reset_audit(actor_id,"FAILED","live ingestion ledger reset failed",error=outcome["gateway_error"])
            raise OperationsConflict("The live ingestion ledger could not be reset; the operations ledger was not deleted.") from error
        if refused=="worker_active":
            log.warning("Development ledger reset REFUSED for %s: investigation worker active",actor_id)
            raise OperationsConflict("Pause auto-triage before starting a new session; nothing was deleted.")
        log.warning("Development ledger reset PERFORMED by %s: %s records deleted",actor_id,outcome.get("deleted_records"))
        if self.adapter is not None and hasattr(self.adapter,"reset"):self.adapter.reset()  # A new session: the field as it was.
        return self.status()

    def outcome_step(self, limit=3, *, case_id=None, force=False):
        """Verify automatically executed actions from evidence that arrived after them (live sessions only)."""
        from operations.outcome_engine import evaluate, EVIDENCE_ACTIONS
        from operations.reasoning import evidence_world
        from operations import action_lifecycle
        def due(tx):
            c=self._control(tx)
            rows=tx.run("MATCH(c:OpsEntity:OpsCase {dataset_id:$dataset,split:'development',workflow_state:'AWAITING_OUTCOME'}) "
                "MATCH(e:OpsEntity:OpsExecution {case_id:c.entity_id,status:'ACKNOWLEDGED'}) "
                "WHERE ($case_id IS NULL OR c.entity_id=$case_id) AND ($force OR c.outcome_checked_as_of IS NULL "
                "OR c.as_of > c.outcome_checked_as_of OR e.deadline_at <= $clock) "
                "RETURN properties(c) AS case,properties(e) AS execution ORDER BY c.as_of LIMIT $limit",
                dataset=self.dataset_id,clock=instant(c["as_of"]),limit=limit,case_id=case_id,force=force)
            return [(public_value(r["case"]),public_value(r["execution"])) for r in rows],c["as_of"]
        items,clock=self._execute(due)
        results=[]
        from dataset_v2.derive import assess_shipment
        for case,execution in items:
            lifecycle=action_lifecycle.load(execution)
            if lifecycle and lifecycle.get("requires_response_events"):
                if lifecycle["state"]!="EVIDENCE_RECEIVED":
                    if instant(clock)>=instant(execution["deadline_at"]):
                        self._expire_action(execution["entity_id"])
                    continue
                execution["action_protocol"]=action_lifecycle.VERSION
                execution["action_target"]=json.loads(execution.get("action_target_json") or "{}")
                execution["expected_evidence"]=json.loads(execution.get("expected_evidence_json") or "[]")
            context=self._reader().evidence(case["shipment_id"],clock)
            world=evidence_world(context,self.config)
            verdict=evaluate(world,case["shipment_id"],execution,context["as_of"])
            # Resolution means the exception is gone, not only that the action worked: the verifier re-assesses
            # the same evidence snapshot and keeps the case open while a standing symptom remains.
            fresh,delivered=set(),False
            if verdict["status"]=="success":
                assessment=assess_shipment(world,case["shipment_id"],context["as_of"],detection_allowance_seconds=DETECTION_ALLOWANCE_SECONDS)
                fresh=set(monitor_finding(assessment)["symptoms"])
                delivered=delivery_corroborated(assessment)
            def record(tx,case=case,execution=execution,verdict=verdict,fresh=fresh,delivered=delivered):
                from operations.authority import HUMAN_FLOOR_SYMPTOMS, OPEN_DISPUTE_SYMPTOMS, DISPUTES_CLEARED_BY_ACTION
                c=self._control(tx,lock=True);current=self._case(tx,case["entity_id"]);when=c["as_of"]
                if (current["workflow_state"]!="AWAITING_OUTCOME" or current["state_version"]!=case["state_version"] or
                    instant(when)!=instant(clock)):return None  # Re-read after concurrent evidence/clock changes.
                latest_execution=self._get(tx,"OpsExecution",execution["entity_id"])
                if lifecycle and lifecycle.get("requires_response_events"):
                    latest_state=action_lifecycle.load(latest_execution)
                    if not latest_state or latest_state["revision"]!=lifecycle["revision"] or latest_state["state"]!="EVIDENCE_RECEIVED":return None
                if verdict["status"]=="pending":
                    current["outcome_checked_as_of"]=current["as_of"];self._put(tx,"OpsCase",current,update=True);return None
                success=verdict["status"]=="success";outcome_id=identity("outcome","auto",execution["entity_id"],when)
                recorded=set(current.get("symptom_codes") or [])
                remaining=sorted(set(fresh)&STANDING_SYMPTOMS)
                others=[]
                if success:
                    # One corrected issue never closes the shipment. Whatever the action, a success does not close a case
                    # while a standing symptom is visible, while a custody, delivery or recipient dispute is recorded or
                    # visible that this action does not itself settle (and that is no longer visible), while another case
                    # of this shipment is still open, or (an address confirmation) while nothing was delivered.
                    others=self._other_open_cases(tx,current)
                    remaining=remaining_symptoms(recorded,fresh,is_delivered=delivered,other_cases=others,outcome_type=verdict["outcome_type"],
                                                 settled=DISPUTES_CLEARED_BY_ACTION.get(execution.get("action_type"),frozenset()))
                self._put(tx,"OpsOutcome",{"entity_id":outcome_id,"shipment_id":current["shipment_id"],"case_id":current["entity_id"],
                    "run_id":execution.get("run_id") or current.get("last_run_id"),
                    "execution_id":execution["entity_id"],"action_code":execution["action_code"],"action_type":execution["action_type"],"success":success,
                    "outcome_type":verdict["outcome_type"],"evidence_ids":verdict["evidence_ids"],"verification_status":"VERIFIED",
                    "verified_at":when,"verifier_id":"SUHAIL-OUTCOME-VERIFIER","invalidated":False,"observed_at":when,
                    "reason":verdict["reason"],"rule_id":verdict.get("rule_id"),"expected_effect":verdict.get("expected_effect"),
                    "exception_cleared":success and not remaining,"remaining_symptoms":remaining,"source":"evidence_verifier",
                    # Decided by the verifier from evidence recorded after the action: the only kind trusted without a person.
                    "trusted_precedent":True,
                    "recorded_at":when,"occurred_at":when})
                self._link(tx,"OPS_HAS_OUTCOME",current["entity_id"],outcome_id,current["shipment_id"],when)
                self._audit(tx,current,"OUTCOME_OBSERVED",when,actor="SUHAIL-OUTCOME-VERIFIER",result=verdict["reason"])
                old=current["workflow_state"]
                # A human-floor symptom recorded on the case or visible now reserves closure for a person.
                floor=sorted((recorded|set(fresh))&HUMAN_FLOOR_SYMPTOMS)
                if others:
                    self._audit(tx,current,"OTHER_OPEN_CASES",when,actor="SUHAIL-OUTCOME-VERIFIER",key=execution["entity_id"],
                                result="Another case of this shipment is still open: "+", ".join(o["entity_id"] for o in others)+". Not closed by this outcome.")
                if success and remaining:
                    # The action did what it was meant to, but the exception is still there: not resolved.
                    current.update(workflow_state="HUMAN_REVIEW",symptom_codes=sorted(recorded|(set(remaining)&set(fresh)&(STANDING_SYMPTOMS|OPEN_DISPUTE_SYMPTOMS))),
                                   state_version=current["state_version"]+1)
                    self._put(tx,"OpsCase",current,update=True)
                    self._audit(tx,current,"OUTCOME_VERIFIED_EXCEPTION_REMAINS",when,actor="SUHAIL-OUTCOME-VERIFIER",old=old,
                                result=f"{execution['action_type']} verified: {verdict['reason']} The exception remains "
                                       f"({', '.join(remaining)}); not resolved, routed to HUMAN_REVIEW.")
                elif success and (execution.get("closure")=="HUMAN" or floor):
                    # Verified evidence, but the observed symptoms reserve closure for a person.
                    current.update(workflow_state="HUMAN_REVIEW",state_version=current["state_version"]+1)
                    self._put(tx,"OpsCase",current,update=True)
                    self._audit(tx,current,"OUTCOME_VERIFIED_HUMAN_CLOSURE",when,actor="SUHAIL-OUTCOME-VERIFIER",old=old,
                                result=f"{execution['action_type']} verified: {verdict['reason']} Closure reserved for a person"
                                       +(f" ({', '.join(floor)})." if floor else "."))
                elif success and execution.get("closure")=="REASSESS":
                    # AUTH-27: the action ran under a reviewer's doubt. Its verified result is new evidence, not a
                    # resolution: the case goes back to the investigator and the reviewer.
                    current.update(workflow_state="OPEN",recommendation_id=None,reassess_outcome_id=outcome_id,quiet_until=None,
                                   outcome_checked_as_of=None,state_version=current["state_version"]+1)
                    without_diagnosis(current,pending=True)
                    self._put(tx,"OpsCase",current,update=True)
                    self._audit(tx,current,"OUTCOME_VERIFIED_REASSESSMENT",when,actor="SUHAIL-OUTCOME-VERIFIER",old=old,key=outcome_id,
                                result=f"{execution['action_type']} verified: {verdict['reason']} The reviewer had not accepted the "
                                       "investigation (AUTH-27), so nothing is resolved yet: the case is investigated and reviewed "
                                       "again with the new evidence.")
                elif success:
                    current.update(workflow_state="RESOLVED",operational_status="RESOLVED",is_terminal=True,closed_at=when,
                                   verified_outcome_id=outcome_id,state_version=current["state_version"]+1)
                    self._put(tx,"OpsCase",current,update=True)
                    self._audit(tx,current,"OUTCOME_VERIFIED",when,actor="SUHAIL-OUTCOME-VERIFIER",old=old,
                                result=f"{execution['action_type']} succeeded: {verdict['reason']}")
                    self._audit(tx,current,"CASE_RESOLVED",when,actor="SUHAIL-OUTCOME-VERIFIER",old=old,
                                result="Resolved from independently observed later evidence; no human action.")
                    self._audit(tx,current,"NOTIFICATION_QUEUED",when,actor="SUHAIL-OUTCOME-VERIFIER",result="Dry run only; zero external sends.")
                else:
                    destination="HUMAN_REVIEW"  # Unresolved: a failed or unconfirmed action never closes a case.
                    current.update(workflow_state=destination,state_version=current["state_version"]+1)
                    self._put(tx,"OpsCase",current,update=True)
                    self._audit(tx,current,"OUTCOME_FAILED",when,actor="SUHAIL-OUTCOME-VERIFIER",old=old,
                                result=f"{execution['action_type']} not confirmed: {verdict['reason']} Routed to {destination}.")
                stored=self._get(tx,"OpsExecution",execution["entity_id"])
                state=action_lifecycle.load(stored)
                if state:
                    stored["action_lifecycle_json"]=canonical(action_lifecycle.verification(state,verdict,when,
                                                                resolved=current["workflow_state"]=="RESOLVED"))
                    self._put(tx,"OpsExecution",stored,update=True)
                return {"case_id":current["entity_id"],"workflow_state":current["workflow_state"]}
            result=self._execute(record,write=True)
            if result:results.append(result)
        return results

    def _expire_action(self,execution_id):
        from operations import action_lifecycle
        def expire(tx):
            control=self._control(tx,lock=True);when=control["as_of"]
            execution=self._get(tx,"OpsExecution",execution_id)
            state=action_lifecycle.load(execution)
            if not state or state["state"] in action_lifecycle.TERMINAL or instant(when)<instant(execution["deadline_at"]):return
            case=self._case(tx,execution["case_id"])
            execution["action_lifecycle_json"]=canonical(action_lifecycle.verification(state,
                {"status":"pending","deadline_at":execution["deadline_at"]},when))
            execution["status"]="RESPONSE_EXPIRED"
            self._put(tx,"OpsExecution",execution,update=True)
            if not case.get("is_terminal"):
                case.update(workflow_state="NEEDS_EVIDENCE",state_version=case["state_version"]+1)
                self._put(tx,"OpsCase",case,update=True)
            self._audit(tx,case,"ACTION_RESPONSE_EXPIRED",when,actor="SUHAIL-EXECUTION-ADAPTER",key=execution_id,
                        result="Synthetic operational response expired. No outcome or resolution is asserted.")
        self._execute(expire,write=True)

    def record_action_response(self,case_id,execution_id,*,actor_id,expected_revision,response_id,kind,occurred_at,evidence_ids,source_ref):
        """Simulation-only operational response, never a success/authority input."""
        from operations import action_lifecycle
        from operations.reasoning import evidence_world
        require_actor(actor_id)
        if (os.environ.get("SUHAIL_SYNTHETIC_ACTION_RESPONSES")!="1" or
            not isinstance(self.adapter,action_lifecycle.SyntheticActionAdapter)):
            raise OperationsConflict("Synthetic response transport is not explicitly enabled")
        event={"response_id":response_id,"kind":kind,"occurred_at":occurred_at,"evidence_ids":evidence_ids,"source_ref":source_ref}
        def record(tx):
            control=self._control(tx,lock=True);when=control["as_of"]
            case=self._case(tx,case_id);execution=self._get(tx,"OpsExecution",execution_id)
            if (not execution or execution["case_id"]!=case_id or execution["shipment_id"]!=case["shipment_id"] or
                not execution.get("receipt_ref") or execution.get("mode")!=self.adapter.name):
                raise OperationsConflict("Response must refer to this case's dispatched synthetic request")
            state=action_lifecycle.load(execution)
            updated,replay=action_lifecycle.respond(state,event,now=when,deadline=execution["deadline_at"],revision=expected_revision)
            if replay:return {"action_lifecycle":action_lifecycle.view(execution),"idempotent":True}
            world=evidence_world(self._reader().evidence(case["shipment_id"],when),self.config)
            for ref in evidence_ids:
                node=world.nodes.get(ref)
                if (node is None or node.properties.get("shipment_id")!=case["shipment_id"] or
                    not node.properties.get("source_ref") or not node.properties.get("recorded_at") or
                    not instant(execution["occurred_at"])<instant(node.properties["recorded_at"])<=instant(when)):
                    raise OperationsConflict("Response evidence must be visible, own, source-backed and received after dispatch")
            execution["action_lifecycle_json"]=canonical(updated)
            if updated["state"] in ("FAILED","REJECTED"):
                execution["status"]="RESPONSE_"+updated["state"]
                if not case.get("is_terminal"):
                    case.update(workflow_state="NEEDS_EVIDENCE",state_version=case["state_version"]+1)
                    self._put(tx,"OpsCase",case,update=True)
            elif kind=="EVIDENCE_RECEIVED" and not updated["events"][-1]["late"]:
                case.update(outcome_checked_as_of=None,state_version=case["state_version"]+1)
                self._put(tx,"OpsCase",case,update=True)
            self._put(tx,"OpsExecution",execution,update=True)
            self._audit(tx,case,"ACTION_RESPONSE_RECEIVED",when,actor=actor_id,key=f"{execution_id}:{response_id}",
                        result=canonical({"execution_id":execution_id,"kind":kind,"source_ref":source_ref,
                                          "evidence_ids":evidence_ids,"late":updated["events"][-1]["late"],"synthetic":True}))
            return {"action_lifecycle":action_lifecycle.view(execution),"idempotent":False}
        return self._execute(record,write=True)

    def _reassessment_result(self,tx,current,analysis,reassess,stale,when):
        """AUTH-27, after the action that ran under a reviewer's doubt was verified: this run is the reassessment on the
        new evidence. Returns (outcome id or None, analysis). The case resolves only when this run's independent review
        accepted, nothing degraded or superseded it, and the exception is still cleared on its snapshot by the same test
        the outcome verifier applies; otherwise it goes to a person. Nothing is executed from this run either way."""
        from operations.authority import HUMAN_FLOOR_SYMPTOMS, DISPUTES_CLEARED_BY_ACTION
        outcome=self._get(tx,"OpsOutcome",reassess["outcome_id"]) or {}
        review=analysis.get("review") or {}
        accepted=(review.get("verdict")=="accept" and review.get("model_verdict")=="ACCEPT" and not analysis.get("degraded")
                  and not stale and bool(analysis.get("investigation")))
        recorded=set(current.get("symptom_codes") or []);fresh=set(reassess.get("fresh") or [])
        others=self._other_open_cases(tx,current)
        remaining=remaining_symptoms(recorded,fresh,is_delivered=bool(reassess.get("delivered")),other_cases=others,
                                     outcome_type=outcome.get("outcome_type"),
                                     settled=DISPUTES_CLEARED_BY_ACTION.get(outcome.get("action_type"),frozenset()))
        floor=sorted((recorded|fresh)&HUMAN_FLOOR_SYMPTOMS)
        verified=bool(outcome.get("success")) and outcome.get("verification_status")=="VERIFIED" and not outcome.get("invalidated")
        current["reassess_outcome_id"]=None
        if accepted and verified and not remaining and not floor:
            self._audit(tx,current,"REASSESSMENT_ACCEPTED",when,actor="SUHAIL-REVIEWER",key=reassess["outcome_id"],
                        result="The investigation was repeated on the evidence gathered by the action and the independent reviewer "
                               "accepted it; the verifier's result stands and no exception remains.")
            self._audit(tx,current,"CASE_RESOLVED",when,actor="SUHAIL-OUTCOME-VERIFIER",key=reassess["outcome_id"],
                        result="Resolved from independently observed later evidence after an accepted reassessment; no human action.")
            self._audit(tx,current,"NOTIFICATION_QUEUED",when,actor="SUHAIL-OUTCOME-VERIFIER",result="Dry run only; zero external sends.")
            return reassess["outcome_id"],{**analysis,"result":{**analysis["result"],"workflow_state":"RESOLVED"}}
        why=("the reviewer did not accept the reassessment ("+str(review.get("model_verdict") or review.get("verdict"))+")" if not accepted
             else "the verified result no longer stands" if not verified
             else "the exception remains ("+", ".join(remaining)+")" if remaining
             else "closure is reserved for a person ("+", ".join(floor)+")")
        self._audit(tx,current,"REASSESSMENT_NOT_ACCEPTED",when,actor="SUHAIL-REVIEWER",key=reassess["outcome_id"],
                    result=f"Not resolved after the reassessment: {why}. Routed to a person; nothing was executed from this run.")
        return None,{**analysis,"result":{**analysis["result"],"workflow_state":"HUMAN_REVIEW"}}

    def _other_open_cases(self,tx,case):
        rows=[public_value(r["props"]) for r in tx.run("MATCH(c:OpsCase {shipment_id:$sid,dataset_id:$dataset,split:'development'}) "
              "RETURN properties(c) AS props",sid=case["shipment_id"],dataset=self.dataset_id)]
        return [o for o in rows if o["entity_id"]!=case["entity_id"] and not o.get("is_terminal") and o["workflow_state"]!="RESOLVED"]

    def _authorize_execution(self,tx,case,execution_id,source_id,proposal,action_type,authority,when,*,decision_id,decided_risk,closure="AUTO",
                             recommendation_id,run_id):
        """Record an authorized action for the execution adapter. Authorization is not execution or success.
        The authority policy is re-checked here on every path; the caller has already refused what it denies.
        The recommendation is marked as authorized: it can never be approved (and so executed) a second time."""
        from operations.authority import execution_permission
        allowed,rule,reason=execution_permission(action_type,authority,decided_risk)
        if not allowed:raise OperationsConflict(f"{rule}: {reason}")
        target=(proposal.get("target") if isinstance(proposal.get("target"),dict) else None) or json.loads(proposal.get("target_json") or "{}")
        from operations.action_lifecycle import initial
        self._put(tx,"OpsExecution",{"entity_id":execution_id,"shipment_id":case["shipment_id"],"case_id":case["entity_id"],
            "decision_id":decision_id,"recommendation_id":recommendation_id,"run_id":run_id,
            "action_code":proposal.get("action_code"),"action_type":action_type,"authority":authority,
            "decided_risk":decided_risk,"permission_rule":rule,
            "status":"AUTHORIZED","expected_result":proposal.get("action"),"idempotency_key":execution_id,"closure":closure,
            "target_device":target.get("device_id"),"expected_evidence_json":canonical(target.get("expected_evidence") or []),
            "case_opened_at":case.get("opened_at"),
            "action_lifecycle_json":canonical(initial(when)),"action_target_json":canonical(target),
            "recorded_at":when,"occurred_at":when})
        self._link(tx,"OPS_INITIATES",source_id,execution_id,case["shipment_id"],when)
        recommendation=self._get(tx,"OpsRecommendation",recommendation_id)
        if recommendation:
            recommendation.update(status="AUTHORIZED",execution_id=execution_id)
            self._put(tx,"OpsRecommendation",recommendation,update=True)

    def _recommendation_executed(self,tx,case,recommendation):
        """Whether an execution was already authorized for this recommendation: recorded on it, or (for records written
        before that) an automatic execution of it or an approving decision on it."""
        rid=recommendation.get("entity_id")
        if recommendation.get("status")=="AUTHORIZED" or recommendation.get("execution_id"):return True
        if self._get(tx,"OpsExecution",identity("execution","auto",rid)):return True
        rows=tx.run("MATCH(n:OpsEntity:OpsDecision {case_id:$case_id,dataset_id:$dataset}) WHERE n.recommendation_id=$rid "
                    "AND n.decision='approve' RETURN properties(n) AS props ORDER BY n.recorded_at DESC,n.entity_id DESC LIMIT 20",
                    case_id=case["entity_id"],dataset=self.dataset_id,rid=rid)
        return any(r["props"].get("recommendation_id")==rid and r["props"].get("decision")=="approve" for r in rows)

    def execute_step(self, limit=5):
        """Execution adapter: carry out authorized actions (oldest first), exactly once each."""
        def claim(tx):
            c=self._control(tx,lock=True)
            rows=[public_value(r["e"]) for r in tx.run("MATCH(e:OpsEntity:OpsExecution {dataset_id:$dataset,status:'AUTHORIZED'}) "
                  "RETURN properties(e) AS e ORDER BY e.recorded_at,e.entity_id LIMIT $limit",dataset=self.dataset_id,limit=limit)]
            for e in rows:
                e["status"]="EXECUTING";self._put(tx,"OpsExecution",e,update=True)
            return rows,c["as_of"]
        rows,clock=self._execute(claim,write=True)
        done=[]
        from operations.authority import execution_permission
        for execution in rows:
            allowed,rule,reason=execution_permission(execution.get("action_type"),execution.get("authority"),execution.get("decided_risk"))
            if not allowed:
                # Defence in depth: whatever wrote it, an execution the policy does not allow is never dispatched.
                def refuse(tx,execution=execution,rule=rule,reason=reason):
                    c=self._control(tx,lock=True);when=c["as_of"]
                    current=self._get(tx,"OpsExecution",execution["entity_id"]);current.update(status="REFUSED",permission_rule=rule)
                    self._put(tx,"OpsExecution",current,update=True)
                    case=self._case(tx,current["case_id"]);old=case["workflow_state"]
                    if not case.get("is_terminal"):
                        case.update(workflow_state="HUMAN_REVIEW",state_version=case["state_version"]+1);self._put(tx,"OpsCase",case,update=True)
                    self._audit(tx,case,"EXECUTION_REFUSED",when,actor="SUHAIL-AUTHORITY-POLICY",key=rule,old=old,
                                result=f"{execution.get('action_type')} · {rule} · {reason} Nothing was dispatched.")
                self._execute(refuse,write=True)
                continue
            # Immediately before dispatch: the same recheck approval ran, on the case as it is now.
            def precheck(tx,execution=execution):
                c=self._control(tx,lock=True);when=c["as_of"]
                current=self._get(tx,"OpsExecution",execution["entity_id"]);case=self._case(tx,current["case_id"]);old=case["workflow_state"]
                check=self._dispatch_check(tx,case,current,when)
                if check["allowed"]:
                    # An execution recovered after a restart is checked again on a case that may not have moved since
                    # its first check. That check is on record already (same execution, same case version): writing it
                    # a second time would collide with it and the execution could never be dispatched again.
                    if not self._get(tx,"OpsAudit",identity("audit",case["entity_id"],"EXECUTION_CONTEXT_CHECKED",case["state_version"],current["entity_id"])):
                        self._audit(tx,case,"EXECUTION_CONTEXT_CHECKED",when,actor="SUHAIL-AUTHORITY-POLICY",key=current["entity_id"],
                                    result=canonical({"rule_id":check["rule"],"decided_risk":check["risk"],"execution_id":current["entity_id"],
                                                      "context":{k:check["current"].get(k) for k in CONTEXT_KEYS},
                                                      "routine_new_records":check["routine_new_records"]}))
                    return True
                current.update(status="REFUSED",permission_rule=check["rule"]);self._put(tx,"OpsExecution",current,update=True)
                if check["requeue"]:
                    self._requeue_stale(tx,case,when,"SUHAIL-AUTHORITY-POLICY","EXECUTION_CONTEXT_STALE",check,key=current["entity_id"])
                else:
                    if not case.get("is_terminal") and case["workflow_state"] in ("ACTION_INITIATED","AWAITING_OUTCOME"):
                        case.update(workflow_state="HUMAN_REVIEW",state_version=case["state_version"]+1);self._put(tx,"OpsCase",case,update=True)
                    self._audit(tx,case,"EXECUTION_REFUSED",when,actor="SUHAIL-AUTHORITY-POLICY",key=f"{check['rule']}:{current['entity_id']}",old=old,
                                result=f"{current.get('action_type')} · {check['rule']} · {check['reason']} Nothing was dispatched.")
                return False
            if not self._execute(precheck,write=True):
                continue
            execution["expected_evidence"]=json.loads(execution.get("expected_evidence_json") or "[]")
            if self.adapter is not None:
                try:receipt=self.adapter.respond(execution,clock);mode=getattr(self.adapter,"name","synthetic_operational_simulator")
                except Exception as error:receipt={"acknowledged":False,"behaviour":f"The execution adapter failed ({type(error).__name__}); nothing was confirmed as sent."};mode="adapter_error"
            else:
                receipt={"acknowledged":False,"behaviour":"No execution adapter is configured; nothing was sent."};mode="no_adapter"
            # When the field's answer, if one comes, is expected to have reached Suhail: the adapter's schedule for this
            # kind of request only. It says nothing about whether an answer will come or what it will be.
            expected=None
            if receipt.get("acknowledged") is not False and hasattr(self.adapter,"expected_response_at"):
                try:expected=self.adapter.expected_response_at(execution,clock)
                except Exception:expected=None
            def record(tx,execution=execution,receipt=receipt,mode=mode,expected=expected):
                c=self._control(tx,lock=True);when=c["as_of"]
                current=self._get(tx,"OpsExecution",execution["entity_id"])
                case=self._case(tx,current["case_id"])
                deadline=(instant(when)+timedelta(hours=AUTO_OUTCOME_WINDOW_HOURS)).isoformat()
                acknowledged=receipt.get("acknowledged") is not False
                from operations import action_lifecycle
                state=action_lifecycle.load(current) or action_lifecycle.initial(when)
                current["action_lifecycle_json"]=canonical(action_lifecycle.dispatched(state,when,
                    requires_responses=bool(getattr(self.adapter,"requires_response_events",False)),acknowledged=acknowledged))
                current.update(status="ACKNOWLEDGED" if acknowledged else "NOT_ACKNOWLEDGED",receipt_ref=f"{mode}:{execution['entity_id']}",
                               mode=mode,executed_at=when,occurred_at=when,deadline_at=deadline if acknowledged else None,
                               expected_response_at=expected if acknowledged else None,
                               adapter_result_json=canonical(receipt))
                self._put(tx,"OpsExecution",current,update=True)
                if not acknowledged:
                    # Nothing was accepted by a field system: nothing can be verified, so a person takes the case.
                    old=case["workflow_state"]
                    if not case.get("is_terminal"):
                        case.update(workflow_state="HUMAN_REVIEW",state_version=case["state_version"]+1);self._put(tx,"OpsCase",case,update=True)
                    self._audit(tx,case,"ACTION_NOT_ACKNOWLEDGED",when,actor="SUHAIL-EXECUTION-ADAPTER",key=execution["entity_id"],old=old,
                                result=f"{execution['action_type']} · {mode} · {receipt.get('behaviour')} Nothing to verify; routed to a person.")
                    return execution["entity_id"]
                if case["workflow_state"]=="ACTION_INITIATED":
                    case.update(workflow_state="AWAITING_OUTCOME",state_version=case["state_version"]+1);self._put(tx,"OpsCase",case,update=True)
                self._audit(tx,case,"ACTION_EXECUTED",when,actor="SUHAIL-EXECUTION-ADAPTER",key=execution["entity_id"],
                            result=f"{execution['action_type']} · {mode} · receipt only, not an outcome. Verification deadline {deadline}.")
                return execution["entity_id"]
            done.append(self._execute(record,write=True))
        return done

    def _update_cases_for_event(self,tx,row,p,sid,when):
        cases=list(tx.run("MATCH(c:OpsCase {shipment_id:$sid,dataset_id:$dataset,split:'development'}) RETURN properties(c) AS props",
                          sid=sid,dataset=self.dataset_id))
        for item in cases:
            case=public_value(item["props"])
            if instant(when)>instant(case["as_of"]):
                case["as_of"]=when
                case["state_version"]+=1
                case["evidence_events"]=(case.get("evidence_events") or 0)+1
                if "RecipientReport" in row["labels"] and case["workflow_state"]=="RESOLVED":
                    case.update(workflow_state="REOPENED",state_version=case["state_version"]+1,is_terminal=False,closed_at=None,verified_outcome_id=None)
                    without_diagnosis(case,pending=True)
                    self._invalidate_outcomes(tx,case)
                    self._audit(tx,case,"CASE_REOPENED",when,result="A new attributed recipient report reopens investigation.",actor="DEMO-SIMULATOR")
                self._put(tx,"OpsCase",case,update=True)
            self._audit(tx,case,"SIMULATION_EVENT",when,result=next(k for k in row["labels"] if k in EVENT_KINDS),key=p["entity_id"],actor="DEMO-SIMULATOR")

    def _quiet_until(self,when):
        """When the next automatic investigation of a case whose run finished at `when` may start (None: at once)."""
        seconds=reinvestigation_quiet_seconds(self.reinvestigation_quiet_seconds)
        return (instant(when)+timedelta(seconds=seconds)).isoformat() if seconds else None

    def _material_since_claim(self,current,claimed,analysis,now):
        """(material changes, new records) since a running investigation claimed its snapshot.
        Anything that moved the case record and is not accounted for by evidence ingestion is material."""
        reasons=[]
        before,after=set(claimed.get("symptom_codes") or []),set(current.get("symptom_codes") or [])
        if before!=after:
            reasons.append({"reason":"symptoms_changed","added":sorted(after-before),"cleared":sorted(before-after)})
        events=(current.get("evidence_events") or 0)-(claimed.get("evidence_events") or 0)
        if before==after and current["state_version"]-claimed["state_version"]!=events:
            reasons.append({"reason":"case_record_changed"})
        arrived=0
        if events>0:
            reader=self._reader();snapshot=reader.evidence(claimed["shipment_id"],claimed["as_of"]);visible=reader.evidence(claimed["shipment_id"],now)
            arrived=len(materiality.new_records(snapshot,visible))
            reasons+=materiality.material_evidence(snapshot,visible,snapshot_at=claimed["as_of"],cited=materiality.cited_evidence_ids(analysis),
                                                   config=self.config,allowance=DETECTION_ALLOWANCE_SECONDS)
        return reasons,arrived

    # ------------------------------------------------------------------ investigation claims (operations.claims)
    def _wall(self):
        return self.wall().astimezone(timezone.utc)

    def _investigating(self,tx):
        rows=tx.run("MATCH(c:OpsEntity:OpsCase {dataset_id:$dataset,split:'development',workflow_state:'INVESTIGATING'}) "
                    "RETURN properties(c) AS props ORDER BY c.entity_id",dataset=self.dataset_id)
        return [public_value(row["props"]) for row in rows]

    def _live_claims(self,tx,now):
        """The cases owned right now: INVESTIGATING under a claim whose lease has not expired."""
        return [case for case in self._investigating(tx) if claims.live(case,now)]

    def _owned(self,tx,claimed,now):
        """The claimed case as it is now, while `claimed` still owns it (same worker, token, epoch and run, lease not
        expired). Otherwise ClaimLost, and the transaction writes nothing."""
        case=self._get(tx,"OpsCase",claimed["entity_id"])
        reason=claims.lost(case,claimed,now)
        if reason:raise claims.ClaimLost(reason)
        return case

    def _close_run(self,tx,case,reason,now,*,failed=False):
        """Close the run of a claim that ends without a committed result. A run that was already closed stays as it is."""
        run=self._get(tx,"OpsRun",case.get("last_run_id") or "")
        if not run or run.get("end_reason"):return
        run.update(status="FAILED" if failed or run.get("status")=="FAILED" else "ABORTED",end_reason=reason,
                   finished_wall_at=now.isoformat(),active_stage=None)
        self._put(tx,"OpsRun",run,update=True)

    def _end_claim(self,tx,case,when,now,*,reason,event,actor,result,recovery,failed=False):
        """Take a case from its owner without a result: its run is closed, ownership moves on and the case is queued
        again. recovery: the investigation was lost (an expired lease, a failed worker) rather than stopped on purpose;
        after claims.MAX_RECOVERIES losses in a row the case goes to a person instead, with no diagnosis, review or
        outcome recorded for it."""
        self._close_run(tx,case,reason,now,failed=failed)
        old=case["workflow_state"];lost=(case.get("claim_recoveries") or 0)+(1 if recovery else 0)
        person=recovery and lost>=claims.MAX_RECOVERIES
        claims.release(case)
        case.update(workflow_state="HUMAN_REVIEW" if person else "OPEN",state_version=case["state_version"]+1,claim_recoveries=lost)
        if person:case["recommendation_id"]=None
        self._put(tx,"OpsCase",without_diagnosis(case,pending=not person),update=True)
        self._audit(tx,case,event,when,actor=actor,old=old,key=reason,result=result)
        if person:
            self._audit(tx,case,"CLAIM_RECOVERY_LIMIT",when,actor="SUHAIL-CLAIM-RECOVERY",old=old,key=reason,
                        result=f"The investigation of this case was lost {lost} times in a row; it is not queued again automatically. "
                               "A person takes it; no diagnosis, review or outcome was recorded.")
        return case

    def _recover_expired(self,tx,control,now):
        """Requeue every case whose claim was not renewed in time. Runs under the control lock, before any decision that
        counts live claims. A claim that is still within its lease is never touched."""
        recovered=[]
        for case in self._investigating(tx):
            if not claims.expired(case,now):continue
            result=(f"The claim held by {case.get('worker_id') or 'an earlier worker'} was not renewed"
                    +(f" before its lease ended at {case['lease_expires_at']}" if case.get("lease_expires_at") else " and has no lease on record")
                    +"; its investigation was abandoned and nothing from it is used.")
            self._end_claim(tx,case,control["as_of"],now,reason=claims.END_EXPIRED,event="CLAIM_EXPIRED",actor="SUHAIL-CLAIM-RECOVERY",
                            recovery=True,result=result)
            recovered.append(case["entity_id"])
        if control.get("worker_claim"):
            # The single flag of the earlier ledger format. It excludes nothing now; ownership is on the cases.
            control.update(worker_claim=None,claim_at=None,claim_shipment_id=None);self._put(tx,"OpsControl",control,update=True)
        return recovered

    def recover_claims(self):
        """Requeue the cases whose claim has expired: a worker that died, or a process that was stopped mid-run.
        Returns their ids. Safe to call at any time and from any worker."""
        def recover(tx):
            control=self._control(tx,lock=True)
            return self._recover_expired(tx,control,self._wall())
        return self._execute(recover,write=True)

    def renew_claim(self,claimed):
        """The owner's heartbeat: extend its lease. Only the two lease times change: not the case version, its evidence
        cutoff, its counters or any progress event. Raises ClaimLost when the case is no longer this claim's."""
        def renew(tx):
            self._control(tx,lock=True);now=self._wall()
            case=self._owned(tx,claimed,now)
            case.update(lease_heartbeat_at=now.isoformat(),lease_expires_at=claims.expires_at(now,claims.lease_seconds(self.lease_seconds)))
            self._put(tx,"OpsCase",case,update=True)
            return case["lease_expires_at"]
        return self._execute(renew,write=True)

    def _hold(self,claimed):
        handle=claims.Handle(claimed)
        with self._claims_lock:self._claims[claimed["entity_id"]]=handle
        if self.claim_heartbeats:
            handle.start(self.renew_claim,claims.heartbeat_seconds(claims.lease_seconds(self.lease_seconds),self.heartbeat_seconds))
        return handle

    def _drop(self,handle):
        handle.stop()
        with self._claims_lock:
            if self._claims.get(handle.claimed["entity_id"]) is handle:del self._claims[handle.claimed["entity_id"]]

    def _signal(self,case_ids):
        """Tell the workers of these cases, in this process, that their claim is gone. It only ends their waits early."""
        with self._claims_lock:
            for case_id in case_ids:
                if case_id in self._claims:self._claims[case_id].cancelled.set()

    def _fail_claim(self,claimed,error):
        """The owner's investigation raised: give up this claim only. Its peer, and automatic investigation as a whole,
        go on. If even this cannot be written, the lease runs out and the case is recovered then."""
        def fail(tx):
            control=self._control(tx,lock=True);now=self._wall()
            case=self._owned(tx,claimed,now)
            self._end_claim(tx,case,control["as_of"],now,reason=claims.END_FAILED,event="CLAIM_FAILED",actor="SUHAIL-INVESTIGATION-WORKER",
                            recovery=True,failed=True,
                            result=f"The investigation by {claimed['worker_id']} stopped on an internal error ({type(error).__name__}); "
                                   "nothing from it was recorded as a result.")
        try:self._execute(fail,write=True)
        except claims.ClaimLost:pass      # Already taken from this worker: nothing of its own is left to release.
        except Exception as second:
            log.warning("The failed claim on %s could not be released (%s); its lease will expire",claimed["entity_id"],type(second).__name__)

    def release_claims(self,worker_ids):
        """The worker pool is stopping: give up the claims this process holds for these workers, each by its own
        identity, so a peer's claim is never touched. Returns the cases released."""
        with self._claims_lock:handles=[h for h in self._claims.values() if h.claimed.get("worker_id") in worker_ids]
        released=[]
        for handle in handles:
            handle.cancelled.set()
            def give_up(tx,claimed=handle.claimed):
                control=self._control(tx,lock=True);now=self._wall()
                case=self._owned(tx,claimed,now)
                self._end_claim(tx,case,control["as_of"],now,reason=claims.END_STOPPED,event="CLAIM_RELEASED",actor="SUHAIL-INVESTIGATION-WORKER",
                                recovery=False,result="The investigation worker was stopped; the case is queued again.")
                return case["entity_id"]
            try:released.append(self._execute(give_up,write=True))
            except claims.ClaimLost:pass
        return released

    def _investigation_status(self,tx,case):
        """InvestigationStatusV3 (docs/v3/08-interface-reference.md) of a case: who investigates it or last did, where
        that run stands, and a bounded summary once it is final. Wall times are the claim's; as_of is the run's fixed
        evidence cutoff. No model text, no evidence contents."""
        queued=case["workflow_state"] in ("OPEN","REOPENED")
        run=None if queued or not case.get("last_run_id") else self._get(tx,"OpsRun",case["last_run_id"])
        status={"case_id":case["entity_id"],"shipment_id":case["shipment_id"],"worker_id":None,"claim_id":None,
                "claim_epoch":case.get("claim_epoch") or 0,"workflow_state":case["workflow_state"],"run_id":None,"run_status":"QUEUED",
                "active_stage":None,"started_at":None,"updated_at":None,"lease_expires_at":None,
                # Queued: the cutoff a new run would start from is not fixed yet; this is the case's pending one.
                "as_of":case["as_of"],"state_version":case["state_version"],"final_result":None}
        if not run:return status
        running=run.get("status")=="RUNNING"
        owner=running and case["workflow_state"]=="INVESTIGATING" and case.get("claim_id")==run.get("claim_id")
        # The latest accepted status or progress of this run. A lease renewal is neither and never moves it.
        moments=[t for t in (run.get("updated_wall_at"),run.get("finished_wall_at")) if t]
        status.update(worker_id=run.get("worker_id"),claim_id=run.get("claim_id"),run_id=run["entity_id"],run_status=run.get("status") or "QUEUED",
                      claim_epoch=run.get("claim_epoch") if run.get("claim_epoch") is not None else status["claim_epoch"],
                      active_stage=run.get("active_stage") if running else None,started_at=run.get("claim_wall_at"),
                      updated_at=max(moments,key=instant) if moments else None,
                      lease_expires_at=case.get("lease_expires_at") if owner else None,
                      as_of=run.get("claim_as_of") or case.get("investigated_as_of") or case["as_of"])
        if not running:
            review=json.loads(run.get("result_json") or "{}").get("review") or {}
            outcomes=[public_value(r["props"]) for r in tx.run("MATCH(n:OpsEntity:OpsOutcome {case_id:$case_id,dataset_id:$dataset}) "
                      "RETURN properties(n) AS props ORDER BY n.recorded_at DESC,n.entity_id DESC LIMIT 20",
                      case_id=case["entity_id"],dataset=self.dataset_id)]
            outcome=next((o for o in outcomes if o.get("run_id")==run["entity_id"] and not o.get("invalidated")),None)
            # A reviewed run is not a verified outcome: the last field is filled only by a recorded verification.
            status["final_result"]={"workflow_state":case["workflow_state"],"review_verdict":review.get("verdict"),
                                    "model_verdict":review.get("model_verdict"),
                                    "outcome_verification_status":(outcome or {}).get("verification_status")}
        return status

    def process_one(self, case_id=None, *, manual=False, worker_id=None):
        """Claim the oldest eligible case and investigate it; every entry point (an investigation loop, a manual step, a
        named case, a re-analysis) claims the same way and counts against the same capacity. worker_id names the owner
        (an investigation loop's name); without one the request is its own owner. Returns the writeback's result, or
        {"processed": False, "reason": ...} when nothing was claimed (worker_paused, capacity, none_eligible) or the
        claim was taken away during the run (claim_lost)."""
        owner=worker_id or claims.operator_worker()
        refused={}
        def claim(tx):
            control=self._control(tx,lock=True)
            if control["worker_state"]!="running" and not manual and case_id is None:
                refused["reason"]="worker_paused";return None
            now=self._wall()
            self._recover_expired(tx,control,now)
            # Capacity is counted here, under the lock every grant takes: two requests can never both see a free place.
            if len(self._live_claims(tx,now))>=self.capacity:
                refused["reason"]="capacity";return None
            rows=list(tx.run("MATCH(c:OpsCase {dataset_id:$dataset,split:'development'}) "
                "WHERE c.workflow_state IN ['OPEN','REOPENED'] AND c.opened_at <= $clock "
                # The quiet interval after a case's previous run: the automatic worker passes over it until then. It runs
                # on the simulation clock, so it applies only while that clock is running: with the world paused nothing
                # new can arrive, and a waiting case would otherwise never be investigated.
                "AND ($explicit OR c.quiet_until IS NULL OR c.quiet_until <= $clock) "
                "AND ($id IS NULL OR c.entity_id=$id) RETURN properties(c) AS props ORDER BY c.opened_at,c.entity_id LIMIT 1",
                dataset=self.dataset_id,clock=instant(control["as_of"]),id=case_id,
                explicit=bool(manual or case_id is not None or control.get("simulator_state")!="running")))
            if not rows:
                refused["reason"]="none_eligible";return None
            case=public_value(rows[0]["props"]); token=identity("claim",case["entity_id"],case["state_version"])
            run_id=identity("run",case["entity_id"],token);wall=now.isoformat()
            # claim_at and as_of are the simulation clock (what evidence the run may see); the lease is wall-clock time.
            # claim_as_of keeps the run's cutoff when later ingestion moves the case's own as_of.
            case.update(workflow_state="INVESTIGATING",state_version=case["state_version"]+1,claim_id=token,claim_at=control["as_of"],as_of=control['as_of'],
                        last_run_id=run_id,worker_id=owner,claim_epoch=(case.get("claim_epoch") or 0)+1,claim_wall_at=wall,
                        claim_as_of=control["as_of"],lease_heartbeat_at=wall,
                        lease_expires_at=claims.expires_at(now,claims.lease_seconds(self.lease_seconds)))
            self._put(tx,"OpsCase",case,update=True)
            # The run exists from the grant, with the claim it was made under: every later write of it is checked
            # against that, and a claim that is lost before its first event still has a run to close.
            self._put(tx,"OpsRun",{"entity_id":run_id,"shipment_id":case["shipment_id"],"case_id":case["entity_id"],
                "recorded_at":case["as_of"],"mode":"deterministic_evidence_rules","result_json":canonical({"pipeline_events":[]}),
                "iteration":0,"status":"RUNNING","worker_id":owner,"claim_id":token,"claim_epoch":case["claim_epoch"],
                "claim_wall_at":wall,"claim_as_of":case["as_of"],"updated_wall_at":wall})
            self._link(tx,"OPS_HAS_RUN",case["entity_id"],run_id,case["shipment_id"],case["as_of"])
            self._audit(tx,case,"CASE_CLAIMED",case["as_of"],result=f"Claimed by {owner} (claim {case['claim_epoch']}).")
            return case
        case=self._execute(claim,write=True)
        if not case:return {"processed":False,"outcome":None,"reason":refused.get("reason")}
        self._reader()
        reassess={}
        def finish(tx,analysis):
            control=self._control(tx,lock=True);now=self._wall()
            # The result, its recommendation and reviews, and any action it authorizes are written only by the worker
            # that still owns the case, within its lease. A worker that lost it writes nothing here.
            current=self._owned(tx,case,now)
            # The case record moved during the run. Only a material change supersedes the snapshot (a changed symptom
            # set, a record that replaces or contradicts what the conclusion rests on, or a change to the case that
            # evidence ingestion does not account for); routine new records do not, and the run is kept as the
            # investigation of its snapshot.
            moved=current["state_version"]!=case["state_version"] or current["as_of"]!=case["as_of"]
            material,arrived=self._material_since_claim(current,case,analysis,control["as_of"]) if moved else ([],0)
            stale=bool(material)
            quiet_until=self._quiet_until(control["as_of"])
            if stale and (current.get("snapshot_refreshes") or 0)<MAX_SNAPSHOT_REFRESHES:
                self._close_run(tx,current,claims.END_SNAPSHOT,now)
                claims.release(current,revoked=False)
                current.update(workflow_state="OPEN",state_version=current["state_version"]+1,
                               snapshot_refreshes=(current.get("snapshot_refreshes") or 0)+1,quiet_until=quiet_until)
                without_diagnosis(current,pending=True)
                self._put(tx,"OpsCase",current,update=True)
                self._audit(tx,current,"CLAIM_RELEASED",control["as_of"],result="Evidence snapshot changed during analysis; re-investigating with the new evidence. "
                            "Material change: "+materiality.describe(material)+".")
                return {"processed":False,"case_id":current["entity_id"],"reason":"snapshot_changed","workflow_state":"OPEN",
                        "state_version":current["state_version"],"outcome":None,"material":material}
            if moved and not stale:
                self._audit(tx,current,"SNAPSHOT_KEPT",control["as_of"],actor="SUHAIL-INVESTIGATION-WORKER",key="snapshot",
                            result=f"{arrived} new record(s) arrived during the investigation; none changes the symptoms or the evidence "
                                   f"the conclusion rests on. The investigation stands as of its snapshot {case['as_of']}.")
            if stale:
                # Evidence kept arriving: record this investigation, but never act on a superseded snapshot.
                # Only an actionable result is turned over to a person; a rejected (ESCALATED) or evidence-less
                # (NEEDS_EVIDENCE) result keeps its state, so a rejected proposal never becomes approvable.
                from operations.authority import rule_id as authority_rule
                reason="Evidence kept changing during repeated investigations; a person must review the latest evidence."
                state=analysis["result"]["workflow_state"]
                analysis={**analysis,"authority":{**(analysis.get("authority") or {}),"risk_class":"HUMAN_REVIEW","reason":reason,
                          "rule_id":authority_rule(reason)},
                          "result":{**analysis["result"],"workflow_state":state if state in ("ESCALATED","NEEDS_EVIDENCE") else "HUMAN_REVIEW"},
                          "degraded":[*(analysis.get("degraded") or []),{"role":"snapshot","error":"evidence changed during investigation",
                                                                       "kind":materiality.SNAPSHOT_SUPERSEDED_KIND}]}
            when=control["as_of"];run_id=identity("run",current["entity_id"],case["claim_id"])
            # A reassessment run (after an action that ran under a reviewer's doubt was verified, AUTH-27) never acts by
            # itself: it resolves the case or hands it to a person.
            reassessing=bool(reassess.get("outcome_id")) and current.get("reassess_outcome_id")==reassess.get("outcome_id")
            resolved_by_reassessment=None
            if reassessing:
                resolved_by_reassessment,analysis=self._reassessment_result(tx,current,analysis,reassess,stale,when)
            # The run is final from this commit: REVIEWED, closed by its owner. Events its worker emits after this (the
            # last stage's end) are appended to it and change nothing else (_record_stages).
            self._put(tx,"OpsRun",{"entity_id":run_id,"shipment_id":case["shipment_id"],"case_id":case["entity_id"],
                "recorded_at":case["as_of"],"mode":analysis["mode"],"result_json":canonical(analysis),"iteration":len(analysis["trace"]),
                "status":"REVIEWED","context_hash":analysis["context_hash"],"end_reason":claims.END_FINISHED,
                "finished_wall_at":now.isoformat(),"active_stage":None},update=True)
            self._link(tx,"OPS_HAS_RUN",case["entity_id"],run_id,case["shipment_id"],when)
            recommendation_id=None
            if analysis["proposal"]:
                proposal=analysis["proposal"];recommendation_id=identity("recommendation",run_id)
                self._put(tx,"OpsRecommendation",{"entity_id":recommendation_id,"shipment_id":case["shipment_id"],
                    "case_id":case["entity_id"],"run_id":run_id,"recorded_at":when,"action_code":proposal["action_code"],
                    "action":proposal["action"],"action_en":proposal.get("action_en",proposal["action"]),
                    "action_ar":proposal.get("action_ar"),"evidence_ids":proposal["evidence_ids"],"status":"PROPOSED","requires_approval":True,
                    "action_type":proposal.get("action_type"),"risk_class":(analysis.get("authority") or {}).get("risk_class"),
                    "authority_reason":(analysis.get("authority") or {}).get("reason"),"target_json":canonical(proposal.get("target") or {}),
                    "agent_mode":((proposal.get("planner") or {}).get("mode")) or analysis["mode"]})
                self._link(tx,"OPS_PROPOSES",run_id,recommendation_id,case["shipment_id"],when)
            from operations.worker import review_reason, REVIEW_SUMMARY_AR
            for item in analysis["trace"]:
                review_id=identity("review",run_id,item["iteration"])
                reason=review_reason(item["review"])
                self._put(tx,"OpsReview",{"entity_id":review_id,"shipment_id":case["shipment_id"],"case_id":case["entity_id"],
                    "run_id":run_id,"recorded_at":when,"verdict":item["review"]["verdict"],"feedback":item["review"]["feedback"],
                    "summary_en":item["review"]["feedback"],"reason_code":reason,
                    "summary_ar":REVIEW_SUMMARY_AR[reason],  # Chosen from the reason that produced this verdict.
                    "model_verdict":item["review"].get("model_verdict"),"degraded":bool(item["review"].get("degraded")),
                    "iteration":item["iteration"],"mode":item["mode"]})
                self._link(tx,"OPS_REVIEWED_BY",run_id,review_id,case["shipment_id"],when)
            old=current["workflow_state"]
            if recommendation_id and analysis["review"]["verdict"]=="accept":
                current.update(workflow_state="RECOMMENDATION_READY",state_version=current["state_version"]+1)
                self._put(tx,"OpsCase",current,update=True)
                self._audit(tx,current,"RECOMMENDATION_READY",when,old=old,result="Reviewed proposal only; no execution or verified outcome.")
                old=current["workflow_state"]
            authority=analysis.get("authority") or {}
            for item in analysis.get("degraded") or []:
                if item["role"]=="snapshot":
                    self._audit(tx,current,"SNAPSHOT_SUPERSEDED",when,actor="SUHAIL-INVESTIGATION-WORKER",key="snapshot",
                                result="New evidence arrived during each investigation attempt; routed to a person, no automatic action.")
                    continue
                failure=("returned output that failed validation" if item.get("kind")=="invalid_model_output" else
                         "reached the per-case model-call cap" if item.get("kind")=="model_call_cap" else
                         "used its turn budget without a valid conclusion" if item.get("kind")=="turn_budget_exhausted" else "unavailable")
                self._audit(tx,current,"MODEL_DEGRADED",when,actor="SUHAIL-"+item["role"].upper(),key=item["role"],
                            result=f"{item['role']} {failure} ({item.get('error') or 'no valid output'}); automatic execution blocked.")
            from operations.authority import execution_permission
            from operations.authority import reviewer_doubt_allows
            # AUTH-27: the reviewer's doubt (never a guard rejection, never a request for a person) on an evidence-gathering
            # action the authority policy decided AUTO. The doubt is recorded with the action and is not an acceptance.
            doubted=bool(recommendation_id and analysis["review"]["verdict"]=="reject" and authority.get("risk_class")=="AUTO"
                         and reviewer_doubt_allows(authority.get("action_type"),analysis["review"].get("model_verdict")))
            auto=(recommendation_id and (analysis["review"]["verdict"]=="accept" or doubted) and authority.get("risk_class")=="AUTO"
                  and not analysis.get("degraded") and not reassessing)
            permitted,refusal_rule,refusal_reason=execution_permission(authority.get("action_type"),"AUTO_POLICY",authority.get("risk_class"))
            if auto and not permitted:
                auto=False
                analysis={**analysis,"result":{**analysis["result"],"workflow_state":"HUMAN_REVIEW"}}
                self._audit(tx,current,"EXECUTION_REFUSED",when,actor="SUHAIL-AUTHORITY-POLICY",key=refusal_rule,
                            result=f"{authority.get('action_type')} · {refusal_rule} · {refusal_reason} Routed to a person.")
            if auto:
                execution_id=identity("execution","auto",recommendation_id)
                self._authorize_execution(tx,current,execution_id,recommendation_id,analysis["proposal"],authority["action_type"],
                                          "AUTO_POLICY",when,decision_id=None,decided_risk=authority.get("risk_class"),
                                          closure=authority.get("closure","AUTO"),recommendation_id=recommendation_id,run_id=run_id)
                if doubted:
                    self._audit(tx,current,"REVIEWER_DOUBT_RECORDED",when,actor="SUHAIL-REVIEWER",key=authority.get("rule_id"),
                                result=f"Reviewer verdict {analysis['review'].get('model_verdict')}, not an acceptance: "
                                       f"{analysis['review'].get('feedback') or 'no feedback text'} The evidence request runs under "
                                       "AUTH-27; the case is reassessed on the new evidence before any resolution.")
                self._audit(tx,current,"ACTION_AUTHORIZED",when,actor="SUHAIL-AUTHORITY-POLICY",old=current["workflow_state"],
                            result=f"AUTO · {authority['action_type']} · {authority['reason']}")
                current.update(workflow_state="ACTION_INITIATED",state_version=current["state_version"]+1)
                self._put(tx,"OpsCase",current,update=True)
                old="ACTION_INITIATED"
            if authority:
                # Every authority decision, including denials, with its rule and the inputs it used.
                self._audit(tx,current,"AUTHORITY_DECISION",when,actor="SUHAIL-AUTHORITY-POLICY",old=old,key=authority.get("rule_id"),
                            result=canonical({k:authority.get(k) for k in ("rule_id","risk_class","action_type","closure","reason","inputs")}))
            # Records up to now were checked against this run; later ones are checked by the monitor. The quiet interval
            # starts when the run finishes.
            claims.release(current,revoked=False)
            current.update(workflow_state=analysis["result"]["workflow_state"],state_version=current["state_version"]+1,
                last_run_id=run_id,recommendation_id=recommendation_id,claim_recoveries=0,
                investigated_as_of=case["as_of"],evidence_checked_as_of=when,quiet_until=quiet_until)
            if resolved_by_reassessment:
                current.update(is_terminal=True,closed_at=when,verified_outcome_id=resolved_by_reassessment)
            if investigation_status(analysis)[0]:
                # An agent investigation the independent reviewer accepted: its cause codes, the status they imply and its
                # own summary (model prose, English) describe the case in the queue. The same text as case detail's
                # diagnosis.summary; the leading hypothesis's assessment only when the investigation gave no summary.
                investigation=analysis["investigation"];primary=investigation.get("primary_cause")
                diagnosis=next((d for d in analysis["result"]["diagnoses"] if d["code"]==primary),None) or next(iter(analysis["result"]["diagnoses"]),None)
                current.update(cause_codes=analysis["result"]["operational_labels"],operational_status=analysis["result"]["operational_status"],
                               diagnosis_available=True,rule_signal_codes=[],
                               issue_summary=(investigation.get("summary") or "").strip() or (diagnosis or {}).get("summary_en") or MONITOR_SUMMARY)
            else:
                # No accepted diagnosis (rules only, a failed investigator, or a review that did not accept it): the monitor's
                # view stands. Rule triage codes are kept apart and labelled as rule signals, never as the cause.
                without_diagnosis(current,pending=False)
                if analysis["mode"]!="gpt_oss_agents":current["rule_signal_codes"]=list(analysis["result"].get("operational_labels") or [])
            if resolved_by_reassessment:current["operational_status"]="RESOLVED"
            self._put(tx,"OpsCase",current,update=True)
            if recommendation_id:
                # The approval context this recommendation rests on: the symptoms and evidence the investigation saw, its
                # run, final review and the resulting case version, plus the inputs of its authority decision. Approval
                # and dispatch recompute it on the current case and refuse when it changed (context_changes): other
                # symptoms, run, review or verdict, a case version not accounted for by ingestion, or MATERIAL new evidence.
                checks=analysis.get("checks") or {};assessment=analysis["result"]["assessment"];proposal=analysis["proposal"]
                agent=proposal.get("investigated_by")=="agent" and analysis["mode"]=="gpt_oss_agents" and bool(analysis.get("investigation"))
                context={**self._approval_context(tx,current,case["as_of"],symptoms=case.get("symptom_codes") or []),
                         "snapshot_at":case["as_of"],  # The investigation's snapshot: what "late" is measured against.
                         "investigated_by":"agent" if agent else "rules","risk_class":authority.get("risk_class"),
                         "authority_inputs":{"diagnosis_codes":assessment["supported_codes"] or [proposal["action_code"]],
                                             "review_verdict":analysis["review"].get("model_verdict"),
                                             # As the routing decided it: a rules-only flag is a rule conflict; the
                                             # investigator's own request for a physical check is separate.
                                             "evidence_conflict":bool((not analysis.get("investigation") and assessment.get("requires_human_review"))
                                                                      or checks.get("unsupported") or checks.get("sensitive")),
                                             "physical_check":bool((analysis.get("investigation") or {}).get("requires_physical_check")),
                                             "contractor_custody":bool(checks.get("contractor_custody")),
                                             "degraded":bool(analysis.get("degraded"))}}
                for kind,identifier in (("OpsRecommendation",recommendation_id),*([("OpsExecution",execution_id)] if auto else [])):
                    record=self._get(tx,kind,identifier);record["approval_context_json"]=canonical(context)
                    self._put(tx,kind,record,update=True)
            # What was decided here is what the run keeps, including a destination this writeback itself overrode (a
            # refused automatic execution).
            self._put(tx,"OpsRun",{"entity_id":run_id,"shipment_id":case["shipment_id"],"case_id":case["entity_id"],
                                   "result_json":canonical(analysis)},update=True)
            control.update(processed_count=control["processed_count"]+1,
                           last_case_id=current["entity_id"],last_shipment_id=current["shipment_id"],
                           last_workflow_state=current["workflow_state"],last_processed_at=when)
            self._put(tx,"OpsControl",control,update=True)
            return {"processed":True,"case_id":current["entity_id"],"workflow_state":current["workflow_state"],
                    "state_version":current["state_version"],"run_id":run_id,"mode":analysis["mode"],"afl":analysis["afl"],"outcome":None}
        from operations.graph import investigate
        # The run's progress events, written in batches (StageBuffer): everything waiting is written before the result
        # is committed, after the run, and on every failure path.
        stages=StageBuffer(lambda batch,events:self._record_stages(case,batch,events),stage_flush_seconds(self.stage_flush_seconds),
                           timer=self.stage_timer)
        committed={}
        def commit(analysis):
            stages.flush()
            if case.get("reassess_outcome_id"):
                # AUTH-27 reassessment: whether the exception is still cleared, re-assessed on this run's own snapshot.
                from dataset_v2.derive import assess_shipment
                from operations.reasoning import evidence_world
                context=self._reader().evidence(case["shipment_id"],case["as_of"])
                assessment=assess_shipment(evidence_world(context,self.config),case["shipment_id"],context["as_of"],
                                           detection_allowance_seconds=DETECTION_ALLOWANCE_SECONDS)
                reassess.update(outcome_id=case["reassess_outcome_id"],fresh=sorted(monitor_finding(assessment)["symptoms"]),
                                delivered=delivery_corroborated(assessment))
            committed["result"]=self._execute(lambda tx:finish(tx,analysis),write=True)
            return committed["result"]
        handle=self._hold(case)
        try:
            try:
                # Every model call of this investigation is labelled with its claim for the provider log, and stops
                # waiting for a provider slot as soon as the claim is known to be gone (operations.provider_gate).
                with provider_gate.scope(cancel=handle.cancelled,case_id=case["entity_id"],run_id=case["last_run_id"],worker_id=owner):
                    analysis,result=investigate(case["shipment_id"],case["as_of"],self.config,self.reader.evidence,
                        lambda sid,codes:self.reader.precedents(sid,codes,as_of=case['as_of']),
                        commit=commit,on_event=stages.add,
                        agents=self.agents,live_session=True,symptoms=case.get("symptom_codes") or [],
                        heartbeats=getattr(self.reader,"heartbeats",None),
                        # The read model's fixed cross-shipment queries (None for a reader without them: tools then say UNKNOWN).
                        port=getattr(self.reader,"fetch",None),disabled_tools=self.disabled_tools,call_cap=self.model_call_cap)
            except Exception as error:
                stages.close(quiet=True)   # Whatever was emitted before the failure is on record; its error never hides this one.
                if "result" in committed:
                    # The result was committed and stands; only the worker's last events or its trace failed after it.
                    log.warning("Case %s: the run was committed, then its worker failed (%s); the committed result stands",
                                case["entity_id"],type(error).__name__)
                    return committed["result"]
                if isinstance(error,claims.ClaimLost):
                    # The case was taken from this worker during the run (a pause, an expired lease). Nothing of the
                    # run was written past that point, and there is nothing of its own left to release.
                    log.warning("Case %s: %s lost its claim (%s); its result was discarded",case["entity_id"],owner,error.reason)
                    return {"processed":False,"case_id":case["entity_id"],"reason":"claim_lost","outcome":None}
                # This claim only: the case is queued again (or handed to a person after repeated losses). The other
                # worker, and automatic investigation as a whole, are not paused.
                self._fail_claim(case,error)
                raise
            # After the commit the claim is released, so these last writes can fail only for their own reasons; they
            # never undo or fail a committed investigation.
            try:
                stages.close()   # The last stage's own events, appended to the run its worker just closed.
                analysis["writeback"]=result
                self._save_run_trace(case,analysis)
            except Exception as error:
                log.warning("Case %s: the committed run's last events or trace were not saved (%s)",case["entity_id"],type(error).__name__)
            return result
        finally:
            self._drop(handle)

    def _record_stage(self,claimed,event,events):
        """One progress event, written at once."""
        self._record_stages(claimed,[event],events)

    def _record_stages(self,claimed,batch,events):
        """Write a batch of consecutive progress events of the claimed run, in order, in one transaction: the run record
        (its pipeline_events are `events`, every event up to the last of the batch) and one PIPELINE_STAGE audit entry
        per event, exactly as each would have been written alone. Subscribers are then sent the state once.

        Accepted from the worker that owns the case, within its lease (operations.claims). One more case is accepted: the
        events a worker emits after committing its own result (the last stage's end), while that run is still the case's
        current one. Those are appended to the closed run and change nothing else: not its status (a REVIEWED run never
        goes back to RUNNING), its result, its authority decision or the case. Anything else raises ClaimLost, before a
        single event is written or sent to a subscriber."""
        last=batch[-1]
        def record(tx):
            self._control(tx,lock=True);now=self._wall()
            run_id=claimed["last_run_id"]
            case=self._get(tx,"OpsCase",claimed["entity_id"])
            current=self._get(tx,"OpsRun",run_id)
            reason=claims.lost(case,claimed,now)
            closed=bool(reason) and bool(case) and case.get("last_run_id")==run_id and claims.closed_by_owner(current,claimed)
            if reason and not closed:raise claims.ClaimLost(reason)
            trace=json.loads(current["result_json"]) if current else {}
            trace["pipeline_events"]=events
            status=current["status"] if closed else ("FAILED" if last["status"]=="FAILED" else "RUNNING")
            run={"entity_id":run_id,"shipment_id":case["shipment_id"],"case_id":case["entity_id"],"result_json":canonical(trace),
                 "updated_wall_at":now.isoformat()}
            if not closed:
                run.update(recorded_at=claimed["as_of"],mode="deterministic_evidence_rules",iteration=last["iteration"],status=status,
                           active_stage=last["stage"] if status=="RUNNING" else None)
            self._put(tx,"OpsRun",run,update=True)
            self._link(tx,"OPS_HAS_RUN",case["entity_id"],run_id,case["shipment_id"],claimed["as_of"])
            for event in batch:
                audit_id=run_id.replace("-RUN-","-STAGE-")+f'-{event["sequence"]:04d}'
                self._put(tx,"OpsAudit",{"entity_id":audit_id,"shipment_id":case["shipment_id"],"case_id":case["entity_id"],
                    "run_id":run_id,"event_type":"PIPELINE_STAGE","stage":event["stage"],"stage_status":event["status"],
                    "sequence":event["sequence"],"wall_recorded_at":event["recorded_at"],
                    "occurred_at":claimed["as_of"],"recorded_at":claimed["as_of"],"actor_id":"DEMO-RULE-WORKER",
                    "to_state":case["workflow_state"],"result":event["stage"]+": "+event["status"]})
                self._link(tx,"OPS_HAS_AUDIT",case["entity_id"],audit_id,case["shipment_id"],claimed["as_of"])
            return {'run_id':run_id,'events':events,'workflow_state':case['workflow_state'],
                    'state_version':case['state_version'],'status':status}
        state=self._execute(record,write=True)
        self._publish_pipeline(claimed['entity_id'],state)
        if self.narrator is not None:self.narrator.request(claimed['entity_id'])

    def _save_run_trace(self,case,analysis):
        """Complete the stored trace of a run its own worker committed (timings, the investigation log, the writeback's
        receipt). The run's status and what the writeback decided are already final and are kept; a run that was taken
        from this worker, or is no longer the case's current one, is left alone (ClaimLost)."""
        def save(tx):
            self._control(tx,lock=True)
            current=self._get(tx,"OpsCase",case["entity_id"])
            run=self._get(tx,"OpsRun",case["last_run_id"])
            if not current or current.get("last_run_id")!=case["last_run_id"] or not claims.closed_by_owner(run,case):
                raise claims.ClaimLost("run_closed")
            # The writeback may have overridden the authority decision and destination (a superseded snapshot,
            # a refused automatic execution); the stored run keeps what was actually decided.
            decided=json.loads(run.get("result_json") or "{}") if analysis['writeback'].get('processed') else {}
            kept={k:decided[k] for k in ("authority","result","degraded") if k in decided}
            self._put(tx,"OpsRun",{"entity_id":run["entity_id"],"shipment_id":run["shipment_id"],"case_id":run["case_id"],
                                   "result_json":canonical({**analysis,**kept})},update=True)
        self._execute(save,write=True)
        with self._subscribers_lock:
            subscribed=bool(self._subscribers.get(case['entity_id']))
        if subscribed:self._publish_pipeline(case['entity_id'],self.pipeline_state(case['entity_id']))

    def subscribe_pipeline(self,case_id):
        listener=queue.Queue(maxsize=64)
        with self._subscribers_lock:self._subscribers.setdefault(case_id,[]).append(listener)
        return listener

    def unsubscribe_pipeline(self,case_id,listener):
        with self._subscribers_lock:
            listeners=self._subscribers.get(case_id,[])
            if listener in listeners:listeners.remove(listener)
            if not listeners:self._subscribers.pop(case_id,None)

    def _publish_pipeline(self,case_id,state):
        with self._subscribers_lock:
            for listener in self._subscribers.get(case_id,[]):
                try:listener.put_nowait(state)
                except queue.Full:
                    try:listener.get_nowait()
                    except queue.Empty:pass
                    try:listener.put_nowait(state)
                    except queue.Full:pass

    NARRATION_ROWS=("MATCH(n:OpsEntity:{kind} {{case_id:$case_id,dataset_id:$dataset}}) RETURN properties(n) AS props "
                    "ORDER BY n.recorded_at DESC,n.entity_id DESC LIMIT 500")

    def _narration_rows(self,tx,case_id,run_id=None):
        rows=[public_value(r["props"]) for r in tx.run(self.NARRATION_ROWS.format(kind="OpsNarration"),case_id=case_id,dataset=self.dataset_id)]
        return sorted((r for r in rows if run_id is None or r.get("run_id")==run_id),key=lambda r:(r.get("run_id") or "",r.get("sequence") or 0))

    def narration_sources(self,case_id):
        """Everything the narrator may read for a case's current run: the run's recorded pipeline events, conclusion and
        final review, the case's audit entries since that run was claimed, and what is narrated already."""
        def read(tx):
            case=self._case(tx,case_id);run_id=case.get("last_run_id")
            run=self._get(tx,"OpsRun",run_id or "")
            if not run:return None
            result=json.loads(run.get("result_json") or "{}")
            audits=[public_value(r["props"]) for r in tx.run(self.NARRATION_ROWS.format(kind="OpsAudit"),case_id=case_id,dataset=self.dataset_id)]
            audits=[a for a in audits if a.get("event_type")!="PIPELINE_STAGE"]
            claims=[a.get("wall_recorded_at") or "" for a in audits if a.get("event_type")=="CASE_CLAIMED"]
            since=max(claims) if claims else ""
            audits=sorted((a for a in audits if (a.get("wall_recorded_at") or "")>=since),key=lambda a:(a.get("wall_recorded_at") or "",a["entity_id"]))
            stored=self._narration_rows(tx,case_id,run_id)
            return {"case":{"entity_id":case["entity_id"],"shipment_id":case["shipment_id"],"workflow_state":case["workflow_state"]},
                    "run_id":run_id,"pipeline_events":result.get("pipeline_events") or [],"investigation":result.get("investigation"),
                    "review":result.get("review"),"audits":audits,"existing_keys":[r.get("key") for r in stored],
                    "model_calls":sum(1 for r in stored if r.get("model_call"))}
        return self._execute(read)

    def narration_append(self,case_id,run_id,events):
        """Append narration events to a run (the narrator's only write). Returns the stored events."""
        def write(tx):
            case=self._case(tx,case_id);control=self._control(tx)
            stored=self._narration_rows(tx,case_id,run_id)
            known={r.get("key") for r in stored};sequence=max((r.get("sequence") or 0 for r in stored),default=0);out=[]
            for event in events:
                if event["key"] in known:continue
                sequence+=1;known.add(event["key"])
                record={"entity_id":identity("narration",run_id,event["key"]),"shipment_id":case["shipment_id"],"case_id":case["entity_id"],
                        "run_id":run_id,"sequence":sequence,"key":event["key"],"stage":event["stage"],"phase":event["phase"],"kind":event["kind"],
                        "iteration":event.get("iteration") or 0,"title_en":event.get("title_en"),"title_ar":event.get("title_ar"),
                        "text_en":str(event.get("text_en") or "")[:2000],"text_ar":(str(event["text_ar"])[:2500] if event.get("text_ar") else None),
                        "evidence_ids":list(event.get("evidence_ids") or []),"graph_node_ids":list(event.get("graph_node_ids") or []),
                        "source_json":canonical(event.get("source") or {}),"source_wall_at":event.get("occurred_at"),
                        "scenario_time":event.get("scenario_time"),"wall_recorded_at":datetime.now(timezone.utc).isoformat(),
                        "model":event.get("model"),"grounded":event.get("grounded"),"fallback":bool(event.get("fallback")),
                        "model_call":bool(event.get("model_call")),"outcome_state":event.get("outcome_state"),
                        "recorded_at":control["as_of"],"occurred_at":control["as_of"]}
                self._put(tx,"OpsNarration",record)
                out.append(narration_view(record))
            return out
        stored=self._execute(write,write=True)
        for event in stored:self._publish_pipeline(case_id,{"narration_event":event})
        return stored

    def narration(self,case_id,run_id=None):
        """A run's narration as served: {run_id, status, model_calls, events} (the case's current run by default)."""
        def read(tx):
            case=self._case(tx,case_id);target=run_id or case.get("last_run_id")
            rows=self._narration_rows(tx,case_id,target) if target else []
            run=self._get(tx,"OpsRun",target or "") or {}
            status=("idle" if not rows else "narrating" if run.get("status")=="RUNNING" and target==case.get("last_run_id") else "complete")
            return {"run_id":target,"status":status,"model_calls":sum(1 for r in rows if r.get("model_call")),
                    "events":[narration_view(r) for r in rows]}
        return self._execute(read)

    def pipeline_state(self,case_id):
        def read(tx):
            case=self._case(tx,case_id)
            if case["workflow_state"] in ("OPEN","REOPENED"):
                # Queued for a new investigation: the earlier run's stages are not the current pipeline.
                return {"workflow_state":case["workflow_state"],"state_version":case["state_version"],"run_id":None,
                        "previous_run_id":case.get("last_run_id"),"status":"QUEUED","events":[]}
            run=self._get(tx,"OpsRun",case.get("last_run_id",""))
            return {"workflow_state":case["workflow_state"],"state_version":case["state_version"],
                    "run_id":case.get("last_run_id"),"status":run["status"] if run else "QUEUED",
                    "events":served_run_result(json.loads(run["result_json"])).get("pipeline_events",[]) if run else []}
        return self._execute(read)

    def case_graph(self,case_id,evidence_ids):
        def read(tx):
            case=self._case(tx,case_id)
            kinds=['OpsCase','OpsRun','OpsRecommendation','OpsReview','OpsDecision','OpsExecution','OpsOutcome']
            rows=list(tx.run("MATCH (n:OpsEntity {dataset_id:$dataset,shipment_id:$sid}) "
                "WHERE any(k IN labels(n) WHERE k IN $kinds) RETURN properties(n) AS props,labels(n) AS labels LIMIT 100",
                dataset=self.dataset_id,sid=case['shipment_id'],kinds=kinds))
            nodes=[]
            for row in rows:
                props=public_value(row['props'])
                props={k:v for k,v in props.items() if k in {'entity_id','shipment_id','case_id','recorded_at','occurred_at','status',
                    'workflow_state','verification_status','success','invalidated','action_code','action','action_en','action_ar','decision','verdict','mode','iteration'}}
                nodes.append({'id':row['props']['entity_id'],'kind':next(k for k in row['labels'] if k in kinds),'properties':props})
            ids=[n['id'] for n in nodes]
            edges=[{'id':r['props']['edge_id'],'kind':r['kind'],'start':r['start'],'end':r['end'],'properties':{}}
                for r in tx.run("MATCH (a:OpsEntity {dataset_id:$dataset})-[r]->(b) "
                    "WHERE a.entity_id IN $ids AND b.entity_id IN $visible RETURN properties(r) AS props,type(r) AS kind,a.entity_id AS start,b.entity_id AS end LIMIT 500",
                    dataset=self.dataset_id,ids=ids,visible=ids+evidence_ids)]
            return {'nodes':nodes,'edges':edges}
        return self._execute(read)

    def _command(self, tx, case, command_type, key, payload):
        if not isinstance(key,str) or not 1<=len(key)<=128:raise OperationsConflict("Idempotency key required")
        identifier=identity("command",case["entity_id"],key)
        existing=self._get(tx,"OpsCommand",identifier)
        request_hash=digest([command_type,payload])
        if existing:
            if existing["request_hash"]!=request_hash:raise OperationsConflict("Idempotency key reused for a different request")
            return identifier,request_hash,{**json.loads(existing["result_json"]),"idempotent":True}
        return identifier,request_hash,None

    def _save_command(self,tx,case,identifier,request_hash,kind,key,result,when):
        self._put(tx,"OpsCommand",{"entity_id":identifier,"shipment_id":case["shipment_id"],"case_id":case["entity_id"],
            "recorded_at":when,"command_type":kind,"idempotency_key":key,"request_hash":request_hash,"result_json":canonical(result)})

    def request_reanalysis(self,case_id,actor_id,expected_version,idempotency_key):
        """Explicit, versioned re-investigation of an open decision; never reopen it."""
        require_actor(actor_id)
        def request(tx):
            control=self._control(tx,lock=True);case=self._case(tx,case_id)
            payload={"actor_id":actor_id,"expected_version":expected_version}
            command,request_hash,replay=self._command(tx,case,"reanalyze",idempotency_key,payload)
            if replay:return replay
            require_version(case,expected_version)
            if case['workflow_state'] not in {'HUMAN_REVIEW','AWAITING_APPROVAL','RECOMMENDATION_READY','NEEDS_EVIDENCE'}:
                raise OperationsConflict('Re-analysis requires an eligible pending decision or evidence request')
            old=case['workflow_state'];when=control['as_of']
            # A person asked for it: the quiet interval after the previous run does not delay it.
            case.update(workflow_state='OPEN',state_version=case['state_version']+1,recommendation_id=None,quiet_until=None)
            self._put(tx,'OpsCase',without_diagnosis(case,pending=True),update=True)
            self._audit(tx,case,'REANALYSIS_REQUESTED',when,actor=actor_id,old=old,
                        result='Explicit re-analysis requested; previous investigation remains recorded.')
            result={'case_id':case_id,'workflow_state':'OPEN','state_version':case['state_version'],'idempotent':False}
            self._save_command(tx,case,command,request_hash,'reanalyze',idempotency_key,result,when)
            return result
        return self._execute(request,write=True)

    HUMAN_OUTCOMES = ("parcel_located", "delivered_confirmed_by_person", "returned_to_depot", "parcel_not_found", "data_corrected")

    def record_human_outcome(self,case_id,actor_id,outcome_type,finding,evidence_ids,expected_version,idempotency_key,*,source="operator"):
        """Record a person's finding after a physical or administrative check. A person cannot declare success.

        The finding must cite visible evidence that is relevant to the kind of finding and was recorded AFTER the case's
        last executed action (or after the case opened, when no action ran): evidence that was already there when an
        action failed verification proves nothing new. The same clearance check the outcome verifier runs is then
        applied to the evidence visible now. Only when nothing remains is the case RESOLVED (HUMAN_VERIFIED, kept
        distinct from evidence-verified outcomes). Otherwise the finding is recorded as HUMAN_FINDING with what
        remains, and the case stays unresolved (ESCALATED). `source` is "operator", or "harness" when the evaluation
        harness records a finding under its own actor id: a harness finding is never a trusted precedent."""
        source=require_actor(actor_id,source=source)
        if outcome_type not in self.HUMAN_OUTCOMES:raise OperationsConflict("Unknown human outcome type")
        if not isinstance(finding,str) or not 10<=len(finding.strip())<=1000:raise OperationsConflict("A written finding of 10 to 1000 characters is required")
        from dataset_v2.derive import assess_shipment
        from operations.reasoning import evidence_world
        detail=self.case_detail(case_id);clock=self.status()["as_of"]
        context=self._reader().evidence(detail["shipment_id"],clock)
        visible={n["id"] for n in context["nodes"]}
        if not evidence_ids or not set(evidence_ids)<=visible:raise OperationsConflict("Attach visible evidence ids for this shipment")
        world=evidence_world(context,self.config)
        assessment=assess_shipment(world,detail["shipment_id"],context["as_of"],detection_allowance_seconds=DETECTION_ALLOWANCE_SECONDS)
        fresh=set(monitor_finding(assessment)["symptoms"])
        def record(tx):
            control=self._control(tx,lock=True);case=self._case(tx,case_id)
            payload={"actor_id":actor_id,"source":source,"outcome_type":outcome_type,"finding":finding,"evidence_ids":sorted(evidence_ids),"expected_version":expected_version}
            command,request_hash,replay=self._command(tx,case,"human_outcome",idempotency_key,payload)
            if replay:return replay
            require_version(case,expected_version)
            if case["workflow_state"] not in ("HUMAN_REVIEW","ESCALATED","NEEDS_EVIDENCE","AWAITING_APPROVAL"):
                raise OperationsConflict("Only a case waiting for a person can be closed by a person's verified finding")
            when=control["as_of"];old=case["workflow_state"];outcome_id=identity("outcome","human",command)
            # Evidence counts only when recorded after the last action this case executed (else after it opened).
            executed=[public_value(r["props"]).get("executed_at") for r in tx.run("MATCH(n:OpsEntity:OpsExecution {case_id:$case_id,dataset_id:$dataset}) "
                      "RETURN properties(n) AS props ORDER BY n.recorded_at DESC,n.entity_id DESC LIMIT 20",case_id=case_id,dataset=self.dataset_id)]
            since=max((instant(str(t)) for t in executed if t),default=instant(str(case["opened_at"])))
            relevant,settled,answered=finding_evidence(world,case["shipment_id"],outcome_type,evidence_ids,since,instant(context["as_of"]))
            negative=outcome_type=="parcel_not_found"
            if not relevant and not negative:
                raise OperationsConflict("This finding needs evidence of what was found, recorded after the case's last executed action "
                                         f"(or after it opened): none of the attached records is relevant to {outcome_type} and recorded after {since.isoformat()}")
            remaining=remaining_symptoms(case.get("symptom_codes") or [],fresh,is_delivered=delivery_corroborated(assessment),
                                         settled=settled,answered=answered,other_cases=self._other_open_cases(tx,case))
            resolved=not negative and not remaining
            status="HUMAN_VERIFIED" if resolved else "HUMAN_FINDING"
            self._put(tx,"OpsOutcome",{"entity_id":outcome_id,"shipment_id":case["shipment_id"],"case_id":case_id,"execution_id":None,
                "run_id":case.get("last_run_id"),
                "action_code":None,"action_type":"HUMAN_INVESTIGATION","success":resolved,"outcome_type":outcome_type,
                "evidence_ids":sorted(evidence_ids),"verification_status":status,"verified_at":when,"verifier_id":actor_id,"source":source,
                "invalidated":False,"observed_at":when,"reason":finding.strip(),"rule_id":"VERIFY-human-finding","exception_cleared":resolved,
                "remaining_symptoms":remaining,"relevant_evidence_ids":relevant,
                # Only an operator's finding that passed the evidence check is a precedent; a harness or simulated one never is.
                "trusted_precedent":resolved and source=="operator",
                "recorded_at":when,"occurred_at":when})
            self._link(tx,"OPS_HAS_OUTCOME",case_id,outcome_id,case["shipment_id"],when)
            if resolved:
                case.update(workflow_state="RESOLVED",operational_status="RESOLVED",is_terminal=True,closed_at=when,
                            verified_outcome_id=outcome_id,state_version=case["state_version"]+1)
            else:
                case.update(workflow_state="ESCALATED",state_version=case["state_version"]+1)
            self._put(tx,"OpsCase",case,update=True)
            self._audit(tx,case,"HUMAN_OUTCOME_RECORDED",when,actor=actor_id,old=old,
                        result=f"{outcome_type} · "+(f"human-verified ({source})" if resolved else f"finding recorded, not resolved ({source})")
                               +f" with {len(relevant)} relevant of {len(evidence_ids)} evidence records"
                               +(f" · remains: {', '.join(remaining)}" if remaining else "")+f" · {finding.strip()[:300]}")
            result={"case_id":case_id,"workflow_state":case["workflow_state"],"state_version":case["state_version"],
                    "outcome_id":outcome_id,"verification_status":status,"resolved":resolved,"remaining_symptoms":remaining,"idempotent":False}
            self._save_command(tx,case,command,request_hash,"human_outcome",idempotency_key,result,when)
            return result
        return self._execute(record,write=True)

    # ------------------------------------------------------------------ approval context (M2)
    def _evidence_marker(self,shipment_id,at):
        """How much shipment evidence is visible at `at`, and the latest time any of it was recorded (ingested)."""
        nodes=self._reader().evidence(shipment_id,at)["nodes"]
        times=[instant(value.isoformat() if hasattr(value,"isoformat") else str(value))
               for value in (n["properties"].get("recorded_at") for n in nodes) if value]
        return {"evidence_count":len(nodes),"latest_evidence_recorded_at":max(times).isoformat() if times else None}

    def _current_review(self,tx,case_id,run_id):
        rows=tx.run("MATCH(n:OpsEntity:OpsReview {case_id:$case_id,dataset_id:$dataset}) RETURN properties(n) AS props "
                    "ORDER BY n.iteration DESC,n.recorded_at DESC,n.entity_id DESC LIMIT 20",case_id=case_id,dataset=self.dataset_id)
        return next((public_value(r["props"]) for r in rows if r["props"].get("run_id")==run_id),None) if run_id else None

    def _approval_context(self,tx,case,evidence_at,*,symptoms=None):
        """The facts an approval rests on: symptoms, the evidence visible at `evidence_at`, the investigation run, its
        final review and the case version."""
        run_id=case.get("last_run_id")
        review=self._current_review(tx,case["entity_id"],run_id) or {}
        return {"symptoms":sorted(case.get("symptom_codes") or [] if symptoms is None else symptoms),
                **self._evidence_marker(case["shipment_id"],evidence_at),"run_id":run_id,"review_id":review.get("entity_id"),
                "review_verdict":review.get("verdict"),"model_verdict":review.get("model_verdict"),"state_version":case["state_version"],
                # The records ingested for the case so far: each advances the case version by one, so a later version
                # is accounted for by ingestion when both moved by the same number.
                "evidence_events":case.get("evidence_events") or 0,"evidence_at":evidence_at}

    def _context_material(self,tx,case,recorded,current,when):
        """(material changes, new records) among the shipment evidence that became visible since the approval context
        was recorded, decided by operations.materiality exactly as the monitor decides them after a finished run: against
        the conclusion of the run the context names (what it cites) and that run's snapshot. ([], n): n routine records,
        none material. (None, 0): it cannot be assessed (the context was recorded without its evidence time, or its
        run is gone), and the caller then treats any difference as a change."""
        if not recorded or not recorded.get("evidence_at") or not recorded.get("run_id"):return None,0
        if all(recorded.get(key)==current.get(key) for key in EVIDENCE_KEYS):return [],0
        run=self._get(tx,"OpsRun",recorded["run_id"])
        if not run:return None,0
        reader=self._reader();before=reader.evidence(case["shipment_id"],recorded["evidence_at"]);after=reader.evidence(case["shipment_id"],when)
        new=materiality.new_records(before,after)
        if not new:
            # The count or the latest time differs and no record was added: something other than new evidence changed.
            return [{"reason":"evidence_changed"}],0
        material=materiality.material_evidence(before,after,config=self.config,allowance=DETECTION_ALLOWANCE_SECONDS,
                                               snapshot_at=recorded.get("snapshot_at") or case.get("investigated_as_of") or recorded["evidence_at"],
                                               cited=materiality.cited_evidence_ids(json.loads(run.get("result_json") or "{}")))
        return material,len(new)

    @staticmethod
    def _changed_text(changed,material):
        return ", ".join(changed)+(f"; material new evidence: {materiality.describe(material)}" if material else "")

    def _approval_check(self,tx,case,recommendation,when):
        """Recompute, on the current case, whether a person's approval may authorize this recommendation."""
        from operations import authority as policy
        action=recommendation.get("action_type")  # None (a legacy record): unknown action, refused.
        recorded=json.loads(recommendation.get("approval_context_json") or "null")
        current=self._approval_context(tx,case,when)
        material,arrived=self._context_material(tx,case,recorded,current,when)
        changed=context_changes(recorded,current,material=material)
        if recommendation.get("run_id")!=case.get("last_run_id") and "run_id" not in changed:changed.append("run_id")
        result={"allowed":False,"stale":False,"changed":changed,"risk":None,"closure":None,"human_investigation":None,
                "current":current,"recorded":recorded,"material":material or [],"routine_new_records":0 if material else arrived}
        # Refusals that hold whatever the current context are checked first: they leave the case where it is (a refused
        # click never pulls a case a person holds back into automatic re-investigation).
        if self._recommendation_executed(tx,case,recommendation):
            return {**result,"rule":"AUTH-24-recommendation-already-executed","reason":"This recommendation was already "
                    "authorized for execution; approving it again would repeat the action. Re-analyse the case for a new "
                    "recommendation, or record a person's finding."}
        if recorded and recorded.get("investigated_by")!="agent":
            return {**result,"rule":"AUTH-22-rules-only-proposal","reason":"Rules-only proposal: no agent investigation or "
                    "independent model review produced it, so approval cannot make it executable."}
        allowed,rule,reason=policy.execution_permission(action,"OPERATOR_APPROVAL",recommendation.get("risk_class"))
        if not allowed:return {**result,"rule":rule,"reason":reason}
        if changed:
            return {**result,"stale":True,"rule":"AUTH-20-approval-context-stale",
                    "reason":f"The approval context changed since the recommendation ({self._changed_text(changed,material)}); renewed "
                             "investigation and review are required before any approval or execution."}
        risk,risk_reason,closure=policy.recheck_authority(action,recorded.get("authority_inputs"),current["symptoms"])
        human=(case["workflow_state"]=="HUMAN_REVIEW" or recommendation.get("risk_class")=="HUMAN_REVIEW" or risk=="HUMAN_REVIEW"
               or bool(set(current["symptoms"])&policy.HUMAN_FLOOR_SYMPTOMS))
        decided="HUMAN_REVIEW" if human and risk!="PROHIBITED" else risk
        allowed,rule,reason=policy.execution_permission(action,"OPERATOR_APPROVAL",decided)
        return {**result,"allowed":allowed,"rule":rule,"reason":reason if not allowed else risk_reason,"risk":decided,
                "closure":"HUMAN" if human else closure,"human_investigation":human}

    def _dispatch_check(self,tx,case,execution,when):
        """The same checks immediately before an authorized action is dispatched."""
        from operations import authority as policy
        recorded=json.loads(execution.get("approval_context_json") or "null")
        result={"allowed":False,"stale":False,"changed":[],"requeue":False}
        if case["workflow_state"] not in ("ACTION_INITIATED","AWAITING_OUTCOME") or case.get("is_terminal"):
            return {**result,"stale":True,"changed":["workflow_state"],"rule":"AUTH-20-approval-context-stale",
                    "reason":f"The case is no longer awaiting this action ({case['workflow_state']}); nothing was dispatched."}
        current=self._approval_context(tx,case,when)
        material,arrived=self._context_material(tx,case,recorded,current,when)
        changed=context_changes(recorded,current,material=material)
        result={**result,"material":material or [],"routine_new_records":0 if material else arrived}
        if changed:
            return {**result,"stale":True,"requeue":True,"changed":changed,"rule":"AUTH-20-approval-context-stale",
                    "reason":f"The approval context changed after authorization ({self._changed_text(changed,material)}); renewed "
                             "investigation and review are required before execution."}
        if recorded.get("investigated_by")!="agent":
            return {**result,"rule":"AUTH-22-rules-only-proposal","reason":"Rules-only proposal: nothing derived from rule checks "
                    "alone is executed."}
        action=execution.get("action_type")
        risk,_,_=policy.recheck_authority(action,recorded.get("authority_inputs"),current["symptoms"])
        if execution.get("authority")=="AUTO_POLICY":
            allowed,rule,reason=policy.execution_permission(action,"AUTO_POLICY",risk)
        else:
            human=(bool(recorded.get("human_investigation")) or risk=="HUMAN_REVIEW"
                   or bool(set(current["symptoms"])&policy.HUMAN_FLOOR_SYMPTOMS))
            allowed,rule,reason=policy.execution_permission(action,"OPERATOR_APPROVAL","HUMAN_REVIEW" if human and risk!="PROHIBITED" else risk)
        return {**result,"allowed":allowed,"rule":rule,"reason":reason,"risk":risk,"current":current}

    def _requeue_stale(self,tx,case,when,actor,event_type,check,key):
        """The approval context changed: invalidate it and send the case back for re-investigation and review."""
        old=case["workflow_state"];refreshes=case.get("snapshot_refreshes") or 0
        # Bounded like snapshot refreshes: when the basis keeps changing, a person reviews instead of another automatic run.
        destination="OPEN" if refreshes<MAX_SNAPSHOT_REFRESHES else "HUMAN_REVIEW"
        case.update(workflow_state=destination,recommendation_id=None,state_version=case["state_version"]+1,snapshot_refreshes=refreshes+1)
        if destination=="OPEN":without_diagnosis(case,pending=True)  # Superseded until the new investigation is reviewed.
        self._put(tx,"OpsCase",case,update=True)
        self._audit(tx,case,event_type,when,actor=actor,key=key,old=old,
                    result=f"{check['rule']} · changed: {', '.join(check['changed'])} · {check['reason']} "
                           +("The case was requeued for re-investigation and renewed review" if destination=="OPEN" else
                             "The basis kept changing; the case went to a person for review")+"; nothing was authorized or dispatched.")

    def decide(self,case_id,decision,actor_id,expected_version,idempotency_key,*,source="operator"):
        source=require_actor(actor_id,source=source)
        def decision_tx(tx):
            control=self._control(tx,lock=True);case=self._case(tx,case_id)
            payload={"decision":decision,"actor_id":actor_id,"expected_version":expected_version,
                     **({"source":source} if source!="operator" else {})}
            command,request_hash,replay=self._command(tx,case,"decision",idempotency_key,payload)
            if replay:return replay
            require_version(case,expected_version);old=case["workflow_state"];destination=decision_state(old,decision)
            when=control["as_of"];decision_id=identity("decision",command);execution_id=None
            recommendation=self._get(tx,"OpsRecommendation",case.get("recommendation_id",""))
            if decision=="approve" and not recommendation:raise OperationsConflict("Approval requires a reviewed grounded recommendation")
            if decision=="approve":
                action=recommendation.get("action_type")  # None (a legacy record): unknown action, refused.
                # Authority is recomputed on the current case: evidence, symptoms, run, review and version.
                check=self._approval_check(tx,case,recommendation,when)
                if not check["allowed"]:
                    # Requeued only for the current investigation's own, never-executed recommendation (an executed one was
                    # refused above with AUTH-24); anything else is refused and the case stays where it is.
                    requeue=check["stale"] and recommendation.get("run_id")==case.get("last_run_id")
                    if requeue:
                        self._requeue_stale(tx,case,when,actor_id,"APPROVAL_CONTEXT_STALE",check,key=f"{check['rule']}:{command}")
                    else:
                        self._audit(tx,case,"APPROVAL_REFUSED",when,actor=actor_id,key=f"{check['rule']}:{command}",old=old,
                                    result=f"{action} · {check['rule']} · {check['reason']} The case state is unchanged; nothing was authorized.")
                    refused={"refused":True,"rule_id":check["rule"],"reason":check["reason"],"requeued":requeue}
                    # Saved as the command's result, so a retry with the same key replays the refusal.
                    self._save_command(tx,case,command,request_hash,"decision",idempotency_key,refused,when)
                    return refused
                self._audit(tx,case,"APPROVAL_CONTEXT_CHECKED",when,actor=actor_id,key=command,old=old,
                            result=canonical({"rule_id":check["rule"],"decided_risk":check["risk"],"closure":check["closure"],
                                              "human_investigation":check["human_investigation"],
                                              "context":{k:check["current"].get(k) for k in CONTEXT_KEYS},
                                              "routine_new_records":check["routine_new_records"]}))
            self._put(tx,"OpsDecision",{"entity_id":decision_id,"shipment_id":case["shipment_id"],"case_id":case_id,
                "recommendation_id":case.get("recommendation_id"),"decision":decision,"actor_id":actor_id,
                "expected_version":expected_version,"idempotency_key":idempotency_key,"source":source,"recorded_at":when,"occurred_at":when})
            self._link(tx,"OPS_HAS_DECISION",case_id,decision_id,case["shipment_id"],when)
            if decision=="approve":
                execution_id=identity("execution",decision_id)
                self._authorize_execution(tx,case,execution_id,decision_id,recommendation,action,"OPERATOR_APPROVAL",when,
                                          decision_id=decision_id,decided_risk=check["risk"],closure=check["closure"],
                                          recommendation_id=recommendation["entity_id"],run_id=recommendation.get("run_id"))
            if execution_id:
                case.update(workflow_state="ACTION_INITIATED",state_version=case["state_version"]+1)
                self._put(tx,"OpsCase",case,update=True)
                self._audit(tx,case,"ACTION_INITIATED",when,actor=actor_id,old=old,
                            result="Operator authorized the action; the execution adapter carries it out. Approval is not an outcome.")
            case.update(workflow_state=destination,state_version=case["state_version"]+1)
            if decision=="reopen":
                case.update(is_terminal=False,closed_at=None,verified_outcome_id=None)
                without_diagnosis(case,pending=True)
            self._put(tx,"OpsCase",case,update=True)
            if execution_id:
                # The context this approval rests on, re-checked immediately before dispatch.
                execution=self._get(tx,"OpsExecution",execution_id)
                execution["approval_context_json"]=canonical({**check["recorded"],**check["current"],"state_version":case["state_version"],
                                                              "human_investigation":check["human_investigation"]})
                self._put(tx,"OpsExecution",execution,update=True)
            self._audit(tx,case,"OPERATOR_DECISION",when,decision=decision,actor=actor_id,old=old)
            if execution_id:
                self._audit(tx,case,"EXECUTION_REQUESTED",when,actor=actor_id,old="ACTION_INITIATED",
                            result="Awaiting execution and an independently verified outcome.")
            if decision=="reopen":self._audit(tx,case,"CASE_REOPENED",when,actor=actor_id,old=old)
            if decision=="reopen":self._invalidate_outcomes(tx,case)
            result={"case_id":case_id,"workflow_state":destination,"state_version":case["state_version"],
                "decision_id":decision_id,"execution_id":execution_id,"outcome":None,"idempotent":False}
            self._save_command(tx,case,command,request_hash,"decision",idempotency_key,result,when)
            return result
        result=self._execute(decision_tx,write=True)
        if result.get("refused"):
            # The refusal is audited (committed above); the caller gets a conflict, and nothing executes.
            raise OperationsConflict(f"{result['rule_id']}: {result['reason']}")
        return result

    def request_verification(self,case_id,actor_id,expected_version,idempotency_key):
        """An operator may ask the independent verifier to check now. Nobody can declare success:
        the verifier decides from causally relevant evidence ingested after the execution."""
        require_actor(actor_id)
        def check(tx):
            control=self._control(tx,lock=True);case=self._case(tx,case_id)
            payload={"actor_id":actor_id,"expected_version":expected_version}
            command,request_hash,replay=self._command(tx,case,"verification_request",idempotency_key,payload)
            if replay:return replay
            require_version(case,expected_version)
            if case["workflow_state"]!="AWAITING_OUTCOME":raise OperationsConflict("Verification requires an executed action awaiting its outcome")
            self._audit(tx,case,"VERIFICATION_REQUESTED",control["as_of"],actor=actor_id,result="Operator asked the verifier to check now.")
            self._save_command(tx,case,command,request_hash,"verification_request",idempotency_key,{"case_id":case_id,"requested":True},control["as_of"])
            return None
        replay=self._execute(check,write=True)
        if replay:return replay
        results=self.outcome_step(limit=10,case_id=case_id,force=True)
        detail=self.case_detail(case_id)
        return {"case_id":case_id,"workflow_state":detail["workflow_state"],"state_version":detail["state_version"],
                "outcome":detail.get("outcome"),"verified":bool(results),"idempotent":False}

    def case_detail(self,case_id):
        def read(tx):
            case=self._case(tx,case_id)
            def linked(kind):
                order="n.iteration DESC," if kind=="OpsReview" else ""
                return [public_value(row["props"]) for row in tx.run(f"MATCH(n:OpsEntity:{kind} {{case_id:$case_id,dataset_id:$dataset}}) RETURN properties(n) AS props ORDER BY {order}n.recorded_at DESC,n.entity_id DESC LIMIT 20",case_id=case_id,dataset=self.dataset_id)]
            recommendation=self._get(tx,"OpsRecommendation",case.get("recommendation_id",""))
            if recommendation:
                # Whether a person's approval may make the system carry this action out: the same checks approval runs,
                # on the current case, and only while the case is actually awaiting a decision.
                try:
                    decision_state(case["workflow_state"],"approve");awaiting=True
                except OperationsConflict:
                    awaiting=False
                check=self._approval_check(tx,case,recommendation,self._control(tx)["as_of"])
                recommendation={**{k:v for k,v in recommendation.items() if k!="approval_context_json"},
                                "approvable":awaiting and check["allowed"],
                                "approval_rule":check["rule"] if awaiting else "LIFECYCLE-not-awaiting-decision",
                                "approval_reason":check["reason"] if awaiting else f"The case is {case['workflow_state']}, not awaiting a decision.",
                                "approval_context_stale":check["stale"]}
            runs=linked("OpsRun");outcomes=linked("OpsOutcome");executions=linked("OpsExecution")
            # The current investigation is the case's last run (ties on the paused clock must not pick an older one),
            # and its review is that run's final round: an earlier run's pass never stands in for the current one.
            last=public_value(case.get("last_run_id")) if case.get("last_run_id") else None
            current=next((r for r in runs if r.get("entity_id")==last),None) or (None if last else (runs[0] if runs else None))
            from operations.worker import with_review_reason
            # While a newer investigation is queued or running, the earlier run's review is not the current review.
            queued=case["workflow_state"] in ("OPEN","REOPENED")
            superseded=queued or case["workflow_state"]=="INVESTIGATING"
            reviews=[with_review_reason(r) for r in linked("OpsReview") if current and not superseded and r.get("run_id")==current.get("entity_id")]
            if current:current["result"]=served_run_result(json.loads(current.pop("result_json")))
            diagnosis=case_diagnosis(case,current)
            previous=None
            if queued and current:
                # Queued for a new investigation: the earlier run, its review rounds and stage events are not current. They
                # are served apart, marked superseded, and the current run is absent until the new one starts.
                previous,current={**current,"superseded":True},None
            run_at=(current or previous or {}).get("recorded_at")
            def in_cycle(record):
                """Whether an outcome or execution belongs to the current investigation cycle (not an earlier one)."""
                if queued:return False  # A new cycle is queued; nothing belongs to it yet.
                if record.get("run_id"):return record["run_id"]==last
                # Recorded before run ids were stored: only a record made after the current run started counts.
                return not run_at or instant(str(record.get("recorded_at")))>instant(str(run_at))
            if outcomes:outcomes[0].update(outcome_id=outcomes[0]["entity_id"],current_cycle=in_cycle(outcomes[0]))
            from operations.action_lifecycle import view as action_view
            for execution in executions:
                execution["current_cycle"]=in_cycle(execution)
                execution["action_lifecycle"]=action_view(execution)
                execution.pop("action_lifecycle_json",None)
                execution.pop("action_target_json",None)
            active_actions=[e["action_lifecycle"] for e in executions if e.get("current_cycle") and e.get("action_lifecycle")]
            human_decision=bool((recommendation or {}).get("risk_class") in ("HUMAN_REVIEW","PROHIBITED") or
                                any(e.get("closure")=="HUMAN" for e in executions if e.get("current_cycle")) or
                                any(r.get("model_verdict") in ("HUMAN_REVIEW","ESCALATE") for r in reviews))
            resolution=("VERIFIED_RESOLVED" if case["workflow_state"]=="RESOLVED" and case.get("verified_outcome_id") else
                        "HUMAN_DECISION_REQUIRED" if human_decision else
                        "UNRESOLVED" if any(a["state"] in ("FAILED","REJECTED","EXPIRED","UNRESOLVED") or
                                            (a["state"]=="VERIFIED" and not a.get("resolved")) for a in active_actions) else
                        "OPERATIONAL_WORK_PENDING" if active_actions else "INVESTIGATION_PENDING")
            return {"case_id":case_id,"shipment_id":case["shipment_id"],"workflow_state":case["workflow_state"],
                "symptom_codes":list(case.get("symptom_codes") or []),"opened_at":case.get("opened_at"),
                "state_version":case["state_version"],"priority":case["priority"],"operational_status":case["operational_status"],
                "as_of":case["as_of"],"recommendation_id":case.get("recommendation_id"),"last_run_id":case.get("last_run_id"),
                "recommendation":recommendation,"review":reviews[0] if reviews else None,"outcome":outcomes[0] if outcomes else None,
                "decisions":linked("OpsDecision"),"executions":executions,"run":current,"previous_run":previous,
                # Who investigates the case or last did, and where that run stands (InvestigationStatusV3).
                "investigation_status":self._investigation_status(tx,case),
                # The current run's accepted agent investigation, or explicitly absent; never rule output.
                "diagnosis":diagnosis,"synthetic":True,
                "action_status":{"version":"suhail-action-1","resolution":resolution,
                                 "human_decision_required":human_decision,"actions":active_actions,"synthetic":True}}
        return self._execute(read)
