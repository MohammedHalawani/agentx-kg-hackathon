"""Mutable development ledger in the verified local shadow; never writes V2Entity."""
from dataclasses import asdict
from datetime import timedelta
import json
import math

from dataset_v2.contracts import Config, canonical, digest, instant, UTC_FIELDS
from dataset_v2.load import target_guard
from operations.schema import SCHEMA, FIELDS, COMMON, public_value
from operations.lifecycle import OperationsConflict, decision_state, require_version, require_actor
from operations.simulator import SPEEDS, EVENT_KINDS
from operations.worker import analyze
from operations.outcome import validate_observation, verify

CONTROL_ID = "DEMO-OPS-CONTROL"


def identity(kind, *parts):
    return "DEMO-OPS-" + kind.upper() + "-" + digest(parts)[:24]


def temporal_properties(props):
    fields = UTC_FIELDS | {"initial_as_of", "cursor_time", "claim_at", "observed_at", "source_occurred_at"}
    return {key: instant(value) if key in fields and isinstance(value, str) else value for key, value in props.items()}


class OperationsStore:
    def __init__(self, driver, database, dataset_id, config=None, reader=None, *, uri="bolt://localhost:7687", protected=()):
        target_guard(uri, database, protected)
        if database != "shipments-v2-demo" or not str(dataset_id).startswith("DEMO-"):
            raise OperationsConflict("Operations requires the fixed local DEMO shadow")
        self.driver, self.database, self.dataset_id = driver, database, dataset_id
        self.config = config or Config(dataset_id=dataset_id)
        self.reader = reader

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
            "event_type": event_type, "occurred_at": when, "recorded_at": when, "actor_id": actor, "decision": decision,
            "result": result[:1000], "from_state": old, "to_state": case["workflow_state"]})
        self._link(tx, "OPS_HAS_AUDIT", case["entity_id"], audit_id, case["shipment_id"], when)

    def _seed_case(self, tx, source, when):
        identifier = identity("case", source["entity_id"])
        if self._get(tx, "OpsCase", identifier):
            return identifier
        from operations.reasoning import operational_status
        codes=source.get("codes",[])
        status=operational_status(codes)
        row=tx.run("MATCH(s:V2Entity:Shipment {entity_id:$sid,dataset_id:$dataset,split:'development'}) RETURN s.destination_city AS city",
                   sid=source["shipment_id"],dataset=self.dataset_id).single()
        case = self._put(tx, "OpsCase", {"entity_id": identifier, "shipment_id": source["shipment_id"],
            "source_case_id": source["entity_id"], "workflow_state": "OPEN", "operational_status": status,
            "priority": "high" if status in {"CRITICAL","UNRECONCILED_CUSTODY","DELIVERY_DISPUTE"} else "medium",
            "cause_codes": codes, "city": row["city"] if row else "", "opened_at": when,
            "recorded_at": when, "as_of": when, "state_version": 0,
            "issue_summary": "Evidence-derived synthetic shipment exception awaiting investigation."})
        self._link(tx, "OPS_ABOUT", identifier, case["shipment_id"], case["shipment_id"], when)
        self._audit(tx, case, "CASE_OPENED", when, key=source["entity_id"], actor="DEMO-SIMULATOR")
        return identifier

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
            row = tx.run("MATCH (c:V2Entity:Case {dataset_id:$dataset,split:'development'}) RETURN min(c.opened_at) AS time",
                         dataset=self.dataset_id).single()
            initial = public_value(row["time"]) if row and row["time"] else self.config.start_at
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
            initial=self._control(tx)["initial_as_of"]
            rows = tx.run("MATCH (c:V2Entity:Case {dataset_id:$dataset,split:'development'}) "
                          "WHERE c.opened_at <= $clock RETURN properties(c) AS props", dataset=self.dataset_id, clock=instant(initial))
            for row in rows:
                props = public_value(row["props"])
                self._seed_case(tx, props, props["opened_at"])
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
                       "active_case_id": control.get("worker_claim")},
            "simulator": {"state": control["simulator_state"], "speed": control["speed"], "replay_mode":control.get("replay_mode","timeline"), "event_count": control["event_count"],
                          "cursor": {"time": control["cursor_time"], "id": control["cursor_id"]}, "end_at": control["end_at"]},
            "notifications": {"mode": "dry_run", "external_calls": 0}}

    def control(self, component, action, speed=None, actor_id="DEMO-OPERATOR-LOCAL", replay_mode=None):
        require_actor(actor_id)
        if component not in {"worker", "simulator"} or action not in {"start", "pause", "step"}:
            raise OperationsConflict("Invalid demo control")
        if speed is not None and (type(speed) is not int or speed not in SPEEDS):
            raise OperationsConflict("Simulation speed must be 1,10 or60")
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

    def tick(self, seconds=1, *, step=False, manual=False):
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 86400:
            raise OperationsConflict("Invalid bounded simulation advance")
        def replay_tx(tx):
            c = self._control(tx, lock=True)
            if c["simulator_state"] != "running" and not step and not manual:
                return {"events_replayed": 0, "as_of": c["as_of"], "case_ids": []}
            compressed=step or (c["simulator_state"]=="running" and c.get("replay_mode")=="compressed" and not manual)
            target = min(instant(c["as_of"]) + timedelta(seconds=seconds*c["speed"]), instant(c["end_at"]))
            # Step traverses the next recorded event even across a quiet time interval.
            rows = list(tx.run("MATCH (e:V2Entity {dataset_id:$dataset,split:'development'}) "
                "WHERE any(k IN labels(e) WHERE k IN $kinds) "
                "WITH e,CASE WHEN e:Case THEN e.opened_at ELSE e.occurred_at END AS observed_time "
                "WITH e,CASE WHEN e.recorded_at>observed_time THEN e.recorded_at ELSE observed_time END AS time "
                "WHERE (time > $cursor OR (time=$cursor AND e.entity_id>$id)) "
                "AND ($step OR time <= $target) RETURN properties(e) AS props,labels(e) AS labels,time "
                "ORDER BY time,e.entity_id LIMIT 100", dataset=self.dataset_id, kinds=sorted(EVENT_KINDS),
                cursor=instant(c["cursor_time"]), id=c["cursor_id"], target=target, step=compressed))
            case_ids=[]
            for row in rows:
                p=public_value(row["props"]); when=public_value(row["time"])
                sid=p.get("shipment_id") or p.get("holdout_group")
                receipt_id=identity("event",p["entity_id"])
                existing=self._get(tx,"OpsEventReceipt",receipt_id)
                if not existing:
                    self._put(tx,"OpsEventReceipt",{"entity_id":receipt_id,"shipment_id":sid,"source_event_id":p["entity_id"],
                        "event_kind":next(k for k in row["labels"] if k in EVENT_KINDS),"source_occurred_at":p.get("occurred_at",p.get("opened_at",when)),
                        "occurred_at":when,"recorded_at":when})
                    if "Case" in row["labels"]:
                        case_id=self._seed_case(tx,p,when);case_ids.append(case_id)
                    else:
                        cases=list(tx.run("MATCH(c:OpsCase {shipment_id:$sid,dataset_id:$dataset,split:'development'}) RETURN properties(c) AS props",
                                          sid=sid,dataset=self.dataset_id))
                        for item in cases:
                            case=public_value(item["props"])
                            if instant(when)>instant(case["as_of"]):
                                case["as_of"]=when
                                case["state_version"]+=1
                                if "RecipientReport" in row["labels"] and case["workflow_state"]=="RESOLVED":
                                    case.update(workflow_state="REOPENED",state_version=case["state_version"]+1)
                                    self._invalidate_outcomes(tx,case)
                                    self._audit(tx,case,"CASE_REOPENED",when,result="A new attributed recipient report reopens investigation.",actor="DEMO-SIMULATOR")
                                self._put(tx,"OpsCase",case,update=True)
                            self._audit(tx,case,"SIMULATION_EVENT",when,result=next(k for k in row["labels"] if k in EVENT_KINDS),key=p["entity_id"],actor="DEMO-SIMULATOR")
                    c["event_count"]+=1
                c.update(cursor_time=when,cursor_id=p["entity_id"])
            # A full batch retains its last committed timestamp; no unreplayed future becomes visible.
            if rows:c["as_of"]=max(c["as_of"],c["cursor_time"])
            if len(rows)<100 and not compressed:c["as_of"]=target.isoformat()
            self._put(tx,"OpsControl",c,update=True)
            return {"events_replayed":len(rows),"as_of":c["as_of"],"case_ids":case_ids}
        result=self._execute(replay_tx,write=True)
        result["status"]=self.status()
        return result

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
            case.update(workflow_state="INVESTIGATING",state_version=case["state_version"]+1,claim_id=token,claim_at=control["as_of"])
            control.update(worker_claim=case["entity_id"],claim_at=control["as_of"])
            self._put(tx,"OpsCase",case,update=True);self._put(tx,"OpsControl",control,update=True)
            self._audit(tx,case,"CASE_CLAIMED",case["as_of"])
            return case
        case=self._execute(claim,write=True)
        if not case:return {"processed":False,"outcome":None}
        self._reader()
        try:
            context=self.reader.evidence(case["shipment_id"],case["as_of"])
            from operations.reasoning import triage
            baseline=triage(context,self.config)
            precedents=self.reader.historical_precedents(case["shipment_id"],baseline["assessment"]["supported_codes"])
            # One explicit reject/revise fixture per ledger, selected by ordinal before any provider call.
            fixture=self.status()["worker"]["processed_count"]==0
            analysis=analyze(context,self.config,precedents,afl_fixture=fixture)
        except Exception:
            self.control("worker","pause")
            raise
        def finish(tx):
            control=self._control(tx,lock=True);current=self._case(tx,case["entity_id"])
            if current.get("claim_id")!=case["claim_id"] or current["workflow_state"]!="INVESTIGATING":
                raise OperationsConflict("Worker claim was released or superseded")
            if current["state_version"]!=case["state_version"] or current["as_of"]!=case["as_of"]:
                current.update(workflow_state="OPEN",state_version=current["state_version"]+1,claim_id=None,claim_at=None)
                control.update(worker_claim=None,claim_at=None)
                self._put(tx,"OpsCase",current,update=True);self._put(tx,"OpsControl",control,update=True)
                self._audit(tx,current,"CLAIM_RELEASED",control["as_of"],result="Evidence snapshot changed during analysis; retry required.")
                return {"processed":False,"case_id":current["entity_id"],"reason":"snapshot_changed","workflow_state":"OPEN",
                        "state_version":current["state_version"],"outcome":None}
            when=control["as_of"];run_id=identity("run",current["entity_id"],case["claim_id"])
            self._put(tx,"OpsRun",{"entity_id":run_id,"shipment_id":case["shipment_id"],"case_id":case["entity_id"],
                "recorded_at":when,"mode":analysis["mode"],"result_json":canonical(analysis),"iteration":len(analysis["trace"]),
                "status":"REVIEWED","context_hash":analysis["context_hash"]})
            self._link(tx,"OPS_HAS_RUN",case["entity_id"],run_id,case["shipment_id"],when)
            recommendation_id=None
            if analysis["proposal"]:
                proposal=analysis["proposal"];recommendation_id=identity("recommendation",run_id)
                self._put(tx,"OpsRecommendation",{"entity_id":recommendation_id,"shipment_id":case["shipment_id"],
                    "case_id":case["entity_id"],"run_id":run_id,"recorded_at":when,"action_code":proposal["action_code"],
                    "action":proposal["action"],"action_en":proposal.get("action_en",proposal["action"]),
                    "action_ar":proposal.get("action_ar"),"evidence_ids":proposal["evidence_ids"],"status":"PROPOSED","requires_approval":True})
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
            current.update(workflow_state=analysis["result"]["workflow_state"],state_version=current["state_version"]+1,
                last_run_id=run_id,recommendation_id=recommendation_id,claim_id=None,claim_at=None,
                cause_codes=analysis["result"]["operational_labels"],operational_status=analysis["result"]["operational_status"])
            self._put(tx,"OpsCase",current,update=True)
            for event in ("ANALYSIS_STARTED","EVIDENCE_RETRIEVED","CLASSIFICATION","RECOMMENDATION","REVIEW_VERDICT"):
                self._audit(tx,current,event,when,result="Deterministic evidence-only triage; outcome unconfirmed.",old=old)
            if analysis["afl"]["fixture"]:self._audit(tx,current,"AFL_RETRY",when,result="Explicit deterministic hard rejection carried into revised investigation proposal.")
            control.update(worker_claim=None,claim_at=None,processed_count=control["processed_count"]+1)
            self._put(tx,"OpsControl",control,update=True)
            return {"processed":True,"case_id":current["entity_id"],"workflow_state":current["workflow_state"],
                    "state_version":current["state_version"],"run_id":run_id,"mode":analysis["mode"],"afl":analysis["afl"],"outcome":None}
        return self._execute(finish,write=True)

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
                self._put(tx,"OpsExecution",{"entity_id":execution_id,"shipment_id":case["shipment_id"],"case_id":case_id,
                    "decision_id":decision_id,"action_code":recommendation["action_code"],"receipt_ref":"synthetic-demo-receipt:"+execution_id,
                    "status":"ACKNOWLEDGED","mode":"local_demo_no_physical_execution","recorded_at":when,"occurred_at":when})
                self._link(tx,"OPS_INITIATES",decision_id,execution_id,case["shipment_id"],when)
            if execution_id:
                case.update(workflow_state="ACTION_INITIATED",state_version=case["state_version"]+1)
                self._put(tx,"OpsCase",case,update=True)
                self._audit(tx,case,"ACTION_INITIATED",when,actor=actor_id,old=old,
                            result="Synthetic demo receipt; no external logistics action executed.")
            case.update(workflow_state=destination,state_version=case["state_version"]+1)
            self._put(tx,"OpsCase",case,update=True)
            self._audit(tx,case,"OPERATOR_DECISION",when,decision=decision,actor=actor_id,old=old)
            if execution_id:
                self._audit(tx,case,"EXECUTION_ACKNOWLEDGED",when,actor=actor_id,old="ACTION_INITIATED",
                            result="Awaiting independently verified outcome; synthetic acknowledgment only.")
            if decision=="reopen":self._audit(tx,case,"CASE_REOPENED",when,actor=actor_id,old=old)
            if decision=="reopen":self._invalidate_outcomes(tx,case)
            result={"case_id":case_id,"workflow_state":destination,"state_version":case["state_version"],
                "decision_id":decision_id,"execution_id":execution_id,"outcome":None,"idempotent":False}
            self._save_command(tx,case,command,request_hash,"decision",idempotency_key,result,when)
            return result
        return self._execute(decision_tx,write=True)

    def observe_outcome(self,case_id,outcome_type,evidence_ids,success,actor_id,expected_version,idempotency_key):
        require_actor(actor_id)
        detail=self.case_detail(case_id)
        context=self._reader().evidence(detail["shipment_id"],detail["as_of"])
        validate_observation(context,evidence_ids,outcome_type,success)
        def observe_tx(tx):
            control=self._control(tx,lock=True);case=self._case(tx,case_id)
            payload={"outcome_type":outcome_type,"evidence_ids":evidence_ids,"success":success,"actor_id":actor_id,"expected_version":expected_version}
            command,request_hash,replay=self._command(tx,case,"observe",idempotency_key,payload)
            if replay:return replay
            require_version(case,expected_version)
            if case["workflow_state"]!="AWAITING_OUTCOME":raise OperationsConflict("Observation requires an initiated action")
            executions=list(tx.run("MATCH(e:OpsExecution {case_id:$case_id,dataset_id:$dataset}) RETURN properties(e) AS props ORDER BY e.recorded_at DESC,e.entity_id DESC LIMIT 1",case_id=case_id,dataset=self.dataset_id))
            if not executions:raise OperationsConflict("Action receipt missing")
            execution=public_value(executions[0]["props"]);when=control["as_of"];outcome_id=identity("outcome",command)
            self._put(tx,"OpsOutcome",{"entity_id":outcome_id,"shipment_id":case["shipment_id"],"case_id":case_id,
                "execution_id":execution["entity_id"],"action_code":execution["action_code"],"outcome_type":outcome_type,
                "success":success,"evidence_ids":evidence_ids,"verification_status":"OBSERVED","invalidated":False,
                "recorded_at":when,"occurred_at":when,"observed_at":when})
            self._link(tx,"OPS_HAS_OUTCOME",execution["entity_id"],outcome_id,case["shipment_id"],when)
            case["state_version"]+=1;self._put(tx,"OpsCase",case,update=True)
            self._audit(tx,case,"OUTCOME_OBSERVED",when,actor=actor_id,result="Observation is unverified; case remains awaiting outcome.")
            result={"case_id":case_id,"workflow_state":case["workflow_state"],"state_version":case["state_version"],"outcome_id":outcome_id,"verification_status":"OBSERVED","idempotent":False}
            self._save_command(tx,case,command,request_hash,"observe",idempotency_key,result,when);return result
        return self._execute(observe_tx,write=True)

    def verify_outcome(self,case_id,outcome_id,actor_id,expected_version,idempotency_key,authority="LOCAL_DEMO_OPERATOR"):
        require_actor(actor_id,authority)
        detail=self.case_detail(case_id);context=self._reader().evidence(detail["shipment_id"],detail["as_of"])
        def verify_tx(tx):
            control=self._control(tx,lock=True);case=self._case(tx,case_id)
            payload={"outcome_id":outcome_id,"actor_id":actor_id,"expected_version":expected_version,"authority":authority}
            command,request_hash,replay=self._command(tx,case,"verify",idempotency_key,payload)
            if replay:return replay
            require_version(case,expected_version)
            if case["workflow_state"]!="AWAITING_OUTCOME":raise OperationsConflict("Verification requires awaiting outcome")
            outcome=self._get(tx,"OpsOutcome",outcome_id)
            if not outcome or outcome["case_id"]!=case_id:raise OperationsConflict("Outcome does not belong to this case")
            execution=self._get(tx,"OpsExecution",outcome["execution_id"])
            verified=verify(context,self.config,outcome,execution,actor_id,authority);when=control["as_of"]
            outcome.update(verification_status="VERIFIED",verified_at=when,verifier_id=actor_id,provenance="VERIFIED_OUTCOME")
            self._put(tx,"OpsOutcome",outcome,update=True)
            old=case["workflow_state"];case.update(workflow_state=verified["workflow_state"],state_version=case["state_version"]+1)
            if verified["resolved"]:case["operational_status"]="RESOLVED"
            self._put(tx,"OpsCase",case,update=True);self._audit(tx,case,"OUTCOME_VERIFIED",when,actor=actor_id,old=old)
            if verified["resolved"]:
                self._audit(tx,case,"CASE_RESOLVED",when,actor=actor_id,old=old)
                notification_id=identity("notification",outcome_id)
                self._put(tx,"OpsNotification",{"entity_id":notification_id,"shipment_id":case["shipment_id"],"case_id":case_id,
                    "recorded_at":when,"trigger":"case_resolved","mode":"dry_run","status":"DRY_RUN","external_calls":0})
                self._link(tx,"OPS_NOTIFIED",case_id,notification_id,case["shipment_id"],when)
                self._audit(tx,case,"NOTIFICATION_RESULT",when,result="Dry run only; zero external sends.",actor=actor_id)
            result={"case_id":case_id,"workflow_state":case["workflow_state"],"state_version":case["state_version"],
                "outcome_id":outcome_id,"verification_status":"VERIFIED","resolved":verified["resolved"],"idempotent":False}
            self._save_command(tx,case,command,request_hash,"verify",idempotency_key,result,when);return result
        return self._execute(verify_tx,write=True)

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
