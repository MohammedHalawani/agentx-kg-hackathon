"""Read-only V2 content rehearsal. Run from chat with uv run python ../scripts/..."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"chat"))
import config
from neo4j import GraphDatabase
from dataset_v2.contracts import Config,canonical,instant
from operations.read_model import OperationsReader


def main():
    bundle=ROOT/"artifacts/dataset-v2/main"
    manifest=json.loads((bundle/"manifest.json").read_text(encoding="utf-8"))
    cfg=Config(**manifest["config"])
    # Gold selects administrative test fixtures only; no label enters retrieval.
    fixtures={}
    heldout=None
    for line in (bundle/"gold.jsonl").open(encoding="utf-8"):
        row=json.loads(line)
        if row["split"]=="development":fixtures.setdefault(row["recipe_id"],row["shipment_id"])
        elif row["split"]=="held_out":heldout=row["shipment_id"]
    report={"read_only":True,"synthetic":True,"provider_calls":0,"samples":[]}
    with GraphDatabase.driver(config.NEO4J_URI,auth=(config.NEO4J_USERNAME,config.NEO4J_PASSWORD)) as driver:
        reader=OperationsReader(driver,"shipments-v2-demo",cfg.dataset_id,cfg,clock=lambda:cfg.as_of)
        for recipe,sid in sorted(fixtures.items()):
            detail=reader.shipment_detail(sid)
            evidence=detail["evidence"]
            private={"split","holdout_group","gold","recipe","recipe_id","thinking","chain_of_thought","_v2_record_hash"}
            for node in evidence["nodes"]:
                assert not private.intersection(node["properties"])
                assert instant(node["properties"]["recorded_at"])<=instant(evidence["as_of"])
                if node["properties"].get("occurred_at"):
                    assert instant(node["properties"]["occurred_at"])<=instant(evidence["as_of"])
            assert detail["reasoning"]["outcome"] is None
            layers=detail["route_layers"]["layers"]
            assert all(p["source"]=="vehicle_telemetry_only" for p in layers["vehicle_path"])
            precedents=detail["reasoning"]["precedents"]
            assert len(precedents)<=5 and all(type(p["success"]) is bool for p in precedents)
            report["samples"].append({"recipe":recipe,"shipment_id":sid,"as_of":evidence["as_of"],
                "nodes":len(evidence["nodes"]),"edges":len(evidence["edges"]),
                "codes":detail["reasoning"]["assessment"]["supported_codes"],
                "workflow_proposal":detail["reasoning"]["workflow_state"],
                "layer_counts":{k:len(v) for k,v in layers.items()},"verified_precedents":len(precedents)})
        try:reader.evidence(heldout)
        except LookupError:report["heldout_withheld"]=True
        else:raise AssertionError("Held-out shipment leaked")
        report["decisions"]=reader.decisions()
    report["status"]="PASS"
    destination=ROOT/"docs/dataset-v2/2026-10-09-read-content-smoke.json"
    destination.write_text(canonical(report)+"\n",encoding="utf-8")
    print(canonical({"status":report["status"],"samples":len(report["samples"]),
                     "heldout_withheld":report["heldout_withheld"],"provider_calls":0}),flush=True)


if __name__=="__main__":main()
