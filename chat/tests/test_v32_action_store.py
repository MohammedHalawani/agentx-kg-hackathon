"""Real store/authority/response/verifier/closure path, on the existing in-memory Neo4j port."""
import copy
import json
import os
import unittest
from datetime import timedelta
from unittest.mock import patch

from dataset_v2.contracts import Config, instant, iso
from dataset_v2.generate import generate
from dataset_v2.derive import assess_shipment
from operations.action_lifecycle import SyntheticActionAdapter, load
from operations.lifecycle import OperationsConflict
from operations.store import OperationsStore, CONTROL_ID
from tests import test_operations_store as port
from tests.world_live import seed_case


class ActionStoreTests(unittest.TestCase):
    traces=[]
    @classmethod
    def setUpClass(cls): cls.base=generate(Config(total=90))

    def make(self,action="REQUEST_RESCAN"):
        self.world=copy.deepcopy(self.base)
        self.clock=instant(self.world.config.as_of)
        scans=[n for n in self.world.of_kind("ScanEvent") if n.properties.get("split")=="development" and n.properties.get("package_id") in self.world.nodes]
        scan=next(n for n in scans if n.properties.get("observed_barcode") and n.properties["observed_barcode"]!=
                  self.world.nodes[n.properties["package_id"]].properties.get("manifest_barcode"))
        self.sid=scan.properties["shipment_id"]
        self.packages=self.world.owned(self.sid,"Package")
        self.facility=scan.properties["facility_id"]
        self.target={"package_ids":sorted(n.id for n in self.packages),"facility_ids":[self.facility],
                     "baseline_device_ids":[scan.properties["device_ref"]]}
        cause,symptoms="BARCODE_MISMATCH",["BARCODE_READ_DIFFERS"]
        if action!="REQUEST_RESCAN":
            self.sid=next(n.id for n in self.world.of_kind("Shipment") if n.properties.get("split")=="development" and
                          not assess_shipment(self.world,n.id,self.world.config.as_of)["exceptions"])
            self.packages=self.world.owned(self.sid,"Package")
            transfer=next(n for n in self.world.owned(self.sid,"CustodyEvent") if n.properties.get("source_event_id") in self.world.nodes and
                          self.world.nodes[n.properties["source_event_id"]].kind=="ScanEvent" and
                          self.world.nodes.get(n.properties.get("to_id")) and
                          self.world.nodes[n.properties["to_id"]].kind in ("DeliveryDepot","Hub","SortingCenter","FulfillmentWarehouse","OrganizationWarehouse"))
            source=self.world.nodes[transfer.properties["source_event_id"]]
            self.facility=transfer.properties["to_id"]
            self.target={"package_ids":sorted(n.id for n in self.packages),"facility_ids":[self.facility],
                         "device_id":source.properties["device_ref"],
                         "expected_evidence":[{"package_id":transfer.properties["package_id"],"predicate":transfer.properties["event_type"],"location_id":self.facility}]}
            if action=="REQUEST_DEVICE_SYNC":
                # A narrow temporary fixture: original observations exist but are
                # buffered beyond dispatch. No frozen source bundle is modified.
                for node in (source,transfer):
                    node.properties.update(recorded_at=iso(self.clock+timedelta(minutes=30)),source_ref="synthetic:controlled-buffered-source")
                self.response_refs=[source.id,transfer.id]
                cause="DELAYED_SYNC"
            else:
                transfer.properties.update(received_acknowledgments=0,source_ref="synthetic:unconfirmed-original-handover")
                cause="CUSTODY_GAP"
            symptoms=["CUSTODY_TRANSFER_UNCONFIRMED"]
        self.driver=port.Driver(self.world)
        self.store=OperationsStore(self.driver,"shipments-v2-demo",self.world.config.dataset_id,self.world.config,port.Reader(self.world))
        self.store.initialize();self.store.adapter=SyntheticActionAdapter()
        self.driver.ledger[CONTROL_ID][1].update(as_of=self.clock,case_source="monitor",session_id="DEMO-OPS-SESSION-V32")
        self.case_id=seed_case(self.store,self.driver,self.sid,action,[cause],target=self.target,symptoms=symptoms)
        [self.execution_id]=self.store.execute_step()
        environment=patch.dict(os.environ,{"SUHAIL_SYNTHETIC_ACTION_RESPONSES":"1"})
        environment.start();self.addCleanup(environment.stop)
        return self.store

    def move(self,minutes):
        self.clock+=timedelta(minutes=minutes)
        self.driver.ledger[CONTROL_ID][1]["as_of"]=self.clock
        self.driver.ledger[self.case_id][1]["as_of"]=self.clock

    def response(self,kind,key,evidence=None,**kwargs):
        execution=self.driver.ledger[self.execution_id][1]
        return self.store.record_action_response(self.case_id,self.execution_id,actor_id="DEMO-OPERATOR-LOCAL",
            expected_revision=load(execution)["revision"],response_id=key,kind=kind,occurred_at=iso(self.clock),
            evidence_ids=evidence or [],source_ref="synthetic:controlled-field-response",**kwargs)

    def new_scans(self,*,wrong=False,foreign=False):
        refs=[]
        for i,package in enumerate(self.packages):
            ref=self.world.node("ScanEvent",f"DEMO-RESPONSE-SCAN-{i}",shipment_id="DEMO-SHP-FOREIGN" if foreign else self.sid,
                split="development",package_id=package.id,occurred_at=iso(self.clock),recorded_at=iso(self.clock),
                facility_id=self.facility,readable=True,confidence=.99,device_ref="DEMO-DEVICE-INDEPENDENT-RESPONSE",
                observed_barcode="OTHER-LABEL" if wrong else package.properties["manifest_barcode"],source_ref="synthetic:independent-rescan")
            refs.append(ref)
        return refs

    def trace(self,name,may_resolve):
        detail=self.store.case_detail(self.case_id)
        self.traces.append({"workflow":name,"case_id":self.case_id,"shipment_id":self.sid,"synthetic":True,
                            "workflow_state":detail["workflow_state"],"outcome":detail["outcome"],
                            "action_status":detail["action_status"],"expected_may_resolve":may_resolve})

    def test_complete_barcode_request_response_and_actual_verified_outcome(self):
        self.make()
        self.assertEqual(self.store.case_detail(self.case_id)["action_status"]["actions"][0]["state"],"AWAITING_ACKNOWLEDGEMENT")
        for i,kind in enumerate(("ACKNOWLEDGED","ACCEPTED","STARTED")):
            self.response(kind,f"response-{i}")
            self.assertEqual(self.store.outcome_step(force=True),[])
            self.assertEqual(self.store.case_detail(self.case_id)["workflow_state"],"AWAITING_OUTCOME")
            self.assertFalse(any(k=="OpsOutcome" for k,_ in self.driver.ledger.values()))
        self.move(30);refs=self.new_scans()
        self.response("EVIDENCE_RECEIVED","new-evidence",refs)
        self.assertEqual(self.store.case_detail(self.case_id)["action_status"]["actions"][0]["verification"],"AWAITING_VERIFICATION")
        [result]=self.store.outcome_step(force=True)
        self.assertEqual(result["workflow_state"],"RESOLVED")
        detail=self.store.case_detail(self.case_id)
        self.assertEqual(detail["outcome"]["verifier_id"],"SUHAIL-OUTCOME-VERIFIER")
        self.assertEqual(detail["outcome"]["outcome_type"],"barcode_corrected")
        self.assertEqual(set(detail["outcome"]["evidence_ids"]),set(refs))
        self.assertEqual(detail["action_status"]["resolution"],"VERIFIED_RESOLVED")
        self.assertEqual(self.store.outcome_step(force=True),[])
        self.trace("barcode-independent-rescan",True)

    def test_accepted_task_without_evidence_and_wrong_label_never_resolve(self):
        self.make();self.response("ACKNOWLEDGED","ack");self.response("ACCEPTED","accepted")
        self.assertEqual(self.store.outcome_step(force=True),[])
        self.move(30);refs=self.new_scans(wrong=True)
        self.response("EVIDENCE_RECEIVED","wrong-label-evidence",refs)
        [result]=self.store.outcome_step(force=True)
        self.assertNotEqual(result["workflow_state"],"RESOLVED")
        detail=self.store.case_detail(self.case_id)
        self.assertFalse(detail["outcome"]["success"])
        self.assertEqual(detail["outcome"]["outcome_type"],"barcode_still_differs")
        self.trace("barcode-continued-mismatch",False)

    def test_foreign_evidence_refused_and_response_timeout_stays_operationally_unresolved(self):
        self.make();self.response("ACKNOWLEDGED","ack");self.response("ACCEPTED","accepted")
        self.move(30);refs=self.new_scans(foreign=True)
        with self.assertRaises(OperationsConflict): self.response("EVIDENCE_RECEIVED","foreign",refs)
        self.move(60*96)
        self.assertEqual(self.store.outcome_step(force=True),[])
        detail=self.store.case_detail(self.case_id)
        self.assertEqual(detail["action_status"]["actions"][0]["state"],"EXPIRED")
        self.assertEqual(detail["workflow_state"],"NEEDS_EVIDENCE")
        self.assertFalse(detail["action_status"]["human_decision_required"])
        self.assertIsNone(detail["outcome"])
        self.trace("foreign-evidence-and-expiry",False)

    def test_disabled_transport_rejection_duplicate_and_late_response_are_audited_without_resolution(self):
        self.make()
        with patch.dict(os.environ,{"SUHAIL_SYNTHETIC_ACTION_RESPONSES":"0"}),self.assertRaises(OperationsConflict):
            self.response("ACKNOWLEDGED","disabled")
        original=self.response("REJECTED","rejected")
        replay=self.response("REJECTED","rejected")
        self.assertTrue(replay["idempotent"])
        self.assertEqual(original["action_lifecycle"],replay["action_lifecycle"])
        self.move(60*96)
        late=self.response("ACKNOWLEDGED","late-ack")
        self.assertTrue(late["action_lifecycle"]["events"][-1]["late"])
        self.assertEqual(late["action_lifecycle"]["state"],"REJECTED")
        self.assertEqual(self.store.outcome_step(force=True),[])
        self.assertIsNone(self.store.case_detail(self.case_id)["outcome"])
        self.trace("rejected-duplicate-late-response",False)

    def test_sync_lifecycle_verifies_original_target_device_upload_and_cleared_exception(self):
        self.make("REQUEST_DEVICE_SYNC")
        self.response("ACKNOWLEDGED","ack");self.response("ACCEPTED","accepted")
        self.assertEqual(self.store.outcome_step(force=True),[])
        self.move(30)
        self.response("EVIDENCE_RECEIVED","uploaded-original-records",self.response_refs)
        [result]=self.store.outcome_step(force=True)
        self.assertEqual(result["workflow_state"],"RESOLVED")
        outcome=self.store.case_detail(self.case_id)["outcome"]
        self.assertEqual((outcome["success"],outcome["outcome_type"],outcome["verifier_id"]),(True,"delayed_upload_received","SUHAIL-OUTCOME-VERIFIER"))
        self.assertTrue(set(self.response_refs)<=set(outcome["evidence_ids"]))
        self.trace("targeted-buffered-upload",True)

    def test_custody_lifecycle_verifies_physical_check_without_inventing_an_old_handover(self):
        self.make("INITIATE_CUSTODY_RECONCILIATION")
        self.response("ACKNOWLEDGED","ack");self.response("ACCEPTED","accepted");self.response("STARTED","search")
        self.move(30);scans=self.new_scans();refs=list(scans)
        for i,(package,scan) in enumerate(zip(self.packages,scans)):
            refs.append(self.world.node("CustodyEvent",f"DEMO-RESPONSE-CUSTODY-{i}",shipment_id=self.sid,split="development",
                package_id=package.id,occurred_at=iso(self.clock),recorded_at=iso(self.clock),from_id=self.facility,to_id=self.facility,
                event_type="RECEIVED",source_event_id=scan,required_acknowledgments=2,received_acknowledgments=2,
                source_quality="CORROBORATED",facility_id=self.facility,source_ref="synthetic:directed-stock-reconciliation"))
        self.response("EVIDENCE_RECEIVED","new-corroborated-stock-check",refs)
        [result]=self.store.outcome_step(force=True)
        detail=self.store.case_detail(self.case_id)
        self.assertTrue(detail["outcome"]["success"])
        self.assertEqual(detail["outcome"]["outcome_type"],"custody_reconciled")
        self.assertEqual(result["workflow_state"],"HUMAN_REVIEW")
        self.assertIn("CUSTODY_TRANSFER_UNCONFIRMED",detail["outcome"]["remaining_symptoms"])
        self.assertNotEqual(detail["action_status"]["resolution"],"VERIFIED_RESOLVED")
        self.trace("custody-confirmed-original-handover-uncertain",False)


if __name__=="__main__":unittest.main()
