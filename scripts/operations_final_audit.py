"""Read-only final product census. Credentials stay in configuration and memory."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"chat"))
import config
from neo4j import GraphDatabase
from dataset_v2.audit import snapshot, json_value
from dataset_v2.contracts import canonical


def main():
    original=json.loads((ROOT/"docs/dataset-v2/2026-10-09-v1-preservation.json").read_text(encoding="utf-8"))
    manifest=json.loads((ROOT/"artifacts/dataset-v2/main/manifest.json").read_text(encoding="utf-8"))
    with GraphDatabase.driver(config.NEO4J_URI,auth=(config.NEO4J_USERNAME,config.NEO4J_PASSWORD)) as driver:
        destination=ROOT/"artifacts/dataset-v2/v1-final-product"
        if destination.exists():
            destination=destination.with_name(destination.name+"-"+__import__('uuid').uuid4().hex[:8])
        v1=snapshot(driver,config.SHIPMENT_DATABASE,destination)
        assert v1["hashes"]==original["hashes"] and v1["indexes"]==original["indexes"]
        with driver.session(database="shipments-v2-demo",default_access_mode="READ") as s:
            def rows(q):return [json_value(dict(r)) for r in s.run(q,dataset=manifest["config"]["dataset_id"])]
            nodes=rows("MATCH(n:V2Entity {dataset_id:$dataset}) RETURN count(n) AS count")[0]["count"]
            edges=rows("MATCH(a:V2Entity {dataset_id:$dataset})-[r]->(b:V2Entity {dataset_id:$dataset}) RETURN count(r) AS count")[0]["count"]
            splits={r["split"]:r["count"] for r in rows("MATCH(s:V2Entity:Shipment {dataset_id:$dataset}) RETURN s.split AS split,count(s) AS count")}
            marker=rows("MATCH(m:_V2Import) RETURN m{.state,.manifest_hash,.dataset_id,.target_database} AS marker")[0]["marker"]
            invalid=rows("MATCH(o:OpsEntity) WHERE o.dataset_id<>$dataset OR o.split<>'development' OR (NOT o:OpsControl AND NOT EXISTS { MATCH(s:V2Entity:Shipment {entity_id:o.shipment_id,dataset_id:$dataset,split:'development'}) }) RETURN count(o) AS count")[0]["count"]
            duplicates=rows("MATCH(r:OpsEventReceipt {dataset_id:$dataset}) WITH r.source_event_id AS source,count(r) AS count WHERE count>1 RETURN source,count")
            control=rows("MATCH(c:OpsControl {dataset_id:$dataset}) RETURN c.as_of AS as_of,c.worker_state AS worker_state,c.simulator_state AS simulator_state,c.worker_claim AS active_claim,c.event_count AS event_count,c.processed_count AS processed_count")[0]
            receipts=rows("MATCH(r:OpsEventReceipt {dataset_id:$dataset}) RETURN count(r) AS count")[0]["count"]
            claims=rows("MATCH(c:OpsCase {dataset_id:$dataset,workflow_state:'INVESTIGATING'}) RETURN count(c) AS count")[0]["count"]
            resolved_invalid=rows("MATCH(c:OpsCase {dataset_id:$dataset,workflow_state:'RESOLVED'}) WHERE NOT EXISTS { MATCH(o:OpsOutcome {case_id:c.entity_id,verification_status:'VERIFIED',invalidated:false,success:true}) MATCH(e:OpsExecution {entity_id:o.execution_id,case_id:c.entity_id}) } RETURN count(c) AS count")[0]["count"]
            notifications=rows("MATCH(n:OpsNotification {dataset_id:$dataset}) RETURN count(n) AS count,sum(n.external_calls) AS external_calls,collect(DISTINCT n.mode) AS modes")[0]
            indexes=rows("SHOW INDEXES YIELD name,state,type RETURN name,state,type ORDER BY name")
            case_counts={r["state"]:r["count"] for r in rows("MATCH(c:OpsCase {dataset_id:$dataset}) RETURN c.workflow_state AS state,count(c) AS count")}
        assert nodes==198454 and edges==456026 and splits=={"history":1200,"development":400,"held_out":400}
        assert marker["state"]=="COMPLETE" and not invalid and not duplicates and not resolved_invalid
        assert not claims and not control["active_claim"] and control["worker_state"]==control["simulator_state"]=="paused"
        assert receipts==control["event_count"] and notifications["external_calls"]==0
        assert all(r["state"]=="ONLINE" for r in indexes)
    report={"status":"PASS","read_only":True,"v1_exactly_preserved":True,"v1":v1,
            "v2":{"entities":nodes,"relationships":edges,"shipment_splits":splits,"marker":marker,"indexes":indexes},
            "operations":{"invalid_namespace_records":invalid,"duplicate_event_receipts":duplicates,"claims":claims,
                "resolved_without_verified_outcome":resolved_invalid,"control":control,"receipts":receipts,"notifications":notifications,"case_counts":case_counts}}
    (ROOT/"docs/agent-runs/2026-10-09-final-graph-audit.json").write_text(canonical(report)+"\n",encoding="utf-8")
    print(canonical({"status":"PASS","v1_exactly_preserved":True,"v2_shipments":sum(splits.values()),"case_counts":case_counts,"external_calls":0}))


if __name__=="__main__":main()
