"""Actual store/reducer paths on a transactional in-memory Neo4j port; no sockets."""
import copy
import json
import re
import threading
import unittest
from datetime import timedelta
from types import SimpleNamespace

from dataset_v2.contracts import Config, canonical, digest, instant
from dataset_v2.generate import generate
from operations.lifecycle import OperationsConflict, decision_state, require_version
from operations.store import OperationsStore, CONTROL_ID, temporal_properties
from operations.reasoning import public_evidence
from operations.simulator import replay_plan
from operations.worker import analyze
from operations.outcome import validate_observation, verify
from dataset_v2.derive import proof_assessment
from operations.reasoning import evidence_world


class Result(list):
    def single(self): return self[0] if self else None
    def consume(self): return SimpleNamespace(counters=SimpleNamespace(nodes_created=0,relationships_created=0))


class Tx:
    def __init__(self, driver, ledger):self.driver,self.ledger=driver,ledger
    def run(self,q,**p):
        self.driver.queries.append(q)
        if "(m:_V2Import)" in q:return Result([{"props":self.driver.marker}])
        if q.startswith("MATCH (s:V2Entity:Shipment"):
            node=self.driver.world.nodes.get(p["id"])
            return Result([{"id":node.id}]) if node and node.properties.get("split")=="development" else Result()
        if q.startswith("MATCH(s:V2Entity:Shipment"):
            node=self.driver.world.nodes[p["sid"]];return Result([{"city":node.properties.get("destination_city")}])
        if q.startswith("MATCH (c:V2Entity:Case"):
            cases=[n for n in self.driver.world.of_kind("Case") if n.properties["split"]=="development"]
            if "min(c.opened_at)" in q:return Result([{"time":min((instant(n.properties["opened_at"]) for n in cases),default=None)}])
            return Result([{"props":temporal_properties(n.properties)} for n in cases if instant(n.properties["opened_at"])<=p["clock"]])
        if q.startswith("MATCH (c:OpsEntity:OpsControl") and "SET" in q:
            self.ledger[p["id"]][1]["state_version"]+=1;return Result()
        if q.startswith("MERGE (n:OpsEntity:"):
            kind=q.split("MERGE (n:OpsEntity:")[1].split(" ")[0]
            if "ON CREATE" in q and p["id"] in self.ledger:return Result()
            prior=self.ledger.get(p["id"],(kind,{}))[1]
            prior.update(copy.deepcopy(p["props"]))
            prior={k:v for k,v in prior.items() if v is not None}
            self.ledger[p["id"]]=(kind,prior);return Result()
        if q.startswith("MATCH (a:OpsEntity") and "MERGE" in q:return Result()
        if q.startswith("MATCH (n:OpsEntity:") and "$id" in q:
            kind=q.split("MATCH (n:OpsEntity:")[1].split(" ")[0]
            row=self.ledger.get(p["id"])
            return Result([{"props":copy.deepcopy(row[1])}]) if row and row[0]==kind else Result()
        if q.startswith("MATCH(n:OpsEntity:"):
            kind=q.split("MATCH(n:OpsEntity:")[1].split(" ")[0]
            rows=[copy.deepcopy(v) for k,v in self.ledger.values() if k==kind and v.get("case_id")==p["case_id"]]
            rows.sort(key=lambda v:(v.get("iteration",0) if "n.iteration" in q else 0,v["recorded_at"],v["entity_id"]),reverse=True)
            return Result([{"props":r} for r in rows[:20]])
        if q.startswith("MATCH(e:OpsExecution"):
            rows=[v for k,v in self.ledger.values() if k=="OpsExecution" and v["case_id"]==p["case_id"]]
            return Result([{"props":copy.deepcopy(r)} for r in sorted(rows,key=lambda r:r["recorded_at"],reverse=True)[:1]])
        if q.startswith("MATCH(c:OpsCase"):
            rows=[v for k,v in self.ledger.values() if k=="OpsCase"]
            if "c.workflow_state IN" in q:
                rows=[v for v in rows if v["workflow_state"] in {"OPEN","REOPENED"} and v["opened_at"]<=p["clock"] and (p["id"] is None or v["entity_id"]==p["id"])]
                rows=sorted(rows,key=lambda r:(r["opened_at"],r["entity_id"]))[:1]
            else:rows=[v for v in rows if v["shipment_id"]==p["sid"]]
            return Result([{"props":copy.deepcopy(r)} for r in rows])
        if q.startswith("MATCH (e:V2Entity"):
            events=[]
            for n in self.driver.world.nodes.values():
                if n.kind not in p["kinds"] or n.properties.get("split")!="development":continue
                when=max(instant(n.properties["opened_at"] if n.kind=="Case" else n.properties["occurred_at"]),instant(n.properties["recorded_at"]))
                if (when,n.id)>(p["cursor"],p["id"]) and (p["step"] or when<=p["target"]):
                    events.append({"props":temporal_properties(n.properties),"labels":[n.kind],"time":when})
            return Result(sorted(events,key=lambda r:(r["time"],r["props"]["entity_id"]))[:100])
        raise AssertionError("Unhandled fixed store query: "+q)


class Driver:
    def __init__(self,world):
        self.world=world;self.ledger={};self.lock=threading.RLock();self.queries=[];self.databases=[]
        self.marker={"state":"COMPLETE","manifest_json":canonical(world.manifest()),"manifest_hash":digest(world.manifest())}
    def session(self,**options):self.databases.append(options["database"]);return self
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def run(self,q,**p):
        if q.startswith("CREATE "):self.queries.append(q);return Result()
        return Tx(self,self.ledger).run(q,**p)
    def execute_read(self,fn):
        with self.lock:return fn(Tx(self,self.ledger))
    def execute_write(self,fn):
        with self.lock:
            candidate=copy.deepcopy(self.ledger);result=fn(Tx(self,candidate));self.ledger=candidate;return result


class Reader:
    def __init__(self,world):self.world=world
    def evidence(self,sid,as_of):return public_evidence(self.world,sid,as_of)
    def historical_precedents(self,sid,codes):return []


class StoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.world=generate(Config(total=90))
    def make(self):
        d=Driver(self.world);s=OperationsStore(d,"shipments-v2-demo",self.world.config.dataset_id,self.world.config,Reader(self.world))
        s.initialize();return s,d
    def processed(self):
        store,driver=self.make();result=store.process_one(manual=True)
        self.assertTrue(result["processed"]);return store,driver,result
    def test_manifest_fence_and_development_only_no_base_writes(self):
        store,driver=self.make();before=canonical(self.world.manifest())
        driver.marker["state"]="LOADING"
        with self.assertRaises(OperationsConflict):store.control("worker","start")
        self.assertEqual(canonical(self.world.manifest()),before)
        self.assertEqual(set(driver.databases),{"shipments-v2-demo"})
        self.assertFalse(any(re.search(r"(?:SET|MERGE|CREATE).*V2Entity",q) for q in driver.queries))
        self.assertTrue(all(p["synthetic"] and p["split"]=="development" for _,p in driver.ledger.values()))
    def test_worker_review_fixture_carries_feedback_and_cannot_resolve(self):
        store,driver,result=self.processed();detail=store.case_detail(result["case_id"])
        self.assertIsNone(result["outcome"]);self.assertNotEqual(detail["workflow_state"],"RESOLVED")
        trace=detail["run"]["result"]["trace"]
        self.assertEqual(trace[0]["review"]["verdict"],"reject")
        self.assertEqual(trace[-1]["feedback_received"],trace[0]["review"]["feedback"])
        self.assertEqual(detail["review"]["verdict"],trace[-1]["review"]["verdict"])
        self.assertEqual(store.process_one(case_id=result["case_id"])["processed"],False)

    def test_initialize_is_idempotent_and_does_not_reset_committed_progress(self):
        store,driver=self.make();store.control("simulator","start",speed=60);store.tick(seconds=86400)
        before=store.status();store.initialize();after=store.status()
        self.assertEqual(after,before)
        self.assertEqual(sum(kind=="OpsControl" for kind,_ in driver.ledger.values()),1)

    def test_sequential_claim_rejects_parallel_processing_and_stale_snapshot_requeues(self):
        store,driver=self.make();original=store.reader.evidence; nested=[]
        def changing_evidence(sid,as_of):
            nested.append(store.process_one(manual=True))
            def mutate(tx):
                case=next(p for kind,p in tx.ledger.values() if kind=="OpsCase" and p["workflow_state"]=="INVESTIGATING")
                case["state_version"]+=1
                case["as_of"]=case["as_of"]+timedelta(seconds=1)
            driver.execute_write(mutate)
            return original(sid,as_of)
        store.reader.evidence=changing_evidence
        result=store.process_one(manual=True)
        self.assertFalse(nested[0]["processed"])
        self.assertFalse(result["processed"]);self.assertEqual(result["reason"],"snapshot_changed")
        self.assertIsNone(store.status()["worker"]["active_case_id"])
        self.assertEqual(sum(kind=="OpsRun" for kind,_ in driver.ledger.values()),0)
        store.reader.evidence=original
        self.assertTrue(store.process_one(case_id=result["case_id"])["processed"])
    def test_decision_idempotence_stale_version_and_approval_unresolved(self):
        store,driver,result=self.processed();case=store.case_detail(result["case_id"])
        approved=store.decide(case["case_id"],"approve","DEMO-OPERATOR-LOCAL",case["state_version"],"approve-one")
        self.assertEqual(approved["workflow_state"],"AWAITING_OUTCOME");self.assertIsNone(approved["outcome"])
        replay=store.decide(case["case_id"],"approve","DEMO-OPERATOR-LOCAL",case["state_version"],"approve-one")
        self.assertTrue(replay["idempotent"]);self.assertEqual(replay["execution_id"],approved["execution_id"])
        with self.assertRaises(OperationsConflict):store.decide(case["case_id"],"reject","DEMO-OPERATOR-LOCAL",case["state_version"],"different")
        with self.assertRaises(OperationsConflict):store.decide(case["case_id"],"reject","DEMO-OPERATOR-LOCAL",case["state_version"],"approve-one")
        self.assertEqual(sum(kind=="OpsExecution" for kind,_ in driver.ledger.values()),1)
        events={p["event_type"]:p for kind,p in driver.ledger.values() if kind=="OpsAudit"}
        self.assertEqual(events["RECOMMENDATION_READY"]["to_state"],"RECOMMENDATION_READY")
        self.assertEqual(events["ACTION_INITIATED"]["to_state"],"ACTION_INITIATED")
        self.assertEqual(events["EXECUTION_ACKNOWLEDGED"]["to_state"],"AWAITING_OUTCOME")
    def test_observed_and_verified_failure_stays_unresolved_and_authority_is_required(self):
        store,driver,result=self.processed();case=store.case_detail(result["case_id"])
        approved=store.decide(case["case_id"],"approve","DEMO-OPERATOR-LOCAL",case["state_version"],"approve")
        evidence=store.reader.evidence(case["shipment_id"],case["as_of"])
        ids=[node["id"] for node in evidence["nodes"] if node["kind"]=="CustodyEvent"][:1]
        observed=store.observe_outcome(case["case_id"],"insufficient_evidence",ids,False,"DEMO-OPERATOR-LOCAL",approved["state_version"],"observe")
        self.assertEqual(observed["verification_status"],"OBSERVED")
        with self.assertRaises(OperationsConflict):store.verify_outcome(case["case_id"],observed["outcome_id"],"AI",observed["state_version"],"bad")
        verified=store.verify_outcome(case["case_id"],observed["outcome_id"],"DEMO-OPERATOR-LOCAL",observed["state_version"],"verify")
        self.assertFalse(verified["resolved"]);self.assertEqual(verified["workflow_state"],"HUMAN_REVIEW")
        self.assertEqual(store.status()["notifications"]["external_calls"],0)
    def test_simulation_replay_cursor_is_committed_idempotent_and_speed_validated(self):
        store,driver=self.make();store.control("simulator","start",speed=60)
        before=store.status();first=store.tick(seconds=86400);second=store.tick(seconds=86400)
        self.assertGreater(first["events_replayed"],0)
        receipts=[p["source_event_id"] for kind,p in driver.ledger.values() if kind=="OpsEventReceipt"]
        self.assertEqual(len(receipts),len(set(receipts)))
        self.assertEqual(len(receipts),store.status()["simulator"]["event_count"])
        self.assertGreaterEqual(store.status()["as_of"],before["as_of"])
        for speed in (0,2,True,100):
            with self.assertRaises(OperationsConflict):store.control("simulator","start",speed=speed)
        self.assertTrue(any("WHERE (time > $cursor OR" in q for q in driver.queries))
    def test_pure_cursor_bounds_and_missing_grounding_rejection(self):
        rows=[{"time":"2026-09-01T00:00:00+00:00","id":str(i)} for i in range(3)]
        planned=replay_plan(rows,{"time":rows[0]["time"],"id":"0"},rows[0]["time"],1)
        self.assertEqual(planned,[rows[1]])
        for state in ("OPEN","INVESTIGATING","AWAITING_OUTCOME"):
            with self.assertRaises(OperationsConflict):decision_state(state,"approve")
        with self.assertRaises(OperationsConflict):require_version({"state_version":2},1)
    def test_outcome_rejects_foreign_ids_and_unresolved_success(self):
        store,_,result=self.processed();case=store.case_detail(result["case_id"]);context=store.reader.evidence(case["shipment_id"],case["as_of"])
        with self.assertRaises(OperationsConflict):validate_observation(context,["DEMO-FOREIGN"],"delivery_verified",True)
        with self.assertRaises(OperationsConflict):validate_observation(context,[context["nodes"][0]["id"]],"dispute_unresolved",True)

    def test_delivery_verification_requires_every_package_and_correct_action(self):
        candidate=None
        for shipment in self.world.of_kind("Shipment"):
            if shipment.properties["split"]!="development":continue
            context=public_evidence(self.world,shipment.id,self.world.config.as_of)
            world=evidence_world(context,self.world.config)
            packages=[node for node in world.nodes.values() if node.kind=="Package"]
            proofs=[node for node in world.nodes.values() if node.kind=="DeliveryProof"]
            assessments=[proof_assessment(world,node,instant(context["as_of"])) for node in proofs]
            if len(packages)>1 and len(proofs)==len(packages) and all(row["corroborated"] for row in assessments):
                candidate=(shipment,context,proofs,assessments);break
        self.assertIsNotNone(candidate,"Need real generated multi-package proof evidence")
        shipment,context,proofs,assessments=candidate
        evidence=sorted({identifier for row in assessments for identifier in row["evidence_ids"]})
        outcome={"outcome_type":"delivery_verified","success":True,"evidence_ids":evidence,
                 "verification_status":"OBSERVED","invalidated":False}
        # Explicit authority fixture, not a claim this healthy shipment had an operational Case.
        execution={"receipt_ref":"synthetic-confirmed","status":"ACKNOWLEDGED","action_code":"JOURNEY_DELAY",
                   "occurred_at":(min(instant(node.properties["occurred_at"]) for node in proofs)-timedelta(minutes=1)).isoformat()}
        self.assertTrue(verify(context,self.world.config,outcome,execution,"DEMO-OPERATOR-LOCAL","LOCAL_DEMO_OPERATOR")["resolved"])
        with self.assertRaises(OperationsConflict):
            verify(context,self.world.config,{**outcome,"evidence_ids":assessments[0]["evidence_ids"]},execution,"DEMO-OPERATOR-LOCAL","LOCAL_DEMO_OPERATOR")
        with self.assertRaises(OperationsConflict):
            verify(context,self.world.config,outcome,{**execution,"action_code":"ADDRESS_CONFLICT"},"DEMO-OPERATOR-LOCAL","LOCAL_DEMO_OPERATOR")

    def test_reopening_invalidates_prior_verified_outcome(self):
        store,driver,result=self.processed();case=store.case_detail(result["case_id"])
        def prepare(tx):
            p=tx.ledger[case["case_id"]][1];p["workflow_state"]="RESOLVED"
            tx.ledger["DEMO-OPS-OLD-OUTCOME"]=("OpsOutcome",{"entity_id":"DEMO-OPS-OLD-OUTCOME","case_id":case["case_id"],
                "shipment_id":case["shipment_id"],"dataset_id":store.dataset_id,"synthetic":True,"split":"development",
                "holdout_group":case["shipment_id"],"recorded_at":instant(case["as_of"]),"verification_status":"VERIFIED","invalidated":False})
        driver.execute_write(prepare)
        reopened=store.decide(case["case_id"],"reopen","DEMO-OPERATOR-LOCAL",case["state_version"],"reopen")
        self.assertEqual(reopened["workflow_state"],"REOPENED")
        self.assertTrue(driver.ledger["DEMO-OPS-OLD-OUTCOME"][1]["invalidated"])


if __name__=="__main__":unittest.main()
