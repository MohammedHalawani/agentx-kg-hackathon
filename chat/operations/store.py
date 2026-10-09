"""Mutable development ledger in the verified local shadow; never writes V2Entity."""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import math
import queue
import threading

from dataset_v2.contracts import Config, canonical, digest, instant, UTC_FIELDS
from dataset_v2.load import target_guard
from operations.schema import SCHEMA, FIELDS, COMMON, public_value
from operations.lifecycle import OperationsConflict, decision_state, require_version, require_actor
from operations.simulator import SPEEDS, EVENT_KINDS
from operations.worker import analyze

CONTROL_ID = "DEMO-OPS-CONTROL"
# The foundation replay database and the live provider-feed database (plus its isolated test twin).
OPERATIONS_DATABASES = ("shipments-v2-demo", "shipments-v2-demo-live", "shipments-v2-demo-test")
INGEST_BATCH = 500


MONITOR_QUEUE_LIMIT = 500
AUTO_OUTCOME_WINDOW_HOURS = 72
# Normal provider upload lag is seconds to minutes. The monitor waits this long past a deadline
# before calling an expected observation missing, so in-flight uploads do not open cases.
DETECTION_ALLOWANCE_SECONDS = 900
# A case whose shipment keeps receiving evidence mid-investigation is re-investigated at most this
# many times before it goes to a person instead of acting on a superseded snapshot.
MAX_SNAPSHOT_REFRESHES = 2


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


def monitor_finding(assessment):
    """Deterministic monitor rule: open a case only when visible evidence shows an abnormal symptom."""
    symptoms = sorted({SYMPTOMS.get(item["code"], "EVIDENCE_MISSING") for item in assessment.get("exceptions", [])})
    return {"open": bool(symptoms), "symptoms": symptoms}


def symptom_status(symptoms):
    return next((status for symptom, status in SYMPTOM_STATUS if symptom in symptoms), "NEEDS_ATTENTION")


def identity(kind, *parts):
    return "DEMO-OPS-" + kind.upper() + "-" + digest(parts)[:24]


def temporal_properties(props):
    fields = UTC_FIELDS | {"initial_as_of", "cursor_time", "claim_at", "observed_at", "source_occurred_at",
                           "outcome_checked_as_of", "deadline_at", "closed_at", "session_started_at", "last_processed_at", "executed_at"}
    return {key: instant(value) if key in fields and isinstance(value, str) else value for key, value in props.items()}


class OperationsStore:
    def __init__(self, driver, database, dataset_id, config=None, reader=None, *, uri="bolt://localhost:7687", protected=(), agents=None):
        target_guard(uri, database, protected)
        if database not in OPERATIONS_DATABASES or not str(dataset_id).startswith("DEMO-"):
            raise OperationsConflict("Operations requires the fixed audited local shadow")
        self.driver, self.database, self.dataset_id = driver, database, dataset_id
        # Live datasets receive observations only through the provider gateway, never by replaying imports.
        self.live = str(dataset_id).startswith("DEMO-SUHAIL-LIVE")
        if self.live:
            from operations.ingestion import Gateway
            self.gateway = Gateway(driver, database, dataset_id)
        self.config = config or Config(dataset_id=dataset_id)
        self.reader = reader
        self.agents = agents  # operations.investigator (GPT-OSS tool loop + reviewer) or None for rules only
        self.adapter = None   # Execution adapter; in development the synthetic operational simulator
        self._subscribers={}
        self._subscribers_lock=threading.RLock()

    def _execute(self, callback, *, write=False):
        with self.driver.session(database=self.database, default_access_mode="WRITE" if write else "READ") as session:
            def guarded(tx):
                self._guard(tx)
                return callback(tx)
            return session.execute_write(guarded) if write else session.execute_read(guarded)

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

    def _invalidate_outcomes(self,tx,case):
        rows=tx.run("MATCH(n:OpsEntity:OpsOutcome {case_id:$case_id,dataset_id:$dataset}) RETURN properties(n) AS props ORDER BY n.recorded_at DESC,n.entity_id DESC LIMIT 20",
                    case_id=case["entity_id"],dataset=self.dataset_id)
        for row in rows:
            outcome=public_value(row["props"])
            if outcome.get("verification_status")=="VERIFIED" and not outcome.get("invalidated"):
                outcome["invalidated"]=True
                self._put(tx,"OpsOutcome",outcome,update=True)

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
        return self.status()

    def clock(self):
        return self._execute(lambda tx: self._control(tx)["as_of"])

    def _reader(self):
        if self.reader is None:
            from operations.read_model import OperationsReader
            self.reader=OperationsReader(self.driver,self.database,self.dataset_id,self.config,clock=self.clock,store=self)
        return self.reader

    def status(self):
        control = self._execute(lambda tx: self._control(tx))
        return {"synthetic": True, "demo": True, "as_of": control["as_of"],
            "worker": {"state": control["worker_state"], "concurrency": 1, "processed_count": control["processed_count"],
                       "active_case_id": control.get("worker_claim"),
                       "active_shipment_id": control.get("claim_shipment_id") if control.get("worker_claim") else None,
                       # Most recent completed claim, so the live panel can show its recorded stages after the run.
                       "last_case_id": control.get("last_case_id"), "last_shipment_id": control.get("last_shipment_id"),
                       "last_workflow_state": control.get("last_workflow_state"), "last_processed_at": control.get("last_processed_at")},
            "session": {"case_source": "monitor", "session_id": control.get("session_id"),
                        "started_at": control.get("session_started_at"), "monitor_pending": len(control.get("monitor_queue") or []),
                        "monitor_checked": control.get("monitor_checked", 0), "monitor_opened": control.get("monitor_opened", 0)},
            "simulator": {"state": control["simulator_state"], "speed": control["speed"], "replay_mode":control.get("replay_mode","timeline"), "event_count": control["event_count"],
                          "cursor": {"time": control["cursor_time"], "id": control["cursor_id"]}, "end_at": control["end_at"]},
            "notifications": {"mode": "dry_run", "external_calls": 0}}

    def control(self, component, action, speed=None, actor_id="DEMO-OPERATOR-LOCAL", replay_mode=None):
        require_actor(actor_id)
        if component not in {"worker", "simulator"} or action not in {"start", "pause", "step"}:
            raise OperationsConflict("Invalid operations control")
        if speed is not None and (type(speed) is not int or speed not in SPEEDS):
            raise OperationsConflict("Simulation speed must be 1, 10, 60, 600 or 3600")
        if replay_mode is not None and (component!="simulator" or replay_mode not in {"timeline","compressed"}):
            raise OperationsConflict("Replay mode must be timeline or compressed")
        def control_tx(tx):
            c = self._control(tx, lock=True)
            c[component + "_state"] = "running" if action == "start" else "paused"
            if speed is not None: c["speed"] = speed
            if replay_mode is not None:c["replay_mode"]=replay_mode
            if action == "pause" and component == "worker" and c.get("worker_claim"):
                case = self._case(tx, c["worker_claim"])
                if case["workflow_state"] == "INVESTIGATING":
                    case.update(workflow_state="OPEN", state_version=case["state_version"] + 1, claim_id=None, claim_at=None)
                    self._put(tx, "OpsCase", case, update=True)
                    self._audit(tx, case, "CLAIM_RELEASED", c["as_of"], actor=actor_id)
                c.update(worker_claim=None, claim_at=None)
            self._put(tx, "OpsControl", c, update=True)
        self._execute(control_tx, write=True)
        if action == "step":
            if component == "worker": self.process_one(manual=True)
            else: self.tick(step=True)
        return self.status()

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
            batch = self.gateway.ingest_due(target, limit=INGEST_BATCH)
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
            case.update(as_of=when, state_version=case["state_version"]+1)
            if kind == "RecipientReport" and case["workflow_state"] == "RESOLVED":
                case.update(workflow_state="REOPENED", state_version=case["state_version"]+1, is_terminal=False, closed_at=None, verified_outcome_id=None)
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
            findings.append((sid,finding,context["as_of"],forecast))
        def record(tx):
            c=self._control(tx,lock=True);opened=[]
            for sid,finding,as_of,forecast in findings:
                c["monitor_checked"]=c.get("monitor_checked",0)+1
                self._risk_flag(tx,sid,forecast,as_of)
                if not finding["open"]:continue
                cases=[public_value(r["props"]) for r in tx.run("MATCH(c:OpsCase {shipment_id:$sid,dataset_id:$dataset,split:'development'}) RETURN properties(c) AS props",
                        sid=sid,dataset=self.dataset_id)]
                active=[x for x in cases if not x.get("is_terminal") and x["workflow_state"]!="RESOLVED"]
                if active:
                    # The open case follows this shipment; newly observed symptoms are added to it, not a new case.
                    case=active[0];new=sorted(set(finding["symptoms"])-set(case.get("symptom_codes") or []))
                    if new:
                        case.update(symptom_codes=sorted(set(case.get("symptom_codes") or [])|set(new)),state_version=case["state_version"]+1)
                        self._put(tx,"OpsCase",case,update=True)
                        self._audit(tx,case,"SYMPTOMS_UPDATED",as_of,actor="SUHAIL-MONITOR",result="New symptoms: "+", ".join(new))
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
            "issue_summary":"Monitor detected an expected-vs-actual divergence in visible evidence; automatic investigation pending."})
        self._link(tx,"OPS_ABOUT",identifier,sid,sid,when)
        self._audit(tx,case,"CASE_OPENED",when,result="Monitor symptoms: "+", ".join(symptoms),actor="SUHAIL-MONITOR")
        return identifier

    def reset_session(self, actor_id="DEMO-OPERATOR-LOCAL"):
        """Start a fresh live session: clear derived operational ledger (never V2 evidence) and rewind the clock."""
        require_actor(actor_id)
        if self.live:
            if self.status()["worker"]["active_case_id"]:raise OperationsConflict("Pause auto-triage before starting a new session")
            self.gateway.reset()
        def reset_tx(tx):
            c=self._control(tx,lock=True)
            if c.get("worker_claim"):raise OperationsConflict("Pause auto-triage before starting a new session")
            if self.live:
                row=tx.run("MATCH (f:ProviderFeedItem {origin:'PROVIDER'}) RETURN min(f.deliver_at) AS start").single()
            else:
                row=tx.run("MATCH (e:V2Entity {dataset_id:$dataset,split:'development'}) WHERE e.occurred_at IS NOT NULL "
                           "RETURN min(e.occurred_at) AS start",dataset=self.dataset_id).single()
            start=public_value(row["start"]) if row and row["start"] else c["initial_as_of"]
            start=start.isoformat() if hasattr(start,"isoformat") else str(start)
            start=(instant(start)-timedelta(seconds=1)).isoformat()
            tx.run("MATCH (n:OpsEntity {dataset_id:$dataset,split:'development'}) WHERE NOT n:OpsControl DETACH DELETE n",
                   dataset=self.dataset_id).consume()
            session=identity("session",c["state_version"],start)
            c.update(as_of=start,initial_as_of=start,cursor_time=start,cursor_id="",simulator_state="paused",worker_state="paused",
                     worker_claim=None,claim_at=None,claim_shipment_id=None,processed_count=0,event_count=0,
                     last_case_id=None,last_shipment_id=None,last_workflow_state=None,last_processed_at=None,
                     case_source="monitor",session_id=session,session_started_at=start,monitor_queue=[],monitor_checked=0,monitor_opened=0)
            self._put(tx,"OpsControl",c,update=True)
        self._execute(reset_tx,write=True)
        return self.status()

    def outcome_step(self, limit=3, *, case_id=None, force=False):
        """Verify automatically executed actions from evidence that arrived after them (live sessions only)."""
        from operations.outcome_engine import evaluate, EVIDENCE_ACTIONS
        from operations.reasoning import evidence_world
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
        for case,execution in items:
            context=self._reader().evidence(case["shipment_id"],clock)
            verdict=evaluate(evidence_world(context,self.config),case["shipment_id"],execution,context["as_of"])
            def record(tx,case=case,execution=execution,verdict=verdict):
                c=self._control(tx,lock=True);current=self._case(tx,case["entity_id"]);when=c["as_of"]
                if current["workflow_state"]!="AWAITING_OUTCOME":return None
                if verdict["status"]=="pending":
                    current["outcome_checked_as_of"]=current["as_of"];self._put(tx,"OpsCase",current,update=True);return None
                success=verdict["status"]=="success";outcome_id=identity("outcome","auto",execution["entity_id"],when)
                self._put(tx,"OpsOutcome",{"entity_id":outcome_id,"shipment_id":current["shipment_id"],"case_id":current["entity_id"],
                    "execution_id":execution["entity_id"],"action_code":execution["action_code"],"action_type":execution["action_type"],"success":success,
                    "outcome_type":verdict["outcome_type"],"evidence_ids":verdict["evidence_ids"],"verification_status":"VERIFIED",
                    "verified_at":when,"verifier_id":"SUHAIL-OUTCOME-VERIFIER","invalidated":False,"observed_at":when,
                    "reason":verdict["reason"],"rule_id":verdict.get("rule_id"),"expected_effect":verdict.get("expected_effect"),
                    "recorded_at":when,"occurred_at":when})
                self._link(tx,"OPS_HAS_OUTCOME",current["entity_id"],outcome_id,current["shipment_id"],when)
                self._audit(tx,current,"OUTCOME_OBSERVED",when,actor="SUHAIL-OUTCOME-VERIFIER",result=verdict["reason"])
                old=current["workflow_state"]
                from operations.authority import HUMAN_FLOOR_SYMPTOMS
                floor=sorted(set(current.get("symptom_codes") or [])&HUMAN_FLOOR_SYMPTOMS)
                if success and (execution.get("closure")=="HUMAN" or floor):
                    # Verified evidence, but the observed symptoms reserve closure for a person.
                    current.update(workflow_state="HUMAN_REVIEW",state_version=current["state_version"]+1)
                    self._put(tx,"OpsCase",current,update=True)
                    self._audit(tx,current,"OUTCOME_VERIFIED_HUMAN_CLOSURE",when,actor="SUHAIL-OUTCOME-VERIFIER",old=old,
                                result=f"{execution['action_type']} verified: {verdict['reason']} Closure reserved for a person"
                                       +(f" ({', '.join(floor)})." if floor else "."))
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
                return {"case_id":current["entity_id"],"workflow_state":current["workflow_state"]}
            result=self._execute(record,write=True)
            if result:results.append(result)
        return results

    def _authorize_execution(self,tx,case,execution_id,source_id,proposal,action_type,authority,when,*,decision_id,closure="AUTO"):
        """Record an authorized action for the execution adapter. Authorization is not execution or success."""
        target=(proposal.get("target") if isinstance(proposal.get("target"),dict) else None) or json.loads(proposal.get("target_json") or "{}")
        self._put(tx,"OpsExecution",{"entity_id":execution_id,"shipment_id":case["shipment_id"],"case_id":case["entity_id"],
            "decision_id":decision_id,"action_code":proposal.get("action_code"),"action_type":action_type,"authority":authority,
            "status":"AUTHORIZED","expected_result":proposal.get("action"),"idempotency_key":execution_id,"closure":closure,
            "target_device":target.get("device_id"),"expected_evidence_json":canonical(target.get("expected_evidence") or []),
            "recorded_at":when,"occurred_at":when})
        self._link(tx,"OPS_INITIATES",source_id,execution_id,case["shipment_id"],when)

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
        for execution in rows:
            execution["expected_evidence"]=json.loads(execution.get("expected_evidence_json") or "[]")
            if self.adapter is not None:
                try:receipt=self.adapter.respond(execution,clock);mode="synthetic_operational_simulator"
                except Exception as error:receipt={"scheduled":0,"behaviour":f"adapter_error_{type(error).__name__}"};mode="adapter_error"
            else:
                receipt={"scheduled":0,"behaviour":"no execution adapter configured; nothing was sent"};mode="no_adapter"
            def record(tx,execution=execution,receipt=receipt,mode=mode):
                c=self._control(tx,lock=True);when=c["as_of"]
                current=self._get(tx,"OpsExecution",execution["entity_id"])
                case=self._case(tx,current["case_id"])
                deadline=(instant(when)+timedelta(hours=AUTO_OUTCOME_WINDOW_HOURS)).isoformat()
                current.update(status="ACKNOWLEDGED",receipt_ref=f"{mode}:{execution['entity_id']}",mode=mode,executed_at=when,
                               occurred_at=when,deadline_at=deadline,adapter_result_json=canonical(receipt))
                self._put(tx,"OpsExecution",current,update=True)
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
                if "RecipientReport" in row["labels"] and case["workflow_state"]=="RESOLVED":
                    case.update(workflow_state="REOPENED",state_version=case["state_version"]+1,is_terminal=False,closed_at=None,verified_outcome_id=None)
                    self._invalidate_outcomes(tx,case)
                    self._audit(tx,case,"CASE_REOPENED",when,result="A new attributed recipient report reopens investigation.",actor="DEMO-SIMULATOR")
                self._put(tx,"OpsCase",case,update=True)
            self._audit(tx,case,"SIMULATION_EVENT",when,result=next(k for k in row["labels"] if k in EVENT_KINDS),key=p["entity_id"],actor="DEMO-SIMULATOR")

    def process_one(self, case_id=None, *, manual=False):
        def claim(tx):
            control=self._control(tx,lock=True)
            if control.get("worker_claim") or (control["worker_state"]!="running" and not manual and case_id is None):return None
            rows=list(tx.run("MATCH(c:OpsCase {dataset_id:$dataset,split:'development'}) "
                "WHERE c.workflow_state IN ['OPEN','REOPENED'] AND c.opened_at <= $clock "
                "AND ($id IS NULL OR c.entity_id=$id) RETURN properties(c) AS props ORDER BY c.opened_at,c.entity_id LIMIT 1",
                dataset=self.dataset_id,clock=instant(control["as_of"]),id=case_id))
            if not rows:return None
            case=public_value(rows[0]["props"]); token=identity("claim",case["entity_id"],case["state_version"])
            case.update(workflow_state="INVESTIGATING",state_version=case["state_version"]+1,claim_id=token,claim_at=control["as_of"],as_of=control['as_of'],
                        last_run_id=identity("run",case["entity_id"],token))
            control.update(worker_claim=case["entity_id"],claim_at=control["as_of"],claim_shipment_id=case["shipment_id"])
            self._put(tx,"OpsCase",case,update=True);self._put(tx,"OpsControl",control,update=True)
            self._audit(tx,case,"CASE_CLAIMED",case["as_of"])
            return case
        case=self._execute(claim,write=True)
        if not case:return {"processed":False,"outcome":None}
        self._reader()
        def finish(tx,analysis):
            control=self._control(tx,lock=True);current=self._case(tx,case["entity_id"])
            if current.get("claim_id")!=case["claim_id"] or current["workflow_state"]!="INVESTIGATING":
                raise OperationsConflict("Worker claim was released or superseded")
            stale=current["state_version"]!=case["state_version"] or current["as_of"]!=case["as_of"]
            if stale and (current.get("snapshot_refreshes") or 0)<MAX_SNAPSHOT_REFRESHES:
                current.update(workflow_state="OPEN",state_version=current["state_version"]+1,claim_id=None,claim_at=None,
                               snapshot_refreshes=(current.get("snapshot_refreshes") or 0)+1)
                control.update(worker_claim=None,claim_at=None)
                self._put(tx,"OpsCase",current,update=True);self._put(tx,"OpsControl",control,update=True)
                self._audit(tx,current,"CLAIM_RELEASED",control["as_of"],result="Evidence snapshot changed during analysis; re-investigating with the new evidence.")
                return {"processed":False,"case_id":current["entity_id"],"reason":"snapshot_changed","workflow_state":"OPEN",
                        "state_version":current["state_version"],"outcome":None}
            if stale:
                # Evidence kept arriving: record this investigation, but never act on a superseded snapshot.
                analysis={**analysis,"authority":{**(analysis.get("authority") or {}),"risk_class":"HUMAN_REVIEW",
                          "reason":"Evidence kept changing during repeated investigations; a person must review the latest evidence."},
                          "result":{**analysis["result"],"workflow_state":"HUMAN_REVIEW"},"degraded":[*(analysis.get("degraded") or []),
                          {"role":"snapshot","error":"evidence changed during investigation"}]}
            when=control["as_of"];run_id=identity("run",current["entity_id"],case["claim_id"])
            self._put(tx,"OpsRun",{"entity_id":run_id,"shipment_id":case["shipment_id"],"case_id":case["entity_id"],
                "recorded_at":when,"mode":analysis["mode"],"result_json":canonical(analysis),"iteration":len(analysis["trace"]),
                "status":"RUNNING","context_hash":analysis["context_hash"]},update=True)
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
            for item in analysis["trace"]:
                review_id=identity("review",run_id,item["iteration"])
                self._put(tx,"OpsReview",{"entity_id":review_id,"shipment_id":case["shipment_id"],"case_id":case["entity_id"],
                    "run_id":run_id,"recorded_at":when,"verdict":item["review"]["verdict"],"feedback":item["review"]["feedback"],
                    "summary_en":item["review"]["feedback"],
                    "summary_ar":("تدعم الأدلة المقترح فقط. يلزم اعتماد المشغّل ونتيجة موثّقة مستقلة قبل الإغلاق."
                                  if item["review"]["verdict"]=="accept" else "رفضت مراجعة السلامة المقترح. يجب استخدام أدلة الشحنة وطلب اعتماد المشغّل؛ موقع المركبة لا يثبت تسليم الطرد."),
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
                self._audit(tx,current,"MODEL_DEGRADED",when,actor="SUHAIL-"+item["role"].upper(),key=item["role"],
                            result=f"{item['role']} unavailable ({item.get('error') or 'no valid output'}); automatic execution blocked.")
            if recommendation_id and analysis["review"]["verdict"]=="accept" and authority.get("risk_class")=="AUTO" and not analysis.get("degraded"):
                execution_id=identity("execution","auto",recommendation_id)
                self._authorize_execution(tx,current,execution_id,recommendation_id,analysis["proposal"],authority["action_type"],
                                          "AUTO_POLICY",when,decision_id=None,closure=authority.get("closure","AUTO"))
                self._audit(tx,current,"ACTION_AUTHORIZED",when,actor="SUHAIL-AUTHORITY-POLICY",old=current["workflow_state"],
                            result=f"AUTO · {authority['action_type']} · {authority['reason']}")
                current.update(workflow_state="ACTION_INITIATED",state_version=current["state_version"]+1)
                self._put(tx,"OpsCase",current,update=True)
                old="ACTION_INITIATED"
            if authority:
                # Every authority decision, including denials, with its rule and the inputs it used.
                self._audit(tx,current,"AUTHORITY_DECISION",when,actor="SUHAIL-AUTHORITY-POLICY",old=old,key=authority.get("rule_id"),
                            result=canonical({k:authority.get(k) for k in ("rule_id","risk_class","action_type","closure","reason","inputs")}))
            current.update(workflow_state=analysis["result"]["workflow_state"],state_version=current["state_version"]+1,
                last_run_id=run_id,recommendation_id=recommendation_id,claim_id=None,claim_at=None,
                cause_codes=analysis["result"]["operational_labels"],operational_status=analysis["result"]["operational_status"])
            investigation=analysis.get("investigation") or {}
            primary=investigation.get("primary_cause") or investigation.get("primary_hypothesis")
            diagnosis=next((d for d in analysis["result"]["diagnoses"] if d["code"]==primary),None) or next(iter(analysis["result"]["diagnoses"]),None)
            if diagnosis:current["issue_summary"]=diagnosis.get("summary_en") or diagnosis["summary"]  # Neutral rule text, not model prose.
            self._put(tx,"OpsCase",current,update=True)
            control.update(worker_claim=None,claim_at=None,processed_count=control["processed_count"]+1,
                           last_case_id=current["entity_id"],last_shipment_id=current["shipment_id"],
                           last_workflow_state=current["workflow_state"],last_processed_at=when)
            self._put(tx,"OpsControl",control,update=True)
            return {"processed":True,"case_id":current["entity_id"],"workflow_state":current["workflow_state"],
                    "state_version":current["state_version"],"run_id":run_id,"mode":analysis["mode"],"afl":analysis["afl"],"outcome":None}
        from operations.graph import investigate
        try:
            analysis,result=investigate(case["shipment_id"],case["as_of"],self.config,self.reader.evidence,
                lambda sid,codes:self.reader.precedents(sid,codes,as_of=case['as_of']),
                commit=lambda a:self._execute(lambda tx:finish(tx,a),write=True),
                on_event=lambda event,events:self._record_stage(case,event,events),
                agents=self.agents,live_session=True,symptoms=case.get("symptom_codes") or [],
                heartbeats=getattr(self.reader,"heartbeats",None))
            analysis["writeback"]=result
            self._save_run_trace(case,analysis)
            return result
        except Exception:
            self.control("worker","pause")
            raise

    def _record_stage(self,claimed,event,events):
        def record(tx):
            self._control(tx,lock=True)
            case=self._case(tx,claimed["entity_id"])
            run_id=claimed["last_run_id"]
            if case.get("last_run_id")!=run_id:raise OperationsConflict("Investigation was superseded")
            current=self._get(tx,"OpsRun",run_id)
            trace=json.loads(current["result_json"]) if current else {}
            trace["pipeline_events"]=events
            self._put(tx,"OpsRun",{"entity_id":run_id,"shipment_id":case["shipment_id"],"case_id":case["entity_id"],
                "recorded_at":claimed["as_of"],"mode":"deterministic_evidence_rules","result_json":canonical(trace),
                "iteration":event["iteration"],"status":"FAILED" if event["status"]=="FAILED" else "RUNNING"},update=True)
            self._link(tx,"OPS_HAS_RUN",case["entity_id"],run_id,case["shipment_id"],claimed["as_of"])
            audit_id=run_id.replace("-RUN-","-STAGE-")+f'-{event["sequence"]:04d}'
            self._put(tx,"OpsAudit",{"entity_id":audit_id,"shipment_id":case["shipment_id"],"case_id":case["entity_id"],
                "run_id":run_id,"event_type":"PIPELINE_STAGE","stage":event["stage"],"stage_status":event["status"],
                "sequence":event["sequence"],"wall_recorded_at":event["recorded_at"],
                "occurred_at":claimed["as_of"],"recorded_at":claimed["as_of"],"actor_id":"DEMO-RULE-WORKER",
                "to_state":case["workflow_state"],"result":event["stage"]+": "+event["status"]})
            self._link(tx,"OPS_HAS_AUDIT",case["entity_id"],audit_id,case["shipment_id"],claimed["as_of"])
            return {'run_id':run_id,'events':events,'workflow_state':case['workflow_state'],
                    'state_version':case['state_version'],'status':'FAILED' if event['status']=='FAILED' else 'RUNNING'}
        state=self._execute(record,write=True)
        self._publish_pipeline(claimed['entity_id'],state)

    def _save_run_trace(self,case,analysis):
        def save(tx):
            self._control(tx,lock=True)
            run=self._get(tx,"OpsRun",case["last_run_id"])
            run.update(result_json=canonical(analysis),status="REVIEWED" if analysis['writeback'].get('processed') else "ABORTED")
            self._put(tx,"OpsRun",run,update=True)
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

    def pipeline_state(self,case_id):
        def read(tx):
            case=self._case(tx,case_id)
            run=self._get(tx,"OpsRun",case.get("last_run_id",""))
            return {"workflow_state":case["workflow_state"],"state_version":case["state_version"],
                    "run_id":case.get("last_run_id"),"status":run["status"] if run else "QUEUED",
                    "events":json.loads(run["result_json"]).get("pipeline_events",[]) if run else []}
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
            case.update(workflow_state='OPEN',state_version=case['state_version']+1,recommendation_id=None)
            self._put(tx,'OpsCase',case,update=True)
            self._audit(tx,case,'REANALYSIS_REQUESTED',when,actor=actor_id,old=old,
                        result='Explicit re-analysis requested; previous investigation remains recorded.')
            result={'case_id':case_id,'workflow_state':'OPEN','state_version':case['state_version'],'idempotent':False}
            self._save_command(tx,case,command,request_hash,'reanalyze',idempotency_key,result,when)
            return result
        return self._execute(request,write=True)

    def decide(self,case_id,decision,actor_id,expected_version,idempotency_key):
        require_actor(actor_id)
        def decision_tx(tx):
            control=self._control(tx,lock=True);case=self._case(tx,case_id)
            payload={"decision":decision,"actor_id":actor_id,"expected_version":expected_version}
            command,request_hash,replay=self._command(tx,case,"decision",idempotency_key,payload)
            if replay:return replay
            require_version(case,expected_version);old=case["workflow_state"];destination=decision_state(old,decision)
            when=control["as_of"];decision_id=identity("decision",command);execution_id=None
            recommendation=self._get(tx,"OpsRecommendation",case.get("recommendation_id",""))
            if decision=="approve" and not recommendation:raise OperationsConflict("Approval requires a reviewed grounded recommendation")
            self._put(tx,"OpsDecision",{"entity_id":decision_id,"shipment_id":case["shipment_id"],"case_id":case_id,
                "recommendation_id":case.get("recommendation_id"),"decision":decision,"actor_id":actor_id,
                "expected_version":expected_version,"idempotency_key":idempotency_key,"recorded_at":when,"occurred_at":when})
            self._link(tx,"OPS_HAS_DECISION",case_id,decision_id,case["shipment_id"],when)
            if decision=="approve":
                execution_id=identity("execution",decision_id)
                self._authorize_execution(tx,case,execution_id,decision_id,recommendation,recommendation.get("action_type") or "REQUEST_ADDITIONAL_EVIDENCE",
                                          "OPERATOR_APPROVAL",when,decision_id=decision_id)
            if execution_id:
                case.update(workflow_state="ACTION_INITIATED",state_version=case["state_version"]+1)
                self._put(tx,"OpsCase",case,update=True)
                self._audit(tx,case,"ACTION_INITIATED",when,actor=actor_id,old=old,
                            result="Operator authorized the action; the execution adapter carries it out. Approval is not an outcome.")
            case.update(workflow_state=destination,state_version=case["state_version"]+1)
            if decision=="reopen":case.update(is_terminal=False,closed_at=None,verified_outcome_id=None)
            self._put(tx,"OpsCase",case,update=True)
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
        return self._execute(decision_tx,write=True)

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
            runs=linked("OpsRun");reviews=linked("OpsReview");outcomes=linked("OpsOutcome")
            if runs:runs[0]["result"]=json.loads(runs[0].pop("result_json"))
            if outcomes:outcomes[0]["outcome_id"]=outcomes[0]["entity_id"]
            return {"case_id":case_id,"shipment_id":case["shipment_id"],"workflow_state":case["workflow_state"],
                "state_version":case["state_version"],"priority":case["priority"],"operational_status":case["operational_status"],
                "as_of":case["as_of"],"recommendation_id":case.get("recommendation_id"),"last_run_id":case.get("last_run_id"),
                "recommendation":recommendation,"review":reviews[0] if reviews else None,"outcome":outcomes[0] if outcomes else None,
                "decisions":linked("OpsDecision"),"executions":linked("OpsExecution"),"run":runs[0] if runs else None,"synthetic":True}
        return self._execute(read)
