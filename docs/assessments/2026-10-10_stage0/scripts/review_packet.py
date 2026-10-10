import json, sys
sys.path.insert(0, r"C:\Projects\demo\chat")
from dataset_v2.network import generate_live, live_config
from operations.reasoning import public_evidence
from operations.tools import InvestigationTools
from operations.checks import fact_checks, cited_records
world, truth = generate_live(live_config(total=600, dataset_id="DEMO-SUHAIL-LIVE-TEST"))
pipe = {c["shipment_id"][-6:]: c for c in json.load(open(r"C:\Projects\demo\docs\evals\2026-10-09_s5\final\pipeline.json"))["cases"]}
for sid6, cause in (("000305", "WEIGHT_MISMATCH"), ("000583", "BARCODE_MISMATCH")):
    c = pipe[sid6]; sid = c["shipment_id"]
    t = InvestigationTools(public_evidence(world, sid, c["opened_at"]), world.config, symptoms=c["opening_symptoms"])
    t.call("shipment_overview", {}); r = t.call("scans", {})
    print("==", sid6, "scans tool evidence_ids:", r["evidence_ids"])
    print("   scans tool result (what the investigator sees):", r["result"][:900])
    flagged = [x for x in json.loads(r["result"].split(" CITABLE_EVIDENCE_IDS")[0])["scans"] if x.get("weight_within_tolerance") is False or x.get("barcode_matches") is False]
    sc = flagged[0]["scan_id"]
    inv = {"primary_cause": cause, "hypotheses": [{"cause": cause, "status": "supported", "supporting_evidence_ids": [sc], "contradicting_evidence_ids": []}]}
    print("   reviewer cited_records when citing only the scan:", json.dumps(cited_records(inv, t), default=str)[:1200])
    print("   reviewer deterministic_checks:", json.dumps(fact_checks(inv, t)["checks"])[:600])
    pk = [n.id for n in t._packages()]
    t.call("policy", {})
    pol = t.nodes[sid].properties.get("policy_id")
    inv2 = {"primary_cause": cause, "hypotheses": [{"cause": cause, "status": "supported", "supporting_evidence_ids": [sc, *pk[:1], pol], "contradicting_evidence_ids": []}]}
    rec = cited_records(inv2, t)
    print("   with package+policy cited, reviewer gets keys:", {k: sorted(v)[:40] for k, v in rec.items()})
