"""Private scripted quality probes, separated from production prompts and source packets.

These measure the offline protocol/evidence harness, not GPT-OSS diagnostic accuracy.
"""
import copy
import json
from pathlib import Path
import unittest

from dataset_v2.contracts import Node, World, Config, instant, iso
from operations import investigator
from operations.authority import authorize
from operations.identifiers import storage_value
from operations.outcome_engine import evaluate
from tests import test_operations_agents as fixtures

ROOT=Path(__file__).resolve().parents[2]


def candidate(records):
    """Scripted role over visible source fields only; no expected answers or case IDs."""
    scans={k:v for k,v in records.items() if v.get("kind")=="ScanEvent"}
    mismatch=[k for k,v in scans.items() if v.get("observed_barcode") and v.get("manifest_barcode") and
              v["observed_barcode"]!=v["manifest_barcode"]]
    delayed=[k for k,v in scans.items() if v.get("occurred_at") and v.get("recorded_at") and
             (instant(v["recorded_at"])-instant(v["occurred_at"])).total_seconds()>=3600]
    gaps=[k for k,v in records.items() if v.get("kind")=="CustodyEvent" and
          type(v.get("required_acknowledgments")) is int and v.get("received_acknowledgments",0)<v["required_acknowledgments"]]
    disputes=[k for k,v in records.items() if v.get("kind")=="RecipientReport" and v.get("report_code")=="NOT_RECEIVED"]
    if disputes: cause,action,ids="DELIVERY_DISPUTE","DELIVERY_DISPUTE_REVIEW",disputes
    elif mismatch: cause,action,ids="BARCODE_MISMATCH","REQUEST_RESCAN",mismatch
    elif delayed: cause,action,ids="DELAYED_SYNC","REQUEST_DEVICE_SYNC",delayed
    elif gaps: cause,action,ids="CUSTODY_GAP","INITIATE_CUSTODY_RECONCILIATION",gaps
    else:cause,action,ids="INSUFFICIENT_EVIDENCE","REQUEST_ADDITIONAL_EVIDENCE",[]
    abstain=cause=="INSUFFICIENT_EVIDENCE"
    hypotheses=[{"cause":cause,"status":"uncertain" if abstain else "supported","supporting_evidence_ids":ids,
                 "contradicting_evidence_ids":[],"assessment":"Source fields support this limited finding; the physical cause may remain uncertain."}]
    alternative=fixtures.receipt_alternative(cause,records)
    if cause=="DELAYED_SYNC":
        alternative={"cause":"CUSTODY_GAP","status":"uncertain","supporting_evidence_ids":[],
                     "contradicting_evidence_ids":delayed,"assessment":"Late receipt is observed; missing physical transfers remain unconfirmed."}
    if alternative:hypotheses.append(alternative)
    return {"action":"conclude","primary_cause":cause,"confidence":"low" if abstain else "medium","hypotheses":hypotheses,
            "missing_evidence":["Independent package-bound source observation"] if abstain else [],
            "next_evidence_step":"Request the missing observation from its source." if abstain else "",
            "recommended_action":action,"requires_physical_check":False,"summary":"A source-backed finding with stated uncertainty."}


def independent_ask(system,user,default):
    packet=json.loads(user.split("\n\n",1)[0])["facts"]
    source=packet["cited_records"]
    expected=candidate(source)
    finding=packet["investigator_conclusion"]
    same=expected["primary_cause"]==finding["primary_cause"]
    alternatives=[h for h in expected["hypotheses"] if h["cause"]!=expected["primary_cause"]]
    checked=all(h in finding["hypotheses"] for h in alternatives)
    verdict="HUMAN_REVIEW" if expected["primary_cause"]=="DELIVERY_DISPUTE" else "ACCEPT" if same and checked else "REVISE"
    return {**default,"verdict":verdict,"feedback":"Compared the visible source fields and the actual alternative assessment.",
            "alternatives_tested":"yes" if alternatives and checked else "no"}


class CaseIntelligenceTests(unittest.TestCase):
    metrics=[]
    def test_taxonomy_retains_all_user_cases_and_twelve_priorities(self):
        data=json.loads((ROOT/"docs/v3.2/case-taxonomy.json").read_text(encoding="utf-8"))
        self.assertEqual((data["case_count"],len(data["families"])),(136,12))
        self.assertEqual(len({r["id"] for r in data["cases"]}),136)
        self.assertEqual(sum("priority"in r for r in data["cases"]),12)
        self.assertIn("CASE INTELLIGENCE PROCEDURE",investigator.SYSTEM)
        self.assertIn("Independently compare",investigator.REVIEWER_SYSTEM)
        for marker in ("000064","000194","v31_saved_evidence","case-taxonomy.json"):
            self.assertNotIn(marker,investigator.SYSTEM+investigator.REVIEWER_SYSTEM)

    def test_classification_citations_alternatives_review_and_authority_are_scored_separately(self):
        timely={"kind":"ScanEvent","occurred_at":"2026-09-20T08:00:00+00:00","recorded_at":"2026-09-20T08:02:00+00:00",
                "observed_barcode":"KNOWN","manifest_barcode":"KNOWN"}
        # Expected categories are test-only and never placed in the role packets.
        probes=[("identity",{"source-scan":{**timely,"observed_barcode":"OTHER"}},"BARCODE_MISMATCH"),
                ("late-upload",{"source-scan":{**timely,"recorded_at":"2026-09-20T10:00:00+00:00"}},"DELAYED_SYNC"),
                ("handover",{"source-scan":timely,"source-custody":{"kind":"CustodyEvent","required_acknowledgments":2,"received_acknowledgments":1}},"CUSTODY_GAP"),
                ("insufficient",{},"INSUFFICIENT_EVIDENCE"),
                ("serious-dispute",{"source-scan":timely,"recipient-source":{"kind":"RecipientReport","report_code":"NOT_RECEIVED"}},"DELIVERY_DISPUTE")]
        for name,records,expected in probes:
            with self.subTest(name=name):
                finding=candidate(records)
                self.assertIsNone(investigator.validate_conclusion(finding,set(records)))
                citations={k for h in finding["hypotheses"] for k in h["supporting_evidence_ids"]+h["contradicting_evidence_ids"]}
                self.assertTrue(citations<=records.keys())
                review=investigator.review(finding,records,[],[],ask=independent_ask,repair=False)
                risk,_=authorize(finding["recommended_action"],[finding["primary_cause"]],review_verdict=review["verdict"],
                                 evidence_conflict=False,synthetic=True,live_session=True)
                self.assertEqual(finding["primary_cause"],expected)
                self.assertEqual(review["verdict"],"HUMAN_REVIEW" if expected=="DELIVERY_DISPUTE" else "ACCEPT")
                self.assertEqual(risk,"HUMAN_REVIEW" if expected=="DELIVERY_DISPUTE" else "AUTO")
                self.metrics.append({"probe":name,"classification":finding["primary_cause"],"classification_correct":True,
                                     "citations_valid":True,"alternative_addressed":review["alternatives_tested"]=="yes",
                                     "abstained":expected=="INSUFFICIENT_EVIDENCE","review_verdict":review["verdict"],
                                     "authority":risk,"unnecessary_human_escalation":False,"mode":"scripted source-field probe"})

    def test_independent_review_rejects_a_valid_schema_with_wrong_source_interpretation(self):
        records={"source-scan":{"kind":"ScanEvent","occurred_at":"2026-09-20T08:00:00+00:00",
                                "recorded_at":"2026-09-20T08:02:00+00:00","observed_barcode":"OTHER","manifest_barcode":"KNOWN"}}
        finding=candidate(records)
        finding["primary_cause"]="CUSTODY_GAP";finding["hypotheses"][0]["cause"]="CUSTODY_GAP"
        self.assertIsNone(investigator.validate_conclusion(finding,set(records)))
        reviewed=investigator.review(finding,records,[],[],ask=independent_ask,repair=False)
        self.assertEqual(reviewed["verdict"],"REVISE")

    def test_saved_000064_and_000194_sources_cannot_verify_a_new_request_without_new_evidence(self):
        cases=json.loads((ROOT/"chat/tests/fixtures/v31_saved_evidence.json").read_text(encoding="utf-8"))["cases"]
        for source in cases:
            case=storage_value(source);world=World(Config())
            for row in case["nodes"]:world.nodes[row["id"]]=Node(row["id"],row["kind"],row["properties"])
            now=max(instant(n.properties["recorded_at"]) for n in world.nodes.values() if n.properties.get("recorded_at"))
            for action in ("REQUEST_RESCAN","INITIATE_CUSTODY_RECONCILIATION"):
                execution={"action_type":action,"occurred_at":iso(now),"deadline_at":iso(now+__import__('datetime').timedelta(hours=24)),
                           "action_protocol":"suhail-action-1","action_target":{"package_ids":sorted(n.id for n in world.nodes.values() if n.kind=="Package")}}
                self.assertEqual(evaluate(world,case["shipment_id"],execution,iso(now))["status"],"pending")


if __name__=="__main__":unittest.main()
