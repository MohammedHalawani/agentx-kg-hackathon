"""Synthetic-only response protocol and actual action-specific verifier decisions.

Expected answers live only in tests. No model-quality claim is made by these probes.
"""
import copy
import json
import os
import unittest
from datetime import timedelta
from unittest.mock import patch

from dataset_v2.contracts import Config, Node, World, instant, iso
from operations import action_lifecycle as life
from operations.lifecycle import OperationsConflict
from operations.outcome_engine import evaluate

START = "2026-09-20T12:00:00+00:00"
NOW = "2026-09-20T13:00:00+00:00"
DEADLINE = "2026-09-21T12:00:00+00:00"
SID, PID, FACILITY = "DEMO-SHP-PROBE", "DEMO-PKG-PROBE", "DEMO-DEPOT-PROBE"


def probe(action):
    world = World(Config())
    for node in (Node(SID,"Shipment",{"policy_id":"DEMO-POLICY"}),
                 Node(PID,"Package",{"shipment_id":SID,"manifest_barcode":"KNOWN-IDENTITY"}),
                 Node(FACILITY,"DeliveryDepot",{}),
                 Node("DEMO-POLICY","EvidencePolicy",{"barcode_min_confidence":.95})):
        world.nodes[node.id]=node
    execution={"entity_id":"DEMO-OPS-EXECUTION-PROBE","action_type":action,"occurred_at":START,"deadline_at":DEADLINE,
               "action_protocol":life.VERSION,"case_opened_at":START,"target_device":"DEMO-DEVICE-OFFLINE",
               "expected_evidence":[{"package_id":PID,"predicate":"RECEIVED","location_id":FACILITY}],
               "action_target":{"package_ids":[PID],"facility_ids":[FACILITY],"baseline_device_ids":["DEMO-DEVICE-ORIGINAL"]}}
    return world,execution


def observation(world, *, wrong=False, foreign=False, late=False, device="DEMO-DEVICE-INDEPENDENT", old=False, source=True):
    scan=Node("DEMO-SCAN-RESPONSE","ScanEvent",{"shipment_id":"DEMO-OTHER" if foreign else SID,"package_id":PID,
        "occurred_at":"2026-09-20T10:00:00+00:00" if old else "2026-09-20T12:20:00+00:00",
        "recorded_at":"2026-09-22T12:30:00+00:00" if late else "2026-09-20T12:30:00+00:00",
        "source_ref":"synthetic:independent-source" if source else "","facility_id":FACILITY,"readable":True,
        "confidence":.99,"device_ref":device,"observed_barcode":"DIFFERENT-IDENTITY" if wrong else "KNOWN-IDENTITY"})
    world.nodes[scan.id]=scan
    return scan


def custody(world, scan, *, old=False, acknowledgements=2):
    event=Node("DEMO-CUSTODY-RESPONSE","CustodyEvent",{"shipment_id":scan.properties["shipment_id"],"package_id":PID,
        "occurred_at":scan.properties["occurred_at"],"recorded_at":scan.properties["recorded_at"],
        "source_ref":"synthetic:corroborated-custody","from_id":"DEMO-VEHICLE","to_id":FACILITY,
        "event_type":"RECEIVED","source_event_id":scan.id,"source_quality":"CORROBORATED",
        "required_acknowledgments":2,"received_acknowledgments":acknowledgements})
    world.nodes[event.id]=event
    return event


class LifecycleTests(unittest.TestCase):
    def state(self): return life.dispatched(life.initial(START),START,requires_responses=True)
    def event(self,kind,key="response-1",evidence=None):
        return {"response_id":key,"kind":kind,"occurred_at":NOW,"evidence_ids":evidence or [],"source_ref":"synthetic:operator-response"}
    def apply(self,state,kind,key="response-1",evidence=None,**overrides):
        return life.respond(state,self.event(kind,key,evidence),now=overrides.get("now",NOW),deadline=DEADLINE,revision=state["revision"])

    def test_receipt_acknowledgement_acceptance_and_evidence_are_independent(self):
        state=self.state()
        for i,kind in enumerate(("ACKNOWLEDGED","ACCEPTED","STARTED","EVIDENCE_RECEIVED")):
            state,_=self.apply(state,kind,f"response-{i}",["DEMO-SCAN-RESPONSE"] if kind=="EVIDENCE_RECEIVED" else [])
            self.assertNotIn(state["state"],("VERIFIED","RESOLVED"))
            self.assertNotIn(state["verification"],("VERIFIED_SUCCESS",))
        self.assertEqual((state["dispatch"],state["acknowledgement"],state["acceptance"],state["execution"],state["verification"]),
                         ("SENT","ACKNOWLEDGED","ACCEPTED","EXECUTING","AWAITING_VERIFICATION"))

    def test_duplicate_is_idempotent_and_changed_duplicate_or_stale_revision_is_refused(self):
        state=self.state(); event=self.event("ACKNOWLEDGED")
        state,_=life.respond(state,event,now=NOW,deadline=DEADLINE,revision=state["revision"])
        replay,idempotent=life.respond(state,event,now=NOW,deadline=DEADLINE,revision=0)
        self.assertTrue(idempotent);self.assertEqual(state,replay)
        with self.assertRaises(OperationsConflict):
            life.respond(state,{**event,"kind":"REJECTED"},now=NOW,deadline=DEADLINE,revision=state["revision"])
        with self.assertRaises(OperationsConflict):
            life.respond(state,self.event("ACCEPTED","response-2"),now=NOW,deadline=DEADLINE,revision=0)

    def test_rejection_failure_expiry_and_late_responses_never_verify_or_reopen(self):
        state,_=self.apply(self.state(),"REJECTED")
        late,_=self.apply(state,"ACKNOWLEDGED","late-ack")
        self.assertEqual(late["state"],"REJECTED");self.assertTrue(late["events"][-1]["late"])
        expired=life.verification(self.state(),{"status":"pending","deadline_at":DEADLINE},DEADLINE)
        self.assertEqual(expired["state"],"EXPIRED")
        late,_=self.apply(expired,"ACCEPTED",now="2026-09-22T13:00:00+00:00")
        self.assertEqual(late["state"],"EXPIRED")
        with self.assertRaises(OperationsConflict):self.apply(self.state(),"EVIDENCE_RECEIVED",evidence=["DEMO-SCAN"])
        with self.assertRaises(OperationsConflict):
            life.respond(self.state(),{**self.event("ACKNOWLEDGED"),"success":True},now=NOW,deadline=DEADLINE,revision=1)
        state,_=self.apply(self.state(),"ACKNOWLEDGED","ack")
        state,_=self.apply(state,"ACCEPTED","accept")
        state,_=self.apply(state,"FAILED","failed")
        self.assertEqual(state["execution"],"FAILED")
        self.assertEqual(state["verification"],"NOT_REQUESTED")


class ActualVerifierTests(unittest.TestCase):
    results=[]
    def check(self,scenario,world,execution,expected,at=NOW):
        result=evaluate(world,SID,execution,at)
        self.results.append({"scenario":scenario,"action":execution["action_type"],"status":result["status"],
                             "rule_id":result["rule_id"],"evidence_ids":result["evidence_ids"],"expected":expected})
        self.assertEqual(result["status"],expected,scenario)
        return result

    def test_barcode_positive_different_cause_foreign_missing_old_late_and_same_device(self):
        for variant,expected in (("independent-match","success"),("wrong-label","failure"),("foreign-source","pending"),
                                 ("missing-source","pending"),("old-scan","pending"),("late-source","failure"),("same-device","pending")):
            with self.subTest(variant=variant):
                world,execution=probe("REQUEST_RESCAN")
                observation(world,wrong=variant=="wrong-label",foreign=variant=="foreign-source",source=variant!="missing-source",
                            old=variant=="old-scan",late=variant=="late-source",
                            device="DEMO-DEVICE-ORIGINAL" if variant=="same-device" else "DEMO-DEVICE-INDEPENDENT")
                self.check(variant,world,execution,expected,at="2026-09-22T13:00:00+00:00" if variant=="late-source" else NOW)

    def test_sync_requires_target_device_original_clock_expected_custody_and_both_source_receipts(self):
        for variant,expected in (("buffered-upload","success"),("healthy-device","pending"),("gps-only","pending"),
                                 ("wrong-device","pending"),("unconfirmed-custody","pending"),("foreign-source","pending"),
                                 ("late-source","pending"),("missing-source","pending"),("no-expected-observation","pending")):
            with self.subTest(variant=variant):
                world,execution=probe("REQUEST_DEVICE_SYNC")
                if variant=="gps-only":
                    world.nodes["DEMO-GPS"]=Node("DEMO-GPS","GPSObservation",{"shipment_id":SID,"recorded_at":NOW,
                                                      "occurred_at":START,"source_ref":"synthetic:vehicle-gps"})
                elif variant!="healthy-device":
                    scan=observation(world,old=True,device="DEMO-WRONG-DEVICE" if variant=="wrong-device" else execution["target_device"],
                                     foreign=variant=="foreign-source",late=variant=="late-source",source=variant!="missing-source")
                    custody(world,scan,acknowledgements=1 if variant=="unconfirmed-custody" else 2)
                if variant=="no-expected-observation":execution["expected_evidence"]=[]
                self.check(variant,world,execution,expected)

    def test_custody_positive_foreign_old_wrong_identity_unconfirmed_and_wrong_facility(self):
        for variant,expected in (("directed-reconciliation","success"),("foreign-source","pending"),("old-event","pending"),
                                 ("wrong-identity","pending"),("unconfirmed-custody","pending"),("wrong-facility","pending"),
                                 ("missing-source","pending"),("late-source","pending")):
            with self.subTest(variant=variant):
                world,execution=probe("INITIATE_CUSTODY_RECONCILIATION")
                scan=observation(world,foreign=variant=="foreign-source",old=variant=="old-event",wrong=variant=="wrong-identity",
                                 source=variant!="missing-source",late=variant=="late-source")
                custody(world,scan,acknowledgements=1 if variant=="unconfirmed-custody" else 2)
                if variant=="wrong-facility":execution["action_target"]["facility_ids"]=["DEMO-OTHER-DEPOT"]
                self.check(variant,world,execution,expected)

    def test_contradictory_good_and_bad_reads_and_serious_dispute_never_succeed(self):
        world,execution=probe("REQUEST_RESCAN")
        good=observation(world)
        bad=copy.deepcopy(good);bad.id="DEMO-SCAN-CONTRADICTION";bad.properties["observed_barcode"]="CONTRADICTORY"
        world.nodes[bad.id]=bad
        self.check("contradictory-rescans",world,execution,"failure")
        del world.nodes[bad.id]
        world.nodes["DEMO-DISPUTE"]=Node("DEMO-DISPUTE","RecipientReport",{"shipment_id":SID,"recorded_at":NOW,
            "occurred_at":NOW,"source_ref":"synthetic:recipient-report","report_code":"NOT_RECEIVED"})
        self.check("serious-nonreceipt-dispute",world,execution,"failure")
        from operations.authority import authorize,execution_permission
        risk,_=authorize("DELIVERY_DISPUTE_REVIEW",["DELIVERY_DISPUTE"],review_verdict="ACCEPT",evidence_conflict=False,
                         synthetic=True,live_session=True)
        self.assertEqual(risk,"HUMAN_REVIEW")
        self.assertFalse(execution_permission("DELIVERY_DISPUTE_REVIEW","AUTO_POLICY",risk)[0])


if __name__=="__main__":unittest.main()
