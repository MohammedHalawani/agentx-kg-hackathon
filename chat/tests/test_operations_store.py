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
from dataset_v2.derive import proof_assessment
from operations.reasoning import evidence_world


class Result(list):
    def single(self): return self[0] if self else None
    def consume(self): return SimpleNamespace(counters=SimpleNamespace(nodes_created=0,relationships_created=0))


class Tx:
    def __init__(self, driver, ledger):self.driver,self.ledger=driver,ledger
    def run(self,q,**p):
        self.driver.queries.append(q)
        if "min(e.occurred_at)" in q:
            times=[instant(n.properties["occurred_at"]) for n in self.driver.world.nodes.values()
                   if n.properties.get("split")=="development" and n.properties.get("occurred_at")]
            return Result([{"start":min(times)}])
        if "DETACH DELETE" in q:
            keys=[k for k,(kind,_) in self.ledger.items() if kind!="OpsControl"]
            for key in keys:del self.ledger[key]
            return Result([{"deleted":len(keys)}])
        if q.startswith("MATCH (m:V2Entity:ExpectedMilestone") or q.startswith("MATCH (s:V2Entity:DeliverySession"):
            kind,field,extra=("ExpectedMilestone","latest_at",0) if "ExpectedMilestone" in q else ("DeliverySession","end_at",60)
            sids=set()
            for n in self.driver.world.of_kind(kind):
                if n.properties.get("split")!="development":continue
                due=instant(n.properties[field])+timedelta(seconds=(n.properties.get("grace_seconds") or 0)+p.get("allowance",0)+extra)
                if p["previous"]<due<=p["now"]:sids.add(n.properties["shipment_id"])
            return Result([{"sid":x} for x in sorted(sids)])
        if q.startswith("MATCH(c:OpsEntity:OpsCase {dataset_id:$dataset,split:'development',workflow_state:'AWAITING_OUTCOME'})"):
            out=[]
            for k,v in self.ledger.values():
                if k!="OpsCase" or v["workflow_state"]!="AWAITING_OUTCOME" or (p.get("case_id") and v["entity_id"]!=p["case_id"]):continue
                ex=[e for kk,e in self.ledger.values() if kk=="OpsExecution" and e["case_id"]==v["entity_id"] and e.get("status")=="ACKNOWLEDGED"]
                for e in ex:
                    if p.get("force") or v.get("outcome_checked_as_of") is None or v["as_of"]>v["outcome_checked_as_of"] or e["deadline_at"]<=p["clock"]:
                        out.append({"case":copy.deepcopy(v),"execution":copy.deepcopy(e)})
            return Result(sorted(out,key=lambda r:str(r["case"]["as_of"]))[:p["limit"]])
        if q.startswith("MATCH(e:OpsEntity:OpsExecution {dataset_id:$dataset,status:'"):
            status=q.split("status:'")[1].split("'")[0]
            rows=sorted((copy.deepcopy(v) for k,v in self.ledger.values() if k=="OpsExecution" and v.get("status")==status),
                        key=lambda e:(str(e["recorded_at"]),e["entity_id"]))
            return Result([{"e":r} for r in rows[:p.get("limit",1000)]])
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
    def historical_precedents(self,sid,codes,as_of=None):return []
    def precedents(self,sid,codes,as_of=None):return []


def development_reset(store, actor="DEMO-OPERATOR-LOCAL"):
    """Tests reset the ledger explicitly: the development flag on for this call only, with the current confirmation."""
    import os
    from unittest import mock
    with mock.patch.dict(os.environ, {"SUHAIL_DEV_RESET": "1"}):
        return store.reset_session(actor, confirmation=store.reset_confirmation())


def approval_policy(decided=("APPROVAL_REQUIRED","Action changes destination or service; operator authorization required.")):
    """While an investigation runs: the authority decision forced to `decided` and no symptom floor, so a test can put
    an agent-investigated case in front of a person. Approval and dispatch recompute authority with the real policy."""
    from contextlib import ExitStack
    from unittest import mock
    stack=ExitStack()
    stack.enter_context(mock.patch("operations.authority.authorize",return_value=decided))
    stack.enter_context(mock.patch("operations.authority.symptom_floor",side_effect=lambda risk,reason,action_type,symptoms:(risk,reason,"AUTO")))
    return stack


def agent_investigator(verdicts=("ACCEPT",),cause="BARCODE_MISMATCH",action="REQUEST_RESCAN"):
    """A scripted GPT-OSS investigator and reviewer over the real tools (no provider)."""
    from tests import test_investigator as ti
    fake=ti.FakeInvestigator(lambda tools:[("shipment_overview",{})],list(verdicts))
    fake.cause,fake.action=cause,action
    return fake


class Acknowledging:
    """A field system that accepts every request and reports nothing back."""
    def respond(self,execution,now):return {"acknowledged":True,"behaviour":"Request accepted."}


class StoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.world=generate(Config(total=90))
    def make(self,rounds=12):
        """Cases exist only once the monitor has opened them from replayed, visible evidence."""
        d=Driver(self.world);s=OperationsStore(d,"shipments-v2-demo",self.world.config.dataset_id,self.world.config,Reader(self.world))
        s.initialize();development_reset(s)
        for _ in range(rounds):
            s.tick(seconds=86400,manual=True,speed=60)
            while s.status()["session"]["monitor_pending"]:s.monitor_step()
            if any(kind=="OpsCase" for kind,_ in d.ledger.values()):break
        return s,d
    def processed(self):
        """Rules only (no investigator): its proposal is informational and never executable by approval."""
        store,driver=self.make();result=store.process_one(manual=True)
        self.assertTrue(result["processed"]);return store,driver,result
    def approvable(self,**agent):
        """An agent-investigated, reviewed case awaiting a person's approval of an evidence request."""
        store,driver=self.make();store.agents=agent_investigator(**agent)
        with approval_policy():result=store.process_one(manual=True)
        self.assertTrue(result["processed"]);self.assertEqual(result["workflow_state"],"AWAITING_APPROVAL")
        return store,driver,result
    def test_manifest_fence_and_development_only_no_base_writes(self):
        store,driver=self.make();before=canonical(self.world.manifest())
        driver.marker["state"]="LOADING"
        with self.assertRaises(OperationsConflict):store.control("worker","start")
        self.assertEqual(canonical(self.world.manifest()),before)
        self.assertEqual(set(driver.databases),{"shipments-v2-demo"})
        self.assertFalse(any(re.search(r"(?:SET|MERGE|CREATE).*V2Entity",q) for q in driver.queries))
        self.assertTrue(all(p["synthetic"] and p["split"]=="development" for _,p in driver.ledger.values()))
    def test_first_investigation_is_not_a_scripted_rehearsal_and_cannot_resolve(self):
        store,driver,result=self.processed();detail=store.case_detail(result["case_id"])
        self.assertIsNone(result["outcome"]);self.assertNotEqual(detail["workflow_state"],"RESOLVED")
        trace=detail["run"]["result"]["trace"]
        # No injected GPS-delivery proposal or forced rejection: the first trace entry is the real proposal.
        self.assertNotIn("MARK_DELIVERED_FROM_GPS",canonical(trace))
        self.assertNotIn("fixture",detail["run"]["result"]["afl"])
        self.assertFalse(any(v["event_type"]=="AFL_RETRY" for kind,v in driver.ledger.values() if kind=="OpsAudit"))
        self.assertEqual(detail["review"]["verdict"],trace[-1]["review"]["verdict"])
        self.assertEqual(store.process_one(case_id=result["case_id"])["processed"],False)

    def test_initialize_is_idempotent_and_does_not_reset_committed_progress(self):
        store,driver=self.make();store.control("simulator","start",speed=60);store.tick(seconds=86400)
        before=store.status();store.initialize();after=store.status()
        self.assertEqual(after,before)
        self.assertEqual(sum(kind=="OpsControl" for kind,_ in driver.ledger.values()),1)

    def test_committed_stage_stream_matches_persistent_audit_and_releases_subscribers(self):
        store,driver=self.make()
        case_id=next(v['entity_id'] for kind,v in driver.ledger.values() if kind=='OpsCase')
        listener=store.subscribe_pipeline(case_id)
        result=store.process_one(case_id=case_id)
        states=[]
        while not listener.empty():states.append(listener.get_nowait())
        events=store.pipeline_state(case_id)['events']
        self.assertEqual([s['events'][-1]['sequence'] for s in states[:-1]],list(range(1,len(events)+1)))
        self.assertEqual(states[0]['events'][-1]['status'],'RUNNING')
        self.assertEqual(states[-1]['status'],'REVIEWED')
        self.assertEqual(states[-1]['workflow_state'],result['workflow_state'])
        audits=[v for kind,v in driver.ledger.values() if kind=='OpsAudit' and v.get('event_type')=='PIPELINE_STAGE']
        self.assertEqual([(v['sequence'],v['stage'],v['stage_status'],v['wall_recorded_at']) for v in sorted(audits,key=lambda v:v['sequence'])],
                         [(e['sequence'],e['stage'],e['status'],e['recorded_at']) for e in events])
        store.unsubscribe_pipeline(case_id,listener)
        self.assertFalse(store._subscribers)

    def test_pending_reanalysis_is_explicit_versioned_and_distinct_from_reopening(self):
        store,driver,result=self.approvable()
        case=store.case_detail(result['case_id'])
        requested=store.request_reanalysis(case['case_id'],'DEMO-OPERATOR-LOCAL',case['state_version'],'reanalyze_01')
        self.assertEqual(requested['workflow_state'],'OPEN')
        self.assertTrue(store.request_reanalysis(case['case_id'],'DEMO-OPERATOR-LOCAL',case['state_version'],'reanalyze_01')['idempotent'])
        with approval_policy():self.assertTrue(store.process_one(case_id=case['case_id'])['processed'])
        self.assertEqual(sum(k=='OpsRun' for k,_ in driver.ledger.values()),2)
        latest=store.case_detail(case['case_id'])
        with self.assertRaises(OperationsConflict):store.decide(case['case_id'],'reopen','DEMO-OPERATOR-LOCAL',latest['state_version'],'reopen_active')
        with self.assertRaises(OperationsConflict):store.request_reanalysis(case['case_id'],'DEMO-OPERATOR-LOCAL',case['state_version'],'stale_analysis')
        approved=store.decide(case['case_id'],'approve','DEMO-OPERATOR-LOCAL',latest['state_version'],'approve_pending')
        with self.assertRaises(OperationsConflict):store.request_reanalysis(case['case_id'],'DEMO-OPERATOR-LOCAL',approved['state_version'],'during_outcome')

    def test_human_review_does_not_block_automatic_next_case(self):
        store,driver,first=self.processed()
        driver.ledger[first['case_id']][1]['workflow_state']='HUMAN_REVIEW'
        store.control('simulator','start',speed=60)
        for _ in range(12):
            store.tick(seconds=86400)
            while store.status()["session"]["monitor_pending"]:store.monitor_step()
        store.control('simulator','pause')
        store.control('worker','start')
        second=store.process_one()
        self.assertTrue(second['processed'])
        self.assertNotEqual(second['case_id'],first['case_id'])
        self.assertEqual(store.case_detail(first['case_id'])['workflow_state'],'HUMAN_REVIEW')
        self.assertEqual(store.status()['worker']['state'],'running')
        store.control('worker','pause')

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
        # A superseded snapshot keeps its real investigation trace, but records
        # no accepted writeback and releases the case for a new claim.
        self.assertEqual([p['status'] for kind,p in driver.ledger.values() if kind=='OpsRun'],['ABORTED'])
        store.reader.evidence=original
        self.assertTrue(store.process_one(case_id=result["case_id"])["processed"])
    def test_decision_idempotence_stale_version_and_approval_unresolved(self):
        store,driver,result=self.approvable();case=store.case_detail(result["case_id"])
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
        self.assertEqual(events["EXECUTION_REQUESTED"]["to_state"],"AWAITING_OUTCOME")
        execution=next(v for kind,v in driver.ledger.values() if kind=="OpsExecution")
        self.assertEqual((execution["status"],execution["authority"]),("AUTHORIZED","OPERATOR_APPROVAL"))  # Approval is not execution.
        self.assertEqual(store.execute_step(),[execution["entity_id"]])
        executed=next(v for kind,v in driver.ledger.values() if kind=="OpsExecution")
        # No adapter: nothing was sent, so nothing can be verified and a person takes the case.
        self.assertEqual((executed["status"],executed["mode"]),("NOT_ACKNOWLEDGED","no_adapter"))
        self.assertEqual(store.case_detail(case["case_id"])["workflow_state"],"HUMAN_REVIEW")
        self.assertEqual(store.execute_step(),[])  # Exactly once.
    def test_operator_cannot_declare_success_only_the_verifier_decides(self):
        store,driver,result=self.approvable();case=store.case_detail(result["case_id"])
        approved=store.decide(case["case_id"],"approve","DEMO-OPERATOR-LOCAL",case["state_version"],"approve")
        store.adapter=Acknowledging()
        store.execute_step()
        current=store.case_detail(case["case_id"])
        with self.assertRaises(TypeError):
            store.request_verification(case["case_id"],"DEMO-OPERATOR-LOCAL",current["state_version"],"verify-now",success=True)
        with self.assertRaises(OperationsConflict):store.request_verification(case["case_id"],"AI",current["state_version"],"verify-ai")
        checked=store.request_verification(case["case_id"],"DEMO-OPERATOR-LOCAL",current["state_version"],"verify-now")
        self.assertNotEqual(checked["workflow_state"],"RESOLVED")  # No action-relevant evidence arrived after execution.
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
    def test_paused_manual_replay_persists_selected_settings_without_starting_background(self):
        store,driver=self.make()
        result=store.tick(seconds=60,manual=True,speed=10,replay_mode="compressed")
        self.assertGreater(result["events_replayed"],0)
        status=store.status()["simulator"]
        self.assertEqual(status["state"],"paused")
        self.assertEqual(status["speed"],10)
        self.assertEqual(status["replay_mode"],"compressed")
        self.assertLessEqual(result["events_replayed"],100)
        with self.assertRaises(OperationsConflict):store.tick(manual=True,speed=True)

    def test_pure_cursor_bounds_and_missing_grounding_rejection(self):
        rows=[{"time":"2026-09-01T00:00:00+00:00","id":str(i)} for i in range(3)]
        planned=replay_plan(rows,{"time":rows[0]["time"],"id":"0"},rows[0]["time"],1)
        self.assertEqual(planned,[rows[1]])
        for state in ("OPEN","INVESTIGATING","AWAITING_OUTCOME"):
            with self.assertRaises(OperationsConflict):decision_state(state,"approve")
        with self.assertRaises(OperationsConflict):require_version({"state_version":2},1)
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


class LiveSessionTests(unittest.TestCase):
    """Fresh-case runtime: only the monitor opens cases, from evidence visible at the scenario clock."""
    @classmethod
    def setUpClass(cls):cls.world=generate(Config(total=90))
    def live(self):
        d=Driver(self.world);s=OperationsStore(d,"shipments-v2-demo",self.world.config.dataset_id,self.world.config,Reader(self.world))
        s.initialize();development_reset(s);return s,d
    def cases(self,d):return [v for k,v in d.ledger.values() if k=="OpsCase"]
    def run_world(self,s,rounds=400):
        for _ in range(rounds):
            r=s.tick(seconds=86400,manual=True,speed=60)
            while s.status()["session"]["monitor_pending"]:s.monitor_step()
            if not r["events_replayed"] and s.status()["as_of"]>=s.status()["simulator"]["end_at"]:break

    def test_reset_starts_empty_before_first_event_and_keeps_v2_evidence(self):
        s,d=self.live()
        status=s.status()
        self.assertEqual(status["session"]["case_source"],"monitor")
        self.assertEqual(self.cases(d),[])
        self.assertEqual(status["worker"]["processed_count"],0)
        first=min(instant(n.properties["occurred_at"]) for n in self.world.nodes.values()
                  if n.properties.get("split")=="development" and n.properties.get("occurred_at"))
        self.assertLess(instant(status["as_of"]),first)
        s.initialize();self.assertEqual(self.cases(d),[])  # Restart never re-seeds dataset cases.

    def test_monitor_opens_cases_only_from_visible_exceptions_never_dataset_labels(self):
        from dataset_v2.derive import assess_shipment
        s,d=self.live();self.run_world(s)
        opened=self.cases(d)
        self.assertTrue(opened)
        healthy=0
        for case in opened:
            case=dict(case,opened_at=case["opened_at"].isoformat() if hasattr(case["opened_at"],"isoformat") else case["opened_at"])
            self.assertEqual(case["opened_by"],"MONITOR");self.assertIsNone(case.get("source_case_id"))
            context=public_evidence(self.world,case["shipment_id"],case["opened_at"])
            # No future leakage: nothing observed after the moment the case opened.
            for node in context["nodes"]:
                when=node["properties"].get("occurred_at")
                if when:self.assertLessEqual(instant(when),instant(case["opened_at"]))
            self.assertTrue(assess_shipment(evidence_world(context,self.world.config),case["shipment_id"],case["opened_at"])["exceptions"])
        with_case={c["shipment_id"] for c in opened}
        for sh in self.world.of_kind("Shipment"):
            if sh.properties["split"]!="development" or sh.id in with_case:continue
            context=public_evidence(self.world,sh.id,s.status()["as_of"])
            if not assess_shipment(evidence_world(context,self.world.config),sh.id,context["as_of"])["exceptions"]:healthy+=1
        self.assertGreater(healthy,0)  # Healthy shipments progress without a case.

    def test_live_worker_investigates_monitor_case_without_scripted_rehearsal(self):
        s,d=self.live();self.run_world(s,rounds=40)
        self.assertTrue(self.cases(d))
        result=s.process_one(manual=True)
        self.assertTrue(result["processed"]);self.assertNotIn("fixture",result["afl"])
